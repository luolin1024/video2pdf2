"""命令行入口。不带参数或想图形界面请用 v2p2-gui（同 core 流水线）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .pipeline import Options, run_batch

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".ts"}


def expand_videos(paths: list[Path]) -> list[Path]:
    """目录 → 展开其中全部视频文件；文件原样保留。"""
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out += sorted(x for x in p.iterdir() if x.suffix.lower() in VIDEO_EXTS)
        else:
            out.append(p)
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="v2p2", description="mp4（批量）→ 关键帧 PDF + 关键字幕 + LLM 分析总结")
    p.add_argument("video", type=Path, nargs="+",
                   help="输入视频或目录（目录会展开其中全部视频），可传多个")
    p.add_argument("-o", "--outdir", type=Path, default=None,
                   help="输出目录（默认逐视频 <视频名>_v2p2/；批量时为 <outdir>/<视频名>/）")
    p.add_argument("--scene-threshold", type=float, default=None,
                   help="场景切换阈值，越小越敏感（默认 0.08）")
    p.add_argument("--min-gap", type=float, default=None, help="关键帧最小间隔秒（默认 2.0）")
    p.add_argument("--asr-backend", choices=["faster-whisper", "mlx-whisper"], default=None,
                   help="转写后端；mlx-whisper 仅限 macOS（默认 faster-whisper，全平台）")
    p.add_argument("--asr-model", default=None,
                   help="whisper 模型 tiny/base/small/medium 或 HF repo（默认 small）")
    p.add_argument("--language", default=None,
                   help="语音语言：auto/zh/en/…（whisper 支持 90+ 语种，默认 auto）")
    p.add_argument("--summary-lang", default=None,
                   help="分析与 PDF 输出语言：zh / zh-en / en（默认 zh）")
    p.add_argument("--zh-script", choices=["auto", "simplified", "traditional"], default=None,
                   help="中文字幕简繁：auto=按系统 locale（默认）")
    p.add_argument("--no-correct", dest="auto_correct", action="store_false", default=None,
                   help="关闭 LLM 字幕校对（默认开启，需已配置 LLM）")
    p.add_argument("--reuse-srt", type=Path, default=None, help="复用已有 SRT，跳过转写")
    p.add_argument("--skip-analysis", action="store_true", help="跳过 LLM 分析")
    p.add_argument("--skip-pdf", action="store_true", help="跳过 PDF 生成")
    p.add_argument("--api-base", default=None,
                   help="OpenAI 兼容 API 地址（优先级：参数 > 环境变量 V2P2_API_BASE > 配置文件）")
    p.add_argument("--api-key", default=None, help="API Key（默认环境变量 V2P2_API_KEY）")
    p.add_argument("--llm-model", default=None, help="视觉模型名（默认环境变量 V2P2_LLM_MODEL）")
    p.add_argument("--keep-wav", action="store_true", help="保留中间 wav 文件")
    p.add_argument("--version", action="version", version=f"v2p2 {__version__}")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    videos = expand_videos(args.video)
    if not videos:
        print("错误：没有找到可处理的视频文件", file=sys.stderr)
        return 1
    print(f"共 {len(videos)} 个视频待处理")
    try:
        results = run_batch(Options(
            video=videos[0], outdir=args.outdir,
            scene_threshold=args.scene_threshold, min_gap=args.min_gap,
            asr_backend=args.asr_backend, asr_model=args.asr_model,
            language=args.language, summary_lang=args.summary_lang,
            zh_script=args.zh_script, auto_correct=args.auto_correct,
            reuse_srt=args.reuse_srt, skip_analysis=args.skip_analysis,
            skip_pdf=args.skip_pdf, api_base=args.api_base,
            api_key=args.api_key, llm_model=args.llm_model, keep_wav=args.keep_wav,
        ), videos)
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    for r in results:
        if isinstance(r, Exception):
            continue
        print(f"── {r.outdir.name}")
        print(f"   PDF  : {r.pdf_path or '-'}")
        print(f"   字幕 : {r.srt or '-'}")
        print(f"   对照 : {r.aligned_path or '-'}")
        print(f"   总结 : {r.summary_path or '-'}")
    return 0 if all(not isinstance(r, Exception) for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
