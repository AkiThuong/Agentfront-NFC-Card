@echo off
setlocal enabledelayedexpansion

title AgentFront.ai Startup Installer

echo.
echo ========================================
echo   AgentFront.ai Startup Installer
echo ========================================
echo.
echo This will configure AgentFront.ai to:
echo   - Launch automatically on Windows login
echo   - Open in full screen (kiosk) mode
echo.
echo Press any key to continue...
pause >nul

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo [ERROR] Please run as Administrator!
    echo.
    echo Right-click this file and select "Run as administrator"
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

echo [OK] Running as Administrator
echo.

:: Get script directory
set "SCRIPT_DIR=%~dp0"
echo Working directory: %SCRIPT_DIR%
echo.

:: ========================================
:: Find Chrome Installation
:: ========================================
echo Step 1: Finding Google Chrome...
echo.

set "CHROME_PATH="

:: Check common Chrome locations
echo   Checking: C:\Program Files\Google\Chrome\Application\
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"
    echo   [FOUND]
) else (
    echo   [NOT FOUND]
)

echo   Checking: C:\Program Files (x86)\Google\Chrome\Application\
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    echo   [FOUND]
) else (
    echo   [NOT FOUND]
)

echo   Checking: %LOCALAPPDATA%\Google\Chrome\Application\
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
    echo   [FOUND]
) else (
    echo   [NOT FOUND]
)

