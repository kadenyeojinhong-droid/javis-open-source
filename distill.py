"""Habit distillation (phase 7.4): what the user typed to every agent -> .ai_bus/distill/profile.md.

Local only: calls Ollama on 127.0.0.1 directly (never CLIProxyAPI), so no chat text leaves this PC. No model training.
python distill.py [days]      run now (default 30 days)
python distill.py --install   register the nightly Task Scheduler job (03:30)
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import llm
import transcripts

ROOT = Path(__file__).resolve().parent
OUT = ROOT / ".ai_bus" / "distill"
MODEL = "deepseek-r1:8b"
NOISE = re.compile(r"^\s*(<|\[Request interrupted|Caveat:|This session is being continued)")
BATCH_CHARS = 6000

MAP_PROMPT = """下面是用户在过去一段时间里亲手发给各个 AI 助手（Claude Code / Codex / Antigravity）的消息，每行一条，格式「agent | 日期 | 内容」。
请只根据这些消息，用简体中文列出用户的使用习惯，分 5 类，每类 0-5 条要点，每条后面用「」附一句原话作证据：
1. 语言与回复风格偏好
2. 常用指令 / 口头禅（例如「报告进度」「plan」）
3. 纠正过 AI 的地方（用户说「不对」「不要」「别」之类）
4. 做事规则（文件放哪、先做什么、禁止什么）
5. 常见任务类型
没有证据的类别写「无」。不要编造，不要写建议。

消息：
{batch}"""

REDUCE_PROTO = """下面是几份从用户聊天记录中提炼的习惯笔记。请合并去重，写成一份 Markdown 用户画像，最多 60 行，结构固定：
## 语言与回复风格
## 常用指令
## 纠正过 AI 的地方
## 做事规则
## 常见任务类型
## 建议写进 CLAUDE.md / AGENTS.md 的规则（仅建议，需人工批准）
多份笔记都提到的放前面；每条保留一句「原话」证据；只写笔记里有的内容。

笔记：
{notes}"""


def collect(days):
    """User's own messages, de-duplicated, noise dropped, each cut to 400 chars."""
    seen, rows = set(), []
    for e in sorted(transcripts.user_messages(days), key=lambda e: e["time"]):
        text = " ".join(e["text"].split())[:400]
        if len(text) < 3 or NOISE.match(text) or text in seen:
            continue
        seen.add(text)
        rows.append(f"{e['agent']} | {time.strftime('%m-%d', time.localtime(e['time']))} | {text}")
    return rows


def batches(rows, size=BATCH_CHARS):
    batch = []
    for row in rows:
        if batch and sum(map(len, batch)) + len(row) > size:
            yield "\n".join(batch)
            batch = []
        batch.append(row)
    if batch:
        yield "\n".join(batch)


def ask(prompt, purpose):
    """One local Ollama call; shows on the capsule's deepseek slot and in the DeepSeek terminal pane."""
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False, "think": False,
            "options": {"num_ctx": 8192, "temperature": 0.2}}
    with llm.activity("deepseek", "deepseek-r1-local", purpose):
        req = Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=900) as r:
            text = json.loads(r.read().decode("utf-8"))["message"]["content"]
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        text = re.sub(r"^```(?:markdown)?\s*\n(.*?)\n```\s*$", r"\1", text, flags=re.S)  # model wraps the reply in a fence
        llm._log_call("deepseek-r1-local", body["messages"], text)
    return text


def run(days=30):
    rows = collect(days)
    if not rows:
        print("no user messages")
        return None
    parts = list(batches(rows))
    notes = [ask(MAP_PROMPT.format(batch=b), f"蒸馏 {i + 1}/{len(parts)}") for i, b in enumerate(parts)]
    profile = notes[0] if len(notes) == 1 else ask(REDUCE_PROTO.format(notes="\n\n---\n\n".join(notes)), "蒸馏 合并")
    OUT.mkdir(parents=True, exist_ok=True)
    head = (f"# 用户习惯画像（自动蒸馏）\n\n> {time.strftime('%Y-%m-%d %H:%M')} · 本地 {MODEL} · 最近 {days} 天 · "
            f"{len(rows)} 条用户消息 · 只读产物，改规则文件需人工批准\n\n")
    tmp = OUT / "profile.md.tmp"
    tmp.write_text(head + profile + "\n", encoding="utf-8")
    tmp.replace(OUT / "profile.md")
    (OUT / "notes.md").write_text("\n\n---\n\n".join(notes) + "\n", encoding="utf-8")
    print(f"{len(rows)} messages, {len(parts)} batches -> {OUT / 'profile.md'}")
    return OUT / "profile.md"


def install():
    """Nightly at 03:30 (the PC is usually idle); runs hidden via pythonw."""
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    cmd = f'"{pyw}" "{ROOT / "distill.py"}"'
    subprocess.run(["schtasks", "/create", "/tn", "JavisDistill", "/sc", "daily", "/st", "03:30", "/tr", cmd, "/f"],
                   check=True)


if __name__ == "__main__":
    if sys.stdout:  # None under pythonw (Task Scheduler)
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["--install"]:
        install()
    else:
        run(float(sys.argv[1]) if len(sys.argv) > 1 else 30)
