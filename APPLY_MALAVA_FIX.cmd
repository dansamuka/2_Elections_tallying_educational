@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".git" (
  echo ERROR: Extract this fix into the root of your existing Git clone first.
  echo The folder must contain the hidden .git directory.
  exit /b 1
)

where git >nul 2>nul || (
  echo ERROR: Git is not available on PATH.
  exit /b 1
)

echo Staging the Malava UI, OCR benchmark and CI fixes...
git add -- ^
  .github/workflows/ci.yml ^
  .github/workflows/sync-historical-forms.yml ^
  data/elections/sync.json ^
  frontend/archive.html ^
  frontend/archive.js ^
  frontend/styles.css ^
  tests/frontend/.npmrc ^
  tests/frontend/package.json ^
  tests/frontend/package-lock.json ^
  tests/frontend/test_malava_pending_roster.js ^
  tests/test_historical_sync.py ^
  MALAVA_UI_AND_CI_FIX_14JUL2026.md

for /f %%A in ('git diff --cached --name-only') do set HAS_CHANGES=1
if not defined HAS_CHANGES (
  echo No new changes to commit. The fix may already be applied.
  exit /b 0
)

git commit -m "Fix Malava benchmark grid and frontend CI" || exit /b 1
git push origin main || exit /b 1

echo.
echo Fix pushed. The updated sync workflow will start automatically because its workflow/config files changed.
echo Malava will first show 198 disabled placeholders, then replace them with named source-linked boxes after the portal bootstrap completes.
exit /b 0
