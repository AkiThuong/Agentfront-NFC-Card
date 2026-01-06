# =============================================================================
# NFC Bridge - Install as Startup Task (Alternative to Windows Service)
# =============================================================================
# This script creates a Windows Scheduled Task that runs at login
# Does NOT require NSSM, simpler setup
# 
# Run as Administrator: .\install-startup-task.ps1
# =============================================================================

param(
    [switch]$Uninstall
)

$TaskName = "NFCBridgeServer"
$ProjectRoot = $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot "venv\Scripts\pythonw.exe"  # pythonw = no console window
$ServerScript = Join-Path $ProjectRoot "server.py"

# Check admin privileges
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "ERROR: Please run as Administrator" -ForegroundColor Red
    exit 1
}

if ($Uninstall) {
    Write-Host "Removing startup task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Done!" -ForegroundColor Green
    exit 0
}

# Check if venv exists
if (-not (Test-Path $PythonExe)) {
    Write-Host "ERROR: Virtual environment not found!" -ForegroundColor Red
    Write-Host "       Run setup.ps1 first" -ForegroundColor Red
    exit 1
}

Write-Host "Creating startup task..." -ForegroundColor Yellow

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Create the task action
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument $ServerScript -WorkingDirectory $ProjectRoot

# Create trigger (at logon)
$Trigger = New-ScheduledTaskTrigger -AtLogOn

# Create settings
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# Create principal (run as current user)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

# Register the task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "NFC Bridge WebSocket Server for Zairyu Card reading"

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  Startup Task Installed!" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "The NFC Bridge will start automatically when you log in." -ForegroundColor White
Write-Host ""
Write-Host "To start now:" -ForegroundColor Gray
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Gray
Write-Host ""
Write-Host "To check status:" -ForegroundColor Gray
Write-Host "  Get-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Gray
Write-Host ""
Write-Host "To uninstall:" -ForegroundColor Gray
Write-Host "  .\install-startup-task.ps1 -Uninstall" -ForegroundColor Gray
Write-Host ""

# Offer to start now
$response = Read-Host "Start the task now? (Y/n)"
if ($response -ne 'n' -and $response -ne 'N') {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Task started! Server running on ws://localhost:3005" -ForegroundColor Green
}
