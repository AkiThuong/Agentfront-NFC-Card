@echo off
echo Starting NFC Bridge Server...
start "" nfc_server.exe
timeout /t 2 /nobreak >nul
start "" nfc_launcher.exe
