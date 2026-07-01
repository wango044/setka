$ErrorActionPreference = "Stop"

$StartupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$Shortcut = Join-Path $StartupDir "SetkaTgGridAgent.cmd"

if (Test-Path -LiteralPath $Shortcut) {
    Remove-Item -LiteralPath $Shortcut -Force
    Write-Host "Removed autostart: $Shortcut"
} else {
    Write-Host "Autostart entry not found."
}
