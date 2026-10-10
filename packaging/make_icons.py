"""生成 Chalkpress 应用图标（与 Tauri 应用图标同源的设计：黑板绿 + 讲义页 + 播放三角）。

用法：python packaging/make_icons.py
产物：packaging/icon_1024.png、packaging/icon.ico；macOS 上另出 packaging/icon.icns。
"""
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw

GREEN = (47, 93, 80, 255)       # #2F5D50 黑板绿
CREAM = (246, 243, 231, 255)    # #F6F3E7 讲义页
FOLD = (190, 207, 199, 255)     # #BECFC7 折角

# 36 单位坐标空间（Tauri 应用图标同源设计）
PAGE = [(11.5, 7), (20.5, 7), (26.5, 13), (26.5, 28.5), (24.7, 30.3),
        (11.5, 30.3), (9.7, 28.5), (9.7, 8.8)]
FOLD_PTS = [(20.5, 7), (26.5, 13), (21.9, 13), (20.5, 11.6)]
PLAY = [(15.2, 15.5), (23, 19.5), (15.2, 23.5)]


def render(size: int) -> Image.Image:
    ss = 4  # 超采样抗锯齿
    img = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = size * ss / 36.0
    s = lambda pts: [(x * k, y * k) for x, y in pts]
    d.rounded_rectangle([0, 0, size * ss - 1, size * ss - 1],
                        radius=9 * k, fill=GREEN)
    d.polygon(s(PAGE), fill=CREAM)
    d.polygon(s(FOLD_PTS), fill=FOLD)
    d.polygon(s(PLAY), fill=GREEN)
    return img.resize((size, size), Image.LANCZOS)


def main():
    here = Path(__file__).parent
    img = render(1024)
    img.save(here / "icon_1024.png")
    img.save(here / "icon.ico", sizes=[(256, 256), (128, 128), (64, 64),
                                       (48, 48), (32, 32), (16, 16)])
    if sys.platform == "darwin":
        iconset = here / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        for n in (16, 32, 64, 128, 256, 512, 1024):
            render(n).save(iconset / f"icon_{n}x{n}.png")
            render(n * 2).save(iconset / f"icon_{n}x{n}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset),
                        "-o", str(here / "icon.icns")], check=True)
    print("icons written to", here)


if __name__ == "__main__":
    main()
