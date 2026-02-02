@echo off
echo ========================================
echo   Checking Port 3005 Status
echo ========================================
echo.

echo [Checking netstat for port 3005...]
netstat -ano | findstr :3005

if %errorLevel% neq 0 (
    echo.
    echo [OK] Port 3005 is NOT in use - no server running
) else (
    echo.
    echo [!] Port 3005 IS IN USE
    echo.
    echo To kill the process, run as Administrator:
    echo   taskkill /PID ^<PID_NUMBER^> /F
)

echo.
echo [Checking for NFC Bridge Windows Service...]
sc query NFCBridgeService 2>nul | findstr STATE

if %errorLevel% neq 0 (
    echo   [OK] No NFCBridgeService found
) else (
    echo   [!] Service exists - run uninstall_service.bat as Admin
)

echo.
echo [Checking for Python processes...]
tasklist | findstr python

if %errorLevel% neq 0 (
    echo   [OK] No Python processes running
)

echo.
pause

