@echo off
chcp 65001 >nul
title Khoi chay He thong RWA Real Estate
cd /d "%~dp0"

echo ============================================================
echo   DANG KHOI CHAY HE THONG RWA REAL ESTATE (ANVIL + API + WEB)
echo ============================================================

REM 1. Khoi chay Blockchain cuc bo Anvil (:8545)
if exist "%~dp0tools\foundry\anvil.exe" (
    start "1. Anvil Blockchain (:8545)" cmd /k ""%~dp0tools\foundry\anvil.exe" --port 8545 --chain-id 31337 --block-time 1 --state anvil_state.json --state-interval 5"
) else (
    start "1. Anvil Blockchain (:8545)" cmd /k "anvil --port 8545 --chain-id 31337 --block-time 1 --state anvil_state.json --state-interval 5"
)

timeout /t 2 /nobreak >nul

REM 2. Khoi chay Backend FastAPI (:8000)
start "2. FastAPI Backend (:8000)" cmd /k "cd /d "%~dp0" && python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"

timeout /t 2 /nobreak >nul

REM 3. Khoi chay Frontend Next.js (:3000)
if exist "%~dp0frontend\.next\BUILD_ID" (
    start "3. Next.js Frontend (:3000)" cmd /k "cd /d "%~dp0frontend" && npm run start"
) else (
    start "3. Next.js Frontend (:3000)" cmd /k "cd /d "%~dp0frontend" && npm run build && npm run start"
)

timeout /t 3 /nobreak >nul

REM 4. Tu dong mo trinh duyet
start "" "http://localhost:3000"

echo.
echo [OK] Da mo 3 dich vu va trinh duyet tai http://localhost:3000
echo      Khi muon tat toan bo, hay nhay dup file stop_all.bat
echo.
pause
