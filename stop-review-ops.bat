@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\stop_review_ops.ps1"
endlocal
