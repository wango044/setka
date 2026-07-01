$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TgGrid = Join-Path $ProjectRoot ".venv\Scripts\tg-grid.exe"
$LogDir = Join-Path $ProjectRoot "logs"
$OutLog = Join-Path $LogDir "bot.out.log"
$ErrLog = Join-Path $LogDir "bot.err.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location -LiteralPath $ProjectRoot

$existing = Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $PID -and
        ($_.Name -eq "tg-grid.exe" -or $_.Name -eq "python.exe" -or $_.Name -eq "powershell.exe") -and
        ($_.CommandLine -like "*tg-grid*run-all*" -or
         $_.CommandLine -like "*tg_grid_agent.cli*run-all*" -or
         $_.CommandLine -like "*SETKA_BOT_RUN_ALL*")
    }

if ($existing) {
    "Bot is already running: $($existing.ProcessId -join ', ')" | Add-Content -LiteralPath $OutLog
    exit 0
}

$Command = @"
`$env:SETKA_BOT_RUN_ALL = '1'
Set-Location -LiteralPath '$ProjectRoot'
& '$TgGrid' run-all --config config.yaml >> '$OutLog' 2>> '$ErrLog'
"@

Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Command `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden

"Started bot at $(Get-Date -Format o)" | Add-Content -LiteralPath $OutLog
