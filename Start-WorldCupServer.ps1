<#
.SYNOPSIS
World Cup 2026 — quick-start Flask SPA server launcher.
#>

$ErrorActionPreference = "Stop"

# ── Working directory (portable across any directory) ──────────────────────
$scriptPath = $PSScriptRoot
if (-not $scriptPath) {
    $scriptPath = (Get-Location).Path
}
Set-Location -Path $scriptPath

# ── Dependency installation ───────────────────────────────────────────────
Write-Host "Installing dependencies from src/requirements.txt..." -ForegroundColor Cyan
python -m pip install -r src/requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Dependency installation failed. Check Python and network." -ForegroundColor Red
    exit 1
}

# ── Launch server ──────────────────────────────────────────────────────────
Write-Host "Starting World Cup 2026 Aggregator Server..." -ForegroundColor Green
Write-Host "Server will run on http://127.0.0.1:5000" -ForegroundColor Yellow
Write-Host "Open http://127.0.0.1:5000 in your browser." -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow
Write-Host ""

python src/app.py
