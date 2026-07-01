$ErrorActionPreference = "SilentlyContinue"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$OutLog = Join-Path $LogDir "bot.out.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$processes = Get-CimInstance Win32_Process |
    Where-Object {
        ($_.Name -eq "tg-grid.exe" -or $_.Name -eq "python.exe" -or $_.Name -eq "powershell.exe") -and
        ($_.CommandLine -like "*tg-grid*run-all*" -or
         $_.CommandLine -like "*tg_grid_agent.cli*run-all*" -or
         $_.CommandLine -like "*SETKA_BOT_RUN_ALL*" -or
         $_.CommandLine -like "*tg-grid*run-admin-bot*" -or
         $_.CommandLine -like "*tg_grid_agent.cli*run-admin-bot*")
    }

foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId -Force
}

"Stopped bot processes at $(Get-Date -Format o): $($processes.ProcessId -join ', ')" | Add-Content -LiteralPath $OutLog
