@echo off
title RWA Real Estate Tokenization - Quick Launch
echo ======================================================================
echo  KHOI DONG HE THONG RWA REAL ESTATE TOKENIZATION (PERSISTENT STATE)
echo ======================================================================

set STATE_EXISTED=0
if exist "anvil_state.json" set STATE_EXISTED=1

echo [1/3] Khoi dong Blockchain Anvil node (:8545, luu state anvil_state.json)...
start "Anvil Blockchain" cmd /k "tools\foundry\anvil.exe --port 8545 --chain-id 31337 --block-time 1 --state anvil_state.json --state-interval 5"

timeout /t 3 /nobreak >nul

if "%STATE_EXISTED%"=="0" (
    echo [2/3] Lan khoi dong dau tien -> Trien khai 6 Smart Contracts...
    powershell -ExecutionPolicy Bypass -File .\scripts\deploy_local.ps1
) else (
    echo [2/3] Da khoi phuc trang thai Blockchain tu anvil_state.json!
)

echo Khoi dong Backend FastAPI (:8000)...
start "FastAPI Backend" cmd /k "python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload"

timeout /t 3 /nobreak >nul

echo [3/3] Khoi dong Frontend Next.js (:3000)...
start "Next.js Frontend" cmd /k "cd frontend && npm run dev"

echo ======================================================================
echo  HE THONG DA DUOC KHOI DONG THANH CONG!
echo  - Frontend Web UI  : http://localhost:3000/login
echo  - Backend API Docs : http://127.0.0.1:8000/docs
echo  - Blockchain RPC   : http://127.0.0.1:8545
echo  - Muon reset sach DB + Chain: chay scripts\reset_all.ps1
echo ======================================================================
pause
