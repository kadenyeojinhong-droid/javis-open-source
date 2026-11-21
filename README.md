# Javis

A Windows desktop "air-traffic control" for several AI coding agents (Claude Code, Codex, Antigravity, DeepSeek).
A floating translucent capsule shows which agent is busy, which model it is using and what it is doing.
Agents talk over a file bus; risky actions wait for a human click.

> 中文：Javis 是一个 Windows 桌面上的多 AI 调度台。左侧半透明胶囊显示每个 AI 是否在忙、用哪个模型、在做什么；AI 之间通过文件总线传「纸飞机」消息，高危操作必须人工批准。使用说明见 [使用手册.md](使用手册.md)。

## Status (2026-11-19)

Personal project, early stage, Windows only. Tested on Windows 11, Python 3.13. 44 tests pass.

| Part | State |
|---|---|
| Capsule HUD (PySide6 + QML, GPU glass, ~25 MB RAM) | done |
| File bus, paper planes, loop breaker, approvals | done |
| Supervisor gate: pytest + blocklist + LLM review | done |
| Git worktree isolation per task | done |
| DeepSeek stand-in when an agent hits quota | done |
| 4th DeepSeek slot, unified transcripts, 2x2 terminal | done |
| Habit distillation (local Ollama only, data stays on the PC) | done |
| Typed contracts, web fetch tool, long-term memory, fine-tuning | planned |

See [TEAM_BOARD.md](TEAM_BOARD.md) for the task list and [PLAN.md](PLAN.md) for architecture decisions.

## Files

| File | Role |
|---|---|
| `hud_lite.py`, `ui/lite/Capsule.qml` | desktop capsule |
| `hud_server.py` | FastAPI server, one worker per agent, `/state`, `/ws` |
| `bus.py` | file message bus, breaker, approvals |
| `approve.py` | CLI: list / approve / reject pending actions |
| `harness.py` | `gate` (checks a diff) and `watch` (halts on anomalies) |
| `wt.py` | git worktree per task |
| `standin.py` | DeepSeek stand-in chain |
| `llm.py` | LLM client (CLIProxyAPI / OpenRouter / Gemini / Ollama) |
| `transcripts.py` | read all agents' chat logs in one format, secrets masked |
| `javis_tail.py`, `javis_term.ps1` | 2x2 Windows Terminal live view |
| `distill.py` | nightly habit summary with a local model |
| `mcp_bridge.py`, `sync_mcp.py`, `mcp_servers.json` | MCP tools and per-CLI config sync |

## Setup

```powershell
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python sync_mcp.py          # writes MCP config for each CLI
.venv\Scripts\python -m pytest -q
powershell -ExecutionPolicy Bypass -File launch_hud.ps1
```

Hotkeys: `Ctrl+Alt+A` show/hide capsule, `Ctrl+Alt+T` open the 2x2 terminal.

API keys come only from environment variables (`OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `CLIPROXY_API_KEY`). Never commit them.
Runtime data (`.ai_bus/logs`, `inbox`, `distill`, `llm_calls.jsonl`) is git-ignored because it holds your chats.

## License

MIT, see [LICENSE](LICENSE). Bundled Inter font: SIL OFL, see `ui/fonts/Inter-LICENSE.txt`.
