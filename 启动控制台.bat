@echo off
chcp 65001 >nul
title Clash Verge VIP 节点编排控制台
cd /d "%~dp0"

echo =======================================================
echo    Clash Verge VIP 节点编排可视化管理控制台
echo =======================================================
echo.

REM 1. 检查 Python 运行环境
where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 未在系统 PATH 中检测到 Python 环境！
    pause
    exit /b 1
)

REM 2. 真实 TCP 探针检测 8899 端口是否已在运行 (彻底摒弃脆弱的 netstat 管道)
python -c "import socket,sys;s=socket.socket();s.settimeout(0.3);sys.exit(0 if s.connect_ex(('127.0.0.1',8899))==0 else 1)" >nul 2>&1
if not errorlevel 1 (
    echo [状态] Clash Verge VIP 控制台已在运行 (端口 8899)
    echo [操作] 正在为您打开浏览器控制台...
    start "" "http://127.0.0.1:8899"
    timeout /t 1 >nul 2>&1
    exit /b 0
)

REM 3. 服务未运行，启动后台服务进程
echo [1/2] 正在启动后台服务进程 (python server.py)...
start "Clash-Verge-VIP-8899" /min python server.py

REM 4. 轮询等待 8899 端口就绪 (真实 TCP 握手确认)
echo [2/2] 正在等待端口 8899 就绪...
for /l %%i in (1, 1, 10) do (
    timeout /t 1 /nobreak >nul 2>&1
    python -c "import socket,sys;s=socket.socket();s.settimeout(0.3);sys.exit(0 if s.connect_ex(('127.0.0.1',8899))==0 else 1)" >nul 2>&1
    if not errorlevel 1 (
        echo [成功] 服务已就绪！正在为您唤起浏览器控制台...
        start "" "http://127.0.0.1:8899"
        timeout /t 1 >nul 2>&1
        exit /b 0
    )
)

echo.
echo =======================================================
echo [警告] 端口 8899 启动超时，请检查控制台或 Python 依赖！
echo =======================================================
echo.
pause
