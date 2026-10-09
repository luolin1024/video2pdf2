# video2pdf2 (v2p2)

mp4 → **关键帧 PDF + 关键字幕 + LLM 分析总结**。场景检测抽帧（内容驱动，不按字幕逐条截），本地 Whisper 转写字幕，字幕×关键帧对齐，可选视觉 LLM 输出结构化学习笔记。

## 特性

- **跨平台**：Windows / macOS / Linux；无系统 ffmpeg 时自动回退 `imageio-ffmpeg` 自带静态二进制（可打进可执行程序）
- **本地 ASR**：faster-whisper（默认，CPU int8，全平台）；macOS 可选 mlx-whisper 加速
- **中英双语**（v1）：语音语言 `--language auto|zh|en|…`（whisper 支持 90+ 语种），输出语言 `--summary-lang zh|zh-en|en`；新增语种只需在 `v2p2/config.py` 的 `LANG_PACK` 加条目
- **简繁规范**：`--zh-script auto|simplified|traditional`（OpenCC 确定性转换；auto 按系统 locale 判定，zh_TW/zh_HK → 繁体）
- **LLM 字幕校对**：自动修正 ASR 同音字/误听（"主江老师"→"主讲老师"），`--no-correct` 关闭；未配置 LLM 时自动跳过
- **可检索 PDF**：reportlab 生成，帧为图、字幕/总结为真实文本层；CJK 字体解析链（系统字体→CID 兜底），三平台不缺字
- **LLM 可插拔**：任何 OpenAI 兼容 `/chat/completions` 端点（GLM / DeepSeek / SiliconFlow / OpenAI / 本地网关）
- **CI 多平台打包**：GitHub Actions 矩阵构建 macOS(arm64)/Windows/Linux 可执行程序（含模型与 ffmpeg，下载即用）；Intel Mac 需自行 `pip install -e .`

## 安装

```bash
cd video2pdf2
uv venv .venv && uv pip install -e . --python .venv/bin/python   # 或 python3 -m venv .venv && .venv/bin/pip install -e .
```

macOS 加速（可选）：`uv pip install -e ".[mac]"`

## 配置 LLM（可选，不配则跳过分析仍产出 PDF+字幕）

环境变量或同名 CLI 参数：

```bash
export V2P2_API_BASE="https://open.bigmodel.cn/api/paas/v4"   # 任意 OpenAI 兼容地址
export V2P2_API_KEY="sk-..."
export V2P2_LLM_MODEL="glm-4.6v"                              # 需支持图片输入
```

## 用法

```bash
v2p2 视频.mp4                       # 全流程：转写+抽帧+对齐+分析+PDF
v2p2 视频.mp4 --language zh --summary-lang zh-en
v2p2 视频.mp4 --reuse-srt 已有.srt   # 已有字幕时跳过转写
v2p2 视频.mp4 --scene-threshold 0.15 --min-gap 5   # 画面变化快的视频调大阈值
v2p2 目录/                          # 批量：递归展开目录（含子目录）内全部视频
v2p2 视频.mp4 --zh-script traditional --no-correct
```

```bash
# 打 v* 标签、或直接 push 到 main、或到 Actions 页手动触发，自动产出 4 平台可执行程序 artifacts：
git tag v0.1.1 && git push origin v0.1.1
```

输出（默认 `<视频名>_v2p2/`）：

```
├── <名>.pdf            # 首页=分析总结，后续每页=关键帧+该窗字幕
├── <名>.srt            # 全程字幕
├── <名>.aligned.md     # 关键字幕 × 关键帧 对照表
├── <名>.summary.md     # LLM 分析总结（Markdown）
└── keyframes/*.jpg     # 关键帧截图（文件名含时间点）
```

## 打包为本地可执行程序（路线）

PyInstaller onefile；faster_whisper 为懒加载后端需 `--hidden-import`，
ffmpeg 二进制随 imageio-ffmpeg 冻结：

```bash
pyinstaller -F -n v2p2 \
  --collect-all imageio_ffmpeg \
  --hidden-import faster_whisper --hidden-import ctranslate2 \
  --collect-submodules faster_whisper \
  -p . v2p2/cli.py
```

## 路线图

- [x] GUI 模式（tkinter，零额外依赖，复用 `v2p2/pipeline.run_batch`，`v2p2-gui` 启动）
- [x] 批量/整个课程目录处理（递归展开子目录）
- [ ] 更多语种语言包
- [ ] 向量检索（沿用 Video2PDF TODO 思路）
