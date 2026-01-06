"""
NFC Bridge Launcher
===================
Opens the status page in the default browser.
Also checks if the server is running and offers to start it.

This is the main entry point when clicking the app icon.
"""

import sys
import os
import time
import socket
import webbrowser
import subprocess
import threading
from pathlib import Path

# Configuration
HOST = "localhost"
PORT = 3005
STATUS_PAGE = "status.html"


def get_script_dir():
    """Get the directory where this script/exe is located"""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return Path(sys.executable).parent
    else:
        # Running as script
        return Path(__file__).parent.resolve()


def is_server_running():
    """Check if the NFC Bridge server is running"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((HOST, PORT))
        sock.close()
        return result == 0
    except:
        return False


def start_server_background():
    """Start the server in the background"""
    script_dir = get_script_dir()
    
    # Try to find the server executable or script
    server_exe = script_dir / "nfc_server.exe"
    server_py = script_dir / "server.py"
    service_py = script_dir / "nfc_service.py"
    
    if server_exe.exists():
        # Run compiled server
        subprocess.Popen(
            [str(server_exe)],
            cwd=str(script_dir),
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        )
        return True
    elif service_py.exists():
        # Run service script
        python_exe = sys.executable
        subprocess.Popen(
            [python_exe, str(service_py), "standalone"],
            cwd=str(script_dir),
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        )
        return True
    elif server_py.exists():
        # Run server script directly
        python_exe = sys.executable
        subprocess.Popen(
            [python_exe, str(server_py)],
            cwd=str(script_dir),
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        )
        return True
    
    return False


def open_status_page():
    """Open the status page in the default browser"""
    script_dir = get_script_dir()
    status_file = script_dir / STATUS_PAGE
    
    if status_file.exists():
        webbrowser.open(f"file:///{status_file}")
    else:
        # Open web version if available
        webbrowser.open(f"http://{HOST}:{PORT}/status")


def show_message(title, message, icon="info"):
    """Show a message box (Windows only)"""
    try:
        import ctypes
        icon_flags = {
            "info": 0x40,
            "warning": 0x30,
            "error": 0x10,
            "question": 0x20
        }
        ctypes.windll.user32.MessageBoxW(
            0, 
            message, 
            title, 
            icon_flags.get(icon, 0x40)
        )
    except:
        print(f"{title}: {message}")


def ask_yes_no(title, message):
    """Show a Yes/No dialog (Windows only)"""
    try:
        import ctypes
        # MB_YESNO = 0x04, MB_ICONQUESTION = 0x20
        result = ctypes.windll.user32.MessageBoxW(0, message, title, 0x04 | 0x20)
        return result == 6  # IDYES = 6
    except:
        return True  # Default to yes if dialog fails


def main():
    """Main launcher function"""
    print("NFC Bridge Launcher")
    print("=" * 40)
    
    # Check if server is running
    if is_server_running():
        print(f"✓ Server is running on port {PORT}")
        open_status_page()
    else:
        print(f"✗ Server is not running on port {PORT}")
        
        # Ask if user wants to start the server
        if ask_yes_no(
            "NFC Bridge Server",
            f"NFC Bridge Server is not running.\n\n"
            f"Would you like to start it now?"
        ):
            print("Starting server...")
            
            if start_server_background():
                # Wait for server to start
                print("Waiting for server to start...")
                for i in range(10):
                    time.sleep(0.5)
                    if is_server_running():
                        print(f"✓ Server started successfully")
                        break
                else:
                    print("✗ Server did not start in time")
            else:
                show_message(
                    "NFC Bridge Server",
                    "Could not find server executable.\n"
                    "Please make sure nfc_server.exe or server.py exists.",
                    "error"
                )
                return
        
        # Open status page regardless
        open_status_page()
    
    print("Status page opened in browser")


if __name__ == "__main__":
    main()

