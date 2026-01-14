@echo off
setlocal enabledelayedexpansion

title Official 8AM-6PM Schedule Installer

echo.
echo ========================================
echo   Official 8AM-6PM Schedule Installer
echo ========================================
echo.
echo This will configure your PC to:
echo   - Wake at 8:00 AM and restart (Mon-Fri)
echo   - Sleep at 6:00 PM (Mon-Fri)
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
:: Step 1: Enable wake timers
:: ========================================
echo Step 1: Enabling wake timers in power settings...
powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /SETACTIVE SCHEME_CURRENT
echo   [OK] Wake timers enabled
echo.

:: ========================================
:: Step 2: Disable hibernation
:: ========================================
echo Step 2: Disabling hibernation (ensures proper sleep)...
powercfg /hibernate off
echo   [OK] Hibernation disabled
echo.

:: ========================================
:: Step 3: Create Wake + Restart Task (8:00 AM)
:: ========================================
echo Step 3: Creating Wake + Restart task for 8:00 AM (Mon-Fri)...
echo.

:: Remove existing task if exists
echo   Removing existing task...
schtasks /delete /tn "AgentFront_Official_WakeRestart" /f >nul 2>&1

:: Create restart script
set "RESTART_SCRIPT=%SCRIPT_DIR%_official_restart_pc.bat"
echo   Creating restart script at: %RESTART_SCRIPT%

(
echo @echo off
echo :: Restart PC after wake
echo echo PC woke up at 8:00 AM! Restarting in 10 seconds...
echo timeout /t 10 /nobreak
echo shutdown /r /f /t 0 /c "Scheduled restart at 8:00 AM"
) > "%RESTART_SCRIPT%"

if exist "%RESTART_SCRIPT%" (
    echo   [OK] Restart script created
) else (
    echo   [ERROR] Failed to create restart script
)

:: Create XML for wake+restart task
set "WAKE_TASK_XML=%SCRIPT_DIR%_official_wake_task.xml"
echo   Creating task XML at: %WAKE_TASK_XML%

(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Description^>Wake PC and Restart at 8:00 AM Mon-Fri^</Description^>
echo   ^</RegistrationInfo^>
echo   ^<Triggers^>
echo     ^<CalendarTrigger^>
echo       ^<StartBoundary^>2024-01-01T08:00:00^</StartBoundary^>
echo       ^<Enabled^>true^</Enabled^>
echo       ^<ScheduleByWeek^>
echo         ^<DaysOfWeek^>
echo           ^<Monday /^>
echo           ^<Tuesday /^>
echo           ^<Wednesday /^>
echo           ^<Thursday /^>
echo           ^<Friday /^>
echo         ^</DaysOfWeek^>
echo         ^<WeeksInterval^>1^</WeeksInterval^>
echo       ^</ScheduleByWeek^>
echo     ^</CalendarTrigger^>
echo   ^</Triggers^>
echo   ^<Principals^>
echo     ^<Principal id="Author"^>
echo       ^<UserId^>S-1-5-18^</UserId^>
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
echo     ^<WakeToRun^>true^</WakeToRun^>
echo     ^<ExecutionTimeLimit^>PT5M^</ExecutionTimeLimit^>
echo   ^</Settings^>
echo   ^<Actions Context="Author"^>
echo     ^<Exec^>
echo       ^<Command^>%RESTART_SCRIPT%^</Command^>
echo       ^<WorkingDirectory^>%SCRIPT_DIR%^</WorkingDirectory^>
echo     ^</Exec^>
echo   ^</Actions^>
echo ^</Task^>
) > "%WAKE_TASK_XML%"

if exist "%WAKE_TASK_XML%" (
    echo   [OK] XML file created
) else (
    echo   [ERROR] Failed to create XML file
)

:: Import the wake+restart task
echo   Importing task to scheduler...
schtasks /create /tn "AgentFront_Official_WakeRestart" /xml "%WAKE_TASK_XML%" /f
if %errorLevel% equ 0 (
    echo   [OK] Wake + Restart task created successfully
) else (
    echo   [ERROR] Failed to create wake+restart task (Error: %errorLevel%)
)
echo.

:: ========================================
:: Step 4: Create Sleep Task (6:00 PM)
:: ========================================
echo Step 4: Creating Sleep task for 6:00 PM (Mon-Fri)...
echo.

:: Remove existing task if exists
echo   Removing existing task...
schtasks /delete /tn "AgentFront_Official_Sleep" /f >nul 2>&1

