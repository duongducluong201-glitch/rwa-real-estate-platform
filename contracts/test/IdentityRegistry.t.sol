// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {IdentityRegistry} from "../src/IdentityRegistry.sol";

contract IdentityRegistryTest is Test {
    IdentityRegistry public registry;
    address public admin = makeAddr("admin");
    address public compliance = makeAddr("compliance");
    address public investor1 = makeAddr("investor1");
    address public investor2 = makeAddr("investor2");
    address public attacker = makeAddr("attacker");

    function setUp() public {
        registry = new IdentityRegistry(admin, compliance);
    }

    function test_ConstructorZeroAddressReverts() public {
        vm.expectRevert(IdentityRegistry.ZeroAddress.selector);
        new IdentityRegistry(address(0), compliance);

        vm.expectRevert(IdentityRegistry.ZeroAddress.selector);
        new IdentityRegistry(admin, address(0));
    }

    function test_AddAndRemoveWhitelist() public {
        assertFalse(registry.isVerified(investor1));

        vm.prank(compliance);
        registry.addToWhitelist(investor1);
        assertTrue(registry.isVerified(investor1));

        vm.prank(compliance);
        registry.removeFromWhitelist(investor1);
        assertFalse(registry.isVerified(investor1));
    }

    function test_BatchAddToWhitelist() public {
        address[] memory accounts = new address[](2);
        accounts[0] = investor1;
        accounts[1] = investor2;

        vm.prank(compliance);
        registry.batchAddToWhitelist(accounts);

        assertTrue(registry.isVerified(investor1));
        assertTrue(registry.isVerified(investor2));
    }

    function test_BatchAddZeroAddressReverts() public {
        address[] memory accounts = new address[](2);
        accounts[0] = investor1;
        accounts[1] = address(0);

        vm.prank(compliance);
        vm.expectRevert(IdentityRegistry.ZeroAddress.selector);
        registry.batchAddToWhitelist(accounts);
    }

    function test_RevertDuplicateAndUnverifiedRemoval() public {
        vm.startPrank(compliance);
        vm.expectRevert(IdentityRegistry.ZeroAddress.selector);
        registry.addToWhitelist(address(0));

        registry.addToWhitelist(investor1);
        vm.expectRevert(abi.encodeWithSelector(IdentityRegistry.AlreadyWhitelisted.selector, investor1));
        registry.addToWhitelist(investor1);

        vm.expectRevert(IdentityRegistry.ZeroAddress.selector);
        registry.removeFromWhitelist(address(0));

        vm.expectRevert(abi.encodeWithSelector(IdentityRegistry.NotWhitelisted.selector, investor2));
        registry.removeFromWhitelist(investor2);
        vm.stopPrank();
    }

    function test_UnauthorizedAccessReverts() public {
        vm.prank(attacker);
        vm.expectRevert();
        registry.addToWhitelist(investor1);
    }
}
