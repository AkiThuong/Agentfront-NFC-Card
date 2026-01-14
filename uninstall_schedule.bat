@echo off
setlocal enabledelayedexpansion

title PC Schedule Uninstaller

echo.
echo ========================================
echo   PC Schedule Uninstaller
echo ========================================
echo.
echo This will remove all AgentFront scheduled tasks:
echo   - Wake PC task (if exists)
echo   - Sleep PC task (if exists)
echo   - Shutdown PC task (if exists)
echo   - Test Sleep PC task (if exists)
echo   - Test Wake+Restart PC task (if exists)
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

:: ========================================
:: Remove Scheduled Tasks
:: ========================================
echo Removing scheduled tasks...
echo.

echo   Removing AgentFront_WakePC...
schtasks /delete /tn "AgentFront_WakePC" /f >nul 2>&1
if %errorLevel% equ 0 (
    echo   [OK] Removed
) else (
    echo   [SKIP] Not found
)

echo   Removing AgentFront_SleepPC...
schtasks /delete /tn "AgentFront_SleepPC" /f >nul 2>&1
if %errorLevel% equ 0 (
    echo   [OK] Removed
) else (
    echo   [SKIP] Not found
)

echo   Removing AgentFront_ShutdownPC...
schtasks /delete /tn "AgentFront_ShutdownPC" /f >nul 2>&1
if %errorLevel% equ 0 (
    echo   [OK] Removed
) else (
    echo   [SKIP] Not found
)

echo   Removing AgentFront_Test_SleepPC...
schtasks /delete /tn "AgentFront_Test_SleepPC" /f >nul 2>&1
if %errorLevel% equ 0 (
    echo   [OK] Removed
) else (
    echo   [SKIP] Not found
)

echo   Removing AgentFront_Test_WakeRestartPC...
schtasks /delete /tn "AgentFront_Test_WakeRestartPC" /f >nul 2>&1
if %errorLevel% equ 0 (
    echo   [OK] Removed
) else (
    echo   [SKIP] Not found
)

echo.

:: ========================================
:: Remove Helper Scripts and XML Files
:: ========================================
echo Removing helper files...
echo.

if exist "%SCRIPT_DIR%_sleep_pc.bat" (
    del "%SCRIPT_DIR%_sleep_pc.bat"
    echo   [OK] Removed _sleep_pc.bat
)

if exist "%SCRIPT_DIR%_shutdown_pc.bat" (
    del "%SCRIPT_DIR%_shutdown_pc.bat"
    echo   [OK] Removed _shutdown_pc.bat
)

if exist "%SCRIPT_DIR%_wake_task.xml" (
    del "%SCRIPT_DIR%_wake_task.xml"
    echo   [OK] Removed _wake_task.xml
)

if exist "%SCRIPT_DIR%_sleep_task.xml" (
    del "%SCRIPT_DIR%_sleep_task.xml"
    echo   [OK] Removed _sleep_task.xml
)

if exist "%SCRIPT_DIR%_shutdown_task.xml" (
    del "%SCRIPT_DIR%_shutdown_task.xml"
    echo   [OK] Removed _shutdown_task.xml
)

if exist "%SCRIPT_DIR%_test_sleep_pc.bat" (
    del "%SCRIPT_DIR%_test_sleep_pc.bat"
    echo   [OK] Removed _test_sleep_pc.bat
)

if exist "%SCRIPT_DIR%_test_restart_pc.bat" (
    del "%SCRIPT_DIR%_test_restart_pc.bat"
    echo   [OK] Removed _test_restart_pc.bat
)

if exist "%SCRIPT_DIR%_test_sleep_task.xml" (
    del "%SCRIPT_DIR%_test_sleep_task.xml"
    echo   [OK] Removed _test_sleep_task.xml
)

if exist "%SCRIPT_DIR%_test_wake_task.xml" (
    del "%SCRIPT_DIR%_test_wake_task.xml"
    echo   [OK] Removed _test_wake_task.xml
)

echo.

:: ========================================
:: Cancel any pending shutdown
:: ========================================
echo Canceling any pending shutdown...
shutdown /a >nul 2>&1
echo   [OK] Done
echo.

:: ========================================
:: Verify Removal
:: ========================================
echo ========================================
echo   Verification
echo ========================================
echo.

set "FOUND=0"

schtasks /query /tn "AgentFront_WakePC" >nul 2>&1
if %errorLevel% equ 0 (
    echo   [WARNING] AgentFront_WakePC still exists!
    set "FOUND=1"
)

schtasks /query /tn "AgentFront_SleepPC" >nul 2>&1
if %errorLevel% equ 0 (
    echo   [WARNING] AgentFront_SleepPC still exists!
    set "FOUND=1"
)

schtasks /query /tn "AgentFront_ShutdownPC" >nul 2>&1
if %errorLevel% equ 0 (
    echo   [WARNING] AgentFront_ShutdownPC still exists!
    set "FOUND=1"
)

schtasks /query /tn "AgentFront_Test_SleepPC" >nul 2>&1
if %errorLevel% equ 0 (
    echo   [WARNING] AgentFront_Test_SleepPC still exists!
    set "FOUND=1"
)

schtasks /query /tn "AgentFront_Test_WakeRestartPC" >nul 2>&1
if %errorLevel% equ 0 (
    echo   [WARNING] AgentFront_Test_WakeRestartPC still exists!
    set "FOUND=1"
)

if %FOUND% equ 0 (
    echo   [OK] All scheduled tasks removed successfully
)

echo.
echo ========================================
echo   Uninstall Complete
echo ========================================
echo.
echo All AgentFront schedule tasks have been removed.
echo.
echo Press any key to exit...
pause >nul
