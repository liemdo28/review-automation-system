@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\fix_and_start.ps1" -OpenBrowser
if errorlevel 1 (
  echo.
  echo Fix-and-start failed. Opening log...
  start notepad "%~dp0.run\fix.err.log"
  pause
) else (
  echo.
  echo START launched. This window can be closed.
)
endlocal
