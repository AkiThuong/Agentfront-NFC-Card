@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Uninstall Service
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

:: Activate venv if exists
if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
)

:: Stop the service
echo Stopping NFC Bridge Service...
net stop NFCBridgeService >nul 2>&1
python nfc_service.py stop >nul 2>&1
timeout /t 2 /nobreak >nul

:: Remove the service
echo Removing NFC Bridge Service...
python nfc_service.py remove >nul 2>&1
sc delete NFCBridgeService >nul 2>&1

:: Verify removal
sc query NFCBridgeService >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo ========================================
    echo   Service Uninstalled Successfully
    echo ========================================
    echo.
    echo The NFC Bridge Service has been removed.
    echo Server will no longer start on boot.
    echo.
    echo To run manually, use: start_server.bat
    echo.
) else (
    echo.
    echo [WARNING] Service may still exist
    echo Try restarting Windows and running this again.
)

pause
