NFC Bridge Server
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
