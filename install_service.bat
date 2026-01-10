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
    echo Please close this window and run install_service.bat again.
    echo ^(PATH needs to refresh^)
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

:: Check if pywin32 is installed
python -c "import win32serviceutil" >nul 2>&1
if %errorLevel% neq 0 (
    echo Installing dependencies...
    python -m pip install --upgrade pip --quiet
    
    :: Install with binary-only
    pip install --only-binary :all: websockets pycryptodome Pillow numpy pywin32 --quiet
    
    :: pywin32 post-install
    python -m pywin32_postinstall -install >nul 2>&1
    
    :: pyscard
    pip install --only-binary :all: pyscard --quiet 2>nul
    if %errorLevel% neq 0 (
        pip install pyscard --quiet 2>nul
    )
    
    echo Dependencies installed!
    echo.
)

:: Stop existing service if running
echo Stopping existing service (if any)...
net stop NFCBridgeService >nul 2>&1
python nfc_service.py stop >nul 2>&1
timeout /t 2 /nobreak >nul

:: Remove existing service
echo Removing existing service (if any)...
python nfc_service.py remove >nul 2>&1
sc delete NFCBridgeService >nul 2>&1
timeout /t 2 /nobreak >nul

:: Install the service
echo.
echo Installing NFC Bridge Service...
python nfc_service.py install
if %errorLevel% neq 0 (
    echo.
    echo [ERROR] Failed to install service
    pause
    exit /b 1
)

:: Configure service to start automatically
echo.
echo Configuring auto-start on boot...
sc config NFCBridgeService start= auto >nul 2>&1

:: Start the service
echo.
echo Starting service...
python nfc_service.py start
if %errorLevel% neq 0 (
    echo.
    echo [WARNING] Service installed but failed to start
    echo Try: net start NFCBridgeService
)

:: Verify service is running
echo.
echo Checking service status...
timeout /t 2 /nobreak >nul
sc query NFCBridgeService | findstr "RUNNING" >nul 2>&1
if %errorLevel% equ 0 (
    echo.
    echo ========================================
    echo   SUCCESS!
    echo ========================================
    echo.
    echo NFC Bridge Service is now:
    echo   - Installed
    echo   - Running
    echo   - Set to auto-start on boot
    echo.
    echo Service name: NFCBridgeService
    echo Port: 3005
    echo.
) else (
    echo.
    echo [INFO] Service installed.
    echo Check status with: sc query NFCBridgeService
)

pause
