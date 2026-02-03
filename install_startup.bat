@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Install Startup
echo ========================================
echo.
echo This will configure the NFC Bridge Server to
echo start automatically when Windows starts.
echo.
echo Features:
echo   - PaddleOCR (primary) + EasyOCR (fallback)
echo   - Reads Zairyu, My Number, CCCD, Suica cards
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

:: Create a wrapper batch file for the task to run
echo Creating startup wrapper...
set WRAPPER_SCRIPT=%SCRIPT_DIR%_run_server.bat

:: Use explicit echo with redirection to create wrapper script
echo @echo off> "%WRAPPER_SCRIPT%"
echo cd /d %SCRIPT_DIR%>> "%WRAPPER_SCRIPT%"
echo call venv\Scripts\activate.bat>> "%WRAPPER_SCRIPT%"
echo python server.py>> "%WRAPPER_SCRIPT%"

echo Done.
echo Wrapper script: %WRAPPER_SCRIPT%
type "%WRAPPER_SCRIPT%"
echo.

:: Create the scheduled task with proper settings
echo.
echo Creating scheduled task...

:: Create XML task definition for better control
set TASK_XML=%SCRIPT_DIR%_nfc_task.xml

:: Generate task XML with working directory
(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<Triggers^>
echo     ^<LogonTrigger^>
echo       ^<Enabled^>true^</Enabled^>
echo     ^</LogonTrigger^>
echo   ^</Triggers^>
echo   ^<Principals^>
echo     ^<Principal id="Author"^>
echo       ^<LogonType^>InteractiveToken^</LogonType^>
echo       ^<RunLevel^>HighestAvailable^</RunLevel^>
echo     ^</Principal^>
echo   ^</Principals^>
echo   ^<Settings^>
echo     ^<MultipleInstancesPolicy^>IgnoreNew^</MultipleInstancesPolicy^>
echo     ^<DisallowStartIfOnBatteries^>false^</DisallowStartIfOnBatteries^>
echo     ^<StopIfGoingOnBatteries^>false^</StopIfGoingOnBatteries^>
echo     ^<AllowHardTerminate^>true^</AllowHardTerminate^>
echo     ^<StartWhenAvailable^>true^</StartWhenAvailable^>
echo     ^<RunOnlyIfNetworkAvailable^>false^</RunOnlyIfNetworkAvailable^>
echo     ^<AllowStartOnDemand^>true^</AllowStartOnDemand^>
echo     ^<Enabled^>true^</Enabled^>
echo     ^<Hidden^>false^</Hidden^>
echo     ^<ExecutionTimeLimit^>PT0S^</ExecutionTimeLimit^>
echo   ^</Settings^>
echo   ^<Actions Context="Author"^>
echo     ^<Exec^>
echo       ^<Command^>wscript.exe^</Command^>
echo       ^<Arguments^>"%SCRIPT_DIR%start_server_background.vbs"^</Arguments^>
echo       ^<WorkingDirectory^>%SCRIPT_DIR%^</WorkingDirectory^>
echo     ^</Exec^>
echo   ^</Actions^>
echo ^</Task^>
) > "%TASK_XML%"

:: Import the task
schtasks /create /tn "NFCBridgeServer" /xml "%TASK_XML%" /f

:: Also try simpler method as backup
if %errorLevel% neq 0 (
    echo XML import failed, trying simple method...
    schtasks /create /tn "NFCBridgeServer" /tr "wscript.exe \"%SCRIPT_DIR%start_server_background.vbs\"" /sc onlogon /rl highest /f
)

:: Check if task was created
schtasks /query /tn "NFCBridgeServer" >nul 2>&1
if %errorLevel% equ 0 (
    echo.
    echo ========================================
    echo   SUCCESS!
    echo ========================================
    echo.
    echo NFC Bridge Server will start automatically when you log in.
    echo.
    echo Registered tasks:
    schtasks /query /tn "NFCBridgeServer" /fo list | findstr "TaskName Status"
    schtasks /query /tn "NFCBridgeServerStartup" /fo list 2>nul | findstr "TaskName Status"
    echo.
    echo Files created:
    echo   - %WRAPPER_SCRIPT%
    echo   - %SCRIPT_DIR%start_server_background.vbs
    echo.
    echo To start now:
    echo   schtasks /run /tn "NFCBridgeServer"
    echo.
    echo To remove auto-start:
    echo   schtasks /delete /tn "NFCBridgeServer" /f
    echo   schtasks /delete /tn "NFCBridgeServerStartup" /f
    echo.
) else (
    echo.
    echo [ERROR] Failed to create scheduled task
    echo.
    echo Alternative: Add shortcut to Startup folder:
    echo.
    
    :: Create shortcut in Startup folder as fallback
    set STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
    echo Creating shortcut in Startup folder...
    
    powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTUP_FOLDER%\NFC Bridge Server.lnk'); $s.TargetPath = '%SCRIPT_DIR%start_server_background.vbs'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.Save()"
    
    if exist "%STARTUP_FOLDER%\NFC Bridge Server.lnk" (
        echo.
        echo Created startup shortcut instead!
        echo Location: %STARTUP_FOLDER%\NFC Bridge Server.lnk
    ) else (
        echo.
        echo Manual steps:
        echo   1. Press Win+R, type: shell:startup
        echo   2. Create shortcut to: %SCRIPT_DIR%start_server_background.vbs
    )
    echo.
)

:: Ask if user wants to test now
echo.
set /p START_NOW="Test the startup task now? (Y/N): "
if /i "%START_NOW%"=="Y" (
    echo.
    echo Running startup task...
    schtasks /run /tn "NFCBridgeServer"
    
    echo.
    echo Waiting for server to start...
    timeout /t 5 /nobreak >nul
    
    :: Check if server is running by testing port 3005
    netstat -an | findstr ":3005.*LISTEN" >nul 2>&1
    if !errorLevel! equ 0 (
        echo.
        echo ========================================
        echo   Server is RUNNING on port 3005!
        echo ========================================
    ) else (
        echo.
        echo Server may still be initializing...
        echo Check logs at: %SCRIPT_DIR%startup.log
        echo.
        if exist "%SCRIPT_DIR%startup.log" (
            echo Startup log:
            type "%SCRIPT_DIR%startup.log"
        )
    )
)

echo.
echo ========================================
echo   Installation Complete
echo ========================================
echo.
echo The NFC Bridge Server will automatically start
echo when you log in to Windows.
echo.
echo To manually start: start_server.bat
echo To check status:   netstat -an | findstr 3005
echo.
pause
