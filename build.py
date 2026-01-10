"""
NFC Bridge Build Script
=======================
Builds the NFC Bridge Server as Windows executables using PyInstaller.

Creates:
- nfc_server.exe   - Main server executable (run in background)
- nfc_launcher.exe - Launcher that opens status page in browser
- nfc_service.exe  - Windows service wrapper

Usage:
    python build.py          # Build main components (server, launcher, service)
    python build.py server   # Build server only
    python build.py launcher # Build launcher only
    python build.py service  # Build service only
    python build.py checker  # Build check_system.exe (optional diagnostic tool)
    python build.py clean    # Clean build artifacts only
"""

import sys
import os
import shutil
import subprocess
from pathlib import Path

# Configuration
SCRIPT_DIR = Path(__file__).parent.resolve()
DIST_DIR = SCRIPT_DIR / "dist"
BUILD_DIR = SCRIPT_DIR / "build"


def check_pyinstaller():
    """Check if PyInstaller is installed"""
    try:
        import PyInstaller
        return True
    except ImportError:
        print("PyInstaller not installed!")
        print("Run: pip install pyinstaller")
        return False


def kill_running_processes():
    """Kill any running NFC server processes that might lock files"""
    processes_to_kill = ['nfc_server.exe', 'nfc_service.exe', 'nfc_launcher.exe', 'check_system.exe']
    
    for proc_name in processes_to_kill:
        try:
            # Use taskkill to terminate processes
            result = subprocess.run(
                ['taskkill', '/F', '/IM', proc_name],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"  Stopped: {proc_name}")
        except Exception:
            pass  # Process not running, ignore


def rmtree_with_retry(path, max_retries=3, delay=2):
    """Remove directory tree with retry logic for locked files"""
    import time
    
    for attempt in range(max_retries):
        try:
            if path.exists():
                shutil.rmtree(path)
            return True
        except PermissionError as e:
            if attempt < max_retries - 1:
                print(f"  [Retry {attempt + 1}/{max_retries}] Files locked, waiting {delay}s...")
                time.sleep(delay)
            else:
                print(f"  [ERROR] Cannot delete {path}: {e}")
                print(f"  Please close any programs using files in this folder.")
                return False
        except Exception as e:
            print(f"  [ERROR] {e}")
            return False
    return True


def clean_build():
    """Clean previous build artifacts"""
    print("Cleaning previous build...")
    
    # First, try to kill any running processes that might lock files
    print("Stopping any running NFC processes...")
    kill_running_processes()
    
    # Small delay to let processes fully terminate
    import time
    time.sleep(1)
    
    success = True
    for path in [DIST_DIR, BUILD_DIR]:
        if path.exists():
            print(f"  Removing: {path}")
            if not rmtree_with_retry(path):
                success = False
    
    # Clean .spec files
    for spec in SCRIPT_DIR.glob("*.spec"):
        try:
            spec.unlink()
            print(f"  Removed: {spec.name}")
        except PermissionError:
            print(f"  [WARNING] Could not delete {spec.name}")
    
    if success:
        print("Clean complete")
    else:
        print("\n[WARNING] Some files could not be deleted.")
        print("Try one of these solutions:")
        print("  1. Close Windows Explorer if the dist/ folder is open")
        print("  2. Stop any running nfc_server.exe manually")
        print("  3. Temporarily disable antivirus")
        print("  4. Run this script as Administrator")
        print("\nPress Enter to continue anyway, or Ctrl+C to cancel...")
        input()


