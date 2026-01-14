@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Install Service
echo ========================================
echo.

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Please run as Administrator!
    echo.
    echo Right-click this file and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

echo Running as Administrator - OK
echo.

:: Get script directory
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"
echo Working directory: %CD%
echo.

:: Force Python 3.13 ONLY
set PYTHON_CMD=
set NEED_RESTART=0
set PYSCARD_OK=0

:: Check for Python 3.13 via py launcher
py -3.13 --version >nul 2>&1
if %errorLevel% equ 0 (
    set PYTHON_CMD=py -3.13
    for /f "tokens=*" %%v in ('py -3.13 --version 2^>^&1') do echo %%v
    goto :python_ready
)

:: Python 3.13 not found - install it
echo.
echo ========================================
echo   Python 3.13 Required - Installing...
echo ========================================
echo.
echo Installing Python 3.13...
echo.

:: Skip winget (known certificate issues) - use direct download
echo Downloading from python.org...
set INSTALLER=%TEMP%\python-3.13-installer.exe
curl -L -o "%INSTALLER%" "https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe" 2>nul
if not exist "%INSTALLER%" (
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe' -OutFile '%INSTALLER%'" 2>nul
)

if exist "%INSTALLER%" (
    echo Running installer...
    "%INSTALLER%" /passive InstallAllUsers=1 PrependPath=1 Include_test=0
    del "%INSTALLER%" 2>nul
    set NEED_RESTART=1
    goto :check_restart
)

echo [ERROR] Failed to install Python 3.13
echo Please install manually: https://www.python.org/downloads/release/python-3131/
pause
exit /b 1

:check_restart
if %NEED_RESTART% equ 1 (
    echo.
    echo ========================================
    echo   Python 3.13 Installed!
    echo ========================================
    echo.
    echo IMPORTANT: Close this window and run install_service.bat again.
    echo.
    pause
    exit /b 0
)

:python_ready
echo.

:: Check and install Visual C++ Redistributable (required for PyTorch)
reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo ========================================
    echo   Installing Visual C++ Redistributable
    echo ========================================
    echo.
    
    set VCREDIST=%TEMP%\vc_redist.x64.exe
    curl -L -o "!VCREDIST!" "https://aka.ms/vs/17/release/vc_redist.x64.exe" 2>nul
    if not exist "!VCREDIST!" (
        powershell -Command "Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile '!VCREDIST!'" 2>nul
    )
    if exist "!VCREDIST!" (
        echo Installing VC++ Redistributable...
        "!VCREDIST!" /install /passive /norestart
        del "!VCREDIST!" 2>nul
        echo VC++ Redistributable installed!
        echo.
    )
)

:: ALWAYS delete venv if it's not Python 3.13 (same as start_server.bat)
if exist "venv\Scripts\python.exe" (
    echo Checking virtual environment Python version...
    for /f "tokens=2 delims= " %%v in ('"venv\Scripts\python.exe" --version 2^>^&1') do set VENV_VER=%%v
    echo Current venv: Python !VENV_VER!
    
    echo !VENV_VER! | findstr /b "3.13" >nul
    if !errorLevel! neq 0 (
        echo.
        echo [WARNING] venv is Python !VENV_VER!, not 3.13!
        echo Deleting old venv and recreating with Python 3.13...
        rmdir /s /q venv 2>nul
        echo.
    )
)

:: Create venv with Python 3.13
if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment with Python 3.13...
    %PYTHON_CMD% -m venv venv
    if %errorLevel% neq 0 (
        echo [ERROR] Failed to create virtual environment
        echo.
        pause
        exit /b 1
    )
    echo Virtual environment created.
    echo.
)

:: Activate venv
call "venv\Scripts\activate.bat"
if %errorLevel% neq 0 (
    echo [ERROR] Failed to activate virtual environment
    pause
    exit /b 1
)

:: Verify Python version in venv
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set ACTIVE_VER=%%v
echo Active Python: !ACTIVE_VER!

