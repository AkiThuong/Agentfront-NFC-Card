@echo off
title NFC Bridge Server
cd /d "%~dp0"

echo ============================================
echo   NFC Bridge Server
echo ============================================
echo.

if exist "venv\Scripts\python.exe" (
    echo Starting server on ws://localhost:3005
    echo Press Ctrl+C to stop
    echo.
    venv\Scripts\python.exe server.py
) else (
    echo ERROR: Virtual environment not found!
    echo.
    echo Please run setup first:
    echo   powershell -ExecutionPolicy Bypass -File setup.ps1
    echo.
    pause
)
