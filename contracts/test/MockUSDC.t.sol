// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {MockUSDC} from "../src/MockUSDC.sol";

contract MockUSDCTest is Test {
    MockUSDC public usdc;
    address public investor = makeAddr("investor");

    function setUp() public {
        usdc = new MockUSDC();
    }

    function test_DecimalsAndInitialSupply() public view {
        assertEq(usdc.decimals(), 6);
        assertEq(usdc.balanceOf(address(this)), 10_000_000 * 10 ** 6);
    }

    function test_FaucetOverloads() public {
        vm.prank(investor);
        usdc.faucet();
        assertEq(usdc.balanceOf(investor), 50_000 * 10 ** 6);

        usdc.faucet(investor, 100_000 * 10 ** 6);
        assertEq(usdc.balanceOf(investor), 150_000 * 10 ** 6);
    }

    function test_RevertWhenFaucetExceedsMax() public {
        uint256 tooMuch = 600_000 * 10 ** 6;
        vm.expectRevert(abi.encodeWithSelector(MockUSDC.FaucetAmountExceeded.selector, tooMuch, usdc.MAX_FAUCET_AMOUNT()));
        usdc.faucet(investor, tooMuch);
    }
}
