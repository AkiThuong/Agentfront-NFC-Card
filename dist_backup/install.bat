@echo off
echo ====================================
echo NFC Bridge Server - Installation
echo ====================================
echo.

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Please run as Administrator!
    pause
    exit /b 1
)

echo Installing NFC Bridge Service...
nfc_service.exe install

echo.
echo Starting NFC Bridge Service...
nfc_service.exe start

echo.
echo ====================================
echo Installation complete!
echo.
echo The NFC Bridge Server is now running.
echo Service name: NFCBridgeService
echo.
echo To open status page, run: nfc_launcher.exe
echo ====================================
pause
