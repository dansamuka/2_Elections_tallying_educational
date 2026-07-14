@echo off
setlocal
cd /d "%~dp0"
if not exist .env (
  echo ERROR: .env is missing. Copy .env.example to .env and set REALTIME_API_TOKEN.
  exit /b 1
)
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m olkalou_engine.cli --root . realtime-api --host 0.0.0.0 --port 8090
