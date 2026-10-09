"""PyInstaller 打包入口。

- `chalkpress --cli <视频...>`：headless 命令行批量模式；
- `chalkpress <视频...>`：打开 GUI 并预载文件列表（支持拖拽到应用图标）；
- `chalkpress`：打开空 GUI。
"""
import os
import sys
from pathlib import Path


def _preempt_tqdm_mp_lock():
    """tqdm 默认写锁会经 fork_exec 拉起 multiprocessing.resource_tracker，
    在冻结应用里成为孤儿并占住继承的管道。提前换成线程锁阻断该路径。"""
    try:
        import threading

        import tqdm

        tqdm.tqdm.set_lock(threading.RLock())
    except Exception:
        pass


def _frozen_cli_exit(rc: int):
    """冻结环境退出：非守护线程会卡住解释器退出，resource_tracker 会占用
    继承的管道导致管道对端永远等不到 EOF。清理后硬退出。"""
    sys.stdout.flush()
    sys.stderr.flush()
    if getattr(sys, "frozen", False):
        try:
            import signal
            from multiprocessing import resource_tracker as _rtmod

            tracker = getattr(_rtmod, "_resource_tracker", None)
            pid = getattr(tracker, "_pid", None) if tracker else None
            if pid and pid > 0:
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        os._exit(rc)
    raise SystemExit(rc)


def main():
    _preempt_tqdm_mp_lock()
    args = sys.argv[1:]
    if "--cli" in args:
        from chalkpress.cli import main as cli_main

        _frozen_cli_exit(cli_main([a for a in args if a != "--cli"]))
    if args:
        import chalkpress.gui as gui

        # 只预载真实存在的视频文件（防御 LaunchServices/argv 传参噪声）
        gui.PRELOAD_FILES = [
            p for a in args
            for p in [Path(a).expanduser()]
            if p.suffix.lower() in gui.VIDEO_EXTS and p.is_file()
        ]

    from chalkpress.gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
