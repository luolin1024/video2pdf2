"""核心流水线：Options → run()/run_batch() → Result。

CLI 与 GUI 都是薄壳，共用本模块；选项解析顺序：显式传入 > 配置文件 > 内置默认。
处理链：ASR → LLM 字幕校对（可选）→ 简繁规范（OpenCC）→ 关键帧 → 对齐 → LLM 总结（可选）→ PDF。
"""
from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass
from pathlib import Path

from . import align, analyze, asr, correct, keyframes, pdf, textproc
from .config import lang_pack, load_config_file, load_llm_config


@dataclass
class Options:
    video: Path
    outdir: Path | None = None
    scene_threshold: float | None = None  # None → 配置文件 → 0.08
    min_gap: float | None = None          # None → 配置文件 → 2.0
    asr_backend: str | None = None        # None → 配置文件 → faster-whisper
    asr_model: str | None = None          # None → 配置文件 → small
    language: str | None = None           # None → 配置文件 → auto
    zh_script: str | None = None          # None → 配置文件 → auto（按系统 locale）
    auto_correct: bool | None = None      # None → 配置文件 → True（LLM 字幕校对）
    reuse_srt: Path | None = None
    summary_lang: str | None = None       # None → 配置文件 → zh
    skip_analysis: bool = False
    skip_pdf: bool = False
    api_base: str | None = None
    api_key: str | None = None
    llm_model: str | None = None
    keep_wav: bool = False


_FILE_OPTION_DEFAULTS = {
    "scene_threshold": 0.08,
    "min_gap": 2.0,
    "asr_backend": "faster-whisper",
    "asr_model": "small",
    "language": "auto",
    "zh_script": "auto",
    "auto_correct": True,
    "summary_lang": "zh",
}


def resolve_options(opt: Options) -> Options:
    """None 字段回退：配置文件 [options] → 内置默认（显式传入值优先）。"""
    file_cfg = load_config_file().get("options", {})
    updates = {}
    for k, d in _FILE_OPTION_DEFAULTS.items():
        val = getattr(opt, k)
        if val is None:
            updates[k] = file_cfg.get(k, d)
    return dataclasses.replace(opt, **updates)


@dataclass
class Result:
    outdir: Path
    srt: Path | None
    frames: list
    aligned: list
    summary_md: str | None
    summary_path: Path | None
    aligned_path: Path | None
    pdf_path: Path | None
    seconds: float


def _emitter(progress):
    """进度事件发射器：GUI 传入 progress 回调，CLI 忽略。"""
    def emit(event, **data):
        if progress:
            try:
                progress(event, **data)
            except Exception:
                pass
    return emit


