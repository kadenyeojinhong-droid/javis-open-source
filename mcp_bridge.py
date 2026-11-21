try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    from mcp.server.mcpserver import MCPServer as FastMCP
import bus
import json
import re
from pathlib import Path
import wt

mcp = FastMCP("paper-plane")


def _enabled():
    return bus.settings().get("allow_hud", True)


@mcp.tool()
def send_paper_plane(sender: str, receiver: str, body: str) -> dict:
    if not _enabled(): return {"status": "hud_disabled"}
    return bus.send(sender, receiver, body)


@mcp.tool()
def request_human_approval(agent: str, action: str, detail: str, timeout_s: int = 300) -> str:
    if not _enabled(): return {"status": "hud_disabled"}
    return bus.approve(agent, action, detail, timeout_s)


@mcp.tool()
def log_agent_activity(sender: str, receiver: str, action: str, chars_in: int, chars_out: int) -> dict:
    if not _enabled(): return {"status": "hud_disabled"}
    record = {"sender": sender, "receiver": receiver, "action": action, "chars_in": chars_in, "chars_out": chars_out,
              "compression_rate": round(1 - chars_out / chars_in, 4) if chars_in else 0}
    bus.audit(record)
    return record


def _valid_task(task_id):
    return isinstance(task_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", task_id) is not None


@mcp.tool()
def codex_implement(task_id: str, goal: str, files: list[str]) -> dict:
    """Queue an isolated Codex task; poll review_status for completion."""
    if not _enabled(): return {"error": "hud_disabled"}
    if (not _valid_task(task_id) or not isinstance(goal, str) or not goal.strip() or len(goal) > 20000 or
            not isinstance(files, list) or len(files) > 100 or
            not all(isinstance(name, str) and name and not Path(name).is_absolute() and ".." not in Path(name).parts for name in files)):
        return {"error": "invalid task input"}
    try:
        result = bus.send("claude", "codex", json.dumps({"task_id": task_id, "goal": goal, "files": files}, ensure_ascii=False))
        if result.get("status") != "sent": return {"error": result.get("status", "dispatch failed")}
        path = wt._path("codex", task_id)
        return {"task_id": task_id, "worktree": str(path), "diff_path": str(Path(__file__).resolve().parent / ".ai_bus" / "reviews" / f"{task_id}.diff"), "gate": None}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def review_status(task_id: str) -> dict:
    if not _valid_task(task_id): return {"error": "invalid task_id"}
    try:
        root = Path(__file__).resolve().parent
        diff_path = root / ".ai_bus" / "reviews" / f"{task_id}.diff"
        reports = sorted((root / ".ai_bus" / "gate").glob(f"*-{task_id}.json"), reverse=True)
        gate = json.loads(reports[0].read_text(encoding="utf-8")) if reports else None
        merged = not any(row["task_id"] == task_id for row in wt.status()) and not any(
            line.strip() == f"feat/{task_id}" for line in __import__("subprocess").run(
                ["git", "branch", "--list", f"feat/{task_id}"], cwd=root, capture_output=True, text=True).stdout.splitlines())
        return {"diff": diff_path.read_text(encoding="utf-8")[:20000] if diff_path.exists() else "", "gate": gate, "merged": merged}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def supervisor_audit(task_id: str) -> dict:
    if not _valid_task(task_id): return {"error": "invalid task_id"}
    try:
        import harness
        report = harness.gate(task_id)
        return {"verdict": report["verdict"], "reasons": report["reasons"], "checks": report["checks"]}
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run()
