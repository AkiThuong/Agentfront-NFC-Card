@echo off
echo ========================================
echo   NFC Bridge Server - Development Mode
echo ========================================
echo.

:: Check if venv exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else if exist "venv313\Scripts\activate.bat" (
    call venv313\Scripts\activate.bat
) else (
    echo Virtual environment not found!
    echo Run 'python -m venv venv' first
    pause
    exit /b 1
)

:: Start server and open status page
echo Starting server on ws://localhost:3005...
echo Opening status page in browser...
echo.
echo Press Ctrl+C to stop the server.
echo.

:: Open status page in background
start "" "status.html"

:: Run server
python server.py

