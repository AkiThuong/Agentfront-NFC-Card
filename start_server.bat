@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Start
echo ========================================
echo.

:: Force Python 3.13 ONLY
set PYTHON_CMD=
set NEED_RESTART=0

:: Check for Python 3.13 via py launcher
py -3.13 --version >nul 2>&1
if %errorLevel% equ 0 (
    set PYTHON_CMD=py -3.13
    for /f "tokens=*" %%v in ('py -3.13 --version 2^>^&1') do echo %%v
    goto :python_ready
)

:: Python 3.13 not found - install it
echo.
echo ========================================
echo   Python 3.13 Required - Installing...
echo ========================================
echo.
echo Python 3.14 has compatibility issues with packages.
echo Installing Python 3.13...
echo.

:: Try winget first
winget --version >nul 2>&1
if %errorLevel% equ 0 (
    echo Using winget...
    winget install Python.Python.3.13 --accept-source-agreements --accept-package-agreements --silent
    if %errorLevel% equ 0 (
        set NEED_RESTART=1
        goto :check_restart
    )
    echo winget failed, trying direct download...
)

:: Download directly
echo Downloading from python.org...
set INSTALLER=%TEMP%\python-3.13-installer.exe
curl -L -o "%INSTALLER%" "https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe" 2>nul
if not exist "%INSTALLER%" (
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe' -OutFile '%INSTALLER%'" 2>nul
)

if exist "%INSTALLER%" (
    echo Running installer...
    "%INSTALLER%" /passive InstallAllUsers=1 PrependPath=1 Include_test=0
    del "%INSTALLER%" 2>nul
    set NEED_RESTART=1
    goto :check_restart
)

echo [ERROR] Failed to install Python 3.13
echo Please install manually: https://www.python.org/downloads/release/python-3131/
pause
exit /b 1

:check_restart
if %NEED_RESTART% equ 1 (
    echo.
    echo ========================================
    echo   Python 3.13 Installed!
    echo ========================================
    echo.
    echo IMPORTANT: Close this window and run start_server.bat again.
    echo.
    pause
    exit /b 0
)

:python_ready
echo.

:: ALWAYS delete venv if it's not Python 3.13
if exist "venv\Scripts\python.exe" (
    echo Checking virtual environment Python version...
    for /f "tokens=2 delims= " %%v in ('"venv\Scripts\python.exe" --version 2^>^&1') do set VENV_VER=%%v
    echo Current venv: Python !VENV_VER!
    
    echo !VENV_VER! | findstr /b "3.13" >nul
    if !errorLevel! neq 0 (
        echo.
        echo [WARNING] venv is Python !VENV_VER!, not 3.13!
        echo Deleting old venv and recreating with Python 3.13...
        rmdir /s /q venv 2>nul
        echo.
    )
)

:: Create venv with Python 3.13
if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment with Python 3.13...
    %PYTHON_CMD% -m venv venv
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

:: Verify Python version in venv
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set ACTIVE_VER=%%v
echo Active Python: !ACTIVE_VER!

echo !ACTIVE_VER! | findstr /b "3.13" >nul
if !errorLevel! neq 0 (
    echo.
    echo [ERROR] Wrong Python version in venv: !ACTIVE_VER!
    echo Expected: 3.13.x
    echo.
    echo Deleting venv and retrying...
    deactivate 2>nul
    rmdir /s /q venv 2>nul
    
    echo Creating fresh venv...
    %PYTHON_CMD% -m venv venv
    call "venv\Scripts\activate.bat"
)

echo.

:: Install core dependencies if missing
python -c "import websockets" >nul 2>&1
if %errorLevel% neq 0 (
    echo ========================================
    echo   Installing Core Dependencies
    echo ========================================
    echo.
    
    python -m pip install --upgrade pip --quiet
    
    echo [1/5] websockets...
    pip install --only-binary :all: websockets --quiet && echo       OK
    
    echo [2/5] pycryptodome...
    pip install --only-binary :all: pycryptodome --quiet && echo       OK
    
    echo [3/5] Pillow...
    pip install --only-binary :all: Pillow --quiet && echo       OK
    
    echo [4/5] numpy...
    pip install --only-binary :all: numpy --quiet && echo       OK
    
    echo [5/5] pywin32...
    pip install --only-binary :all: pywin32 --quiet && echo       OK
    python -m pywin32_postinstall -install >nul 2>&1
    
    echo.
)

:: Install EasyOCR if missing
python -c "import easyocr" >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo ========================================
    echo   Installing EasyOCR + PyTorch
    echo ========================================
    echo.
    echo Downloading ~2GB. Please wait...
    echo.
    
    echo Installing PyTorch...
    pip install --only-binary :all: torch torchvision --quiet 2>nul
    if %errorLevel% neq 0 (
        pip install torch torchvision --quiet
    )
    
    echo Installing EasyOCR...
    pip install --only-binary :all: easyocr --quiet 2>nul
    if %errorLevel% neq 0 (
        pip install easyocr --quiet
    )
    
    python -c "import easyocr" >nul 2>&1
    if %errorLevel% equ 0 (
        echo.
        echo Downloading OCR models...
        python -c "import easyocr; easyocr.Reader(['ja', 'en'], gpu=False, verbose=False); print('Models loaded!')"
        echo EasyOCR installed!
    ) else (
        echo [ERROR] Failed to install EasyOCR
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
