// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface IIdentityRegistry {
    event Whitelisted(address indexed account, address indexed operator);
    event RemovedFromWhitelist(address indexed account, address indexed operator);

    function addToWhitelist(address account) external;
    function removeFromWhitelist(address account) external;
    function isVerified(address account) external view returns (bool);
}
