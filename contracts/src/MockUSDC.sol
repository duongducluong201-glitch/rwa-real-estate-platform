// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/**
 * @title MockUSDC
 * @notice Đồng stablecoin giả lập (6 chữ số thập phân) phục vụ thanh toán sơ cấp và thứ cấp.
 */
contract MockUSDC is ERC20 {
    uint8 private constant DECIMALS = 6;
    uint256 public constant DEFAULT_FAUCET_AMOUNT = 50_000 * 10 ** DECIMALS;
    uint256 public constant MAX_FAUCET_AMOUNT = 500_000 * 10 ** DECIMALS;

    event FaucetClaimed(address indexed recipient, uint256 amount);

    error FaucetAmountExceeded(uint256 requested, uint256 max);

    constructor() ERC20("Mock USD Coin", "mUSDC") {
        _mint(msg.sender, 10_000_000 * 10 ** DECIMALS);
    }

    function decimals() public pure override returns (uint8) {
        return DECIMALS;
    }

    /**
     * @notice Nhận 50,000 MockUSDC mặc định cho msg.sender.
     */
    function faucet() external {
        _mint(msg.sender, DEFAULT_FAUCET_AMOUNT);
        emit FaucetClaimed(msg.sender, DEFAULT_FAUCET_AMOUNT);
    }

    /**
     * @notice Cấp một lượng MockUSDC xác định tới địa chỉ chỉ định (tối đa 500,000 mUSDC/lần).
     */
    function faucet(address to, uint256 amount) external {
        if (amount > MAX_FAUCET_AMOUNT) {
            revert FaucetAmountExceeded(amount, MAX_FAUCET_AMOUNT);
        }
        _mint(to, amount);
        emit FaucetClaimed(to, amount);
    }
}
