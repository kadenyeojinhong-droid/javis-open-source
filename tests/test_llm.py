import json

import pytest

import llm


def test_supervise_uses_fallback_only_when_main_fails(tmp_path, monkeypatch):
    (tmp_path / ".ai_bus").mkdir()
    (tmp_path / ".ai_bus" / "settings.json").write_text(
        json.dumps({"supervisor_model": "main", "supervisor_fallback": "local"}), encoding="utf-8")
    calls = []

    def fake_chat(model, messages, json_mode=False, timeout=120):
        calls.append(model)
        if model == "main":
            raise llm.LLMUnavailable("402")
        return '{"verdict":"PASS"}'

    monkeypatch.setattr(llm, "chat", fake_chat)
    assert llm.supervise([], tmp_path) == '{"verdict":"PASS"}'
    assert calls == ["main", "local"]


def test_activity_marker_lives_only_during_call(tmp_path):
    with llm.activity("codex", "deepseek-v4-flash", "写代码: x", tmp_path):
        assert llm.active(tmp_path) == {"codex": {"model": "deepseek-v4-flash", "purpose": "写代码: x"}}
    assert llm.active(tmp_path) == {}
    try:
        with llm.activity("agy", "m", "p", tmp_path):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert llm.active(tmp_path) == {}   # a crashed call never leaves the ring spinning


def test_supervise_raises_when_all_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(llm.LLMUnavailable("offline")))
    with pytest.raises(llm.LLMUnavailable):
        llm.supervise([], tmp_path)
