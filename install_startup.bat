@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Install Startup
echo ========================================
echo.
echo This will configure the NFC Bridge Server to
echo start automatically when Windows starts.
echo.
echo Method: Windows Task Scheduler (more reliable than Services)
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
echo Working directory: %CD%
echo.

:: Check if venv exists
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found!
    echo.
    echo Please run start_server.bat first to set up the environment.
    echo.
    pause
    exit /b 1
)

set VENV_PYTHON=%SCRIPT_DIR%venv\Scripts\pythonw.exe
set SERVER_SCRIPT=%SCRIPT_DIR%server.py

echo Configuration:
echo   Python: %VENV_PYTHON%
echo   Script: %SERVER_SCRIPT%
echo.

:: Remove existing scheduled task if exists
echo Removing existing scheduled task...
schtasks /delete /tn "NFCBridgeServer" /f >nul 2>&1
echo Done.
echo.

:: Create the scheduled task
echo Creating scheduled task...
schtasks /create /tn "NFCBridgeServer" /tr "\"%VENV_PYTHON%\" \"%SERVER_SCRIPT%\"" /sc onlogon /rl highest /f

if %errorLevel% equ 0 (
    echo.
    echo ========================================
    echo   SUCCESS!
    echo ========================================
    echo.
    echo NFC Bridge Server will now start automatically
    echo when you log in to Windows.
    echo.
    echo To start now without restarting:
    echo   1. Run start_server.bat
    echo   OR
    echo   2. Run: schtasks /run /tn "NFCBridgeServer"
    echo.
    echo To remove auto-start:
    echo   schtasks /delete /tn "NFCBridgeServer" /f
    echo.
) else (
    echo.
    echo [ERROR] Failed to create scheduled task
    echo.
    echo Alternative: Add start_server.bat to Startup folder:
    echo   1. Press Win+R
    echo   2. Type: shell:startup
    echo   3. Create shortcut to start_server.bat
    echo.
)

:: Ask if user wants to start now
echo.
set /p START_NOW="Start the server now? (Y/N): "
if /i "%START_NOW%"=="Y" (
    echo.
    echo Starting server...
    start "" cmd /c "cd /d "%SCRIPT_DIR%" && call venv\Scripts\activate.bat && python server.py"
    echo.
    echo Server started in background!
    timeout /t 3 /nobreak >nul
)

pause
