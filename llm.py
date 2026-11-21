"""Small OpenAI-compatible CLIProxyAPI client."""
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent


_current = threading.local()  # slot/purpose of the activity() block this thread is in, for the call log


class LLMUnavailable(RuntimeError):
    pass


def _settings(root=None):
    try:
        return json.loads(((root or ROOT) / ".ai_bus" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def supervisor_model(root=None):
    return _settings(root).get("supervisor_model") or "deepseek-reasoner"


@contextmanager
def activity(slot, model, purpose, root=None):
    """While a model call runs, a file in .ai_bus/llm_active/ says which capsule slot is working, on what, with which
    model. One file per call (not a shared JSON) so harness CLI, mcp_bridge and hud_server never clobber each other."""
    folder = (root or ROOT) / ".ai_bus" / "llm_active"
    path = folder / f"{os.getpid()}-{uuid.uuid4().hex[:8]}.json"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"slot": slot, "model": model, "purpose": purpose[:60], "started": time.time()},
                                   ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # the HUD is only a view: a failed marker must never stop the real work
    previous = getattr(_current, "info", None)
    _current.info = {"slot": slot, "purpose": purpose[:60]}
    try:
        yield
    finally:
        _current.info = previous
        try:
            path.unlink()
        except OSError:
            pass


def active(root=None, max_age=1800):
    """{slot: {"model", "purpose"}} for calls in flight; markers older than max_age are leftovers of a killed process."""
    rows = {}
    for path in ((root or ROOT) / ".ai_bus" / "llm_active").glob("*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if time.time() - row.get("started", 0) > max_age:
            try:
                path.unlink()
            except OSError:
                pass
            continue
        rows[row.get("slot") or "harness"] = {"model": row.get("model", ""), "purpose": row.get("purpose", "")}
    return rows


def supervise(messages, root=None, slot=None, purpose="审查", timeout=60):
    """Fastest first: the main supervisor model, then each fallback only if the one before fails.
    The harness must answer in seconds so mistakes are caught while you watch; a model slower than `timeout` is skipped."""
    fallback = _settings(root).get("supervisor_fallback") or []
    models = [supervisor_model(root), *([fallback] if isinstance(fallback, str) else fallback)]
    error = LLMUnavailable("no supervisor model configured")
    for model in filter(None, models):
        try:
            with activity(slot, model, purpose, root):
                return chat(model, messages, json_mode=True, timeout=timeout)
        except LLMUnavailable as exc:
            error = exc
    raise error


def chat(model, messages, json_mode=False, timeout=120):
    key = os.environ.get("CLIPROXY_API_KEY")
    if not key:
        raise LLMUnavailable("CLIPROXY_API_KEY is not set")
    try:
        req = Request("http://127.0.0.1:8317/v1/chat/completions",
                      data=json.dumps({"model": model, "messages": messages,
                                       **({"response_format": {"type": "json_object"}} if json_mode else {})}).encode(),
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
    except (URLError, TimeoutError, OSError, ValueError, KeyError, IndexError) as exc:
        raise LLMUnavailable(str(exc)) from exc
    if not isinstance(content, str):
        raise LLMUnavailable(f"{model} returned no text")
    _log_call(model, messages, content)
    return content


def _log_call(model, messages, reply):
    """One line per call in .ai_bus/llm_calls.jsonl: the DeepSeek pane of the Javis terminal reads it."""
    try:
        import transcripts  # lazy: transcripts is optional for llm's callers
        prompt = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        line = {"time": time.time(), "model": model, **(getattr(_current, "info", None) or {}), "prompt": transcripts.redact(str(prompt))[:1500],
                "reply": transcripts.redact(reply)[:3000]}
        with open(ROOT / ".ai_bus" / "llm_calls.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass  # logging must never break a model call
