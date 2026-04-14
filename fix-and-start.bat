@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\fix_and_start.ps1" -OpenBrowser
endlocal
