# Chalkpress 前端 Tauri 2 重构设计

日期：2026-10-10
状态：已与维护者确认

## 背景与目标

现有 GUI 为 tkinter 自绘（`chalkpress/gui.py`，约 1050 行），存在观感粗糙、动效缺失等固有限制。决定用 **Tauri 2 壳 + Web 前端** 重写 GUI，追求精致的产品级 UI；Python 流水线（faster-whisper / OpenCC / reportlab）是项目核心资产且无 Rust 对等生态，**原样保留**，以 sidecar 子进程形式被 Tauri 拉起。

## 已确认的决策

| 决策点 | 结论 |
|---|---|
| 壳 | Tauri 2（Rust，系统 WebView） |
| 前端框架 | Svelte 5 + Vite + TypeScript |
| UI 设计 | 全新设计：**A · 单页工作台**（投放区即首页，进度/成果原地展开，设置为滑出面板），**靛蓝 #4F5BD5** 主色，**浅色**底；深色主题留作后续 CSS 变量工作 |
| IPC | **stdio 行 JSON 协议**（不用 HTTP：无端口/防火墙/多实例问题，零新增 Python 依赖） |
| 自动更新 | **Tauri 官方 updater 插件**：签名密钥 + Releases `latest.json`，应用内静默更新 |
| 功能范围 | 与现有 GUI 完全对等：添加视频/文件夹、批量转换与进度、取消、设置（输出语言/简繁/ASR 模型/场景灵敏度/最小间隔/字幕校对/LLM 配置/日志开关）、打开输出文件夹、日志文件夹 |
| CLI | 不动；`chalkpress` 命令行为不变 |

## 总体架构

```
┌─ Tauri 2 壳 (src-tauri/, Rust) ────────────────┐
│  窗口 980×680（min 880×600）；插件：           │
│  dialog（文件/文件夹选择）                      │
│  opener（打开输出/日志文件夹）                  │
│  shell（拉起 sidecar，stdio 转发）              │
│  updater（应用内静默更新）                      │
├─ Svelte 5 前端 (src/) ────────────────────────┤
│  单页工作台 UI；IPC client 封装为 Svelte stores │
└──────────┬─────────────────────────────────────┘
           │ stdin/stdout，每行一个 JSON（UTF-8）
┌──────────┴─────────────────────────────────────┐
│ chalkpress-core：PyInstaller 打包的 sidecar     │
│ = 现有 chalkpress 包（pipeline/config/…）       │
│   + 新增 chalkpress/ipc.py 调度循环             │
│ 内嵌 whisper 模型（--add-data，同现状）         │
└────────────────────────────────────────────────┘
```

- 流水线代码零改动；`ipc.py` 只做请求分发。
- WebView 原生支持文件拖拽，dialog 插件兜底点击选择。

## IPC 协议

传输：stdin/stdout，每行一个 JSON 对象。请求带自增 `id`，响应带相同 `id`；事件无 `id`、单向流。

**请求（前端 → sidecar）**

| 方法 | 参数 | 响应 |
|---|---|---|
| `settings.get` | – | `{options, app, llm_configured}`（结构同 config.toml） |
| `settings.set` | 完整 settings 对象 | `ok`（现 `_save_settings` 的归一化逻辑迁入 `chalkpress/config.py`，GUI 无关化） |
| `convert.start` | `{videos: [path…], options: {...}}` | `ok`；随后推送事件流 |
| `convert.cancel` | – | `ok`（当前视频完成后停止，语义同现在） |

**事件（sidecar → 前端）**

复用 `run_batch` 现有 progress 事件原样透传：`video_start`、`stage`、`stage_done`、`frames`、`video_done`、`video_error`、`batch_done`，另加 sidecar 自身的 `log`（写日志文件）。

**异常路径**：未知方法 → `{id, error}`；sidecar 崩溃/提前退出 → 前端检测 stdout 关闭，UI 顶栏红条 + 重试按钮。

**开发期调试**：`python -m chalkpress.ipc` 直接在终端跑，手敲 JSON 行即可测试，无需浏览器。

## 前端设计（Svelte 5）

- **布局（A · 单页工作台）**：
  - 空闲态：居中 hero 投放区 + "开始转换"主按钮 + 当前"转换方案"芯片行（与现有语义一致）+ 右上角设置齿轮
  - 运行态：同一页面原地切换为进度视图（五阶段 + 总进度条 + 本视频进度 + 当前文件名），保留"停止"按钮
  - 完成态：成果卡片（统计 + PDF 列表 + 打开输出文件夹）
  - 设置：右上滑出 Sheet，分组同现有（输出 / 语音识别 / AI 分析 / 关键帧高级 / 日志 / 关于）；"自动更新"开关移除（updater 全权接管）
- **状态管理**：Svelte 5 runes；两个核心 store——`settings`（读写即 IPC）与转换状态机（idle / running / done / error），progress 事件驱动
- **图标**：`tauri icon packaging/icon_1024.png` 生成全平台图标（源文件由现有 `packaging/make_icons.py` 产出）

## 打包与 CI

- **产物**：Windows NSIS 安装包（替代 Inno Setup）、macOS dmg、Linux AppImage（替代 tar.gz）
- **sidecar**：PyInstaller 按 target triple 命名输出到 `src-tauri/binaries/chalkpress-core-<triple>[.exe]`，`tauri.conf.json` 的 `externalBin` 引用
- **updater**：`tauri signer generate` 生成密钥对；私钥入 GitHub Secrets（`TAURI_SIGNING_PRIVATE_KEY` / `_PASSWORD`）；Release 附加 `latest.json`
- **CI（build-binaries.yml 重写）**：三平台 setup Rust + pnpm → PyInstaller 出 sidecar → tauri-action 构建 → artifact 上传；tag 推送时发 Release + `latest.json`
- 签名/公证：暂不做 macOS codesign（与现状一致，保持占位）

## 退役清单（切换完成后删除）

`chalkpress/gui.py`、`chalkpress/_icon.py`、`chalkpress/update.py`、`run_gui.py`、`packaging/chalkpress.iss`、`chalkpress.spec`（PyInstaller 命令行参数迁入 CI 与新打包脚本）；pyproject 移除 `chalkpress-gui` 入口；README 的 GUI 说明与截图更新。

## 测试

- `chalkpress/ipc.py`：pytest 覆盖协议帧（行解析/坏行容错）、方法 dispatch（含未知方法报错）、`convert.cancel` 置位——以子进程或直接调用调度循环的方式测
- 现有 pipeline/config 测试原样保留
- 前端暂无 JS 单测；三平台手动验收清单（拖拽、转换进度、取消、设置持久化、更新检查）

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| sidecar 启动慢（解压/加载模型） | 首屏不依赖 sidecar 响应；启动请求异步化，UI 有 loading 态 |
| stdio 被子进程库污染（whisper 打日志到 stdout） | sidecar 内所有第三方日志重定向到 stderr；协议层丢弃非 JSON 行并记日志 |
| WebView 拖拽行为三平台差异 | dialog 插件兜底 + 三平台验收清单 |
| updater 签名密钥管理 | 密钥仅存 GitHub Secrets；文档记录生成与轮换步骤 |
