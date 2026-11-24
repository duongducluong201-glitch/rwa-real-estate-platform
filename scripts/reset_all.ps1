# Script: Reset sach ca Database SQLite lan trang thai Blockchain Anvil (Dong bo 100%)
$ErrorActionPreference = "Continue"
$RootDir = (Resolve-Path "$PSScriptRoot\..").Path

Write-Host "======================================================================" -ForegroundColor Yellow
Write-Host " RESET SACH DATABASE SQLITE & ANVIL BLOCKCHAIN STATE" -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Yellow

# 1. Dung cac tien trinh dang lang nghe tren cong 8545, 8000, 3000
foreach ($port in @(8545, 8000, 3000)) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        try {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
            Write-Host " - Da dung tien trinh tren cong :$port (PID=$($c.OwningProcess))" -ForegroundColor Gray
        } catch {}
    }
}
Start-Sleep -Seconds 1

# 2. Xoa file DB SQLite & Anvil state cu
$filesToRemove = @(
    (Join-Path $RootDir "rwa_platform.db"),
    (Join-Path $RootDir "backend\rwa_platform.db"),
    (Join-Path $RootDir "anvil_state.json")
)
foreach ($f in $filesToRemove) {
    if (Test-Path $f) {
        Remove-Item -Path $f -Force
        Write-Host " - Da xoa: $f" -ForegroundColor Green
    }
}

Write-Host "`n[OK] Da don sach DB va Anvil state! Dang khoi dong lai he thong sach..." -ForegroundColor Cyan
powershell -ExecutionPolicy Bypass -File "$RootDir\scripts\demo_up.ps1"
