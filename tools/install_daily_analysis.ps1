param(
    [string]$Project = 'C:\Users\Owner\Trend-Radar',
    [string]$Time = '21:00'
)
$ErrorActionPreference = 'Stop'
$taskScript = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'daily_analysis.py')).Path
$projectPath = (Resolve-Path -LiteralPath $Project).Path
$pythonLauncher = (Get-Command pyw.exe -ErrorAction Stop).Source
$arguments = '-3.13 -B "' + $taskScript + '" --project "' + $projectPath + '"'
$action = New-ScheduledTaskAction -Execute $pythonLauncher -Argument $arguments -WorkingDirectory $projectPath
$daily = New-ScheduledTaskTrigger -Daily -At $Time
$logon = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'Trend Radar Daily Plus Analysis' -Action $action -Trigger @($daily, $logon) -Settings $settings -Principal $principal -Description 'Analyze public evidence with local Codex ChatGPT login. Maximum one attempt per day. No paid API.' -Force | Select-Object TaskName, State
