' NFC Bridge Server - Background Launcher
' This script starts the server without showing a console window
' Perfect for auto-start at Windows login

On Error Resume Next

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

' Get script directory
scriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)

' Build paths - use python.exe (not pythonw.exe) for better compatibility
activateScript = scriptDir & "\venv\Scripts\activate.bat"
pythonExe = scriptDir & "\venv\Scripts\python.exe"
serverScript = scriptDir & "\server.py"

' Check if venv exists
If Not FSO.FileExists(pythonExe) Then
    ' Try to show error in log
    Set logFile = FSO.CreateTextFile(scriptDir & "\startup_error.log", True)
    logFile.WriteLine "ERROR: Virtual environment not found at " & pythonExe
    logFile.WriteLine "Please run start_server.bat first."
    logFile.Close
    WScript.Quit 1
End If

' Log startup attempt
Set logFile = FSO.CreateTextFile(scriptDir & "\startup.log", True)
logFile.WriteLine "Starting NFC Bridge Server at " & Now()
logFile.WriteLine "Script dir: " & scriptDir
logFile.WriteLine "Python: " & pythonExe
logFile.Close

' Change to script directory
WshShell.CurrentDirectory = scriptDir

' Run using cmd.exe to properly activate venv and run server
' This ensures all environment variables are set correctly
cmdLine = "cmd.exe /c ""cd /d """ & scriptDir & """ && call venv\Scripts\activate.bat && python server.py"""
WshShell.Run cmdLine, 0, False
