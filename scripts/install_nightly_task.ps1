$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "nightly_sync.ps1"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`""
$Trigger = New-ScheduledTaskTrigger -Daily -At 2:00AM
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun
Register-ScheduledTask -TaskName "Media Library Nightly Sync" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Refresh media catalogs and publish changes to GitHub" -Force
Write-Host "Installed Media Library Nightly Sync for 2:00 AM daily."