if "!CHROME_PATH!"=="" (
    echo.
    echo [ERROR] Google Chrome not found!
    echo Please make sure Chrome is installed.
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

echo.
echo Using Chrome: !CHROME_PATH!
echo.

:: ========================================
:: Find AgentFront.ai App/Shortcut
:: ========================================
echo Step 2: Searching for AgentFront.ai shortcut...
echo.

set "AGENTFRONT_SHORTCUT="
set "AGENTFRONT_URL="

:: Common locations for Chrome PWA shortcuts
echo   Checking Desktop...
for %%f in ("%USERPROFILE%\Desktop\AgentFront*.lnk" "%USERPROFILE%\Desktop\*agentfront*.lnk") do (
    if exist "%%f" (
        set "AGENTFRONT_SHORTCUT=%%f"
        echo   [FOUND] %%f
    )
)

echo   Checking Start Menu...
for %%f in ("%APPDATA%\Microsoft\Windows\Start Menu\Programs\AgentFront*.lnk" "%APPDATA%\Microsoft\Windows\Start Menu\Programs\*agentfront*.lnk") do (
    if exist "%%f" (
        set "AGENTFRONT_SHORTCUT=%%f"
        echo   [FOUND] %%f
    )
)

echo   Checking Chrome Apps folder...
for %%f in ("%APPDATA%\Microsoft\Windows\Start Menu\Programs\Chrome Apps\AgentFront*.lnk" "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Chrome Apps\*agentfront*.lnk") do (
    if exist "%%f" (
        set "AGENTFRONT_SHORTCUT=%%f"
        echo   [FOUND] %%f
    )
)

echo.

:: If no shortcut found, ask for URL
if "!AGENTFRONT_SHORTCUT!"=="" (
    echo No AgentFront.ai shortcut found automatically.
    echo.
    echo Please provide the AgentFront.ai URL or shortcut path:
    echo   Example URL: https://app.agentfront.ai
    echo   Example shortcut: C:\Users\YourName\Desktop\AgentFront.ai.lnk
    echo.
    set /p "AGENTFRONT_INPUT=URL or Path: "
    
    :: Check if it's a URL or path
    echo !AGENTFRONT_INPUT! | findstr /i "http" >nul
    if !errorLevel! equ 0 (
        set "AGENTFRONT_URL=!AGENTFRONT_INPUT!"
        echo   Using URL: !AGENTFRONT_URL!
    ) else (
        if exist "!AGENTFRONT_INPUT!" (
            set "AGENTFRONT_SHORTCUT=!AGENTFRONT_INPUT!"
            echo   Using shortcut: !AGENTFRONT_SHORTCUT!
        ) else (
            echo   [ERROR] File not found: !AGENTFRONT_INPUT!
            echo.
            echo Press any key to exit...
            pause >nul
            exit /b 1
        )
    )
)

echo.

:: ========================================
:: Create Launcher VBS Script (Full Screen / Kiosk Mode)
:: ========================================
echo Step 3: Creating full screen launcher...
echo.

set "LAUNCHER_VBS=%SCRIPT_DIR%_launch_agentfront.vbs"
echo   Creating: %LAUNCHER_VBS%

:: Determine launch method
if defined AGENTFRONT_URL (
    :: Launch Chrome with URL in kiosk mode
    echo   Mode: Chrome Kiosk with URL
    (
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo.
    echo ' Launch Chrome in kiosk mode with AgentFront.ai
    echo WshShell.Run """!CHROME_PATH!"" --kiosk --start-fullscreen ""!AGENTFRONT_URL!""", 1, False
    echo.
    echo Set WshShell = Nothing
    ) > "%LAUNCHER_VBS%"
) else (
    :: Launch using existing shortcut, then fullscreen
    echo   Mode: Shortcut with F11 fullscreen
    (
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo.
    echo ' Launch AgentFront.ai shortcut
    echo WshShell.Run """!AGENTFRONT_SHORTCUT!""", 1, False
    echo.
    echo ' Wait for app to load
    echo WScript.Sleep 4000
    echo.
    echo ' Try to maximize and go full screen with F11
    echo On Error Resume Next
    echo WshShell.AppActivate "AgentFront"
    echo WScript.Sleep 500
    echo WshShell.SendKeys "{F11}"
    echo.
    echo Set WshShell = Nothing
    ) > "%LAUNCHER_VBS%"
)

if exist "%LAUNCHER_VBS%" (
    echo   [OK] Launcher script created
    echo.
    echo   Contents:
    type "%LAUNCHER_VBS%"
    echo.
) else (
    echo   [ERROR] Failed to create launcher script
)
echo.

:: ========================================
:: Create Alternative Batch Launcher
:: ========================================
set "LAUNCHER_BAT=%SCRIPT_DIR%_launch_agentfront.bat"
echo   Also creating batch launcher: %LAUNCHER_BAT%

if defined AGENTFRONT_URL (
    (
    echo @echo off
    echo start "" "!CHROME_PATH!" --kiosk --start-fullscreen "!AGENTFRONT_URL!"
    ) > "%LAUNCHER_BAT%"
) else (
    (
    echo @echo off
    echo start "" "!AGENTFRONT_SHORTCUT!"
    echo timeout /t 4 /nobreak ^>nul
    echo :: Press F11 for fullscreen - this may not work from batch
    ) > "%LAUNCHER_BAT%"
)
echo   [OK] Batch launcher created
echo.

:: ========================================
:: Remove Existing Scheduled Task
:: ========================================
echo Step 4: Removing existing startup task...
schtasks /delete /tn "AgentFront_Startup" /f >nul 2>&1
echo   Done.
echo.

:: ========================================
:: Create Scheduled Task for Login
:: ========================================
echo Step 5: Creating startup task...
echo.

set "STARTUP_TASK_XML=%SCRIPT_DIR%_agentfront_startup.xml"
echo   Creating XML at: %STARTUP_TASK_XML%

(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Description^>Launch AgentFront.ai in full screen on login^</Description^>
echo   ^</RegistrationInfo^>
echo   ^<Triggers^>
echo     ^<LogonTrigger^>
echo       ^<Enabled^>true^</Enabled^>
echo       ^<Delay^>PT15S^</Delay^>
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

if exist "%STARTUP_TASK_XML%" (
    echo   [OK] XML file created
) else (
    echo   [ERROR] Failed to create XML file
)

:: Import the task
echo   Importing task to scheduler...
schtasks /create /tn "AgentFront_Startup" /xml "%STARTUP_TASK_XML%" /f
if %errorLevel% equ 0 (
    echo   [OK] Startup task created successfully
) else (
    echo   [WARNING] Task Scheduler failed, trying Startup folder...
    
    :: Fallback: Create shortcut in Startup folder
    set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
    
    powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('!STARTUP_FOLDER!\AgentFront.ai.lnk'); $s.TargetPath = 'wscript.exe'; $s.Arguments = '\"%LAUNCHER_VBS%\"'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.Save()"
    
    if exist "!STARTUP_FOLDER!\AgentFront.ai.lnk" (
        echo   [OK] Created startup shortcut in Startup folder
    ) else (
        echo   [ERROR] Failed to create startup shortcut
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
schtasks /query /tn "AgentFront_Startup" /fo list 2>nul | findstr "TaskName Status Next"
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
set /p "TEST_NOW=Test launch now? (Y/N): "
if /i "!TEST_NOW!"=="Y" (
    echo.
    echo Launching AgentFront.ai in full screen...
    echo.
    wscript.exe "%LAUNCHER_VBS%"
    echo.
    echo The app should be launching now.
    echo If using kiosk mode, press Alt+F4 to close.
)

echo.
echo ========================================
echo   Installation Complete
echo ========================================
echo.
echo AgentFront.ai will:
echo   - Launch automatically 15 seconds after Windows login
echo   - Open in full screen mode
echo.
if defined AGENTFRONT_URL (
echo Launch URL: !AGENTFRONT_URL!
echo Mode: Chrome Kiosk ^(true fullscreen, no UI^)
) else (
echo Shortcut: !AGENTFRONT_SHORTCUT!
echo Mode: Shortcut + F11 fullscreen
)
echo.
echo Launcher: %LAUNCHER_VBS%
echo.
echo To test manually:
echo   wscript.exe "%LAUNCHER_VBS%"
echo.
echo To remove auto-start:
echo   schtasks /delete /tn "AgentFront_Startup" /f
echo   del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AgentFront.ai.lnk"
echo.
echo ========================================
echo Press any key to exit...
pause >nul
