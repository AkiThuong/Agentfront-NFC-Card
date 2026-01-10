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

:: Check if Python is available
where python >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python not found!
    echo Please run install_dependencies.bat first.
    pause
    exit /b 1
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

:: Check if pywin32 is installed
python -c "import win32serviceutil" >nul 2>&1
if %errorLevel% neq 0 (
    echo Installing Windows service dependencies...
    pip install pywin32
    
    :: Run pywin32 post-install script
    python -m pywin32_postinstall -install >nul 2>&1
)

:: Check if core dependencies are installed
python -c "import websockets" >nul 2>&1
if %errorLevel% neq 0 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

:: Stop existing service if running
echo.
echo Stopping existing service (if any)...
python nfc_service.py stop >nul 2>&1
timeout /t 2 /nobreak >nul

:: Remove existing service
echo Removing existing service (if any)...
python nfc_service.py remove >nul 2>&1
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
    echo Try starting manually: net start NFCBridgeService
)

:: Verify service is running
echo.
echo Checking service status...
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
    echo To check status:  sc query NFCBridgeService
    echo To stop service:  net stop NFCBridgeService
    echo To start service: net start NFCBridgeService
    echo.
) else (
    echo.
    echo [WARNING] Service installed but may not be running
    echo Check with: sc query NFCBridgeService
)

pause
