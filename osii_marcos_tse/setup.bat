@echo off
REM One-time host setup (Windows): creates .venv and installs requirements.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -m venv .venv || goto :err
.venv\Scripts\python -m pip install --upgrade pip
if exist wheels\*.whl (
  .venv\Scripts\python -m pip install --no-index --find-links wheels -r requirements.txt || goto :err
) else (
  .venv\Scripts\python -m pip install -r requirements.txt || goto :err
)
.venv\Scripts\python -c "import numpy, matplotlib, msgpack; print('OK: numpy', numpy.__version__)"
echo Setup complete. Use osii.bat ^<command^> (see README.md).
goto :eof
:err
echo Setup FAILED.
exit /b 1
