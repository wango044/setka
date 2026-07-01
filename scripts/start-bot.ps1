$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogDir = Join-Path $ProjectRoot "logs"
$OutLog = Join-Path $LogDir "bot.out.log"
$ErrLog = Join-Path $LogDir "bot.err.log"
$RunOutLog = Join-Path $LogDir "bot.run.out.log"
$RunErrLog = Join-Path $LogDir "bot.run.err.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location -LiteralPath $ProjectRoot

$existing = Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $PID -and
        ($_.Name -eq "tg-grid.exe" -or $_.Name -eq "python.exe") -and
        ($_.CommandLine -like "*tg-grid*run-all*" -or
         $_.CommandLine -like "*tg_grid_agent.cli*run-all*")
    }

if ($existing) {
    "Bot is already running: $($existing.ProcessId -join ', ')" | Add-Content -LiteralPath $OutLog
    exit 0
}

Start-Process `
    -FilePath $Python `
    -ArgumentList "-m", "tg_grid_agent.cli", "run-all", "--config", "config.yaml" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $RunOutLog `
    -RedirectStandardError $RunErrLog

"Started bot at $(Get-Date -Format o)" | Add-Content -LiteralPath $OutLog
