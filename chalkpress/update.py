"""GitHub Releases 检查更新与安装包下载。

版本来源：仓库 Releases 列表第一条非 draft（滚动 latest 优先，其次 v* tag）。
资产匹配规则（文件名包含）：
- darwin  → "macos"，优先 .dmg
- win32   → "windows"，优先 "setup"（Inno 安装包）
- linux   → "linux"，.tar.gz
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = "luolin1024/video2pdf2"
_API = f"https://api.github.com/repos/{REPO}/releases?per_page=5"


def parse_version(v: str) -> tuple[int, ...]:
    """'v0.2.1' → (0, 2, 1)；解析失败回退 (0,)。"""
    m = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in m[:3]) if m else (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def fetch_latest(timeout: float = 10.0) -> dict | None:
    """返回 {"version", "prerelease", "assets": [{"name","url","size"}], "html_url"} 或 None。"""
    import requests

    r = requests.get(
        _API, timeout=timeout,
        headers={"Accept": "application/vnd.github+json"},
    )
    r.raise_for_status()
    for rel in r.json():
        if rel.get("draft"):
            continue
        assets = [
            {"name": a["name"], "url": a["browser_download_url"], "size": a["size"]}
            for a in rel.get("assets", [])
        ]
        return {
            "version": (rel.get("tag_name") or "").lstrip("vV"),
            "prerelease": bool(rel.get("prerelease")),
            "assets": assets,
            "html_url": rel.get("html_url", f"https://github.com/{REPO}/releases"),
        }
    return None


def pick_asset(assets: list[dict]) -> dict | None:
    """按当前平台挑最合适的安装资产。"""
    if sys.platform == "darwin":
        pool = [a for a in assets if "macos" in a["name"].lower()]
        prefer = (".dmg", ".zip")
    elif sys.platform == "win32":
        pool = [a for a in assets if "windows" in a["name"].lower()]
        prefer = ("setup", ".exe", ".zip")
    else:
        pool = [a for a in assets if "linux" in a["name"].lower()]
        prefer = (".tar.gz",)
    for key in prefer:
        for a in pool:
            if key in a["name"].lower():
                return a
    return pool[0] if pool else None


def download(url: str, dest_dir: Path, progress=None) -> Path:
    """流式下载到 dest_dir；progress(received, total) 可选回调。"""
    import requests

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / url.rsplit("/", 1)[-1]
    with requests.get(url, stream=True, timeout=30, allow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done, total)
    return dest


def reveal(path: Path) -> None:
    """在文件管理器中显示下载好的文件。"""
    path = Path(path)
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])
