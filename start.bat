@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\start_review_ops.ps1" -OpenBrowser
endlocal
