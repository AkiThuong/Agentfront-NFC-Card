@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - COMPLETE Uninstall
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

:: ========================================
:: Step 1: Kill any running Python processes on port 3005
:: ========================================
echo [Step 1] Killing processes on port 3005...

:: Find PID using port 3005
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3005 ^| findstr LISTENING 2^>nul') do (
    echo   Found PID: %%a on port 3005
    taskkill /PID %%a /F >nul 2>&1
    echo   Killed PID: %%a
)

:: Kill any Python processes that might be the server
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM pythonw.exe /T >nul 2>&1
echo   All Python processes killed
echo.

:: ========================================
:: Step 2: Stop and Remove Windows Service
:: ========================================
echo [Step 2] Removing Windows Service...

:: Stop the service
net stop NFCBridgeService >nul 2>&1
echo   Service stopped

:: Use sc to delete (more reliable)
sc stop NFCBridgeService >nul 2>&1
sc delete NFCBridgeService >nul 2>&1
echo   Service deleted via sc command

:: Also try via Python
if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
    python nfc_service.py stop >nul 2>&1
    python nfc_service.py remove >nul 2>&1
    echo   Service removed via Python
)

echo.

:: ========================================
:: Step 3: Remove ALL Scheduled Tasks
:: ========================================
echo [Step 3] Removing Scheduled Tasks...

schtasks /Delete /TN "NFCBridgeStartup" /F >nul 2>&1
echo   Deleted: NFCBridgeStartup

schtasks /Delete /TN "NFCBridge" /F >nul 2>&1
echo   Deleted: NFCBridge

schtasks /Delete /TN "AgentfrontNFCBridge" /F >nul 2>&1
echo   Deleted: AgentfrontNFCBridge

schtasks /Delete /TN "NFCBridgeWakeSchedule" /F >nul 2>&1
echo   Deleted: NFCBridgeWakeSchedule

schtasks /Delete /TN "NFCBridgeShutdown" /F >nul 2>&1
echo   Deleted: NFCBridgeShutdown

schtasks /Delete /TN "NFCServerAutoStart" /F >nul 2>&1
echo   Deleted: NFCServerAutoStart

echo.

:: ========================================
:: Step 4: Remove Startup Scripts
:: ========================================
echo [Step 4] Removing Startup Scripts...

set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

if exist "%STARTUP_DIR%\start_server_background.vbs" (
    del "%STARTUP_DIR%\start_server_background.vbs" >nul 2>&1
    echo   Deleted: start_server_background.vbs from Startup
)

if exist "%STARTUP_DIR%\nfc_bridge*.vbs" (
    del "%STARTUP_DIR%\nfc_bridge*.vbs" >nul 2>&1
    echo   Deleted: nfc_bridge VBS files from Startup
)

if exist "%STARTUP_DIR%\agentfront*.vbs" (
    del "%STARTUP_DIR%\agentfront*.vbs" >nul 2>&1
    echo   Deleted: agentfront VBS files from Startup
)

echo.

:: ========================================
:: Step 5: Verify Port 3005 is Free
:: ========================================
echo [Step 5] Verifying port 3005 is free...

netstat -ano | findstr :3005 >nul 2>&1
if %errorLevel% equ 0 (
    echo   [WARNING] Port 3005 is still in use!
    echo.
    echo   Active connections:
    netstat -ano | findstr :3005
    echo.
    echo   You may need to restart Windows.
) else (
    echo   [OK] Port 3005 is free!
)

echo.

:: ========================================
:: Step 6: Verify Service is Gone
:: ========================================
echo [Step 6] Verifying service removal...

sc query NFCBridgeService >nul 2>&1
if %errorLevel% equ 0 (
    echo   [WARNING] Service still exists. May need restart.
) else (
    echo   [OK] Service removed successfully!
)

echo.
echo ========================================
echo   UNINSTALL COMPLETE
echo ========================================
echo.
echo All NFC Bridge services, tasks, and startup scripts
echo have been removed.
echo.
echo If port 3005 is still in use, restart Windows.
echo.
echo To run manually later, use: start_server.bat
echo.

pause
