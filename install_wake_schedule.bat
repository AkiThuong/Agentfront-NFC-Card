@echo off
setlocal enabledelayedexpansion

title PC Wake & Shutdown Schedule Installer

echo.
echo ========================================
echo   PC Wake ^& Shutdown Schedule Installer
echo ========================================
echo.
echo This will configure your PC to:
echo   - Wake at 8:00 AM (Monday-Friday)
echo   - Shutdown at 8:00 PM (Monday-Friday)
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
:: Create Wake PC Task (8:00 AM)
:: ========================================
echo Step 1: Creating Wake PC task for 8:00 AM...
echo.

:: Remove existing task if exists
echo   Removing existing task...
schtasks /delete /tn "AgentFront_WakePC" /f >nul 2>&1

:: Create wake script
set "WAKE_SCRIPT=%SCRIPT_DIR%_wake_pc.bat"
echo   Creating wake script at: %WAKE_SCRIPT%

(
echo @echo off
echo :: This script runs when PC wakes up
echo echo PC woke up at %%date%% %%time%% ^>^> "%SCRIPT_DIR%wake_log.txt"
) > "%WAKE_SCRIPT%"

if exist "%WAKE_SCRIPT%" (
    echo   [OK] Wake script created
) else (
    echo   [ERROR] Failed to create wake script
)

:: Create XML for wake task
set "WAKE_TASK_XML=%SCRIPT_DIR%_wake_task.xml"
echo   Creating task XML at: %WAKE_TASK_XML%

(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Description^>Wake PC for AgentFront at 8:00 AM^</Description^>
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
echo     ^<WakeToRun^>true^</WakeToRun^>
echo   ^</Settings^>
echo   ^<Actions Context="Author"^>
echo     ^<Exec^>
echo       ^<Command^>%WAKE_SCRIPT%^</Command^>
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
:: Create Shutdown PC Task (8:00 PM)
:: ========================================
echo Step 2: Creating Shutdown PC task for 8:00 PM...
echo.

:: Remove existing task if exists
echo   Removing existing task...
schtasks /delete /tn "AgentFront_SleepPC" /f >nul 2>&1
schtasks /delete /tn "AgentFront_ShutdownPC" /f >nul 2>&1

:: Create shutdown script
set "SHUTDOWN_SCRIPT=%SCRIPT_DIR%_shutdown_pc.bat"
echo   Creating shutdown script at: %SHUTDOWN_SCRIPT%

(
echo @echo off
echo :: Give user 60 seconds warning before shutdown
echo msg * "PC will shutdown in 60 seconds. Save your work!" 2^>nul
echo shutdown /s /f /t 60 /c "Scheduled shutdown at 8:00 PM"
) > "%SHUTDOWN_SCRIPT%"

if exist "%SHUTDOWN_SCRIPT%" (
    echo   [OK] Shutdown script created
) else (
    echo   [ERROR] Failed to create shutdown script
)

:: Create XML for shutdown task
set "SHUTDOWN_TASK_XML=%SCRIPT_DIR%_shutdown_task.xml"
echo   Creating task XML at: %SHUTDOWN_TASK_XML%

(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Description^>Shutdown PC for AgentFront at 8:00 PM^</Description^>
echo   ^</RegistrationInfo^>
echo   ^<Triggers^>
echo     ^<CalendarTrigger^>
echo       ^<StartBoundary^>2024-01-01T20:00:00^</StartBoundary^>
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
echo       ^<Command^>%SHUTDOWN_SCRIPT%^</Command^>
echo       ^<WorkingDirectory^>%SCRIPT_DIR%^</WorkingDirectory^>
echo     ^</Exec^>
echo   ^</Actions^>
echo ^</Task^>
) > "%SHUTDOWN_TASK_XML%"

if exist "%SHUTDOWN_TASK_XML%" (
    echo   [OK] XML file created
) else (
    echo   [ERROR] Failed to create XML file
)

:: Import the shutdown task
echo   Importing task to scheduler...
schtasks /create /tn "AgentFront_ShutdownPC" /xml "%SHUTDOWN_TASK_XML%" /f
if %errorLevel% equ 0 (
    echo   [OK] Shutdown PC task created successfully
) else (
    echo   [ERROR] Failed to create shutdown task (Error: %errorLevel%)
)
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
echo Shutdown Task (8:00 PM):
schtasks /query /tn "AgentFront_ShutdownPC" /fo list 2>nul | findstr "TaskName Status Next"
if %errorLevel% neq 0 echo   [NOT FOUND]
echo.

echo ========================================
echo   Installation Complete
echo ========================================
echo.
echo Schedule:
echo   - PC wakes at 8:00 AM (Mon-Fri)
echo   - PC shuts down at 8:00 PM (Mon-Fri)
echo.
echo Note: Wake-to-run requires BIOS/UEFI wake timer support.
echo Users will get a 60-second warning before shutdown.
echo.
echo To cancel a pending shutdown:
echo   shutdown /a
echo.
echo To remove these tasks:
echo   schtasks /delete /tn "AgentFront_WakePC" /f
echo   schtasks /delete /tn "AgentFront_ShutdownPC" /f
echo.
echo ========================================
echo Press any key to exit...
pause >nul
