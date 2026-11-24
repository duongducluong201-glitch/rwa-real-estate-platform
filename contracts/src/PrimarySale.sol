// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IdentityRegistry} from "./IdentityRegistry.sol";
import {AssetToken} from "./AssetToken.sol";

/**
 * @title PrimarySale
 * @notice Quản lý các đợt chào bán sơ cấp giá cố định thanh toán bằng MockUSDC.
 */
contract PrimarySale is AccessControl, ReentrancyGuard {
    using SafeERC20 for IERC20;

    bytes32 public constant ISSUER_ROLE = keccak256("ISSUER_ROLE");

    struct SaleInfo {
        address token;
        uint256 pricePerShare; // Đơn giá tính theo MockUSDC (6 chữ số thập phân) cho mỗi 1.0 AssetToken (10^18)
        uint256 totalAmount;
        uint256 remainingAmount;
        address treasury;
        bool isOpen;
    }

    IERC20 public mockUSDC;
    IdentityRegistry public identityRegistry;
    mapping(address => SaleInfo) public sales;

    event SaleOpened(
        address indexed token,
        uint256 pricePerShare,
        uint256 amount,
        address indexed issuer
    );
    event SaleClosed(address indexed token, uint256 remainingAmount);
    event PrimaryPurchased(
        address indexed token,
        address indexed buyer,
        uint256 amount,
        uint256 usdcPaid
    );

    error ZeroAddress();
    error InvalidParameters();
    error SaleNotOpen(address token);
    error BuyerNotWhitelisted(address buyer);
    error InsufficientRemainingShares(uint256 requested, uint256 available);

    constructor(
        address admin_,
        address issuer_,
        address mockUSDC_,
        address identityRegistry_
    ) {
        if (
            admin_ == address(0) ||
            issuer_ == address(0) ||
            mockUSDC_ == address(0) ||
            identityRegistry_ == address(0)
        ) {
            revert ZeroAddress();
        }
        _grantRole(DEFAULT_ADMIN_ROLE, admin_);
        _grantRole(ISSUER_ROLE, issuer_);
        mockUSDC = IERC20(mockUSDC_);
        identityRegistry = IdentityRegistry(identityRegistry_);
    }

    /**
     * @notice Mở đợt bán sơ cấp cho một AssetToken với đơn giá cố định pricePerShare.
     * Nếu token đã được mint sẵn vào kho PrimarySale thì dùng số dư hiện có; nếu thiếu sẽ kéo thêm từ ví Issuer.
     */
    function openSale(
        address token,
        uint256 pricePerShare,
        uint256 amount
    ) external onlyRole(ISSUER_ROLE) {
        if (token == address(0) || pricePerShare == 0 || amount == 0) {
            revert InvalidParameters();
        }

        uint256 currentBalance = IERC20(token).balanceOf(address(this));
        if (currentBalance < amount) {
            uint256 needed = amount - currentBalance;
            IERC20(token).safeTransferFrom(msg.sender, address(this), needed);
        }

        sales[token] = SaleInfo({
            token: token,
            pricePerShare: pricePerShare,
            totalAmount: amount,
            remainingAmount: amount,
            treasury: msg.sender,
            isOpen: true
        });

        emit SaleOpened(token, pricePerShare, amount, msg.sender);
    }

    /**
     * @notice Đóng đợt bán sơ cấp hiện tại của AssetToken.
     */
    function closeSale(address token) external onlyRole(ISSUER_ROLE) {
        SaleInfo storage sale = sales[token];
        if (!sale.isOpen) revert SaleNotOpen(token);
        sale.isOpen = false;
        emit SaleClosed(token, sale.remainingAmount);
    }

    /**
     * @notice Nhà đầu tư đã KYC mua phần sở hữu BĐS từ đợt mở bán sơ cấp bằng MockUSDC.
     */
    function buy(address token, uint256 amount) external nonReentrant {
        SaleInfo storage sale = sales[token];
        if (!sale.isOpen) revert SaleNotOpen(token);
        if (amount == 0) revert InvalidParameters();
        if (amount > sale.remainingAmount) {
            revert InsufficientRemainingShares(amount, sale.remainingAmount);
        }
        if (!identityRegistry.isVerified(msg.sender)) {
            revert BuyerNotWhitelisted(msg.sender);
        }

        uint8 tokenDecimals = AssetToken(token).decimals();
        uint256 usdcCost = (amount * sale.pricePerShare) / (10 ** tokenDecimals);

        sale.remainingAmount -= amount;
        if (sale.remainingAmount == 0) {
            sale.isOpen = false;
        }

        mockUSDC.safeTransferFrom(msg.sender, sale.treasury, usdcCost);
        IERC20(token).safeTransfer(msg.sender, amount);

        emit PrimaryPurchased(token, msg.sender, amount, usdcCost);
    }

    function getSaleInfo(address token) external view returns (SaleInfo memory) {
        return sales[token];
    }
}