echo !ACTIVE_VER! | findstr /b "3.13" >nul
if !errorLevel! neq 0 (
    echo.
    echo [ERROR] Wrong Python version in venv: !ACTIVE_VER!
    echo Expected: 3.13.x
    echo.
    echo Deleting venv and retrying...
    deactivate 2>nul
    rmdir /s /q venv 2>nul
    
    echo Creating fresh venv...
    %PYTHON_CMD% -m venv venv
    call "venv\Scripts\activate.bat"
)

echo.

:: Install core dependencies if missing (same as start_server.bat)
python -c "import websockets" >nul 2>&1
if %errorLevel% neq 0 (
    echo ========================================
    echo   Installing Core Dependencies
    echo ========================================
    echo.
    
    python -m pip install --upgrade pip --quiet
    
    echo [1/5] websockets...
    pip install --only-binary :all: websockets --quiet
    echo       Done
    
    echo [2/5] pycryptodome...
    pip install --only-binary :all: pycryptodome --quiet
    echo       Done
    
    echo [3/5] Pillow...
    pip install --only-binary :all: Pillow --quiet
    echo       Done
    
    echo [4/5] numpy...
    pip install --only-binary :all: numpy --quiet
    echo       Done
    
    echo [5/5] pywin32...
    pip install --only-binary :all: pywin32 --quiet
    python -m pywin32_postinstall -install >nul 2>&1
    echo       Done
    
    echo.
    echo Core dependencies installed!
    echo.
)

:: Install pyscard separately (critical for NFC readers)
echo ========================================
echo   Installing pyscard (NFC Reader)
echo ========================================
echo.

python -c "from smartcard.System import readers" >nul 2>&1
if %errorLevel% equ 0 (
    echo pyscard is already installed.
    set PYSCARD_OK=1
) else (
    echo Installing pyscard...
    echo.
    
    :: Try binary install first (fastest)
    pip install --only-binary :all: pyscard 2>nul
    
    :: Check if it worked
    python -c "from smartcard.System import readers" >nul 2>&1
    if !errorLevel! equ 0 (
        echo pyscard installed successfully!
        set PYSCARD_OK=1
    ) else (
        echo Binary install failed. Trying source install...
        pip install pyscard 2>nul
        
        python -c "from smartcard.System import readers" >nul 2>&1
        if !errorLevel! equ 0 (
            echo pyscard installed successfully!
            set PYSCARD_OK=1
        ) else (
            echo.
            echo [WARNING] pyscard installation failed
            echo NFC reader communication may not work.
            echo.
        )
    )
)
echo.

:: Install PaddleOCR if missing (primary OCR engine)
python -c "import paddleocr" >nul 2>&1
if %errorLevel% neq 0 (
    echo ========================================
    echo   Installing PaddleOCR
    echo ========================================
    echo.
    echo This may take a few minutes...
    echo.
    
    :: Upgrade pip first
    python -m pip install --upgrade pip setuptools wheel --quiet
    
    :: Install shapely first (required dependency)
    echo [1/4] Installing shapely...
    pip install --only-binary :all: shapely --quiet 2>nul
    if !errorLevel! neq 0 pip install shapely --quiet 2>nul
    echo       Done
    
    :: Install PaddlePaddle (CPU version for compatibility)
    echo [2/4] Installing PaddlePaddle...
    pip install paddlepaddle==3.0.0b2 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/ --quiet 2>nul
    if !errorLevel! neq 0 (
        pip install paddlepaddle --quiet 2>nul
    )
    echo       Done
    
    :: Install PaddleOCR with all dependencies
    echo [3/4] Installing PaddleOCR...
    pip install "paddleocr>=2.9.0" --quiet 2>nul
    if !errorLevel! neq 0 pip install paddleocr --quiet 2>nul
    echo       Done
    
    :: Install additional dependencies
    echo [4/4] Installing OCR dependencies...
    pip install opencv-python-headless pyclipper --quiet 2>nul
    echo       Done
    
    echo.
    python -c "import paddleocr" >nul 2>&1
    if !errorLevel! equ 0 (
        echo PaddleOCR installed successfully!
    ) else (
        echo [WARNING] PaddleOCR may not be fully installed.
        echo Trying EasyOCR fallback...
        pip install torch torchvision easyocr --quiet 2>nul
    )
    echo.
)

