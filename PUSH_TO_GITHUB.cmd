@echo off
setlocal
cd /d "%~dp0"

where pwsh >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\github\push_to_github.ps1"
) else (
  PowerShell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\github\push_to_github.ps1"
)

set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" (
  echo GitHub publishing did not complete. Review the message above.
) else (
  echo GitHub publishing completed successfully.
)
pause
exit /b %EXIT_CODE%
