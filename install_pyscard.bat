@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   pyscard Installation Helper
echo ========================================
echo.
echo This script helps install pyscard for NFC reader support.
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

echo Current Python version:
python --version
echo.

:: Check if pyscard is already working
python -c "from smartcard.System import readers; print('pyscard is already installed and working!')" 2>nul
if %errorLevel% equ 0 (
    echo.
    echo Listing available readers:
    python -c "from smartcard.System import readers; r = readers(); print(f'Found {len(r)} reader(s):'); [print(f'  - {x}') for x in r]"
    echo.
    pause
    exit /b 0
)

echo pyscard is not installed. Attempting installation...
echo.

:: Method 1: Try pip with binary only
echo [Method 1] Trying pip install --only-binary...
pip install --only-binary :all: pyscard 2>nul
python -c "from smartcard.System import readers" >nul 2>&1
if %errorLevel% equ 0 (
    echo Success!
    goto :success
)

:: Method 2: Try regular pip
echo [Method 2] Trying pip install pyscard...
pip install pyscard 2>nul
python -c "from smartcard.System import readers" >nul 2>&1
if %errorLevel% equ 0 (
    echo Success!
    goto :success
)

:: Method 3: Install SWIG first
echo.
echo [Method 3] Installing SWIG (required to build pyscard)...
winget install swig --accept-source-agreements --accept-package-agreements --silent 2>nul
if %errorLevel% equ 0 (
    echo SWIG installed. Retrying pyscard...
    pip install pyscard 2>nul
    python -c "from smartcard.System import readers" >nul 2>&1
    if %errorLevel% equ 0 (
        echo Success!
        goto :success
    )
)

:: Method 4: Download pre-built wheel
echo.
echo [Method 4] Downloading pre-built wheel...
echo.

:: Determine Python version for wheel filename
for /f "tokens=1,2 delims=." %%a in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
set WHEEL_NAME=pyscard-2.0.7-cp%PY_MAJOR%%PY_MINOR%-cp%PY_MAJOR%%PY_MINOR%-win_amd64.whl

echo Looking for: %WHEEL_NAME%
echo.

:: Try to download from PyPI
pip download --only-binary :all: --platform win_amd64 --python-version %PY_MAJOR%.%PY_MINOR% pyscard -d . 2>nul
if exist "pyscard*.whl" (
    echo Found wheel file. Installing...
    pip install pyscard*.whl 2>nul
    del pyscard*.whl 2>nul
    
    python -c "from smartcard.System import readers" >nul 2>&1
    if %errorLevel% equ 0 (
        echo Success!
        goto :success
    )
)

:: All methods failed
echo.
echo ========================================
echo   [ERROR] pyscard installation failed
echo ========================================
echo.
echo Please try one of these manual methods:
echo.
echo Option A - Download wheel manually:
echo   1. Go to: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyscard
echo   2. Download the wheel for Python %PY_MAJOR%.%PY_MINOR% (64-bit)
echo   3. Run: pip install [downloaded_file].whl
echo.
echo Option B - Use conda:
echo   conda install -c conda-forge pyscard
echo.
echo Option C - Build from source:
echo   1. Install Visual Studio Build Tools
echo   2. Install SWIG: winget install swig
echo   3. pip install pyscard
echo.
pause
exit /b 1

:success
echo.
echo ========================================
echo   pyscard installed successfully!
echo ========================================
echo.
echo Checking for NFC readers...
python -c "from smartcard.System import readers; r = readers(); print(f'Found {len(r)} reader(s):'); [print(f'  - {x}') for x in r] if r else print('  No readers detected - connect your NFC reader')"
echo.
echo If no readers are detected:
echo   1. Ensure your NFC reader is connected
echo   2. Install reader drivers if needed
echo   3. For Sony PaSoRi: https://www.sony.co.jp/Products/felica/consumer/download/
echo.
pause
