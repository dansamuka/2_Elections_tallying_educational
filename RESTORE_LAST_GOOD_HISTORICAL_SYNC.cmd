@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set SNAPSHOT=b81eab0841661e5dc3deb86396b966181eac019a
if not "%~1"=="" set SNAPSHOT=%~1
where py >nul 2>&1 && (set PY=py -3) || (set PY=python)
git fetch origin main || exit /b 1
git checkout -B main origin/main || exit /b 1
git cat-file -e %SNAPSHOT%^^{commit} || exit /b 1
git checkout %SNAPSHOT% -- data/elections/banissa-2025 data/elections/malava-2025 data/public/elections/banissa-2025.json data/public/elections/malava-2025.json data/public/elections/banissa-2025 data/public/elections/malava-2025 || exit /b 1
%PY% -m olkalou_engine.cli --root . archive-remap malava-2025 || exit /b 1
%PY% -m olkalou_engine.cli --root . archive-ocr malava-2025 --engine embedded || exit /b 1
%PY% -m olkalou_engine.cli --root . archive-build malava-2025 || exit /b 1
%PY% -m olkalou_engine.cli --root . archive-build banissa-2025 || exit /b 1
git add data/elections/banissa-2025 data/elections/malava-2025 data/public/elections/banissa-2025.json data/public/elections/malava-2025.json data/public/elections/banissa-2025 data/public/elections/malava-2025 data/public/elections/catalog.json
git commit -m "Restore Banissa PDFs and finalize Malava hierarchy"
if errorlevel 1 echo No new restore changes to commit.
git push origin main || exit /b 1
echo Historical archive restored and pushed.
