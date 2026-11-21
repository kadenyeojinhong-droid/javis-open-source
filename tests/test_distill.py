import distill


def fake_messages(days):
    texts = ["报告进度", "报告进度", "<task-notification>x", "ok", "全部按照推荐去做", "x" * 900]
    return iter({"agent": "claude", "time": 1_700_000_000 + i, "text": t} for i, t in enumerate(texts))


def test_collect_dedupes_drops_noise_and_truncates(monkeypatch):
    monkeypatch.setattr(distill.transcripts, "user_messages", fake_messages)
    rows = distill.collect(30)
    assert [r.split(" | ")[2][:4] for r in rows] == ["报告进度", "全部按照", "xxxx"]
    assert len(rows[-1].split(" | ")[2]) == 400


def test_batches_respect_size():
    parts = list(distill.batches(["a" * 40] * 5, size=100))
    assert [p.count("\n") + 1 for p in parts] == [2, 2, 1]


def test_run_writes_profile_locally(monkeypatch, tmp_path):
    monkeypatch.setattr(distill.transcripts, "user_messages", fake_messages)
    monkeypatch.setattr(distill, "OUT", tmp_path)
    calls = []
    monkeypatch.setattr(distill, "ask", lambda prompt, purpose: calls.append(purpose) or "## 常用指令\n- 报告进度")
    path = distill.run(30)
    assert calls == ["蒸馏 1/1"]
    assert "报告进度" in path.read_text(encoding="utf-8")
    assert not (tmp_path / "profile.md.tmp").exists()


def test_ask_strips_think_and_fence(monkeypatch):
    fence = chr(96) * 3
    reply = "<think>hmm</think>" + fence + "markdown\n## 常用指令\n- 报告进度\n" + fence

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            import json
            return json.dumps({"message": {"content": reply}}).encode()

    monkeypatch.setattr(distill, "urlopen", lambda req, timeout: Resp())
    monkeypatch.setattr(distill.llm, "_log_call", lambda *a: None)
    assert distill.ask("x", "test") == "## 常用指令\n- 报告进度"
