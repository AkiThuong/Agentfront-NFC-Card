@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge - Install EasyOCR
echo ========================================
echo.
echo This will install EasyOCR + PyTorch (~2GB download)
echo.

:: Check if venv exists
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Please run start_server.bat first to set up.
    pause
    exit /b 1
)

:: Activate venv
call "venv\Scripts\activate.bat"

echo Installing PyTorch...
pip install --only-binary :all: torch torchvision --quiet
if %errorLevel% neq 0 (
    echo [WARNING] Binary install failed, trying regular install...
    pip install torch torchvision
)

echo.
echo Installing EasyOCR...
pip install easyocr
if %errorLevel% neq 0 (
    echo [ERROR] Failed to install EasyOCR
    pause
    exit /b 1
)

echo.
echo Downloading OCR language models (Japanese + English)...
echo This may take a few minutes...
python -c "import easyocr; print('Loading models...'); r = easyocr.Reader(['ja', 'en'], gpu=False, verbose=False); print('Models loaded successfully!')"

echo.
echo ========================================
echo   EasyOCR Installed Successfully!
echo ========================================
echo.
echo Restart the server to enable OCR:
echo   1. Stop the current server (Ctrl+C)
echo   2. Run start_server.bat again
echo.
pause
