# Chalkpress Tauri 2 前端重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Tauri 2 壳 + Svelte 5 前端替换 tkinter GUI，Python 流水线保留为 stdio JSON sidecar。

**Architecture:** Tauri 通过 shell 插件把 PyInstaller 打包的 `chalkpress-core` 作为 sidecar 子进程拉起，stdin/stdout 行 JSON 通信；前端单页工作台（投放区即首页），设置滑出面板，Tauri updater 应用内静默更新。

**Tech Stack:** Tauri 2 / Svelte 5 + Vite + TypeScript / Python(现有包) + PyInstaller / pytest

**Spec:** `docs/superpowers/specs/2026-10-10-tauri-frontend-design.md`

## Global Constraints

- Python 流水线代码零改动；仅允许新增 `chalkpress/ipc.py`、修改 `chalkpress/config.py`（新增函数）。
- IPC 协议：stdin/stdout 每行一个 JSON（UTF-8）；请求 `{id, method, params}`，响应 `{id, result}` 或 `{id, error}`；事件 `{event, ...data}` 无 id。
- 主色 `#4F5BD5`，浅色底；窗口 980×680，min 880×600。
- 更新源：`https://github.com/luolin1024/chalkpress/releases/latest/download/latest.json`（注意全小写仓库名）。
- 打包产物：Windows NSIS / macOS dmg / Linux AppImage。
- 包管理器 pnpm；Python 侧零新增运行时依赖。
- 退役文件（Task 10 前不得提前删除）：`chalkpress/gui.py`、`chalkpress/_icon.py`、`chalkpress/update.py`、`run_gui.py`、`packaging/chalkpress.iss`、`chalkpress.spec`。

---

### Task 1: settings 归一化函数迁入 config.py

**Files:**
- Modify: `chalkpress/config.py`（文件末尾追加）
- Test: `tests/test_config.py`（新建，tests/ 目录新建）

**Interfaces:**
- Consumes: 现有 `load_config_file()` / `save_config_file()`（不改动）。
- Produces: `normalize_settings(raw: dict) -> dict`——Task 2 的 `settings.set` 处理器调用；输出结构：`{"options": {"summary_lang","zh_script","auto_correct"[,"asr_model","scene_threshold","min_gap"]}, "app": {"keep_log": bool}[, "llm": {"api_base","api_key","model"}]}`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_config.py
from chalkpress.config import normalize_settings


def test_normalize_defaults():
    cfg = normalize_settings({})
    assert cfg == {"options": {"summary_lang": "zh", "zh_script": "auto",
                               "auto_correct": True},
                   "app": {"keep_log": True}}


def test_normalize_optional_fields():
    raw = {"options": {"summary_lang": "en", "asr_model": "small",
                       "scene_threshold": 0.05, "min_gap": 5.0,
                       "auto_correct": False},
           "app": {"keep_log": False},
           "llm": {"api_base": " https://api.example.com/v1 ", "api_key": "sk-1",
                   "model": "gpt-4o-mini"}}
    cfg = normalize_settings(raw)
    assert cfg["options"]["asr_model"] == "small"
    assert cfg["options"]["scene_threshold"] == 0.05
    assert cfg["options"]["auto_correct"] is False
    assert cfg["app"] == {"keep_log": False}
    assert cfg["llm"]["api_base"] == "https://api.example.com/v1"


def test_normalize_partial_llm_dropped():
    """llm 三项缺一不可，否则整体丢弃（与旧 GUI 行为一致）。"""
    cfg = normalize_settings({"llm": {"api_base": "https://x", "api_key": "k"}})
    assert "llm" not in cfg


