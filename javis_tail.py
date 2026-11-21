"""One pane of the Javis terminal: live status + recent conversation of one agent. No model calls (0 tokens).

python javis_tail.py <claude|agy|codex|deepseek>     (javis_term.ps1 opens all four in a 2x2 Windows Terminal)
"""
import json
import os
import shutil
import sys
import time
import unicodedata
from pathlib import Path

import llm
import standin
import transcripts

ROOT = Path(__file__).resolve().parent
COLOR = {"claude": "38;2;255;159;10", "agy": "38;2;100;210;255", "codex": "38;2;48;209;88", "deepseek": "38;2;77;107;254"}
ROLE = {"user": ("你", "1;37"), "assistant": ("AI", "0"), "tool": ("⚙", "2")}


def wrap(text, width, limit):
    """Split text into at most `limit` lines of <= width terminal columns (CJK = 2 columns)."""
    lines, cur, w = [], "", 0
    for ch in text:
        cw = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if w + cw > width:
            lines.append(cur)
            if len(lines) == limit:
                return lines
            cur, w = "", 0
        cur, w = cur + ch, w + cw
    return lines + [cur]


def status_line(agent):
    try:
        busy = agent in json.loads((ROOT / ".ai_bus" / "state.json").read_text(encoding="utf-8")).get("busy", [])
    except (OSError, ValueError):
        busy = False
    model = llm.active().get(agent)
    down = standin.active().get(agent)
    if model:
        local = "本地" if model["model"].endswith("-local") or model["model"] in ("claude-code", "antigravity") else "外部"
        text = f"● 忙  {model['model']}（{local}）· {model['purpose']}"
    elif busy:
        text = "● 忙"
    else:
        text = "○ 空闲"
    if down:
        text += f"  ·  已停用到 {time.strftime('%m-%d %H:%M', time.localtime(down['until']))}，DeepSeek 替补"
    return text


def render(agent, files_cache):
    cols, rows = shutil.get_terminal_size((100, 30))
    out = [f"[{COLOR[agent]};1m{agent.upper():<9}[0m " + wrap(status_line(agent), cols - 11, 1)[0]]
    files = transcripts.sessions(agent)
    if files:
        session, mtime = files[0], os.path.getmtime(files[0])
        if files_cache.get("key") != (session, mtime):  # re-parse only when the log changed
            files_cache.update(key=(session, mtime), events=list(transcripts.events(agent, session))[-200:])
        ago = int(time.time() - mtime)
        when = f"{ago}秒" if ago < 60 else f"{ago // 60}分" if ago < 3600 else f"{ago // 3600}小时" if ago < 86400 else f"{ago // 86400}天"
        out.append(f"\x1b[2m会话 {Path(session).stem[-12:]} · 最后更新 {when}前\x1b[0m")
    else:
        files_cache.update(key=None, events=[])
        out.append("\x1b[2m（还没有记录）\x1b[0m")
    out.append("─" * (cols - 1))
    lines = []
    for e in files_cache["events"]:
        label, style = ROLE.get(e["role"], ("?", "0"))
        stamp = time.strftime("%H:%M", time.localtime(e["time"])) if e["time"] else "--:--"
        text = " ".join(e["text"].split())
        chunk = wrap(text, cols - 10, 1 if e["role"] == "tool" else 3)
        lines.append(f"\x1b[2m{stamp}\x1b[0m \x1b[{style}m{label:<2} {chunk[0]}\x1b[0m")
        lines += [f"         \x1b[{style}m{c}\x1b[0m" for c in chunk[1:]]
    out += lines[-(rows - len(out) - 1):]
    return "\n".join(out)


def main(agent):
    if agent not in transcripts.AGENTS:
        sys.exit(f"agent must be one of {transcripts.AGENTS}")
    sys.stdout.reconfigure(encoding="utf-8")
    os.system("")  # enables ANSI colours in a classic Windows console
    os.system(f"title Javis · {agent}")
    cache, last = {}, None
    while True:
        try:
            frame = render(agent, cache)
        except Exception as exc:  # a half-written log line or a locked db must not kill the pane
            frame = f"{agent}: 读取失败 {exc!r}"
        if frame != last:
            sys.stdout.write("\x1b[2J\x1b[H" + frame)
            sys.stdout.flush()
            last = frame
        time.sleep(1.5)


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else "claude")
    except KeyboardInterrupt:
        pass
