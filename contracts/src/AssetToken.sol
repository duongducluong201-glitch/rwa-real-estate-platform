// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {IdentityRegistry} from "./IdentityRegistry.sol";

/**
 * @title AssetToken
 * @notice Token chuẩn ERC-20 đại diện quyền sở hữu kinh tế phân mảnh của một bất động sản (RWA).
 * Thực thi kiểm soát tuân thủ tập trung tại hàm _update (KYC whitelist, đóng băng tài khoản, tạm dừng hệ thống)
 * và hỗ trợ chuyển nhượng cưỡng chế (forcedTransfer) khi xử lý tranh chấp hoặc mất tài khoản.
 */
contract AssetToken is ERC20, AccessControl, Pausable {
    bytes32 public constant ISSUER_ROLE = keccak256("ISSUER_ROLE");
    bytes32 public constant COMPLIANCE_ROLE = keccak256("COMPLIANCE_ROLE");
    string public constant CONSTANT_ASSET_TYPE = "RealEstate";

    IdentityRegistry public identityRegistry;
    uint256 public valuation;
    string public docCID;
    bytes32 public docHash;

    mapping(address => bool) private _frozen;
    bool private _inForcedTransfer;

    event Frozen(address indexed account, bool isFrozen, address indexed operator);
    event ForcedTransfer(address indexed from, address indexed to, uint256 amount, address indexed admin);
    event ValuationUpdated(uint256 oldValuation, uint256 newValuation, address indexed issuer);

    error ZeroAddress();
    error InvalidAmount();
    error AccountFrozen(address account);
    error AccountNotWhitelisted(address account);
    error InvalidForcedTransferRecipient(address recipient);

    struct InitParams {
        string name;
        string symbol;
        uint256 totalShares;
        uint256 valuation;
        string docCID;
        bytes32 docHash;
        address identityRegistry;
        address admin;
        address issuer;
        address compliance;
        address initialReceiver;
    }

    constructor(InitParams memory p) ERC20(p.name, p.symbol) {
        if (
            p.identityRegistry == address(0) ||
            p.admin == address(0) ||
            p.issuer == address(0) ||
            p.compliance == address(0) ||
            p.initialReceiver == address(0)
        ) {
            revert ZeroAddress();
        }
        if (p.totalShares == 0 || p.valuation == 0) revert InvalidAmount();

        identityRegistry = IdentityRegistry(p.identityRegistry);
        valuation = p.valuation;
        docCID = p.docCID;
        docHash = p.docHash;

        _grantRole(DEFAULT_ADMIN_ROLE, p.admin);
        _grantRole(ISSUER_ROLE, p.issuer);
        _grantRole(COMPLIANCE_ROLE, p.compliance);

        _mint(p.initialReceiver, p.totalShares);
    }

    /**
     * @notice Đóng băng hoặc mở băng tài khoản mục tiêu.
     */
    function setFrozen(address account, bool frozen) external onlyRole(COMPLIANCE_ROLE) {
        if (account == address(0)) revert ZeroAddress();
        _frozen[account] = frozen;
        emit Frozen(account, frozen, msg.sender);
    }

    /**
     * @notice Kiểm tra trạng thái đóng băng của một tài khoản.
     */
    function isFrozen(address account) external view returns (bool) {
        return _frozen[account];
    }

    /**
     * @notice Cập nhật định giá giả lập (theo đơn vị MockUSDC 6 chữ số thập phân).
     */
    function updateValuation(uint256 newValuation) external onlyRole(ISSUER_ROLE) {
        if (newValuation == 0) revert InvalidAmount();
        uint256 oldValuation = valuation;
        valuation = newValuation;
        emit ValuationUpdated(oldValuation, newValuation, msg.sender);
    }

    /**
     * @notice Tạm dừng toàn bộ giao dịch thông thường của AssetToken khi khẩn cấp.
     */
    function pause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _pause();
    }

    /**
     * @notice Mở lại hoạt động giao dịch bình thường của AssetToken.
     */
    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }

    /**
     * @notice Chuyển nhượng cưỡng chế khi xảy ra tranh chấp hoặc mất tài khoản.
     * Bỏ qua kiểm tra frozen/whitelist của ví nguồn nhưng bắt buộc ví đích phải hợp lệ, không frozen và đã KYC.
     */
    function forcedTransfer(
        address from,
        address to,
        uint256 amount
    ) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (from == address(0)) revert ZeroAddress();
        if (to == address(0) || _frozen[to] || !identityRegistry.isVerified(to)) {
            revert InvalidForcedTransferRecipient(to);
        }
        if (amount == 0) revert InvalidAmount();

        _inForcedTransfer = true;
        _update(from, to, amount);
        _inForcedTransfer = false;

        emit ForcedTransfer(from, to, amount, msg.sender);
    }

    /**
     * @dev Chốt chặn tuân thủ tập trung cho mọi thao tác mint, transfer, transferFrom.
     */
    function _update(
        address from,
        address to,
        uint256 value
    ) internal override whenNotPaused {
        if (!_inForcedTransfer) {
            if (from != address(0)) {
                if (_frozen[from]) revert AccountFrozen(from);
                if (!identityRegistry.isVerified(from)) revert AccountNotWhitelisted(from);
            }
            if (to != address(0)) {
                if (_frozen[to]) revert AccountFrozen(to);
                if (!identityRegistry.isVerified(to)) revert AccountNotWhitelisted(to);
            }
        }
        super._update(from, to, value);
    }
}