def test_normalize_none_fields_dropped():
    cfg = normalize_settings({"options": {"asr_model": None, "min_gap": None}})
    assert "asr_model" not in cfg["options"]
    assert "min_gap" not in cfg["options"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL（`ImportError: cannot import name 'normalize_settings'`）

- [ ] **Step 3: 实现**

```python
# chalkpress/config.py 末尾追加
def normalize_settings(raw: dict) -> dict:
    """前端提交的散装配置 → 规范 config.toml 结构（原 GUI _save_settings 逻辑）。"""
    o = raw.get("options", {})
    app = raw.get("app", {})
    llm = raw.get("llm", {})
    options = {
        "summary_lang": o.get("summary_lang", "zh"),
        "zh_script": o.get("zh_script", "auto"),
        "auto_correct": bool(o.get("auto_correct", True)),
    }
    for k in ("asr_model", "scene_threshold", "min_gap"):
        if o.get(k) is not None:
            options[k] = o[k]
    cfg: dict = {"options": options,
                 "app": {"keep_log": bool(app.get("keep_log", True))}}
    base = (llm.get("api_base") or "").strip()
    key = (llm.get("api_key") or "").strip()
    model = (llm.get("model") or "").strip()
    if base and key and model:
        cfg["llm"] = {"api_base": base, "api_key": key, "model": model}
    return cfg
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_config.py chalkpress/config.py
git commit -m "feat(config): normalize_settings 迁移 GUI 设置归一化逻辑"
```

---

### Task 2: chalkpress/ipc.py — stdio 行 JSON IPC 服务

**Files:**
- Create: `chalkpress/ipc.py`
- Test: `tests/test_ipc.py`

**Interfaces:**
- Consumes: `config.load_config_file/save_config_file/normalize_settings/load_llm_config/logs_dir`；`pipeline.Options/run_batch`（`run_batch(opt, videos, log=, cancel_check=, progress=)`，progress 回调签名 `progress(event: str, **data)`，会自发 `batch_done`）。
- Produces:
  - `IPCServer(stdin, stdout)`：`.handle(req: dict) -> dict`（同步请求）、`.serve()`（stdin 循环，供 `python -m chalkpress.ipc`）
  - 协议：响应 `{"id": req_id, "result": ...}` / `{"id": req_id, "error": "..."}`；事件 `{"event": name, **data}`
  - 方法：`settings.get` / `settings.set` / `convert.start {videos, options}` / `convert.cancel`
  - `main()` 入口：日志全部导流 stderr

- [ ] **Step 1: 写失败测试**

```python
# tests/test_ipc.py
import io
import json
import time

from chalkpress.ipc import sanitize_progress


def make_server():
    from chalkpress.ipc import IPCServer
    return IPCServer(stdin=io.StringIO(), stdout=io.StringIO())


def lines(server):
    out = server.stdout.getvalue()
    return [json.loads(l) for l in out.splitlines() if l.strip()]


def test_unknown_method_returns_error():
    s = make_server()
    resp = s.handle({"id": 1, "method": "nope"})
    assert resp["id"] == 1 and "unknown method" in resp["error"]


def test_settings_roundtrip(tmp_path, monkeypatch):
    import chalkpress.config as config
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.toml")
    s = make_server()
    s.handle({"id": 1, "method": "settings.set",
              "params": {"options": {"summary_lang": "en"}, "app": {}}})
    resp = s.handle({"id": 2, "method": "settings.get"})
    assert resp["result"]["options"]["summary_lang"] == "en"
    assert resp["result"]["llm_configured"] is False


def test_convert_start_empty_batch_emits_batch_done():
    s = make_server()
    s.handle({"id": 1, "method": "convert.start", "params": {"videos": []}})
    deadline = time.time() + 5
    while s.worker.is_alive() and time.time() < deadline:
        time.sleep(0.02)
    evs = [m["event"] for m in lines(s) if "event" in m]
    assert evs[-1] == "batch_done"


def test_cancel_sets_event():
    s = make_server()
    s.handle({"id": 1, "method": "convert.cancel"})
    assert s.cancel.is_set()


def test_serve_skips_non_json_lines():
    from chalkpress.ipc import IPCServer
    stdin = io.StringIO('not json\n{"id":1,"method":"nope"}\n\n')
    out = io.StringIO()
    s = IPCServer(stdin=stdin, stdout=out)
    s.serve()
    msgs = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    assert len(msgs) == 1 and "error" in msgs[0]


def test_sanitize_progress_result_to_dict():
    """Result 数据类不可 JSON 序列化，必须展平为标量字段。"""
    class FakeResult:
        frames = [1, 2, 3]
        summary_md = "# t"
        outdir = None
    ev, kw = sanitize_progress("video_done", {"index": 1, "result": FakeResult()})
    assert ev == "video_done"
    assert "result" not in kw
    assert kw["pages"] == 3 and kw["summary"] is True
    json.dumps(kw)  # 必须可序列化
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_ipc.py -v`
Expected: FAIL（`ModuleNotFoundError: chalkpress.ipc`）

- [ ] **Step 3: 实现**

```python
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
                    "llm_configured": load_llm_config() is not None}
        if method == "settings.set":
            save_config_file(normalize_settings(params))
            return {}
        if method == "convert.start":
            self._start(params)
            return {}
        if method == "convert.cancel":
            self.cancel.set()
            return {}
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
                log.warning("丢弃非 JSON 行: %.80s", line)  # 第三方库污染 stdout 时兜底
                continue
            self.send(self.handle(req))


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
    IPCServer().serve()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_ipc.py tests/test_config.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 手动冒烟**

```bash
echo '{"id":1,"method":"settings.get"}' | python -m chalkpress.ipc
```
Expected: stdout 一行 `{"id": 1, "result": {...}}`；无其它 stdout 输出。

- [ ] **Step 6: Commit**

```bash
git add chalkpress/ipc.py tests/test_ipc.py
git commit -m "feat(ipc): stdio 行 JSON sidecar 服务（settings/convert/cancel）"
```

---

### Task 3: Tauri 2 + Svelte 5 脚手架

**Files:**
- Create: `package.json`、`vite.config.ts`、`svelte.config.js`、`tsconfig.json`、`index.html`、`src/main.ts`、`src/App.svelte`（占位）、`src/app.css`
- Create: `src-tauri/Cargo.toml`、`src-tauri/build.rs`、`src-tauri/tauri.conf.json`、`src-tauri/capabilities/default.json`、`src-tauri/src/main.rs`、`src-tauri/src/lib.rs`、`src-tauri/.gitignore`
- Modify: `.gitignore`

**Interfaces:**
- Produces: 可构建的前端骨架；`src-tauri/binaries/chalkpress-core-<triple>` 为 sidecar 约定路径（Task 4 产出）；后续任务的组件都挂载在 `src/App.svelte`。

- [ ] **Step 1: 前端工程文件**

```json
// package.json
{
  "name": "chalkpress",
  "private": true,
  "version": "0.3.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "tauri": "tauri"
  },
  "dependencies": {
    "@tauri-apps/api": "^2",
    "@tauri-apps/plugin-dialog": "^2",
    "@tauri-apps/plugin-opener": "^2",
    "@tauri-apps/plugin-shell": "^2",
    "@tauri-apps/plugin-updater": "^2"
  },
  "devDependencies": {
    "@sveltejs/vite-plugin-svelte": "^5",
    "@tauri-apps/cli": "^2",
    "svelte": "^5",
    "tslib": "^2",
    "typescript": "^5",
    "vite": "^6"
  }
}
```

```ts
// vite.config.ts
import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  plugins: [svelte()],
  clearScreen: false,
  server: { port: 5173, strictPort: true },
  build: { target: "es2022" },
});
```

```js
// svelte.config.js
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";
export default { preprocess: vitePreprocess() };
```

```json
// tsconfig.json
{
  "compilerOptions": {
    "target": "ES2022", "module": "ESNext", "moduleResolution": "bundler",
    "strict": true, "noEmit": true, "skipLibCheck": true,
    "types": ["vite/client"], "verbatimModuleSyntax": true
  },
  "include": ["src"]
}
```

```html
<!-- index.html -->
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <title>Chalkpress</title>
    <link rel="stylesheet" href="/src/app.css" />
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

```ts
// src/main.ts
import { mount } from "svelte";
import App from "./App.svelte";

mount(App, { target: document.getElementById("app")! });
```

```svelte
<!-- src/App.svelte（占位，Task 6 重写） -->
<main><h1>Chalkpress</h1></main>
```

```css
/* src/app.css —— 设计令牌，全项目共用 */
:root {
  --accent: #4f5bd5;
  --accent-dk: #4348b8;
  --accent-bg: #edefff;
  --bg: #f5f6fa;
  --card: #ffffff;
  --ink: #1d1d1f;
  --ink2: #6e6e73;
  --faint: #a6a6ad;
  --line: #e2e4ee;
  --red: #c4453c;
  --radius: 12px;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
       font: 14px/1.5 -apple-system, "Segoe UI", "PingFang SC",
             "Microsoft YaHei UI", sans-serif; }
```

- [ ] **Step 2: Rust/Tauri 工程文件**

```toml
# src-tauri/Cargo.toml
[package]
name = "chalkpress"
version = "0.3.0"
edition = "2021"

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-dialog = "2"
tauri-plugin-opener = "2"
tauri-plugin-shell = "2"
tauri-plugin-updater = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
```

```rust
// src-tauri/build.rs
fn main() { tauri_build::build() }
```

```rust
// src-tauri/src/main.rs
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() { chalkpress_lib::run() }
```

