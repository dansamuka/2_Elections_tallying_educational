@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1 && (set PY=py -3) || (set PY=python)
%PY% -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat || exit /b 1
python -m pip install --upgrade pip || exit /b 1
pip install -e ".[dev,pdf]" || exit /b 1
python -m pytest || exit /b 1
python -m olkalou_engine.cli --root . publish --simulations 100 || exit /b 1
echo.
echo IMPLEMENTATION READY.
echo Dashboard: run-local.cmd
endlocal
