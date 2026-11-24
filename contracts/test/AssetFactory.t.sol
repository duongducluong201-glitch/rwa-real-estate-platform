// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {IdentityRegistry} from "../src/IdentityRegistry.sol";
import {AssetFactory} from "../src/AssetFactory.sol";
import {AssetToken} from "../src/AssetToken.sol";

contract AssetFactoryTest is Test {
    IdentityRegistry public registry;
    AssetFactory public factory;

    address public admin = makeAddr("admin");
    address public issuer = makeAddr("issuer");
    address public compliance = makeAddr("compliance");
    address public vault = makeAddr("vault");
    address public stranger = makeAddr("stranger");

    function setUp() public {
        registry = new IdentityRegistry(admin, compliance);
        vm.prank(compliance);
        registry.addToWhitelist(vault);

        factory = new AssetFactory(admin, issuer, compliance, address(registry));
    }

    function test_ConstructorZeroAddressReverts() public {
        vm.expectRevert(AssetFactory.ZeroAddress.selector);
        new AssetFactory(address(0), issuer, compliance, address(registry));

        vm.expectRevert(AssetFactory.ZeroAddress.selector);
        new AssetFactory(admin, address(0), compliance, address(registry));

        vm.expectRevert(AssetFactory.ZeroAddress.selector);
        new AssetFactory(admin, issuer, address(0), address(registry));

        vm.expectRevert(AssetFactory.ZeroAddress.selector);
        new AssetFactory(admin, issuer, compliance, address(0));
    }

    function test_CreateAssetSuccess() public {
        vm.prank(issuer);
        address tokenAddr = factory.createAsset(
            "Dat Nen Thu Thiem",
            "THUT01",
            5_000 * 10 ** 18,
            500_000 * 10 ** 6,
            "QmThuThiemCID",
            keccak256("thu-thiem-doc"),
            vault
        );

        address[] memory tokens = factory.getDeployedTokens();
        assertEq(tokens.length, 1);
        assertEq(tokens[0], tokenAddr);

        AssetToken token = AssetToken(tokenAddr);
        assertEq(token.balanceOf(vault), 5_000 * 10 ** 18);
        assertEq(token.valuation(), 500_000 * 10 ** 6);
    }

    function test_CreateMultipleAssets() public {
        vm.startPrank(issuer);
        address t1 = factory.createAsset(unicode"BĐS 1", "BDS1", 1000e18, 100000e6, "CID1", keccak256("1"), vault);
        address t2 = factory.createAsset(unicode"BĐS 2", "BDS2", 2000e18, 200000e6, "CID2", keccak256("2"), vault);
        vm.stopPrank();

        address[] memory tokens = factory.getDeployedTokens();
        assertEq(tokens.length, 2);
        assertEq(tokens[0], t1);
        assertEq(tokens[1], t2);
    }

    function test_GrantNewIssuerRole() public {
        address newIssuer = makeAddr("newIssuer");
        bytes32 issuerRole = factory.ISSUER_ROLE();

        vm.prank(admin);
        factory.grantRole(issuerRole, newIssuer);
        assertTrue(factory.hasRole(issuerRole, newIssuer));

        vm.prank(newIssuer);
        address tokenAddr = factory.createAsset(unicode"BĐS 3", "BDS3", 1000e18, 100000e6, "CID3", keccak256("3"), vault);
        assertTrue(tokenAddr != address(0));
    }

    function test_CreateAssetUnauthorizedReverts() public {
        vm.prank(stranger);
        vm.expectRevert();
        factory.createAsset(
            "Unauthorized",
            "UNAUTH",
            1_000 * 10 ** 18,
            100_000 * 10 ** 6,
            "QmCID",
            bytes32(uint256(1)),
            vault
        );
    }
}
