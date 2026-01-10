@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   NFC Bridge Server - Install Dependencies
echo ========================================
echo.

:: Force Python 3.13
set PYTHON_CMD=
set NEED_RESTART=0

:: Check for Python 3.13 via py launcher
py -3.13 --version >nul 2>&1
if %errorLevel% equ 0 (
    set PYTHON_CMD=py -3.13
    py -3.13 --version
    goto :python_ready
)

:: Python 3.13 not found - install it automatically
echo [INFO] Python 3.13 not found. Installing automatically...
echo.

:: Try winget first
winget --version >nul 2>&1
if %errorLevel% equ 0 (
    echo Installing Python 3.13 via winget...
    winget install Python.Python.3.13 --accept-source-agreements --accept-package-agreements --silent
    if %errorLevel% equ 0 (
        set NEED_RESTART=1
        goto :check_restart
    )
    echo winget install failed, trying direct download...
)

:: Download directly
echo Downloading Python 3.13 from python.org...
set INSTALLER=%TEMP%\python-3.13-installer.exe
curl -L -o "%INSTALLER%" "https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe" 2>nul
if not exist "%INSTALLER%" (
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe' -OutFile '%INSTALLER%'" 2>nul
)

if exist "%INSTALLER%" (
    echo.
    echo Installing Python 3.13...
    "%INSTALLER%" /passive InstallAllUsers=1 PrependPath=1 Include_test=0
    del "%INSTALLER%" 2>nul
    set NEED_RESTART=1
    goto :check_restart
)

echo.
echo [ERROR] Failed to install Python 3.13 automatically.
echo Please install manually from:
echo   https://www.python.org/downloads/release/python-3131/
echo.
echo Make sure to check "Add Python to PATH"!
pause
exit /b 1

:check_restart
if %NEED_RESTART% equ 1 (
    echo.
    echo ========================================
    echo   Python 3.13 Installed Successfully!
    echo ========================================
    echo.
    echo Please CLOSE this window and run install_dependencies.bat again.
    echo ^(The PATH environment variable needs to refresh^)
    echo.
    pause
    exit /b 0
)

:python_ready
echo.

:: Remove old venv if wrong Python version
if exist "venv\pyvenv.cfg" (
    findstr /c:"3.13" "venv\pyvenv.cfg" >nul 2>&1
    if %errorLevel% neq 0 (
        echo Removing old virtual environment ^(wrong Python version^)...
        rmdir /s /q venv 2>nul
    )
)

:: Create venv if not exists
if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment with Python 3.13...
    %PYTHON_CMD% -m venv venv
    if %errorLevel% neq 0 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
)

:: Activate venv
call "venv\Scripts\activate.bat"
echo Virtual environment activated.
echo.

:: Show Python version
python --version
echo.

:: Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip --quiet

:: Install core packages
echo.
echo ========================================
echo   Installing Core Dependencies
echo ========================================
echo.

echo [1/5] websockets...
pip install --only-binary :all: websockets --quiet
if %errorLevel% equ 0 ( echo       OK ) else ( echo       FAILED )

echo [2/5] pycryptodome...
pip install --only-binary :all: pycryptodome --quiet
if %errorLevel% equ 0 ( echo       OK ) else ( echo       FAILED )

echo [3/5] Pillow...
pip install --only-binary :all: Pillow --quiet
if %errorLevel% equ 0 ( echo       OK ) else ( echo       FAILED )

echo [4/5] numpy...
pip install --only-binary :all: numpy --quiet
if %errorLevel% equ 0 ( echo       OK ) else ( echo       FAILED )

echo [5/5] pywin32...
pip install --only-binary :all: pywin32 --quiet
if %errorLevel% equ 0 (
    echo       OK
    python -m pywin32_postinstall -install >nul 2>&1
) else (
    echo       FAILED ^(service mode may not work^)
)

:: pyscard - try binary first
echo.
echo Installing pyscard (NFC reader support)...
pip install --only-binary :all: pyscard --quiet 2>nul
if %errorLevel% neq 0 (
    echo [INFO] No binary wheel, trying source build...
    pip install pyscard --quiet 2>nul
    if %errorLevel% neq 0 (
        echo.
        echo [WARNING] pyscard failed - NFC reader may not work.
        echo To fix, install Visual C++ Build Tools:
        echo   https://visualstudio.microsoft.com/visual-cpp-build-tools/
        echo.
    ) else (
        echo       OK (built from source)
    )
) else (
    echo       OK
)

:: Force install EasyOCR
echo.
echo ========================================
echo   Installing EasyOCR (Text Extraction)
echo ========================================
echo.
echo Installing PyTorch + EasyOCR (~2GB download)...
echo This may take several minutes...
echo.

pip install --only-binary :all: torch torchvision --quiet 2>nul
if %errorLevel% neq 0 (
    echo [INFO] Binary install failed, trying regular install...
    pip install torch torchvision --quiet
)

pip install easyocr --quiet
if %errorLevel% equ 0 (
    echo.
    echo Downloading OCR language models (Japanese + English)...
    python -c "import easyocr; easyocr.Reader(['ja', 'en'], gpu=False, verbose=False); print('Models loaded!')"
    echo.
    echo EasyOCR installed successfully!
) else (
    echo [WARNING] EasyOCR installation failed
    echo You can try again later with: install_ocr.bat
)

echo.
echo ========================================
echo   Installation Complete!
echo ========================================
echo.
echo Next steps:
echo   - Run server manually:  start_server.bat
echo   - Auto-start on boot:   install_service.bat (as Admin)
echo.
pause