```rust
// src-tauri/src/lib.rs
// sidecar 由前端 startCore() 通过 Command.sidecar 拉起（前端要直接订阅 stdout，
// 不在 Rust 端重复 spawn，避免两个 core 进程）。
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

```json
// src-tauri/tauri.conf.json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "Chalkpress",
  "version": "0.3.0",
  "identifier": "org.chalkpress.app",
  "build": {
    "beforeDevCommand": "pnpm dev",
    "devUrl": "http://localhost:5173",
    "beforeBuildCommand": "pnpm build",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [
      { "title": "Chalkpress", "width": 980, "height": 680,
        "minWidth": 880, "minHeight": 600 }
    ],
    "security": { "csp": null }
  },
  "bundle": {
    "active": true,
    "targets": ["nsis", "dmg", "appimage"],
    "icon": ["icons/32x32.png", "icons/128x128.png", "icons/icon.ico", "icons/icon.icns"],
    "externalBin": ["binaries/chalkpress-core"],
    "createUpdaterArtifacts": true
  }
}
```

注意：updater 的 `plugins.updater` 配置块（endpoints + pubkey）在 Task 8 加入；先不写，避免无签名构建失败。

```json
// src-tauri/capabilities/default.json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "dialog:default",
    "opener:default",
    "updater:default",
    {
      "identifier": "shell:allow-execute",
      "allow": [
        { "name": "binaries/chalkpress-core", "sidecar": true }
      ]
    }
  ]
}
```

```gitignore
# src-tauri/.gitignore
/target/
/gen/schemas/
```

- [ ] **Step 3: icons 与 gitignore**

```bash
pnpm install
python packaging/make_icons.py            # 产出 packaging/icon_1024.png（已有）
pnpm tauri icon packaging/icon_1024.png   # 生成 src-tauri/icons/* 全平台图标
grep -qx "node_modules/" .gitignore || echo "node_modules/" >> .gitignore
grep -qx "dist/" .gitignore || echo "dist/" >> .gitignore
grep -qx "src-tauri/binaries/" .gitignore || echo "src-tauri/binaries/" >> .gitignore
```

- [ ] **Step 4: 验证构建**

Run: `pnpm build && cargo check --manifest-path src-tauri/Cargo.toml`
Expected: vite 构建成功；cargo check 通过（icons 已生成才能过）。

- [ ] **Step 5: Commit**

```bash
git add package.json pnpm-lock.yaml vite.config.ts svelte.config.js tsconfig.json index.html src src-tauri .gitignore
git commit -m "feat(tauri): Tauri 2 + Svelte 5 脚手架（窗口/插件/能力声明）"
```

---

### Task 4: sidecar 构建脚本

**Files:**
- Create: `packaging/build_sidecar.py`

**Interfaces:**
- Produces: `python packaging/build_sidecar.py [--dev]`——PyInstaller 打包 `chalkpress/ipc.py` 为 `src-tauri/binaries/chalkpress-core-<target-triple>[.exe]`（`--dev` 额外复制一份无 triple 后缀的 `chalkpress-core`，便于 CI 调试）；内嵌 whisper 模型；CI（Task 9）与 `pnpm tauri dev` 都靠它产出二进制。

- [ ] **Step 1: 实现**

```python
#!/usr/bin/env python3
"""构建 Tauri sidecar：PyInstaller 打包 chalkpress.ipc，输出到 src-tauri/binaries/。

用法：python packaging/build_sidecar.py [--dev]
--dev 额外产出无 target-triple 后缀的副本（调试用）。
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MODEL_DIR = ROOT / "build" / "model"
OUT = ROOT / "src-tauri" / "binaries"


def target_triple() -> str:
    out = subprocess.check_output(["rustc", "-vV"], text=True)
    return next(l.split(": ", 1)[1].strip() for l in out.splitlines()
                if l.startswith("host:"))


def ensure_model():
    if MODEL_DIR.is_dir() and any(MODEL_DIR.iterdir()):
        return
    print("下载 whisper-small 模型到 build/model ...", file=sys.stderr)
    from huggingface_hub import snapshot_download
    snapshot_download("Systran/faster-whisper-small", local_dir=str(MODEL_DIR))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", action="store_true")
    args = ap.parse_args()
    ensure_model()
    OUT.mkdir(parents=True, exist_ok=True)
    sep = ";" if sys.platform == "win32" else ":"
    triple = target_triple()
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile",
        "--name", f"chalkpress-core-{triple}" if not args.dev else "chalkpress-core-dev",
        "--collect-all", "faster_whisper", "--collect-all", "ctranslate2",
        "--collect-all", "imageio_ffmpeg", "--collect-all", "onnxruntime",
        "--collect-all", "tokenizers", "--collect-all", "av",
        "--add-data", f"{MODEL_DIR}{sep}models/faster-whisper-small",
        "--distpath", str(OUT), "--workpath", str(ROOT / "build" / "pyi"),
        "--specpath", str(ROOT / "build" / "pyi"),
        str(ROOT / "chalkpress" / "ipc.py"),
    ], check=True, cwd=ROOT)
    # onefile：Tauri externalBin 要求单个可执行文件；启动解压稍慢是可接受的代价


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 本地验证**

```bash
pip install pyinstaller huggingface_hub   # 如未装
python packaging/build_sidecar.py --dev
echo '{"id":1,"method":"settings.get"}' | src-tauri/binaries/chalkpress-core-*
```
Expected: stdout 一行 JSON 响应（模型下载首次较慢，属预期）。

- [ ] **Step 3: Commit**

```bash
git add packaging/build_sidecar.py
git commit -m "feat(packaging): PyInstaller 构建 Tauri sidecar（triple 命名 + 模型内嵌）"
```

---

### Task 5: 前端 IPC client 与状态 store

**Files:**
- Create: `src/lib/ipc.ts`、`src/lib/state.svelte.ts`

**Interfaces:**
- Consumes: Task 2 的协议；Task 3 的 shell 插件。sidecar 由本任务 `startCore()` 独自负责拉起（Rust 端不 spawn，见 Task 3 lib.rs 注释）。
- Produces:
  - `startCore(): Promise<void>`、`request<T>(method, params?): Promise<T>`、`onEvent(h: (ev: any) => void): () => void`、`onCoreExit(h: () => void): () => void`
  - `app` 响应式状态：`{videos: string[], phase: 'idle'|'running'|'done'|'error', err: string, run: {index,total,name,stages: Record<string,'todo'|'doing'|'done'>, pages: number, pct: number}, results: {name: string, pages: number, summary: boolean}[], outdir: string | null}`

- [ ] **Step 1: 实现 ipc.ts**

```ts
// src/lib/ipc.ts
import { Command } from "@tauri-apps/plugin-shell";

type Pending = { resolve: (v: any) => void; reject: (e: Error) => void };

let cmd: Command<any> | null = null;
let seq = 0;
const pending = new Map<number, Pending>();
const eventHandlers = new Set<(ev: any) => void>();
const exitHandlers = new Set<() => void>();

export async function startCore(): Promise<void> {
  if (cmd) return;
  cmd = Command.sidecar("binaries/chalkpress-core");
  cmd.stdout.on("data", (line: string) => {
    for (const l of line.split("\n")) {
      const t = l.trim();
      if (!t) continue;
      let msg: any;
      try { msg = JSON.parse(t); } catch { continue; }  // 非 JSON 行丢弃
      if (msg.event !== undefined) {
        eventHandlers.forEach((h) => h(msg));
      } else {
        const p = pending.get(msg.id);
        pending.delete(msg.id);
        if (p) msg.error ? p.reject(new Error(msg.error)) : p.resolve(msg.result);
      }
    }
  });
  cmd.stderr.on("data", (l: string) => console.error("[core]", l));
  cmd.on("close", () => {
    pending.forEach((p) => p.reject(new Error("core 已退出")));
    pending.clear();
    exitHandlers.forEach((h) => h());
  });
  await cmd.spawn();
}

export function request<T = any>(method: string, params?: object): Promise<T> {
  if (!cmd) return Promise.reject(new Error("core 未启动"));
  const id = ++seq;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    cmd!.write(JSON.stringify({ id, method, params: params ?? {} }) + "\n");
  });
}

export function onEvent(h: (ev: any) => void): () => void {
  eventHandlers.add(h);
  return () => eventHandlers.delete(h);
}

export function onCoreExit(h: () => void): () => void {
  exitHandlers.add(h);
  return () => exitHandlers.delete(h);
}
```

- [ ] **Step 2: 实现 state.svelte.ts（Svelte 5 runes）**

```ts
// src/lib/state.svelte.ts
export type Phase = "idle" | "running" | "done" | "error";

export const app = $state({
  videos: [] as string[],
  phase: "idle" as Phase,
  err: "",
  run: {
    index: 0, total: 0, name: "", pages: 0, pct: 0,
    stages: {} as Record<string, "todo" | "doing" | "done">,
  },
  results: [] as { name: string; pages: number; summary: boolean }[],
  outdir: null as string | null,
});

export const STAGES = [
  ["asr", "语音转写"], ["correct", "字幕校对"], ["frames", "关键帧对齐"],
  ["summary", "AI 总结"], ["pdf", "生成 PDF"],
] as const;

// 各阶段权重（本视频进度百分比），与旧 GUI 一致
export const WEIGHTS: Record<string, number> = {
  asr: 45, correct: 10, frames: 25, summary: 12, pdf: 8,
};

export function resetRun() {
  app.run = { index: 0, total: 0, name: "", pages: 0, pct: 0, stages: {} };
  app.results = [];
  app.err = "";
}

// 本视频进度由阶段状态推导：完成阶段全额、进行中阶段记一半
export function computePct(stages: Record<string, string>): number {
  let w = 0;
  for (const [k, weight] of Object.entries(WEIGHTS)) {
    if (stages[k] === "done") w += weight;
    else if (stages[k] === "doing") w += weight / 2;
  }
  return Math.min(100, Math.round(w));
}
```

- [ ] **Step 3: 类型检查**

Run: `pnpm build`
Expected: vite 构建通过（App.svelte 仍是占位）。

- [ ] **Step 4: Commit**

```bash
git add src/lib
git commit -m "feat(ui): sidecar IPC client 与转换状态 store"
```

---

### Task 6: 单页工作台 UI（空闲态 / 运行态 / 完成态）

**Files:**
- Modify: `src/App.svelte`（整文件替换）
- Create: `src/components/RunPanel.svelte`、`src/components/ResultsCard.svelte`

**Interfaces:**
- Consumes: Task 5 的 `request/onEvent/startCore` 与 `app/STAGES/resetRun`；Task 7 将挂载 `<SettingsSheet>`（本任务先留 `{#if settingsOpen}` 空位与 `settingsOpen` 变量）。
- Produces: `App.svelte` 导出零接口（根组件）；进度事件 → `app.run`/`app.results` 的映射逻辑在 `App.svelte` 的 `onMount` 中。

- [ ] **Step 1: App.svelte（根组件 + 事件映射 + 空闲态）**

```svelte
<!-- src/App.svelte -->
<script lang="ts">
  import { onMount } from "svelte";
  import { open } from "@tauri-apps/plugin-dialog";
  import { request, startCore, onEvent, onCoreExit } from "./lib/ipc";
  import { app, resetRun, STAGES, computePct } from "./lib/state";
  import RunPanel from "./components/RunPanel.svelte";
  import ResultsCard from "./components/ResultsCard.svelte";

  let settingsOpen = false;
  let coreDown = false;

  async function addFiles() {
    const sel = await open({ multiple: true,
      filters: [{ name: "视频", extensions: ["mp4","mov","mkv","webm","avi","m4v","flv","ts"] }] });
    if (sel) for (const f of [].concat(sel as any)) addVideo(f as string);
  }
  async function addFolder() {
    const dir = await open({ directory: true });
    if (!dir) return;
    const { videos } = await request<{ videos: string[] }>("fs.list_videos", { dir });
    for (const v of videos) addVideo(v);
  }
  function addVideo(p: string) {
    if (!app.videos.includes(p)) app.videos.push(p);
  }
  function removeVideo(p: string) {
    app.videos = app.videos.filter((v) => v !== p);
  }

  async function start() {
    if (!app.videos.length) return;
    resetRun();
    app.phase = "running";
    for (const [k] of STAGES) app.run.stages[k] = "todo";
    try {
      // 选项与 keep_log 以当前持久化设置为准
      const s = await request<{ options: any; app: any }>("settings.get");
      await request("convert.start",
                    { videos: app.videos, options: s.options, app: s.app });
    } catch (e: any) {
      app.phase = "error"; app.err = String(e.message ?? e);
    }
  }
  async function stop() { await request("convert.cancel"); }

  onMount(async () => {
    try { await startCore(); } catch { coreDown = true; }
    onEvent((ev) => {
      switch (ev.event) {
        case "video_start":
          app.run.index = ev.index; app.run.total = ev.total; app.run.name = ev.name;
          for (const [k] of STAGES) app.run.stages[k] = "todo";
          app.run.pages = 0;
          break;
        case "stage":
          app.run.stages[ev.key] = "doing";
          app.run.pct = computePct(app.run.stages);
          break;
        case "stage_done":
          app.run.stages[ev.key] = "done";
          app.run.pct = computePct(app.run.stages);
          break;
        case "frames": app.run.pages = ev.count; break;
        case "video_done":
          app.results.push({ name: ev.name ?? app.run.name,
                             pages: ev.pages ?? 0, summary: !!ev.summary });
          if (ev.outdir) app.outdir = ev.outdir;
          break;
        case "video_error": app.err = `${ev.name}：${ev.error}`; break;
        case "batch_error": app.phase = "error"; app.err = ev.error; break;
        case "batch_done": app.phase = "done"; break;
      }
    });
    onCoreExit(() => { coreDown = true; });
  });
</script>

{#if coreDown}
  <div class="corebar">转换引擎未启动，请重启应用；若持续出现请重新安装。</div>
{/if}

<main class="wrap">
  <header>
    <div class="brand"><span class="logo"></span> Chalkpress</div>
    <button class="gear" title="设置" onclick={() => (settingsOpen = true)}>⚙</button>
  </header>

  {#if app.phase === "idle"}
    <section class="hero">
      <div class="drop" role="button" tabindex="0" onclick={addFiles}>
        <div class="drop-icon">▶</div>
        <div class="drop-title">拖入视频，或点击添加</div>
        <div class="drop-sub">支持 mp4 · mov · mkv · webm 等，可多选或整个文件夹</div>
      </div>
      <button class="ghost" onclick={addFolder}>添加文件夹</button>

      {#if app.videos.length}
        <div class="card">
          {#each app.videos as v (v)}
            <div class="vrow">
              <span class="vname">{v.split(/[\\/]/).pop()}</span>
              <span class="vsize">{v}</span>
              <button class="x" onclick={() => removeVideo(v)}>✕</button>
            </div>
          {/each}
          <div class="vsum">{app.videos.length} 个视频 · 讲义生成在各自视频所在文件夹</div>
        </div>
        <button class="primary" onclick={start}>开始转换</button>
      {/if}
    </section>
  {:else if app.phase === "running"}
    <RunPanel {stop} />
  {:else if app.phase === "done"}
    <ResultsCard />
  {:else}
    <section class="hero">
      <p class="err">✗ {app.err}</p>
      <button class="primary" onclick={() => (app.phase = app.results.length ? "done" : "idle")}>返回</button>
    </section>
  {/if}
</main>

<style>
  .wrap { max-width: 760px; margin: 0 auto; padding: 16px 24px 32px; }
  header { display: flex; align-items: center; justify-content: space-between; }
  .brand { font-weight: 700; font-size: 16px; display: flex; align-items: center; gap: 8px; }
  .logo { width: 22px; height: 22px; border-radius: 7px; background: var(--accent); display: inline-block; }
  .gear { border: 0; background: transparent; font-size: 18px; cursor: pointer; color: var(--ink2); }
  .hero { display: flex; flex-direction: column; align-items: center; gap: 14px; margin-top: 8vh; }
  .drop { width: 100%; background: var(--card); border: 1.5px dashed var(--faint); border-radius: var(--radius);
          padding: 44px 0 38px; text-align: center; cursor: pointer; transition: border-color .15s; }
  .drop:hover { border-color: var(--accent); }
  .drop-icon { width: 44px; height: 44px; border-radius: 12px; background: var(--accent); color: #fff;
               display: flex; align-items: center; justify-content: center; font-size: 20px; margin: 0 auto 10px; }
  .drop-title { font-weight: 600; font-size: 15px; }
  .drop-sub { color: var(--ink2); font-size: 12px; margin-top: 3px; }
  .card { width: 100%; background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 6px 16px; }
  .vrow { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--line); }
  .vname { font-weight: 500; }
  .vsize { color: var(--faint); font-size: 11px; margin-left: auto; overflow: hidden;
           text-overflow: ellipsis; white-space: nowrap; max-width: 40%; }
  .x { border: 0; background: transparent; color: var(--faint); cursor: pointer; }
  .x:hover { color: var(--red); }
  .vsum { color: var(--ink2); font-size: 12px; padding: 8px 0; }
  .primary { background: var(--accent); color: #fff; border: 0; border-radius: 10px;
             padding: 11px 28px; font-size: 15px; font-weight: 600; cursor: pointer; width: 100%; }
  .primary:hover { background: var(--accent-dk); }
  .ghost { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
           padding: 8px 18px; cursor: pointer; }
  .err { color: var(--red); }
  .corebar { background: var(--red); color: #fff; text-align: center; padding: 6px; font-size: 13px; }
</style>
```

- [ ] **Step 2: RunPanel.svelte**

```svelte
<!-- src/components/RunPanel.svelte -->
<script lang="ts">
  import { app, STAGES } from "../lib/state";
  let { stop }: { stop: () => void } = $props();
</script>

<section class="hero">
  <div class="card">
    <h3>正在转换 {app.run.index} / {app.run.total}</h3>
    <p class="now">{app.run.name}</p>
    <div class="bar"><div class="fill" style="width: {app.run.total ? (app.run.index - 1) / app.run.total * 100 : 0}%"></div></div>
    <div class="stages">
      {#each STAGES as [key, label], i (key)}
        <span class="stage {app.run.stages[key]}">{app.run.stages[key] === "done" ? "✓" : app.run.stages[key] === "doing" ? "●" : "○"} {label}</span>
        {#if i < STAGES.length - 1}<span class="arrow">→</span>{/if}
      {/each}
    </div>
    <div class="vbar">
      <span>本视频 {app.run.pct}%</span>
      <div class="bar thin"><div class="fill" style="width: {app.run.pct}%"></div></div>
    </div>
    {#if app.results.length || app.run.pages}
      <p class="pages">已生成 {app.run.pages} 页</p>
    {/if}
  </div>
  <button class="ghost" onclick={stop}>停止（当前视频完成后）</button>
</section>

<style>
  .hero { display: flex; flex-direction: column; gap: 14px; margin-top: 8vh; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 20px; }
  h3 { margin: 0 0 4px; }
  .now { color: var(--ink2); font-size: 13px; margin: 0 0 12px; }
  .stages { display: flex; gap: 8px; margin: 14px 0; flex-wrap: wrap; }
  .stage { font-size: 12px; color: var(--faint); }
  .stage.doing { color: var(--ink); font-weight: 600; }
  .stage.done { color: var(--accent-dk); }
  .arrow { color: var(--faint); font-size: 12px; }
  .bar { height: 6px; background: var(--accent-bg); border-radius: 3px; overflow: hidden; }
  .bar.thin { height: 5px; flex: 1; }
  .fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width .3s; }
  .vbar { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--ink2); }
  .pages { color: var(--ink2); font-size: 12px; }
  .ghost { align-self: center; background: var(--card); border: 1px solid var(--line);
           border-radius: 10px; padding: 8px 18px; cursor: pointer; }
</style>
```

- [ ] **Step 3: ResultsCard.svelte**

```svelte
<!-- src/components/ResultsCard.svelte -->
<script lang="ts">
  import { openPath } from "@tauri-apps/plugin-opener";
  import { app } from "../lib/state";

  const pages = $derived(app.results.reduce((n, r) => n + r.pages, 0));
</script>

<section class="hero">
  <div class="card">
    <h3>{app.results.length} 个视频完成 🎉</h3>
    <div class="stats">
      <div><b>{app.results.length}</b><span>讲义 PDF</span></div>
      <div><b>{pages}</b><span>讲义页数</span></div>
    </div>
    {#each app.results as r (r.name)}
      <div class="row"><span class="pdf">PDF</span> {r.name} <span class="meta">{r.pages} 页 · AI 总结 {r.summary ? "✓" : "—"}</span></div>
    {/each}
    {#if app.outdir}
      <button class="primary" onclick={() => openPath(app.outdir!)}>打开输出文件夹</button>
    {/if}
  </div>
</section>

<style>
  .hero { margin-top: 8vh; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 20px; }
  .stats { display: flex; gap: 28px; margin: 12px 0; }
  .stats b { font-size: 22px; display: block; }
  .stats span { color: var(--ink2); font-size: 12px; }
  .row { padding: 7px 0; border-bottom: 1px solid var(--line); font-size: 13px; }
  .pdf { color: var(--red); font-size: 11px; border: 1px solid var(--red); border-radius: 4px; padding: 0 4px; }
  .meta { color: var(--ink2); font-size: 12px; float: right; }
  .primary { margin-top: 14px; background: var(--accent); color: #fff; border: 0;
             border-radius: 10px; padding: 10px 22px; font-weight: 600; cursor: pointer; }
</style>
```

- [ ] **Step 4: 补 `fs.list_videos` 方法（Task 2 的 ipc.py 增量修改）**

`video_done` 事件的 `pages/summary/outdir` 已由 Task 2 的 `sanitize_progress` 处理，前端无需额外逻辑。此处只补目录枚举——dialog 插件返回目录后，前端无法读文件系统，由 sidecar 枚举：

`chalkpress/ipc.py` 的 `dispatch` 增加：

```python
if method == "fs.list_videos":
    d = Path(params["dir"]).expanduser()
    return {"videos": sorted(str(p) for p in d.iterdir()
                             if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm",
                                                     ".avi", ".m4v", ".flv", ".ts"})}
```

（前端 `addFolder` 已在 Step 1 写好调用。）

`tests/test_ipc.py` 追加：

```python
def test_fs_list_videos(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.txt").write_text("x")
    s = make_server()
    resp = s.handle({"id": 1, "method": "fs.list_videos", "params": {"dir": str(tmp_path)}})
    assert resp["result"]["videos"] == [str(tmp_path / "a.mp4")]
```

- [ ] **Step 5: 全量测试 + 构建验证**

Run: `python -m pytest tests/ -v && pnpm build`
Expected: 全部 PASS；vite 构建通过。

- [ ] **Step 6: Commit**

```bash
git add src chalkpress/ipc.py tests/test_ipc.py
git commit -m "feat(ui): 单页工作台（投放/进度/成果三态）+ fs.list_videos"
```

---

### Task 7: 设置滑出面板（SettingsSheet）

**Files:**
- Create: `src/components/SettingsSheet.svelte`
- Modify: `src/App.svelte`（挂载 `{#if settingsOpen}<SettingsSheet on:close …/>{/if}`；Svelte 5 用 props 回调 `onClose`）

**Interfaces:**
- Consumes: `request("settings.get")` / `request("settings.set", cfg)`；`openPath`（@tauri-apps/plugin-opener）打开日志目录——日志目录路径由 `settings.get` 响应附带（Task 2 `settings.get` 的 result 增加 `"logs_dir": str(logs_dir())`）。
- Produces: `<SettingsSheet onClose: () => void />`

- [ ] **Step 1: Task 2 小改——settings.get 附带 logs_dir**

`chalkpress/ipc.py` 的 `settings.get` 分支改为：

```python
if method == "settings.get":
    cfg = load_config_file()
    return {"options": cfg.get("options", {}),
            "app": cfg.get("app", {}),
            "llm": cfg.get("llm", {}),
            "llm_configured": load_llm_config() is not None,
            "logs_dir": str(logs_dir())}
```

- [ ] **Step 2: SettingsSheet.svelte**

```svelte
<!-- src/components/SettingsSheet.svelte -->
<script lang="ts">
  import { openPath } from "@tauri-apps/plugin-opener";
  import { request } from "../lib/ipc";

  let { onClose }: { onClose: () => void } = $props();

  let s = $state<any>(null);
  let saved = $state(false);

  $effect(() => {
    request("settings.get").then((r: any) => (s = r));
  });

  const save = $state({ timer: 0 as any });
  function touch() {
    saved = false;
    clearTimeout(save.timer);
    save.timer = setTimeout(flush, 400);   // 输入防抖，改动即时保存
  }
  async function flush() {
    await request("settings.set", { options: s.options, app: s.app, llm: s.llm });
    saved = true;
  }
</script>

{#if s}
  <div class="mask" onclick={onClose}></div>
  <aside class="sheet">
    <header><h2>设置</h2><button class="x" onclick={onClose}>✕</button></header>
    <p class="hint">改动即时保存{saved ? " · 已保存 ✓" : ""}</p>

    <h3>输出</h3>
    <label>输出语言（AI 总结）
      <select bind:value={s.options.summary_lang} onchange={touch}>
        <option value="zh">简体中文</option><option value="zh-en">中英对照</option><option value="en">English</option>
      </select></label>
    <label>简繁
      <select bind:value={s.options.zh_script} onchange={touch}>
        <option value="auto">自动</option><option value="simplified">简体</option><option value="traditional">繁体</option>
      </select></label>

    <h3>语音识别</h3>
    <label>字幕模型
      <select bind:value={s.options.asr_model} onchange={touch}>
        <option value={null}>自动（推荐）</option><option value="tiny">tiny（最快）</option>
        <option value="small">small（默认）</option><option value="medium">medium（最准）</option>
      </select></label>
    <label class="row">AI 字幕校对
      <input type="checkbox" bind:checked={s.options.auto_correct} onchange={touch} /></label>

    <h3>AI 分析（OpenAI 兼容接口）</h3>
    <label>接口地址<input bind:value={s.llm.api_base} oninput={touch} placeholder="不配置则跳过 AI 步骤" /></label>
    <label>API Key<input type="password" bind:value={s.llm.api_key} oninput={touch} /></label>
    <label>模型<input bind:value={s.llm.model} oninput={touch} /></label>

    <h3>关键帧（高级）</h3>
    <label>场景切换灵敏度
      <select bind:value={s.options.scene_threshold} onchange={touch}>
        <option value={null}>标准</option><option value={0.05}>更多页数（画面琐碎）</option>
        <option value={0.12}>更少页数（课件翻页少）</option>
      </select></label>
    <label>关键帧最小间隔
      <select bind:value={s.options.min_gap} onchange={touch}>
        <option value={null}>2 秒</option><option value={5}>5 秒</option><option value={10}>10 秒</option>
      </select></label>

    <h3>日志</h3>
    <label class="row">保留运行日志
      <input type="checkbox" bind:checked={s.app.keep_log} onchange={touch} /></label>
    <button class="ghost" onclick={() => openPath(s.logs_dir)}>打开日志文件夹</button>

    <h3>关于</h3>
    <p class="about">Chalkpress · 讲座视频 → 讲义 PDF<br />AGPL-3.0 开源 · 商用请联系作者</p>
  </aside>
{:else}
  <div class="mask" onclick={onClose}></div>
{/if}

<style>
  .mask { position: fixed; inset: 0; background: rgba(0,0,0,.25); }
  .sheet { position: fixed; top: 0; right: 0; bottom: 0; width: 380px; background: var(--card);
           box-shadow: -8px 0 32px rgba(0,0,0,.12); padding: 18px 22px 32px; overflow-y: auto;
           animation: slide .18s ease-out; }
  @keyframes slide { from { transform: translateX(40px); opacity: 0; } }
  header { display: flex; justify-content: space-between; align-items: center; }
  h2 { margin: 0; font-size: 17px; }
  h3 { font-size: 12px; color: var(--ink2); margin: 20px 0 6px; text-transform: none; }
  label { display: block; font-size: 13px; margin: 10px 0; }
  label.row { display: flex; justify-content: space-between; align-items: center; }
  input[type="text"], input:not([type]), input[type="password"], select {
      width: 100%; margin-top: 4px; padding: 7px 10px; border: 1px solid var(--line);
      border-radius: 8px; font: inherit; background: var(--card); }
  input:focus, select:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
  .hint { color: var(--ink2); font-size: 12px; margin: 4px 0 0; }
  .about { color: var(--ink2); font-size: 12px; }
  .x { border: 0; background: transparent; font-size: 16px; cursor: pointer; }
  .ghost { border: 1px solid var(--line); background: var(--card); border-radius: 8px;
           padding: 7px 14px; cursor: pointer; }
</style>
```

注意：`s.llm` 可能为空对象——`settings.get` 返回的 `llm` 键在未配置时是 `{}`，`bind:value={s.llm.api_base}` 会因 undefined 报错。在 `$effect` 里补默认值：`r.llm = {api_base: "", api_key: "", model: "", ...r.llm}`；`options` 同理补 `asr_model: null, scene_threshold: null, min_gap: null` 缺省。

- [ ] **Step 3: App.svelte 挂载**

在 `<main>` 之后追加：

```svelte
{#if settingsOpen}
  <SettingsSheet onClose={() => (settingsOpen = false)} />
{/if}
```

`<script>` 顶部导入 `import SettingsSheet from "./components/SettingsSheet.svelte";`

- [ ] **Step 4: 测试与构建**

Run: `python -m pytest tests/ -v && pnpm build`
Expected: PASS；构建通过。

- [ ] **Step 5: Commit**

```bash
git add src chalkpress/ipc.py
git commit -m "feat(ui): 设置滑出面板（防抖即时保存 + 日志目录）"
```

---

### Task 8: Tauri updater 接线

**Files:**
- Modify: `src-tauri/tauri.conf.json`（加 `plugins.updater`）、`src/components/SettingsSheet.svelte`（关于区加"检查更新"）、`src/App.svelte`（启动时静默检查）

**Interfaces:**
- Consumes: `@tauri-apps/plugin-updater` 的 `check()` / `update.downloadAndInstall()`。
- Produces: 应用内静默更新；Release 的 `latest.json` 由 tauri-action 在 Task 9 自动生成上传。

- [ ] **Step 1: 生成签名密钥（本地执行一次，密钥不入库）**

```bash
pnpm tauri signer generate -w ~/.tauri/chalkpress.key
# 输出末尾的 JSON 里有 "public" 字段 → 把公钥体粘贴进 tauri.conf.json
# 私钥路径 ~/.tauri/chalkpress.key 与其密码记入 GitHub Secrets（用户手工操作）：
#   TAURI_SIGNING_PRIVATE_KEY=<私钥文件内容或路径> TAURI_SIGNING_PRIVATE_KEY_PASSWORD=<密码>
```

- [ ] **Step 2: tauri.conf.json 加 updater 配置**

`plugins` 块（与 `bundle` 同级）：

```json
"plugins": {
  "updater": {
    "endpoints": [
      "https://github.com/luolin1024/chalkpress/releases/latest/download/latest.json"
    ],
    "pubkey": "<Step 1 生成的公钥，逐字粘贴>"
  }
}
```

`capabilities/default.json` 的 permissions 增加 `"updater:default"`（Task 3 已含则跳过）。

- [ ] **Step 3: 前端更新逻辑**

`src/lib/updater.ts`：

```ts
import { check, Update } from "@tauri-apps/plugin-updater";

export async function autoUpdate(): Promise<string | null> {
  try {
    const u: Update | null = await check();
    if (!u) return null;
    await u.downloadAndInstall();
    return u.version;
  } catch (e) {
    console.error("updater:", e);
    return null;
  }
}
```

`App.svelte` 的 `onMount` 里 `autoUpdate().then(v => v && alert(`已更新到 v${v}，重启后生效`))`（静默下载，装完提示重启）。SettingsSheet「关于」区加一行"当前版本见窗口标题；更新自动进行"文案即可，不做手动检查按钮（YAGNI）。

- [ ] **Step 4: 构建验证**

Run: `pnpm build && cargo check --manifest-path src-tauri/Cargo.toml`
Expected: 通过（无密钥时 `tauri build` 会失败，`cargo check` 不受影响；完整构建验证在 Task 9 CI）。

- [ ] **Step 5: Commit**

```bash
git add src src-tauri
git commit -m "feat(updater): Tauri updater 静默更新接线"
```

---

### Task 9: CI 重写（build-binaries.yml）

**Files:**
- Modify: `.github/workflows/build-binaries.yml`（build job 整体替换；release job 保留但产物路径不变）

**Interfaces:**
- Consumes: Task 4 `packaging/build_sidecar.py`；Task 3/8 的 tauri 工程。
- Produces: 三平台 NSIS/dmg/AppImage + updater 产物（`*.sig`、`latest.json`）上传 artifact；tag 推送发 Release。

- [ ] **Step 1: 替换 build job**

```yaml
# .github/workflows/build-binaries.yml —— build job 整体替换为：
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: macos-15
            artifact: chalkpress-macos-arm64
          - os: windows-latest
            artifact: chalkpress-windows-x64
          - os: ubuntu-22.04
            artifact: chalkpress-linux-x64

    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4

      - name: Install pnpm
        uses: pnpm/action-setup@v4
        with: { version: 9 }

      - name: Install Node
        uses: actions/setup-node@v4
        with: { node-version: 22, cache: pnpm }

      - name: Install Rust
        uses: dtolnay/rust-toolchain@stable

      - name: Rust cache
        uses: swatinem/rust-cache@v2
        with: { workspaces: src-tauri }

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with: { python-version: "3.13" }

      - name: Install Python deps
        shell: bash
        run: |
          unset VIRTUAL_ENV
          uv venv .venv --python 3.13 --allow-existing
          uv pip install -e . pyinstaller huggingface_hub --python .venv/bin/python || \
          uv pip install -e . pyinstaller huggingface_hub --python .venv/Scripts/python.exe

      - name: Build sidecar
        shell: bash
        run: |
          PY=.venv/bin/python; [ -f .venv/Scripts/python.exe ] && PY=.venv/Scripts/python.exe
          "$PY" packaging/build_sidecar.py

      - name: Build Tauri app
        uses: tauri-apps/tauri-action@v0
        env:
          GITHUB_TOKEN: ${{ github.token }}
          TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
          TAURI_SIGNING_PRIVATE_KEY_PASSWORD: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD }}
        with:
          # tag 推送才创建/上传 Release；main 推送只构建不出版
          tagName: ${{ startsWith(github.ref, 'refs/tags/v') && github.ref_name || '' }}
          releaseName: ${{ startsWith(github.ref, 'refs/tags/v') && github.ref_name || '' }}

      - name: Collect artifacts
        shell: bash
        run: |
          mkdir -p dist
          find src-tauri/target/release/bundle -type f \
            \( -name "*.exe" -o -name "*.dmg" -o -name "*.AppImage" \
               -o -name "*.sig" -o -name "latest.json" \) -exec cp {} dist/ \;

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: ${{ matrix.artifact }}
          path: dist/*
          if-no-files-found: error
```

release job 保持现有逻辑（main 推送刷 `latest` prerelease、tag 推送发正式 Release），`dist/*` 匹配新产物类型无需改动。

- [ ] **Step 2: 用户手工步骤（Agent 无法代做，写入 PR 描述提醒）**

GitHub 仓库 Settings → Secrets and variables → Actions 新增：
- `TAURI_SIGNING_PRIVATE_KEY`：`~/.tauri/chalkpress.key` 文件内容
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`：生成密钥时设置的密码

- [ ] **Step 3: 本地干跑校验 workflow 语法**

```bash
python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/build-binaries.yml')); print('yaml ok')"
```
Expected: `yaml ok`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/build-binaries.yml
git commit -m "ci: Tauri 三平台构建（sidecar + tauri-action + updater 签名）"
```

---

### Task 10: 退役 tkinter GUI 与旧打包链

**Files:**
- Delete: `chalkpress/gui.py`、`chalkpress/_icon.py`、`chalkpress/update.py`、`run_gui.py`、`packaging/chalkpress.iss`、`chalkpress.spec`
- Modify: `pyproject.toml`（scripts）、`README.md`（GUI 章节）

**Interfaces:**
- Consumes: 前八个任务全部完成并验收。
- Produces: 干净的仓库——CLI 与 Tauri GUI 双入口，无死代码。

- [ ] **Step 1: 确认无残留引用**

```bash
grep -rn "gui\|update\b\|_icon" chalkpress/ --include="*.py" | grep -v "gui.py\|update.py\|_icon.py" || echo "clean"
grep -rn "from .gui\|from .update\|from ._icon\|import gui\|import update" chalkpress/ run_gui.py 2>/dev/null
```
Expected: 仅 `__init__.py` 若 `__version__` 引用除外；如有引用先解。

- [ ] **Step 2: 删除退役文件**

```bash
git rm chalkpress/gui.py chalkpress/_icon.py chalkpress/update.py run_gui.py packaging/chalkpress.iss chalkpress.spec
```

- [ ] **Step 3: pyproject.toml 清理**

删除：

```toml
[project.scripts]
chalkpress-gui = "chalkpress.gui:main"
```

（`chalkpress = "chalkpress.cli:main"` 保留。）

- [ ] **Step 4: README 更新**

- 「GUI」相关描述改为 Tauri 版说明（零配置首页 + 设置中心 + 应用内自动更新），构建命令改为 `pnpm i && pnpm tauri build`（sidecar 用 `python packaging/build_sidecar.py`）
- 技术要点中"本地 ASR/简繁/可检索 PDF/配置链"保留，删除 tkinter 相关描述
- 「许可」章节不动

- [ ] **Step 5: 全量验证**

```bash
python -m pytest tests/ -v
python -m py_compile chalkpress/*.py
pnpm build
```
Expected: 全部通过；`python -m chalkpress` CLI 行为不变（手动抽测 `--help`）。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor!: 退役 tkinter GUI 与 Inno Setup 打包链，统一为 Tauri 2"
```

---

## 验收清单（三平台手动）

- [ ] 拖拽视频到窗口 → 出现在列表；点击添加/文件夹可用
- [ ] 转换全程五阶段推进、双进度条刷新、可"停止"
- [ ] 完成页显示统计与 PDF 列表，"打开输出文件夹"有效
- [ ] 设置改动 400ms 防抖后持久化（重开应用仍在）；LLM 三项配齐后转换走 AI 步骤
- [ ] 应用内更新：低版本 → 提示下载安装
- [ ] Windows：NSIS 安装包正常安装、开始菜单图标正确、无防火墙弹窗
- [ ] macOS：dmg 拖拽安装、dock 图标正确
- [ ] Linux：AppImage 可运行
