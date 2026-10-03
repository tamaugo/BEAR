@echo off
rem What the BEAR desktop shortcut runs: the BEAR page in your browser, this window shows progress.
title BEAR
cd /d "%~dp0.."
call "%~dp0bear.cmd" ui
if errorlevel 1 (
  echo.
  echo BEAR stopped with a problem. Read the messages above.
  pause
)
