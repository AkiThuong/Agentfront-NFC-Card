@echo off
echo ========================================
echo   NFC Bridge Server - Build Executable
echo ========================================
echo.

:: Check if Python is available
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo Python not found! Please install Python 3.9+
    pause
    exit /b 1
)

:: Check if venv exists
if exist "venv\Scripts\activate.bat" (
    echo Using existing virtual environment...
    call venv\Scripts\activate.bat
) else if exist "venv313\Scripts\activate.bat" (
    echo Using existing virtual environment (Python 3.13)...
    call venv313\Scripts\activate.bat
) else (
    echo Creating virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
)

:: Install dependencies
echo.
echo Installing dependencies...
pip install -r requirements.txt

:: Install PyInstaller if not present
pip show pyinstaller >nul 2>&1
if %errorLevel% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

:: Run build script
echo.
echo Building executables...
python build.py

echo.
echo ========================================
if exist "dist\nfc_server.exe" (
    echo Build successful!
    echo.
    echo Files created in 'dist' folder:
    dir /b dist
    echo.
    echo To install as Windows service:
    echo   1. Open Command Prompt as Administrator
    echo   2. cd to dist folder
    echo   3. Run: install.bat
) else (
    echo Build failed! Check the output above for errors.
)
echo ========================================
pause

