import json

import state


def test_snapshot_fields_and_proxy_offline(tmp_path, monkeypatch):
    (tmp_path / ".ai_bus").mkdir()
    (tmp_path / "TEAM_BOARD.md").write_text("## 任务\n- [x] done\n- [ ] pending\n", encoding="utf-8")
    monkeypatch.setattr(state, "_proxy", lambda: {"online": False, "models": 0})
    monkeypatch.setattr(state.wt, "status", lambda: [])
    value = state.write(tmp_path)
    assert {"agents", "queues", "busy", "breaker", "approvals", "worktrees", "tasks", "harness", "halted", "proxy", "updated_at"} <= value.keys()
    assert [task["done"] for task in value["tasks"]] == [True, False]
    assert value["proxy"] == {"online": False, "models": 0}
    assert json.loads((tmp_path / ".ai_bus" / "state.json").read_text(encoding="utf-8"))["halted"] is False
