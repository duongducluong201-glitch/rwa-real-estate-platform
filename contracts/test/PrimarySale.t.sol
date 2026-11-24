// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {IdentityRegistry} from "../src/IdentityRegistry.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {AssetToken} from "../src/AssetToken.sol";
import {PrimarySale} from "../src/PrimarySale.sol";

contract PrimarySaleTest is Test {
    IdentityRegistry public registry;
    MockUSDC public usdc;
    AssetToken public token;
    PrimarySale public primarySale;

    address public admin = makeAddr("admin");
    address public issuer = makeAddr("issuer");
    address public compliance = makeAddr("compliance");
    address public investorA = makeAddr("investorA");
    address public unverified = makeAddr("unverified");

    function setUp() public {
        registry = new IdentityRegistry(admin, compliance);
        usdc = new MockUSDC();
        primarySale = new PrimarySale(admin, issuer, address(usdc), address(registry));

        vm.startPrank(compliance);
        registry.addToWhitelist(issuer);
        registry.addToWhitelist(address(primarySale));
        registry.addToWhitelist(investorA);
        vm.stopPrank();

        token = new AssetToken(
            AssetToken.InitParams({
                name: "Vinhomes Penthouse",
                symbol: "VINH01",
                totalShares: 10_000 * 10 ** 18,
                valuation: 1_000_000 * 10 ** 6,
                docCID: "QmCID",
                docHash: keccak256("doc"),
                identityRegistry: address(registry),
                admin: admin,
                issuer: issuer,
                compliance: compliance,
                initialReceiver: address(primarySale)
            })
        );

        usdc.faucet(investorA, 200_000 * 10 ** 6);
        usdc.faucet(unverified, 200_000 * 10 ** 6);
    }

    function test_ConstructorZeroAddressReverts() public {
        vm.expectRevert(PrimarySale.ZeroAddress.selector);
        new PrimarySale(address(0), issuer, address(usdc), address(registry));
    }

    function test_OpenAndBuyPrimarySale() public {
        vm.prank(issuer);
        primarySale.openSale(address(token), 100 * 10 ** 6, 5_000 * 10 ** 18);

        PrimarySale.SaleInfo memory info = primarySale.getSaleInfo(address(token));
        assertTrue(info.isOpen);
        assertEq(info.remainingAmount, 5_000 * 10 ** 18);

        vm.startPrank(investorA);
        usdc.approve(address(primarySale), 100_000 * 10 ** 6);
        primarySale.buy(address(token), 1_000 * 10 ** 18);
        vm.stopPrank();

        assertEq(token.balanceOf(investorA), 1_000 * 10 ** 18);
        assertEq(usdc.balanceOf(issuer), 100_000 * 10 ** 6);
    }

    function test_BuyAllRemainingAutoClosesSale() public {
        vm.prank(issuer);
        primarySale.openSale(address(token), 100 * 10 ** 6, 1_000 * 10 ** 18);

        vm.startPrank(investorA);
        usdc.approve(address(primarySale), 100_000 * 10 ** 6);
        primarySale.buy(address(token), 1_000 * 10 ** 18);
        vm.stopPrank();

        PrimarySale.SaleInfo memory info = primarySale.getSaleInfo(address(token));
        assertFalse(info.isOpen);
        assertEq(info.remainingAmount, 0);
    }

    function test_OpenSalePullsFromIssuerIfVaultShort() public {
        AssetToken tokenInIssuerWallet = new AssetToken(
            AssetToken.InitParams({
                name: "Building Token",
                symbol: "BLD01",
                totalShares: 2_000 * 10 ** 18,
                valuation: 200_000 * 10 ** 6,
                docCID: "QmCID2",
                docHash: keccak256("doc2"),
                identityRegistry: address(registry),
                admin: admin,
                issuer: issuer,
                compliance: compliance,
                initialReceiver: issuer
            })
        );

        vm.startPrank(issuer);
        tokenInIssuerWallet.approve(address(primarySale), 2_000 * 10 ** 18);
        primarySale.openSale(address(tokenInIssuerWallet), 100 * 10 ** 6, 2_000 * 10 ** 18);
        vm.stopPrank();

        assertEq(tokenInIssuerWallet.balanceOf(address(primarySale)), 2_000 * 10 ** 18);
    }

    function test_CloseSaleWhenNotOpenReverts() public {
        vm.prank(issuer);
        vm.expectRevert(abi.encodeWithSelector(PrimarySale.SaleNotOpen.selector, address(token)));
        primarySale.closeSale(address(token));
    }

    function test_CloseSaleAndReverts() public {
        vm.prank(issuer);
        vm.expectRevert(PrimarySale.InvalidParameters.selector);
        primarySale.openSale(address(0), 100, 100);

        vm.prank(issuer);
        primarySale.openSale(address(token), 100 * 10 ** 6, 1_000 * 10 ** 18);

        vm.prank(investorA);
        vm.expectRevert(PrimarySale.InvalidParameters.selector);
        primarySale.buy(address(token), 0);

        // Chưa KYC không mua được
        vm.prank(unverified);
        vm.expectRevert(abi.encodeWithSelector(PrimarySale.BuyerNotWhitelisted.selector, unverified));
        primarySale.buy(address(token), 10 * 10 ** 18);

        // Mua quá số lượng còn lại
        vm.prank(investorA);
        vm.expectRevert(
            abi.encodeWithSelector(PrimarySale.InsufficientRemainingShares.selector, 2_000 * 10 ** 18, 1_000 * 10 ** 18)
        );
        primarySale.buy(address(token), 2_000 * 10 ** 18);

        // Đóng đợt bán
        vm.prank(issuer);
        primarySale.closeSale(address(token));

        vm.prank(investorA);
        vm.expectRevert(abi.encodeWithSelector(PrimarySale.SaleNotOpen.selector, address(token)));
        primarySale.buy(address(token), 10 * 10 ** 18);
    }
}
