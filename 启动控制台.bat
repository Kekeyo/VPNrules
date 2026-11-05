@echo off
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH
    pause
    exit /b 1
)
python -c "import yaml" >nul 2>&1
if errorlevel 1 (
    echo Installing PyYAML...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Could not install PyYAML. Run: pip install PyYAML
        pause
        exit /b 1
    )
)
powershell -NoProfile -Command "if (Test-NetConnection -ComputerName 127.0.0.1 -Port 8899 -InformationLevel Quiet -WarningAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 goto open
powershell -NoProfile -Command "Start-Process -FilePath (Get-Command python).Source -ArgumentList 'server.py' -WorkingDirectory '%~dp0' -WindowStyle Hidden"
set "OK="
for /l %%i in (1,1,20) do (
    if not defined OK (
        powershell -NoProfile -Command "if (Test-NetConnection -ComputerName 127.0.0.1 -Port 8899 -InformationLevel Quiet -WarningAction SilentlyContinue) { exit 0 } else { exit 1 }"
        if not errorlevel 1 set "OK=1"
        if not defined OK ping 127.0.0.1 -n 2 >nul
    )
)
if not defined OK (
    echo [ERROR] Port 8899 did not start within 20s. See server.log
    pause
    exit /b 1
)
:open
start "" "http://127.0.0.1:8899"
echo Running in background: http://127.0.0.1:8899
timeout /t 2 >nul
exit /b 0
