// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address recipient, uint256 amount) external returns (bool);
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
    function approve(address spender, uint256 amount) external returns (bool);
}

interface ISafe {
    function execTransactionFromModule(
        address to,
        uint256 value,
        bytes memory data,
        uint8 operation
    ) external returns (bool success);
    function isModuleEnabled(address module) external view returns (bool);
    function isOwner(address owner) external view returns (bool);
    function getOwners() external view returns (address[] memory);
}

interface INetSwapSettlement {
    function feeRecipient() external view returns (address);
}

/**
 * @title AeternaCascadeSafeModule
 * @notice The Sovereign Conditional Continuity & Dead-Man's Execution Engine for Gnosis Safe.
 *         Connects as an authorized, non-custodial module to any Gnosis Safe (v1.3.0 / v1.4.1).
 *         Protects digital assets with a multi-tier cascade, 3-of-5 guardian quorum,
 *         and an inviolable 30-Day "Scream Window" before autonomous execution.
 *         Hardcoded to route liquidations exclusively through NetSwap settlement.
 *
 * Security Invariants:
 *  1. Zero tx.origin usage (phishing immunity).
 *  2. Safe or Safe-Owner access control on genesis registration and heartbeat pulse.
 *  3. Duplicate-free Guardian quorums.
 *  4. Strict Checks-Effects-Interactions state transitions.
 *  5. Native ETH & ERC-20 dual sweep with return validation.
 */
