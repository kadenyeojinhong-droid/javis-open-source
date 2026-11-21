import argparse
import json
import os
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent


def configs(root=ROOT):
    # "{ROOT}" in mcp_servers.json = this checkout's folder, so the file holds no machine-specific paths
    text = (root / "mcp_servers.json").read_text(encoding="utf-8").replace("{ROOT}", json.dumps(str(Path(root).resolve()))[1:-1])
    servers = {k: v for k, v in json.loads(text).items() if not v.get("_disabled")}
    claude = {"mcpServers": servers}
    gemini = {"mcpServers": servers}
    codex = "\n\n".join(f"[mcp_servers.{name}]\ncommand = {json.dumps(s['command'])}\nargs = {json.dumps(s['args'])}" for name, s in servers.items()) + "\n"
    return claude, gemini, codex, {"mcpServers": servers}


def generate(root=ROOT, out=None):
    root, out = Path(root), Path(out or root / "generated")
    claude, gemini, codex, agy = configs(root)
    out.mkdir(parents=True, exist_ok=True)
    (out / "claude_mcp.json").write_text(json.dumps(claude, indent=2), encoding="utf-8")
    (out / "gemini_settings.json").write_text(json.dumps(gemini, indent=2), encoding="utf-8")
    (out / "codex_mcp.toml").write_text(codex, encoding="utf-8")
    (out / "agy_mcp.json").write_text(json.dumps(agy, indent=2), encoding="utf-8")
    return claude, gemini, codex, agy


def apply(root=ROOT, home=None):
    root = Path(root)
    home = Path(home or Path.home())
    claude, gemini, codex, agy = generate(root)
    (root / ".mcp.json").write_text(json.dumps(claude, indent=2), encoding="utf-8")
    gd = root / ".gemini"
    gd.mkdir(exist_ok=True)
    (gd / "settings.json").write_text(json.dumps(gemini, indent=2), encoding="utf-8")
    cfg = home / ".codex" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    original = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    tomllib.loads(original) if original.strip() else {}
    backup = cfg.with_suffix(cfg.suffix + ".bak")
    if cfg.exists() and not backup.exists():
        backup.write_text(original, encoding="utf-8")
    import re
    kept = re.sub(r"(?ms)^\[mcp_servers(?:\.[^\]]+)?\]\s*.*?(?=^\[|\Z)", "", original).rstrip()
    cfg.write_text((kept + "\n\n" if kept else "") + codex, encoding="utf-8")
    agy_cfg = home / ".gemini" / "antigravity" / "mcp_config.json"
    agy_cfg.parent.mkdir(parents=True, exist_ok=True)
    original_agy_text = agy_cfg.read_text(encoding="utf-8") if agy_cfg.exists() else ""
    original_agy = json.loads(original_agy_text) if original_agy_text else {}
    agy_backup = agy_cfg.with_suffix(agy_cfg.suffix + ".bak")
    if agy_cfg.exists() and not agy_backup.exists():
        agy_backup.write_text(original_agy_text, encoding="utf-8")
    original_agy["mcpServers"] = agy["mcpServers"]
    agy_cfg.write_text(json.dumps(original_agy, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        apply()
    else:
        generate()
