@echo off
setlocal enabledelayedexpansion

title PC Wake/Sleep Schedule Installer

echo.
echo ========================================
echo   PC Wake/Sleep Schedule Installer
echo ========================================
echo.
echo This will configure your PC to:
echo   - Wake up at 8:00 AM (Monday-Friday)
echo   - Sleep at 6:00 PM (Monday-Friday)
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
:: Create Wake PC Task (8 AM)
:: ========================================
echo Step 1: Creating Wake PC task for 8:00 AM...
echo.

:: Remove existing task if exists
echo   Removing existing task...
schtasks /delete /tn "AgentFront_WakePC" /f >nul 2>&1

:: Create XML for wake task with wake timer enabled
set "WAKE_TASK_XML=%SCRIPT_DIR%_wake_task.xml"
echo   Creating task XML at: %WAKE_TASK_XML%

(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Description^>Wake PC for AgentFront at 8 AM^</Description^>
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
echo     ^<ExecutionTimeLimit^>PT1M^</ExecutionTimeLimit^>
echo   ^</Settings^>
echo   ^<Actions Context="Author"^>
echo     ^<Exec^>
echo       ^<Command^>cmd.exe^</Command^>
echo       ^<Arguments^>/c echo PC Woken at 8 AM^</Arguments^>
echo     ^</Exec^>
echo   ^</Actions^>
echo ^</Task^>
) > "%WAKE_TASK_XML%"

if exist "%WAKE_TASK_XML%" (
    echo   [OK] XML file created
) else (
    echo   [ERROR] Failed to create XML file
)

:: Import the wake task
echo   Importing task to scheduler...
schtasks /create /tn "AgentFront_WakePC" /xml "%WAKE_TASK_XML%" /f
if %errorLevel% equ 0 (
    echo   [OK] Wake PC task created successfully
) else (
    echo   [ERROR] Failed to create wake task (Error: %errorLevel%)
)
echo.

:: ========================================
:: Create Sleep PC Task (6 PM)
:: ========================================
echo Step 2: Creating Sleep PC task for 6:00 PM...
echo.

:: Remove existing task if exists
echo   Removing existing task...
schtasks /delete /tn "AgentFront_SleepPC" /f >nul 2>&1

:: Create sleep script
set "SLEEP_SCRIPT=%SCRIPT_DIR%_sleep_pc.bat"
echo   Creating sleep script at: %SLEEP_SCRIPT%

(
echo @echo off
echo :: Give user 60 seconds warning before sleep
echo msg * "PC will go to sleep in 60 seconds. Save your work!" 2^>nul
echo timeout /t 60 /nobreak
echo rundll32.exe powrprof.dll,SetSuspendState 0,1,0
) > "%SLEEP_SCRIPT%"

if exist "%SLEEP_SCRIPT%" (
    echo   [OK] Sleep script created
) else (
    echo   [ERROR] Failed to create sleep script
)

:: Create XML for sleep task
set "SLEEP_TASK_XML=%SCRIPT_DIR%_sleep_task.xml"
echo   Creating task XML at: %SLEEP_TASK_XML%

(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Description^>Put PC to sleep for AgentFront at 6 PM^</Description^>
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
schtasks /create /tn "AgentFront_SleepPC" /xml "%SLEEP_TASK_XML%" /f
if %errorLevel% equ 0 (
    echo   [OK] Sleep PC task created successfully
) else (
    echo   [ERROR] Failed to create sleep task (Error: %errorLevel%)
)
echo.

:: ========================================
:: Enable Wake Timers in Power Settings
:: ========================================
echo Step 3: Enabling wake timers in power settings...
powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /SETACTIVE SCHEME_CURRENT
echo   [OK] Wake timers enabled
echo.

:: ========================================
:: Verify Tasks
:: ========================================
echo ========================================
echo   Scheduled Tasks Status
echo ========================================
echo.
echo Wake Task (8:00 AM):
schtasks /query /tn "AgentFront_WakePC" /fo list 2>nul | findstr "TaskName Status Next"
if %errorLevel% neq 0 echo   [NOT FOUND]
echo.
echo Sleep Task (6:00 PM):
schtasks /query /tn "AgentFront_SleepPC" /fo list 2>nul | findstr "TaskName Status Next"
if %errorLevel% neq 0 echo   [NOT FOUND]
echo.

echo ========================================
echo   Installation Complete
echo ========================================
echo.
echo Schedule:
echo   - PC wakes at 8:00 AM (Mon-Fri)
echo   - PC sleeps at 6:00 PM (Mon-Fri)
echo.
echo IMPORTANT: For wake to work:
echo   1. Your BIOS must support wake timers
echo   2. Wake timers must be enabled in BIOS
echo   3. PC must be in Sleep mode (not Shutdown)
echo.
echo To remove these tasks:
echo   schtasks /delete /tn "AgentFront_WakePC" /f
echo   schtasks /delete /tn "AgentFront_SleepPC" /f
echo.
echo ========================================
echo Press any key to exit...
pause >nul
