$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $ScriptDir "logs"
$Runner = Join-Path $ScriptDir "zoho_monthly_tickets.py"

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Stdout = Join-Path $LogDir "zoho_monthly_tickets_$Timestamp.out.log"
$Stderr = Join-Path $LogDir "zoho_monthly_tickets_$Timestamp.err.log"

Set-Location -LiteralPath $ScriptDir
$process = Start-Process `
    -FilePath "python" `
    -ArgumentList "`"$Runner`"" `
    -WorkingDirectory $ScriptDir `
    -NoNewWindow `
    -Wait `
    -PassThru `
    -RedirectStandardOutput $Stdout `
    -RedirectStandardError $Stderr

if ($process.ExitCode -ne 0) {
    throw "Zoho monthly tickets failed with exit code $($process.ExitCode). See $Stdout and $Stderr."
}
