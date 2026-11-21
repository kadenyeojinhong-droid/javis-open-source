"""DeepSeek stand-in: when codex/agy/claude is out (quota, rate limit, not installed), an API model takes the slot.

down.json records which agents are out and until when; the capsule swaps that slot's icon to DeepSeek.
"""
import json
import re
import subprocess
import time
from pathlib import Path

import llm
from transcripts import redact

ROOT = Path(__file__).resolve().parent
# only provider-side "you are out" wording: a plain "maximum recursion depth exceeded" must not bench an agent for 12 h
EXHAUSTED = re.compile(r"usage limit|rate.?limit|quota|insufficient (?:quota|credits?|balance|funds)|out of credits|"
                       r"purchase more|too many requests|\b429\b", re.I)
SECRET = re.compile(r"(^|[/\\])\.env|secret|token|credential|password|api.?key|\.pem$|\.key$|config\.ya?ml$", re.I)
# NTFS is case-insensitive and takes backslashes: both must be caught
UNSAFE_PATH = re.compile(r"^(?:---|\+\+\+) (?:[ab]/)?(?:[/\\]|[A-Za-z]:|.*\.\.[/\\]|\.git(?:[/\\]|$)|\.ai_bus[/\\])",
                         re.M | re.I)
# deepseek-r1-local is left out on purpose: on the RTX 4060 it thinks >300 s per coding task (bench 2026-11-18);
# it stays as the harness supervisor fallback, where a short JSON verdict takes ~1-2 min
DEFAULT_MODELS = ["deepseek-v4-flash", "gemma-4-26b-free"]


def _file(root):
    return Path(root or ROOT) / ".ai_bus" / "down.json"


