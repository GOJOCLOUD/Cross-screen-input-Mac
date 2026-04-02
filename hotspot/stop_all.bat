@echo off
chcp 65001 >nul
echo ==================================
echo 停止所有服务 (Windows)
echo ==================================

for %%p in (2345 8000 9000) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p" ^| findstr "LISTENING"') do (
    echo 停止端口 %%p 的进程 PID: %%a
    taskkill /F /PID %%a 2>nul
  )
)

echo ==================================
echo 已尝试停止占用 2345 / 8000 / 9000 的进程
echo ==================================
pause
