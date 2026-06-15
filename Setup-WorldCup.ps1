<#
.SYNOPSIS
World Cup 2026 – first-time setup and launch pipeline.

.DESCRIPTION
Validates the SQLite schema, populates match data (init mode), then launches
the Flask SPA server.  This script is the one-stop entry point for setting up
the project from scratch on a new machine.
#>

$ErrorActionPreference = "Stop"

function Write-Log {
    param (
        [Parameter(Mandatory = $true)]
        [string]$Message,
        [ValidateSet('INFO', 'SUCCESS', 'WARNING', 'ERROR')]
        [string]$Level = 'INFO'
    )
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    switch ($Level) {
        'INFO'    { Write-Host "[$timestamp] [INFO] $Message" -ForegroundColor Cyan }
        'SUCCESS' { Write-Host "[$timestamp] [SUCCESS] $Message" -ForegroundColor Green }
        'WARNING' { Write-Host "[$timestamp] [WARNING] $Message" -ForegroundColor Yellow }
        'ERROR'   { Write-Host "[$timestamp] [ERROR] $Message" -ForegroundColor Red }
    }
}

Write-Log "Starting World Cup 2026 Aggregator Setup Pipeline..." 'INFO'

# 1. Verify Python installation
try {
    $pythonVersion = & python --version 2>&1
    Write-Log "Python runtime detected: $pythonVersion" 'INFO'
} catch {
    Write-Log "Python is not installed or not in PATH." 'ERROR'
    exit 1
}

# 2. Set working directory
$scriptPath = $PSScriptRoot
if (-not $scriptPath) {
    $scriptPath = (Get-Location).Path
}
Set-Location -Path $scriptPath
Write-Log "Working directory set to: $scriptPath" 'INFO'

# 3. Install dependencies
Write-Log "Installing Python dependencies from src/requirements.txt..." 'INFO'
python -m pip install -r src/requirements.txt --quiet

# 4. Database schema initialisation (idempotent)
Write-Log "Step 1: Verifying database schema..." 'INFO'
try {
    $dbOutput = & python src/init_db.py 2>&1
    if ($LASTEXITCODE -ne 0) { throw $dbOutput }
    Write-Log "Database schema verified." 'SUCCESS'
} catch {
    Write-Log "Database schema verification failed: $_" 'ERROR'
    exit 1
}

# 5. Initial data population (init mode — skipped if DB already populated)
Write-Log "Step 2: Initiating data ingestion (init mode)..." 'INFO'
try {
    $scrapeOutput = & python src/scrape_and_store.py --mode init 2>&1
    if ($LASTEXITCODE -eq 2) {
        Write-Log "Database already populated; skipping init data load." 'WARNING'
    } elseif ($LASTEXITCODE -ne 0) {
        throw $scrapeOutput
    } else {
        Write-Log "Initial data population completed." 'SUCCESS'
    }
} catch {
    Write-Log "Data ingestion failed: $_" 'ERROR'
    exit 1
}

# 6. Start Flask SPA server
Write-Log "Step 3: Starting Flask server (http://127.0.0.1:5000)..." 'INFO'
try {
    $serverUrl = "http://127.0.0.1:5000"
    Start-Process $serverUrl
    & python src/app.py 2>&1
} catch {
    Write-Log "Failed to start server. Run Start-WorldCupServer.ps1 manually." 'ERROR'
    exit 1
}
