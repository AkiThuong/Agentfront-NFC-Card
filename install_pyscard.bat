@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge - Install pyscard
echo ========================================
echo.

:: Check if venv exists
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Please run start_server.bat first to set up.
    pause
    exit /b 1
)

:: Activate venv
call "venv\Scripts\activate.bat"

echo Trying binary wheel first...
pip install --only-binary :all: pyscard
if %errorLevel% equ 0 (
    echo.
    echo pyscard installed successfully!
    goto :success
)

echo.
echo [INFO] No binary wheel available for your Python version.
echo Trying to build from source...
echo.

pip install pyscard
if %errorLevel% equ 0 (
    echo.
    echo pyscard built and installed successfully!
    goto :success
)

echo.
echo ========================================
echo   pyscard Installation Failed
echo ========================================
echo.
echo pyscard requires Visual C++ Build Tools to compile.
echo.
echo Option 1: Install Visual C++ Build Tools
echo   https://visualstudio.microsoft.com/visual-cpp-build-tools/
echo   Then run this script again.
echo.
echo Option 2: Use a pre-built wheel (if available)
echo   Download from: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyscard
echo   Then: pip install pyscard-X.X.X-cpXXX-win_amd64.whl
echo.
pause
exit /b 1

:success
echo.
echo ========================================
echo   pyscard Installed Successfully!
echo ========================================
echo.
echo Restart the server to enable NFC reading:
echo   1. Stop the current server (Ctrl+C)
echo   2. Run start_server.bat again
echo.
pause
