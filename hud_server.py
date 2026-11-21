import asyncio
from collections import deque
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import bus
import harness
import standin
import state as state_store
import wt

ROOT = Path(__file__).resolve().parent
app = FastAPI()
events = deque(maxlen=500)  # read only by /ws; bounded so nothing piles up while no HUD is connected
busy_agents = set()
_AUDIT = ROOT / ".ai_bus" / "activity_audit.jsonl"
_audit_pos = _AUDIT.stat().st_size if _AUDIT.exists() else 0  # stream only new activity, not the whole history, after a restart
CONSOLE_HWND = None
JAVIS_SCRIPT = ROOT / "javis_term.ps1"  # 2x2 live panes (javis_tail.py); old start_javis.ps1 still had a gemini pane

try:
    import ctypes
    CONSOLE_HWND = ctypes.windll.kernel32.GetConsoleWindow()
    if CONSOLE_HWND:
        ctypes.windll.kernel32.SetConsoleTitleW("Agent HUD Server")
        ctypes.windll.user32.ShowWindow(CONSOLE_HWND, 0)
except (AttributeError, OSError):
    CONSOLE_HWND = None


def push(sender, receiver, action, chars_in=0, chars_out=0):
    rate = round(1 - chars_out / chars_in, 4) if chars_in else 0
    bus.audit({"sender": sender, "receiver": receiver, "action": action, "chars_in": chars_in,
               "chars_out": chars_out, "compression_rate": rate})
    print(f"{time.strftime('%H:%M:%S')}  {sender} -> {receiver}  {action}  {rate:.0%}", flush=True)
    events.append({"type": action, "sender": sender, "receiver": receiver, "action": action,
                "summary": "", "compression_rate": rate, "time": time.strftime("%H:%M:%S")})


def _foreign(origin):
    # browsers send Origin on cross-site calls; local tools (HUD, approve.py, curl) send none
    return bool(origin) and re.fullmatch(r"https?://(127\.0\.0\.1|localhost)(:\d+)?", origin) is None


def _bad_host(host):
    # DNS rebinding: evil.com resolving to 127.0.0.1 sends same-origin GETs with no Origin but Host: evil.com
    return re.fullmatch(r"(127\.0\.0\.1|localhost|testserver)(:\d+)?", host or "") is None


@app.middleware("http")
async def local_pages_only(request, call_next):
    # any web page could otherwise POST here (no-body POSTs skip the browser's preflight): reset the breaker, open the workbench
    if _foreign(request.headers.get("origin")) or _bad_host(request.headers.get("host")):
        return JSONResponse({"error": "forbidden origin"}, status_code=403)
    return await call_next(request)


def _settings_path(): return ROOT / ".ai_bus" / "settings.json"


@app.get("/settings")
def get_settings(): return bus.settings(_settings_path().parent)


@app.post("/settings")
def post_settings(data: dict):
    current = bus.settings(_settings_path().parent)
    allowed = {"allow_hud", "allow_agent_messages", "breaker_limit", "language", "auto_hide", "idle_seconds"}
    if set(data) - allowed: return JSONResponse({"error": "unknown setting"}, status_code=400)
    value = {**current, **data}
    if (any(type(value[k]) is not bool for k in ("allow_hud", "allow_agent_messages")) or
            type(value["breaker_limit"]) is not int or not 1 <= value["breaker_limit"] <= 50 or
            type(value["auto_hide"]) is not bool or type(value["idle_seconds"]) is not int or not 5 <= value["idle_seconds"] <= 120 or
            value.get("language") not in ("zh", "en")):
        return JSONResponse({"error": "invalid settings"}, status_code=400)
    _settings_path().parent.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    events.append({"type": "settings", "settings": value})
    return value


@app.get("/console")
def get_console():
    if not CONSOLE_HWND:
        return {"ok": False, "visible": False}
    return {"ok": True, "visible": bool(__import__("ctypes").windll.user32.IsWindowVisible(CONSOLE_HWND))}


@app.post("/console")
def post_console(data: dict):
    if not CONSOLE_HWND:
        return {"ok": False}
    import ctypes
    if type(data.get("show")) is not bool:
        return JSONResponse({"error": "invalid console state"}, status_code=400)
    if data["show"]:
        ctypes.windll.user32.ShowWindow(CONSOLE_HWND, 5)
        ctypes.windll.user32.SetForegroundWindow(CONSOLE_HWND)
    else:
        ctypes.windll.user32.ShowWindow(CONSOLE_HWND, 0)
    return {"ok": True, "visible": data["show"]}


@app.post("/workbench")
def workbench():
    if not JAVIS_SCRIPT.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(JAVIS_SCRIPT)])
    return {"ok": True}


@app.get("/agents")
def get_agents():
    return bus.agents(_settings_path().parent)


