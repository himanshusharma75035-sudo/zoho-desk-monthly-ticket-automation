Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
runner = fso.BuildPath(scriptDir, "run_zoho_monthly_tickets.ps1")

shell.CurrentDirectory = scriptDir
exitCode = shell.Run("powershell.exe -NoProfile -ExecutionPolicy Bypass -File " & Chr(34) & runner & Chr(34), 0, True)
WScript.Quit exitCode
