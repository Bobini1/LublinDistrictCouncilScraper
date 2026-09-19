[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = 'LublinDistrictCouncilNotifier',
    [string]$PythonPath = ''
)

$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
if (-not $PythonPath) { $PythonPath = Join-Path $projectDir '.venv\Scripts\python.exe' }
$pythonExe = (Resolve-Path -LiteralPath $PythonPath).Path
$pythonWindowless = Join-Path (Split-Path -Parent $pythonExe) 'pythonw.exe'
$entryPoint = Join-Path $projectDir 'run_mattermost_scheduled.py'
$envFile = Join-Path $projectDir '.env'
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent()

if (-not (Test-Path -LiteralPath $pythonWindowless -PathType Leaf)) {
    throw "Cannot find pythonw.exe next to $pythonExe. Use a Windows Python installation."
}
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw 'Copy .env.example to .env and fill in the three Mattermost values first.'
}
if ((Get-TimeZone).Id -notin @('Central European Standard Time', 'Europe/Warsaw')) {
    throw 'The Friday 18:00 trigger requires the Windows time zone to be set to Warsaw.'
}

# Check dependencies without loading secrets or making network requests.
& $pythonExe -c "import dotenv, requests, bs4; from zoneinfo import ZoneInfo; ZoneInfo('Europe/Warsaw')"
if ($LASTEXITCODE -ne 0) {
    throw 'Install requirements.txt in the selected Python environment first.'
}

$arguments = '"{0}"' -f $entryPoint
$existing = Get-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction SilentlyContinue
$existingUserSid = ''
if ($existing) {
    $existingUserSid = $existing.Principal.UserId
    if ($existingUserSid -notmatch '^S-1-') {
        $existingAccount = New-Object System.Security.Principal.NTAccount($existingUserSid)
        $existingUserSid = $existingAccount.Translate([System.Security.Principal.SecurityIdentifier]).Value
    }
}
if ($existing -and (
    $existing.Actions.Count -ne 1 -or
    $existing.Actions[0].Arguments -ne $arguments -or
    $existingUserSid -ne $taskUser.User.Value
)) {
    throw "A different task already uses the name $TaskName. Choose another -TaskName."
}

$action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument $arguments -WorkingDirectory $projectDir
$now = Get-Date
$triggers = @(foreach ($hour in @(0, 4, 8, 12, 16, 20)) {
    $start = $now.Date.AddHours($hour).AddMinutes(17)
    if ($start -le $now) { $start = $start.AddDays(1) }
    $trigger = New-ScheduledTaskTrigger -Daily -At $start
    # No fixed UTC offset: follow Windows local time across daylight saving.
    $trigger.StartBoundary = $start.ToString("yyyy-MM-dd'T'HH:mm:ss")
    $trigger
})
$friday = $now.Date.AddDays((5 - [int]$now.DayOfWeek + 7) % 7).AddHours(18)
if ($friday -le $now) { $friday = $friday.AddDays(7) }
$weeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At $friday
$weeklyTrigger.StartBoundary = $friday.ToString("yyyy-MM-dd'T'HH:mm:ss")
$triggers += $weeklyTrigger
$triggers += New-ScheduledTaskTrigger -AtLogOn -User $taskUser.Name

$principal = New-ScheduledTaskPrincipal -UserId $taskUser.User.Value -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 10)

if ($PSCmdlet.ShouldProcess($TaskName, 'Protect .env and register the background notifier for this Windows user')) {
    # .env is plaintext: restrict it to this user, administrators and SYSTEM.
    # Build only a DACL, without rewriting owner/audit information (which can
    # require elevated privileges when reinstalling the task).
    $acl = New-Object System.Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @($taskUser.User.Value, 'S-1-5-18', 'S-1-5-32-544')) {
        $identity = New-Object System.Security.Principal.SecurityIdentifier($sid)
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow')
        $acl.AddAccessRule($rule)
    }
    $envItem = Get-Item -LiteralPath $envFile -Force
    $envItem.SetAccessControl($acl)

    Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Action $action `
        -Trigger $triggers -Principal $principal -Settings $settings -Force `
        -Description 'Lublin weekly Mattermost digest: Friday 18:00 Warsaw, four-hour refreshes and logon catch-up. Requires this user to be signed in.' | Out-Null
    Write-Output "Registered $TaskName. Runs while you are signed in, including when locked; does not wake the PC."
    Write-Output 'Fill in .env locally before the first live run. Logs: .logs\mattermost.log'
    Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath '\' |
        Select-Object TaskName, NextRunTime, LastRunTime, LastTaskResult
}
