@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Remove Startup
echo ========================================
echo.
echo This will:
echo   1. Stop the NFC Bridge Server if running
echo   2. Remove the auto-start scheduled task
echo   3. Remove startup shortcuts
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

:: Get script directory
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

echo ----------------------------------------
echo Step 1: Stopping NFC Bridge Server...
echo ----------------------------------------
echo.

:: Find and kill python processes running server.py
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq python.exe" /fo list ^| findstr "PID:"') do (
    wmic process where "ProcessId=%%a" get CommandLine 2>nul | findstr /i "server.py" >nul
    if !errorLevel! equ 0 (
        echo Killing python.exe PID %%a (server.py)
        taskkill /pid %%a /f >nul 2>&1
    )
)

:: Also kill pythonw.exe (background python)
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq pythonw.exe" /fo list ^| findstr "PID:"') do (
    wmic process where "ProcessId=%%a" get CommandLine 2>nul | findstr /i "server.py" >nul
    if !errorLevel! equ 0 (
        echo Killing pythonw.exe PID %%a (server.py)
        taskkill /pid %%a /f >nul 2>&1
    )
)

:: Force kill any process using port 3005
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3005.*LISTEN"') do (
    echo Killing process on port 3005 (PID %%a)
    taskkill /pid %%a /f >nul 2>&1
)

:: Verify port is free
timeout /t 1 /nobreak >nul
netstat -an | findstr ":3005.*LISTEN" >nul 2>&1
if %errorLevel% equ 0 (
    echo [WARNING] Port 3005 still in use
) else (
    echo Server stopped successfully.
)
echo.

echo ----------------------------------------
echo Step 2: Removing Scheduled Tasks...
echo ----------------------------------------
echo.

:: Remove main scheduled task
schtasks /query /tn "NFCBridgeServer" >nul 2>&1
if %errorLevel% equ 0 (
    echo Removing task: NFCBridgeServer
    schtasks /delete /tn "NFCBridgeServer" /f
) else (
    echo Task NFCBridgeServer not found (OK)
)

:: Remove backup scheduled task if exists
schtasks /query /tn "NFCBridgeServerStartup" >nul 2>&1
if %errorLevel% equ 0 (
    echo Removing task: NFCBridgeServerStartup
    schtasks /delete /tn "NFCBridgeServerStartup" /f
) else (
    echo Task NFCBridgeServerStartup not found (OK)
)

echo.

echo ----------------------------------------
echo Step 3: Removing Startup Shortcuts...
echo ----------------------------------------
echo.

:: Remove from Startup folder
set STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
if exist "%STARTUP_FOLDER%\NFC Bridge Server.lnk" (
    echo Removing: %STARTUP_FOLDER%\NFC Bridge Server.lnk
    del "%STARTUP_FOLDER%\NFC Bridge Server.lnk" /f
) else (
    echo No startup shortcut found (OK)
)

echo.

echo ----------------------------------------
echo Step 4: Cleaning Up Temp Files...
echo ----------------------------------------
echo.

:: Remove wrapper script
if exist "%SCRIPT_DIR%_run_server.bat" (
    echo Removing: _run_server.bat
    del "%SCRIPT_DIR%_run_server.bat" /f
)

:: Remove task XML
if exist "%SCRIPT_DIR%_nfc_task.xml" (
    echo Removing: _nfc_task.xml
    del "%SCRIPT_DIR%_nfc_task.xml" /f
)

:: Remove startup log
if exist "%SCRIPT_DIR%startup.log" (
    echo Removing: startup.log
    del "%SCRIPT_DIR%startup.log" /f
)

echo Done.
echo.

echo ========================================
echo   Removal Complete!
echo ========================================
echo.
echo - NFC Bridge Server has been stopped
echo - Auto-start has been disabled
echo - Startup shortcuts have been removed
echo.
echo The server will NOT start automatically anymore.
echo.
echo To start manually: start_server.bat
echo To re-enable auto-start: install_startup.bat
echo.
pause
