$ErrorActionPreference = "Stop"

Write-Host "Stopping any existing server on port 8000..." -ForegroundColor Cyan

# Find and stop any process listening on port 8000
$pids = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

foreach ($processId in $pids) {
    try {
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-Host "Stopped PID $processId" -ForegroundColor Yellow
    } catch {
        Write-Host "PID $processId already stopped" -ForegroundColor DarkYellow
    }
}

Write-Host "Starting API server..." -ForegroundColor Green
python run_api.py