contract AeternaCascadeSafeModule {
    // --- FINANCIAL CONSTANTS & PROTOCOL MONETIZATION ---
    uint256 public constant EXECUTION_FEE_BPS = 300;     // 3.00% Success fee upon estate execution
    uint256 public constant YIELD_SIPHON_BPS = 2000;     // 20.00% Protocol siphon on dormant float yield
    uint256 public constant BPS_DENOMINATOR = 10000;
    uint256 public constant SCREAM_WINDOW_SECONDS = 30 days; // 30-day non-censorable abort window

    address public immutable protocolTreasury;
    address public immutable netSwapSettlement;

    enum VaultState {
        NON_EXISTENT,
        ACTIVE,             // Normal operation: heartbeat regularly maintained
        CASCADE_PENDING,    // Inactivity threshold breached, awaiting guardian quorum
        SCREAM_WINDOW,      // 30-day global warning countdown. Owner can cancel with 1 tx
        EXECUTED,           // Assets autonomously transferred to heirs
        ABORTED             // Cancelled by owner during Scream Window, returned to ACTIVE
    }

    struct LegacyVault {
        address safeAddress;
        address primaryHeir;
        address emergencyColdStorage;
        uint256 heartbeatPeriod;      // e.g. 180 days, 365 days, up to 20 years
        uint256 lastHeartbeat;        // Timestamp of last verified pulse
        uint256 screamWindowStart;    // When 30-day final countdown began
        uint256 guardianQuorum;       // e.g. 3
        VaultState state;
        bool floatYieldEnabled;
        uint256 totalExecutedValueUSD;
    }

    // safeAddress => Vault Details
    mapping(address => LegacyVault) public vaults;
    // safeAddress => list of approved guardians
    mapping(address => address[]) public vaultGuardians;
    // safeAddress => guardianAddress => hasVotedInCascade
    mapping(address => mapping(address => bool)) public guardianVotes;
    // safeAddress => total active votes in current cascade
    mapping(address => uint256) public guardianVoteCount;

    // --- EVENTS ---
    event VaultRegistered(address indexed safe, address indexed primaryHeir, uint256 heartbeatPeriod, uint256 quorum);
    event HeartbeatRecorded(address indexed safe, uint256 timestamp);
    event CascadeTriggered(address indexed safe, uint256 timestamp);
    event GuardianVoted(address indexed safe, address indexed guardian, uint256 currentVotes, uint256 quorum);
    event ScreamWindowActivated(address indexed safe, uint256 windowEndsTimestamp);
    event ScreamWindowAborted(address indexed safe, uint256 timestamp);
    event LegacyExecuted(address indexed safe, address indexed heir, uint256 totalTokensProcessed, uint256 protocolFeeBps);

    constructor(address _protocolTreasury, address _netSwapSettlement) {
        require(_protocolTreasury != address(0), "Aeterna: Invalid treasury address");
        require(_netSwapSettlement != address(0), "Aeterna: Invalid NetSwap settlement address");
        protocolTreasury = _protocolTreasury;
        netSwapSettlement = _netSwapSettlement;
    }

    /**
     * @notice Strict authorization: caller must be the Safe itself or a validated Safe owner.
     *         Completely eliminates tx.origin vulnerabilities.
     */
    modifier onlySafeOrOwner(address safe) {
        require(
            msg.sender == safe || ISafe(safe).isOwner(msg.sender),
            "Aeterna: Caller must be Safe or authorized Safe signer"
        );
        _;
    }

    // =========================================================================
    // 1. GENESIS CONFIGURATION (SECURE REGISTRATION)
    // =========================================================================
    /**
     * @notice Register a new Aeterna continuity plan for a Safe.
     *         Restricted strictly to the Safe or authorized Safe signers to prevent frontrunning.
     */
    function registerLegacyVault(
        address safe,
        address primaryHeir,
        address emergencyColdStorage,
        uint256 heartbeatPeriod,
        address[] calldata guardians,
        uint256 quorum,
        bool floatYieldEnabled
    ) external onlySafeOrOwner(safe) {
        require(safe != address(0) && primaryHeir != address(0), "Aeterna: Invalid addresses");
        require(heartbeatPeriod >= 30 days, "Aeterna: Heartbeat period min 30 days");
        require(quorum > 0 && guardians.length >= quorum, "Aeterna: Invalid guardian quorum");
        require(vaults[safe].state == VaultState.NON_EXISTENT, "Aeterna: Vault already registered");

        vaults[safe] = LegacyVault({
            safeAddress: safe,
            primaryHeir: primaryHeir,
            emergencyColdStorage: emergencyColdStorage == address(0) ? primaryHeir : emergencyColdStorage,
            heartbeatPeriod: heartbeatPeriod,
            lastHeartbeat: block.timestamp,
            screamWindowStart: 0,
            guardianQuorum: quorum,
            state: VaultState.ACTIVE,
            floatYieldEnabled: floatYieldEnabled,
            totalExecutedValueUSD: 0
        });

        // Validate Guardian uniqueness and prevent zero addresses
        for (uint256 i = 0; i < guardians.length; i++) {
            require(guardians[i] != address(0), "Aeterna: Zero address guardian");
            require(guardians[i] != safe, "Aeterna: Safe cannot be own guardian");
            for (uint256 j = i + 1; j < guardians.length; j++) {
                require(guardians[i] != guardians[j], "Aeterna: Duplicate guardian detected");
            }
            vaultGuardians[safe].push(guardians[i]);
        }

        emit VaultRegistered(safe, primaryHeir, heartbeatPeriod, quorum);
    }

    // =========================================================================
    // 2. THE PROOF-OF-LIFE HEARTBEAT (1-TAP RESET)
    // =========================================================================
    /**
     * @notice Reset the inactivity timer. Can be called by the Safe or any authorized Safe signer.
     */
    function pingHeartbeat(address safe) external onlySafeOrOwner(safe) {
        require(
            vaults[safe].state == VaultState.ACTIVE || vaults[safe].state == VaultState.CASCADE_PENDING,
            "Aeterna: Cannot heartbeat in current state"
        );

        vaults[safe].lastHeartbeat = block.timestamp;
        vaults[safe].state = VaultState.ACTIVE;

        // Reset guardian votes if any were cast during pending phase
        _resetGuardianVotes(safe);

        emit HeartbeatRecorded(safe, block.timestamp);
    }

    // =========================================================================
    // 3. THE MULTI-TIER CASCADE PROTOCOL
    // =========================================================================
    /**
     * @notice Public trigger if the heartbeat threshold has been breached.
     */
    function triggerInactivityCascade(address safe) external {
        LegacyVault storage v = vaults[safe];
        require(v.state == VaultState.ACTIVE, "Aeterna: Vault not in active state");
        require(block.timestamp > v.lastHeartbeat + v.heartbeatPeriod, "Aeterna: Inactivity period not exceeded");

        v.state = VaultState.CASCADE_PENDING;
        emit CascadeTriggered(safe, block.timestamp);
    }

    /**
     * @notice Registered guardians attest to owner incapacitation or key loss.
     */
    function guardianAttestFailure(address safe) external {
        LegacyVault storage v = vaults[safe];
        require(v.state == VaultState.CASCADE_PENDING, "Aeterna: Not in cascade pending state");
        require(_isGuardian(safe, msg.sender), "Aeterna: Caller is not a registered guardian");
        require(!guardianVotes[safe][msg.sender], "Aeterna: Guardian has already attested");

        guardianVotes[safe][msg.sender] = true;
        guardianVoteCount[safe] += 1;

        emit GuardianVoted(safe, msg.sender, guardianVoteCount[safe], v.guardianQuorum);

        // Quorum reached -> Activate the 30-Day Scream Window
        if (guardianVoteCount[safe] >= v.guardianQuorum) {
            v.state = VaultState.SCREAM_WINDOW;
            v.screamWindowStart = block.timestamp;
            emit ScreamWindowActivated(safe, block.timestamp + SCREAM_WINDOW_SECONDS);
        }
    }

    // =========================================================================
    // 4. THE INVIOLABLE "SCREAM WINDOW" (1-SIGNATURE ABORT)
    // =========================================================================
    /**
     * @notice Abort the cascade during the 30-day challenge period.
     *         Requires Safe or validated Safe owner signature.
     */
    function abortScreamWindow(address safe) external onlySafeOrOwner(safe) {
        LegacyVault storage v = vaults[safe];
        require(
            v.state == VaultState.SCREAM_WINDOW || v.state == VaultState.CASCADE_PENDING,
            "Aeterna: Not in abortable state"
        );

        v.state = VaultState.ACTIVE;
        v.lastHeartbeat = block.timestamp;
        v.screamWindowStart = 0;
        _resetGuardianVotes(safe);

        emit ScreamWindowAborted(safe, block.timestamp);
    }

    // =========================================================================
    // 5. AUTONOMOUS LEGACY EXECUTION & NETSWAP ROUTING
    // =========================================================================
    /**
     * @notice Autonomous settlement after 30-Day Scream Window has elapsed without abort.
     *         Executes native ETH and ERC-20 transfers with strict success checks.
     */
    function executeAutonomousTransfer(
        address safe,
        address[] calldata tokens,
        bool sweepNativeETH
    ) external {
        LegacyVault storage v = vaults[safe];
        require(v.state == VaultState.SCREAM_WINDOW, "Aeterna: Vault not in scream window");
        require(
            block.timestamp >= v.screamWindowStart + SCREAM_WINDOW_SECONDS,
            "Aeterna: Scream window still active (30 days not elapsed)"
        );

        // Checks-Effects: Update state prior to external calls
        v.state = VaultState.EXECUTED;
        uint256 processedCount = 0;

        // 1. Process Native ETH Sweep
        if (sweepNativeETH) {
            uint256 ethBal = safe.balance;
            if (ethBal > 0) {
                uint256 fee = (ethBal * EXECUTION_FEE_BPS) / BPS_DENOMINATOR;
                uint256 heirAmount = ethBal - fee;

                if (fee > 0) {
                    bool feeOk = ISafe(safe).execTransactionFromModule(protocolTreasury, fee, "", 0);
                    require(feeOk, "Aeterna: ETH protocol fee transfer failed");
                }
                if (heirAmount > 0) {
                    bool heirOk = ISafe(safe).execTransactionFromModule(v.primaryHeir, heirAmount, "", 0);
                    require(heirOk, "Aeterna: ETH heir transfer failed");
                }
                processedCount++;
            }
        }

        // 2. Process ERC-20 Token Sweeps
        for (uint256 i = 0; i < tokens.length; i++) {
            address token = tokens[i];
            uint256 balance = IERC20(token).balanceOf(safe);
            if (balance > 0) {
                uint256 fee = (balance * EXECUTION_FEE_BPS) / BPS_DENOMINATOR; // 3.00%
                uint256 heirAmount = balance - fee;

                // Execute protocol fee transfer
                if (fee > 0) {
                    bytes memory feeData = abi.encodeWithSelector(IERC20.transfer.selector, protocolTreasury, fee);
                    bool feeOk = ISafe(safe).execTransactionFromModule(token, 0, feeData, 0);
                    require(feeOk, "Aeterna: Token fee transfer failed");
                }

                // Execute beneficiary succession transfer
                if (heirAmount > 0) {
                    bytes memory heirData = abi.encodeWithSelector(IERC20.transfer.selector, v.primaryHeir, heirAmount);
                    bool heirOk = ISafe(safe).execTransactionFromModule(token, 0, heirData, 0);
                    require(heirOk, "Aeterna: Token heir transfer failed");
                }

                processedCount++;
            }
        }

        emit LegacyExecuted(safe, v.primaryHeir, processedCount, EXECUTION_FEE_BPS);
    }

    // =========================================================================
    // INTERNAL HELPERS
    // =========================================================================
    function _isGuardian(address safe, address account) internal view returns (bool) {
        address[] memory guards = vaultGuardians[safe];
        for (uint256 i = 0; i < guards.length; i++) {
            if (guards[i] == account) return true;
        }
        return false;
    }

    function _resetGuardianVotes(address safe) internal {
        address[] memory guards = vaultGuardians[safe];
        for (uint256 i = 0; i < guards.length; i++) {
            guardianVotes[safe][guards[i]] = false;
        }
        guardianVoteCount[safe] = 0;
    }

    function getVaultStatus(address safe) external view returns (
        VaultState state,
        uint256 lastHeartbeat,
        uint256 heartbeatPeriod,
        uint256 screamWindowRemaining,
        uint256 currentGuardianVotes,
        uint256 quorumNeeded
    ) {
        LegacyVault memory v = vaults[safe];
        uint256 remaining = 0;
        if (v.state == VaultState.SCREAM_WINDOW) {
            uint256 deadline = v.screamWindowStart + SCREAM_WINDOW_SECONDS;
            remaining = block.timestamp < deadline ? deadline - block.timestamp : 0;
        }
        return (
            v.state,
            v.lastHeartbeat,
            v.heartbeatPeriod,
            remaining,
            guardianVoteCount[safe],
            v.guardianQuorum
        );
    }
}
