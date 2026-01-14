@echo off
setlocal enabledelayedexpansion

title Quick Sleep/Wake/Restart Test

echo.
echo ========================================
echo   Quick Sleep/Wake/Restart Test
echo ========================================
echo.
echo This will test the sleep/wake/restart flow:
echo   1. PC sleeps in 10 seconds
echo   2. PC wakes after 1 minute
echo   3. PC restarts immediately after wake
echo.
echo TOTAL TEST TIME: ~1 minute 15 seconds
echo.
echo Press any key to start the test...
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

:: ========================================
:: Step 1: Enable wake timers
:: ========================================
echo Step 1: Enabling wake timers...
powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /SETACTIVE SCHEME_CURRENT
echo   [OK] Wake timers enabled
echo.

:: ========================================
:: Step 2: Disable hibernation
:: ========================================
echo Step 2: Disabling hibernation...
powercfg /hibernate off
echo   [OK] Hibernation disabled
echo.

:: ========================================
:: Step 3: Create wake task (1 minute from now)
:: ========================================
echo Step 3: Creating wake task for 1 minute from now...

:: Calculate wake time (current time + 1 minute)
for /f "tokens=1-3 delims=:" %%a in ("%TIME%") do (
    set /a "hour=%%a"
    set /a "min=%%b + 1"
    set /a "sec=%%c"
)

:: Handle minute overflow
if !min! geq 60 (
    set /a "min=!min! - 60"
    set /a "hour=!hour! + 1"
)

:: Handle hour overflow
if !hour! geq 24 (
    set /a "hour=!hour! - 24"
)

:: Format with leading zeros
if !hour! lss 10 set "hour=0!hour!"
if !min! lss 10 set "min=0!min!"

set "WAKE_TIME=!hour!:!min!:00"
echo   Wake scheduled for: !WAKE_TIME!

:: Remove existing test wake task
schtasks /delete /tn "AgentFront_QuickTest_Wake" /f >nul 2>&1

:: Create restart script
set "RESTART_SCRIPT=%SCRIPT_DIR%_quicktest_restart.bat"
(
echo @echo off
echo echo PC woke up! Restarting in 5 seconds...
echo timeout /t 5 /nobreak
echo shutdown /r /f /t 0 /c "Test restart after wake"
) > "%RESTART_SCRIPT%"

:: Get today's date in correct format
for /f "tokens=2 delims==" %%a in ('wmic os get localdatetime /value') do set "dt=%%a"
set "TODAY=%dt:~0,4%-%dt:~4,2%-%dt:~6,2%"

:: Create XML for wake task
set "WAKE_XML=%SCRIPT_DIR%_quicktest_wake.xml"
(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Description^>Quick test wake and restart^</Description^>
echo   ^</RegistrationInfo^>
echo   ^<Triggers^>
echo     ^<TimeTrigger^>
echo       ^<StartBoundary^>!TODAY!T!WAKE_TIME!^</StartBoundary^>
echo       ^<Enabled^>true^</Enabled^>
echo     ^</TimeTrigger^>
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
echo       ^<Command^>!RESTART_SCRIPT!^</Command^>
echo       ^<WorkingDirectory^>%SCRIPT_DIR%^</WorkingDirectory^>
echo     ^</Exec^>
echo   ^</Actions^>
echo ^</Task^>
) > "%WAKE_XML%"

:: Import the wake task
schtasks /create /tn "AgentFront_QuickTest_Wake" /xml "%WAKE_XML%" /f >nul 2>&1
if %errorLevel% equ 0 (
    echo   [OK] Wake task created
) else (
    echo   [ERROR] Failed to create wake task
    echo   Press any key to exit...
    pause >nul
    exit /b 1
)
echo.

:: ========================================
:: Step 4: Put PC to sleep
:: ========================================
echo ========================================
echo   Starting Test
echo ========================================
echo.
echo PC will sleep in 10 seconds...
echo Wake scheduled for: !WAKE_TIME! (in ~1 minute)
echo After wake: PC will restart immediately
echo.
echo Press Ctrl+C to cancel...
echo.

timeout /t 10

echo.
echo Putting PC to sleep NOW...
echo.

:: Use PowerShell for reliable sleep
powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)"
