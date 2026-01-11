@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge - Install OCR Engine
echo ========================================
echo.
echo Choose OCR engine:
echo   1. PaddleOCR (Recommended - Best for Japanese text)
echo   2. EasyOCR (Fallback - Requires PyTorch ~2GB)
echo.
set /p choice="Enter choice (1 or 2): "

:: Check if venv exists
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Please run start_server.bat first to set up.
    pause
    exit /b 1
)

:: Activate venv
call "venv\Scripts\activate.bat"

:: Upgrade pip first
python -m pip install --upgrade pip setuptools wheel --quiet

if "%choice%"=="2" goto :install_easyocr

:install_paddleocr
echo.
echo ========================================
echo   Installing PaddleOCR (Latest Version)
echo ========================================
echo.

:: Install shapely first (required dependency)
echo [1/5] Installing shapely...
pip install --only-binary :all: shapely --quiet 2>nul
if %errorLevel% neq 0 (
    pip install shapely --quiet
)
echo       OK

:: Install PaddlePaddle
echo [2/5] Installing PaddlePaddle...
pip install paddlepaddle==3.0.0b2 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/ --quiet 2>nul
if %errorLevel% neq 0 (
    echo Trying alternative installation...
    pip install paddlepaddle --quiet 2>nul
    if %errorLevel% neq 0 (
        pip install paddlepaddle-gpu --quiet 2>nul
    )
)
echo       OK

:: Install PaddleOCR
echo [3/5] Installing PaddleOCR...
pip install "paddleocr>=2.9.0" --quiet 2>nul
if %errorLevel% neq 0 (
    pip install paddleocr --quiet
)
echo       OK

:: Install additional dependencies
echo [4/5] Installing OCR dependencies...
pip install opencv-python-headless pyclipper --quiet 2>nul
echo       OK

:: Test installation
echo [5/5] Testing installation...
python -c "import paddleocr; print('PaddleOCR imported successfully')" 2>nul
if %errorLevel% equ 0 (
    echo       OK
    echo.
    echo ========================================
    echo   PaddleOCR Installed Successfully!
    echo ========================================
    echo.
    echo Note: OCR models will download on first use.
    echo Restart the server to enable OCR.
    echo.
    pause
    exit /b 0
) else (
    echo [WARNING] PaddleOCR installation may have issues.
    echo Trying EasyOCR fallback...
    goto :install_easyocr
)

:install_easyocr
echo.
echo ========================================
echo   Installing EasyOCR
echo ========================================
echo.

echo [1/3] Installing PyTorch...
pip install --only-binary :all: torch torchvision --quiet
if %errorLevel% neq 0 (
    echo [WARNING] Binary install failed, trying regular install...
    pip install torch torchvision
)
echo       OK

echo [2/3] Installing EasyOCR...
pip install easyocr
if %errorLevel% neq 0 (
    echo [ERROR] Failed to install EasyOCR
    pause
    exit /b 1
)
echo       OK

echo [3/3] Downloading OCR language models (Japanese + English)...
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
