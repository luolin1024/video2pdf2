# chalkpress/ipc.py
"""stdio 行 JSON IPC 服务：Tauri sidecar 入口（开发期可直接 python -m chalkpress.ipc 调试）。"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from pathlib import Path

from .config import (
    load_config_file,
    load_llm_config,
    logs_dir,
    normalize_settings,
    save_config_file,
)
from .pipeline import Options, run_batch

log = logging.getLogger("chalkpress.ipc")


def sanitize_progress(ev: str, kw: dict) -> tuple[str, dict]:
    """pipeline 的 progress 事件 → 可 JSON 序列化的 IPC 事件。

    video_done 事件携带 Result 数据类（含 Path/列表），展平为 pages/summary/outdir。
    """
    if "result" in kw:
        r = kw.pop("result")
        kw["pages"] = len(getattr(r, "frames", None) or [])
        kw["summary"] = bool(getattr(r, "summary_md", None))
        kw["outdir"] = str(getattr(r, "outdir", None) or "")
    return ev, kw


class IPCServer:
    def __init__(self, stdin=None, stdout=None):
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self._wlock = threading.Lock()
        self._fh = None

    # ---------- 输出 ----------
    def send(self, obj: dict):
        with self._wlock:
            self.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.stdout.flush()

    # ---------- 请求处理 ----------
    def handle(self, req: dict) -> dict:
        rid = req.get("id")
        try:
            result = self.dispatch(req.get("method"), req.get("params") or {})
        except Exception as exc:
            log.exception("handle %s failed", req.get("method"))
            return {"id": rid, "error": str(exc)}
        return {"id": rid, "result": result}

    def dispatch(self, method: str, params: dict):
        if method == "settings.get":
            cfg = load_config_file()
            return {"options": cfg.get("options", {}),
                    "app": cfg.get("app", {}),
                    "llm": cfg.get("llm", {}),
                    "llm_configured": load_llm_config() is not None,
                    "logs_dir": str(logs_dir())}
        if method == "settings.set":
            save_config_file(normalize_settings(params))
            return {}
        if method == "convert.start":
            self._start(params)
            return {}
        if method == "convert.cancel":
            self.cancel.set()
            return {}
        if method == "fs.list_videos":
            d = Path(params["dir"]).expanduser()
            return {"videos": sorted(str(p) for p in d.iterdir()
                                     if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm",
                                                             ".avi", ".m4v", ".flv", ".ts"})}
        raise KeyError(f"unknown method: {method}")

    # ---------- 转换 ----------
    def _start(self, params: dict):
        if self.worker and self.worker.is_alive():
            raise RuntimeError("转换进行中")
        self.cancel.clear()
        o = params.get("options", {})
        keep_log = bool((params.get("app") or {}).get("keep_log", True))
        opt = Options(
            video=Path(params["videos"][0]) if params.get("videos") else Path(),
            scene_threshold=o.get("scene_threshold"),
            min_gap=o.get("min_gap"),
            language="auto",
            summary_lang=o.get("summary_lang", "zh"),
            zh_script=o.get("zh_script", "auto"),
            auto_correct=o.get("auto_correct", True),
            asr_model=o.get("asr_model"),
            api_base=o.get("api_base"),
            api_key=o.get("api_key"),
            llm_model=o.get("llm_model"),
            skip_analysis=not load_llm_config(o.get("api_base"), o.get("api_key"),
                                              o.get("llm_model")),
        )
        videos = [Path(v) for v in params.get("videos", [])]
        self._open_logfile(keep_log)

        def progress(ev, **kw):
            ev, kw = sanitize_progress(ev, kw)
            self.send({"event": ev, **kw})

        def work():
            try:
                run_batch(opt, videos, log=self._log,
                          cancel_check=self.cancel.is_set, progress=progress)
            except Exception as exc:
                log.exception("run_batch failed")
                self.send({"event": "batch_error", "error": str(exc)})
            finally:
                self._close_logfile()

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _open_logfile(self, keep_log: bool):
        if not keep_log:
            return
        try:
            d = logs_dir()
            d.mkdir(parents=True, exist_ok=True)
            self._fh = open(d / f"chalkpress-{time.strftime('%Y%m%d-%H%M%S')}.log",
                            "a", encoding="utf-8")
        except OSError:
            self._fh = None

    def _log(self, text: str):
        if self._fh:
            try:
                self._fh.write(text + "\n")
                self._fh.flush()
            except OSError:
                pass

    def _close_logfile(self):
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    # ---------- 主循环 ----------
    def serve(self):
        for line in self.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                log.warning("丢弃非 JSON 行: %.80s", line)  # stdin 非 JSON 行容错；stdout 污染由 main() 的 sys.stdout 重定向防护
                continue
            self.send(self.handle(req))


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    protocol_out = sys.stdout   # 协议通道固定为真实 stdout
    sys.stdout = sys.stderr     # 第三方 Python 级 print() → stderr
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
    IPCServer(stdout=protocol_out).serve()


if __name__ == "__main__":
    main()
