import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bus
import sync_mcp


def test_breaker_and_reset(tmp_path):
    for _ in range(10):
        assert bus.send("a", "b", "x", tmp_path)["status"] == "sent"
    assert bus.send("a", "b", "x", tmp_path)["status"] == "breaker_open"
    bus.reset(tmp_path)
    assert bus.send("a", "b", "x", tmp_path)["status"] == "sent"


def test_send_and_take(tmp_path):
    assert bus.send("codex", "agy", "hello", tmp_path)["status"] == "sent"
    messages = bus.take("agy", tmp_path)
    assert messages[0]["body"] == "hello"
    assert list((tmp_path / "done").glob("*.jsonl"))


def test_write_is_atomic_and_take_skips_bad_lines(tmp_path):
    bus.send("a", "b", "x", tmp_path)
    assert not list(tmp_path.glob("*.tmp"))  # swap-in leaves nothing behind
    inbox = tmp_path / "inbox" / "b.jsonl"
    inbox.write_text(inbox.read_text(encoding="utf-8") + '{"half": \n[1]\n', encoding="utf-8")
    assert [m["body"] for m in bus.take("b", tmp_path)] == ["x"]  # broken lines dropped, good one kept


def test_approval_timeout_denied(tmp_path):
    assert bus.approve("agent", "action", "detail", .01, tmp_path) == "denied"


def test_sync_mcp_preview_structure(tmp_path):
    (tmp_path / "mcp_servers.json").write_text((ROOT / "mcp_servers.json").read_text(encoding="utf-8"), encoding="utf-8")
    sync_mcp.generate(tmp_path)
    out = tmp_path / "generated"
    assert set(p.name for p in out.iterdir()) == {"claude_mcp.json", "gemini_settings.json", "codex_mcp.toml", "agy_mcp.json"}
    assert "mcpServers" in json.loads((out / "claude_mcp.json").read_text(encoding="utf-8"))
    assert "mcp_servers.memory" in (out / "codex_mcp.toml").read_text(encoding="utf-8")
    assert "custom-tools" not in (out / "agy_mcp.json").read_text(encoding="utf-8")


def test_sync_mcp_apply_home_configs(tmp_path):
    (tmp_path / "mcp_servers.json").write_text((ROOT / "mcp_servers.json").read_text(encoding="utf-8"), encoding="utf-8")
    home = tmp_path / "home"
    agy_cfg = home / ".gemini" / "antigravity" / "mcp_config.json"
    agy_cfg.parent.mkdir(parents=True)
    old_agy = '{"other": {"keep": true}, "mcpServers": {"old": {}}}'
    agy_cfg.write_text(old_agy, encoding="utf-8")
    codex_cfg = home / ".codex" / "config.toml"
    codex_cfg.parent.mkdir(parents=True)
    old_codex = '[notice]\nvalue = "keep"\n\n[mcp_servers.old]\ncommand = "old"\nargs = []\n'
    codex_cfg.write_text(old_codex, encoding="utf-8")

    sync_mcp.apply(tmp_path, home=home)

    agy = json.loads(agy_cfg.read_text(encoding="utf-8"))
    assert agy["other"] == {"keep": True}
    assert "old" not in agy["mcpServers"]
    assert "memory" in agy["mcpServers"]
    assert agy_cfg.with_suffix(".json.bak").read_text(encoding="utf-8") == old_agy
    assert "value = \"keep\"" in codex_cfg.read_text(encoding="utf-8")
    assert "mcp_servers.memory" in codex_cfg.read_text(encoding="utf-8")
    assert codex_cfg.with_suffix(".toml.bak").read_text(encoding="utf-8") == old_codex

    # A second apply must preserve the original backups rather than snapshot generated config.
    agy_cfg.write_text('{"other": {"new": true}}', encoding="utf-8")
    codex_cfg.write_text('[notice]\nvalue = "new"\n', encoding="utf-8")
    sync_mcp.apply(tmp_path, home=home)
    assert agy_cfg.with_suffix(".json.bak").read_text(encoding="utf-8") == old_agy
    assert codex_cfg.with_suffix(".toml.bak").read_text(encoding="utf-8") == old_codex
