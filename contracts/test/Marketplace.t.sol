// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {IdentityRegistry} from "../src/IdentityRegistry.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {AssetToken} from "../src/AssetToken.sol";
import {Marketplace} from "../src/Marketplace.sol";

contract MarketplaceTest is Test {
    IdentityRegistry public registry;
    MockUSDC public usdc;
    AssetToken public token;
    Marketplace public marketplace;

    address public admin = makeAddr("admin");
    address public issuer = makeAddr("issuer");
    address public compliance = makeAddr("compliance");
    address public seller = makeAddr("seller");
    address public buyer = makeAddr("buyer");
    address public unverified = makeAddr("unverified");

    function setUp() public {
        registry = new IdentityRegistry(admin, compliance);
        usdc = new MockUSDC();
        marketplace = new Marketplace(address(usdc), address(registry));

        vm.startPrank(compliance);
        registry.addToWhitelist(issuer);
        registry.addToWhitelist(address(marketplace));
        registry.addToWhitelist(seller);
        registry.addToWhitelist(buyer);
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
                initialReceiver: seller
            })
        );

        usdc.faucet(buyer, 200_000 * 10 ** 6);
    }

    function test_ConstructorZeroAddressReverts() public {
        vm.expectRevert(Marketplace.ZeroAddress.selector);
        new Marketplace(address(0), address(registry));
    }

    function test_ListPartialBuyAndCancel() public {
        vm.startPrank(seller);
        token.approve(address(marketplace), 300 * 10 ** 18);
        uint256 listingId = marketplace.list(address(token), 300 * 10 ** 18, 120 * 10 ** 6);
        vm.stopPrank();

        assertEq(listingId, 0);
        assertEq(token.balanceOf(address(marketplace)), 300 * 10 ** 18);

        // Buyer mua 1 phần (100 token @ 120 USDC = 12,000 USDC)
        vm.startPrank(buyer);
        usdc.approve(address(marketplace), 12_000 * 10 ** 6);
        marketplace.buy(listingId, 100 * 10 ** 18);
        vm.stopPrank();

        assertEq(token.balanceOf(buyer), 100 * 10 ** 18);
        assertEq(usdc.balanceOf(seller), 12_000 * 10 ** 6);

        Marketplace.Listing memory item = marketplace.getListing(listingId);
        assertEq(item.remainingAmount, 200 * 10 ** 18);
        assertTrue(item.isOpen);

        // Seller hủy phần còn lại (200 token)
        vm.prank(seller);
        marketplace.cancel(listingId);

        assertEq(token.balanceOf(address(marketplace)), 0);
        assertFalse(marketplace.getListing(listingId).isOpen);
    }

    function test_FullBuyClosesListing() public {
        vm.startPrank(seller);
        token.approve(address(marketplace), 100 * 10 ** 18);
        uint256 listingId = marketplace.list(address(token), 100 * 10 ** 18, 110 * 10 ** 6);
        vm.stopPrank();

        vm.startPrank(buyer);
        usdc.approve(address(marketplace), 11_000 * 10 ** 6);
        marketplace.buy(listingId, 100 * 10 ** 18);
        vm.stopPrank();

        assertFalse(marketplace.getListing(listingId).isOpen);
    }

    function test_BuyOrCancelInactiveListingReverts() public {
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(Marketplace.ListingNotOpen.selector, 99));
        marketplace.buy(99, 10 * 10 ** 18);

        vm.prank(seller);
        vm.expectRevert(abi.encodeWithSelector(Marketplace.ListingNotOpen.selector, 99));
        marketplace.cancel(99);
    }

    function test_BuyZeroAmountReverts() public {
        vm.startPrank(seller);
        token.approve(address(marketplace), 50 * 10 ** 18);
        uint256 listingId = marketplace.list(address(token), 50 * 10 ** 18, 100 * 10 ** 6);
        vm.stopPrank();

        vm.prank(buyer);
        vm.expectRevert(Marketplace.InvalidAmount.selector);
        marketplace.buy(listingId, 0);
    }

    function test_RevertConditionsOnMarketplace() public {
        vm.prank(unverified);
        vm.expectRevert(abi.encodeWithSelector(Marketplace.AccountNotWhitelisted.selector, unverified));
        marketplace.list(address(token), 10 * 10 ** 18, 100 * 10 ** 6);

        vm.startPrank(seller);
        vm.expectRevert(Marketplace.ZeroAddress.selector);
        marketplace.list(address(0), 10, 10);

        vm.expectRevert(Marketplace.InvalidAmount.selector);
        marketplace.list(address(token), 0, 10);

        token.approve(address(marketplace), 50 * 10 ** 18);
        uint256 listingId = marketplace.list(address(token), 50 * 10 ** 18, 100 * 10 ** 6);
        vm.stopPrank();

        // Người khác không được cancel
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(Marketplace.NotSeller.selector, buyer));
        marketplace.cancel(listingId);

        // Mua vượt số lượng còn lại
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(Marketplace.ExceedsRemaining.selector, 60 * 10 ** 18, 50 * 10 ** 18));
        marketplace.buy(listingId, 60 * 10 ** 18);

        // Chưa KYC không mua được
        vm.prank(unverified);
        vm.expectRevert(abi.encodeWithSelector(Marketplace.AccountNotWhitelisted.selector, unverified));
        marketplace.buy(listingId, 10 * 10 ** 18);
    }
}
