@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   AgentFront.ai Startup Installer
echo ========================================
echo.
echo This will configure AgentFront.ai to:
echo   - Launch automatically on Windows login
echo   - Open in full screen mode
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

:: ========================================
:: Find AgentFront.ai Application
:: ========================================
echo Searching for AgentFront.ai...
echo.

:: Common installation paths to check
set AGENTFRONT_PATH=

:: Check common locations
if exist "C:\Program Files\AgentFront.ai\AgentFront.ai.exe" (
    set AGENTFRONT_PATH=C:\Program Files\AgentFront.ai\AgentFront.ai.exe
)
if exist "C:\Program Files (x86)\AgentFront.ai\AgentFront.ai.exe" (
    set AGENTFRONT_PATH=C:\Program Files (x86)\AgentFront.ai\AgentFront.ai.exe
)
if exist "%LOCALAPPDATA%\AgentFront.ai\AgentFront.ai.exe" (
    set AGENTFRONT_PATH=%LOCALAPPDATA%\AgentFront.ai\AgentFront.ai.exe
)
if exist "%LOCALAPPDATA%\Programs\AgentFront.ai\AgentFront.ai.exe" (
    set AGENTFRONT_PATH=%LOCALAPPDATA%\Programs\AgentFront.ai\AgentFront.ai.exe
)
:: Check for Edge/Chrome PWA style apps
if exist "%LOCALAPPDATA%\AgentFront\AgentFront.exe" (
    set AGENTFRONT_PATH=%LOCALAPPDATA%\AgentFront\AgentFront.exe
)

:: If not found, ask user
if "%AGENTFRONT_PATH%"=="" (
    echo AgentFront.ai not found in common locations.
    echo.
    echo Please enter the full path to AgentFront.ai executable:
    echo Example: C:\Program Files\AgentFront.ai\AgentFront.ai.exe
    echo.
    set /p AGENTFRONT_PATH="Path: "
    
    if not exist "!AGENTFRONT_PATH!" (
        echo.
        echo [ERROR] File not found: !AGENTFRONT_PATH!
        echo.
        echo Please make sure AgentFront.ai is installed.
        echo.
        pause
        exit /b 1
    )
)

echo Found: %AGENTFRONT_PATH%
echo.

:: ========================================
:: Create Launcher VBS Script (Full Screen)
:: ========================================
echo Creating full screen launcher...

set LAUNCHER_VBS=%SCRIPT_DIR%_launch_agentfront.vbs

:: Create VBS script that launches app and sends F11 for full screen
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo.
echo ' Launch AgentFront.ai
echo WshShell.Run """%AGENTFRONT_PATH%""", 1, False
echo.
echo ' Wait for app to load
echo WScript.Sleep 3000
echo.
echo ' Try to maximize and go full screen with F11
echo WshShell.AppActivate "AgentFront"
echo WScript.Sleep 500
echo WshShell.SendKeys "{F11}"
echo.
echo Set WshShell = Nothing
) > "%LAUNCHER_VBS%"

echo Created: %LAUNCHER_VBS%
echo.

:: ========================================
:: Create Alternative PowerShell Launcher
:: ========================================
set LAUNCHER_PS1=%SCRIPT_DIR%_launch_agentfront.ps1

(
echo # Launch AgentFront.ai in Full Screen
echo $agentFrontPath = "%AGENTFRONT_PATH%"
echo.
echo # Start the application
echo Start-Process -FilePath $agentFrontPath
echo.
echo # Wait for app to initialize
echo Start-Sleep -Seconds 3
echo.
echo # Try to bring to foreground and maximize
echo Add-Type @"
echo using System;
echo using System.Runtime.InteropServices;
echo public class Window {
echo     [DllImport^("user32.dll"^)]
echo     public static extern bool ShowWindow^(IntPtr hWnd, int nCmdShow^);
echo     [DllImport^("user32.dll"^)]
echo     public static extern bool SetForegroundWindow^(IntPtr hWnd^);
echo }
echo "@
echo.
echo $process = Get-Process -Name "*AgentFront*" -ErrorAction SilentlyContinue ^| Select-Object -First 1
echo if ^($process^) {
echo     [Window]::SetForegroundWindow^($process.MainWindowHandle^)
echo     [Window]::ShowWindow^($process.MainWindowHandle, 3^)  # SW_MAXIMIZE
echo     
echo     # Send F11 for full screen
echo     Start-Sleep -Milliseconds 500
echo     [System.Windows.Forms.SendKeys]::SendWait^("{F11}"^)
echo }
) > "%LAUNCHER_PS1%"

