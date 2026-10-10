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
