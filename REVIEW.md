# T3 QA Review

- PASS — Python syntax: all repository `.py` files outside `.venv` and `.git` compile with `.venv/Scripts/python -m py_compile` equivalent.
- PASS — Test suite: `.venv/Scripts/python -m pytest -q tests` (10 passed; sandbox-local basetemp/cache options used).
- PASS — HUD GET `/` returns HTML through FastAPI TestClient.
- PASS — POST `/reset_breaker` returns reset status.
- PASS — 11 sends for one pair: the first 10 are sent and the 11th returns `breaker_open`.
- PASS — POST `/approve/{id}` changes a pending approval to `denied`.
- PASS — UI includes plan cards, module checkboxes, extra input, launch button, approval card, breaker red indicator, and foldable ball.
- PASS — `hud_server.py` and `launch_hud.ps1` contain no dangerous/bypass/yolo flags; backend binds to `127.0.0.1` and launcher polls that address.
- PASS — `sync_mcp.apply` preserves existing `.bak` files; regression test covers a second apply.

# UI8 selftest rerun (2026-11-15)

```text
PASS page loaded
GPU renderer: ANGLE (Intel, Intel(R) UHD Graphics (0x0000A7A8) Direct3D11 vs_5_0 ps_5_0, D3D11)
GPU renderer: available
PASS four avatar clicks open matching cards
PASS settings card opens
FAIL English settings title
Selftest API detail: <connection refused: hud_server was not listening on 127.0.0.1:8765>
FAIL selftest API available after language switch
```

The requested complete PASS run could not be recorded in this environment: the launched `hud_server.py` did not remain reachable on port 8765. This run is recorded as observed; no CPU readings are available because the service-dependent checks could not proceed.

## QML migration implementation status (Codex, 2026-11-15)

