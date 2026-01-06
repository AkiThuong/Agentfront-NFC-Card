# NFC Bridge Server for Zairyu Card (在留カード)

A WebSocket bridge server that connects NFC card readers to web applications.

Supports:
- 🇻🇳 Vietnamese CCCD (Căn cước công dân)
- 🇯🇵 Japanese My Number Card (マイナンバーカード)
- 🇯🇵 Japanese Zairyu Card (在留カード)
- 🚃 Suica/Pasmo/ICOCA (limited)
- 🔖 Generic NFC cards

---

## 🚀 Quick Start - Executable Version

### Download & Run (No Python Required!)

1. Download the pre-built executables from the `dist` folder
2. Double-click `start.bat` or `nfc_launcher.exe`
3. The status page will open in your browser

### Install as Windows Service (Auto-start on Boot)

1. Right-click `install.bat` → **Run as Administrator**
2. The service will be installed and started automatically
3. To uninstall, run `uninstall.bat` as Administrator

---

## 🔧 Quick Start (Development - Windows PowerShell)

### Step 1: Open PowerShell

```powershell
# Right-click Start menu → Windows Terminal (or PowerShell)
# Navigate to project folder
cd C:\path\to\nfc_bridge
```

### Step 2: Setup Virtual Environment & Install Dependencies

```powershell
# Allow script execution (run once)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Run setup script
.\setup.ps1
```

### Step 3: Run Server

```powershell
# Option A: Use the setup script to activate venv
.\venv\Scripts\Activate.ps1
python server.py

# Option B: Double-click run.bat

# Option C: Direct run
.\venv\Scripts\python.exe server.py
```

---

## Manual Setup (Step by Step)

If you prefer to set up manually:

```powershell
# 1. Create virtual environment
python -m venv venv

# 2. Activate virtual environment
.\venv\Scripts\Activate.ps1

# 3. Upgrade pip
python -m pip install --upgrade pip

# 4. Install dependencies
pip install websockets pyscard

# 5. Run server
python server.py
```

---

## Install as Windows Service

To run the NFC bridge automatically on startup:

```powershell
# Run PowerShell as Administrator!

# Install service
.\setup.ps1 -InstallService

# Start service
.\setup.ps1 -StartService

# Check service status
Get-Service NFCBridgeServer

# Stop service
.\setup.ps1 -StopService

# Uninstall service
.\setup.ps1 -UninstallService
```

---

## Troubleshooting pyscard Installation

If `pip install pyscard` fails on Windows:

### Option 1: Install Pre-built Wheel

```powershell
# Download wheel from unofficial builds
# https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyscard

# Install the downloaded wheel
pip install pyscard-2.0.7-cp311-cp311-win_amd64.whl
```

### Option 2: Install Build Tools

```powershell
# Install SWIG (required to build pyscard)
choco install swig  # Using Chocolatey

# Or download from http://www.swig.org/download.html
# Add to PATH, then:
pip install pyscard
```

### Option 3: Use Conda

```powershell
# If using Anaconda/Miniconda
conda install -c conda-forge pyscard
```

---

## Configuration

Edit `server.py` to change settings:

```python
HOST = "localhost"  # Bind address
PORT = 3005         # WebSocket port
LOG_LEVEL = logging.INFO  # Logging verbosity
```

---

## Web Application Integration

Connect from your web application:

```javascript
// JavaScript client
const ws = new WebSocket('ws://localhost:3005');

ws.onopen = () => {
    console.log('Connected to NFC Bridge');
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('Received:', data);
};

// Start scanning with card number
ws.send(JSON.stringify({
    type: 'start_scan',
    card_number: 'AB12345678CD',
    timeout: 30
}));

// Cancel scan
ws.send(JSON.stringify({ type: 'cancel_scan' }));

// Check status
ws.send(JSON.stringify({ type: 'get_status' }));
```

---

## API Reference

### Messages from Client → Server

| Type | Parameters | Description |
|------|------------|-------------|
| `start_scan` | `card_number`, `timeout` | Start waiting for card |
| `cancel_scan` | - | Cancel current scan |
| `get_status` | - | Get server/reader status |
| `get_readers` | - | List available readers |
| `ping` | - | Keep-alive ping |

