@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Start
echo ========================================
echo.

:: Check if Python is available
where python >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python not found!
    echo.
    echo Please install Python 3.10+ from:
    echo   https://www.python.org/downloads/
    echo.
    echo Or use winget:
    echo   winget install Python.Python.3.13
    echo.
    pause
    exit /b 1
)

:: Show Python version
python --version
echo.

:: Check if venv exists
if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv venv
    if %errorLevel% neq 0 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo Virtual environment created.
    echo.
)

:: Activate venv
call "venv\Scripts\activate.bat"

:: Check if requirements are installed (check for websockets as indicator)
python -c "import websockets" >nul 2>&1
if %errorLevel% neq 0 (
    echo Installing dependencies...
    echo This may take a few minutes on first run.
    echo.
    
    :: Upgrade pip
    python -m pip install --upgrade pip --quiet
    
    :: Install requirements
    pip install -r requirements.txt
    if %errorLevel% neq 0 (
        echo.
        echo [WARNING] Some packages may have failed.
        echo Trying to install core packages only...
        pip install websockets pyscard pycryptodome Pillow numpy pywin32
    )
    echo.
    echo Dependencies installed!
    echo.
)

:: Check if EasyOCR is installed
python -c "import easyocr" >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo [INFO] EasyOCR not installed - OCR disabled
    echo To enable OCR text extraction, run:
    echo   pip install easyocr
    echo.
)

:: Run the server
echo ========================================
echo   Starting NFC Bridge Server
echo   Port: 3005
echo   Press Ctrl+C to stop
echo ========================================
echo.

python server.py

:: If server exits, pause to show any errors
echo.
echo Server stopped.
pause
