// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {IdentityRegistry} from "../src/IdentityRegistry.sol";
import {AssetToken} from "../src/AssetToken.sol";

contract AssetTokenTest is Test {
    IdentityRegistry public registry;
    AssetToken public token;

    address public admin = makeAddr("admin");
    address public issuer = makeAddr("issuer");
    address public compliance = makeAddr("compliance");
    address public investorA = makeAddr("investorA");
    address public investorB = makeAddr("investorB");
    address public investorBNew = makeAddr("investorBNew");
    address public unverifiedUser = makeAddr("unverifiedUser");

    uint256 public constant TOTAL_SHARES = 10_000 * 10 ** 18;
    uint256 public constant INITIAL_VALUATION = 1_000_000 * 10 ** 6;

    function setUp() public {
        registry = new IdentityRegistry(admin, compliance);

        vm.startPrank(compliance);
        registry.addToWhitelist(issuer);
        registry.addToWhitelist(investorA);
        registry.addToWhitelist(investorB);
        registry.addToWhitelist(investorBNew);
        vm.stopPrank();

        token = new AssetToken(
            AssetToken.InitParams({
                name: "Penthouse Vinhomes",
                symbol: "VINH01",
                totalShares: TOTAL_SHARES,
                valuation: INITIAL_VALUATION,
                docCID: "QmDocCID123",
                docHash: keccak256("doc-content"),
                identityRegistry: address(registry),
                admin: admin,
                issuer: issuer,
                compliance: compliance,
                initialReceiver: issuer
            })
        );
    }

    function test_InitialStateAndMetadata() public view {
        assertEq(token.name(), "Penthouse Vinhomes");
        assertEq(token.symbol(), "VINH01");
        assertEq(token.totalSupply(), TOTAL_SHARES);
        assertEq(token.balanceOf(issuer), TOTAL_SHARES);
        assertEq(token.valuation(), INITIAL_VALUATION);
        assertEq(token.docCID(), "QmDocCID123");
        assertEq(token.CONSTANT_ASSET_TYPE(), "RealEstate");
    }

    function test_ConstructorValidationReverts() public {
        vm.expectRevert(AssetToken.ZeroAddress.selector);
        new AssetToken(
            AssetToken.InitParams({
                name: "A",
                symbol: "A",
                totalShares: TOTAL_SHARES,
                valuation: INITIAL_VALUATION,
                docCID: "cid",
                docHash: bytes32(0),
                identityRegistry: address(0),
                admin: admin,
                issuer: issuer,
                compliance: compliance,
                initialReceiver: issuer
            })
        );

        vm.expectRevert(AssetToken.InvalidAmount.selector);
        new AssetToken(
            AssetToken.InitParams({
                name: "A",
                symbol: "A",
                totalShares: 0,
                valuation: INITIAL_VALUATION,
                docCID: "cid",
                docHash: bytes32(0),
                identityRegistry: address(registry),
                admin: admin,
                issuer: issuer,
                compliance: compliance,
                initialReceiver: issuer
            })
        );
    }

    function test_TransferBetweenVerifiedInvestors() public {
        vm.prank(issuer);
        token.transfer(investorA, 1_000 * 10 ** 18);
        assertEq(token.balanceOf(investorA), 1_000 * 10 ** 18);

        vm.prank(investorA);
        token.transfer(investorB, 300 * 10 ** 18);
        assertEq(token.balanceOf(investorA), 700 * 10 ** 18);
        assertEq(token.balanceOf(investorB), 300 * 10 ** 18);
    }

    function test_RevertTransferToUnverifiedRecipient() public {
        vm.prank(issuer);
        vm.expectRevert(abi.encodeWithSelector(AssetToken.AccountNotWhitelisted.selector, unverifiedUser));
        token.transfer(unverifiedUser, 100 * 10 ** 18);
    }

    function test_RevertTransferFromRevokedSender() public {
        vm.prank(issuer);
        token.transfer(investorA, 500 * 10 ** 18);

        vm.prank(compliance);
        registry.removeFromWhitelist(investorA);

        vm.prank(investorA);
        vm.expectRevert(abi.encodeWithSelector(AssetToken.AccountNotWhitelisted.selector, investorA));
        token.transfer(investorB, 100 * 10 ** 18);
    }

    function test_FreezeAndUnfreezeAccount() public {
        vm.prank(issuer);
        token.transfer(investorA, 500 * 10 ** 18);

        vm.prank(compliance);
        vm.expectRevert(AssetToken.ZeroAddress.selector);
        token.setFrozen(address(0), true);

        vm.prank(compliance);
        token.setFrozen(investorA, true);
        assertTrue(token.isFrozen(investorA));

        // Chặn chiều gửi
        vm.prank(investorA);
        vm.expectRevert(abi.encodeWithSelector(AssetToken.AccountFrozen.selector, investorA));
        token.transfer(investorB, 100 * 10 ** 18);

        // Chặn chiều nhận
        vm.prank(issuer);
        vm.expectRevert(abi.encodeWithSelector(AssetToken.AccountFrozen.selector, investorA));
        token.transfer(investorA, 100 * 10 ** 18);

        // Mở băng
        vm.prank(compliance);
        token.setFrozen(investorA, false);
        assertFalse(token.isFrozen(investorA));

        vm.prank(investorA);
        token.transfer(investorB, 100 * 10 ** 18);
        assertEq(token.balanceOf(investorB), 100 * 10 ** 18);
    }

    function test_PauseAndUnpause() public {
        vm.prank(admin);
        token.pause();
        assertTrue(token.paused());

        vm.prank(issuer);
        vm.expectRevert();
        token.transfer(investorA, 100 * 10 ** 18);

        vm.prank(admin);
        token.unpause();
        assertFalse(token.paused());

        vm.prank(issuer);
        token.transfer(investorA, 100 * 10 ** 18);
        assertEq(token.balanceOf(investorA), 100 * 10 ** 18);
    }

    function test_ForcedTransferByAdmin() public {
        vm.prank(issuer);
        token.transfer(investorB, 400 * 10 ** 18);

        // Đóng băng ví B do tranh chấp
        vm.prank(compliance);
        token.setFrozen(investorB, true);

        // Admin thực hiện forcedTransfer sang ví mới đã KYC
        vm.prank(admin);
        token.forcedTransfer(investorB, investorBNew, 400 * 10 ** 18);

        assertEq(token.balanceOf(investorB), 0);
        assertEq(token.balanceOf(investorBNew), 400 * 10 ** 18);
    }

    function test_ForcedTransferInvalidRecipientReverts() public {
        vm.prank(issuer);
        token.transfer(investorB, 400 * 10 ** 18);

        vm.startPrank(admin);
        vm.expectRevert(AssetToken.ZeroAddress.selector);
        token.forcedTransfer(address(0), investorBNew, 100 * 10 ** 18);

        vm.expectRevert(abi.encodeWithSelector(AssetToken.InvalidForcedTransferRecipient.selector, unverifiedUser));
        token.forcedTransfer(investorB, unverifiedUser, 100 * 10 ** 18);

        vm.expectRevert(AssetToken.InvalidAmount.selector);
        token.forcedTransfer(investorB, investorBNew, 0);
        vm.stopPrank();
    }

    function test_UpdateValuation() public {
        vm.prank(issuer);
        vm.expectRevert(AssetToken.InvalidAmount.selector);
        token.updateValuation(0);

        vm.prank(issuer);
        token.updateValuation(1_250_000 * 10 ** 6);
        assertEq(token.valuation(), 1_250_000 * 10 ** 6);
    }
}
