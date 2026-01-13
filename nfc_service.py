"""
NFC Bridge Windows Service
==========================
Runs the NFC Bridge Server as a Windows Service.

Installation:
    python nfc_service.py install
    
Start:
    python nfc_service.py start
    OR
    net start NFCBridgeService

Stop:
    python nfc_service.py stop
    OR
    net stop NFCBridgeService

Remove:
    python nfc_service.py remove

Debug (run in console):
    python nfc_service.py debug
"""

# CRITICAL: Set environment variables BEFORE any imports to prevent PaddleOCR timeout
import os
os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'  # Skip PaddleOCR network check
os.environ['PADDLE_PDX_LOCAL_MODEL_SOURCE'] = 'True'  # Use local models only
os.environ['FLAGS_use_mkldnn'] = 'False'  # Disable MKL-DNN for faster startup

import sys
import time
import asyncio
import logging
import threading
from pathlib import Path

# Add current directory to path for imports
script_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(script_dir))

# Determine the venv Python executable path for service registration
VENV_PYTHON = script_dir / "venv" / "Scripts" / "python.exe"
SERVICE_PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

# Try to import win32 service components
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    print("WARNING: pywin32 not installed - service mode unavailable")
    print("Install: pip install pywin32")

# Defer server module import to avoid PaddleOCR initialization at service registration time
# This will be imported when the service actually starts
SERVER_AVAILABLE = None  # Will be set to True/False when needed
NFCBridge = None
HOST = "localhost"
PORT = 3005

def _import_server():
    """Lazy import of server module to defer PaddleOCR initialization"""
    global SERVER_AVAILABLE, NFCBridge, HOST, PORT
    if SERVER_AVAILABLE is not None:
        return SERVER_AVAILABLE
    
    try:
        from server import NFCBridge as _NFCBridge, HOST as _HOST, PORT as _PORT
        import websockets
        NFCBridge = _NFCBridge
        HOST = _HOST
        PORT = _PORT
        SERVER_AVAILABLE = True
        return True
    except ImportError as e:
        print(f"WARNING: Cannot import server module: {e}")
        SERVER_AVAILABLE = False
        return False


