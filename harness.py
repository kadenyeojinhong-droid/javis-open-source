"""Local quality gate and activity watchdog."""
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import bus
import llm
import wt

ROOT = Path(__file__).resolve().parent
BAD = re.compile(r"--dangerously|bypass|HKLM|Remove-Item\s+.*-Recurse|rm\s+-rf\s+/|BypassSandbox", re.I)


def _git(*args, cwd=None):
    return subprocess.run(["git", *map(str, args)], cwd=cwd or ROOT, text=True,
                          encoding="utf-8", errors="replace", capture_output=True, check=True).stdout


def _report(task_id, verdict, checks, reasons):
    directory = ROOT / ".ai_bus" / "gate"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    report = {"task_id": task_id, "verdict": verdict, "checks": checks, "reasons": reasons[:3], "time": stamp}
    (directory / f"{stamp}-{task_id}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def gate(task_id):
    changes = wt.diff(task_id)
    rows = [row for row in wt.status() if row["task_id"] == task_id]
    if not rows:
        raise ValueError("worktree not found")
    path = Path(rows[0]["path"])
    static_bad = any(BAD.search(line[1:]) for line in changes.splitlines() if line.startswith("+") and not line.startswith("+++"))
    try:
        if static_bad:  # never execute a diff that already tripped the blacklist: pytest would run that code
            raise subprocess.TimeoutExpired("pytest", 0, output="skipped: forbidden pattern in diff")
        result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=path, text=True,
                                encoding="utf-8", errors="replace", capture_output=True, timeout=900)
        tests_ok = result.returncode == 0
        test_output = (result.stdout + result.stderr)[-12000:]
    except subprocess.TimeoutExpired as exc:
        tests_ok, test_output = False, exc.output if static_bad else f"pytest timeout: {exc}"
    changes = changes.replace("\r\n", "\n")  # git on Windows: CRLF made "(.+)$" capture "name\r" and miss every file
    changed = set(re.findall(r"^\+\+\+ b/(.+)$", changes, re.M)) | set(re.findall(r"^--- a/(.+)$", changes, re.M))
    changed = {name for name in changed if name.endswith(".py") and not name.startswith("tests/") and not name.startswith(".ai_bus/")}
    tests_changed = any(name.startswith("tests/") and name.endswith(".py") for name in
                        (set(re.findall(r"^\+\+\+ b/(.+)$", changes, re.M)) | set(re.findall(r"^--- a/(.+)$", changes, re.M))))
    checks = {"pytest": "PASS" if tests_ok else "FAIL", "tests_for_python": "PASS" if not changed or tests_changed else "FAIL",
              "static": "FAIL" if static_bad else "PASS"}
    reasons = []
    if not tests_ok: reasons.append("pytest failed")
    if changed and not tests_changed: reasons.append("Python changes lack test changes")
    if checks["static"] == "FAIL": reasons.append("forbidden pattern in added diff")
    try:
        response = llm.supervise([{"role": "system", "content": 'Review the diff and test output. Reply only JSON: {"verdict":"PASS|FAIL","reasons":[]}.'},
                                    {"role": "user", "content": f"DIFF:\n{changes[:40000]}\nTESTS:\n{test_output}"}], ROOT,
                                   slot=rows[0].get("agent"), purpose=f"监管审查 {task_id}")  # spins the slot whose work is reviewed
        review = json.loads(response)
        checks["llm"] = review.get("verdict", "FAIL")
        if checks["llm"] not in ("PASS", "FAIL"): checks["llm"] = "FAIL"
        reasons.extend(str(x) for x in review.get("reasons", [])[:3])
    except llm.LLMUnavailable:
        checks["llm"] = "skipped"
    except (ValueError, TypeError, AttributeError):
        checks["llm"] = "FAIL"
        reasons.append("invalid LLM review response")
    verdict = "PASS" if all(checks[k] == "PASS" for k in ("pytest", "tests_for_python", "static")) and checks["llm"] in ("PASS", "skipped") else "FAIL"
    return _report(task_id, verdict, checks, reasons)


def _halt(reason):
    path = ROOT / ".ai_bus" / "HALT"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(reason, encoding="utf-8")


def watch_once(position=0):
    path = ROOT / ".ai_bus" / "activity_audit.jsonl"
    if not path.exists(): return position
    with path.open("r", encoding="utf-8") as stream:
        stream.seek(position)
        lines = stream.readlines()
        position = stream.tell()
    entries = []
    for line in lines:
        try: entries.append(json.loads(line))
        except json.JSONDecodeError: continue
    if len(entries) >= 2:
        limit = bus.settings(ROOT / ".ai_bus").get("breaker_limit", 10)
        tail = entries[-(limit + 1):]
        pairs = [tuple(sorted((str(e.get("sender", "")), str(e.get("receiver", ""))))) for e in tail]
        if len(pairs) >= limit + 1 and len(set(pairs)) == 1:
            _halt(f"agent pair exceeded breaker limit ({limit})")
    cutoff = time.time() - 1800
    counts = {}
    for row in wt.status():
        try:
            log = _git("log", "--since=30 minutes ago", "--name-only", "--pretty=format:", cwd=row["path"])
            for name in log.splitlines(): counts[name] = counts.get(name, 0) + 1
        except subprocess.CalledProcessError: pass
    repeated = next((name for name, count in counts.items() if count > 5), None)
    if repeated: _halt(f"file changed more than 5 times in 30 minutes: {repeated}")
    if any(time.time() - float(e.get("time", 0)) > 900 for e in entries if e.get("action") == "process_running"):
        _halt("child process exceeded 900 seconds")
    return position


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv or argv[0] not in ("gate", "watch", "resume"):
        raise SystemExit("usage: harness.py gate <task_id>|watch|resume")
    if argv[0] == "gate":
        if len(argv) != 2: raise SystemExit("task_id required")
        print(json.dumps(gate(argv[1]), ensure_ascii=False, indent=2))
    elif argv[0] == "resume":
        (ROOT / ".ai_bus" / "HALT").unlink(missing_ok=True)
    else:
        position = (ROOT / ".ai_bus" / "activity_audit.jsonl").stat().st_size if (ROOT / ".ai_bus" / "activity_audit.jsonl").exists() else 0
        while True:
            position = watch_once(position)
            time.sleep(5)


if __name__ == "__main__": main()