def get_hidden_imports():
    """Get list of hidden imports needed"""
    return [
        # Core
        'websockets',
        'websockets.legacy',
        'websockets.legacy.server',
        'websockets.server',
        'websockets.exceptions',
        'asyncio',
        'json',
        'logging',
        'hashlib',
        
        # Smart card (pyscard)
        'smartcard',
        'smartcard.System',
        'smartcard.util',
        'smartcard.Exceptions',
        'smartcard.scard',
        'smartcard.CardConnection',
        'smartcard.CardRequest',
        'smartcard.CardType',
        
        # Cryptography (pycryptodome)
        'Crypto',
        'Crypto.Cipher',
        'Crypto.Cipher.DES3',
        'Crypto.Cipher.DES',
        'Crypto.Cipher.AES',
        'Crypto.Hash',
        'Crypto.Hash.SHA1',
        'Crypto.Hash.SHA256',
        'Crypto.Util',
        'Crypto.Util.Padding',
        # Also try Cryptodome namespace
        'Cryptodome',
        'Cryptodome.Cipher',
        'Cryptodome.Cipher.DES3',
        'Cryptodome.Cipher.DES',
        
        # Image processing (Pillow)
        'PIL',
        'PIL.Image',
        'PIL.ImageFile',
        'PIL.JpegImagePlugin',
        'PIL.Jpeg2KImagePlugin',
        'PIL.PngImagePlugin',
        
        # NumPy
        'numpy',
        'numpy.core',
        'numpy.core._multiarray_umath',
        
        # EasyOCR and dependencies (large - consider excluding if not needed)
        'easyocr',
        'easyocr.easyocr',
        
        # nfcpy
        'nfc',
        'nfc.tag',
        'nfc.clf',
        
        # Windows service
        'win32serviceutil',
        'win32service',
        'win32event',
        'servicemanager',
        'win32api',
        'win32con',
        'pywintypes',
    ]


def get_data_files():
    """Get list of data files to include"""
    files = []
    
    # Include status.html
    status_html = SCRIPT_DIR / "status.html"
    if status_html.exists():
        files.append((str(status_html), '.'))
    
    # Include suica_subprocess.py if exists
    suica_sub = SCRIPT_DIR / "suica_subprocess.py"
    if suica_sub.exists():
        files.append((str(suica_sub), '.'))
    
    return files


def get_collect_packages():
    """Get packages that need all submodules collected"""
    return [
        'smartcard',
        'Crypto',
        'Cryptodome',
        'PIL',
        'websockets',
    ]


def build_server():
    """Build the main server executable"""
    print("\n" + "=" * 60)
    print("Building NFC Server...")
    print("=" * 60)
    
    hidden_imports = get_hidden_imports()
    hidden_import_args = []
    for imp in hidden_imports:
        hidden_import_args.extend(['--hidden-import', imp])
    
    # Collect all submodules for complex packages
    collect_args = []
    for pkg in get_collect_packages():
        collect_args.extend(['--collect-all', pkg])
    
    data_files = get_data_files()
    data_args = []
    for src, dst in data_files:
        data_args.extend(['--add-data', f'{src};{dst}'])
    
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--name', 'nfc_server',
        '--icon', 'NONE',  # Add icon if you have one
        '--console',  # Show console for debugging, use --noconsole for production
        '--noupx',
        '--noconfirm',  # Don't ask to overwrite
        *hidden_import_args,
        *collect_args,
        *data_args,
        str(SCRIPT_DIR / 'server.py')
    ]
    
    print(f"Running: {' '.join(cmd[:10])}...")
    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    
    if result.returncode == 0:
        print("✓ Server build complete: dist/nfc_server.exe")
        return True
    else:
        print("✗ Server build failed")
        return False


def build_launcher():
    """Build the launcher executable"""
    print("\n" + "=" * 60)
    print("Building NFC Launcher...")
    print("=" * 60)
    
    # Include status.html with launcher
    data_files = get_data_files()
    data_args = []
    for src, dst in data_files:
        data_args.extend(['--add-data', f'{src};{dst}'])
    
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--name', 'nfc_launcher',
        '--icon', 'NONE',
        '--noconsole',  # No console for launcher
        '--noupx',
        *data_args,
        str(SCRIPT_DIR / 'launcher.py')
    ]
    
    print(f"Running: {' '.join(cmd[:10])}...")
    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    
    if result.returncode == 0:
        print("✓ Launcher build complete: dist/nfc_launcher.exe")
        return True
    else:
        print("✗ Launcher build failed")
        return False