@app.post("/agents")
def post_agents(data: object = Body(...)):
    known = {item["id"] for item in bus.DEFAULT_AGENTS}
    if (not isinstance(data, list) or len(data) != len(known) or not all(isinstance(item, dict) for item in data) or
            not all(isinstance(item.get("id"), str) for item in data) or
            {item.get("id") for item in data} != known):
        return JSONResponse({"error": "invalid agents"}, status_code=400)
    for item in data:
        if (set(item) != {"id", "name", "role", "color", "enabled"} or
                not isinstance(item["name"], str) or len(item["name"]) > 20 or
                not isinstance(item["role"], str) or len(item["role"]) > 40 or
                not isinstance(item["enabled"], bool) or
                not isinstance(item["color"], str) or
                re.fullmatch(r"#[0-9A-Fa-f]{6}", item["color"]) is None):
            return JSONResponse({"error": "invalid agent fields"}, status_code=400)
    if not any(item["enabled"] for item in data):
        return JSONResponse({"error": "at least one agent must be enabled"}, status_code=400)
    ordered = [next(item for item in data if item["id"] == ident) for ident in [a["id"] for a in bus.DEFAULT_AGENTS]]
    root = _settings_path().parent
    root.mkdir(parents=True, exist_ok=True)
    (root / "agents.json").write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    events.append({"type": "agents", "agents": ordered})
    return ordered


@app.get("/state")
def state():
    return state_store.build(ROOT)


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    if _foreign(websocket.headers.get("origin")) or _bad_host(websocket.headers.get("host")):  # http middleware does not cover websockets
        await websocket.close(code=1008)
        return
    await websocket.accept()
    global _audit_pos
    while True:
        payload = []
        while events:
            payload.append(events.popleft())
        audit = ROOT / ".ai_bus" / "activity_audit.jsonl"
        if audit.exists():
            with audit.open("rb") as f:
                f.seek(_audit_pos)
                lines = f.readlines()
                if lines and not lines[-1].endswith(b"\n"):
                    lines.pop()  # still being appended: read it whole next second (a half line used to crash this socket)
                _audit_pos += sum(len(x) for x in lines)
            payload += [{"type": "activity", **json.loads(x)} for x in lines if x.strip()]
        payload.append({"type": "state", **state()})
        try:
            await websocket.send_json(payload)
        except WebSocketDisconnect:
            return
        await asyncio.sleep(1)


class Order(BaseModel):
    text: str


class Dispatch(BaseModel):
    option: str
    modules: list[str] = []
    text: str = ""
    extra: str = ""


class Decision(BaseModel):
    approved: bool


@app.post("/order")
def order(data: Order):
    try:
        import nlp_compressor
    except ImportError as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    try:
        return nlp_compressor.compress(data.text)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.post("/dispatch")
def dispatch(data: Dispatch):
    body = "\n".join(x for x in (data.option, ", ".join(data.modules), data.extra) if x)
    return bus.send("human", "codex", body)  # bus.send audits it; the audit stream flies the plane


@app.post("/approve/{ident}")
def approve(ident: str, decision: Decision):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", ident):  # "..\settings" used to rewrite any json under .ai_bus
        return JSONResponse({"error": "not found"}, status_code=404)
    path = ROOT / ".ai_bus" / "approvals" / f"{ident}.json"
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    item = json.loads(path.read_text(encoding="utf-8"))
    if item.get("status") != "pending":
        return JSONResponse({"error": "already decided"}, status_code=409)
    item["status"] = "approved" if decision.approved else "denied"
    bus._write(path, item)
    state_store.write(ROOT)
    return item


@app.post("/reset_breaker")
def reset_breaker():
    bus.reset()
    return {"status": "reset"}


