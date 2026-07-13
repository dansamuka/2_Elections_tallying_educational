@echo off
setlocal
cd /d "%~dp0"

echo Kenya Election Tallying Wall - Ol Kalou IEBC update
echo Repository: dansamuka/2_Elections_tallying_educational
echo Target: ol-kalou-2026
echo.

where gh >nul 2>nul
if errorlevel 1 (
  echo GitHub CLI is required. Run PUSH_TO_GITHUB.cmd once to install and authenticate it.
  pause
  exit /b 1
)

gh auth status >nul 2>nul
if errorlevel 1 (
  gh auth login --hostname github.com --git-protocol https --web
  if errorlevel 1 exit /b 1
)

echo Starting the secure Ol Kalou portal and OCR update...
gh workflow run sync-historical-forms.yml --repo dansamuka/2_Elections_tallying_educational --ref main -f election_id=ol-kalou-2026 -f engine=auto -f rebuild=false
if errorlevel 1 (
  echo The workflow could not be started.
  pause
  exit /b 1
)

echo Ol Kalou update requested successfully.
start "" "https://github.com/dansamuka/2_Elections_tallying_educational/actions/workflows/sync-historical-forms.yml"
pause
