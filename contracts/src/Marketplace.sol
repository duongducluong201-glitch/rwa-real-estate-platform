// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IdentityRegistry} from "./IdentityRegistry.sol";
import {AssetToken} from "./AssetToken.sol";

/**
 * @title Marketplace
 * @notice Chợ giao dịch thứ cấp theo cơ chế ký quỹ giá cố định (Fixed-price Escrow).
 * Hỗ trợ niêm yết (list), mua toàn bộ hoặc một phần (buy) và hủy lệnh (cancel).
 */
contract Marketplace is ReentrancyGuard {
    using SafeERC20 for IERC20;

    struct Listing {
        uint256 listingId;
        address token;
        address seller;
        uint256 initialAmount;
        uint256 remainingAmount;
        uint256 pricePerShare; // Đơn giá cố định tính theo MockUSDC (6 chữ số thập phân)
        bool isOpen;
    }

    IERC20 public mockUSDC;
    IdentityRegistry public identityRegistry;
    uint256 public nextListingId;
    mapping(uint256 => Listing) public listings;

    event Listed(
        uint256 indexed listingId,
        address indexed token,
        address indexed seller,
        uint256 amount,
        uint256 pricePerShare
    );
    event Bought(
        uint256 indexed listingId,
        address indexed token,
        address indexed buyer,
        uint256 amount,
        uint256 usdcPaid,
        uint256 remainingAmount
    );
    event Cancelled(
        uint256 indexed listingId,
        address indexed seller,
        uint256 refundedAmount
    );

    error ZeroAddress();
    error InvalidAmount();
    error ListingNotOpen(uint256 listingId);
    error NotSeller(address caller);
    error AccountNotWhitelisted(address account);
    error ExceedsRemaining(uint256 requested, uint256 available);

    constructor(address mockUSDC_, address identityRegistry_) {
        if (mockUSDC_ == address(0) || identityRegistry_ == address(0)) {
            revert ZeroAddress();
        }
        mockUSDC = IERC20(mockUSDC_);
        identityRegistry = IdentityRegistry(identityRegistry_);
    }

    /**
     * @notice Ký quỹ một lượng AssetToken vào hợp đồng Marketplace với mức giá cố định pricePerShare.
     */
    function list(
        address token,
        uint256 amount,
        uint256 pricePerShare
    ) external nonReentrant returns (uint256) {
        if (token == address(0)) revert ZeroAddress();
        if (amount == 0 || pricePerShare == 0) revert InvalidAmount();
        if (!identityRegistry.isVerified(msg.sender)) {
            revert AccountNotWhitelisted(msg.sender);
        }

        IERC20(token).safeTransferFrom(msg.sender, address(this), amount);

        uint256 listingId = nextListingId++;
        listings[listingId] = Listing({
            listingId: listingId,
            token: token,
            seller: msg.sender,
            initialAmount: amount,
            remainingAmount: amount,
            pricePerShare: pricePerShare,
            isOpen: true
        });

        emit Listed(listingId, token, msg.sender, amount, pricePerShare);
        return listingId;
    }

    /**
     * @notice Mua toàn bộ hoặc một phần số lượng token trong lệnh đang niêm yết.
     */
    function buy(uint256 listingId, uint256 amount) external nonReentrant {
        Listing storage item = listings[listingId];
        if (!item.isOpen) revert ListingNotOpen(listingId);
        if (amount == 0) revert InvalidAmount();
        if (amount > item.remainingAmount) {
            revert ExceedsRemaining(amount, item.remainingAmount);
        }
        if (!identityRegistry.isVerified(msg.sender)) {
            revert AccountNotWhitelisted(msg.sender);
        }

        uint8 tokenDecimals = AssetToken(item.token).decimals();
        uint256 usdcCost = (amount * item.pricePerShare) / (10 ** tokenDecimals);

        item.remainingAmount -= amount;
        if (item.remainingAmount == 0) {
            item.isOpen = false;
        }

        mockUSDC.safeTransferFrom(msg.sender, item.seller, usdcCost);
        IERC20(item.token).safeTransfer(msg.sender, amount);

        emit Bought(listingId, item.token, msg.sender, amount, usdcCost, item.remainingAmount);
    }

    /**
     * @notice Hủy lệnh đang mở và rút lại số lượng AssetToken chưa khớp về ví người bán.
     */
    function cancel(uint256 listingId) external nonReentrant {
        Listing storage item = listings[listingId];
        if (!item.isOpen) revert ListingNotOpen(listingId);
        if (msg.sender != item.seller) revert NotSeller(msg.sender);

        item.isOpen = false;
        uint256 refundAmount = item.remainingAmount;
        item.remainingAmount = 0;

        IERC20(item.token).safeTransfer(item.seller, refundAmount);

        emit Cancelled(listingId, msg.sender, refundAmount);
    }

    function getListing(uint256 listingId) external view returns (Listing memory) {
        return listings[listingId];
    }
}
