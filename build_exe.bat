@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Build Executable
echo ========================================
echo.
echo Current directory: %CD%
echo.

:: Check if Python is available
echo Checking Python...
where python >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo [ERROR] Python not found in PATH!
    echo Please install Python 3.9+ from python.org
    echo Make sure to check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)

python --version
echo.

:: Check if venv exists and activate
echo Looking for virtual environment...
if exist "venv313\Scripts\activate.bat" (
    echo Found venv313, activating...
    call "venv313\Scripts\activate.bat"
    if %errorLevel% neq 0 (
        echo [ERROR] Failed to activate venv313
        pause
        exit /b 1
    )
    echo Activated: venv313
) else if exist "venv\Scripts\activate.bat" (
    echo Found venv, activating...
    call "venv\Scripts\activate.bat"
    if %errorLevel% neq 0 (
        echo [ERROR] Failed to activate venv
        pause
        exit /b 1
    )
    echo Activated: venv
) else (
    echo No virtual environment found, creating one...
    python -m venv venv
    if %errorLevel% neq 0 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    call "venv\Scripts\activate.bat"
    echo Created and activated: venv
)

echo.
echo Python being used:
where python
python --version
echo.

:: Install/upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip

:: Install dependencies
echo.
echo Installing dependencies from requirements.txt...
pip install -r requirements.txt
if %errorLevel% neq 0 (
    echo [WARNING] Some dependencies may have failed to install
)

:: Install PyInstaller
echo.
echo Checking PyInstaller...
pip show pyinstaller >nul 2>&1
if %errorLevel% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
    if %errorLevel% neq 0 (
        echo [ERROR] Failed to install PyInstaller
        pause
        exit /b 1
    )
)
echo PyInstaller is ready.

:: Run build script
echo.
echo ========================================
echo   Starting Build Process
echo ========================================
echo.

python build.py
set BUILD_RESULT=%errorLevel%

echo.
echo ========================================
if %BUILD_RESULT% equ 0 (
    if exist "dist\nfc_server.exe" (
        echo   BUILD SUCCESSFUL!
        echo ========================================
        echo.
        echo Files created in 'dist' folder:
        echo.
        dir /b dist
        echo.
        echo ----------------------------------------
        echo Next steps:
        echo   1. Copy the 'dist' folder to target PC
        echo   2. Run 'install.bat' as Administrator
        echo ----------------------------------------
    ) else (
        echo   BUILD COMPLETED but no exe found
        echo ========================================
        echo Check the output above for warnings.
    )
) else (
    echo   BUILD FAILED!
    echo ========================================
    echo Check the error messages above.
)
echo.
echo Press any key to exit...
pause >nul

