param(
    [string]$TaskName = "Zoho Desk Monthly Tickets",
    [string]$Python = "python",
    [string]$FirstDayTime = "11:00",
    [string]$ThirdDayTime = "10:00",
    [string]$SeventhDayTime = "15:00"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "zoho_monthly_tickets.py"
$TaskRunner = Join-Path $ScriptDir "run_zoho_monthly_tickets.ps1"
$TaskLauncher = Join-Path $ScriptDir "run_zoho_monthly_tickets_hidden.vbs"

if (-not (Test-Path -LiteralPath $Runner)) {
    throw "Runner not found: $Runner"
}
if (-not (Test-Path -LiteralPath $TaskRunner)) {
    throw "Task runner not found: $TaskRunner"
}
if (-not (Test-Path -LiteralPath $TaskLauncher)) {
    throw "Hidden task launcher not found: $TaskLauncher"
}

$service = New-Object -ComObject Schedule.Service
$service.Connect()
$rootFolder = $service.GetFolder("\")
$task = $service.NewTask(0)

$task.RegistrationInfo.Description = "Create Zoho Desk tickets on configured monthly days and notify Telegram."
$task.Settings.Enabled = $true
$task.Settings.StartWhenAvailable = $true
$task.Settings.MultipleInstances = 2
$task.Settings.DisallowStartIfOnBatteries = $false
$task.Settings.StopIfGoingOnBatteries = $false
$task.Settings.Hidden = $true

$principal = $task.Principal
$principal.LogonType = 3
$principal.RunLevel = 0

function Add-MonthlyTrigger {
    param(
        [object]$Task,
        [int]$DayOfMonth,
        [string]$Time
    )

    if ($DayOfMonth -lt 1 -or $DayOfMonth -gt 31) {
        throw "Invalid day of month: $DayOfMonth"
    }

    $timeParts = $Time.Split(":")
    if ($timeParts.Count -ne 2) {
        throw "Time must be in HH:mm format."
    }

    $trigger = $Task.Triggers.Create(4)
    $trigger.Enabled = $true
    $trigger.DaysOfMonth = 1 -shl ($DayOfMonth - 1)
    $trigger.MonthsOfYear = 4095
    $start = Get-Date -Hour ([int]$timeParts[0]) -Minute ([int]$timeParts[1]) -Second 0
    $trigger.StartBoundary = $start.ToString("yyyy-MM-ddTHH:mm:ss")
}

Add-MonthlyTrigger -Task $task -DayOfMonth 1 -Time $FirstDayTime
Add-MonthlyTrigger -Task $task -DayOfMonth 3 -Time $ThirdDayTime
Add-MonthlyTrigger -Task $task -DayOfMonth 7 -Time $SeventhDayTime

$action = $task.Actions.Create(0)
$action.Path = "wscript.exe"
$action.Arguments = "//B //Nologo `"$TaskLauncher`""
$action.WorkingDirectory = $ScriptDir

$null = $rootFolder.RegisterTaskDefinition($TaskName, $task, 6, $null, $null, 3)

Write-Host "Scheduled task '$TaskName' created for day 1 at $FirstDayTime, day 3 at $ThirdDayTime, and day 7 at $SeventhDayTime."
