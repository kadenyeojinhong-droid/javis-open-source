"""Git worktree helpers for isolated agent tasks."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASK_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _git(*args, cwd=None):
    return subprocess.run(["git", *map(str, args)], cwd=cwd or ROOT, text=True,
                          encoding="utf-8", errors="replace", capture_output=True, check=True).stdout.strip()


def _task(task_id):
    if not isinstance(task_id, str) or not TASK_RE.fullmatch(task_id):
        raise ValueError("invalid task_id")
    return task_id


def _path(agent, task_id):
    if not isinstance(agent, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", agent):
        raise ValueError("invalid agent")
    return ROOT.parent / f"wt-{agent}-{_task(task_id)}"


def create(agent, task_id):
    path = _path(agent, task_id)
    if path.exists():
        return path
    branch = f"feat/{task_id}"
    _git("worktree", "add", "-b", branch, str(path))
    return path


def status():
    rows = []
    for line in _git("worktree", "list", "--porcelain").splitlines():
        if not line.startswith("worktree "):
            continue
        path = Path(line[9:])
        if path.resolve() == ROOT.resolve():
            continue
        match = re.fullmatch(r"wt-([A-Za-z0-9_-]+)-([A-Za-z0-9_-]{1,40})", path.name)
        if not match:
            continue
        if not path.is_dir():  # folder deleted by hand: one stale row must not make /state 500 forever
            _git("worktree", "prune")
            continue
        try:
            branch = _git("-C", str(path), "branch", "--show-current")
            ahead = int(_git("rev-list", "--count", f"{_git('rev-parse', '--abbrev-ref', 'HEAD')}..{branch}"))
            dirty = bool(_git("-C", str(path), "status", "--porcelain"))
        except (subprocess.CalledProcessError, ValueError):
            continue
        rows.append({"agent": match.group(1), "task_id": match.group(2), "path": str(path),
                     "branch": branch, "ahead": ahead, "dirty": dirty})
    return rows


def diff(task_id):
    task_id = _task(task_id)
    base = _git("rev-parse", "--abbrev-ref", "HEAD")
    branch = f"feat/{task_id}"
    result = _git("diff", f"{base}...{branch}")
    entries = [row for row in status() if row["task_id"] == task_id]
    if entries:
        _git("-C", entries[0]["path"], "add", "--intent-to-add", ".")  # make new untracked files show up in diff
        extra = _git("-C", entries[0]["path"], "diff", "HEAD")
        staged = _git("-C", entries[0]["path"], "diff", "--cached")
        result += ("\n" if result and (extra or staged) else "") + staged + extra
    return result


def merge(task_id, timeout_s=300):
    task_id = _task(task_id)
    import bus
    if bus.approve("claude", "git merge", f"Merge feat/{task_id}", timeout_s) != "approved":
        return False
    try:
        _git("merge", "--no-ff", f"feat/{task_id}")
    except subprocess.CalledProcessError:
        subprocess.run(["git", "merge", "--abort"], cwd=ROOT, capture_output=True)  # never leave main stuck in MERGING
        return False
    rows = [row for row in status() if row["task_id"] == task_id]
    if rows:
        _git("worktree", "remove", rows[0]["path"])
    _git("branch", "-d", f"feat/{task_id}")
    return True


def drop(task_id, timeout_s=300):
    task_id = _task(task_id)
    import bus
    if bus.approve("claude", "git merge", f"Drop worktree feat/{task_id}", timeout_s) != "approved":
        return False
    rows = [row for row in status() if row["task_id"] == task_id]
    if rows:
        _git("worktree", "remove", "--force", rows[0]["path"])
    _git("branch", "-D", f"feat/{task_id}")
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("list", "diff", "merge", "drop"))
    parser.add_argument("task_id", nargs="?")
    args = parser.parse_args()
    if args.command == "list":
        import json
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    elif not args.task_id:
        parser.error("task_id required")
    elif args.command == "diff":
        print(diff(args.task_id))
    else:
        print("approved" if (merge if args.command == "merge" else drop)(args.task_id) else "denied")
