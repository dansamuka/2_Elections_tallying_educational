@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where py >nul 2>&1 && (set PY=py -3) || (set PY=python)
if not exist .venv\Scripts\python.exe (
  %PY% -m venv .venv || exit /b 1
)
call .venv\Scripts\activate.bat || exit /b 1
python -m pip install --upgrade pip || exit /b 1
python -m pip install -e ".[dev,historical-ocr,pdf]" || exit /b 1
python -m ruff check src tests scripts || exit /b 1
python -m pytest || exit /b 1
node --check frontend\app.js || exit /b 1
node --check frontend\archive.js || exit /b 1
pushd tests\frontend
call npm ci --ignore-scripts --no-audit --no-fund || exit /b 1
call npm test || exit /b 1
popd

echo.
echo REALTIME UPGRADE VALIDATED.
echo 1. Copy .env.example to .env and set REALTIME_API_TOKEN.
echo 2. Start with START_REALTIME_SYNC.cmd or docker compose up -d realtime dashboard.
echo 3. Configure the deployed HTTPS URL with CONFIGURE_REALTIME_FRONTEND.cmd.
echo 4. Push with PUSH_TO_GITHUB.cmd after reviewing frontend\config.js.
endlocal
