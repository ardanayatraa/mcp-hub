@echo off
rem Double-click to start the Hub API and the admin UI (see dev.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %*
if errorlevel 1 pause
