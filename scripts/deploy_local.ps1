# Script: Deploy 6 Smart Contracts to local Anvil (:8545)
$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "DEPLOYING 6 SMART CONTRACTS TO LOCAL ANVIL (:8545)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

Set-Location "$PSScriptRoot\..\contracts"

& "..\tools\foundry\forge.exe" script script/Deploy.s.sol:DeployScript `
    --rpc-url http://127.0.0.1:8545 `
    --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 `
    --broadcast `
    --legacy

Write-Host "`n[OK] Deployed all 6 Smart Contracts & sample VINH01 asset on Anvil!" -ForegroundColor Green
