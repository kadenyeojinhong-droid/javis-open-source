import json
import subprocess

import harness


def test_gate_static_failure_and_llm_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(harness.wt, "diff", lambda _task: "+ --dangerously-skip-permissions\n")
    monkeypatch.setattr(harness.wt, "status", lambda: [{"task_id": "sample", "path": str(tmp_path)}])
    monkeypatch.setattr(harness.llm, "chat", lambda *a, **k: (_ for _ in ()).throw(harness.llm.LLMUnavailable("offline")))
    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "1 passed", ""))
    report = harness.gate("sample")
    assert report["verdict"] == "FAIL"
    assert report["checks"]["static"] == "FAIL"
    assert report["checks"]["llm"] == "skipped"
    saved = next((tmp_path / ".ai_bus" / "gate").glob("*.json"))
    assert json.loads(saved.read_text(encoding="utf-8"))["task_id"] == "sample"


def test_watch_repeated_pair_writes_halt(tmp_path, monkeypatch):
    bus_dir = tmp_path / ".ai_bus"
    bus_dir.mkdir()
    (bus_dir / "settings.json").write_text('{"breaker_limit": 2}')
    audit = bus_dir / "activity_audit.jsonl"
    audit.write_text('\n'.join(json.dumps({"sender": "codex", "receiver": "claude"}) for _ in range(3)) + '\n')
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(harness.wt, "status", lambda: [])
    harness.watch_once(0)
    assert (bus_dir / "HALT").exists()
