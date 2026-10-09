"""LLM 分析总结：OpenAI 兼容 /chat/completions，多关键帧图片输入。

提示词按输出语种分模板（zh 系 / en）；新增语种在 config.LANG_PACK 增加条目即可。
"""
from __future__ import annotations

import base64
from pathlib import Path

import requests

from .align import _mmss
from .config import LangPack, LLMConfig

_PROMPT_ZH = """你是一名资深课程笔记助手。以下材料来自课程视频《{title}》（时长 {duration}）：
- {n} 张关键帧截图，按时间顺序排列；
- 每个关键帧对应时间窗内的字幕原文。

请只依据上述材料，输出以下结构的 Markdown 学习笔记：

## 主题
一句话概括本节内容。

## 关键知识点
按讲解顺序列出知识点；保留术语、编号、数字与画面表格中的数据。

## 关键帧解读
逐帧输出：`[开始时间] 画面内容 + 该时间段讲解要点`。

## 复习建议
列出易错点与建议重看的时间段；若无则写"无"。

要求：不要编造画面与字幕之外的内容；截图看不清的字段不要猜测。
语言要求：{lang}"""

_PROMPT_EN = """You are an expert study-notes assistant. The material below comes from a
course video "{title}" (duration {duration}): {n} keyframe screenshots in chronological
order, plus the subtitle text spoken during each keyframe's time window.

Based ONLY on this material, produce a Markdown study note with exactly these sections:

## Topic
One-sentence summary of the video.

## Key Points
Ordered list of the points taught; keep terminology, numbering, numbers and any data
visible in slide tables.

## Keyframe Notes
For each frame: `[start time] what is shown + the point explained in that window`.

## Study Advice
Common mistakes and timestamps worth re-watching; write "None" if empty.

Rules: never invent content beyond the subtitles and screenshots; do not guess fields
that are unreadable in the screenshots.
Language: {lang}"""


def _pick_template(pack: LangPack) -> str:
    return _PROMPT_EN if pack.code.startswith("en") else _PROMPT_ZH


def summarize(title, duration, aligned, frames, cfg: LLMConfig, pack: LangPack,
              timeout: int = 300) -> str:
    """把关键帧（图片）+ 分窗字幕喂给视觉模型，返回 Markdown 总结。"""
    frames_md = ["", "## 关键帧时间窗与字幕"]
    for i, (kf, seg) in enumerate(zip(frames, aligned), 1):
        frames_md.append(f"### 帧{i} [{_mmss(seg['start'])}–{_mmss(seg['end'])}]")
        subs = [f"[{_mmss(s['start'])}] {s['text']}" for s in seg["subs"]]
        frames_md += subs if subs else ["（无字幕）"]
        frames_md.append("")
    prompt = _pick_template(pack).format(
        title=title, duration=_mmss(duration), n=len(frames), lang=pack.prompt_language,
    ) + "\n".join(frames_md)

    content: list[dict] = [{"type": "text", "text": prompt}]
    for kf in frames:
        b64 = base64.b64encode(Path(kf.path).read_bytes()).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + b64},
        })

    payload = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "max_tokens": 16384,
    }
    url = cfg.api_base + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.api_key}"}

    def _send(with_images: bool):
        body = dict(payload)
        if not with_images:
            body["messages"] = [{"role": "user", "content": prompt}]
        return requests.post(url, json=body, headers=headers, timeout=timeout)

    resp = _send(True)
    if resp.status_code in (400, 415, 422):
        # 模型不接受图片输入 → 降级为纯字幕文本分析
        resp = _send(False)
    resp.raise_for_status()
    data = resp.json()
    msg = data["choices"][0]["message"]
    text = (msg.get("content") or "").strip()
    if not text:
        finish = data["choices"][0].get("finish_reason")
        raise RuntimeError(
            f"LLM 未返回正文（finish={finish}，思考 {len(msg.get('reasoning_content') or '')} 字符）；"
            "建议更换模型或增大 max_tokens")
    return text
