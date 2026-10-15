@echo off
chcp 65001 >nul
title Clash Verge VIP 节点编排控制台
cd /d "%~dp0"

echo =======================================================
echo    Clash Verge VIP 节点编排可视化管理控制台
echo =======================================================
echo.

:: 1. 检查 8899 端口是否已在运行
netstat -ano | findstr "8899" >nul 2>&1
if %errorlevel% equ 0 (
    echo [✔] 本地服务已在后台运行中 (端口: 8899)。
) else (
    echo [1/2] 正在启动后台服务进程...
    start /b python server.py
    timeout /t 2 >nul
)

:: 2. 唤起系统浏览器
echo [2/2] 正在为您唤起浏览器控制台...
start http://127.0.0.1:8899

echo.
echo =======================================================
echo    🎉 控制台已就绪！网址：http://127.0.0.1:8899
echo    如需关闭后台服务，关闭本窗口或按 Ctrl+C 即可。
echo =======================================================
echo.
pause
