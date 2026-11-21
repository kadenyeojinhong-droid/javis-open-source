# Add Codex to the launcher as a split pane alongside the existing agents:
# Start-Process wt.exe -ArgumentList @('-w','0','new-tab','--title','codex','powershell','-NoExit','-Command',"Set-Location '$PSScriptRoot'; codex")
# For unattended HUD dispatch, use: codex exec -s workspace-write -C <repo> <order>