### Messages from Server → Client

| Type | Fields | Description |
|------|--------|-------------|
| `connected` | `state`, `reader_available`, `reader_name` | Initial connection |
| `status` | `status`, `message` | Status updates |
| `scan_result` | `success`, `data`, `error` | Card read result |
| `error` | `error` | Error message |
| `pong` | `timestamp` | Ping response |

---

## Supported NFC Readers

PC/SC compatible readers:
- ACR122U
- ACR1252U
- SCL3711
- Identive SCM3712
- Any PC/SC compliant reader

---

## Building Executables

To create standalone `.exe` files that can run on any Windows machine:

### Automatic Build

```powershell
# Double-click build_exe.bat or run:
.\build_exe.bat
```

### Manual Build

```powershell
# 1. Activate virtual environment
.\venv\Scripts\Activate.ps1

# 2. Install PyInstaller
pip install pyinstaller

# 3. Run build script
python build.py

# 4. Find executables in dist/ folder
```

### Build Output

The `dist/` folder will contain:

| File | Description |
|------|-------------|
| `nfc_server.exe` | Main WebSocket server |
| `nfc_launcher.exe` | Opens status page in browser |
| `nfc_service.exe` | Windows service wrapper |
| `status.html` | Browser status page |
| `install.bat` | Install as Windows service |
| `uninstall.bat` | Remove Windows service |
| `start.bat` | Run without service |

---

## Status Page

Open `status.html` in your browser (or click `nfc_launcher.exe`) to:
- Check if server is running
- See if card reader is connected
- Monitor card detection
- View activity log

---

## Project Structure

```
nfc_bridge/
├── server.py          # Main server application
├── nfc_service.py     # Windows service wrapper
├── launcher.py        # Browser launcher
├── build.py           # Build script for executables
├── status.html        # Browser status page
├── setup.ps1          # PowerShell setup script
├── run.bat            # Quick start batch file
├── run_dev.bat        # Development mode
├── build_exe.bat      # Build executables
├── requirements.txt   # Python dependencies
└── README.md          # This file
```

---

## Common PowerShell Commands Reference

```powershell
# ============================================
# ENVIRONMENT SETUP
# ============================================

# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Deactivate virtual environment
deactivate

# Delete virtual environment (if needed)
Remove-Item -Recurse -Force venv

# ============================================
# PACKAGE MANAGEMENT
# ============================================

# Install from requirements.txt
pip install -r requirements.txt

# Install single package
pip install websockets

# List installed packages
pip list

# Freeze dependencies
pip freeze > requirements.txt

# ============================================
# RUNNING THE SERVER
# ============================================

# Run directly
python server.py

# Run in background
Start-Process -NoNewWindow python server.py

# Run and save output
python server.py | Tee-Object -FilePath output.log

# ============================================
# SERVICE MANAGEMENT (Run as Admin)
# ============================================

# View all services
Get-Service

# View specific service
Get-Service NFCBridgeServer

# Start service
Start-Service NFCBridgeServer

# Stop service  
Stop-Service NFCBridgeServer

# Restart service
Restart-Service NFCBridgeServer

# ============================================
# NETWORK / PORT CHECK
# ============================================

# Check if port 3005 is in use
Get-NetTCPConnection -LocalPort 3005 -ErrorAction SilentlyContinue

# Find process using port
Get-Process -Id (Get-NetTCPConnection -LocalPort 3005).OwningProcess

# Test WebSocket connection
# (Use browser console or wscat)
# npm install -g wscat
# wscat -c ws://localhost:3005

# ============================================
# FIREWALL (if needed)
# ============================================

# Allow port 3005 inbound (Run as Admin)
New-NetFirewallRule -DisplayName "NFC Bridge" -Direction Inbound -LocalPort 3005 -Protocol TCP -Action Allow

# Remove firewall rule
Remove-NetFirewallRule -DisplayName "NFC Bridge"
```

---

## License

MIT License
