"""跨平台二进制解析。

解析顺序：环境变量 CHALKPRESS_FFMPEG（兼容旧 V2P2_FFMPEG）→ 系统 PATH → imageio-ffmpeg 自带静态 ffmpeg。
imageio-ffmpeg 在 Windows/macOS/Linux 均提供轮子，PyInstaller 打包时可一并冻结，
保证最终可执行程序不依赖用户安装 ffmpeg。
"""
from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def ffmpeg() -> str:
    override = os.getenv("CHALKPRESS_FFMPEG") or os.getenv("V2P2_FFMPEG")
    if override and Path(override).is_file():
        return override
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "未找到 ffmpeg：请安装系统 ffmpeg，或 pip install imageio-ffmpeg"
        ) from exc
