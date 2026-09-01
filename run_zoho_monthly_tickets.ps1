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
& python "$Runner" > "$Stdout" 2> "$Stderr"
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    throw "Zoho monthly tickets failed with exit code $exitCode. See $Stdout and $Stderr."
}
