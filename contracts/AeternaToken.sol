// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title AeternaToken ($AET)
 * @notice The Sovereign Governance, Flash Arb Fuel & Value-Accrual Asset of Aeterna Protocol.
 * 
 * Total Supply: 1,000,000,000 $AET (1 Billion Fixed Forever. Zero Inflation.)
 *
 * Strategic Allocation (The 25% Controlled Gravity Structure):
 * - 10% (100,000,000 $AET): Core Contributors / Founder Allocation (Personal Deployer)
 * - 10% (100,000,000 $AET): Strategic Ecosystem Treasury (CEX Listings, Security Bounties, OTC)
 * - 5%  (50,000,000 $AET):  Flash Arb & Gas Reserve (NetSwap Autonomous Hunter Bot)
 * - 75% (750,000,000 $AET): Fair Launch Liquidity (Clanker / Aerodrome / Uniswap v3 on Base)
 *
 * Deflationary Burn Mechanism:
 * - NetSwap Flash Arb & Aeterna Cascade execution fees are programmatically routed 
 *   to buy back and burn $AET, permanently shrinking circulating supply.
 */
contract AeternaToken {
    string public constant name = "Aeterna Protocol";
    string public constant symbol = "AET";
    uint8 public constant decimals = 18;
    uint256 public constant totalSupply = 1_000_000_000 * 10**18; // 1 Billion

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event Burn(address indexed from, uint256 value);

    constructor(
        address coreContributors,
        address strategicTreasury,
        address flashArbGasReserve,
        address fairLaunchLiquidity
    ) {
        require(coreContributors != address(0), "Invalid core contributor address");
        require(strategicTreasury != address(0), "Invalid strategic treasury address");
        require(flashArbGasReserve != address(0), "Invalid flash arb reserve address");
        require(fairLaunchLiquidity != address(0), "Invalid liquidity pool address");

        uint256 coreAmount = (totalSupply * 10) / 100;       // 10% (100,000,000 $AET)
        uint256 treasuryAmount = (totalSupply * 10) / 100;   // 10% (100,000,000 $AET)
        uint256 flashArbAmount = (totalSupply * 5) / 100;    // 5%  (50,000,000 $AET)
        uint256 liquidityAmount = totalSupply - coreAmount - treasuryAmount - flashArbAmount; // 75% (750,000,000 $AET)

        balanceOf[coreContributors] = coreAmount;
        emit Transfer(address(0), coreContributors, coreAmount);

        balanceOf[strategicTreasury] = treasuryAmount;
        emit Transfer(address(0), strategicTreasury, treasuryAmount);

        balanceOf[flashArbGasReserve] = flashArbAmount;
        emit Transfer(address(0), flashArbGasReserve, flashArbAmount);

        balanceOf[fairLaunchLiquidity] = liquidityAmount;
        emit Transfer(address(0), fairLaunchLiquidity, liquidityAmount);
    }

    function transfer(address recipient, uint256 amount) external returns (bool) {
        _transfer(msg.sender, recipient, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool) {
        uint256 currentAllowance = allowance[sender][msg.sender];
        if (currentAllowance != type(uint256).max) {
            require(currentAllowance >= amount, "ERC20: transfer amount exceeds allowance");
            allowance[sender][msg.sender] = currentAllowance - amount;
        }
        _transfer(sender, recipient, amount);
        return true;
    }

    /**
     * @notice Permanent burn function. Used by NetSwap Flash Arb & Cascade module
     *         to consume tokens purchased with protocol profits, deflating total supply.
     */
    function burn(uint256 amount) external {
        require(balanceOf[msg.sender] >= amount, "ERC20: burn amount exceeds balance");
        balanceOf[msg.sender] -= amount;
        emit Transfer(msg.sender, address(0), amount);
        emit Burn(msg.sender, amount);
    }

    function _transfer(address sender, address recipient, uint256 amount) internal {
        require(sender != address(0), "ERC20: transfer from zero address");
        require(recipient != address(0), "ERC20: transfer to zero address");
        require(balanceOf[sender] >= amount, "ERC20: transfer amount exceeds balance");

        balanceOf[sender] -= amount;
        balanceOf[recipient] += amount;
        emit Transfer(sender, recipient, amount);
    }
}
