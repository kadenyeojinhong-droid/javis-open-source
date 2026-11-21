"""One read-only view over every agent's own chat log: claude / codex / agy / deepseek -> uniform events.

event = {"agent", "session", "time" (epoch s), "role" (user/assistant/tool), "text"}
Sources are never written. Text is redacted (key-like strings) before it leaves this module.
CLI: python transcripts.py tail <agent> [n]   |   python transcripts.py users [days]
"""
import glob
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
AGENTS = ("claude", "agy", "codex", "deepseek")
KEYLIKE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{30,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]+-----[^-]*"
                     r"|(?i:(?:api[_-]?key|token|secret|password)\s*[=:]\s*)\S{8,})")
_ID = re.compile(r"^[\W\d]*([0-9a-f]{8}-[0-9a-f-]{27}|call_\d+|bot-[0-9a-f-]+|[A-Za-z0-9_-]{20,}X?)\W*$")


def redact(text):
    return KEYLIKE.sub("[已遮蔽]", text or "")


def _ts(value):
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e11 else value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def sessions(agent):
    """Session files of one agent, newest first."""
    if agent == "claude":
        files = [f for f in glob.glob(str(HOME / ".claude/projects/*/*.jsonl")) if "observer" not in f]
    elif agent == "codex":
        files = glob.glob(str(HOME / ".codex/sessions/**/*.jsonl"), recursive=True)
    elif agent == "agy":
        files = glob.glob(str(HOME / ".gemini/antigravity-cli/conversations/*.db"))
    elif agent == "deepseek":
        files = [str(ROOT / ".ai_bus" / "llm_calls.jsonl")]
    else:
        raise ValueError(agent)
    return sorted((f for f in files if os.path.isfile(f)), key=os.path.getmtime, reverse=True)


def _blocks(content):
    if isinstance(content, str):
        yield "text", content
        return
    for block in content or []:
        kind = block.get("type")
        if kind in ("text", "input_text", "output_text"):
            yield "text", block.get("text", "")
        elif kind == "tool_use":
            yield "tool", f"{block.get('name')} {json.dumps(block.get('input', {}), ensure_ascii=False)[:300]}"
        elif kind == "tool_result":
            yield "result", ""


def _claude(path):
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") not in ("user", "assistant") or d.get("isSidechain") or d.get("isMeta"):
            continue
        for kind, text in _blocks(d.get("message", {}).get("content")):
            if kind == "result" or not text.strip() or text.startswith(("<system-reminder>", "<command-", "<local-command")):
                continue
            yield {"time": _ts(d.get("timestamp")), "role": "tool" if kind == "tool" else d["type"], "text": text,
                   "auto": d.get("entrypoint", "cli") != "cli"}  # sdk-*: scripts / claude -p, not the human


def _codex(path):
    auto = False
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        p = d.get("payload") or {}
        if (p.get("turn_attribution") or {}).get("turn_trigger") == "exec":
            auto = True  # codex exec = an order written by another agent
        if d.get("type") != "response_item":
            continue
        if p.get("type") == "message" and p.get("role") in ("user", "assistant"):
            for _, text in _blocks(p.get("content")):
                if text.strip() and not text.lstrip().startswith(("<environment_context", "<user_instructions", "# AGENTS.md")):
                    yield {"time": _ts(d.get("timestamp")), "role": p["role"], "text": text, "auto": auto}
        elif p.get("type") in ("function_call", "custom_tool_call", "local_shell_call"):
            args = p.get("arguments") or p.get("input") or p.get("action") or ""
            yield {"time": _ts(d.get("timestamp")), "role": "tool", "text": f"{p.get('name', 'shell')} {str(args)[:300]}"}


def _agy(path):
    """agy keeps protobuf blobs; readable runs (prompts, replies, tool-call JSON) are pulled out heuristically."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute("select idx, step_type, step_payload from steps order by idx").fetchall()
    except sqlite3.Error:
        return
    finally:
        con.close()
    mtime = os.path.getmtime(path)
    for idx, step_type, payload in rows:
        runs = re.findall(r"[^\x00-\x1f\x7f-\x9f�]{6,}", (payload or b"").decode("utf-8", "replace"))
        runs = [r.strip() for r in runs if not _ID.match(r)]
        if not runs:
            continue
        text = max(runs, key=len)
        if step_type == 14:
            role = "user"
        elif text.lstrip(" @GWc{").startswith('"') or '{"' in text[:4]:
            role, text = "tool", text.lstrip("@GWcK:\"$ ")
        else:
            role = "assistant"
        yield {"time": mtime - (len(rows) - idx), "role": role, "text": text}


def _deepseek(path):
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        yield {"time": d.get("time", 0), "role": "user", "text": f"[{d.get('model')} · {d.get('purpose', '')}] {d.get('prompt', '')}"}
        yield {"time": d.get("time", 0), "role": "assistant", "text": d.get("reply", "")}


READERS = {"claude": _claude, "codex": _codex, "agy": _agy, "deepseek": _deepseek}


def events(agent, path):
    for e in READERS[agent](path):
        yield {"agent": agent, "session": Path(path).stem, **e, "text": redact(e["text"])}


def tail(agent, n=30):
    files = sessions(agent)
    return list(events(agent, files[0]))[-n:] if files else []


def user_messages(days=30, agents=AGENTS):
    """What the human typed to every agent in the last `days` days (deepseek prompts are machine-made: skipped)."""
    since = time.time() - days * 86400
    for agent in agents:
        if agent == "deepseek":
            continue
        if agent == "agy":  # the conversation dbs are mostly agy -p runs; typed prompts live in history.jsonl
            history = HOME / ".gemini/antigravity-cli/history.jsonl"
            for line in (open(history, encoding="utf-8", errors="replace") if history.is_file() else []):
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if _ts(d.get("timestamp")) >= since and d.get("display", "").strip():
                    yield {"agent": "agy", "session": "history", "time": _ts(d["timestamp"]), "role": "user",
                           "text": redact(d["display"])}
            continue
        for path in sessions(agent):
            if os.path.getmtime(path) < since:
                break
            for e in events(agent, path):
                if e["role"] == "user" and e["time"] >= since and not e.get("auto"):
                    yield e


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 3 and sys.argv[1] == "tail":
        for e in tail(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 20):
            print(time.strftime("%H:%M:%S", time.localtime(e["time"])), e["role"], "|", e["text"][:200].replace("\n", " "))
    elif len(sys.argv) >= 2 and sys.argv[1] == "users":
        rows = list(user_messages(float(sys.argv[2]) if len(sys.argv) > 2 else 7))
        print(len(rows), "user messages")
        for e in rows[-10:]:
            print(e["agent"], "|", e["text"][:120].replace("\n", " "))
    else:
        print(__doc__)
