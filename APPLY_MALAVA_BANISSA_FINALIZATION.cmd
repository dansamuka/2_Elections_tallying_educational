@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist .git (
  echo ERROR: Run this from the root of the cloned 2_Elections_tallying_educational repository.
  exit /b 1
)

where py >nul 2>&1 && (set PY=py -3) || (set PY=python)

%PY% -m compileall -q src scripts || exit /b 1
where node >nul 2>&1 && node --check frontend\archive.js || exit /b 1

%PY% -m pytest -q
if errorlevel 1 (
  echo ERROR: Tests failed. Nothing was pushed.
  exit /b 1
)

git add .github\workflows\sync-historical-forms.yml .github\workflows\restore-historical-snapshot.yml ^
  src\olkalou_engine\models.py src\olkalou_engine\portal.py src\olkalou_engine\archive.py ^
  src\olkalou_engine\historical_ocr.py src\olkalou_engine\historical_identity.py src\olkalou_engine\cli.py ^
  frontend\archive.js frontend\archive.html frontend\styles.css ^
  scripts\validate_archive_form_links.py tests\test_malava_bootstrap.py tests\test_portal.py ^
  RESTORE_LAST_GOOD_HISTORICAL_SYNC.cmd RESTORE_LAST_GOOD_HISTORICAL_SYNC.sh ^
  MALAVA_BANISSA_ARCHIVE_FINALIZATION_14JUL2026.md

git commit -m "Finalize Malava hierarchy and restore Banissa form links"
if errorlevel 1 echo No new code changes required a commit.

git push origin main || exit /b 1

where gh >nul 2>&1
if errorlevel 1 (
  echo.
  echo Code pushed. In GitHub Actions, run "Restore Banissa and Malava archive" once.
  exit /b 0
)

gh workflow run restore-historical-snapshot.yml --ref main -f snapshot_sha=b81eab0841661e5dc3deb86396b966181eac019a || exit /b 1
echo.
echo Restore workflow dispatched. Open GitHub Actions to watch it complete.
endlocal
