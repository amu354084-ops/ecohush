param(
  [string]$ScriptPath = (Join-Path $PSScriptRoot "download_daily_backup.ps1"),
  [string]$TaskName = "ERP daily cloud backup",
  [string]$RunAt = "03:15"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $ScriptPath)) {
  throw "Backup script not found: $ScriptPath"
}

$time = [DateTime]::ParseExact($RunAt, "HH:mm", $null)
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At $time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "Scheduled task '$TaskName' registered for $RunAt every day."
