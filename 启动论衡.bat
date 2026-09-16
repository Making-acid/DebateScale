@echo off
setlocal EnableExtensions

set "CRE_PROJECT=%~dp0systems\deep-research"
set "CRE_STARTER=%CRE_PROJECT%\start_web.ps1"
set "CRE_URL=http://127.0.0.1:8765/"
set "CRE_VERSION=0.8.2"
set "CRE_LOG=%CRE_PROJECT%\web\.local\server.log"

if not exist "%CRE_STARTER%" (
    echo [CRE] Cannot find the launcher:
    echo %CRE_STARTER%
    echo.
    pause
    exit /b 1
)

rem Reuse only the current product version. An older preview is shut down first.
powershell.exe -NoProfile -WindowStyle Hidden -Command ^
  "try { $r = Invoke-RestMethod -TimeoutSec 2 '%CRE_URL%api/health'; if ($r.ok -and $r.version -eq '%CRE_VERSION%') { exit 0 }; try { $null = Invoke-RestMethod -Method Post -TimeoutSec 2 '%CRE_URL%api/shutdown' } catch {}; Start-Sleep -Milliseconds 3000; exit 1 } catch { exit 1 }"

if not errorlevel 1 (
    powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath '%CRE_URL%'"
    exit /b 0
)

rem Start the complete local service. The launcher, not the hidden server, opens the page.
set "CRE_NO_BROWSER=1"
start "" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%CRE_STARTER%"
set "CRE_NO_BROWSER="

echo [CRE] Starting the research service...
powershell.exe -NoProfile -Command ^
  "$deadline = (Get-Date).AddSeconds(35); do { try { $r = Invoke-RestMethod -TimeoutSec 2 '%CRE_URL%api/health'; if ($r.ok -and $r.version -eq '%CRE_VERSION%') { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $deadline); exit 1"

if errorlevel 1 (
    echo.
    echo [CRE] The service did not become ready. See the log:
    echo %CRE_LOG%
    echo.
    pause
    exit /b 1
)

powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath '%CRE_URL%'"
exit /b 0
