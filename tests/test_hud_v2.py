import json
import sys
from pathlib import Path
from fastapi.testclient import TestClient
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bus, hud_server, nlp_compressor


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(hud_server, "ROOT", tmp_path)
    monkeypatch.setattr(bus, "BUS", tmp_path / ".ai_bus")
    (tmp_path / ".ai_bus").mkdir(exist_ok=True)
    return TestClient(hud_server.app)


def test_order_chinese_stdout(tmp_path, monkeypatch):
    client = setup(tmp_path, monkeypatch)
    raw = {"goal": "中文目标", "constraints": [], "files": [], "options": [
        {"id": x, "title": "方案" + x, "summary": "摘要" + x, "modules": ["mod"]} for x in "ABC"]}
    monkeypatch.setattr(nlp_compressor.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": json.dumps(raw, ensure_ascii=False)})())
    r = client.post("/order", json={"text": "测试 中文"})
    assert r.status_code == 200 and len(r.json()["options"]) == 3


def test_settings_validation_and_file(tmp_path, monkeypatch):
    c = setup(tmp_path, monkeypatch)
    assert c.post("/settings", json={"breaker_limit": 0}).status_code == 400
    assert c.post("/settings", json={"language": "fr"}).status_code == 400
    assert c.post("/settings", json={"idle_seconds": 4}).status_code == 400
    assert c.post("/settings", json={"idle_seconds": 121}).status_code == 400
    assert c.post("/settings", json={"idle_seconds": 30, "auto_hide": False}).status_code == 200
    assert c.post("/settings", json={"language": "en"}).json()["language"] == "en"
    r = c.post("/settings", json={"breaker_limit": 3})
    assert r.status_code == 200
    assert json.loads((tmp_path / ".ai_bus/settings.json").read_text(encoding="utf-8"))["breaker_limit"] == 3
    for _ in range(3): assert bus.send("codex", "agy", "x")["status"] == "sent"
    assert bus.send("codex", "agy", "x")["status"] == "breaker_open"


def test_message_policy_rejects_speak_as_me(tmp_path, monkeypatch):
    c = setup(tmp_path, monkeypatch)
    c.post("/settings", json={"allow_agent_messages": False})
    assert bus.send("codex", "agy", "x")["status"] == "blocked"
    assert bus.send("human", "codex", "x")["status"] == "sent"
    assert c.post("/settings", json={"speak_as_me": True}).status_code == 400


def test_state(tmp_path, monkeypatch):
    c = setup(tmp_path, monkeypatch)
    s = c.get("/state").json()
    assert {"settings", "agents", "breaker", "queues", "busy", "approvals"} <= set(s)


def test_agents_validation_and_persistence(tmp_path, monkeypatch):
    c = setup(tmp_path, monkeypatch)
    agents = c.get("/agents").json()
    assert len(agents) == 4
    assert (tmp_path / ".ai_bus" / "agents.json").exists()
    assert c.post("/agents", json={"invalid": "shape"}).status_code == 400
    assert c.post("/agents", json=[{**a, "enabled": False} for a in agents]).status_code == 400
    assert c.post("/agents", json=[{**agents[0], "id": "unknown"}, *agents[1:]]).status_code == 400
    assert c.post("/agents", json=[{**agents[0], "name": "x" * 21}, *agents[1:]]).status_code == 400
    assert c.post("/agents", json=[{**agents[0], "role": "x" * 41}, *agents[1:]]).status_code == 400
    assert c.post("/agents", json=[{**agents[0], "color": "red"}, *agents[1:]]).status_code == 400
    updated = [{**a, "enabled": a["id"] != "agy"} for a in agents]
    assert c.post("/agents", json=updated).status_code == 200
    assert len([a for a in c.get("/agents").json() if a["enabled"]]) == 3
    saved = json.loads((tmp_path / ".ai_bus" / "agents.json").read_text(encoding="utf-8"))
    assert [a["id"] for a in saved] == ["claude", "agy", "codex", "deepseek"]


def test_state_busy_during_subprocess(tmp_path, monkeypatch):
    c = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(hud_server.shutil, "which", lambda command: command)

    def run(*args, **kwargs):
        assert c.get("/state").json()["busy"] == ["agy"]
        return type("Result", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(hud_server.subprocess, "run", run)
    hud_server.handle("agy", {"sender": "human", "receiver": "agy", "body": "hello"})
    assert c.get("/state").json()["busy"] == []


def test_console_without_console_and_workbench_missing(tmp_path, monkeypatch):
    c = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(hud_server, "CONSOLE_HWND", None)
    assert c.get("/console").json() == {"ok": False, "visible": False}
    assert c.post("/console", json={"show": True}).json() == {"ok": False}
    monkeypatch.setattr(hud_server, "JAVIS_SCRIPT", tmp_path / "missing.ps1")
    assert c.post("/workbench").status_code == 404
