# =============================================================================
# NFC Bridge - Setup Script for Windows PowerShell
# =============================================================================
# Run this script in PowerShell as Administrator (for service installation)
# Usage: .\setup.ps1
# =============================================================================

param(
    [switch]$InstallService,
    [switch]$UninstallService,
    [switch]$StartService,
    [switch]$StopService
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot "venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$ServiceName = "NFCBridgeServer"

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  NFC Bridge Server - Setup Script" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# -----------------------------------------------------------------------------
# Function: Check if running as Administrator
# -----------------------------------------------------------------------------
function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# -----------------------------------------------------------------------------
# Function: Create Virtual Environment
# -----------------------------------------------------------------------------
function New-VirtualEnvironment {
    Write-Host "[1/4] Creating virtual environment..." -ForegroundColor Yellow
    
    if (Test-Path $VenvPath) {
        Write-Host "      Virtual environment already exists." -ForegroundColor Gray
    } else {
        python -m venv $VenvPath
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: Failed to create virtual environment" -ForegroundColor Red
            Write-Host "Make sure Python is installed and in PATH" -ForegroundColor Red
            exit 1
        }
        Write-Host "      Virtual environment created." -ForegroundColor Green
    }
}

# -----------------------------------------------------------------------------
# Function: Activate Virtual Environment
# -----------------------------------------------------------------------------
function Enable-VirtualEnvironment {
    Write-Host "[2/4] Activating virtual environment..." -ForegroundColor Yellow
    
    $activateScript = Join-Path $VenvPath "Scripts\Activate.ps1"
    if (Test-Path $activateScript) {
        & $activateScript
        Write-Host "      Virtual environment activated." -ForegroundColor Green
    } else {
        Write-Host "ERROR: Activate script not found" -ForegroundColor Red
        exit 1
    }
}

# -----------------------------------------------------------------------------
# Function: Install Dependencies
# -----------------------------------------------------------------------------
function Install-Dependencies {
    Write-Host "[3/4] Installing dependencies..." -ForegroundColor Yellow
    
    # Upgrade pip first
    & $PythonExe -m pip install --upgrade pip | Out-Null
    
    # Install requirements
    $requirementsPath = Join-Path $ProjectRoot "requirements.txt"
    if (Test-Path $requirementsPath) {
        & $PythonExe -m pip install -r $requirementsPath
    } else {
        # Install individually if no requirements.txt
        & $PythonExe -m pip install websockets pyscard pywin32
    }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARNING: Some packages may have failed to install" -ForegroundColor Yellow
        Write-Host "         pyscard requires swig - see README for manual installation" -ForegroundColor Yellow
    } else {
        Write-Host "      Dependencies installed." -ForegroundColor Green
    }
}

# -----------------------------------------------------------------------------
# Function: Test Setup
# -----------------------------------------------------------------------------
function Test-Setup {
    Write-Host "[4/4] Testing setup..." -ForegroundColor Yellow
    
    $testScript = @"
import sys
print(f"Python: {sys.version}")
try:
    import websockets
    print("websockets: OK")
except ImportError as e:
    print(f"websockets: FAILED - {e}")
try:
    from smartcard.System import readers
    r = readers()
    print(f"pyscard: OK - {len(r)} reader(s) found")
    for reader in r:
        print(f"         - {reader}")
except ImportError as e:
    print(f"pyscard: FAILED - {e}")
except Exception as e:
    print(f"pyscard: OK (no readers connected)")
"@
    
    & $PythonExe -c $testScript
    Write-Host ""
}