:: Set venv Python path explicitly
set VENV_PYTHON=%SCRIPT_DIR%venv\Scripts\python.exe
echo.
echo Using venv Python: %VENV_PYTHON%
echo.

:: Stop existing service
echo ========================================
echo   Stopping Existing Service
echo ========================================
echo.
net stop NFCBridgeService >nul 2>&1
"%VENV_PYTHON%" nfc_service.py stop >nul 2>&1
timeout /t 2 /nobreak >nul
echo Done.

:: Remove existing service
echo.
echo ========================================
echo   Removing Existing Service
echo ========================================
echo.
"%VENV_PYTHON%" nfc_service.py remove >nul 2>&1
sc delete NFCBridgeService >nul 2>&1
timeout /t 3 /nobreak >nul
echo Done.

:: Install the service using venv Python
echo.
echo ========================================
echo   Installing NFC Bridge Service
echo ========================================
echo.
echo Service will be registered to use:
echo   Python: %VENV_PYTHON%
echo   Script: %SCRIPT_DIR%nfc_service.py
echo.

"%VENV_PYTHON%" nfc_service.py install
if %errorLevel% neq 0 (
    echo.
    echo [ERROR] Failed to install service
    echo.
    echo Try running manually:
    echo   "%VENV_PYTHON%" nfc_service.py install
    echo.
    pause
    exit /b 1
)

:: Configure auto-start
echo.
echo Configuring auto-start...
sc config NFCBridgeService start= auto >nul 2>&1
echo Done.

:: Start the service using net start (more reliable than python script)
echo.
echo ========================================
echo   Starting Service
echo ========================================
echo.
echo Starting service (this may take a moment for initialization)...
echo.

:: Use net start with longer timeout (more reliable)
net start NFCBridgeService 2>nul
set START_RESULT=%errorLevel%

:: Give extra time for background initialization
echo Waiting for server initialization...
timeout /t 5 /nobreak >nul

:: Check if service is running
sc query NFCBridgeService | findstr "RUNNING" >nul 2>&1
if %errorLevel% equ 0 (
    echo.
    echo ========================================
    echo   SUCCESS!
    echo ========================================
    echo.
    echo NFC Bridge Service is:
    echo   - Installed
    echo   - Running  
    echo   - Auto-start on boot
    echo.
    echo Configuration:
    echo   Port: 3005
    echo   Python: %VENV_PYTHON%
    echo   Log: %SCRIPT_DIR%nfc_service.log
    echo.
    echo To check status:  sc query NFCBridgeService
    echo To view logs:     type %SCRIPT_DIR%nfc_service.log
    echo.
) else (
    echo.
    echo ========================================
    echo   Service Installed (Not Running)
    echo ========================================
    echo.
    echo The service was installed but failed to start.
    echo This is common with complex Python applications.
    echo.
    echo RECOMMENDED: Use Task Scheduler instead!
    echo   Run: install_startup.bat
    echo.
    echo This method is more reliable for:
    echo   - PaddleOCR/PyTorch applications
    echo   - NFC reader access
    echo   - Interactive services
    echo.
    echo Debug steps (if you want to try Windows Service):
    echo   1. Check logs: type %SCRIPT_DIR%nfc_service.log
    echo   2. Check Event Viewer: eventvwr.msc
    echo   3. Try starting manually: net start NFCBridgeService
    echo.
    
    :: Offer to install Task Scheduler alternative
    echo.
    set /p USE_TASK="Install Task Scheduler auto-start instead? (Y/N): "
    if /i "!USE_TASK!"=="Y" (
        echo.
        echo Removing service and setting up Task Scheduler...
        net stop NFCBridgeService >nul 2>&1
        sc delete NFCBridgeService >nul 2>&1
        
        call install_startup.bat
        exit /b 0
    )
)

pause
