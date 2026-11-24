// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {AssetToken} from "./AssetToken.sol";
import {IdentityRegistry} from "./IdentityRegistry.sol";

/**
 * @title AssetFactory
 * @notice Hợp đồng nhà máy triển khai các hợp đồng AssetToken mới đại diện cho từng bất động sản.
 */
contract AssetFactory is AccessControl {
    bytes32 public constant ISSUER_ROLE = keccak256("ISSUER_ROLE");

    IdentityRegistry public identityRegistry;
    address public defaultAdmin;
    address public defaultCompliance;
    address[] public deployedTokens;

    event AssetCreated(
        address indexed token,
        string name,
        string symbol,
        uint256 totalShares,
        uint256 valuation,
        string docCID,
        bytes32 docHash,
        address indexed issuer
    );

    error ZeroAddress();

    constructor(
        address admin_,
        address issuer_,
        address compliance_,
        address identityRegistry_
    ) {
        if (
            admin_ == address(0) ||
            issuer_ == address(0) ||
            compliance_ == address(0) ||
            identityRegistry_ == address(0)
        ) {
            revert ZeroAddress();
        }
        _grantRole(DEFAULT_ADMIN_ROLE, admin_);
        _grantRole(ISSUER_ROLE, issuer_);
        defaultAdmin = admin_;
        defaultCompliance = compliance_;
        identityRegistry = IdentityRegistry(identityRegistry_);
    }

    /**
     * @notice Triển khai một hợp đồng AssetToken mới và mint toàn bộ totalShares vào initialReceiver.
     */
    function createAsset(
        string calldata name,
        string calldata symbol,
        uint256 totalShares,
        uint256 valuation,
        string calldata docCID,
        bytes32 docHash,
        address initialReceiver
    ) external onlyRole(ISSUER_ROLE) returns (address) {
        AssetToken token = new AssetToken(
            AssetToken.InitParams({
                name: name,
                symbol: symbol,
                totalShares: totalShares,
                valuation: valuation,
                docCID: docCID,
                docHash: docHash,
                identityRegistry: address(identityRegistry),
                admin: defaultAdmin,
                issuer: msg.sender,
                compliance: defaultCompliance,
                initialReceiver: initialReceiver
            })
        );

        address tokenAddr = address(token);
        deployedTokens.push(tokenAddr);

        emit AssetCreated(
            tokenAddr,
            name,
            symbol,
            totalShares,
            valuation,
            docCID,
            docHash,
            msg.sender
        );

        return tokenAddr;
    }

    /**
     * @notice Trả về danh sách tất cả địa chỉ AssetToken đã triển khai.
     */
    function getDeployedTokens() external view returns (address[] memory) {
        return deployedTokens;
    }
}