# -----------------------------------------------------------------------------
# Function: Install Windows Service using NSSM
# -----------------------------------------------------------------------------
function Install-NFCService {
    if (-not (Test-Administrator)) {
        Write-Host "ERROR: Administrator privileges required for service installation" -ForegroundColor Red
        Write-Host "       Please run PowerShell as Administrator" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "Installing Windows Service..." -ForegroundColor Yellow
    
    # Check for NSSM
    $nssmPath = Join-Path $ProjectRoot "nssm.exe"
    if (-not (Test-Path $nssmPath)) {
        Write-Host "Downloading NSSM (Non-Sucking Service Manager)..." -ForegroundColor Gray
        $nssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
        $nssmZip = Join-Path $ProjectRoot "nssm.zip"
        
        try {
            Invoke-WebRequest -Uri $nssmUrl -OutFile $nssmZip
            Expand-Archive -Path $nssmZip -DestinationPath $ProjectRoot -Force
            
            # Find and copy the exe
            $nssmExe = Get-ChildItem -Path $ProjectRoot -Recurse -Filter "nssm.exe" | 
                       Where-Object { $_.Directory.Name -eq "win64" } | 
                       Select-Object -First 1
            if ($nssmExe) {
                Copy-Item $nssmExe.FullName $nssmPath
            }
            
            # Cleanup
            Remove-Item $nssmZip -Force
            Remove-Item (Join-Path $ProjectRoot "nssm-*") -Recurse -Force -ErrorAction SilentlyContinue
        } catch {
            Write-Host "ERROR: Failed to download NSSM" -ForegroundColor Red
            Write-Host "       Please download manually from https://nssm.cc" -ForegroundColor Red
            exit 1
        }
    }
    
    # Install service
    $serverScript = Join-Path $ProjectRoot "server.py"
    
    & $nssmPath install $ServiceName $PythonExe $serverScript
    & $nssmPath set $ServiceName AppDirectory $ProjectRoot
    & $nssmPath set $ServiceName DisplayName "NFC Bridge Server"
    & $nssmPath set $ServiceName Description "WebSocket bridge for NFC card readers"
    & $nssmPath set $ServiceName Start SERVICE_AUTO_START
    & $nssmPath set $ServiceName AppStdout (Join-Path $ProjectRoot "service_stdout.log")
    & $nssmPath set $ServiceName AppStderr (Join-Path $ProjectRoot "service_stderr.log")
    
    Write-Host "Service '$ServiceName' installed successfully!" -ForegroundColor Green
    Write-Host "Use: .\setup.ps1 -StartService to start" -ForegroundColor Gray
}

# -----------------------------------------------------------------------------
# Function: Uninstall Windows Service
# -----------------------------------------------------------------------------
function Uninstall-NFCService {
    if (-not (Test-Administrator)) {
        Write-Host "ERROR: Administrator privileges required" -ForegroundColor Red
        exit 1
    }
    
    $nssmPath = Join-Path $ProjectRoot "nssm.exe"
    if (Test-Path $nssmPath) {
        & $nssmPath stop $ServiceName confirm
        & $nssmPath remove $ServiceName confirm
        Write-Host "Service removed." -ForegroundColor Green
    } else {
        # Try native sc command
        Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        sc.exe delete $ServiceName
    }
}

# -----------------------------------------------------------------------------
# Function: Start Service
# -----------------------------------------------------------------------------
function Start-NFCService {
    Write-Host "Starting service..." -ForegroundColor Yellow
    Start-Service -Name $ServiceName
    Write-Host "Service started." -ForegroundColor Green
}

# -----------------------------------------------------------------------------
# Function: Stop Service
# -----------------------------------------------------------------------------
function Stop-NFCService {
    Write-Host "Stopping service..." -ForegroundColor Yellow
    Stop-Service -Name $ServiceName -Force
    Write-Host "Service stopped." -ForegroundColor Green
}

# -----------------------------------------------------------------------------
# Main Execution
# -----------------------------------------------------------------------------
if ($InstallService) {
    Install-NFCService
} elseif ($UninstallService) {
    Uninstall-NFCService
} elseif ($StartService) {
    Start-NFCService
} elseif ($StopService) {
    Stop-NFCService
} else {
    # Default: Setup environment
    New-VirtualEnvironment
    Enable-VirtualEnvironment
    Install-Dependencies
    Test-Setup
    
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host "  Setup Complete!" -ForegroundColor Green
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "To run the server manually:" -ForegroundColor White
    Write-Host "  .\venv\Scripts\Activate.ps1" -ForegroundColor Gray
    Write-Host "  python server.py" -ForegroundColor Gray
    Write-Host ""
    Write-Host "To install as Windows Service (run as Admin):" -ForegroundColor White
    Write-Host "  .\setup.ps1 -InstallService" -ForegroundColor Gray
    Write-Host "  .\setup.ps1 -StartService" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Server will run on: ws://localhost:3005" -ForegroundColor Yellow
    Write-Host ""
}
