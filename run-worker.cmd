@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call implement.cmd || exit /b 1
.venv\Scripts\python.exe -m olkalou_engine.cli --root . worker
endlocal
