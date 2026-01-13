' NFC Bridge Server - Background Launcher
' This script starts the server without showing a console window
' Perfect for auto-start at Windows login

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

' Get script directory
scriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)

' Build paths
pythonExe = scriptDir & "\venv\Scripts\pythonw.exe"
serverScript = scriptDir & "\server.py"

' Check if venv exists
If Not FSO.FileExists(pythonExe) Then
    MsgBox "Virtual environment not found!" & vbCrLf & vbCrLf & _
           "Please run start_server.bat first to set up the environment.", _
           vbExclamation, "NFC Bridge Server"
    WScript.Quit 1
End If

' Change to script directory and run server
WshShell.CurrentDirectory = scriptDir
WshShell.Run """" & pythonExe & """ """ & serverScript & """", 0, False

' Optional: Show notification (comment out if not needed)
' MsgBox "NFC Bridge Server started on port 3005", vbInformation, "NFC Bridge"
