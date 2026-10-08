"""关键帧：ffmpeg 场景检测 → 段首/段末取样 → 平均哈希去重。

策略（针对课件/讲解类视频）：
- 每个场景段取“段起始状态”与“段末状态”两帧，覆盖页面上逐步出现的高亮/标注；
- 始终保留结尾帧；
- 相邻帧平均哈希距离过近则丢弃，避免重复画面。
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .binaries import ffmpeg


@dataclass
class KeyFrame:
    ts: float
    path: Path


def parse_duration_ffmpeg(video: Path) -> float:
    """无 ffprobe 依赖：从 `ffmpeg -i` 的 stderr 解析 Duration。"""
    proc = subprocess.run(
        [ffmpeg(), "-hide_banner", "-i", str(video), "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not m:
        raise RuntimeError(f"无法解析视频时长：{video}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def detect_cuts(video: Path, threshold: float) -> list[float]:
    """返回场景切换时间点（秒）。低阈值对高亮渐变更敏感。"""
    proc = subprocess.run(
        [ffmpeg(), "-hide_banner", "-nostats", "-an", "-i", str(video),
         "-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return [float(x) for x in re.findall(r"pts_time:(\d+(?:\.\d+)?)", proc.stderr)]


def plan_frame_times(video: Path, duration: float, threshold: float, min_gap: float) -> list[float]:
    cuts = [c for c in detect_cuts(video, threshold) if 0.5 < c < duration - 0.5]
    bounds = [0.0] + cuts + [duration]
    times = set()
    for a, b in zip(bounds, bounds[1:]):
        if b - a < 1.0:
            continue
        times.add(min(a + 0.3, b - 0.2))      # 段起始状态
        if b - a >= 4.0:
            times.add(b - 0.5)                # 段末状态
    times.add(max(duration - 0.3, 0.0))       # 结尾状态
    ordered = sorted(t for t in times if 0 <= t < duration)
    kept: list[float] = []
    for t in ordered:
        if not kept or t - kept[-1] >= min_gap:
            kept.append(t)
    return kept


def _ahash(path: Path, size: int = 16) -> list[int]:
    img = Image.open(path).convert("L").resize((size, size), Image.LANCZOS)
    px = list(img.getdata())
    avg = sum(px) / len(px)
    return [1 if p >= avg else 0 for p in px]


def _hamming(a: list[int], b: list[int]) -> int:
    return sum(x != y for x, y in zip(a, b))


def extract_frames(video: Path, times, frames_dir: Path, dup_bits: int = 12) -> list[KeyFrame]:
    """逐个抽全分辨率 JPEG；与上一保留帧哈希距离 ≤ dup_bits 视为重复丢弃。"""
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[KeyFrame] = []
    last_hash = None
    for ts in times:
        path = frames_dir / f"{len(frames):02d}_{_stamp(ts)}.jpg"
        subprocess.run(
            [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
             "-ss", f"{ts:.3f}", "-i", str(video),
             "-frames:v", "1", "-q:v", "2", str(path)],
            check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        h = _ahash(path)
        if last_hash is not None and _hamming(h, last_hash) <= dup_bits:
            path.unlink()
            continue
        last_hash = h
        frames.append(KeyFrame(ts=ts, path=path))
    return frames


def _stamp(ts: float) -> str:
    return f"{int(ts // 60):02d}m{int(ts % 60):02d}s"
