# Script: One-command Demo Up with Anvil State Persistence (Anvil :8545 + Contracts + FastAPI :8000 + Next.js :3000)
$ErrorActionPreference = "Continue"
$RootDir = (Resolve-Path "$PSScriptRoot\..").Path
$AnvilStateFile = Join-Path $RootDir "anvil_state.json"
$AnvilExe = if (Test-Path "$RootDir\tools\foundry\anvil.exe") { "$RootDir\tools\foundry\anvil.exe" } else { "$env:USERPROFILE\.foundry\bin\anvil.exe" }

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " STARTING RWA REAL ESTATE TOKENIZATION SYSTEM - ANVIL LAB (:8545) " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

$hadState = Test-Path $AnvilStateFile

# 1. Start local Anvil node on port 8545 with persistent state file
$anvilRunning = Get-NetTCPConnection -LocalPort 8545 -State Listen -ErrorAction SilentlyContinue
if (-not $anvilRunning) {
    Write-Host "`n[1/4] Starting local Anvil blockchain (:8545, Chain ID 31337, persistent state)..." -ForegroundColor Yellow
    Start-Process -FilePath $AnvilExe -ArgumentList "--port 8545 --chain-id 31337 --block-time 1 --state `"$AnvilStateFile`" --state-interval 5" -WindowStyle Minimized
    Start-Sleep -Seconds 3
} else {
    Write-Host "`n[1/4] Local Anvil node is already running on :8545" -ForegroundColor Green
}

# 2. Deploy 6 Smart Contracts only if starting fresh (or if state file did not exist)
if (-not $hadState) {
    Write-Host "[2/4] Fresh chain detected -> Deploying 6 Smart Contracts (Deploy.s.sol)..." -ForegroundColor Yellow
    powershell -ExecutionPolicy Bypass -File "$RootDir\scripts\deploy_local.ps1"
} else {
    Write-Host "[2/4] Loaded existing blockchain state from anvil_state.json (skipping re-deploy)" -ForegroundColor Green
}

# 3. Start Backend FastAPI (:8000) if not already listening
$backendRunning = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $backendRunning) {
    Write-Host "[3/4] Starting Backend FastAPI at http://127.0.0.1:8000 ..." -ForegroundColor Yellow
    Start-Process -FilePath "python" -ArgumentList "-m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload" -WorkingDirectory "$RootDir" -WindowStyle Minimized
    Start-Sleep -Seconds 3
} else {
    Write-Host "[3/4] Backend FastAPI is already running on :8000" -ForegroundColor Green
}

# 4. Start Frontend Next.js (:3000) if not already listening
$frontendRunning = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
if (-not $frontendRunning) {
    Write-Host "[4/4] Starting Frontend Next.js Web UI at http://localhost:3000 ..." -ForegroundColor Yellow
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev" -WorkingDirectory "$RootDir\frontend" -WindowStyle Minimized
    Start-Sleep -Seconds 4
} else {
    Write-Host "[4/4] Frontend Next.js Web UI is already running on :3000" -ForegroundColor Green
}

Write-Host "`n======================================================================" -ForegroundColor Green
Write-Host " RWA SYSTEM IS LIVE AND READY!" -ForegroundColor Green
Write-Host " - Web UI (Session Lab)   : http://localhost:3000/login" -ForegroundColor White
Write-Host " - OpenAPI Docs (Swagger) : http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host " - Local Anvil RPC        : http://127.0.0.1:8545 (Chain ID 31337)" -ForegroundColor White
Write-Host " - Anvil State File       : $AnvilStateFile" -ForegroundColor Gray
Write-Host "======================================================================" -ForegroundColor Green
