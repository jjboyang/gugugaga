@echo off
rem Thin wrapper around start-pet.ps1 so users can double-click from Explorer
rem or run from cmd.exe without worrying about PowerShell execution policy.
rem
rem Usage:
rem   scripts\start-pet.cmd             - normal start
rem   scripts\start-pet.cmd -Debug      - debug mode (red outline + logs)
rem   scripts\start-pet.cmd -Reset      - rebuild venv from scratch
rem   scripts\start-pet.cmd -Regen      - regenerate sprite PNGs

setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start-pet.ps1" %*
exit /b %ERRORLEVEL%
