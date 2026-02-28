$ErrorActionPreference = "Stop"

Write-Host "Stopping any existing server on port 8000..." -ForegroundColor Cyan

# Find and stop any process listening on port 8000
$pids = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

foreach ($processId in $pids) {
    try {
        # Stop the process and all its children
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-Host "Stopped PID $processId" -ForegroundColor Yellow
    } catch {
        Write-Host "PID $processId already stopped" -ForegroundColor DarkYellow
    }
}

# Also stop any uvicorn/python processes that might be running the API
$apiProcesses = Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*uvicorn*" -or $_.CommandLine -like "*api.main*" }

foreach ($proc in $apiProcesses) {
    try {
        Stop-Process -Id $proc.Id -Force -ErrorAction Stop
        Write-Host "Stopped API process PID $($proc.Id)" -ForegroundColor Yellow
    } catch {
        # Process already stopped
    }
}

if ($pids.Count -gt 0) {
    Write-Host "Waiting for port to be released..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}

Write-Host "Starting API server..." -ForegroundColor Green
python run_api.py
