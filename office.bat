@echo off
setlocal
title 10-Agent Virtual Office Dashboard

echo =======================================================
echo Starting 10-Agent Virtual Office Dashboard...
echo =======================================================

cd /d "%~dp0"
python dashboard\serve.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Failed to start the dashboard server.
    echo Please ensure Python is installed and accessible in your PATH.
    echo.
    pause
)
