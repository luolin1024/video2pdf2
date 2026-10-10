# Chalkpress

**讲座视频 → 讲义 PDF。** 把录播课、讲座、网课视频变成一册可翻阅、可检索、可打印的讲义：关键帧成页、关键字幕随页、AI 总结开篇。

<p align="center">
<b>🎬 视频 ──→ 📄 讲义</b><br>
语音转写 → 字幕校对 → 关键帧对齐 → AI 总结 → 生成 PDF
</p>

## 为什么是 Chalkpress

看网课时最痛的不是"看"，是"回头找"。视频没法检索、没法打印、拖进度条全靠记忆。Chalkpress 把一场讲座**压缩成一册讲义**：

- **关键帧成页** —— 场景检测驱动抽帧（内容变化才截，不是固定间隔），每页一个画面
- **字幕随页** —— Whisper 本地转写，字幕对齐到所在画面的时间窗，页面即上下文
- **AI 总结开篇** —— 可选接入任意 OpenAI 兼容视觉模型，生成结构化学习笔记作为 PDF 首页
- **全程本地** —— 转写、抽帧在你电脑上完成；视频不上传
- **零配置上手** —— 拖入视频、点开始，其余全部自动

## 下载安装

从 [GitHub Releases](https://github.com/luolin1024/video2pdf2/releases) 下载：

| 平台 | 文件 | 说明 |
|---|---|---|
| Windows | `chalkpress_*_x64-setup.exe` | NSIS 安装向导（简中），per-user 安装无需管理员 |
| macOS (Apple Silicon) | `chalkpress_*_aarch64.dmg` | 打开拖入 Applications |
| Linux x64 | `chalkpress_*_amd64.AppImage` | 赋予执行权限后直接运行 |

应用内置自动更新（设置 → 关于与更新），自动从 GitHub Releases 拉取新版本并安装。

## 快速上手

1. 打开 Chalkpress，把视频（或整个课程文件夹）拖入窗口，或点"添加视频"
2. 点 **开始转换**
3. 完成后点 **打开输出文件夹** —— 讲义 PDF 就在视频旁边（`<视频名>_讲义/`）

首页无需任何配置：语音语言自动识别、字幕模型自动选择、输出语言默认简体中文。
想调整？侧栏 → **设置**：输出语言、简繁、字幕模型、场景灵敏度……每项都有一句话解释。

## CLI

```bash
chalkpress 视频.mp4                       # 全流程：转写+抽帧+对齐+分析+PDF
chalkpress 视频.mp4 --summary-lang zh-en  # 输出中英对照
chalkpress 目录/                          # 批量：递归展开目录内全部视频
chalkpress 视频.mp4 --reuse-srt 已有.srt   # 已有字幕时跳过转写
chalkpress 视频.mp4 --scene-threshold 0.15 --min-gap 5   # 画面变化快时调大阈值
chalkpress 视频.mp4 --zh-script traditional --no-correct  # 繁体输出、关闭校对
```

输出结构（默认 `<视频名>_讲义/`）：

```
├── <名>.pdf            # 首页=AI 总结，后续每页=关键帧+该窗字幕
├── <名>.srt            # 全部字幕（可独立使用）
├── <名>.aligned.md     # 字幕×关键帧对照（Markdown）
├── <名>.summary.md     # AI 总结
└── keyframes/          # 关键帧图片
```

## AI 分析（可选）

不配置也能用（输出关键帧 PDF + 字幕）；配置后额外获得字幕校对与结构化总结。
任意 OpenAI 兼容 `/chat/completions` 端点均可（GLM / DeepSeek / SiliconFlow / OpenAI / 本地网关），
需支持图片输入：

```bash
export CHALKPRESS_API_BASE="https://open.bigmodel.cn/api/paas/v4"   # 任意 OpenAI 兼容地址
export CHALKPRESS_API_KEY="sk-..."
export CHALKPRESS_LLM_MODEL="glm-4.6v"                              # 需支持图片输入
```

也可在 GUI 设置页填写（改动即存，持久生效）。旧 `V2P2_*` 环境变量仍兼容。

## 桌面应用（Tauri 2）

GUI 为 Tauri 2 桌面应用：**零配置首页**（拖入视频即可转换）+ **设置中心**（每项带一句话解释，改动 400ms 防抖后持久化）+ **应用内自动更新**（从 GitHub Releases 检查并安装新版本）。Python 流水线以 PyInstaller sidecar 形式内嵌，转换逻辑与 CLI 完全同源。

## 从源码运行 / 构建

```bash
# 运行（Python ≥ 3.9）
uv pip install -e .
chalkpress 视频.mp4        # CLI

# 构建 GUI（先打 sidecar，再打桌面应用）
corepack pnpm i
python packaging/build_sidecar.py
corepack pnpm tauri build
```

CI（`.github/workflows/build-binaries.yml`）在推送 main / 打 `v*` tag 时自动三平台构建 sidecar 与 Tauri 应用，并发布安装包到 Releases。

## 技术要点

- **流水线**：`Options → run()/run_batch()`，五段处理链，单个视频失败不中断批量
- **桌面 GUI**：Tauri 2（零配置首页 + 设置中心 + 应用内自动更新），Python 流水线作为 PyInstaller sidecar 内嵌
- **本地 ASR**：faster-whisper（CPU int8，全平台）；macOS 可选 mlx-whisper 加速；whisper 支持 90+ 语种
- **简繁规范**：OpenCC 确定性转换；`auto` 按系统 locale 判定
- **可检索 PDF**：reportlab 生成，帧为图、字幕/总结为真实文本层；CJK 字体解析链三平台不缺字
- **配置链**：显式参数 > `CHALKPRESS_*` 环境变量 > config.toml > 内置默认

## 路线图

- [x] GUI（macOS 风格双页布局：转换 / 设置）
- [x] 批量/整个课程目录处理（递归展开子目录）
- [x] Windows 安装包 + macOS dmg + 自动检查更新
- [ ] 更多语种语言包

## 许可与商业授权

本项目采用 **AGPL-3.0-or-later** 协议开源：

- 个人学习、研究、内部非商业使用，随意用、随便改
- 修改版或基于它的服务（包括网络服务）对外提供时，须按 AGPL 开放源代码

**闭源 / 商业使用**需获得商业许可，联系作者洽谈。

### 贡献者协议（CLA）

向本项目提交 PR 即表示同意：该贡献以 AGPL-3.0-or-later 授权项目，**并授权项目维护者将其用于未来的商业许可发行版**。不接受此条款的贡献恕不合并——这是双许可模式能成立的前提。
