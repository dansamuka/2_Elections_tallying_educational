@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call implement.cmd || exit /b 1
start "Ol Kalou Dashboard" cmd /k ".venv\Scripts\python.exe -m olkalou_engine.cli --root . serve-static --host 127.0.0.1 --port 8000"
start "Ol Kalou Review" cmd /k ".venv\Scripts\python.exe -m olkalou_engine.cli --root . review --host 127.0.0.1 --port 8080"
timeout /t 2 >nul
start http://127.0.0.1:8000/frontend/
start http://127.0.0.1:8080/
endlocal
