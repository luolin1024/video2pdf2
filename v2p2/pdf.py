"""关键帧 + 字幕 + 总结 → 可检索 PDF（reportlab，A4 横版）。

跨平台字体解析链：V2P2_FONT → 项目 fonts/ → 平台系统 CJK 字体 → reportlab CID 兜底，
保证 Windows/macOS/Linux 中文渲染不缺字。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer

from .align import _mmss
from .config import LangPack

_FONT_CANDIDATES = {
    "win32": [
        "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",    # 黑体
        "C:/Windows/Fonts/simsun.ttc",    # 宋体
    ],
    "darwin": [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ],
    "linux": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ],
}


def register_cjk_font() -> str:
    candidates: list[Path] = []
    env_font = os.getenv("V2P2_FONT")
    if env_font:
        candidates.append(Path(env_font))
    bundled = Path(__file__).resolve().parent / "fonts"
    if bundled.is_dir():
        candidates += sorted(bundled.glob("*.ttf")) + sorted(bundled.glob("*.ttc"))
    candidates += [Path(p) for p in _FONT_CANDIDATES.get(sys.platform, [])]
    for c in candidates:
        try:
            if not c.is_file():
                continue
            if c.suffix.lower() == ".ttc":
                pdfmetrics.registerFont(TTFont("V2P2CJK", str(c), subfontIndex=0))
            else:
                pdfmetrics.registerFont(TTFont("V2P2CJK", str(c)))
            return "V2P2CJK"
        except Exception:
            continue
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_flow(md: str, styles: dict) -> list:
    """极简 Markdown → flowables（标题/列表/正文，忽略行内样式）。"""
    flow = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flow.append(Spacer(1, 4))
            continue
        clean = _esc(line.replace("**", "").replace("`", ""))
        if line.startswith("### "):
            flow.append(Paragraph(clean[4:], styles["h3"]))
        elif line.startswith("## ") or line.startswith("# "):
            flow.append(Paragraph(clean.lstrip("# "), styles["h2"]))
        elif line.lstrip().startswith(("- ", "* ")):
            flow.append(Paragraph("• " + clean.lstrip()[2:], styles["body"]))
        else:
            flow.append(Paragraph(clean, styles["body"]))
    return flow


def build_pdf(out_path: Path, title: str, frames, aligned, summary_md: str | None,
              pack: LangPack) -> Path:
    font = register_cjk_font()
    styles = {
        "title": ParagraphStyle("title", fontName=font, fontSize=20, leading=26, spaceAfter=4),
        "h2": ParagraphStyle("h2", fontName=font, fontSize=14, leading=20,
                             spaceBefore=10, spaceAfter=4),
        "h3": ParagraphStyle("h3", fontName=font, fontSize=11.5, leading=16,
                             spaceBefore=8, spaceAfter=3),
        "body": ParagraphStyle("body", fontName=font, fontSize=10.5, leading=15),
        "small": ParagraphStyle("small", fontName=font, fontSize=9, leading=13),
        "sub": ParagraphStyle("sub", fontName=font, fontSize=10, leading=14, leftIndent=10),
    }
    page = landscape(A4)
    margin_x, margin_y = 14 * mm, 12 * mm
    doc = SimpleDocTemplate(str(out_path), pagesize=page,
                            leftMargin=margin_x, rightMargin=margin_x,
                            topMargin=margin_y, bottomMargin=margin_y, title=title)
    usable_w = page[0] - 2 * margin_x

    story: list = [Paragraph(_esc(title), styles["title"]),
                   Paragraph(_esc(pack.pdf_footer), styles["small"]), Spacer(1, 6)]
    if summary_md:
        story += _md_flow(summary_md, styles)
        story.append(PageBreak())

    for i, (kf, seg) in enumerate(zip(frames, aligned), 1):
        story.append(Paragraph(
            f"{_esc(pack.pdf_keyframe)} {i:02d} · {_mmss(kf.ts)}"
            f"（{_esc(pack.pdf_window)} {_mmss(seg['start'])}–{_mmss(seg['end'])}）",
            styles["h2"]))
        with PILImage.open(kf.path) as im:
            w, h = im.size
        draw_w, draw_h = usable_w, usable_w * h / w
        if draw_h > 120 * mm:
            draw_h = 120 * mm
            draw_w = draw_h * w / h
        story.append(Image(str(kf.path), width=draw_w, height=draw_h))
        story.append(Spacer(1, 4))
        story.append(Paragraph(_esc(pack.pdf_subtitle), styles["h3"]))
        if seg["subs"]:
            for s in seg["subs"]:
                story.append(Paragraph(f"[{_mmss(s['start'])}] {_esc(s['text'])}", styles["sub"]))
        else:
            story.append(Paragraph("—", styles["sub"]))
        story.append(PageBreak())

    doc.build(story)
    return out_path
