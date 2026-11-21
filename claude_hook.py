"""Claude Code hook: makes the interactive Claude session show on the capsule's claude slot.

UserPromptSubmit -> start (ring spins, tooltip shows the prompt), PreToolUse -> ping (tooltip shows the tool),
Stop -> stop (ring stops). Writes the same .ai_bus/llm_active/ marker llm.activity() uses; never fails the hook.
"""
import json
import sys
import time
from pathlib import Path

FOLDER = Path(__file__).resolve().parent / ".ai_bus" / "llm_active"


def main(action):
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    session = "".join(c for c in str(data.get("session_id", "x")) if c.isalnum() or c == "-")[:40] or "x"
    path = FOLDER / f"claude-{session}.json"
    if action == "stop":
        path.unlink(missing_ok=True)
        return
    if action == "start":
        purpose = "思考: " + " ".join(str(data.get("prompt", "")).split())[:30]
    else:
        old = {}
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        purpose = f"工具: {data.get('tool_name', '?')}" if data.get("tool_name") else old.get("purpose", "工作中")
    FOLDER.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"slot": "claude", "model": "Claude Code", "purpose": purpose, "started": time.time()},
                               ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else "ping")
    except Exception:
        pass  # the capsule is a view: a hook error must never block Claude
