@echo off
setlocal
cd /d "%~dp0"
set "ELECTION_ID=banissa-2025"
set /p "TYPED_ID=Election ID [banissa-2025]: "
if not "%TYPED_ID%"=="" set "ELECTION_ID=%TYPED_ID%"

where pwsh >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\historical\run_ocr.ps1" -ElectionId "%ELECTION_ID%" -Engine auto
) else (
  PowerShell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\historical\run_ocr.ps1" -ElectionId "%ELECTION_ID%" -Engine auto
)

set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" (
  echo Historical OCR did not complete. Review the message above.
) else (
  echo Historical OCR and repository update completed.
)
pause
exit /b %EXIT_CODE%
