@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Install Dependencies
echo ========================================
echo.

:: Check if Python is available
where python >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python not found!
    echo.
    echo Installing Python 3.13 via winget...
    winget install Python.Python.3.13 --accept-source-agreements --accept-package-agreements
    if %errorLevel% neq 0 (
        echo.
        echo [ERROR] Auto-install failed. Please install manually:
        echo   https://www.python.org/downloads/
        echo.
        pause
        exit /b 1
    )
    echo.
    echo Python installed! Please restart this script.
    pause
    exit /b 0
)

python --version
echo.

:: Create venv if not exists
if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate venv
call "venv\Scripts\activate.bat"

:: Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip --quiet

:: Install core requirements
echo.
echo Installing core dependencies...
pip install websockets pyscard pycryptodome Pillow numpy pywin32

:: Ask about OCR
echo.
echo ========================================
echo   Optional: Install EasyOCR
echo ========================================
echo.
echo EasyOCR enables text extraction from card images.
echo It requires ~2GB download (PyTorch + models).
echo.
set /p INSTALL_OCR="Install EasyOCR? (y/n): "

if /i "%INSTALL_OCR%"=="y" (
    echo.
    echo Installing EasyOCR + PyTorch...
    echo This will take several minutes...
    pip install easyocr
    
    echo.
    echo Downloading OCR models...
    python -c "import easyocr; easyocr.Reader(['ja', 'en'], gpu=False)"
    
    echo.
    echo EasyOCR installed!
) else (
    echo.
    echo Skipping EasyOCR. You can install later with:
    echo   pip install easyocr
)

echo.
echo ========================================
echo   Installation Complete!
echo ========================================
echo.
echo To start the server, run:
echo   start_server.bat
echo.
pause
