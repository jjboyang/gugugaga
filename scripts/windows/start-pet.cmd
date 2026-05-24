@echo off
rem Thin wrapper around scripts\windows\start-pet.ps1 — double-click from Explorer or run from cmd.exe.
rem
rem Usage:
rem   scripts\windows\start-pet.cmd             - normal start
rem   scripts\windows\start-pet.cmd -Debug      - debug mode (red outline + logs)
rem   scripts\windows\start-pet.cmd -Reset      - rebuild venv from scratch
rem   scripts\windows\start-pet.cmd -Regen      - regenerate sprite PNGs

setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start-pet.ps1" %*
exit /b %ERRORLEVEL%
