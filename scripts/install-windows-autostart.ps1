$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$StartupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$Shortcut = Join-Path $StartupDir "SetkaTgGridAgent.cmd"
$StartScript = Join-Path $ProjectRoot "scripts\start-bot.ps1"

New-Item -ItemType Directory -Force -Path $StartupDir | Out-Null

@"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$StartScript"
"@ | Set-Content -LiteralPath $Shortcut -Encoding ASCII

Write-Host "Installed autostart: $Shortcut"
