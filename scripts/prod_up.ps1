# Script: Official Production Launcher (Anvil :8545 + FastAPI :8000 + Next.js Production :3000)
$ErrorActionPreference = "Continue"
$RootDir = (Resolve-Path "$PSScriptRoot\..").Path
$AnvilStateFile = Join-Path $RootDir "anvil_state.json"
$AnvilExe = if (Test-Path "$RootDir\tools\foundry\anvil.exe") { "$RootDir\tools\foundry\anvil.exe" } else { "$env:USERPROFILE\.foundry\bin\anvil.exe" }

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " RWA REAL ESTATE TOKENIZATION PLATFORM - OFFICIAL PRODUCTION LAUNCH " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

$hadState = Test-Path $AnvilStateFile

# 1. Start local Anvil node on port 8545 with persistent state file
$anvilRunning = Get-NetTCPConnection -LocalPort 8545 -State Listen -ErrorAction SilentlyContinue
if (-not $anvilRunning) {
    Write-Host "`n[1/4] Starting Anvil EVM Node (:8545, Chain ID 31337, persistent state)..." -ForegroundColor Yellow
    Start-Process -FilePath $AnvilExe -ArgumentList "--port 8545 --chain-id 31337 --block-time 1 --state `"$AnvilStateFile`" --state-interval 5" -WindowStyle Minimized
    Start-Sleep -Seconds 3
} else {
    Write-Host "`n[1/4] Anvil EVM Node is already running on :8545" -ForegroundColor Green
}

# 2. Deploy Smart Contracts if fresh chain
if (-not $hadState) {
    Write-Host "[2/4] Deploying 6 Smart Contracts (Deploy.s.sol)..." -ForegroundColor Yellow
    powershell -ExecutionPolicy Bypass -File "$RootDir\scripts\deploy_local.ps1"
} else {
    Write-Host "[2/4] Loaded persistent chain state from anvil_state.json" -ForegroundColor Green
}

# 3. Start Backend FastAPI (:8000) in production mode (no reload overhead)
$backendRunning = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $backendRunning) {
    Write-Host "[3/4] Starting FastAPI Production Server at http://127.0.0.1:8000 ..." -ForegroundColor Yellow
    Start-Process -FilePath "python" -ArgumentList "-m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000" -WorkingDirectory "$RootDir" -WindowStyle Minimized
    Start-Sleep -Seconds 3
} else {
    Write-Host "[3/4] FastAPI Server is already running on :8000" -ForegroundColor Green
}

# 4. Build (if needed) & Start Next.js Production Server (:3000)
$frontendRunning = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
if (-not $frontendRunning) {
    if (-not (Test-Path "$RootDir\frontend\.next\BUILD_ID")) {
        Write-Host "[4/4] Building Next.js Production Bundle..." -ForegroundColor Yellow
        Push-Location "$RootDir\frontend"
        cmd.exe /c "npm run build"
        Pop-Location
    }
    Write-Host "[4/4] Starting Next.js Official Production UI at http://localhost:3000 ..." -ForegroundColor Yellow
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run start" -WorkingDirectory "$RootDir\frontend" -WindowStyle Minimized
    Start-Sleep -Seconds 3
} else {
    Write-Host "[4/4] Next.js Web UI is already running on :3000" -ForegroundColor Green
}

Write-Host "`n======================================================================" -ForegroundColor Green
Write-Host " RWA OFFICIAL SYSTEM IS LIVE!" -ForegroundColor Green
Write-Host " - Web Application       : http://localhost:3000" -ForegroundColor White
Write-Host " - Login / Register      : http://localhost:3000/login" -ForegroundColor White
Write-Host " - REST API & Swagger    : http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host " - Anvil EVM RPC         : http://127.0.0.1:8545 (Chain ID 31337)" -ForegroundColor White
Write-Host "======================================================================" -ForegroundColor Green
