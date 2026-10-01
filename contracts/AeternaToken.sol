// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title AeternaToken ($AET) - The Real-Yield Infrastructure & Continuity Standard
 * @notice Fixed supply ERC-20 with mathematical burn deflation and anti-exploit
 *         pro-rata ETH dividend distribution powered by NetSwap MEV & Flash Arb.
 *
 * Tokenomics:
 * - Genesis Supply: 1,000,000,000 $AET (1B Fixed)
 * - 10% Founder / Core Contributor
 * - 10% Protocol Treasury & Continuity Buffer
 * - 5% Citadel Vault Liquidity Lock
 * - 75% Fair Launch / Liquidity Pool
 */
contract AeternaToken {
    // --- ERC-20 METADATA ---
    string public constant name = "Aeterna";
    string public constant symbol = "AET";
    uint8 public constant decimals = 18;
    uint256 public totalSupply;

    // --- REENTRANCY GUARD ---
    uint8 private _unlocked = 1;
    modifier nonReentrant() {
        require(_unlocked == 1, "REENTRANT_CALL");
        _unlocked = 0;
        _;
        _unlocked = 1;
    }

    // --- BALANCES & ALLOWANCES ---
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    // --- REAL YIELD (SYNTHETIX-STYLE MAGNIFIED DIVIDEND ACCUMULATION) ---
    // Scaled by 1e18 to prevent rounding precision loss
    uint256 private constant MAGNITUDE = 1e18;
    uint256 public magnifiedDividendPerToken;
    mapping(address => int256) public magnifiedDividendCorrections;
    mapping(address => uint256) public withdrawnDividends;
    uint256 public totalYieldDistributed;

    // --- IMMUTABLE PROTOCOL DESTINATIONS ---
    address public constant FOUNDER_WALLET = 0xcC12Fd53A0bA26F42Fea6Ff8B285a77Aa54B170d;
    address public constant TREASURY_WALLET = 0xcC12Fd53A0bA26F42Fea6Ff8B285a77Aa54B170d;
    address public constant CITADEL_VAULT = 0xbE40c75844197fD334db4174CBd7D07F9bAb93f8;

    // --- EVENTS ---
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event ProofOfBurn(address indexed burner, uint256 amountBurned, uint256 newTotalSupply);
    event DividendDeposited(address indexed depositor, uint256 amountEth, uint256 totalYieldToDate);
    event DividendClaimed(address indexed holder, uint256 amountEth);

    constructor() {
        uint256 totalGenesis = 1_000_000_000 * 10**18; // 1 Billion AET
        totalSupply = totalGenesis;

        uint256 founderShare = (totalGenesis * 10) / 100;    // 10% (100M)
        uint256 treasuryShare = (totalGenesis * 10) / 100;   // 10% (100M)
        uint256 citadelShare = (totalGenesis * 5) / 100;     // 5%  (50M)
        uint256 poolShare = totalGenesis - founderShare - treasuryShare - citadelShare; // 75% (750M)

        balanceOf[FOUNDER_WALLET] = founderShare;
        emit Transfer(address(0), FOUNDER_WALLET, founderShare);

        balanceOf[TREASURY_WALLET] += treasuryShare;
        emit Transfer(address(0), TREASURY_WALLET, treasuryShare);

        balanceOf[CITADEL_VAULT] = citadelShare;
        emit Transfer(address(0), CITADEL_VAULT, citadelShare);

        balanceOf[msg.sender] = poolShare;
        emit Transfer(address(0), msg.sender, poolShare);
    }

    // --- ERC-20 STANDARD IMPLEMENTATION ---

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 currentAllowance = allowance[from][msg.sender];
        if (currentAllowance != type(uint256).max) {
            require(currentAllowance >= amount, "ERC20: insufficient allowance");
            allowance[from][msg.sender] = currentAllowance - amount;
        }
        _transfer(from, to, amount);
        return true;
    }

    function _transfer(address from, address to, uint256 amount) internal {
        require(from != address(0), "ERC20: transfer from zero");
        require(to != address(0), "ERC20: transfer to zero");
        require(balanceOf[from] >= amount, "ERC20: transfer amount exceeds balance");

        balanceOf[from] -= amount;
        balanceOf[to] += amount;

        // Anti-Flashloan Dividend Corrections:
        // Adjust dividend correction so recipient only earns dividends accumulated AFTER transfer
        int256 magCorrection = int256(magnifiedDividendPerToken * amount);
        magnifiedDividendCorrections[from] += magCorrection;
        magnifiedDividendCorrections[to] -= magCorrection;

        emit Transfer(from, to, amount);
    }

    // --- MATHEMATICAL DEFLATION (BURN) ---

    function burn(uint256 amount) external {
        require(balanceOf[msg.sender] >= amount, "ERC20: burn exceeds balance");

        balanceOf[msg.sender] -= amount;
        totalSupply -= amount;

        // Adjust dividend correction for burned tokens
        magnifiedDividendCorrections[msg.sender] += int256(magnifiedDividendPerToken * amount);

        emit Transfer(msg.sender, address(0), amount);
        emit ProofOfBurn(msg.sender, amount, totalSupply);
    }

    // --- REAL YIELD DIVIDEND DISTRIBUTION (CALLABLE BY FLASH ARB / COMMUNITY) ---

    receive() external payable {
        depositDividends();
    }

    function depositDividends() public payable {
        require(msg.value > 0, "No ETH deposited");
        require(totalSupply > 0, "No circulating supply");

        magnifiedDividendPerToken += (msg.value * MAGNITUDE) / totalSupply;
        totalYieldDistributed += msg.value;

        emit DividendDeposited(msg.sender, msg.value, totalYieldDistributed);
    }

    // --- DIVIDEND CLAIMING & VIEWS ---

    function accumulativeDividendOf(address account) public view returns (uint256) {
        int256 accumulated = int256(magnifiedDividendPerToken * balanceOf[account]) + magnifiedDividendCorrections[account];
        return accumulated > 0 ? uint256(accumulated) / MAGNITUDE : 0;
    }

    function withdrawableDividendOf(address account) public view returns (uint256) {
        uint256 totalAccumulated = accumulativeDividendOf(account);
        uint256 withdrawn = withdrawnDividends[account];
        return totalAccumulated > withdrawn ? totalAccumulated - withdrawn : 0;
    }

    function claimDividends() external nonReentrant returns (uint256) {
        uint256 withdrawable = withdrawableDividendOf(msg.sender);
        require(withdrawable > 0, "No dividends to claim");

        withdrawnDividends[msg.sender] += withdrawable;

        (bool success, ) = msg.sender.call{value: withdrawable}("");
        require(success, "ETH transfer failed");

        emit DividendClaimed(msg.sender, withdrawable);
        return withdrawable;
    }
}
