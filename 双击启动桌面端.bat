@echo off
setlocal
title AstraCode Workbench Launcher
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_desktop.ps1"
if errorlevel 1 pause
endlocal
