@echo off
rem bear - BEAR 0.2 launcher for Windows. Works in cmd and PowerShell. See bin\bear_windows.py.
setlocal
set "PYTHONUTF8=1"
if exist "%~dp0..\.venv\Scripts\python.exe" (
  "%~dp0..\.venv\Scripts\python.exe" "%~dp0bear_windows.py" %*
  exit /b
)
set "BEAR_PY="
rem Prefer the py launcher; plain "python" may be the Microsoft Store stub, so test it runs.
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "BEAR_PY=py -3"
if not defined BEAR_PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "BEAR_PY=python"
if not defined BEAR_PY (
  echo BEAR needs Python 3.10 or newer.
  echo Install it with:  winget install -e --id Python.Python.3.12
  echo or from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then open a new window.
  exit /b 1
)
%BEAR_PY% "%~dp0bear_windows.py" %*
