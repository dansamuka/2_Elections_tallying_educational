@echo off
setlocal
cd /d "%~dp0"
set /p API_BASE=Realtime API or Cloudflare Worker URL (https://...): 
set /p DATA_BASE=Optional R2/custom data URL (press Enter to skip): 
python scripts\configure_realtime_frontend.py --root . --api-base "%API_BASE%" --data-base "%DATA_BASE%"
if errorlevel 1 exit /b %errorlevel%
echo Updated frontend\config.js
