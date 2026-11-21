import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bus
import hud_server


def test_worker_handles_missing_cli_and_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(hud_server, "ROOT", tmp_path)
    monkeypatch.setattr(hud_server, "push", lambda *args, **kwargs: None)
    item = {"sender": "human", "receiver": "agy", "body": "hello"}
    failed = tmp_path / ".ai_bus" / "failed" / "agy.jsonl"

    # CLI missing: the DeepSeek stand-in takes the slot instead of failing outright
    calls = []
    monkeypatch.setattr(hud_server.standin, "implement", lambda *a, **k: calls.append(a) or (1, "", "offline"))
    monkeypatch.setattr(hud_server.shutil, "which", lambda command: None)
    hud_server.handle("agy", item)
    assert len(calls) == 1 and hud_server.standin.is_down("agy", tmp_path)
    hud_server.standin.mark_up("agy", tmp_path)

    monkeypatch.setattr(hud_server.shutil, "which", lambda command: command)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))
    monkeypatch.setattr(hud_server.subprocess, "run", timeout)
    hud_server.handle("agy", item)
    assert [json.loads(line) for line in failed.read_text(encoding="utf-8").splitlines()] == [item]


def test_hud_routes_and_bus_flow(tmp_path, monkeypatch):
    # Keep this HTTP integration test isolated from the working bus and CLI processes.
    monkeypatch.setattr(bus, "BUS", tmp_path / "bus")
    monkeypatch.setattr(hud_server.subprocess, "run", lambda *a, **k: None)
    client = TestClient(hud_server.app)

    assert client.post("/reset_breaker", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/reset_breaker", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
    assert client.post("/reset_breaker").json() == {"status": "reset"}
    for i in range(10):
        assert bus.send("alpha", "beta", str(i))["status"] == "sent"
    assert bus.send("alpha", "beta", "11th")["status"] == "breaker_open"

    hud_root = tmp_path / "hud"
    monkeypatch.setattr(hud_server, "ROOT", hud_root)
    approval_dir = hud_root / ".ai_bus" / "approvals"
    approval_dir.mkdir(parents=True)
    pending = {"id": "qa-pending", "status": "pending", "action": "test"}
    (approval_dir / "qa-pending.json").write_text(json.dumps(pending), encoding="utf-8")
    response = client.post("/approve/qa-pending", json={"approved": False})
    assert response.status_code == 200
    assert response.json()["status"] == "denied"
