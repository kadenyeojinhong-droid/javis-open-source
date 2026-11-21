"""Build and atomically publish the HUD's combined state snapshot."""
import json
import os
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

import bus
import llm
import standin
import wt


def _json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


_proxy_cache = {"at": 0.0, "value": {"online": False, "models": 0}}


def _proxy():
    # an offline proxy costs a full connect timeout on Windows; cache so /state stays fast
    if time.time() - _proxy_cache["at"] < 30:
        return _proxy_cache["value"]
    _proxy_cache["value"] = _probe_proxy()
    _proxy_cache["at"] = time.time()
    return _proxy_cache["value"]


def _probe_proxy():
    headers = {}
    if os.environ.get("CLIPROXY_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['CLIPROXY_API_KEY']}"
    try:
        req = Request("http://127.0.0.1:8317/v1/models", headers=headers)
        with urlopen(req, timeout=0.3) as response:
            data = json.loads(response.read().decode("utf-8"))
        return {"online": True, "models": len(data.get("data", []))}
    except Exception:
        return {"online": False, "models": 0}


def build(root):
    root = Path(root)
    bus_dir = root / ".ai_bus"
    graph = _json(bus_dir / "traffic_graph.json", {})
    queues = {}
    for name in ("agy", "codex", "claude"):
        path = bus_dir / "inbox" / f"{name}.jsonl"
        queues[name] = sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0
    approvals = []
    for path in (bus_dir / "approvals").glob("*.json"):
        item = _json(path, {})
        if item.get("status") == "pending":
            approvals.append(item)
    tasks = []
    board = root / "TEAM_BOARD.md"
    if board.exists():
        active = False
        for line in board.read_text(encoding="utf-8").splitlines():
            if line.strip() == "## 任务":
                active = True
                continue
            if active and line.startswith("## "):
                break
            if active:
                import re
                match = re.match(r"\s*- \[([ xX])\]\s+(.*)", line)
                if match:
                    tasks.append({"done": match.group(1).lower() == "x", "text": match.group(2)})
    reports = sorted((bus_dir / "gate").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if (bus_dir / "gate").exists() else []
    report = _json(reports[0], {}) if reports else {}
    harness = {"verdict": report.get("verdict"), "time": report.get("time"), "reasons": report.get("reasons", [])}
    busy = []
    try:
        import sys
        module = sys.modules.get("hud_server")
        busy = sorted(getattr(module, "busy_agents", [])) if module else []
    except Exception:
        pass
    # model calls from any process (stand-in, harness review): their slot spins and the capsule names the model
    models = llm.active(root)
    busy = sorted(set(busy) | {slot for slot in models if slot in ("claude", "agy", "codex")})
    return {"models": models,"settings": bus.settings(bus_dir), "agents": bus.agents(bus_dir), "breaker": graph,
            "queues": queues, "busy": busy, "approvals": approvals, "worktrees": wt.status(),
            "tasks": tasks, "harness": harness, "halted": (bus_dir / "HALT").exists(),
            "proxy": _proxy(), "standins": standin.active(root), "updated_at": time.time()}


def write(root):
    root = Path(root)
    path = root / ".ai_bus" / "state.json"
    value = build(root)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return value
