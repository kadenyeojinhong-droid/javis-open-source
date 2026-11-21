param([switch]$Uninstall)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$startup = [Environment]::GetFolderPath('Startup')
$link = Join-Path $startup 'Javis HUD.lnk'
if ($Uninstall) { Remove-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue; exit 0 }
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
$shortcut.Arguments = "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $root 'launch_hud.ps1')`" -Hidden"
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7
$shortcut.Description = 'Javis HUD (lite capsule)'
$shortcut.Save()