- Added `hud_qml.py`, native Qt Quick component files under `ui/qml/`, `launch_hud.ps1` QML startup selection, and `install_autostart.ps1` install/uninstall support. Backend HTTP and WebSocket routes were not changed.
- Verification: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q --basetemp=.tmp/pytest-qml -p no:cacheprovider` → 26 passed. QML component syntax/load checks, no infinite animation token, zh/en key parity, and autostart uninstall flag are included.
- A server-backed `--selftest` startup smoke run exited 0. It currently only loads and exits; full interaction automation, `--shots`, and the requested 5-second hidden/visible memory and CPU sampling have not been implemented. Thus this run does not establish the stated performance targets or full feature parity.
- Manual visual/runtime review is still required. Existing screenshots and full end-to-end UI assertions were not produced in this pass.



## QML2 migration and selftest (Codex, 2026-11-15)

- Added reusable SVG path icons, per-DPR source-size limits, registry-backed `AppsUseLightTheme` polling, and custom styled QML surfaces. `ui/qml/` contains no QtQuick.Controls imports or default Button/Switch/TextField/SpinBox/ComboBox controls.
- `hud_qml.py --selftest` exercises card/language/avatar toggles, captures all five requested states in light and dark, posts two `WM_HOTKEY` messages, and samples process working set/CPU through Win32 APIs. The ten requested PNGs are in `.ai_bus/shots/qml/`.
- Memory reduction attempts, in order: D3D11 RHI, no QtQuick.Controls load, card Loader active only while open, SVG sourceSize limits, and `gc.collect()` while hidden. Working set remained about 216-220 MB, above the 100 MB target; this points to the resident PySide6 Qt Quick/graphics runtime and driver allocation floor. Idle CPU stayed below 1%.
- Pytest ran after `ui/floating_hud.html` changed in the shared workspace (an untracked `ui/floating_hud.html.bak` is also present). Final result: 24 passed, 2 failed in `tests/test_hud_v2.py`, whose old assertions require the former `html,body {` spelling and no CJK strings. Those assertions conflict with the current HTML (`html, body {` and localized title text); the reference HTML and tests were left untouched. The earlier run before that concurrent HTML change was 26 passed.


Complete final `hud_qml.py --selftest --shots .ai_bus/shots/qml` output:

```text
PASS server state loaded: agents=4
PASS four enabled avatars
PASS avatar card claude
PASS card rendered claude
PASS card rendered agy
PASS card rendered codex
PASS card rendered gemini
PASS settings card opens
PASS screenshot .ai_bus/shots/qml/light/card_settings_zh.png
PASS screenshot .ai_bus/shots/qml/dark/card_settings_zh.png
PASS English settings title
PASS screenshot .ai_bus/shots/qml/light/card_settings_en.png
PASS screenshot .ai_bus/shots/qml/dark/card_settings_en.png
PASS disable Gemini
PASS restore Gemini
PASS screenshot .ai_bus/shots/qml/light/dock_left.png
PASS screenshot .ai_bus/shots/qml/dark/dock_left.png
PASS screenshot .ai_bus/shots/qml/light/card_agy.png
PASS screenshot .ai_bus/shots/qml/dark/card_agy.png
PASS screenshot .ai_bus/shots/qml/light/island_top.png
PASS screenshot .ai_bus/shots/qml/dark/island_top.png
PASS hotkey hide queued
PASS hotkey hid window
METRIC hidden 5s working_set=217.41MB CPU=0.34%
PASS hotkey show queued
METRIC shown_idle 5s working_set=216.24MB CPU=0.16%
PASS hotkey showed window
PASS dock left layout: side=left size=400x600
PASS dock right layout: side=right size=400x600
PASS top island layout: side=top size=720x420
PASS bottom island layout
PASS snap left attachment: side=left x=8 expected=8
PASS snap right attachment: side=right x=1128 width=720 right=1535
PASS snap top centered and in screen
PASS Escape closes card
PASS snap remains on screen
FAIL working set <=100MB: hidden=217.41MB shown=216.24MB
PASS idle CPU <1%: hidden=0.34% shown=0.16%
SELFTEST SUMMARY: 35 PASS, 1 FAIL
```

## QML round 3 visual and memory acceptance (Codex, 2026-11-15)

- Fixed the dock geometry: four 36px agent circles are laid out with 14px gaps, then a divider and workbench, terminal, and settings actions. The vertical capsule now follows its contents at 370 logical px; the top island is a centered horizontal 460×70 logical px capsule inside a 720×100 logical px window.
- Replaced the two settings sliders with right-aligned numeric fields. Enabled switches now place the knob on the right over `#34C759`; the knob uses a 200ms spring animation. Settings and agent cards use 14px corners, 16px padding, 1px separators, 15px bold headings, and 11px descriptions. Agent icons are drawn with Qt Quick Shape paths. The card Loader activates only while a card is open.
- Restored `ui/floating_hud.html` from the existing `ui/floating_hud.html.bak` rollback copy; no test assertions were changed.
- Memory measurements (Windows working set, MiB; observed values vary with page residency):
  - Empty transparent `QQuickWindow`, D3D11: 54.44 before trim, 1.77 immediately after `SetProcessWorkingSetSize(-1,-1)`.
  - Empty transparent `QQuickWindow`, software: 54.58 before trim, 1.76 immediately after trim.
  - Full HUD, D3D11, Shape icons + lazy Loader + `gc.collect()` + startup working-set trim: hidden 37.49, shown idle 45.67.
  - Full HUD, software with the same implementation: hidden 26.41, shown idle 37.23.
  - The empty-window baseline and both full-HUD modes are below 100 MiB after normal residency; no framework floor above the target was observed. Startup trim readings are transient and are not used as the full-HUD steady-state figures.
- `hud_qml.py --selftest --shots .ai_bus/shots/qml` (D3D11): 38 passed, 0 failed; `montage_round3.png` is 1120×840 with the round 2 dark top row / light bottom row arrangement. English AGY screenshots are also saved as `card_agy_en.png`.
- Software selftest: 26 passed, 0 failed. Working set: hidden 26.41 MiB, shown idle 37.23 MiB. CPU stayed below 1% in both runs.
- Final pytest run: 26 passed.

## HUD QML 第 4 轮（2026-11-15）

- 本轮完成：设置卡片只保留语言、智能体互发、连续来回步进、不用时自动隐藏；既有 `allow_hud`、`idle_seconds` 与智能体配置仍由后端保留。加载 `ui/fonts/Inter-*.ttf`，字体族回退 Microsoft YaHei UI。Agent glyph 改为样稿 SVG path，busy 弧线按 1.1s 周期绘制且仅 busy 时启用；拖动改为 QQuickWindow 原生 x/y 指针增量移动，阈值 5px，松开/取消吸附。选择自行移动而非 `startSystemMove`，因为 Qt 系统移动交接后无法保证指针增量同步及 QML cancel 路径。
- 真毛玻璃技术验证：Windows `SetWindowCompositionAttribute` 返回成功，`ACCENT_ENABLE_ACRYLICBLURBEHIND=4` 使用 `0xD9FFFFFF`；`SetWindowRgn(CreateRoundRectRgn)` 返回成功，圆角 region 应用于胶囊顶层窗口。运行日志为 `GLASS acrylic=True rounded_region=True`。当前仅实际接到胶囊窗口；卡片和通知还没有独立顶层玻璃窗口，未制作条纹桌面 `glass_probe.png`，所以尚未以截图验收真实桌面模糊。方案 b 尚未执行。
- 验证：`py_compile hud_qml.py` 成功，`pytest` 为 26 passed；`hud_qml.py --selftest --shots .ai_bus/shots/qml4` 为 38 PASS / 0 FAIL。工作集 hidden 37.36 MiB、shown idle 45.83 MiB；CPU 分别 0.27% 与 0.08%。忙碌态 CPU 未采样。输出 montage_qml4.png。
- 未完成：独立穿透动画覆盖窗口及纸飞机/信封/WS 通知卡；Antigravity 输入后整理再呈现 A/B/C 与发射；中心保持、甩动速度弹簧、失焦/捕获丢失处理；上限药丸、busy on/off/悬停、拖动 cancel 与 plane_mid 等新增专用 selftest/shots；真毛玻璃仅验证胶囊，需补充 glass_probe 截图。现有 selftest 通过的是旧覆盖范围，不代表以上新增交互验收通过。

## QML 第 5 轮（2026-11-15）

- 已改：胶囊顶层窗从 400×600 / 720×100 改成胶囊内容尺寸（竖向 64×370、横向约 460×70）；无保存位置时左侧 x=12 且垂直居中。Win32 region 使用窗口短边作为圆角直径；acrylic tint 改为白色约 26% alpha；卡片已迁移为独立 `CardWindow.qml` 顶层玻璃窗，定位按 dock 四边选择，并以 12px 间距约束到屏幕。
- Agent glyph 调整为白色 1.8 线宽，右下角保留状态点。
- 验证：`py_compile hud_qml.py` 成功；pytest 26 passed。QML 运行日志报告 `acrylic=True rounded_region=True`。
- 本轮 selftest **未通过**：运行环境没有 `127.0.0.1:8765` 服务（ConnectionRefused），状态/语言相关用例失败；旧 selftest 还包含旧窗体尺寸断言。其截图路径仍使用 `root.grabWindow()`，没有建立高对比全屏背景、屏幕抓取、方差与圆角外像素断言，也没有生成规定的八张验收图和 montage。忙碌光圈 CPU 也未采样。因此实拍验收尚未完成，当前改动不能视为第 5 轮通过。
- 步骤 C（纸飞机/信封/通知覆盖动画）未实施。

## QML round 6 fixes and validation

- 首启位置：位置仍使用 Qt 逻辑坐标；无存储位置时 `Main.qml` 将 x 置为屏幕左侧 12px，y 按当前胶囊高度居中。实拍坐标应以 QScreen 逻辑几何验证，不将 DPR 再乘入窗口 x/y。
- 圆角区域：`apply_acrylic` 将窗口逻辑宽高乘 `devicePixelRatio()` 后传给 Win32，region 边界为 `w+1/h+1`，圆角直径取短边，半径为短边一半。窗口只在创建、宽高改变时更新 region。
- 亚克力：tint 调为 `0x36FFFFFF`（约 21%），dock 内描边约 45% 白色；动作文字增加深色描边阴影，Agent path 增加阴影层，以兼顾深浅桌面。
- 按钮裁切：竖向窗口高度从 370 调到 410 逻辑 px，容纳 Agent 列、分隔线和工作台/终端/设置操作。
- 重设日志：移除 500ms acrylic 定时器，使用窗口首次显示与宽高信号触发；同一 hwnd/尺寸/DPR 只设置一次。
- 服务与真实截屏：selftest 需要 API 服务可用；截屏改为 `QScreen.grabWindow(0)`，selftest 会显示彩色竖条纹底窗，并对圆角左上/右上外侧像素作颜色断言，另输出八张验收状态图及 `montage_qml6.png`。
- 验证记录：待本轮服务启动、selftest 与 pytest 执行完成后填写实际结果。

## QML round 7 snapshot glass

- Replaced Win32 acrylic and window regions with per-pixel transparent QML surfaces. `QScreen.grabWindow(0, x, y, w, h)` refreshes dock/card snapshots at 1.5s while visible and after movement/card opening; refresh timers stop while hidden and skip during dragging. Windows capture exclusion uses `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`.
- `GlassSurface.qml` applies `MultiEffect` blur (1.0/48), saturation 0.35, brightness 0.04, a rounded mask, white tint, top sheen, and 1px outline. The selftest stripe window is topmost and raised before the HUD; screenshots composite the capture-excluded HUD over the desktop frame.
- Validation: `py_compile hud_qml.py` passed; `.venv/Scripts/python.exe -m pytest -q --basetemp=.tmp/pytest-qml7 -p no:cacheprovider tests` passed (27 tests). Real desktop selftest remains for Tech Lead; capture behavior and CPU must be confirmed on that desktop because sandbox screen capture is black.
- 修复 1：无保存位置时 Python 用 `QScreen.availableGeometry()` 设置 x=left+12 逻辑 px，y 按窗口高度居中；实拍位置以逻辑坐标判断，不混乘 DPR。
- 修复 2：Win32 region 把 Qt 逻辑宽高乘 `devicePixelRatio()`，边界 w+1/h+1，半径短边一半，圆角直径 2r。QQuickWindow 尺寸动画已移除，避免动画逐帧触发 region 重设。
- 修复 3：acrylic alpha 为 0x36（约 21%）；dock 内描边 #73ffffff（约 45%）；操作文字用深色描边阴影，Agent path 加 MultiEffect 阴影。
- 修复 4：竖胶囊高度改为 410 逻辑 px；selftest 断言四个 agent、分隔线和三个操作所需区域，横向仍为 460×70。
- 修复 5：删除 500ms 重设定时器，窗口创建、宽高变化时设置 acrylic/region；相同 HWND/尺寸/DPR 仅设置一次。
- 修复 6：本次确实后台启动 hud_server.py 并等待 8765；结束时关闭服务及端口监听子进程。QML selftest CPU/内存及布局项通过。
- 修复 7：selftest 用 QScreen.grabWindow(0)，准备全屏彩色条纹窗口，并比较胶囊圆角外采样像素；生成规定名称及 montage。当前运行环境的屏幕抓取返回全黑 1920×1080 图，角像素为 #000000，且条纹底窗不可见，因此正确报告截图断言失败（26 PASS / 11 FAIL），这些空白 PNG 不构成真实桌面验收证据，需要在可见的交互桌面会话重跑。
- 验证：`py_compile` 成功；pytest 27 passed。实测 DPR=1.25，dock 物理 region 80×512；日志仅初始化 1 条 dock glass（卡片每次显示各初始化一次）。

## QML round 8 snapshot fallback and selftest repair

- Glass snapshot source remains enabled while loading; the blur effect appears only after an image is ready. Tint, outline, sheen, and the foreground dock contents therefore remain visible before capture succeeds.
- Fixed selftest screenshot compositing to draw `QQuickWindow.grabWindow()`'s returned `QImage` directly. Added a 240-second selftest timeout that records failure and exits with status 1. Each stage remains guarded so exceptions are reported and subsequent timer steps continue.
- Added `--diag`: after 3 seconds it prints each Qt window's name, visibility, logical and DPR-scaled geometry, opacity, and matching snapshot status/size, then exits. Diagnostic mode disables auto-hide.
- Verification: `.venv/Scripts/python.exe -m pytest -q --basetemp=.pytest_tmp/qml8-final -p no:cacheprovider tests` passed (28 tests); `py_compile hud_qml.py` passed.

## QML round 9 glass capture corrections

- Qt 6 `QScreen.grabWindow()` sub-area arguments are device-independent pixels; returned pixmaps can be larger on high-DPI displays. Snapshot capture now passes logical window bounds once, relative to the screen origin. The image source size matches the logical surface, uses exact stretch bounds, and MultiEffect padding is enabled with 64px maximum blur.
- Selftest sets `HUD_CAPTURE_VISIBLE=1`, saves full-screen comparison frames, and saves direct `QQuickWindow.grabWindow()` captures for dock and card alongside the composited review image. Qt reference: https://doc.qt.io/qt-6/qscreen.html.
- Selftest now captures a clean screen baseline with HUD windows temporarily hidden, restores them, saves raw dock/card `QQuickWindow.grabWindow()` images, and asserts mean per-channel snapshot color error <25 plus glass-to-desktop mean gradient ratio <0.35.
- Verification: `.venv/Scripts/python.exe -m py_compile hud_qml.py` passed; `.venv/Scripts/python.exe -m pytest -q --basetemp=.pytest_tmp/qml9-final -p no:cacheprovider tests` passed (28 tests). A real desktop `--selftest` run was not available in this environment, so its pixel thresholds remain unmeasured here.
