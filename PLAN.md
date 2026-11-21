# PLAN.md — Agent HUD & Traffic Bus（Tech Lead 裁定版 2026-11-15）

总规格见 MASTER_PLAN.md。本文件只记：盘点结果、架构裁定、任务单。

## 1. 盘点（与 MASTER_PLAN 的差异）
| 项 | 实际状态 |
|---|---|
| git | 已 `git init`（之前不是仓库，`git diff` 无法用） |
| `.mcp.json` | **不存在**；`~/.gemini/settings.json` 只有 api-key 认证，**未配任何 MCP** |
| 技能 `slow-human-typer` / `token-saver-traffic` / `skill-opt-router` | **四个 skills 目录里都没有**；`.agent/.gemini/.codex/skills` 为空 |
| 启动器 | `start_ai_lab.ps1` 只有 3 格（agy/claude/gemini），**缺 codex 格** |
| 规则文件 | 原 CLAUDE.md/GEMINI.md/.agent 规则是 TEAM_BOARD 的复制品，且把 Claude 写成 Builder → 已改为指向本文件的短指针；新增 AGENTS.md（Codex 读这个） |
| Python | 默认 `python` = msys 3.14，无 fastapi/rich/mcp。**统一用 `py -3.13` 建 `.venv`** |
| CLI | agy / codex(0.169, 已用 ChatGPT 登录) / gemini(0.68) / claude 均在 PATH |
| 无头调用（已核实） | `codex exec "<order>"`；`gemini -p "<order>"`；`agy -p "<order>" --output-format json --json-schema <schema>`（可直接强制 ORDER.json 结构） |
| MCP 配置 | **每个 CLI 读不同文件**：claude=`.mcp.json`，gemini=`.gemini/settings.json`(项目级)，codex=`~/.codex/config.toml` 的 `[mcp_servers.*]`（当前没配），agy=待查 |
| agy MCP 配置 | `~/.gemini/antigravity/mcp_config.json`，顶层 `{"mcpServers":{...}}`（用户提供）。agy 无头模式会拒绝所有 shell 命令，只派读写文件类任务 |

## 2. 架构裁定（所有 Agent 必须遵守）
1. **MCP 是被动的**：MCP server 不能"唤醒"CLI。纸飞机投递 = `hud_server.py` 里的调度器读队列，用无头模式拉起接收方：`codex exec "<order>"`、`gemini -p "<order>"`、agy 的无头命令（**T1 先确认 agy 是否支持非交互模式，不支持则 agy 只做人工格**）。
2. **队列 = 文件**：`.ai_bus/inbox/<agent>.jsonl`（追加写，处理后移到 `.ai_bus/done/`）。不引入 Redis/数据库。
3. **熔断器**：计数键 = 排序后的 `(A,B)` 对；每次自动转发 +1；人类在 HUD 发消息时清零；`>=10` 拒绝转发并广播 `breaker_open`。必须有单测。
4. **审批**：危险动作（git merge、删文件、改 `.mcp.json`/SKILL.md、唤醒 claude）→ `request_human_approval` 写 `.ai_bus/approvals/<id>.json` 并阻塞轮询，HUD 点允许/拒绝改文件状态；超时默认**拒绝**。
5. **Skill OPT 不得自动改四端 SKILL.md**：Gemini 只写 `LESSONS_LEARNED.md` + 生成补丁建议，落盘走审批卡。
6. 依赖上限：`fastapi uvicorn rich mcp`（requirements.txt）。前端单 HTML 零依赖。
7. 端口 `127.0.0.1:8765`，只绑本机。
8. **无头权限**：调度器禁止用 `--dangerously-skip-permissions` / codex 的 bypass 沙箱。codex 用 `--sandbox workspace-write`，agy 用 `--mode accept-edits`，工作目录锁定本目录；`--print-timeout` 设上限防卡死。
9. **单一 MCP 源**：只维护一份 `mcp_servers.json`，由 `launch_hud.ps1` 生成四端各自格式的配置，避免四处手改漂移。

## 3. 任务单（状态以 TEAM_BOARD.md 为准）
- **T1 agy**：`repo_mapper.py`（路径+函数签名 → REPO_MAP.txt，用 `ast`，忽略 .git/.venv/node_modules）；`nlp_compressor.py`（输入大白话 → `ORDER.json`，含 `goal/constraints/files/options[A,B,C]`，A 极速/B 稳健/C 零新依赖）；nlp_compressor 用 `agy -p --json-schema`；查清 agy 的 MCP 配置文件位置写回本文件。
- **T2 codex**：`mcp_bridge.py`（4 个工具，按裁定 2/4）；`hud_server.py`（FastAPI+WS、调度器、熔断器、rich 审计屏、写 `activity_audit.jsonl`）；`ui/floating_hud.html`（方案卡片/勾选/补充输入/审批卡/红灯/折叠球）；`launch_hud.ps1`（起后端 + `msedge --app` + SetWindowPos TOPMOST 靠右）；`mcp_servers.json` 插槽（memory、git、filesystem 限本目录、playwright、custom-tools 空位）+ 生成四端配置（裁定 9）；`start_ai_lab.ps1` 补 codex 格；`tests/test_breaker.py`。
- **T3 gemini**：起服务跑端到端模拟（投信→排队→执行→熔断→审批拒绝），验证 playwright MCP 能截 HUD；报错压到 ≤3 行写 `REVIEW.md`；首版 `LESSONS_LEARNED.md`。
- **T4 claude**：审 `git diff --stat` + 熔断/审批代码，向人类请求合并批准。
