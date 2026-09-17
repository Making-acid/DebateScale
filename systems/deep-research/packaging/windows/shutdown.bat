@echo off
setlocal
powershell.exe -NoProfile -WindowStyle Hidden -Command ^
  "try { Invoke-RestMethod -Method Post -TimeoutSec 3 'http://127.0.0.1:8765/api/shutdown' | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo DebateScale is not running.
) else (
    echo DebateScale has stopped.
)
timeout /t 2 /nobreak >nul
