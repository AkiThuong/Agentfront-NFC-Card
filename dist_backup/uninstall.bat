@echo off
echo ====================================
echo NFC Bridge Server - Uninstallation
echo ====================================
echo.

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Please run as Administrator!
    pause
    exit /b 1
)

echo Stopping NFC Bridge Service...
nfc_service.exe stop

echo.
echo Removing NFC Bridge Service...
nfc_service.exe remove

echo.
echo ====================================
echo Uninstallation complete!
echo ====================================
pause