def build_service():
    """Build the Windows service executable"""
    print("\n" + "=" * 60)
    print("Building NFC Service...")
    print("=" * 60)
    
    hidden_imports = get_hidden_imports()
    hidden_import_args = []
    for imp in hidden_imports:
        hidden_import_args.extend(['--hidden-import', imp])
    
    # Collect all submodules for complex packages
    collect_args = []
    for pkg in get_collect_packages():
        collect_args.extend(['--collect-all', pkg])
    
    data_files = get_data_files()
    data_args = []
    for src, dst in data_files:
        data_args.extend(['--add-data', f'{src};{dst}'])
    
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--name', 'nfc_service',
        '--icon', 'NONE',
        '--console',
        '--noupx',
        '--noconfirm',
        *hidden_import_args,
        *collect_args,
        *data_args,
        str(SCRIPT_DIR / 'nfc_service.py')
    ]
    
    print(f"Running: {' '.join(cmd[:10])}...")
    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    
    if result.returncode == 0:
        print("✓ Service build complete: dist/nfc_service.exe")
        return True
    else:
        print("✗ Service build failed")
        return False


def build_checker():
    """Build the system checker executable"""
    print("\n" + "=" * 60)
    print("Building System Checker...")
    print("=" * 60)
    
    hidden_imports = get_hidden_imports()
    hidden_import_args = []
    for imp in hidden_imports:
        hidden_import_args.extend(['--hidden-import', imp])
    
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--name', 'check_system',
        '--icon', 'NONE',
        '--console',
        '--noupx',
        *hidden_import_args,
        str(SCRIPT_DIR / 'check_system.py')
    ]
    
    print(f"Running: {' '.join(cmd[:10])}...")
    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    
    if result.returncode == 0:
        print("✓ System checker build complete: dist/check_system.exe")
        return True
    else:
        print("✗ System checker build failed")
        return False


def copy_additional_files():
    """Copy additional files to dist folder"""
    print("\nCopying additional files...")
    
    # Copy status.html
    status_src = SCRIPT_DIR / "status.html"
    if status_src.exists():
        shutil.copy(status_src, DIST_DIR / "status.html")
        print("  ✓ status.html")
    
    # Copy suica_subprocess.py
    suica_src = SCRIPT_DIR / "suica_subprocess.py"
    if suica_src.exists():
        shutil.copy(suica_src, DIST_DIR / "suica_subprocess.py")
        print("  ✓ suica_subprocess.py")
    
    # Copy install guide
    guide_src = SCRIPT_DIR / "dist_package" / "INSTALL_GUIDE.txt"
    if guide_src.exists():
        shutil.copy(guide_src, DIST_DIR / "INSTALL_GUIDE.txt")
        print("  ✓ INSTALL_GUIDE.txt")