def _load(root=None):
    try:
        return json.loads(_file(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def active(root=None):
    """{agent: reason} for agents still marked out."""
    now = time.time()
    return {agent: row.get("reason", "") for agent, row in _load(root).items() if row.get("until", 0) > now}


def is_down(agent, root=None):
    return agent in active(root)


def mark_down(agent, reason, hours=12, root=None):
    data = _load(root)
    data[agent] = {"until": time.time() + hours * 3600, "reason": reason[:200]}
    path = _file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_up(agent, root=None):
    data = _load(root)
    if data.pop(agent, None) is not None:
        _file(root).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def exhausted(text):
    return bool(EXHAUSTED.search(text or ""))


# the deepseek slot answers local-first (private, free); code goes to the API model since r1-local is too slow for it
CHAINS = {"standin_models": DEFAULT_MODELS, "deepseek_chain": ["deepseek-r1-local", "deepseek-v4-flash"],
          "deepseek_code_chain": ["deepseek-v4-flash", "gemma-4-26b-free"]}


def _models(root=None, key="standin_models"):
    try:
        settings = json.loads((Path(root or ROOT) / ".ai_bus" / "settings.json").read_text(encoding="utf-8-sig"))
        return settings.get(key) or CHAINS[key]
    except (OSError, json.JSONDecodeError):
        return CHAINS[key]


def _ask(messages, root=None, slot=None, purpose="", key="standin_models"):
    """First model in the chain that answers wins; returns (model, text)."""
    error = llm.LLMUnavailable("no stand-in model configured")
    profile = (root or ROOT) / ".ai_bus" / "distill" / "profile.md"
    for model in _models(root, key):
        sent = messages
        if model.endswith("-local") and profile.is_file():  # habit profile (distill.py) stays on this PC: local models only
            sent = [{"role": "system", "content": "用户习惯画像：\n" + profile.read_text(encoding="utf-8")[:4000]}] + messages
        try:
            with llm.activity(slot, model, purpose, root):
                return model, llm.chat(model, sent, timeout=240 if model.endswith("-local") else 300)
        except llm.LLMUnavailable as exc:
            error = exc
    raise error


def extract_diff(text):
    fenced = re.search(r"```(?:diff|patch)?\s*\n(.*?)```", text, re.S)
    body = fenced.group(1) if fenced else text
    start = body.find("diff --git")
    if start < 0:
        start = body.find("--- ")
    return body[start:].rstrip() + "\n" if start >= 0 else ""


def answer(prompt, root=None, slot="claude", key="standin_models"):
    """Stand-in for claude (or the deepseek slot itself): text reply only, no files touched."""
    try:
        model, text = _ask([{"role": "user", "content": redact(prompt)}], root, slot, "回答: " + prompt[:40], key)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        return 0, f"[stand-in {model}]\n{text}", ""
    except llm.LLMUnavailable as exc:
        return 1, "", f"stand-in unavailable: {exc}"


def implement(task_root, goal, files=(), root=None, slot=None, key="standin_models"):
    """Stand-in for codex/agy: ask for full new file contents (or a diff) and write them inside the task worktree."""
    task_root = Path(task_root)
    context = []
    for name in files:
        path = (task_root / name).resolve()
        if SECRET.search(str(name).replace("\\", "/")) or task_root.resolve() not in path.parents:
            continue  # never ship secrets or files outside the worktree to an outside API
        if path.is_file():
            context.append(f"=== {name}\n{redact(path.read_text(encoding='utf-8', errors='replace')[:20000])}")
    if not context:
        listing = subprocess.run(["git", "ls-files"], cwd=task_root, text=True, capture_output=True).stdout
        context.append("=== repo files\n" + "\n".join(listing.splitlines()[:200]))
    messages = [{"role": "system", "content": "You are a substitute coding agent. For EVERY file you change or create, "
                 "output its COMPLETE new content in this exact block, nothing else:\n<<<FILE relative/path.py>>>\n"
                 "...full file content...\n<<<END>>>\nNo prose, no markdown fences."},
                {"role": "user", "content": f"TASK:\n{goal}\n\nFILES:\n" + "\n\n".join(context)}]
    error = "no stand-in model configured"
    for model in _models(root, key):  # a model that answers with junk does not end the task: the next one gets a go
        try:
            with llm.activity(slot, model, "写代码: " + (goal.splitlines() or [""])[0][:40], root):
                text = llm.chat(model, messages, timeout=300)
        except llm.LLMUnavailable as exc:
            error = f"stand-in unavailable: {exc}"
            continue
        ok, detail = _apply(task_root, re.sub(r"<thought>.*?</thought>|<think>.*?</think>", "", text, flags=re.S))
        if ok:
            return 0, f"[stand-in {model}] {detail}", ""
        error = f"[stand-in {model}] {detail}"
    return 1, "", error


def _apply(task_root, text):
    """Write <<<FILE>>> blocks (preferred: models get full files right far more often than diff hunks), else git-apply a diff."""
    blocks = re.findall(r"<<<FILE\s+(.+?)>>>\n(.*?)\n?<<<END>>>", text, re.S)
    root = task_root.resolve()
    if blocks:
        for name, _ in blocks:
            target = (root / name.strip()).resolve()
            parts = {part.lower() for part in Path(name.strip()).parts}  # NTFS: .GIT == .git
            if root not in target.parents or ".git" in parts or ".ai_bus" in parts:
                return False, f"file {name.strip()!r} is outside the worktree or protected; rejected"
        for name, body in blocks:
            target = root / name.strip()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body.rstrip("\n") + "\n", encoding="utf-8")
        return True, "wrote " + ", ".join(n.strip() for n, _ in blocks)
    patch = extract_diff(text)
    if not patch:
        return False, "reply had no file blocks or diff"
    if UNSAFE_PATH.search(patch):
        return False, "diff touches .git/.ai_bus or leaves the worktree; rejected"
    applied = subprocess.run(["git", "apply", "--recount", "--whitespace=nowarn", "-"], cwd=task_root, input=patch,
                             text=True, capture_output=True)
    if applied.returncode:
        return False, f"git apply failed: {applied.stderr.strip()[:200]}"
    return True, "applied diff"


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] in ("down", "up"):
        if sys.argv[1] == "down":
            mark_down(sys.argv[2], "manual", float(sys.argv[3]) if len(sys.argv) > 3 else 12)
        else:
            mark_up(sys.argv[2])
    print(json.dumps(active(), ensure_ascii=False))
