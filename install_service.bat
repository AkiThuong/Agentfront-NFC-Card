@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Install Service
echo ========================================
echo.

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Please run as Administrator!
    echo.
    echo Right-click this file and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

echo Running as Administrator - OK
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

winget --version >nul 2>&1
if %errorLevel% equ 0 (
    echo Installing Python 3.13 via winget...
    winget install Python.Python.3.13 --accept-source-agreements --accept-package-agreements --silent
    if %errorLevel% equ 0 (
        set NEED_RESTART=1
        goto :check_restart
    )
)

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
pause
exit /b 1

:check_restart
if %NEED_RESTART% equ 1 (
    echo.
    echo Python 3.13 Installed! Please restart this script.
    pause
    exit /b 0
)

:python_ready
echo.

:: Check and install Visual C++ Redistributable (required for PyTorch)
reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" >nul 2>&1
if %errorLevel% neq 0 (
    echo Installing Visual C++ Redistributable...
    set VCREDIST=%TEMP%\vc_redist.x64.exe
    curl -L -o "!VCREDIST!" "https://aka.ms/vs/17/release/vc_redist.x64.exe" 2>nul
    if not exist "!VCREDIST!" (
        powershell -Command "Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile '!VCREDIST!'" 2>nul
    )
    if exist "!VCREDIST!" (
        "!VCREDIST!" /install /passive /norestart
        del "!VCREDIST!" 2>nul
        echo VC++ Redistributable installed!
    )
    echo.
)

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
    echo Creating virtual environment...
    %PYTHON_CMD% -m venv venv
)

:: Activate venv
call "venv\Scripts\activate.bat"

:: Install all dependencies if missing
python -c "import websockets" >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo Installing dependencies...
    python -m pip install --upgrade pip --quiet
    
    pip install --only-binary :all: websockets pycryptodome Pillow numpy pywin32 --quiet
    python -m pywin32_postinstall -install >nul 2>&1
    
    echo Dependencies installed!
)

:: Install EasyOCR if missing
python -c "import easyocr" >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo Installing EasyOCR + PyTorch (~2GB)...
    pip install --only-binary :all: torch torchvision --quiet 2>nul
    if %errorLevel% neq 0 ( pip install torch torchvision --quiet )
    pip install easyocr --quiet
    
    if %errorLevel% equ 0 (
        echo Downloading OCR models...
        python -c "import easyocr; easyocr.Reader(['ja', 'en'], gpu=False, verbose=False)"
        echo EasyOCR installed!
    )
)

:: Stop existing service
echo.
echo Stopping existing service...
net stop NFCBridgeService >nul 2>&1
python nfc_service.py stop >nul 2>&1
timeout /t 2 /nobreak >nul

:: Remove existing service
echo Removing existing service...
python nfc_service.py remove >nul 2>&1
sc delete NFCBridgeService >nul 2>&1
timeout /t 2 /nobreak >nul

:: Install the service
echo.
echo Installing NFC Bridge Service...
python nfc_service.py install
if %errorLevel% neq 0 (
    echo [ERROR] Failed to install service
    pause
    exit /b 1
)

:: Configure auto-start
echo Configuring auto-start...
sc config NFCBridgeService start= auto >nul 2>&1

:: Start the service
echo Starting service...
python nfc_service.py start

:: Verify
timeout /t 2 /nobreak >nul
sc query NFCBridgeService | findstr "RUNNING" >nul 2>&1
if %errorLevel% equ 0 (
    echo.
    echo ========================================
    echo   SUCCESS!
    echo ========================================
    echo.
    echo NFC Bridge Service is:
    echo   - Installed
    echo   - Running  
    echo   - Auto-start on boot
    echo.
    echo Port: 3005
    echo.
) else (
    echo.
    echo Service installed. Check: sc query NFCBridgeService
)

pause
