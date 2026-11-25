@echo off
chcp 65001 >nul
echo Dang dung toan bo dich vu RWA (Anvil :8545, FastAPI :8000, Next.js :3000)...
for %%p in (3000 8000 8545) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R ":%%p .*LISTENING"') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)
echo [OK] Da dung xong toan bo dich vu!
pause
