import subprocess

import pytest

import wt


def repo(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "base.txt").write_text("base\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "base"], check=True, capture_output=True)
    monkeypatch.setattr(wt, "ROOT", root)
    return root


def test_create_status_and_diff(tmp_path, monkeypatch):
    root = repo(tmp_path, monkeypatch)
    path = wt.create("codex", "J1_task")
    assert path == wt.create("codex", "J1_task")
    (path / "new.txt").write_text("change\n")
    rows = wt.status()
    assert rows[0]["task_id"] == "J1_task" and rows[0]["dirty"]
    assert "new.txt" in wt.diff("J1_task")


def test_invalid_task_id(tmp_path, monkeypatch):
    repo(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        wt.create("codex", "../escape")


def test_merge_denied_does_not_merge(tmp_path, monkeypatch):
    root = repo(tmp_path, monkeypatch)
    path = wt.create("codex", "deny")
    (path / "new.txt").write_text("change\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "change"], check=True, capture_output=True)
    import bus
    monkeypatch.setattr(bus, "approve", lambda *args, **kwargs: "denied")
    assert not wt.merge("deny")
    assert not (root / "new.txt").exists()
