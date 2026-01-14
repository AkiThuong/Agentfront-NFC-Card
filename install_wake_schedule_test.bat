@echo off
setlocal enabledelayedexpansion

title PC Sleep/Wake Test Schedule Installer

echo.
echo ========================================
echo   PC Sleep/Wake Test Schedule Installer
echo ========================================
echo.
echo This will configure your PC to:
echo   - Sleep at 7:25 PM
echo   - Wake at 7:27 PM and restart immediately
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
:: Step 1: Create Sleep PC Task (7:25 PM)
:: ========================================
echo Step 1: Creating Sleep PC task for 7:25 PM...
echo.

:: Remove existing task if exists
echo   Removing existing task...
schtasks /delete /tn "AgentFront_Test_SleepPC" /f >nul 2>&1

:: Create sleep script
set "SLEEP_SCRIPT=%SCRIPT_DIR%_test_sleep_pc.bat"
echo   Creating sleep script at: %SLEEP_SCRIPT%

(
echo @echo off
echo :: Put PC to sleep using PowerShell
echo echo Putting PC to sleep in 10 seconds...
echo timeout /t 10 /nobreak
echo :: Use PowerShell for reliable sleep ^(not hibernate/shutdown^)
echo powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)"
) > "%SLEEP_SCRIPT%"

if exist "%SLEEP_SCRIPT%" (
    echo   [OK] Sleep script created
) else (
    echo   [ERROR] Failed to create sleep script
)

:: Create XML for sleep task
set "SLEEP_TASK_XML=%SCRIPT_DIR%_test_sleep_task.xml"
echo   Creating task XML at: %SLEEP_TASK_XML%

(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Description^>Sleep PC for AgentFront Test at 7:25 PM^</Description^>
echo   ^</RegistrationInfo^>
echo   ^<Triggers^>
echo     ^<CalendarTrigger^>
echo       ^<StartBoundary^>2024-01-01T19:25:00^</StartBoundary^>
echo       ^<Enabled^>true^</Enabled^>
echo       ^<ScheduleByDay^>
echo         ^<DaysInterval^>1^</DaysInterval^>
echo       ^</ScheduleByDay^>
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
schtasks /create /tn "AgentFront_Test_SleepPC" /xml "%SLEEP_TASK_XML%" /f
if %errorLevel% equ 0 (
    echo   [OK] Sleep PC task created successfully
) else (
    echo   [ERROR] Failed to create sleep task (Error: %errorLevel%)
)
echo.

:: ========================================
:: Step 2: Create Wake + Restart PC Task (7:27 PM)
:: ========================================
echo Step 2: Creating Wake + Restart PC task for 7:27 PM...
echo.

:: Remove existing task if exists
echo   Removing existing task...
schtasks /delete /tn "AgentFront_Test_WakeRestartPC" /f >nul 2>&1

:: Create restart script
set "RESTART_SCRIPT=%SCRIPT_DIR%_test_restart_pc.bat"
echo   Creating restart script at: %RESTART_SCRIPT%

(
echo @echo off
echo :: Restart PC immediately after wake
echo echo PC woke up! Restarting in 5 seconds...
echo timeout /t 5 /nobreak
echo shutdown /r /f /t 0 /c "Scheduled restart after wake"
) > "%RESTART_SCRIPT%"

if exist "%RESTART_SCRIPT%" (
    echo   [OK] Restart script created
) else (
    echo   [ERROR] Failed to create restart script
)

:: Create XML for wake+restart task with WakeToRun enabled
set "WAKE_TASK_XML=%SCRIPT_DIR%_test_wake_task.xml"
echo   Creating task XML at: %WAKE_TASK_XML%

(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Description^>Wake PC and Restart for AgentFront Test at 7:27 PM^</Description^>
echo   ^</RegistrationInfo^>
echo   ^<Triggers^>
echo     ^<CalendarTrigger^>
echo       ^<StartBoundary^>2024-01-01T19:27:00^</StartBoundary^>
echo       ^<Enabled^>true^</Enabled^>
echo       ^<ScheduleByDay^>
echo         ^<DaysInterval^>1^</DaysInterval^>
echo       ^</ScheduleByDay^>
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
schtasks /create /tn "AgentFront_Test_WakeRestartPC" /xml "%WAKE_TASK_XML%" /f
if %errorLevel% equ 0 (
    echo   [OK] Wake + Restart PC task created successfully
) else (
    echo   [ERROR] Failed to create wake+restart task (Error: %errorLevel%)
)
echo.

:: ========================================
:: Verify Tasks
:: ========================================
echo ========================================
echo   Scheduled Tasks Status
echo ========================================
echo.
echo Sleep Task (7:25 PM):
schtasks /query /tn "AgentFront_Test_SleepPC" /fo list 2>nul | findstr "TaskName Status Next"
if %errorLevel% neq 0 echo   [NOT FOUND]
echo.

echo Wake + Restart Task (7:27 PM):
schtasks /query /tn "AgentFront_Test_WakeRestartPC" /fo list 2>nul | findstr "TaskName Status Next"
if %errorLevel% neq 0 echo   [NOT FOUND]
echo.

:: ========================================
:: Important: Enable Wake Timers in Power Settings
:: ========================================
echo ========================================
echo   IMPORTANT: Power Settings Required
echo ========================================
echo.
echo For wake from sleep to work, ensure:
echo   1. Wake timers are enabled in Power Options
echo   2. BIOS/UEFI has "Wake on RTC" or similar enabled
echo.
echo Enabling wake timers now...
powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /SETACTIVE SCHEME_CURRENT
echo   [OK] Wake timers enabled
echo.
echo Disabling hibernation to ensure proper sleep...
powercfg /hibernate off
echo   [OK] Hibernation disabled (sleep will work correctly now)
echo.

echo ========================================
echo   Installation Complete
echo ========================================
echo.
echo Test Schedule:
echo   - PC sleeps at 7:25 PM
echo   - PC wakes at 7:27 PM and restarts immediately
echo.
echo To remove these test tasks:
echo   schtasks /delete /tn "AgentFront_Test_SleepPC" /f
echo   schtasks /delete /tn "AgentFront_Test_WakeRestartPC" /f
echo.
echo ========================================
echo Press any key to exit...
pause >nul
