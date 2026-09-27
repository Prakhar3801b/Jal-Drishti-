<#
    Starts the JalDrishti backend and frontend in two PowerShell windows.

    Usage:  .\run-dev.ps1
#>

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

Write-Host 'JalDrishti - starting backend (port 8000) and frontend (port 5173)' -ForegroundColor Yellow

if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
    Write-Host 'Installing frontend dependencies...' -ForegroundColor Cyan
    Push-Location (Join-Path $root 'frontend')
    npm install
    Pop-Location
}

Start-Process powershell -ArgumentList @(
    '-NoExit', '-Command',
    "Set-Location '$root\backend'; python -m uvicorn app.main:app --reload --port 8000"
)

Start-Process powershell -ArgumentList @(
    '-NoExit', '-Command',
    "Set-Location '$root\frontend'; npm run dev"
)

Write-Host ''
Write-Host '  dashboard : http://localhost:5173' -ForegroundColor Green
Write-Host '  API docs  : http://localhost:8000/docs' -ForegroundColor Green