def create_install_script():
    """Create installation scripts for the dist folder"""
    
    # Create install.bat
    install_bat = DIST_DIR / "install.bat"
    install_bat.write_text('''@echo off
echo ====================================
echo NFC Bridge Server - Installation
echo ====================================
echo.

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Please run as Administrator!
    pause
    exit /b 1
)

echo Installing NFC Bridge Service...
nfc_service.exe install

echo.
echo Starting NFC Bridge Service...
nfc_service.exe start

echo.
echo ====================================
echo Installation complete!
echo.
echo The NFC Bridge Server is now running.
echo Service name: NFCBridgeService
echo.
echo To open status page, run: nfc_launcher.exe
echo ====================================
pause
''', encoding='utf-8')
    print("  ✓ install.bat")
    
    # Create uninstall.bat
    uninstall_bat = DIST_DIR / "uninstall.bat"
    uninstall_bat.write_text('''@echo off
echo ====================================
echo NFC Bridge Server - Uninstallation
echo ====================================
echo.

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Please run as Administrator!
    pause
    exit /b 1
)

echo Stopping NFC Bridge Service...
nfc_service.exe stop

echo.
echo Removing NFC Bridge Service...
nfc_service.exe remove

echo.
echo ====================================
echo Uninstallation complete!
echo ====================================
pause
''', encoding='utf-8')
    print("  ✓ uninstall.bat")
    
    # Create start.bat (run without service)
    start_bat = DIST_DIR / "start.bat"
    start_bat.write_text('''@echo off
echo Starting NFC Bridge Server...
start "" nfc_server.exe
timeout /t 2 /nobreak >nul
start "" nfc_launcher.exe
''', encoding='utf-8')
    print("  ✓ start.bat")
    
    # Create README
    readme = DIST_DIR / "README.txt"
    readme.write_text('''NFC Bridge Server
=================

Files:
- nfc_server.exe    : Main server (WebSocket on port 3005)
- nfc_launcher.exe  : Opens status page in browser
- nfc_service.exe   : Windows service wrapper
- status.html       : Status page (opened by launcher)

Quick Start:
------------
1. Double-click 'start.bat' to run the server
2. Or run 'nfc_launcher.exe' - it will ask to start server

Install as Windows Service:
--------------------------
1. Run 'install.bat' as Administrator
2. Service will start automatically on Windows boot

Uninstall Service:
-----------------
1. Run 'uninstall.bat' as Administrator

Manual Service Commands:
-----------------------
- Install: nfc_service.exe install
- Start:   nfc_service.exe start
- Stop:    nfc_service.exe stop
- Remove:  nfc_service.exe remove

WebSocket API:
-------------
Connect to: ws://localhost:3005

Supported Cards:
- Vietnamese CCCD (Căn cước công dân)
- Japanese My Number Card (マイナンバーカード)
- Japanese Zairyu Card (在留カード)
- Suica/Pasmo/ICOCA (limited)
- Generic NFC cards

Version: 2.1
''', encoding='utf-8')
    print("  ✓ README.txt")


def main():
    """Main build function"""
    print("=" * 60)
    print("  NFC Bridge Build Script")
    print("=" * 60)
    
    if not check_pyinstaller():
        return 1
    
    # Parse arguments
    build_all = len(sys.argv) == 1
    build_items = sys.argv[1:] if len(sys.argv) > 1 else ['all']
    
    if 'clean' in build_items:
        clean_build()
        if build_items == ['clean']:
            return 0
    
    # Clean on full build
    if build_all or 'all' in build_items:
        clean_build()
    
    success = True
    
    # Build requested components
    if build_all or 'all' in build_items or 'server' in build_items:
        success = build_server() and success
    
    if build_all or 'all' in build_items or 'launcher' in build_items:
        success = build_launcher() and success
    
    if build_all or 'all' in build_items or 'service' in build_items:
        success = build_service() and success
    
    # Checker is optional - only build if explicitly requested
    # (It can cause file locking issues if left running)
    if 'checker' in build_items:
        success = build_checker() and success
    elif build_all or 'all' in build_items:
        print("\n[INFO] Skipping check_system.exe (optional)")
        print("       To build it: python build.py checker")
    
    # Copy additional files
    if DIST_DIR.exists():
        copy_additional_files()
        create_install_script()
    
    # Summary
    print("\n" + "=" * 60)
    if success:
        print("  BUILD COMPLETE")
        print("=" * 60)
        print(f"\nOutput directory: {DIST_DIR}")
        print("\nFiles created:")
        for f in DIST_DIR.iterdir():
            size = f.stat().st_size
            if size > 1024 * 1024:
                size_str = f"{size / 1024 / 1024:.1f} MB"
            elif size > 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
            print(f"  - {f.name} ({size_str})")
    else:
        print("  BUILD FAILED")
        print("=" * 60)
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

