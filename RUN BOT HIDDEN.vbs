Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """" & WScript.CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\RUN BOT.bat""", 0, False
Set WshShell = Nothing