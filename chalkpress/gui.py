"""Chalkpress GUI（tkinter，零额外 GUI 依赖，跨平台，可被 PyInstaller 打包）。

设计原则（macOS 风格）：左侧边栏 + 双页签（转换 / 设置）。
首页零配置——拖入视频点开始即可；whisper 模型、语音/输出语言、简繁、
场景阈值等全部收进设置页并默认自动，首页仅以"转换方案"芯片展示当前决策。
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from . import __version__
from .config import (
    logs_dir,
    load_config_file,
    load_llm_config,
    save_config_file,
)
from .pipeline import Options, run_batch
from .update import download, fetch_latest, is_newer, pick_asset, reveal

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".ts"}

# 由打包入口注入：拖拽/带参启动时预载的文件列表
PRELOAD_FILES: list[Path] = []

# ---------- 视觉令牌 ----------
BG = "#F5F5F7"        # 窗口底
SIDE = "#E9E9EC"      # 侧栏
CARD = "#FFFFFF"      # 卡片
INK = "#1D1D1F"       # 主文字
INK2 = "#6E6E73"      # 次文字
FAINT = "#A6A6AD"     # 弱文字
LINE = "#D9D9DE"      # 描边
GREEN = "#2F5D50"     # 黑板绿（主色）
GREEN_DK = "#274E43"
GREEN_BG = "#EAF1EE"
RED = "#C4453C"

STAGES = [("asr", "语音转写"), ("correct", "字幕校对"), ("frames", "关键帧对齐"),
          ("summary", "AI 总结"), ("pdf", "生成 PDF")]
WEIGHTS = {"asr": 45, "correct": 10, "frames": 25, "summary": 12, "pdf": 8}

VOICE_LANGS = ["auto", "zh", "en", "ja", "ko", "de", "fr", "es", "ru", "pt"]
SUMMARY_LANGS = [("简体中文", "zh"), ("中英对照", "zh-en"), ("English", "en")]
ZH_SCRIPTS = [("自动", "auto"), ("简体", "simplified"), ("繁体", "traditional")]
ASR_MODELS = [("自动（推荐）", None), ("tiny（最快）", "tiny"),
              ("small（默认）", "small"), ("medium（最准）", "medium")]
SCENE_PRESETS = [("标准", None), ("更多页数（画面琐碎）", 0.05), ("更少页数（课件翻页少）", 0.12)]
GAP_PRESETS = [("2 秒", None), ("5 秒", 5.0), ("10 秒", 10.0)]


def _open_in_explorer(path: Path):
    path = Path(path)
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _human_size(p: Path) -> str:
    try:
        n = p.stat().st_size
    except OSError:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def draw_logo(cv: tk.Canvas, size: int):
    """黑板绿圆角块 + 米白讲义页（折角）+ 播放三角。"""
    s = size / 36.0
    r = 9 * s

    def pt(x, y):
        return x * s, y * s

    # 圆角矩形（8 点 smooth 多边形）
    pts = [pt(0 + r / s * 0, 0)]  # 占位，下面用标准圆角近似
    x0, y0, x1, y1 = 0, 0, 36, 36
    pts = [(x0 + r, y0), (x1 - r, y0), (x1, y0 + r), (x1, y1 - r),
           (x1 - r, y1), (x0 + r, y1), (x0, y1 - r), (x0, y0 + r)]
    cv.create_polygon([c * s for c in sum(pts, ())][0:0] or
                      [coord for p_ in pts for coord in p_],
                      smooth=True, fill=GREEN, outline="")
    # 讲义页
    cv.create_polygon([11.5 * s, 7 * s, 20.5 * s, 7 * s, 26.5 * s, 13 * s,
                       26.5 * s, 28.5 * s, 24.7 * s, 30.3 * s, 11.5 * s, 30.3 * s,
                       9.7 * s, 28.5 * s, 9.7 * s, 8.8 * s],
                      fill="#F6F3E7", outline="")
    # 折角
    cv.create_polygon([20.5 * s, 7 * s, 26.5 * s, 13 * s, 21.9 * s, 13 * s,
                       20.5 * s, 11.6 * s], fill="#BECFC7", outline="")
    # 播放三角
    cv.create_polygon([15.2 * s, 15.5 * s, 23 * s, 19.5 * s, 15.2 * s, 23.5 * s],
                      fill=GREEN, outline="")


class Switch(tk.Canvas):
    """macOS 风格开关（自绘）。"""

    def __init__(self, master, value=True, command=None):
        super().__init__(master, width=44, height=24, bg=master["bg"],
                         highlightthickness=0, cursor="hand2")
        self.value = bool(value)
        self.command = command
        self.bind("<Button-1>", self._toggle)
        self._draw()

    def _toggle(self, _e=None):
        self.value = not self.value
        self._draw()
        if self.command:
            self.command(self.value)

    def set(self, value: bool):
        self.value = bool(value)
        self._draw()

    def _draw(self):
        self.delete("all")
        bg = GREEN if self.value else "#D5D5DA"
        self.create_oval(2, 2, 22, 22, fill=bg, outline="")
        self.create_oval(22, 2, 42, 22, fill=bg, outline="")
        self.create_rectangle(12, 2, 32, 22, fill=bg, outline="")
        kx = 24 if self.value else 4
        self.create_oval(kx, 4, kx + 16, 20, fill="#FFFFFF", outline="")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"Chalkpress v{__version__}")
        root.geometry("980x680")
        root.minsize(900, 620)
        root.configure(bg=BG)
        root.minsize(880, 600)

        self.log_q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.videos: list[Path] = []
        self.results: list = []
        self.log_fh = None
        self.last_outdir: Path | None = None
        self.upd_checking = False
        self._stage_done_w = 0

        self._build_fonts()
        self._build_style()
        self._build_sidebar()
        self.body = tk.Frame(root, bg=BG)
        self.body.pack(side="right", fill="both", expand=True)
        self._build_convert()
        self._build_settings()
        self._load_settings()
        self._refresh_plan()
        self.show("convert")
        for p in PRELOAD_FILES:
            self.add_video(p)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(120, self._poll)
        self._auto_check_updates()

    # ---------- 字体与样式 ----------
    def _build_fonts(self):
        want = {"darwin": ["PingFang SC"], "win32": ["Microsoft YaHei UI", "微软雅黑"],
                "linux": ["Noto Sans CJK SC", "WenQuanYi Micro Hei"]}.get(sys.platform, [])
        avail = set(tkfont.families(self.root))
        self.family = next((w for w in want if w in avail), None)
        mk = lambda size, weight="normal": (
            tkfont.Font(family=self.family, size=size, weight=weight)
            if self.family else tkfont.Font(size=size, weight=weight))
        self.f = mk(13)
        self.f_small = mk(11)
        self.f_tiny = mk(10)
        self.f_bold = mk(13, "bold")
        self.f_name = mk(15, "bold")
        self.f_h1 = mk(17, "bold")
        self.f_h2 = mk(15, "bold")
        self.f_stat = mk(21, "bold")
        mono_family = "Menlo" if sys.platform == "darwin" else (
            "Consolas" if sys.platform == "win32" else "Monospace")
        self.f_mono = tkfont.Font(family=mono_family, size=10)

    def _build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("CP.TCombobox", fieldbackground=CARD, background=LINE,
                        arrowcolor=INK2, bordercolor=LINE, lightcolor=CARD,
                        darkcolor=CARD, borderwidth=1, padding=5,
                        selectbackground="#EFEFF2", selectforeground=INK,
                        postselectbackground=GREEN_BG, postselectforeground=INK)
        style.map("CP.TCombobox",
                  fieldbackground=[("readonly", CARD)],
                  bordercolor=[("focus", GREEN)])
        style.configure("CP.Vertical.TScrollbar", background=SIDE,
                        troughcolor=BG, bordercolor=BG, arrowcolor=INK2)
        style.configure("CP.Horizontal.TProgressbar", troughcolor="#E4E4E8",
                        background=GREEN, bordercolor=BG, lightcolor=GREEN,
                        darkcolor=GREEN, thickness=6)
        style.configure("CP2.Horizontal.TProgressbar", troughcolor="#E4E4E8",
                        background=GREEN, bordercolor=BG, lightcolor=GREEN,
                        darkcolor=GREEN, thickness=5)
        self.style = style
    # ---------- 通用小组件 ----------
    def _card(self, parent) -> tk.Frame:
        return tk.Frame(parent, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE)

    def _btn(self, parent, text, command, kind="normal", size=13):
        """ttk 按钮（clam 主题下 bg 才可靠；aqua 的 tk.Button 会忽略 background）。"""
        name = f"CP.{'Primary' if kind == 'primary' else 'Ghost'}.{size}.TButton"
        fnt = tkfont.Font(family=self.family, size=size,
                          weight="bold" if kind == "primary" else "normal")
        if kind == "primary":
            self.style.configure(name, background=GREEN, foreground="#FFFFFF",
                                 bordercolor=GREEN, lightcolor=GREEN,
                                 darkcolor=GREEN, focusthickness=0,
                                 padding=(18, 8), font=fnt)
            self.style.map(name,
                           background=[("disabled", "#A8BEB7"),
                                       ("pressed", GREEN_DK), ("active", GREEN_DK)],
                           foreground=[("disabled", "#E8EFEC")])
        else:
            self.style.configure(name, background=CARD, foreground=INK,
                                 bordercolor=LINE, lightcolor=CARD,
                                 darkcolor=CARD, focusthickness=0,
                                 padding=(14, 6), font=fnt)
            self.style.map(name,
                           background=[("pressed", "#F2F2F5"), ("active", "#F2F2F5")],
                           foreground=[("disabled", FAINT)])
        return ttk.Button(parent, text=text, command=command, style=name,
                          cursor="hand2")

    def _chip(self, parent, text):
        return tk.Label(parent, text=text, bg=GREEN_BG, fg=GREEN_DK,
                        padx=10, pady=3, font=self.f_small)

    def _row(self, parent, title, desc, widget, extra=None):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=16, pady=1)
        top = tk.Frame(row, bg=CARD); top.pack(fill="x", pady=7)
        lab = tk.Frame(top, bg=CARD); lab.pack(side="left", fill="x", expand=True)
        tk.Label(lab, text=title, bg=CARD, fg=INK, font=self.f_bold,
                 anchor="w").pack(anchor="w")
        if desc:
            tk.Label(lab, text=desc, bg=CARD, fg=INK2, font=self.f_tiny,
                     anchor="w", justify="left", wraplength=300).pack(anchor="w")
        ctl = tk.Frame(top, bg=CARD); ctl.pack(side="right")
        def _raise(w):
            # Canvas/TTK 的 path 命令不支持 raise 子命令，用全局 raise 命令
            w.tk.call("raise", str(w))
        if extra is not None:
            extra.pack(in_=ctl, side="right", padx=(10, 0))
            _raise(extra)
        # 控件可能先于 row 框架创建：不抬升会被后建的不透明框架盖住
        if isinstance(widget, tuple):
            for w in widget:
                w.pack(in_=ctl, side="left", padx=(0, 8))
                _raise(w)
        else:
            widget.pack(in_=ctl, side="right")
            _raise(widget)
        tk.Frame(row, bg="#EFEFF2", height=1).pack(fill="x")
        return row

    def _combo(self, parent, values, width=24):
        return ttk.Combobox(parent, values=[v[0] for v in values], width=width,
                            state="readonly", style="CP.TCombobox")

    def _entry(self, parent, show=""):
        e = tk.Entry(parent, show=show, relief="flat", bg=CARD, fg=INK,
                     highlightthickness=1, highlightbackground=LINE,
                     highlightcolor=GREEN, insertbackground=INK,
                     font=self.f, width=30)
        return e

    # ---------- 侧栏 ----------
    def _build_sidebar(self):
        side = tk.Frame(self.root, bg=SIDE, width=210)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        brand = tk.Frame(side, bg=SIDE)
        brand.pack(fill="x", padx=14, pady=(16, 14))
        cv = tk.Canvas(brand, width=36, height=36, bg=SIDE, highlightthickness=0)
        cv.pack(side="left")
        draw_logo(cv, 36)
        txt = tk.Frame(brand, bg=SIDE)
        txt.pack(side="left", padx=(10, 0))
        tk.Label(txt, text="Chalkpress", bg=SIDE, fg=INK, font=self.f_name,
                 anchor="w").pack(anchor="w")
        tk.Label(txt, text="讲座视频 → 讲义 PDF", bg=SIDE, fg=INK2,
                 font=self.f_tiny, anchor="w").pack(anchor="w")

        self.nav_btns = {}
        for key, label in (("convert", "转换"), ("settings", "设置")):
            b = tk.Label(side, text="  " + label, bg=SIDE, fg=INK, font=self.f,
                         anchor="w", padx=10, pady=7, cursor="hand2")
            b.pack(fill="x", padx=10, pady=1)
            b.bind("<Button-1>", lambda _e, k=key: self.show(k))
            self.nav_btns[key] = b

        foot = tk.Frame(side, bg=SIDE)
        foot.pack(side="bottom", fill="x", padx=14, pady=12)
        self.ver_lbl = tk.Label(foot, text=f"v{__version__}", bg=SIDE, fg=INK2,
                                font=self.f_tiny, anchor="w", cursor="hand2")
        self.ver_lbl.pack(anchor="w")
        self.upd_hint = tk.Label(foot, text="", bg=SIDE, fg=GREEN_DK,
                                 font=self.f_tiny, anchor="w", cursor="hand2")
        self.upd_hint.pack(anchor="w")
        self.upd_hint.bind("<Button-1>", lambda _e: self.show("settings"))

    def _nav_active(self, key):
        for k, b in self.nav_btns.items():
            if k == key:
                b.configure(bg=CARD, font=self.f_bold)
            else:
                b.configure(bg=SIDE, font=self.f)
    def show(self, key):
        self._nav_active(key)
        (self.convert_pane if key == "convert" else self.settings_pane).tkraise()

    def _build_convert(self):
        pane = tk.Frame(self.body, bg=BG)
        pane.place(x=0, y=0, relwidth=1, relheight=1)
        inner = tk.Frame(pane, bg=BG)
        inner.pack(fill="both", expand=True, padx=24, pady=18)
        self.convert_pane = pane

        # 投放区
        self.drop = tk.Canvas(inner, height=110, bg=CARD, highlightthickness=0,
                              cursor="hand2")
        self.drop.pack(fill="x")
        self.drop.bind("<Button-1>", lambda _e: self.add_files())
        self.drop.bind("<Configure>", self._draw_drop)

        # 文件卡片
        self.files_card = self._card(inner)
        self.files_card.pack(fill="x", pady=(12, 0))
        head = tk.Frame(self.files_card, bg=CARD)
        head.pack(fill="x", padx=16, pady=(10, 2))
        tk.Label(head, text="已添加的视频", bg=CARD, fg=INK2,
                 font=self.f_small).pack(anchor="w")
        self.files_box = tk.Frame(self.files_card, bg=CARD)
        self.files_box.pack(fill="x", padx=16, pady=(2, 4))
        self.fsum = tk.Label(self.files_card, text="", bg=CARD, fg=INK2,
                             font=self.f_tiny, anchor="w")
        self.fsum.pack(fill="x", padx=16, pady=(0, 8))

        # 方案芯片
        self.plan_card = self._card(inner)
        self.plan_card.pack(fill="x", pady=12)
        plan_in = tk.Frame(self.plan_card, bg=CARD)
        plan_in.pack(fill="x", padx=14, pady=10)
        self.chips_box = tk.Frame(plan_in, bg=CARD)
        self.chips_box.pack(side="left", fill="x", expand=True)
        link = tk.Label(plan_in, text="在设置中调整 →", bg=CARD, fg=GREEN_DK,
                        font=self.f_small, cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda _e: self.show("settings"))

        # 动作行（files/plan 卡片永远插在本行之前）
        self.acts = tk.Frame(inner, bg=BG)
        self.acts.pack(fill="x")
        self.start_btn = self._btn(self.acts, "开始转换", self.start, kind="primary", size=15)
        self.start_btn.pack(side="left", fill="x", expand=True, ipady=4)
        self.open_btn = self._btn(self.acts, "打开输出文件夹", self.open_output, size=14)
        self.open_btn.pack(side="left", padx=(10, 0), ipady=4)
        self.open_btn.configure(state="disabled")
        self.stop_btn = self._btn(inner, "停止（当前视频完成后）", self.stop, size=13)
        self.stop_btn.pack(fill="x", pady=(10, 0))
        self.stop_btn.configure(state="disabled")

        # 进度卡片
        self.prog_card = self._card(inner)
        pc = tk.Frame(self.prog_card, bg=CARD)
        pc.pack(fill="x", padx=16, pady=12)
        self.prog_title = tk.Label(pc, text="", bg=CARD, fg=INK, font=self.f_h2,
                                   anchor="w")
        self.prog_title.pack(anchor="w")
        self.nowline = tk.Label(pc, text="", bg=CARD, fg=INK2, font=self.f_small,
                                anchor="w")
        self.nowline.pack(anchor="w", pady=(2, 6))
        self.bar = ttk.Progressbar(pc, style="CP.Horizontal.TProgressbar",
                                   mode="determinate")
        self.bar.pack(fill="x")
        stages_f = tk.Frame(pc, bg=CARD)
        stages_f.pack(anchor="w", pady=(8, 0))
        self.stage_lbls: dict[str, tk.Label] = {}
        for i, (key, name) in enumerate(STAGES):
            lbl = tk.Label(stages_f, text="○ " + name, bg=CARD, fg=FAINT,
                           font=self.f_small)
            lbl.pack(side="left")
            self.stage_lbls[key] = lbl
            if i < len(STAGES) - 1:
                tk.Label(stages_f, text=" → ", bg=CARD, fg="#C9C9CF",
                         font=self.f_tiny).pack(side="left")
        vrow = tk.Frame(pc, bg=CARD)
        vrow.pack(fill="x", pady=(8, 0))
        self.vbar_lbl = tk.Label(vrow, text="本视频 0%", bg=CARD, fg=INK2,
                                 font=self.f_small)
        self.vbar_lbl.pack(side="left")
        self.vbar = ttk.Progressbar(vrow, style="CP2.Horizontal.TProgressbar",
                                    mode="determinate", length=240)
        self.vbar.pack(side="left", padx=(10, 0), fill="x", expand=True)

        # 成果卡片
        self.done_card = self._card(inner)
        dc = tk.Frame(self.done_card, bg=CARD)
        dc.pack(fill="x", padx=16, pady=14)
        ok = tk.Canvas(dc, width=40, height=40, bg=CARD, highlightthickness=0)
        ok.create_oval(2, 2, 38, 38, fill=GREEN, outline="")
        ok.create_text(20, 20, text="✓", fill="#FFFFFF", font=(self.family or "TkDefaultFont", 17, "bold"))
        self.done_cvs = ok
        top = tk.Frame(dc, bg=CARD)
        top.pack(fill="x")
        ok.pack(side="left", padx=(0, 12))
        self.done_title = tk.Label(top, text="", bg=CARD, fg=INK, font=self.f_h2,
                                   anchor="w")
        self.done_title.pack(anchor="w")
        self.stats_box = tk.Frame(dc, bg=CARD)
        self.stats_box.pack(fill="x", pady=(10, 4))
        self.outs_box = tk.Frame(dc, bg=CARD)
        self.outs_box.pack(fill="x", pady=(2, 6))
        self.open_btn2 = self._btn(dc, "打开输出文件夹", self.open_output,
                                   kind="primary", size=13)
        self.open_btn2.configure(state="disabled")
        self.open_btn2.pack(anchor="w", pady=(6, 0))

        self._refresh_files()
        self.prog_card.pack_forget()
        self.done_card.pack_forget()

    def _draw_drop(self, e=None):
        cv = self.drop
        cv.delete("all")
        w = cv.winfo_width() or 900
        h = 110
        cv.create_rectangle(3, 3, w - 3, h - 3, dash=(5, 3),
                            outline="#B9B9C0", width=1.5)
        cv.create_text(w / 2, 26, text="🎬", font=(self.family or "TkDefaultFont", 20))
        cv.create_text(w / 2, 58, text="拖入视频，或点击添加",
                       fill=INK, font=(self.family or "TkDefaultFont", 14, "bold"))
        cv.create_text(w / 2, 82,
                       text="支持 mp4 · mov · mkv · webm 等，可多选文件或整个文件夹",
                       fill=INK2, font=(self.family or "TkDefaultFont", 11))

    # ---------- 文件列表 ----------
    def add_files(self):
        files = filedialog.askopenfilenames(
            title="选择视频",
            filetypes=[("视频", "*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.flv *.ts"),
                       ("全部文件", "*.*")])
        for f in files:
            self.add_video(Path(f))

    def add_folder(self):
        d = filedialog.askdirectory(title="选择文件夹（自动展开其中全部视频）")
        if d:
            for p in sorted(Path(d).iterdir()):
                if p.suffix.lower() in VIDEO_EXTS:
                    self.add_video(p)

    def add_video(self, p: Path):
        if p not in self.videos:
            self.videos.append(p)
            self._refresh_files()

    def _refresh_files(self):
        for w in self.files_box.winfo_children():
            w.destroy()
        empty = not self.videos
        if empty:
            self.files_card.pack_forget()
            self.plan_card.pack_forget()
            self._hide_run_cards()
            self.start_btn.configure(state="disabled")
            return
        for p in self.videos:
            row = tk.Frame(self.files_box, bg=CARD)
            row.pack(fill="x", pady=1)
            tk.Label(row, text="🎬", bg=CARD, font=self.f).pack(side="left")
            name = p.name if len(p.name) <= 52 else p.name[:24] + "…" + p.name[-24:]
            tk.Label(row, text=name, bg=CARD, fg=INK, font=self.f,
                     anchor="w").pack(side="left", padx=(8, 0))
            tk.Label(row, text=_human_size(p), bg=CARD, fg=INK2,
                     font=self.f_tiny).pack(side="right")
            x = tk.Label(row, text="✕", bg=CARD, fg=FAINT, cursor="hand2",
                         font=self.f_small)
            x.pack(side="right", padx=(14, 2))
            x.bind("<Button-1>", lambda _e, pp=p: self._remove_video(pp))
            x.bind("<Enter>", lambda _e, l=x: l.configure(fg=RED))
            x.bind("<Leave>", lambda _e, l=x: l.configure(fg=FAINT))
        self.fsum.configure(
            text=f"{len(self.videos)} 个视频 · 讲义生成在各自视频所在文件夹")
        self.files_card.pack(fill="x", before=self.acts, pady=(12, 0))
        self.plan_card.pack(fill="x", before=self.acts, pady=12)
        self.start_btn.configure(state="normal" if not self.worker else "disabled")
        self._refresh_plan()

    def _remove_video(self, p: Path):
        self.videos = [v for v in self.videos if v != p]
        self._refresh_files()

    def _hide_run_cards(self):
        self.prog_card.pack_forget()
        self.done_card.pack_forget()

    # ---------- 方案芯片 ----------
    def _refresh_plan(self):
        for w in self.chips_box.winfo_children():
            w.destroy()
        out_lang = dict(SUMMARY_LANGS).get(self.summary_lang_val, "简体中文")
        chips = [
            f"语音语言  自动识别",
            f"字幕模型  {'自动' if self.asr_model_val is None else self.asr_model_val}",
            f"输出语言  {out_lang}",
            f"字幕校对  {'开' if self.auto_correct_val else '关'}",
        ]
        cfg = load_llm_config()
        chips.append(f"AI 总结  {'开' if self.ai_on_val and cfg else ('未配置' if self.ai_on_val else '关')}")
        for c in chips:
            self._chip(self.chips_box, c).pack(side="left", padx=(0, 6), pady=2)

    # ---------- 设置页 ----------
    def _build_settings(self):
        pane = tk.Frame(self.body, bg=BG)
        pane.place(x=0, y=0, relwidth=1, relheight=1)
        self.settings_pane = pane
        cv = tk.Canvas(pane, bg=BG, highlightthickness=0)
        sf = tk.Frame(cv, bg=BG)
        sb = ttk.Scrollbar(pane, orient="vertical", command=cv.yview,
                           style="CP.Vertical.TScrollbar")
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        self.set_win = cv.create_window((0, 0), window=sf, anchor="nw")
        inner = tk.Frame(sf, bg=BG)
        inner.pack(fill="both", expand=True, padx=24, pady=18)
        sf.bind("<Configure>", lambda e: cv.configure(
            scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(self.set_win, width=e.width))
        self._bind_wheel(cv, sf)

        tk.Label(inner, text="设置", bg=BG, fg=INK, font=self.f_h1,
                 anchor="w").pack(anchor="w")
        tk.Label(inner, text="改动即时保存；首页的\"转换方案\"会随之更新",
                 bg=BG, fg=INK2, font=self.f_small, anchor="w").pack(anchor="w", pady=(2, 12))

        # 输出
        c1 = self._card(inner); c1.pack(fill="x", pady=(0, 12))
        tk.Label(c1, text="输出", bg=CARD, fg=INK2, font=self.f_small).pack(anchor="w", padx=16, pady=(10, 0))
        self.out_lang_cb = self._combo(c1, SUMMARY_LANGS)
        self.out_lang_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_setting("summary_lang"))
        self._row(c1, "输出语言", "AI 总结使用的语言", self.out_lang_cb)
        self.zh_cb = self._combo(c1, ZH_SCRIPTS)
        self.zh_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_setting("zh_script"))
        self._row(c1, "简繁", "自动 = 跟随系统语言（简体系统 → 简体）", self.zh_cb)
        keep = tk.Label(c1, text="跟随视频（自动）", bg=CARD, fg=INK2, font=self.f_small)
        self._row(c1, "保存位置", "讲义 PDF 生成在视频所在文件夹，无需配置", keep)

        # 语音识别
        c2 = self._card(inner); c2.pack(fill="x", pady=(0, 12))
        tk.Label(c2, text="语音识别", bg=CARD, fg=INK2, font=self.f_small).pack(anchor="w", padx=16, pady=(10, 0))
        self.model_cb = self._combo(c2, ASR_MODELS)
        self.model_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_setting("asr_model"))
        self._row(c2, "字幕模型",
                  "自动 = small，准确与速度均衡；想更快选 tiny，更准选 medium（更大更慢）",
                  self.model_cb)
        self.correct_sw = Switch(c2, True, lambda v: self._on_setting("auto_correct"))
        self._row(c2, "AI 字幕校对", "用 AI 修正转写错别字与术语，需要配置 AI 分析", self.correct_sw)

        # AI 分析
        c3 = self._card(inner); c3.pack(fill="x", pady=(0, 12))
        tk.Label(c3, text="AI 分析（OpenAI 兼容接口）", bg=CARD, fg=INK2,
                 font=self.f_small).pack(anchor="w", padx=16, pady=(10, 0))
        self.api_base_e = self._entry(c3)
        self._row(c3, "接口地址",
                  "用于字幕校对与总结；不配置则跳过 AI 步骤，只出关键帧 PDF + 字幕",
                  self.api_base_e)
        self.api_key_e = self._entry(c3, show="•")
        self._row(c3, "API Key", "", self.api_key_e)
        self.model_e = self._entry(c3)
        self._row(c3, "模型", "", self.model_e)
        for e in (self.api_base_e, self.api_key_e, self.model_e):
            e.bind("<FocusOut>", lambda _e: self._on_setting("llm"))

        # 关键帧（高级）
        c4 = self._card(inner); c4.pack(fill="x", pady=(0, 12))
        tk.Label(c4, text="关键帧（高级）", bg=CARD, fg=INK2, font=self.f_small).pack(anchor="w", padx=16, pady=(10, 0))
        self.scene_cb = self._combo(c4, SCENE_PRESETS)
        self.scene_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_setting("scene_threshold"))
        self._row(c4, "场景切换灵敏度",
                  "画面变化多敏感就截一页：课件翻页少的视频可减少页数，画面琐碎可增加",
                  self.scene_cb)
        self.gap_cb = self._combo(c4, GAP_PRESETS)
        self.gap_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_setting("min_gap"))
        self._row(c4, "关键帧最小间隔", "两页之间至少相隔的秒数，避免同一页 PPT 重复截图", self.gap_cb)

        # 日志
        c5 = self._card(inner); c5.pack(fill="x", pady=(0, 12))
        tk.Label(c5, text="日志（专业）", bg=CARD, fg=INK2, font=self.f_small).pack(anchor="w", padx=16, pady=(10, 0))
        open_log = self._btn(c5, "打开日志文件夹", self._open_logs, size=12)
        self.keep_log_sw = Switch(c5, True, lambda v: self._on_setting("keep_log"))
        self._row(c5, "保留运行日志",
                  "界面只展示进度；开启后完整日志写入本地文件，供排障与回溯；关闭则不保留任何日志",
                  self.keep_log_sw, extra=open_log)

        # 关于与更新
        c6 = self._card(inner); c6.pack(fill="x", pady=(0, 12))
        tk.Label(c6, text="关于与更新", bg=CARD, fg=INK2, font=self.f_small).pack(anchor="w", padx=16, pady=(10, 0))
        about = tk.Frame(c6, bg=CARD)
        about.pack(fill="x", padx=16, pady=10)
        cv2 = tk.Canvas(about, width=34, height=34, bg=CARD, highlightthickness=0)
        cv2.pack(side="left")
        draw_logo(cv2, 34)
        mt = tk.Frame(about, bg=CARD); mt.pack(side="left", padx=(12, 0))
        tk.Label(mt, text="Chalkpress", bg=CARD, fg=INK, font=self.f_name,
                 anchor="w").pack(anchor="w")
        self.about_ver = tk.Label(mt, text=f"v{__version__} · 讲座视频 → 讲义 PDF",
                                  bg=CARD, fg=INK2, font=self.f_tiny, anchor="w")
        self.about_ver.pack(anchor="w")
        self.upd_status = tk.Label(about, text="", bg=CARD, fg=INK2,
                                   font=self.f_small)
        self.upd_status.pack(side="right", padx=(0, 10))
        self.upd_btn = self._btn(about, "检查更新", self.check_updates, size=12)
        self.upd_btn.pack(side="right")
        self.auto_upd_sw = Switch(c6, True, lambda v: self._on_setting("auto_update"))
        self._row(c6, "自动更新",
                  "发现新版本后自动从 GitHub Releases 下载安装包并打开发布目录，安装后重启生效",
                  self.auto_upd_sw)

    def _bind_wheel(self, cv, frame):
        def wheel(e):
            if getattr(e, "num", None) == 4:
                d = -1
            elif getattr(e, "num", None) == 5:
                d = 1
            else:
                d = -1 if e.delta > 0 else (1 if e.delta < 0 else 0)
            if d:
                cv.yview_scroll(d, "units")
        frame.bind("<Enter>", lambda _e: (
            cv.bind_all("<MouseWheel>", wheel),
            cv.bind_all("<Button-4>", wheel), cv.bind_all("<Button-5>", wheel)))
        frame.bind("<Leave>", lambda _e: (
            cv.unbind_all("<MouseWheel>"), cv.unbind_all("<Button-4>"),
            cv.unbind_all("<Button-5>")))

    # ---------- 设置状态 ----------
    def _load_settings(self):
        cfg = load_config_file()
        opts = cfg.get("options", {})
        self.summary_lang_val = opts.get("summary_lang", "zh")
        self.zh_script_val = opts.get("zh_script", "auto")
        self.asr_model_val = opts.get("asr_model")  # None = 自动
        self.scene_val = opts.get("scene_threshold")  # None = 标准
        self.gap_val = opts.get("min_gap")  # None = 2 秒
        self.auto_correct_val = bool(opts.get("auto_correct", True))
        app = cfg.get("app", {})
        self.keep_log_val = bool(app.get("keep_log", True))
        self.auto_update_val = bool(app.get("auto_update", True))
        llm = cfg.get("llm", {})
        self.ai_on_val = True

        _set_combo(self.out_lang_cb, SUMMARY_LANGS, self.summary_lang_val)
        _set_combo(self.zh_cb, ZH_SCRIPTS, self.zh_script_val)
        _set_combo(self.model_cb, ASR_MODELS, self.asr_model_val or "__auto__")
        _set_combo(self.scene_cb, SCENE_PRESETS, self.scene_val if self.scene_val is not None else "__std__")
        _set_combo(self.gap_cb, GAP_PRESETS, self.gap_val if self.gap_val is not None else "__2s__")
        self.correct_sw.set(self.auto_correct_val)
        self.keep_log_sw.set(self.keep_log_val)
        self.auto_upd_sw.set(self.auto_update_val)
        self.api_base_e.insert(0, llm.get("api_base", ""))
        self.api_key_e.insert(0, llm.get("api_key", ""))
        self.model_e.insert(0, llm.get("model", ""))

    def _on_setting(self, _key=None):
        self.summary_lang_val = dict((v, k) for k, v in SUMMARY_LANGS)[self.out_lang_cb.get()]
        self.zh_script_val = dict((v, k) for k, v in ZH_SCRIPTS)[self.zh_cb.get()]
        self.asr_model_val = dict(ASR_MODELS)[self.model_cb.get()]
        self.scene_val = dict(SCENE_PRESETS)[self.scene_cb.get()]
        self.gap_val = dict(GAP_PRESETS)[self.gap_cb.get()]
        self.auto_correct_val = self.correct_sw.value
        self.keep_log_val = self.keep_log_sw.value
        self.auto_update_val = self.auto_upd_sw.value
        self._save_settings()
        self._refresh_plan()

    def _save_settings(self):
        cfg = load_config_file()
        options = {
            "summary_lang": self.summary_lang_val,
            "zh_script": self.zh_script_val,
            "auto_correct": self.auto_correct_val,
        }
        if self.asr_model_val:
            options["asr_model"] = self.asr_model_val
        if self.scene_val is not None:
            options["scene_threshold"] = self.scene_val
        if self.gap_val is not None:
            options["min_gap"] = self.gap_val
        cfg["options"] = options
        cfg["app"] = {"keep_log": self.keep_log_val, "auto_update": self.auto_update_val}
        base = self.api_base_e.get().strip()
        key = self.api_key_e.get().strip()
        model = self.model_e.get().strip()
        if base and key and model:
            cfg["llm"] = {"api_base": base, "api_key": key, "model": model}
        else:
            cfg.pop("llm", None)
        save_config_file(cfg)

    def _open_logs(self):
        d = logs_dir()
        if self.keep_log_val and d.is_dir():
            _open_in_explorer(d)
        else:
            messagebox.showinfo("日志", "当前未保留日志。打开\"保留运行日志\"后，转换日志才会写入本地。")

    # ---------- 运行 ----------
    def start(self):
        if not self.videos:
            messagebox.showinfo("提示", "请先添加视频文件或文件夹")
            return
        cfg = load_llm_config(self.api_base_e.get().strip() or None,
                              self.api_key_e.get().strip() or None,
                              self.model_e.get().strip() or None)
        skip_ai = False
        if self.ai_on_val and not cfg:
            if messagebox.askyesno(
                    "AI 分析未配置",
                    "未配置 AI 接口，本次仅生成关键帧 PDF + 字幕（跳过校对与总结）。\n\n"
                    "继续转换？可稍后在设置中配置 AI。"):
                skip_ai = True
            else:
                self.show("settings")
                return
        opt = Options(
            video=self.videos[0],
            scene_threshold=self.scene_val,
            min_gap=self.gap_val,
            language="auto",
            summary_lang=self.summary_lang_val,
            zh_script=self.zh_script_val,
            auto_correct=self.auto_correct_val,
            asr_model=self.asr_model_val,
            api_base=self.api_base_e.get().strip() or None,
            api_key=self.api_key_e.get().strip() or None,
            llm_model=self.model_e.get().strip() or None,
        )
        self.cancel.clear()
        self.results = []
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.open_btn.configure(state="disabled")
        self.open_btn2.configure(state="disabled")
        self.done_card.pack_forget()
        self.prog_card.pack(fill="x", before=self.stop_btn, pady=(4, 0))
        self.bar.configure(value=0, maximum=max(len(self.videos), 1))
        self._reset_stages()
        self.vbar.configure(value=0)
        self.vbar_lbl.configure(text="本视频 0%")
        if self.keep_log_val:
            self._open_logfile()
        self._log(f"Chalkpress v{__version__} · {len(self.videos)} 个视频")

        def work():
            try:
                run_batch(opt, list(self.videos), log=self._log,
                          cancel_check=self.cancel.is_set,
                          progress=lambda ev, **kw: self.log_q.put(("progress", ev, kw)))
                self.log_q.put(("done",))
            except Exception as exc:
                self.log_q.put(("failed", str(exc)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def stop(self):
        self.cancel.set()
        self.nowline.configure(text="将在当前视频完成后停止 …")

    def _reset_stages(self):
        for key, name in STAGES:
            self.stage_lbls[key].configure(text="○ " + name, fg=FAINT,
                                           font=self.f_small)
        self._stage_done_w = 0

    def _set_stage(self, key, state):
        for k, name in STAGES:
            if k != key:
                continue
            lbl = self.stage_lbls[k]
            if state == "done":
                lbl.configure(text="✓ " + name, fg=GREEN_DK, font=self.f_small)
            elif state == "doing":
                lbl.configure(text="● " + name, fg=INK, font=self.f_bold)
            else:
                lbl.configure(text="○ " + name, fg=FAINT, font=self.f_small)

    def _on_progress(self, ev, data):
        if ev == "video_start":
            i, total, name = data["index"], data["total"], data["name"]
            self.prog_title.configure(text=f"正在转换 {i} / {total}")
            self.nowline.configure(text=f"当前：{name}", fg=INK2)
            self._reset_stages()
            self.vbar.configure(value=0)
            self.vbar_lbl.configure(text="本视频 0%")
            self.bar.configure(value=i - 1)
        elif ev == "stage":
            self._set_stage(data["key"], "doing")
            self._vbar_pct(WEIGHTS[data["key"]] / 2)
        elif ev == "stage_done":
            self._set_stage(data["key"], "done")
            self._stage_done_w += WEIGHTS[data["key"]]
            self._vbar_pct(self._stage_done_w)
        elif ev == "frames":
            self.nowline.configure(
                text=self.nowline.cget("text").split(" · ")[0] + f" · 已生成 {data['count']} 页")
        elif ev == "video_done":
            self.results.append(data["result"])
            self.bar.configure(value=self.bar.cget("value") + 1)
        elif ev == "video_error":
            self.results.append(Exception(data["error"]))
            self.nowline.configure(text=f"✗ {data['name']} 失败：{data['error']}", fg=RED)
        elif ev == "batch_done":
            self._show_done(data)

    def _vbar_pct(self, done_w):
        pct = min(int(done_w), 100)
        self.vbar.configure(value=pct, maximum=100)
        self.vbar_lbl.configure(text=f"本视频 {pct}%")

    def _show_done(self, data):
        ok = data["ok"]; total = data["total"]
        self.prog_card.pack_forget()
        self.done_card.pack(fill="x", before=self.stop_btn)
        results = [r for r in self.results if not isinstance(r, Exception)]
        fails = [r for r in self.results if isinstance(r, Exception)]
        self.done_title.configure(
            text=f"{ok} 个视频完成" + (f"，{len(fails)} 个失败" if fails else " 🎉" if ok == total else ""))
        for w in self.stats_box.winfo_children():
            w.destroy()
        pages = sum(len(r.frames) for r in results)
        subs = sum(len(r.aligned) for r in results)
        secs = sum(r.seconds for r in results)
        stats = [(str(ok), "讲义 PDF"), (str(pages), "讲义页数"),
                 (str(subs), "条字幕"),
                 (f"{int(secs // 60)} 分 {int(secs % 60)} 秒" if secs else "-", "总耗时")]
        for val, lab in stats:
            col = tk.Frame(self.stats_box, bg=CARD)
            col.pack(side="left", expand=True)
            tk.Label(col, text=val, bg=CARD, fg=INK, font=self.f_stat).pack()
            tk.Label(col, text=lab, bg=CARD, fg=INK2, font=self.f_tiny).pack()
        for w in self.outs_box.winfo_children():
            w.destroy()
        shown = 0
        for r in results:
            if shown >= 6 and len(results) > 7:
                shown += 1
                continue
            row = tk.Frame(self.outs_box, bg=CARD)
            row.pack(fill="x", pady=1)
            tk.Label(row, text="PDF", bg=CARD, fg=RED, font=self.f_tiny,
                     relief="solid", padx=3, bd=0).pack(side="left")
            tk.Label(row, text=" " + (r.pdf_path.name if r.pdf_path else "（未生成）"),
                     bg=CARD, fg=INK, font=self.f_small, anchor="w").pack(side="left")
            tk.Label(row, text=f"{len(r.frames)} 页 · AI 总结 {'✓' if r.summary_md else '—'}",
                     bg=CARD, fg=INK2, font=self.f_tiny).pack(side="right")
            shown += 1
        if fails:
            for exc in fails[:3]:
                row = tk.Frame(self.outs_box, bg=CARD)
                row.pack(fill="x", pady=1)
                tk.Label(row, text=f"✗ 失败：{exc}", bg=CARD, fg=RED,
                         font=self.f_tiny, anchor="w").pack(anchor="w")
        if results:
            self.last_outdir = results[-1].outdir
            self.open_btn.configure(state="normal")
            self.open_btn2.configure(state="normal")
        self.start_btn.configure(state="normal" if self.videos else "disabled")
        self.stop_btn.configure(state="disabled")
        self._close_logfile()

    # ---------- 日志文件 ----------
    def _open_logfile(self):
        try:
            d = logs_dir()
            d.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self.log_fh = open(d / f"chalkpress-{stamp}.log", "a", encoding="utf-8")
        except OSError:
            self.log_fh = None

    def _log(self, text):
        if self.log_fh:
            try:
                self.log_fh.write(text + "\n")
                self.log_fh.flush()
            except OSError:
                pass

    def _close_logfile(self):
        if self.log_fh:
            try:
                self.log_fh.close()
            except OSError:
                pass
            self.log_fh = None

    def open_output(self):
        if self.last_outdir:
            _open_in_explorer(self.last_outdir)

    # ---------- 更新 ----------
    def _auto_check_updates(self):
        if self.auto_update_val:
            self._do_check(quiet=True)

    def check_updates(self):
        self.upd_status.configure(text="正在检查更新 …")
        self._do_check(quiet=False)

    def _do_check(self, quiet):
        if self.upd_checking:
            return
        self.upd_checking = True

        def work():
            try:
                info = fetch_latest()
                self.log_q.put(("upd_info", info, quiet))
            except Exception as exc:
                self.log_q.put(("upd_fail", str(exc), quiet))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_info(self, info, quiet):
        self.upd_checking = False
        if not info:
            if not quiet:
                self.upd_status.configure(text="未能获取版本信息")
            return
        if not is_newer(info["version"], __version__):
            if not quiet:
                self.upd_status.configure(text=f"已是最新版本（v{__version__}）")
            return
        self.upd_hint.configure(text=f"有新版本 v{info['version']} →")
        self.upd_status.configure(text=f"发现新版本 v{info['version']}，开始下载 …")
        asset = pick_asset(info["assets"])
        if not asset:
            self.upd_status.configure(text="暂无当前平台的安装包")
            return

        def prog(received, total_):
            self.log_q.put(("upd_prog", received * 100 // max(total_, 1), None))

        def work():
            try:
                path = download(asset["url"], Path.home() / "Downloads", prog)
                self.log_q.put(("upd_done", path, None))
            except Exception as exc:
                self.log_q.put(("upd_fail", str(exc), False))

        threading.Thread(target=work, daemon=True).start()

    # ---------- 事件泵 ----------
    def _poll(self):
        try:
            while True:
                item = self.log_q.get_nowait()
                kind = item[0]
                if kind == "progress":
                    _ev, data = item[1], item[2]
                    self._on_progress(_ev, data)
                elif kind == "done":
                    self._close_logfile()
                elif kind == "failed":
                    self._log("错误：" + item[1])
                    self.nowline.configure(text="✗ " + item[1], fg=RED)
                    self.start_btn.configure(
                        state="normal" if self.videos else "disabled")
                    self.stop_btn.configure(state="disabled")
                    self._close_logfile()
                elif kind == "upd_info":
                    self._on_update_info(item[1], item[2])
                elif kind == "upd_prog":
                    self.upd_status.configure(text=f"下载中 {item[1]}%")
                elif kind == "upd_done":
                    self.upd_status.configure(text=f"已下载：{item[1].name}")
                    reveal(item[1])
                    messagebox.showinfo(
                        "更新已下载",
                        f"安装包已下载到下载文件夹：\n{item[1]}\n\n打开并按提示安装后重启 Chalkpress 即可。")
                elif kind == "upd_fail":
                    self.upd_checking = False
                    self.upd_status.configure(text="更新检查失败：" + item[1])
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel("退出", "正在转换中，确定退出？"):
                return
            self.cancel.set()
        self._close_logfile()
        self.root.destroy()


def _set_combo(cb: ttk.Combobox, pairs, value):
    """按值选中 Combobox 项；value=None 时选中第一项。"""
    display = {v: k for k, v in pairs}
    key = value if value is not None else "__auto__" if pairs is ASR_MODELS else pairs[0][1]
    if key in display:
        cb.set(display[key])
    elif pairs:
        cb.set(pairs[0][0])


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
