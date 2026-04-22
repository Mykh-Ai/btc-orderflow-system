# demo_aggregator.ps1
# Run from repository root: ./demo_aggregator.ps1

$ErrorActionPreference = "Stop"

# Ensure output folders exist on host
New-Item -ItemType Directory -Force -Path ".\data\feed",".\data\logs" | Out-Null

Write-Host "Starting Aggregator (Docker Compose demo)..." -ForegroundColor Green
docker compose -f .\docker-compose.demo.yml up -d --remove-orphans

Write-Host ""
Write-Host "Aggregator is running." -ForegroundColor Green
Write-Host "Live view: aggregated.csv (tail 12) + trades_log.txt (tail 8)" -ForegroundColor Cyan
Write-Host "Stop: Ctrl+C (container will keep running). To stop container: docker compose -f docker-compose.demo.yml down"
Write-Host ""

Start-Sleep -Seconds 2

while ($true) {
  Clear-Host

  Write-Host "=== aggregated.csv (tail 12) ===" -ForegroundColor Cyan
  if (Test-Path ".\data\feed\aggregated.csv") {
    Get-Content ".\data\feed\aggregated.csv" -Tail 12
  } else {
    Write-Host "Waiting for data/feed/aggregated.csv ..." -ForegroundColor Yellow
  }

  Write-Host ""
  Write-Host "=== trades_log.txt (tail 8) ===" -ForegroundColor Cyan
  if (Test-Path ".\data\logs\trades_log.txt") {
    Get-Content ".\data\logs\trades_log.txt" -Tail 8
  } else {
    Write-Host "Waiting for data/logs/trades_log.txt ..." -ForegroundColor Yellow
  }

  Start-Sleep -Seconds 3
}
