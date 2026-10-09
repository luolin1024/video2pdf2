"""SRT 解析与 字幕↔关键帧 对齐。"""
from __future__ import annotations

import re
from pathlib import Path


def parse_srt(path: Path) -> list[dict]:
    """宽容解析 SRT（兼容 BOM/CRLF/多行 cue），返回按开始时间排序的段落。"""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    segments = []
    for block in re.split(r"\n\s*\n", text.strip()):
        rows = [r for r in block.splitlines() if r.strip()]
        ti = next((i for i, r in enumerate(rows) if "-->" in r), None)
        if ti is None:
            continue
        a, z = rows[ti].split("-->")
        body = " ".join(x.strip() for x in rows[ti + 1:]).strip()
        if body:
            segments.append({"start": _sec(a), "end": _sec(z), "text": body})
    segments.sort(key=lambda s: s["start"])
    return segments


def _sec(stamp: str) -> float:
    stamp = stamp.strip()
    h, m, rest = stamp.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))


def align(segments, frame_ts: list[float]) -> list[dict]:
    """字幕按中点归入所在关键帧时间窗 (prev_ts, ts]，避免跨窗重复。"""
    out = []
    for i, ts in enumerate(frame_ts):
        a = frame_ts[i - 1] if i else 0.0
        subs = [s for s in segments if a <= (s["start"] + s["end"]) / 2 < ts]
        out.append({"start": a, "end": ts, "subs": subs})
    return out


def window_markdown(aligned, frames) -> str:
    """关键字幕 × 关键帧 对照表（Markdown）。"""
    lines = ["## 关键字幕 × 关键帧对照", ""]
    for i, (kf, seg) in enumerate(zip(frames, aligned), 1):
        lines.append(
            f"### [{i:02d}] {_mmss(seg['start'])} – {_mmss(seg['end'])}  `{kf.path.name}`"
        )
        if seg["subs"]:
            lines += [f"- [{_mmss(s['start'])}] {s['text']}" for s in seg["subs"]]
        else:
            lines.append("-（此时间窗内无字幕）")
        lines.append("")
    return "\n".join(lines)


def _mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"
