"""video2pdf2 GUI（tkinter，零额外 GUI 依赖，跨平台，可被 PyInstaller 打包）。

设计原则：用户体验优先——选文件即可跑到底；AI 分析在设置里配置一次，持久化。
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .config import (
    LANG_PACK,
    config_path,
    load_config_file,
    load_llm_config,
    save_config_file,
)
from .pipeline import Options, run_batch

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".ts"}
VOICE_LANGS = ["auto", "zh", "en", "ja", "ko", "de", "fr", "es", "ru", "pt"]


def _open_in_explorer(path: Path):
    path = Path(path)
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# 由打包入口注入：拖拽/带参启动时预载的文件列表
PRELOAD_FILES: list[Path] = []


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"video2pdf2 v{__version__} — mp4 转关键帧PDF+字幕+AI总结")
        root.geometry("860x640")
        root.minsize(760, 560)

        self.log_q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.last_outdir: Path | None = None

        self._build_files_area()
        for p in PRELOAD_FILES:
            self._append_unique(p)
        self._build_options_area()
        self._build_llm_area()
        self._build_run_area()
        self._load_settings()
        root.after(100, self._poll_log)

    # ---------- UI 构建 ----------
    def _build_files_area(self):
        box = ttk.LabelFrame(self.root, text=" 1. 视频（可加多个文件或整个文件夹，支持批量） ")
        box.pack(fill="x", padx=10, pady=(10, 4))
        btns = ttk.Frame(box); btns.pack(fill="x", padx=6, pady=4)
        ttk.Button(btns, text="添加文件…", command=self.add_files).pack(side="left")
        ttk.Button(btns, text="添加文件夹…", command=self.add_folder).pack(side="left", padx=4)
        ttk.Button(btns, text="移除选中", command=self.remove_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="清空", command=self.clear).pack(side="left")
        self.filelist = tk.Listbox(box, height=6, selectmode="extended")
        self.filelist.pack(fill="x", padx=6, pady=(0, 6))

    def _build_options_area(self):
        box = ttk.LabelFrame(self.root, text=" 2. 转换选项 ")
        box.pack(fill="x", padx=10, pady=4)
        row = ttk.Frame(box); row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text="语音语言").pack(side="left")
        self.voice_lang = ttk.Combobox(row, values=VOICE_LANGS, width=6, state="readonly")
        self.voice_lang.set("auto"); self.voice_lang.pack(side="left", padx=(2, 10))
        ttk.Label(row, text="输出语言").pack(side="left")
        self.summary_lang = ttk.Combobox(row, values=list(LANG_PACK), width=7, state="readonly")
        self.summary_lang.set("zh"); self.summary_lang.pack(side="left", padx=(2, 10))
        ttk.Label(row, text="whisper模型").pack(side="left")
        self.asr_model = ttk.Combobox(row, values=["small", "base", "tiny", "medium"],
                                      width=7, state="readonly")
        self.asr_model.set("small"); self.asr_model.pack(side="left", padx=(2, 10))
        ttk.Label(row, text="场景阈值").pack(side="left")
        self.scene_thr = ttk.Entry(row, width=6); self.scene_thr.insert(0, "0.08")
        self.scene_thr.pack(side="left", padx=(2, 10))
        ttk.Label(row, text="最小间隔s").pack(side="left")
        self.min_gap = ttk.Entry(row, width=5); self.min_gap.insert(0, "2.0")
        self.min_gap.pack(side="left", padx=2)
        ttk.Label(row, text="简繁").pack(side="left")
        self.zh_script = ttk.Combobox(row, values=["auto", "simplified", "traditional"],
                                      width=11, state="readonly")
        self.zh_script.set("auto"); self.zh_script.pack(side="left", padx=(2, 10))
        self.auto_correct = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="LLM字幕校对", variable=self.auto_correct).pack(side="left")

    def _build_llm_area(self):
        box = ttk.LabelFrame(self.root, text=" 3. AI 分析（OpenAI 兼容端点，留空则跳过分析） ")
        box.pack(fill="x", padx=10, pady=4)
        top = ttk.Frame(box); top.pack(fill="x", padx=6, pady=(4, 2))
        self.analysis_on = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="启用 AI 分析总结", variable=self.analysis_on).pack(side="left")
        ttk.Button(top, text="保存为默认配置", command=self.save_settings).pack(side="right")
        ttk.Label(top, text=f"配置文件：{config_path()}").pack(side="right", padx=8)

        row1 = ttk.Frame(box); row1.pack(fill="x", padx=6, pady=2)
        ttk.Label(row1, text="API地址", width=8).pack(side="left")
        self.api_base = ttk.Entry(row1); self.api_base.pack(side="left", fill="x", expand=True)
        ttk.Label(row1, text="模型", width=5).pack(side="left", padx=(8, 0))
        self.llm_model = ttk.Entry(row1, width=26); self.llm_model.pack(side="left")
        row2 = ttk.Frame(box); row2.pack(fill="x", padx=6, pady=(2, 6))
        ttk.Label(row2, text="API Key", width=8).pack(side="left")
        self.api_key = ttk.Entry(row2, show="•"); self.api_key.pack(side="left", fill="x", expand=True)

    def _build_run_area(self):
        box = ttk.Frame(self.root); box.pack(fill="x", padx=10, pady=4)
        self.start_btn = ttk.Button(box, text="开始转换", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(box, text="停止", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.open_btn = ttk.Button(box, text="打开输出目录", command=self.open_output,
                                   state="disabled")
        self.open_btn.pack(side="left", padx=6)
        self.progress = ttk.Progressbar(box, mode="determinate", length=280)
        self.progress.pack(side="right", padx=4)

        self.log = tk.Text(self.root, height=12, state="disabled", font=("Menlo", 11))
        self.log.pack(fill="both", expand=True, padx=10, pady=(4, 10))

    # ---------- 设置 ----------
    def _load_settings(self):
        cfg = load_config_file()
        llm = load_llm_config()
        if llm:
            self.api_base.insert(0, llm.api_base)
            self.api_key.insert(0, llm.api_key)
            self.llm_model.insert(0, llm.model)
        opts = cfg.get("options", {})
        if opts.get("language"):
            self.voice_lang.set(opts["language"])
        if opts.get("summary_lang"):
            self.summary_lang.set(opts["summary_lang"])
        if opts.get("asr_model"):
            self.asr_model.set(opts["asr_model"])
        if opts.get("zh_script"):
            self.zh_script.set(opts["zh_script"])
        if opts.get("auto_correct") is not None:
            self.auto_correct.set(bool(opts["auto_correct"]))

    def save_settings(self):
        try:
            opts = {
                "language": self.voice_lang.get(),
                "summary_lang": self.summary_lang.get(),
                "asr_model": self.asr_model.get(),
                "zh_script": self.zh_script.get(),
                "auto_correct": bool(self.auto_correct.get()),
                "scene_threshold": float(self.scene_thr.get() or 0.08),
                "min_gap": float(self.min_gap.get() or 2.0),
            }
        except ValueError:
            messagebox.showerror("配置错误", "场景阈值/最小间隔必须是数字")
            return
        cfg = load_config_file()
        cfg["options"] = opts
        if self.api_base.get().strip() and self.api_key.get().strip():
            cfg["llm"] = {
                "api_base": self.api_base.get().strip(),
                "api_key": self.api_key.get().strip(),
                "model": self.llm_model.get().strip(),
            }
        save_config_file(cfg)
        messagebox.showinfo("已保存", f"配置已写入：{config_path()}")

    # ---------- 文件列表 ----------
    def add_files(self):
        files = filedialog.askopenfilenames(
            title="选择视频", filetypes=[("视频", "*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.flv *.ts"),
                                        ("全部文件", "*.*")])
        for f in files:
            self._append_unique(Path(f))

    def add_folder(self):
        d = filedialog.askdirectory(title="选择文件夹（自动展开其中全部视频）")
        if d:
            for p in sorted(Path(d).iterdir()):
                if p.suffix.lower() in VIDEO_EXTS:
                    self._append_unique(p)

    def _append_unique(self, p: Path):
        if str(p) not in self.filelist.get(0, "end"):
            self.filelist.insert("end", str(p))

    def remove_selected(self):
        for i in reversed(self.filelist.curselection()):
            self.filelist.delete(i)

    def clear(self):
        self.filelist.delete(0, "end")

    # ---------- 运行 ----------
    def start(self):
        videos = [Path(x) for x in self.filelist.get(0, "end")]
        if not videos:
            messagebox.showwarning("提示", "请先添加视频文件或文件夹")
            return
        try:
            thr = float(self.scene_thr.get() or 0.08)
            gap = float(self.min_gap.get() or 2.0)
        except ValueError:
            messagebox.showerror("参数错误", "场景阈值/最小间隔必须是数字")
            return
        analysis = self.analysis_on.get()
        opt = Options(
            video=videos[0],
            scene_threshold=thr, min_gap=gap,
            language=self.voice_lang.get(), summary_lang=self.summary_lang.get(),
            zh_script=self.zh_script.get(), auto_correct=bool(self.auto_correct.get()),
            asr_model=self.asr_model.get() or None,
            skip_analysis=not analysis,
            api_base=self.api_base.get().strip() or None,
            api_key=self.api_key.get().strip() or None,
            llm_model=self.llm_model.get().strip() or None,
        )
        self.cancel.clear()
        self.start_btn.config(state="disabled"); self.stop_btn.config(state="normal")
        self.progress.config(mode="determinate", maximum=len(videos), value=0)
        self._log(f"共 {len(videos)} 个视频，开始处理 …")

        def work():
            try:
                run_batch(opt, videos, log=lambda m: self.log_q.put(("log", m)),
                          cancel_check=self.cancel.is_set)
                self.log_q.put(("done", None))
            except Exception as exc:
                self.log_q.put(("error", str(exc)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def stop(self):
        self.cancel.set()
        self._log("将在当前视频完成后停止 …")

    def open_output(self):
        if self.last_outdir:
            _open_in_explorer(self.last_outdir)

    # ---------- 日志线程 ----------
    def _log(self, text: str):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _poll_log(self):
        try:
            while True:
                kind, payload = self.log_q.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                    if str(payload).startswith("完成："):
                        self.last_outdir = Path(str(payload).split("完成：", 1)[1].split("（")[0])
                        self.open_btn.config(state="normal")
                elif kind == "done":
                    self.progress.step(len(self.filelist.get(0, "end")) or 1)
                    self.start_btn.config(state="normal"); self.stop_btn.config(state="disabled")
                    self.progress.config(value=self.progress["maximum"])
                elif kind == "error":
                    self._log(f"错误：{payload}")
                    self.start_btn.config(state="normal"); self.stop_btn.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(120, self._poll_log)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("aqua" if sys.platform == "darwin" else "clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