def handle(agent, item):
    try:
        envelope = {}
        try:
            candidate = json.loads(item["body"])
            if isinstance(candidate, dict) and isinstance(candidate.get("task_id"), str):
                envelope = candidate
        except (json.JSONDecodeError, TypeError):
            pass
        body = envelope.get("goal", item["body"])
        if envelope.get("files"):
            body += "\n只改这些文件：" +", ".join(map(str, envelope["files"]))
        task_id = envelope.get("task_id") or item.get("task_id") or f"{agent}-{time.strftime('%Y%m%d%H%M%S')}"
        task_id = re.sub(r"[^A-Za-z0-9_-]", "_", task_id)[:40]
        if agent == "claude" and bus.approve("hud", "wake claude", item["body"], 300) != "approved":
            push(item["sender"], agent, "approval_denied")
            return
        def run_standin(reason):
            # codex/agy/claude is out: DeepSeek (or the next API model in the chain) takes the slot
            standin.mark_down(agent, reason, root=ROOT)
            events.append({"type": "standin", "agent": agent, "reason": reason[:120]})
            busy_agents.add(agent)
            state_store.write(ROOT)
            events.append({"type": "state", **state()})
            try:
                if agent == "claude":
                    rc, out, err = standin.answer(item["body"], ROOT, agent)
                else:
                    rc, out, err = standin.implement(wt.create(agent, task_id), body, envelope.get("files") or [], ROOT, agent)
            finally:
                busy_agents.discard(agent)
                state_store.write(ROOT)
                events.append({"type": "state", **state()})
            return subprocess.CompletedProcess(["standin"], rc, out, err)

        if agent not in ("codex", "agy", "claude", "deepseek"):
            return
        coding = agent in ("codex", "agy") or (agent == "deepseek" and bool(envelope))
        task_root = wt.create(agent, task_id) if coding else ROOT
        if agent == "deepseek":  # always-on slot: local model first for answers, API model for code (r1-local is too slow)
            cmd, stood_in = ["deepseek"], False
            busy_agents.add(agent)
            state_store.write(ROOT)
            events.append({"type": "state", **state()})
            try:
                if coding:
                    rc, out, err = standin.implement(task_root, body, envelope.get("files") or [], ROOT, agent, "deepseek_code_chain")
                else:
                    rc, out, err = standin.answer(item["body"], ROOT, agent, "deepseek_chain")
            finally:
                busy_agents.discard(agent)
                state_store.write(ROOT)
                events.append({"type": "state", **state()})
            result = subprocess.CompletedProcess(cmd, rc, out, err)
        elif agent == "codex":
            cmd = ["codex", "exec", "-s", "workspace-write", "-C", str(task_root), body]
        elif agent == "agy":
            cmd = ["agy", "-p", body, "--mode", "accept-edits", "--print-timeout", "600s"]
        else:
            cmd = ["claude", "-p", item["body"]]
        stood_in = False
        executable = shutil.which(cmd[0]) if agent != "deepseek" else None
        if agent == "deepseek":
            pass  # already answered above
        elif standin.is_down(agent, ROOT) or executable is None:
            stood_in = True
            result = run_standin("marked down" if executable else f"{cmd[0]} not installed")
        else:
            cmd[0] = executable
            busy_agents.add(agent)
            state_store.write(ROOT)
            events.append({"type": "state", **state()})
            try:
                result = subprocess.run(cmd, cwd=task_root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
            finally:
                busy_agents.discard(agent)
                state_store.write(ROOT)
                events.append({"type": "state", **state()})
            if result.returncode and standin.exhausted(result.stdout[-2000:] + result.stderr[-2000:]):
                result, stood_in = run_standin(f"{agent} quota/rate limit"), True
        if (stood_in and agent in ("codex", "agy") or agent == "deepseek" and coding) and result.returncode == 0:
            # stand-in work is gated at once (tests + blacklist + fastest supervisor model), not left for a manual audit
            threading.Thread(target=harness.gate, args=(task_id,), daemon=True).start()
        if coding:
            review_dir = ROOT / ".ai_bus" / "reviews"
            review_dir.mkdir(parents=True, exist_ok=True)
            (review_dir / f"{task_id}.diff").write_text(wt.diff(task_id), encoding="utf-8")
            events.append({"type": "review_ready", "task_id": task_id})
        log = ROOT / ".ai_bus" / "logs" / f"{agent}_{time.strftime('%Y%m%d_%H%M%S')}.log"  # full reply, for review
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f"$ {cmd[0]}{' (DeepSeek stand-in)' if stood_in else ''} ...\n--- body\n{item['body']}\n--- stdout\n{result.stdout}\n--- stderr\n{result.stderr}", encoding="utf-8")
        summary = next((line.strip() for line in reversed(result.stdout.splitlines()) if line.strip()), "")[:120]
        events.append({"type": "completed" if result.returncode == 0 else "failed", "sender": item["sender"], "receiver": agent, "summary": summary})
        push(item["sender"], agent, "completed" if result.returncode == 0 else "failed",
             len(item["body"]), len(result.stdout))
    except Exception as exc:  # any error (git, a bad envelope, a None reply): record it, never drop the message
        print(f"handle {agent}: {exc!r}", flush=True)
        events.append({"type": "failed", "sender": item.get("sender", "?"), "receiver": agent, "summary": repr(exc)[:120]})
        push(item.get("sender", "?"), agent, "failed", len(item.get("body", "")), 0)
        failed = ROOT / ".ai_bus" / "failed" / f"{agent}.jsonl"
        failed.parent.mkdir(parents=True, exist_ok=True)
        with failed.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def worker(agent):
    # one thread per agent: a 5-minute claude approval or a 15-minute codex run no longer holds up the others
    while True:
        try:
            if (ROOT / ".ai_bus" / "HALT").exists():  # stop taking new work; /state reports halted live
                time.sleep(2)
                continue
            for item in bus.take(agent):  # take() already removed these from the inbox, so finish them all
                handle(agent, item)
        except Exception as e:  # a locked inbox or a bad message must not stop this agent forever
            print(f"worker {agent}: {e!r}", flush=True)
        time.sleep(1)



if __name__ == "__main__":
    for name in ("codex", "agy", "claude", "deepseek"):
        threading.Thread(target=worker, args=(name,), daemon=True).start()
    import harness  # supervisor watchdog: writes .ai_bus/HALT on runaway loops / hot files / stuck processes
    threading.Thread(target=harness.main, args=(["watch"],), daemon=True).start()
    __import__("uvicorn").run(app, host="127.0.0.1", port=8765)
