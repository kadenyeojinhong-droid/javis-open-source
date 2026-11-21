# Javis terminal: 2x2 Windows Terminal, one live pane per agent (claude | agy / codex | deepseek). Read-only, 0 tokens.
# A second launch only brings the existing window to the front.
$root = $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'
$tail = Join-Path $root 'javis_tail.py'
$running = Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'javis_tail\.py' }
if ($running) { Start-Process wt.exe -ArgumentList @('-w', 'javis', 'focus-tab', '-t', '0'); exit }
$pane = { param($a) @('--title', "Javis-$a", '-d', $root, $py, $tail, $a) }
$wtArgs = @('-w', 'javis', 'new-tab') + (& $pane 'claude') +
  @(';', 'split-pane', '-V') + (& $pane 'agy') +
  @(';', 'move-focus', 'left', ';', 'split-pane', '-H') + (& $pane 'codex') +
  @(';', 'move-focus', 'right', ';', 'split-pane', '-H') + (& $pane 'deepseek')
Start-Process wt.exe -ArgumentList $wtArgs

