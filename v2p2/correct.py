"""LLM 字幕校对：修正 ASR 同音字/近音字错误（可配置，可关闭）。

策略：编号行进出、temperature=0；解析结果按编号回写，任何解析异常只影响
对应行（未匹配的行保持原文），整体失败由调用方兜底。
"""
from __future__ import annotations

import re

import requests

from .config import LLMConfig

_PROMPT = """你是字幕校对员。下面是语音识别(ASR)输出的中文字幕，可能包含同音字/近音字/分词错误。
请逐条修正明显的识别错误（计算机与软考专有名词按行业习惯写法，例如"主讲老师"而非"主江老师"），要求：
- 不改写句式，不增删内容，不合并/拆分条目，不翻译；
- 无法确定的保持原文。

输入是编号行 `编号|文本`，输出同样格式的编号行 `编号|修正后文本`。
必须覆盖全部编号且顺序一致，除编号行外不要输出任何其他文字。
"""


def correct_transcript(segments, cfg: LLMConfig, timeout: int = 300) -> int:
    """就地修正 segments[i]['text']，返回修正条数。失败抛异常由调用方兜底。"""
    numbered = "\n".join(f"{i}|{s['text']}" for i, s in enumerate(segments, 1))
    resp = requests.post(
        cfg.api_base + "/chat/completions",
        json={
            "model": cfg.model,
            "messages": [{"role": "user", "content": _PROMPT + "\n" + numbered}],
            "temperature": 0.0,
            "max_tokens": 16384,
        },
        headers={"Authorization": f"Bearer {cfg.api_key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    text = (msg.get("content") or "").strip()
    if not text:
        raise RuntimeError("校对模型未返回正文")

    fixed = 0
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\s*[|｜:：、.]\s*(.+)$", line.strip())
        if not m:
            continue
        i = int(m.group(1)) - 1
        new = m.group(2).strip()
        if 0 <= i < len(segments) and new and new != segments[i]["text"]:
            segments[i]["text"] = new
            fixed += 1
    return fixed
