# TEAM_BOARD.md — task board / progress

Rule: read PLAN.md §2 before work. Touch only your task's files. When done, change `[ ]` to `[x]` and append one Handoff line: `date | who | what | files`.

## Tasks
- [x] Phase 1: file bus (`bus.py`), paper-plane queue, breaker, approvals (`approve.py`)
- [x] Phase 1: desktop capsule HUD (`hud_lite.py` + `ui/lite/Capsule.qml`), hotkeys, autostart
- [x] Phase 2: DeepSeek supervisor gate (`harness.py gate/watch`)
- [x] J1: worktree isolation (`wt.py`), unified state (`state.py`), LLM client (`llm.py`)
- [x] Stand-in: DeepSeek takes a slot when an agent hits quota (`standin.py`)
- [x] 7.1 DeepSeek as 4th resident slot
- [x] 7.2 unified transcripts across agents (`transcripts.py`)
- [x] 7.3 2x2 Windows Terminal view (`javis_tail.py`, `javis_term.ps1`)
- [x] 7.4 local-only habit distillation (`distill.py`)
- [ ] 3: pydantic contracts for Order / PaperPlane / Approval
- [ ] 4: limited `fetch_page(url)` MCP tool (public docs only, robots.txt, rate limit)
- [ ] 6: `.ai_bus/knowledge.jsonl` long-term memory
- [ ] 7.5: QLoRA fine-tune (decide after 7.4 has run one month)
- [ ] Wire distill "suggested rules" into `approve.py`

## Handoff
- 2026-11-19 | claude | public export of Javis (fresh history) | all
