@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Build Executable
echo ========================================
echo.
echo Current directory: %CD%
echo.

:: Required Python version
set REQUIRED_MAJOR=3
set REQUIRED_MINOR=13

:: Check if Python 3.13 is available via py launcher
echo Checking for Python %REQUIRED_MAJOR%.%REQUIRED_MINOR%...

py -%REQUIRED_MAJOR%.%REQUIRED_MINOR% --version >nul 2>&1
if %errorLevel% equ 0 (
    for /f "tokens=2 delims= " %%v in ('py -%REQUIRED_MAJOR%.%REQUIRED_MINOR% --version 2^>^&1') do set PYVER=%%v
    echo Found Python !PYVER! via py launcher
    set PYTHON_CMD=py -%REQUIRED_MAJOR%.%REQUIRED_MINOR%
    goto :python_ready
)

:: Check if python command is 3.13
python --version >nul 2>&1
if %errorLevel% equ 0 (
    for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
    for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
        if %%a EQU %REQUIRED_MAJOR% if %%b EQU %REQUIRED_MINOR% (
            echo Found Python !PYVER!
            set PYTHON_CMD=python
            goto :python_ready
        )
    )
    echo Found Python !PYVER! but need %REQUIRED_MAJOR%.%REQUIRED_MINOR%
)

:: Python 3.13 not found - try to install
echo.
echo [INFO] Python %REQUIRED_MAJOR%.%REQUIRED_MINOR% not found.
echo.

:: Check if winget is available
winget --version >nul 2>&1
if %errorLevel% equ 0 (
    echo Installing Python %REQUIRED_MAJOR%.%REQUIRED_MINOR% via winget...
    echo.
    winget install Python.Python.%REQUIRED_MAJOR%.%REQUIRED_MINOR% --accept-source-agreements --accept-package-agreements
    if %errorLevel% equ 0 (
        echo.
        echo [SUCCESS] Python %REQUIRED_MAJOR%.%REQUIRED_MINOR% installed!
        echo.
        echo IMPORTANT: Please close and reopen this terminal, then run build_exe.bat again.
        echo This is needed to refresh the PATH environment variable.
        echo.
        pause
        exit /b 0
    ) else (
        echo [WARNING] winget install failed. Trying alternative method...
    )
)

:: If winget not available or failed, try downloading directly
echo.
echo Downloading Python %REQUIRED_MAJOR%.%REQUIRED_MINOR% installer...
set PYTHON_URL=https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe
set INSTALLER=%TEMP%\python-%REQUIRED_MAJOR%.%REQUIRED_MINOR%-installer.exe

:: Download using curl (available on Windows 10+)
curl -L -o "%INSTALLER%" "%PYTHON_URL%" 2>nul
if %errorLevel% neq 0 (
    :: Try PowerShell if curl fails
    powershell -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%INSTALLER%'" 2>nul
)

if exist "%INSTALLER%" (
    echo.
    echo Installing Python %REQUIRED_MAJOR%.%REQUIRED_MINOR%...
    echo Please wait and follow the installer prompts.
    echo IMPORTANT: Check "Add Python to PATH" option!
    echo.
    
    :: Run installer with options: add to PATH, install for all users
    "%INSTALLER%" /passive InstallAllUsers=1 PrependPath=1 Include_test=0
    
    if %errorLevel% equ 0 (
        echo.
        echo [SUCCESS] Python %REQUIRED_MAJOR%.%REQUIRED_MINOR% installed!
        echo.
        echo IMPORTANT: Please close and reopen this terminal, then run build_exe.bat again.
        echo This is needed to refresh the PATH environment variable.
        echo.
        del "%INSTALLER%" 2>nul
        pause
        exit /b 0
    ) else (
        echo [ERROR] Installation failed. Please install Python %REQUIRED_MAJOR%.%REQUIRED_MINOR% manually.
        echo Download from: https://www.python.org/downloads/release/python-3131/
        del "%INSTALLER%" 2>nul
        pause
        exit /b 1
    )
) else (
    echo.
    echo [ERROR] Could not download Python installer.
    echo Please install Python %REQUIRED_MAJOR%.%REQUIRED_MINOR% manually:
    echo   https://www.python.org/downloads/release/python-3131/
    echo.
    echo Make sure to check "Add Python to PATH" during installation!
    echo.
    pause
    exit /b 1
)

:python_ready
echo.
echo Using: %PYTHON_CMD%
echo.

:: Check if venv313 exists and activate
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
) else (
    echo Creating Python 3.13 virtual environment...
    %PYTHON_CMD% -m venv venv313
    if %errorLevel% neq 0 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    call "venv313\Scripts\activate.bat"
    echo Created and activated: venv313
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
    echo Trying to install with binary-only wheels...
    pip install --only-binary :all: pyscard pycryptodome Pillow numpy 2>nul
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
