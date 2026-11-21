"""Approve or deny pending high-risk actions from the terminal (the HUD no longer shows approval buttons).

    python approve.py                 list pending requests
    python approve.py <id> yes|no     approve or deny one (an id prefix is enough)
    python approve.py all no          deny everything pending

Unanswered requests time out as denied, so doing nothing is always the safe choice.
"""
import json
import sys
import urllib.request

API = "http://127.0.0.1:8765"


def call(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def main(argv):
    try:
        pending = call("/state").get("approvals", [])
    except OSError:
        print("hud_server is not running on 127.0.0.1:8765 (start it with launch_hud.ps1).")
        return 1
    if len(argv) < 2:
        if not pending:
            print("No pending approvals.")
        for a in pending:
            print(f"{a['id'][:8]}  {a.get('agent', '?'):<8} {a.get('action', '')}  {a.get('detail', '')}")
        return 0
    target, answer = argv[0], argv[1].lower()
    if answer not in ("yes", "no", "y", "n"):
        print("Answer must be yes or no.")
        return 2
    picked = pending if target == "all" else [a for a in pending if a["id"].startswith(target)]
    if not picked:
        print(f"No pending approval matches '{target}'.")
        return 1
    if target != "all" and len(picked) > 1:
        print(f"'{target}' matches {len(picked)} requests; use a longer id.")
        return 1
    for a in picked:
        call(f"/approve/{a['id']}", {"approved": answer.startswith("y")})
        print(f"{'approved' if answer.startswith('y') else 'denied'}: {a['id'][:8]} {a.get('action', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
