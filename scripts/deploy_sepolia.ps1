# Script: Deploy Smart Contracts to Ethereum Sepolia Testnet
param(
    [Parameter(Mandatory=$true)]
    [string]$PrivateKey,

    [Parameter(Mandatory=$false)]
    [string]$RpcUrl = "https://rpc.sepolia.org",

    [Parameter(Mandatory=$false)]
    [string]$EtherscanApiKey = ""
)

$ErrorActionPreference = "Stop"

Write-Host "===============================================" -ForegroundColor Yellow
Write-Host "Triển khai Smart Contracts lên Ethereum Sepolia" -ForegroundColor Yellow
Write-Host "===============================================" -ForegroundColor Yellow

Set-Location "$PSScriptRoot\..\contracts"

$env:PRIVATE_KEY = $PrivateKey

if ($EtherscanApiKey -ne "") {
    & "..\tools\foundry\forge.exe" script script/Deploy.s.sol:DeployScript `
        --rpc-url $RpcUrl `
        --broadcast `
        --verify `
        --etherscan-api-key $EtherscanApiKey
} else {
    & "..\tools\foundry\forge.exe" script script/Deploy.s.sol:DeployScript `
        --rpc-url $RpcUrl `
        --broadcast
}

Write-Host "`nĐã hoàn thành triển khai lên Sepolia!" -ForegroundColor Green
