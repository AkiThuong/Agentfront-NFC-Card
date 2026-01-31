@echo off
title Shutdown Test - 1 Minute Countdown

echo.
echo ========================================
echo   SHUTDOWN TEST - 1 MINUTE COUNTDOWN
echo ========================================
echo.
echo WARNING: This will shutdown the PC in 60 seconds!
echo.
echo Press any key to START the countdown...
echo Or close this window to cancel.
pause >nul

echo.
echo Starting shutdown countdown...
echo.

:: Show warning message
msg * "PC will shutdown in 60 seconds. Save your work!" 2>nul

:: Shutdown with 60 second delay
shutdown /s /f /t 60 /c "Test shutdown - 1 minute countdown"

echo.
echo ========================================
echo   Shutdown scheduled in 60 seconds!
echo ========================================
echo.
echo To CANCEL the shutdown, run:
echo   shutdown /a
echo.
echo Or press any key to open a new window and cancel...
pause >nul

:: Cancel the shutdown
shutdown /a
echo.
echo Shutdown CANCELLED!
pause

