import json
import os
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUS = ROOT / ".ai_bus"
DEFAULT_SETTINGS = {"allow_hud": True, "allow_agent_messages": True, "breaker_limit": 10, "language": "zh", "auto_hide": True, "idle_seconds": 15}
DEFAULT_AGENTS = [
    {"id": "claude", "name": "Claude", "role": "审查与分析", "color": "#FF9F0A", "enabled": True},
    {"id": "agy", "name": "Antigravity", "role": "规划与压缩", "color": "#64D2FF", "enabled": True},
    {"id": "codex", "name": "Codex", "role": "编码实现", "color": "#30D158", "enabled": True},
    {"id": "deepseek", "name": "DeepSeek", "role": "本地助手与蒸馏", "color": "#4D6BFE", "enabled": True},
]


def settings(root=None):
    root = root or BUS
    try:
        # utf-8-sig: Notepad / PS 5.1 save a BOM, which plain utf-8 rejects (settings silently fell back to defaults)
        return {**DEFAULT_SETTINGS, **json.loads((root / "settings.json").read_text(encoding="utf-8-sig"))}
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)


def agents(root=None):
    root = root or BUS
    path = root / "agents.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        data = None
    except (OSError, json.JSONDecodeError):
        return [dict(item) for item in DEFAULT_AGENTS]  # unreadable: never overwrite the user's file
    if not isinstance(data, list):
        _write(path, DEFAULT_AGENTS)
        return [dict(item) for item in DEFAULT_AGENTS]
    known = {item.get("id") for item in data if isinstance(item, dict)}
    missing = [dict(item) for item in DEFAULT_AGENTS if item["id"] not in known]
    if missing:  # a new built-in agent (deepseek) joins an older agents.json without touching the user's edits
        data = data + missing
        _write(path, data)
    return data


def _write(path, value, append=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if append:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(value, ensure_ascii=False) + "\n")
        return
    # write aside, then swap in: a reader never sees a half-written file (it used to read {} and wipe the breaker)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    for _ in range(50):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows: a reader has the target open right now
            time.sleep(0.01)
    os.replace(tmp, path)
    # shortcut: two processes that +1 the same count at the same instant can still lose one; add a file lock if agents ever loop that fast


def send(sender, receiver, body, root=None):
    root = root or BUS
    config = settings(root)
    if not config["allow_agent_messages"] and sender != "human" and receiver != "human":
        return {"status": "blocked"}
    graph_path = root / "traffic_graph.json"
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        graph = {}
    pair = "->".join(sorted((sender, receiver)))
    count = graph.get(pair, 0)
    # the breaker stops agent<->agent ping-pong; the human dispatching work is never a loop
    if "human" not in (sender, receiver) and count >= config["breaker_limit"]:
        return {"status": "breaker_open", "pair": pair, "count": count}
    graph[pair] = count + 1
    _write(graph_path, graph)
    message = {"id": uuid.uuid4().hex, "sender": sender, "receiver": receiver, "body": body, "time": time.time()}
    _write(root / "inbox" / f"{receiver}.jsonl", message, append=True)
    # every send (HUD, CLI or an agent over MCP) shows up in the audit stream, which is what flies the HUD's paper plane
    audit({"sender": sender, "receiver": receiver, "action": "sent", "chars_in": len(body), "chars_out": 0, "compression_rate": 0}, root)
    return {"status": "sent", **message}


def reset(root=None):
    root = root or BUS
    _write(root / "traffic_graph.json", {})


def take(agent, root=None):
    root = root or BUS
    inbox = root / "inbox" / f"{agent}.jsonl"
    if not inbox.exists():
        return []
    dest = root / "done" / f"{agent}_{int(time.time()*1000)}.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(50):
        try:
            inbox.replace(dest)
            break
        except PermissionError:  # Windows: send() is appending or state.py is reading the inbox right now
            time.sleep(0.02)
    else:
        return []  # still locked: leave the messages in the inbox for the next poll
    messages = []
    for line in dest.read_text(encoding="utf-8").splitlines():
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # one broken line must not drop the rest; the raw file stays in done/ for a look
    return [m for m in messages if isinstance(m, dict) and {"sender", "body"} <= m.keys()]


def approve(agent, action, detail, timeout_s=300, root=None):
    root = root or BUS
    ident = uuid.uuid4().hex
    path = root / "approvals" / f"{ident}.json"
    _write(path, {"id": ident, "agent": agent, "action": action, "detail": detail, "status": "pending"})
    request = {"id": ident, "agent": agent, "action": action, "detail": detail, "status": "pending"}
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
            if request["status"] in ("approved", "denied"):
                return request["status"]
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(min(.1, max(0, deadline-time.monotonic())))
    request["status"] = "denied"
    _write(path, request)
    return "denied"


def audit(entry, root=None):
    root = root or BUS
    _write(root / "activity_audit.jsonl", {"time": time.time(), **entry}, append=True)