:: Create sleep script
set "SLEEP_SCRIPT=%SCRIPT_DIR%_official_sleep_pc.bat"
echo   Creating sleep script at: %SLEEP_SCRIPT%

(
echo @echo off
echo :: Put PC to sleep at 6:00 PM
echo echo PC will sleep in 60 seconds. Save your work!
echo msg * "PC will sleep in 60 seconds. Save your work!" 2^>nul
echo timeout /t 60 /nobreak
echo echo Putting PC to sleep now...
echo powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)"
) > "%SLEEP_SCRIPT%"

if exist "%SLEEP_SCRIPT%" (
    echo   [OK] Sleep script created
) else (
    echo   [ERROR] Failed to create sleep script
)

:: Create XML for sleep task
set "SLEEP_TASK_XML=%SCRIPT_DIR%_official_sleep_task.xml"
echo   Creating task XML at: %SLEEP_TASK_XML%

(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Description^>Sleep PC at 6:00 PM Mon-Fri^</Description^>
echo   ^</RegistrationInfo^>
echo   ^<Triggers^>
echo     ^<CalendarTrigger^>
echo       ^<StartBoundary^>2024-01-01T18:00:00^</StartBoundary^>
echo       ^<Enabled^>true^</Enabled^>
echo       ^<ScheduleByWeek^>
echo         ^<DaysOfWeek^>
echo           ^<Monday /^>
echo           ^<Tuesday /^>
echo           ^<Wednesday /^>
echo           ^<Thursday /^>
echo           ^<Friday /^>
echo         ^</DaysOfWeek^>
echo         ^<WeeksInterval^>1^</WeeksInterval^>
echo       ^</ScheduleByWeek^>
echo     ^</CalendarTrigger^>
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
echo     ^<StartWhenAvailable^>false^</StartWhenAvailable^>
echo     ^<RunOnlyIfNetworkAvailable^>false^</RunOnlyIfNetworkAvailable^>
echo     ^<AllowStartOnDemand^>true^</AllowStartOnDemand^>
echo     ^<Enabled^>true^</Enabled^>
echo     ^<Hidden^>false^</Hidden^>
echo     ^<ExecutionTimeLimit^>PT5M^</ExecutionTimeLimit^>
echo   ^</Settings^>
echo   ^<Actions Context="Author"^>
echo     ^<Exec^>
echo       ^<Command^>%SLEEP_SCRIPT%^</Command^>
echo       ^<WorkingDirectory^>%SCRIPT_DIR%^</WorkingDirectory^>
echo     ^</Exec^>
echo   ^</Actions^>
echo ^</Task^>
) > "%SLEEP_TASK_XML%"

if exist "%SLEEP_TASK_XML%" (
    echo   [OK] XML file created
) else (
    echo   [ERROR] Failed to create XML file
)

:: Import the sleep task
echo   Importing task to scheduler...
schtasks /create /tn "AgentFront_Official_Sleep" /xml "%SLEEP_TASK_XML%" /f
if %errorLevel% equ 0 (
    echo   [OK] Sleep task created successfully
) else (
    echo   [ERROR] Failed to create sleep task (Error: %errorLevel%)
)
echo.

:: ========================================
:: Verify Tasks
:: ========================================
echo ========================================
echo   Scheduled Tasks Status
echo ========================================
echo.
echo Wake + Restart Task (8:00 AM):
schtasks /query /tn "AgentFront_Official_WakeRestart" /fo list 2>nul | findstr "TaskName Status Next"
if %errorLevel% neq 0 echo   [NOT FOUND]
echo.

echo Sleep Task (6:00 PM):
schtasks /query /tn "AgentFront_Official_Sleep" /fo list 2>nul | findstr "TaskName Status Next"
if %errorLevel% neq 0 echo   [NOT FOUND]
echo.

echo ========================================
echo   Installation Complete
echo ========================================
echo.
echo Official Schedule (Monday-Friday):
echo   - 8:00 AM: PC wakes up and restarts
echo   - 6:00 PM: PC sleeps (60 second warning)
echo.
echo To cancel a pending sleep:
echo   Press Ctrl+C during the 60 second countdown
echo.
echo To remove these tasks:
echo   schtasks /delete /tn "AgentFront_Official_WakeRestart" /f
echo   schtasks /delete /tn "AgentFront_Official_Sleep" /f
echo.
echo ========================================
echo Press any key to exit...
pause >nul