echo Created: %LAUNCHER_PS1%
echo.

:: ========================================
:: Remove Existing Scheduled Task
:: ========================================
echo Removing existing startup task...
schtasks /delete /tn "AgentFront_Startup" /f >nul 2>&1
echo Done.
echo.

:: ========================================
:: Create Scheduled Task for Login
:: ========================================
echo Creating startup task...

set STARTUP_TASK_XML=%SCRIPT_DIR%_agentfront_startup.xml

(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Description^>Launch AgentFront.ai in full screen on login^</Description^>
echo   ^</RegistrationInfo^>
echo   ^<Triggers^>
echo     ^<LogonTrigger^>
echo       ^<Enabled^>true^</Enabled^>
echo       ^<Delay^>PT10S^</Delay^>
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
echo     ^<ExecutionTimeLimit^>PT1M^</ExecutionTimeLimit^>
echo   ^</Settings^>
echo   ^<Actions Context="Author"^>
echo     ^<Exec^>
echo       ^<Command^>wscript.exe^</Command^>
echo       ^<Arguments^>"%LAUNCHER_VBS%"^</Arguments^>
echo       ^<WorkingDirectory^>%SCRIPT_DIR%^</WorkingDirectory^>
echo     ^</Exec^>
echo   ^</Actions^>
echo ^</Task^>
) > "%STARTUP_TASK_XML%"

:: Import the task
schtasks /create /tn "AgentFront_Startup" /xml "%STARTUP_TASK_XML%" /f
if %errorLevel% equ 0 (
    echo [OK] Startup task created successfully
) else (
    echo [WARNING] Task Scheduler method failed, trying Startup folder...
    
    :: Fallback: Create shortcut in Startup folder
    set STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
    
    powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTUP_FOLDER%\AgentFront.ai.lnk'); $s.TargetPath = 'wscript.exe'; $s.Arguments = '\"%LAUNCHER_VBS%\"'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.Save()"
    
    if exist "%STARTUP_FOLDER%\AgentFront.ai.lnk" (
        echo [OK] Created startup shortcut in Startup folder
    )
)
echo.

:: ========================================
:: Verify Task
:: ========================================
echo ========================================
echo   Scheduled Task Status
echo ========================================
echo.
schtasks /query /tn "AgentFront_Startup" /fo list 2>nul | findstr "TaskName Status"
if %errorLevel% neq 0 (
    echo Task not found in scheduler.
    if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AgentFront.ai.lnk" (
        echo Using Startup folder method instead.
    )
)
echo.

:: ========================================
:: Test Option
:: ========================================
echo.
set /p TEST_NOW="Test launch now? (Y/N): "
if /i "%TEST_NOW%"=="Y" (
    echo.
    echo Launching AgentFront.ai in full screen...
    wscript.exe "%LAUNCHER_VBS%"
)

echo.
echo ========================================
echo   Installation Complete
echo ========================================
echo.
echo AgentFront.ai will:
echo   - Launch automatically on Windows login
echo   - Open in full screen mode
echo.
echo App path: %AGENTFRONT_PATH%
echo Launcher: %LAUNCHER_VBS%
echo.
echo To remove auto-start:
echo   schtasks /delete /tn "AgentFront_Startup" /f
echo   del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AgentFront.ai.lnk"
echo.
pause
