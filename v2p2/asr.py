"""语音转字幕：抽音轨 → 本地 whisper 转写 → 带时间戳段落/SRT。

后端：
- faster-whisper（默认）：CTranslate2 int8 CPU 推理，Windows/macOS/Linux 通用；
- mlx-whisper：Apple Silicon 加速，仅在 macOS 可选。
whisper 原生支持 90+ 语种，--language 传任何 whisper 语言码即可扩展。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .binaries import ffmpeg

_MLX_REPO = "mlx-community/whisper-{}-mlx"


def extract_audio(video: Path, wav: Path) -> Path:
    subprocess.run(
        [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(wav)],
        check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return wav


def wav_duration(wav: Path) -> float:
    """用 wave 模块读精确时长，避免依赖 ffprobe（imageio-ffmpeg 不带 ffprobe）。"""
    import wave

    with wave.open(str(wav), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 1)


def transcribe(wav: Path, model_size="small", backend="faster-whisper", language=None):
    """返回 [{start, end, text}]；language=None 时由 whisper 自动检测。"""
    if backend == "mlx-whisper":
        if sys.platform != "darwin":
            raise RuntimeError("mlx-whisper 后端仅支持 macOS")
        return _mlx(wav, model_size, language)
    return _faster(wav, model_size, language)


def resolve_model(model_size: str) -> str:
    """打包环境优先使用内置模型目录；开发环境用 HF id（首次自动下载）。"""
    if os.path.isdir(model_size):
        return model_size
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and model_size == "small":
        bundled = Path(meipass) / "models" / "faster-whisper-small"
        if bundled.is_dir():
            return str(bundled)
    return model_size


def _faster(wav: Path, model_size: str, language):
    """绕开 PyAV 兼容性问题：wave 解码 → float32 数组直接送 transcribe。

    faster-whisper 原生支持 numpy 输入（mono float32 @16k），不再调用
    decode_audio 的 av.open(metadata_errors=...)（新版 PyAV 已移除该参数）。
    """
    _ensure_hf_reachable()
    import wave

    import numpy as np
    from faster_whisper import WhisperModel

    model = WhisperModel(resolve_model(model_size), device="cpu", compute_type="int8")
    with wave.open(str(wav), "rb") as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = audio.astype(np.float32) / 32768.0
    kwargs = {"vad_filter": True, "beam_size": 5}
    if language:
        kwargs["language"] = language
        if language == "zh":
            # 引导 whisper 输出简体中文并贴近领域词汇
            kwargs["initial_prompt"] = "以下是普通话简体中文的课程讲解，涉及计算机、软件考试术语。"
    segments, _info = model.transcribe(audio, **kwargs)
    return [
        {"start": s.start, "end": s.end, "text": s.text.strip()}
        for s in segments
        if s.text.strip()
    ]


def _mlx(wav: Path, model_size: str, language):
    import mlx_whisper

    repo = model_size if "/" in model_size else _MLX_REPO.format(model_size)
    kwargs = {"path_or_hf_repo": repo, "verbose": False}
    if language:
        kwargs["language"] = language
    result = mlx_whisper.transcribe(str(wav), **kwargs)
    return [
        {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
        for s in result.get("segments", [])
        if s.get("text", "").strip()
    ]


def _ensure_hf_reachable():
    """huggingface.co 不可达时自动切国内镜像（必须在导入 huggingface_hub 前设置）。"""
    if os.getenv("HF_ENDPOINT"):
        return
    import socket

    try:
        socket.create_connection(("huggingface.co", 443), timeout=3).close()
    except OSError:
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"


def write_srt(segments, path: Path) -> Path:
    lines = []
    for i, s in enumerate(segments, 1):
        lines += [str(i), f"{_ts(s['start'])} --> {_ts(s['end'])}", s["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
