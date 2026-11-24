// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {IIdentityRegistry} from "./interfaces/IIdentityRegistry.sol";

/**
 * @title IdentityRegistry
 * @notice Quản lý danh sách trắng (whitelist) các tài khoản đã hoàn tất xác minh KYC.
 * Kiểm soát bởi COMPLIANCE_ROLE và DEFAULT_ADMIN_ROLE.
 */
contract IdentityRegistry is AccessControl, IIdentityRegistry {
    bytes32 public constant COMPLIANCE_ROLE = keccak256("COMPLIANCE_ROLE");

    mapping(address => bool) private _whitelisted;

    error ZeroAddress();
    error AlreadyWhitelisted(address account);
    error NotWhitelisted(address account);

    constructor(address admin, address compliance) {
        if (admin == address(0) || compliance == address(0)) revert ZeroAddress();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(COMPLIANCE_ROLE, compliance);
    }

    /**
     * @notice Thêm một địa chỉ vào danh sách trắng KYC.
     */
    function addToWhitelist(address account) external override onlyRole(COMPLIANCE_ROLE) {
        if (account == address(0)) revert ZeroAddress();
        if (_whitelisted[account]) revert AlreadyWhitelisted(account);

        _whitelisted[account] = true;
        emit Whitelisted(account, msg.sender);
    }

    /**
     * @notice Thêm hàng loạt địa chỉ vào danh sách trắng KYC.
     */
    function batchAddToWhitelist(address[] calldata accounts) external onlyRole(COMPLIANCE_ROLE) {
        for (uint256 i = 0; i < accounts.length; i++) {
            address account = accounts[i];
            if (account == address(0)) revert ZeroAddress();
            if (!_whitelisted[account]) {
                _whitelisted[account] = true;
                emit Whitelisted(account, msg.sender);
            }
        }
    }

    /**
     * @notice Thu hồi một địa chỉ khỏi danh sách trắng KYC.
     */
    function removeFromWhitelist(address account) external override onlyRole(COMPLIANCE_ROLE) {
        if (account == address(0)) revert ZeroAddress();
        if (!_whitelisted[account]) revert NotWhitelisted(account);

        _whitelisted[account] = false;
        emit RemovedFromWhitelist(account, msg.sender);
    }

    /**
     * @notice Kiểm tra một địa chỉ đã nằm trong danh sách trắng KYC hay chưa.
     */
    function isVerified(address account) external view override returns (bool) {
        return _whitelisted[account];
    }
}
