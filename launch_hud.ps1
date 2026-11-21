param([switch]$Hidden)
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:CLIPROXY_API_KEY = [Environment]::GetEnvironmentVariable('CLIPROXY_API_KEY', 'User')  # setx value, also for shells started before it existed
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
function Test-Hud { try { (Invoke-WebRequest 'http://127.0.0.1:8765/state' -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200 } catch { $false } }
if (-not (Test-Hud)) { $command = "Set-Location -LiteralPath '$root'; & '.venv\Scripts\python.exe' hud_server.py"; Start-Process conhost.exe -WindowStyle Hidden -ArgumentList "powershell -NoExit -ExecutionPolicy Bypass -Command `"$command`"" }
$ready = $false
for ($i = 0; $i -lt 60; $i++) { try { $r = Invoke-WebRequest 'http://127.0.0.1:8765/state' -UseBasicParsing -TimeoutSec 1; if ($r.StatusCode -eq 200) { $ready = $true; break } } catch {}; Start-Sleep -Milliseconds 500 }
if (-not $ready) { throw 'HUD server did not start' }
# hud_lite.py owns the QLocalServer single-instance lock, avoiding command-line
# matching races between concurrent launcher invocations.
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$hudArgs = @('hud_lite.py')  # lite capsule: four agents + animations
if ($Hidden) { $hudArgs += '--hidden' }
Start-Process $pythonw -ArgumentList $hudArgs -WorkingDirectory $root

