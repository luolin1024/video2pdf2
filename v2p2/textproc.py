"""简繁转换与文本后处理。

zh_script=auto 时按系统 locale 判定（zh_TW/zh_HK/zh_MO/Hant → 繁体，否则简体）。
"""
from __future__ import annotations

import os

_OPENCC_CACHE: dict = {}


def _opencc(direction: str):
    cc = _OPENCC_CACHE.get(direction)
    if cc is None:
        from opencc import OpenCC

        cc = _OPENCC_CACHE[direction] = OpenCC(direction)
    return cc


def detect_zh_script() -> str:
    for src in (os.getenv("LC_ALL"), os.getenv("LC_CTYPE"), os.getenv("LANG")):
        if src:
            s = src.lower().replace("-", "_")
            if s.startswith("zh"):
                if any(t in s for t in ("tw", "hk", "mo", "hant")):
                    return "traditional"
                return "simplified"
    return "simplified"


def resolve_zh_script(mode: str | None) -> str:
    mode = (mode or "auto").lower()
    if mode in ("simplified", "traditional"):
        return mode
    return detect_zh_script()


def convert(text: str, script: str) -> str:
    """按目标简繁转换；非 CJK 文本原样通过。"""
    return _opencc("s2t" if script == "traditional" else "t2s").convert(text)