class NFCBridgeService:
    """Service wrapper for NFC Bridge Server"""
    
    _svc_name_ = "NFCBridgeService"
    _svc_display_name_ = "NFC Bridge Server"
    _svc_description_ = "WebSocket server for NFC card reading (CCCD, My Number, Suica)"
    
    def __init__(self):
        self.running = False
        self.bridge = None
        self.server = None
        self.loop = None
        self.server_thread = None
        self.logger = None
        
        # Setup logging with error handling (service may run as SYSTEM)
        self._setup_logging()
    
    def _setup_logging(self):
        """Setup logging with fallbacks for service environment"""
        try:
            log_path = script_dir / 'nfc_service.log'
            
            # Clear any existing handlers
            root_logger = logging.getLogger()
            root_logger.handlers.clear()
            
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler(str(log_path), encoding='utf-8'),
                ]
            )
            self.logger = logging.getLogger(__name__)
        except Exception as e:
            # Fallback to null logger if file logging fails
            self.logger = logging.getLogger(__name__)
            self.logger.addHandler(logging.NullHandler())
    
    def start(self):
        """Start the service"""
        self.logger.info("NFC Bridge Service starting...")
        self.running = True
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        self.logger.info("NFC Bridge Service started")
    
    def stop(self):
        """Stop the service"""
        self.logger.info("NFC Bridge Service stopping...")
        self.running = False
        
        if self.loop and self.server:
            # Schedule server close
            asyncio.run_coroutine_threadsafe(self._stop_server(), self.loop)
        
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=5)
        
        self.logger.info("NFC Bridge Service stopped")
    
    async def _stop_server(self):
        """Stop the WebSocket server"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
    
    def _run_server(self):
        """Run the server in a separate thread"""
        try:
            self.logger.info("Initializing server components...")
            
            # Import server module here (lazy loading to avoid startup timeout)
            if not _import_server():
                self.logger.error("Failed to import server module")
                return
            
            import websockets
            
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            self.logger.info("Creating NFC Bridge...")
            self.bridge = NFCBridge()
            
            async def serve():
                self.server = await websockets.serve(
                    self.bridge.handler, 
                    HOST, 
                    PORT
                )
                self.logger.info(f"Server listening on ws://{HOST}:{PORT}")
                
                # Keep running until stopped
                while self.running:
                    await asyncio.sleep(1)
            
            self.loop.run_until_complete(serve())
            
        except Exception as e:
            self.logger.error(f"Server error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.loop:
                self.loop.close()


if WIN32_AVAILABLE:
    class NFCBridgeWindowsService(win32serviceutil.ServiceFramework):
        """Windows Service Framework wrapper"""
        
        _svc_name_ = "NFCBridgeService"
        _svc_display_name_ = "NFC Bridge Server"
        _svc_description_ = "WebSocket server for NFC card reading (CCCD, My Number, Suica)"
        
        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.service = None
            
            try:
                # Change to script directory so imports work correctly
                os.chdir(str(script_dir))
                
                # Create service instance (minimal initialization)
                self.service = NFCBridgeService()
            except Exception as e:
                # Log error but don't fail - service will handle it in SvcDoRun
                try:
                    servicemanager.LogErrorMsg(f"Service init error: {e}")
                except:
                    pass
        
        def SvcStop(self):
            """Called when the service is asked to stop"""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            try:
                if self.service:
                    self.service.stop()
            except Exception:
                pass
            win32event.SetEvent(self.stop_event)
        
        def SvcDoRun(self):
            """Called when the service is asked to start"""
            try:
                # Ensure we're in the correct directory
                os.chdir(str(script_dir))
                
                # Report running status IMMEDIATELY to prevent Windows timeout
                # The actual server initialization will happen in background thread
                self.ReportServiceStatus(win32service.SERVICE_RUNNING)
                
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_INFORMATION_TYPE,
                    servicemanager.PYS_SERVICE_STARTED,
                    (self._svc_name_, '')
                )
                
                # Create service if not already created
                if self.service is None:
                    self.service = NFCBridgeService()
                
                # Start server in background (PaddleOCR initialization happens here)
                self.service.start()
                
                # Wait for stop event
                win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
                
            except Exception as e:
                servicemanager.LogErrorMsg(f"Service error: {e}")
                self.SvcStop()


def run_standalone():
    """Run the server standalone (not as a service)"""
    # Import server module to get actual HOST/PORT
    _import_server()
    
    print("=" * 60)
    print("  NFC Bridge Server - Standalone Mode")
    print("=" * 60)
    print(f"  URL: ws://{HOST}:{PORT}")
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    
    service = NFCBridgeService()
    
    try:
        service.start()
        # Keep main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        service.stop()


def install_service():
    """Install the service using standard pywin32 approach"""
    if not WIN32_AVAILABLE:
        print("ERROR: pywin32 not installed")
        return False
    
    print(f"Script directory: {script_dir}")
    print(f"Python executable: {sys.executable}")
    
    # Check if we're running from venv
    if VENV_PYTHON.exists() and str(VENV_PYTHON) not in sys.executable:
        print(f"\nWARNING: Not running from venv!")
        print(f"Expected: {VENV_PYTHON}")
        print(f"Current:  {sys.executable}")
        print()
    
    try:
        # Use standard pywin32 installation (uses pythonservice.exe)
        win32serviceutil.HandleCommandLine(NFCBridgeWindowsService, argv=['', 'install'])
        print(f"\nService '{NFCBridgeWindowsService._svc_name_}' installed successfully!")
        
        # Set service description
        try:
            import win32api
            import win32con
            key = win32api.RegOpenKeyEx(
                win32con.HKEY_LOCAL_MACHINE,
                f"SYSTEM\\CurrentControlSet\\Services\\{NFCBridgeWindowsService._svc_name_}",
                0,
                win32con.KEY_SET_VALUE
            )
            win32api.RegSetValueEx(key, "Description", 0, win32con.REG_SZ, 
                                   NFCBridgeWindowsService._svc_description_)
            win32api.RegCloseKey(key)
        except:
            pass  # Description is optional
        
        return True
    except Exception as e:
        print(f"ERROR installing service: {e}")
        return False


def main():
    if len(sys.argv) == 1:
        # No arguments - run standalone
        run_standalone()
    elif sys.argv[1] == 'standalone':
        run_standalone()
    elif WIN32_AVAILABLE:
        # Handle Windows service commands
        if len(sys.argv) > 1 and sys.argv[1] == 'debug':
            # Debug mode - run standalone
            run_standalone()
        elif len(sys.argv) > 1 and sys.argv[1] == 'install':
            # Custom install to ensure venv Python is used
            install_service()
        else:
            # Handle other commands (start, stop, remove, etc.)
            win32serviceutil.HandleCommandLine(NFCBridgeWindowsService)
    else:
        print("Windows service mode requires pywin32")
        print("Run 'pip install pywin32' to enable service mode")
        print("\nRunning in standalone mode...")
        run_standalone()


if __name__ == "__main__":
    main()

