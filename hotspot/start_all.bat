@echo off
chcp 65001 >nul
echo ==================================
echo 启动所有服务 (Windows)
echo ==================================

:: 清理端口 2345 8000 9000
echo 清理端口...
for %%p in (2345 8000 9000) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
  )
)
echo 端口清理完成

:: 启动局域网中转站（后台）
echo 启动局域网中转站...
start /b "" python "%~dp0..\lan\relay_server.py" > "%~dp0logs\relay.log" 2>&1
timeout /t 1 /nobreak >nul

:: 启动主服务（后台）
echo 启动主服务...
cd /d "%~dp0backend"
start /b "" python main.py > "..\logs\main.log" 2>&1
timeout /t 2 /nobreak >nul

echo ==================================
echo 服务启动状态检查
echo ==================================
netstat -ano | findstr "2345 8000 9000" | findstr "LISTENING"
echo.
echo 若上面看到 2345 / 8000 / 9000，则服务已启动。
echo 电脑端: http://localhost:2345
echo 手机端: http://本机IP:2345/phone
echo ==================================
pause
