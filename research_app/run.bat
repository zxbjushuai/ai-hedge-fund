@echo off
setlocal
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-services.ps1" -LogDirectory "%~dp0..\logs\research-app"
exit /b %errorlevel%