def run(opt: Options, log=print, progress=None) -> Result:
    t0 = time.time()
    opt = resolve_options(opt)
    emit = _emitter(progress)
    video = opt.video.expanduser().resolve()
    if not video.is_file():
        raise FileNotFoundError(f"视频不存在：{video}")
    outdir = (opt.outdir or video.with_name(video.stem + "_讲义")).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    pack = lang_pack(opt.summary_lang)

    cfg = None
    if not opt.skip_analysis:
        cfg = load_llm_config(opt.api_base, opt.api_key, opt.llm_model)

    emit("stage", key="asr", name="语音转写")
    detected = opt.language or None
    if opt.reuse_srt:
        segments = align.parse_srt(opt.reuse_srt)
        log(f"[1/5] 复用字幕 {opt.reuse_srt}（{len(segments)} 条）")
    else:
        log(f"[1/5] 抽取音轨 → 本地转写（{opt.asr_backend}/{opt.asr_model}）…")
        asr.extract_audio(video, wav)
        lang = None if opt.language in ("auto", "") else opt.language
        segments, detected = asr.transcribe(wav, opt.asr_model, opt.asr_backend, lang)
        log(f"      {len(segments)} 条原始字幕（检测语言：{detected or '?'}）")
    emit("detected_lang", lang=detected)
    emit("stage_done", key="asr")
    if opt.auto_correct and cfg is not None and segments and detected == "zh":
        emit("stage", key="correct", name="字幕校对")
        log("      LLM 字幕校对（同音字/误听修正）…")
        try:
            fixed = correct.correct_transcript(segments, cfg)
            log(f"      修正 {fixed} 条")
        except Exception as exc:
            log(f"      校对失败，保留原文：{exc}")
        emit("stage_done", key="correct")
    script = textproc.resolve_zh_script(opt.zh_script)
    for s in segments:
        s["text"] = textproc.convert(s["text"], script)
    asr.write_srt(segments, srt_path)
    log(f"      {len(segments)} 条字幕（{script}）→ {srt_path.name}")
    duration = asr.wav_duration(wav) if wav.exists() else keyframes.parse_duration_ffmpeg(video)

    emit("stage", key="frames", name="关键帧对齐")
    log(f"[2/5] 场景检测（阈值 {opt.scene_threshold}）→ 抽帧 → 去重 …")
    times = keyframes.plan_frame_times(video, duration, opt.scene_threshold, opt.min_gap)
    frames = keyframes.extract_frames(video, times, outdir / "keyframes")
    log(f"      {len(times)} 个候选 → {len(frames)} 个关键帧")
    emit("frames", count=len(frames))

    log("[3/5] 字幕 × 关键帧 对齐 …")
    aligned = align.align(segments, [f.ts for f in frames])
    aligned_path = outdir / f"{video.stem}.aligned.md"
    aligned_path.write_text(align.window_markdown(aligned, frames), encoding="utf-8")
    emit("stage_done", key="frames")

    # 4) LLM 分析（未配置端点则降级跳过）
    summary_md = None
    if opt.skip_analysis:
        log("[4/5] 已指定跳过分析")
    elif cfg is None:
        log("[4/5] 未配置 LLM 端点（配置文件/环境变量 CHALKPRESS_*），跳过分析")
    else:
        emit("stage", key="summary", name="AI 总结")
        log(f"[4/5] LLM 分析（{cfg.model}，{len(frames)} 帧）…")
        summary_md = analyze.summarize(video.stem, duration, aligned, frames, cfg, pack)
        if summary_md and opt.summary_lang.startswith("zh"):
            summary_md = textproc.convert(summary_md, script)
        emit("stage_done", key="summary")
    summary_path = None
    if summary_md:
        summary_path = outdir / f"{video.stem}.summary.md"
        summary_path.write_text(summary_md, encoding="utf-8")

    if opt.skip_pdf:
        log("[5/5] 已指定跳过 PDF")
    else:
        emit("stage", key="pdf", name="生成 PDF")
        log("[5/5] 生成 PDF …")
        pdf_path = pdf.build_pdf(outdir / f"{video.stem}.pdf", video.stem,
                                 frames, aligned, summary_md, pack)
        emit("stage_done", key="pdf")

    if wav.exists() and not opt.keep_wav:
        wav.unlink()

    dt = time.time() - t0
    log(f"完成：{outdir}（{dt:.1f}s）")
    emit("video_done", result=Result(
        outdir=outdir, srt=srt_path if srt_path.exists() else None,
        frames=frames, aligned=aligned, summary_md=summary_md,
        summary_path=summary_path, aligned_path=aligned_path,
        pdf_path=pdf_path, seconds=dt))
    return Result(outdir=outdir, srt=srt_path if srt_path.exists() else None,
                  frames=frames, aligned=aligned, summary_md=summary_md,
                  summary_path=summary_path, aligned_path=aligned_path,
                  pdf_path=pdf_path, seconds=dt)


def run_batch(opt: Options, videos: list[Path], log=print, cancel_check=None,
              progress=None) -> list:
    """批量处理：逐个转换，单个失败不影响后续；cancel_check 在每个视频间检查。"""
    emit = _emitter(progress)
    results = []
    total = len(videos)
    for i, v in enumerate(videos, 1):
        if cancel_check and cancel_check():
            log(f"已停止：{total - i + 1} 个视频未处理")
            break
        v = v.expanduser().resolve()
        log(f"═══ [{i}/{total}] {v.name} ═══")
        emit("video_start", index=i, total=total, name=v.name)
        outdir = (opt.outdir / v.stem) if opt.outdir else None
        try:
            results.append(run(dataclasses.replace(opt, video=v, outdir=outdir),
                               log=log, progress=progress))
        except Exception as exc:  # 单个失败继续下一个
            log(f"✗ {v.name} 失败：{exc}")
            results.append(exc)
            emit("video_error", name=v.name, error=str(exc))
    ok = sum(1 for r in results if isinstance(r, Result))
    log(f"批量完成：成功 {ok}/{total}")
    emit("batch_done", ok=ok, total=total)
    return results
