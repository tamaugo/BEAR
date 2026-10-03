@echo off
rem BEAR for Windows installer: double-click it. Safe to run again.
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "BEAR_PY="
rem Prefer the py launcher; plain "python" may be the Microsoft Store stub, so test it runs.
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "BEAR_PY=py -3"
if not defined BEAR_PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "BEAR_PY=python"
if not defined BEAR_PY (
  echo BEAR needs Python 3.10 or newer, and it is not installed.
  echo.
  echo Install it with:  winget install -e --id Python.Python.3.12
  echo or from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^),
  echo then double-click install.cmd again.
  if not defined CI pause
  exit /b 1
)
%BEAR_PY% "%~dp0bin\bear_windows.py" install
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo Install did not finish. Read the messages above.
)
if not defined CI pause
exit /b %RC%
