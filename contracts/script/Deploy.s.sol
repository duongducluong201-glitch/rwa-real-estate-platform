// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {IdentityRegistry} from "../src/IdentityRegistry.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {AssetFactory} from "../src/AssetFactory.sol";
import {PrimarySale} from "../src/PrimarySale.sol";
import {Marketplace} from "../src/Marketplace.sol";
import {AssetToken} from "../src/AssetToken.sol";

contract DeployScript is Script {
    // 5 tài khoản dự án cố định trên Anvil (mnemonic mặc định: "test test test test test test test test test test test junk")
    uint256 constant ADMIN_PK = 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;
    uint256 constant ISSUER_PK = 0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d;
    uint256 constant COMPLIANCE_PK = 0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a;
    uint256 constant INVESTOR_A_PK = 0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6;
    uint256 constant INVESTOR_B_PK = 0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a;

    function run() external {
        address admin = vm.addr(ADMIN_PK);
        address issuer = vm.addr(ISSUER_PK);
        address compliance = vm.addr(COMPLIANCE_PK);
        address investorA = vm.addr(INVESTOR_A_PK);
        address investorB = vm.addr(INVESTOR_B_PK);

        console.log("=== DEPLOYING REAL ESTATE RWA ECOSYSTEM ON ANVIL ===");
        console.log("Admin (#0):      ", admin);
        console.log("Issuer (#1):     ", issuer);
        console.log("Compliance (#2): ", compliance);
        console.log("Investor A (#3): ", investorA);
        console.log("Investor B (#4): ", investorB);

        // 1. Admin triển khai 5 hợp đồng nền tảng
        vm.startBroadcast(ADMIN_PK);
        IdentityRegistry identityRegistry = new IdentityRegistry(admin, compliance);
        MockUSDC mockUSDC = new MockUSDC();
        AssetFactory assetFactory = new AssetFactory(admin, issuer, compliance, address(identityRegistry));
        PrimarySale primarySale = new PrimarySale(admin, issuer, address(mockUSDC), address(identityRegistry));
        Marketplace marketplace = new Marketplace(address(mockUSDC), address(identityRegistry));

        // Cấp MockUSDC ban đầu cho Investor A & Investor B để sẵn sàng demo
        mockUSDC.faucet(investorA, 150_000 * 10 ** 6);
        mockUSDC.faucet(investorB, 100_000 * 10 ** 6);
        vm.stopBroadcast();

        // 2. Compliance đưa PrimarySale, Marketplace, Issuer, Admin và Investor A vào Whitelist
        vm.startBroadcast(COMPLIANCE_PK);
        address[] memory initialWhitelist = new address[](5);
        initialWhitelist[0] = admin;
        initialWhitelist[1] = issuer;
        initialWhitelist[2] = address(primarySale);
        initialWhitelist[3] = address(marketplace);
        initialWhitelist[4] = investorA;
        identityRegistry.batchAddToWhitelist(initialWhitelist);
        vm.stopBroadcast();

        // 3. Issuer tạo BĐS mẫu #1 (Penthouse Vinhomes Central Park - VINH01) & mở bán sơ cấp
        vm.startBroadcast(ISSUER_PK);
        address vinh01Token = assetFactory.createAsset(
            "Penthouse Vinhomes Central Park",
            "VINH01",
            10_000 * 10 ** 18,            // 10,000 phần sở hữu
            1_000_000 * 10 ** 6,          // Định giá 1,000,000 MockUSDC
            "QmVinhomesPenthouseLegalDeed2026",
            keccak256("Penthouse-Vinhomes-Central-Park-Legal-Deed-2026"),
            address(primarySale)          // Mint thẳng vào kho PrimarySale
        );

        // Mở đợt bán sơ cấp 5,000 phần với giá 100 MockUSDC / phần
        primarySale.openSale(vinh01Token, 100 * 10 ** 6, 5_000 * 10 ** 18);
        vm.stopBroadcast();

        console.log("IdentityRegistry:", address(identityRegistry));
        console.log("MockUSDC:        ", address(mockUSDC));
        console.log("AssetFactory:    ", address(assetFactory));
        console.log("PrimarySale:     ", address(primarySale));
        console.log("Marketplace:     ", address(marketplace));
        console.log("VINH01 Token:    ", vinh01Token);
    }
}
