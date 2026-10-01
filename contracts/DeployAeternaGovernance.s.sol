// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./AeternaCascadeSafeModule.sol";

/**
 * @title DeployAeternaGovernanceModule
 * @notice Automated Foundry Deployment & Safe Configuration Script for DAOs and Honeypots.
 *
 * To run via Foundry:
 *   forge script contracts/DeployAeternaGovernance.s.sol:DeployAeternaGovernance --rpc-url $BASE_RPC --broadcast --verify
 */
contract DeployAeternaGovernance {
    // Official NetSwap / Aeterna Protocol Treasury on Base
    address public constant PROTOCOL_TREASURY = 0xcc12fD53A0ba26f42FEA6fF8b285a77aa54B170d;
    // NetSwap Settlement Contract on Base
    address public constant NETSWAP_SETTLEMENT = 0xbE40c75844197fD334db4174CBd7D07F9bAb93f8;

    function run() external returns (AeternaCascadeSafeModule module) {
        // 1. Deploy the Module Contract
        module = new AeternaCascadeSafeModule(
            PROTOCOL_TREASURY,
            NETSWAP_SETTLEMENT
        );

        // 2. Output deployment addresses
        // Safe owners can then execute:
        // Safe.enableModule(address(module))
        // module.registerLegacyVault(safe, backupColdStorage, backupColdStorage, 90 days, 3, guardians, false)
    }

    /**
     * @notice Helper to generate the exact calldata needed for Safe multisig execution
     */
    function getEnableModuleCalldata(address moduleAddress) external pure returns (bytes memory) {
        return abi.encodeWithSignature("enableModule(address)", moduleAddress);
    }
}
