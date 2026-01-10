@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Start
echo ========================================
echo.

:: Force Python 3.13
set PYTHON_CMD=
set NEED_RESTART=0

:: Check for Python 3.13 via py launcher
py -3.13 --version >nul 2>&1
if %errorLevel% equ 0 (
    set PYTHON_CMD=py -3.13
    py -3.13 --version
    goto :python_ready
)

:: Python 3.13 not found - install it
echo [INFO] Python 3.13 not found. Installing...
echo.

:: Try winget first
winget --version >nul 2>&1
if %errorLevel% equ 0 (
    echo Installing Python 3.13 via winget...
    winget install Python.Python.3.13 --accept-source-agreements --accept-package-agreements --silent
    if %errorLevel% equ 0 (
        set NEED_RESTART=1
        goto :check_restart
    )
)

:: winget failed, download directly
echo Downloading Python 3.13...
set INSTALLER=%TEMP%\python-3.13-installer.exe
curl -L -o "%INSTALLER%" "https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe" 2>nul
if not exist "%INSTALLER%" (
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe' -OutFile '%INSTALLER%'" 2>nul
)

if exist "%INSTALLER%" (
    echo Installing Python 3.13...
    "%INSTALLER%" /passive InstallAllUsers=1 PrependPath=1 Include_test=0
    del "%INSTALLER%" 2>nul
    set NEED_RESTART=1
    goto :check_restart
)

echo [ERROR] Failed to install Python 3.13
echo Please install manually from: https://www.python.org/downloads/release/python-3131/
pause
exit /b 1

:check_restart
if %NEED_RESTART% equ 1 (
    echo.
    echo ========================================
    echo   Python 3.13 Installed!
    echo ========================================
    echo.
    echo Please close this window and run start_server.bat again.
    echo.
    pause
    exit /b 0
)

:python_ready
echo.

:: Remove old venv if wrong Python version
if exist "venv\pyvenv.cfg" (
    findstr /c:"3.13" "venv\pyvenv.cfg" >nul 2>&1
    if %errorLevel% neq 0 (
        echo Removing old virtual environment...
        rmdir /s /q venv 2>nul
    )
)

:: Create venv if not exists
if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment with Python 3.13...
    %PYTHON_CMD% -m venv venv
    if %errorLevel% neq 0 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
)

:: Activate venv
call "venv\Scripts\activate.bat"

:: Check if core dependencies are installed
python -c "import websockets" >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo ========================================
    echo   Installing Dependencies
    echo ========================================
    echo.
    
    python -m pip install --upgrade pip --quiet
    
    echo [1/6] websockets...
    pip install --only-binary :all: websockets --quiet && echo       OK
    
    echo [2/6] pycryptodome...
    pip install --only-binary :all: pycryptodome --quiet && echo       OK
    
    echo [3/6] Pillow...
    pip install --only-binary :all: Pillow --quiet && echo       OK
    
    echo [4/6] numpy...
    pip install --only-binary :all: numpy --quiet && echo       OK
    
    echo [5/6] pywin32...
    pip install --only-binary :all: pywin32 --quiet && echo       OK
    python -m pywin32_postinstall -install >nul 2>&1
    
    echo [6/6] pyscard...
    pip install --only-binary :all: pyscard --quiet 2>nul
    if %errorLevel% neq 0 (
        pip install pyscard --quiet 2>nul
        if %errorLevel% neq 0 (
            echo       FAILED - NFC may not work
        ) else (
            echo       OK
        )
    ) else (
        echo       OK
    )
    echo.
)

:: Check and install pyscard if missing
python -c "import smartcard" >nul 2>&1
if %errorLevel% neq 0 (
    echo Installing pyscard...
    pip install --only-binary :all: pyscard --quiet 2>nul
    if %errorLevel% neq 0 (
        pip install pyscard --quiet 2>nul
    )
)

:: Check and install EasyOCR if missing
python -c "import easyocr" >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo ========================================
    echo   Installing EasyOCR + PyTorch
    echo ========================================
    echo.
    echo This will download ~2GB. Please wait...
    echo.
    
    echo Installing PyTorch...
    pip install --only-binary :all: torch torchvision --quiet 2>nul
    if %errorLevel% neq 0 (
        pip install torch torchvision --quiet
    )
    
    echo Installing EasyOCR...
    pip install easyocr --quiet
    
    if %errorLevel% equ 0 (
        echo.
        echo Downloading OCR models (Japanese + English)...
        python -c "import easyocr; easyocr.Reader(['ja', 'en'], gpu=False, verbose=False); print('Models loaded!')"
        echo.
        echo EasyOCR installed!
    ) else (
        echo [WARNING] EasyOCR installation failed
    )
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

echo.
echo Server stopped.
pause
