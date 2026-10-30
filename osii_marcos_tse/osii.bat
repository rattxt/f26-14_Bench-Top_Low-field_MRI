@echo off
REM Wrapper: osii make all^|tse^|bench   /   osii info^|plot^|compile^|run [file.seq]
REM          osii check [converted.seq]  /   osii view [data\file.npz]
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if not exist %PY% set PY=python
set CMD=%1
shift
set ARGS=
:loop
if "%~1"=="" goto go
set ARGS=%ARGS% %1
shift
goto loop
:go
if "%CMD%"=="make" (%PY% tools\make_seq.py %ARGS% & goto :eof)
if "%CMD%"=="check" (%PY% tools\check_equivalence.py %ARGS% & goto :eof)
if "%CMD%"=="view" (%PY% tools\view_rx.py %ARGS% & goto :eof)
for %%m in (info plot compile run) do if "%CMD%"=="%%m" (%PY% tools\run_seq.py %CMD% %ARGS% & goto :eof)
echo usage: osii make^|info^|plot^|compile^|run^|check^|view ...
