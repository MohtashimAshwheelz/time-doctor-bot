@echo off
REM HR Audit Bot launcher
REM Double-click this file to start the bot in HR mode.

REM Change directory to where this .bat file lives
cd /d "%~dp0"

REM Launch with --hr flag so only HR modules show up
python main.py --hr

REM If python isn't installed, this will fail. Pause so user sees error.
if errorlevel 1 (
    echo.
    echo Failed to launch. Press any key to close.
    pause >nul
)
