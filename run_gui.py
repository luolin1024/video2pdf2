"""PyInstaller 打包入口。

- `v2p2 --cli <视频...>`：headless 命令行批量模式；
- `v2p2 <视频...>`：打开 GUI 并预载文件列表（支持拖拽到应用图标）；
- `v2p2`：打开空 GUI。
"""
import sys
from pathlib import Path


def main():
    args = sys.argv[1:]
    if "--cli" in args:
        from v2p2.cli import main as cli_main

        raise SystemExit(cli_main([a for a in args if a != "--cli"]))
    if args:
        import v2p2.gui as gui

        gui.PRELOAD_FILES = [Path(a).expanduser().resolve() for a in args]
    from v2p2.gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
