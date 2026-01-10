"""
NFC Bridge System Checker
=========================
Checks if the system is ready to run NFC Bridge Server.
Run this to diagnose issues on target machines.
"""

import sys
import os
import ctypes
import subprocess

def is_admin():
    """Check if running as administrator"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def check_python():
    """Check Python version"""
    print(f"  Python: {sys.version}")
    if sys.version_info >= (3, 8):
        print("  ✓ Python version OK")
        return True
    else:
        print("  ✗ Python 3.8+ required")
        return False

def check_smartcard_service():
    """Check if Smart Card service is running"""
    print("\n[Smart Card Service]")
    try:
        result = subprocess.run(
            ['sc', 'query', 'SCardSvr'],
            capture_output=True,
            text=True
        )
        if 'RUNNING' in result.stdout:
            print("  ✓ Smart Card service is running")
            return True
        elif 'STOPPED' in result.stdout:
            print("  ✗ Smart Card service is stopped")
            print("  → Run: sc start SCardSvr (as Administrator)")
            return False
        else:
            print("  ? Could not determine service status")
            return None
    except Exception as e:
        print(f"  ✗ Error checking service: {e}")
        return False

def check_pyscard():
    """Check if pyscard is working"""
    print("\n[PC/SC Library]")
    try:
        from smartcard.System import readers
        from smartcard.Exceptions import NoCardException
        print("  ✓ pyscard library loaded")
        
        r = readers()
        if r:
            print(f"  ✓ Found {len(r)} reader(s):")
            for reader in r:
                print(f"    - {reader}")
            return True
        else:
            print("  ✗ No card readers found")
            print("  → Check USB connection and driver installation")
            return False
    except Exception as e:
        print(f"  ✗ pyscard error: {e}")
        return False

def check_websockets():
    """Check if websockets is available"""
    print("\n[WebSocket Library]")
    try:
        import websockets
        print(f"  ✓ websockets {websockets.__version__}")
        return True
    except ImportError:
        print("  ✗ websockets not installed")
        return False

def check_crypto():
    """Check if cryptography is available"""
    print("\n[Cryptography Library]")
    try:
        from Crypto.Cipher import DES3
        print("  ✓ pycryptodome available")
        return True
    except ImportError:
        try:
            from Cryptodome.Cipher import DES3
            print("  ✓ pycryptodomex available")
            return True
        except ImportError:
            print("  ✗ pycryptodome not installed")
            print("  → BAC authentication will not work")
            return False

def check_port():
    """Check if port 3005 is available"""
    print("\n[Port 3005]")
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('localhost', 3005))
        sock.close()
        
        if result == 0:
            print("  ⚠ Port 3005 is in use (server may be running)")
            return True
        else:
            print("  ✓ Port 3005 is available")
            return True
    except Exception as e:
        print(f"  ? Error checking port: {e}")
        return None

def check_nfc_reader_driver():
    """Check for NFC reader in Device Manager"""
    print("\n[NFC Reader Device]")
    try:
        # Use WMI to check for smart card readers
        result = subprocess.run(
            ['wmic', 'path', 'Win32_PnPEntity', 'where', 
             "PNPClass='SmartCardReader'", 'get', 'Name'],
            capture_output=True,
            text=True
        )
        
        lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip() and l.strip() != 'Name']
        
        if lines:
            print(f"  ✓ Found smart card reader(s):")
            for line in lines:
                print(f"    - {line}")
            return True
        else:
            print("  ✗ No smart card reader found in Device Manager")
            print("  → Install your NFC reader driver")
            return False
    except Exception as e:
        print(f"  ? Could not check Device Manager: {e}")
        return None

def main():
    print("=" * 60)
    print("  NFC Bridge System Checker")
    print("=" * 60)
    
    if is_admin():
        print("  Running as: Administrator")
    else:
        print("  Running as: Normal user")
    
    print("\n" + "-" * 60)
    
    results = {}
    
    print("\n[Python Environment]")
    results['python'] = check_python()
    
    results['smartcard_service'] = check_smartcard_service()
    results['nfc_driver'] = check_nfc_reader_driver()
    results['pyscard'] = check_pyscard()
    results['websockets'] = check_websockets()
    results['crypto'] = check_crypto()
    results['port'] = check_port()
    
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    
    all_ok = True
    critical_ok = True
    
    for name, status in results.items():
        if status is True:
            icon = "✓"
        elif status is False:
            icon = "✗"
            all_ok = False
            if name in ['smartcard_service', 'nfc_driver', 'pyscard']:
                critical_ok = False
        else:
            icon = "?"
            all_ok = False
        
        print(f"  {icon} {name}")
    
    print("\n" + "-" * 60)
    
    if all_ok:
        print("  ✓ System is ready for NFC Bridge!")
    elif critical_ok:
        print("  ⚠ System has minor issues but may work")
    else:
        print("  ✗ System is NOT ready - fix critical issues above")
    
    print("=" * 60)
    
    # Check if running in automated mode (e.g., --no-wait flag)
    if '--no-wait' in sys.argv:
        return 0 if critical_ok else 1
    
    # Auto-close after 30 seconds to prevent locking files
    print("\nClosing in 30 seconds (press any key to exit now)...")
    
    import msvcrt
    import time
    
    for i in range(300):  # 30 seconds in 0.1s increments
        if msvcrt.kbhit():
            msvcrt.getch()
            break
        time.sleep(0.1)
    
    return 0 if critical_ok else 1

if __name__ == "__main__":
    sys.exit(main())

