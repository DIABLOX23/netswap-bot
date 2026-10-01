// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title AeternaToken ($AET)
 * @notice The Sovereign Governance & Fee-Siphon Asset of the Aeterna Continuity Protocol.
 * 
 * Tokenomics:
 * - Total Supply: 1,000,000,000 $AET (Fixed forever. Zero inflation. Zero minting after genesis.)
 * - 80% (800,000,000 $AET): Fair Launch Liquidity Pool (Aerodrome / Uniswap v3)
 * - 10% (100,000,000 $AET): Founder / Core Contributor Treasury (Locked / Secondary OTC)
 * - 10% (100,000,000 $AET): On-Chain Mainnet Security Challenge & Bug Bounty Reserve
 *
 * Value Accrual:
 * - All NetSwap execution fees (3%) & Float Yield Siphons (20%) can be routed to buy back and burn $AET.
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
        address founderTreasury,
        address bountyReserve,
        address liquidityDistributor
    ) {
        require(founderTreasury != address(0), "Invalid founder address");
        require(bountyReserve != address(0), "Invalid bounty address");
        require(liquidityDistributor != address(0), "Invalid LP distributor");

        uint256 founderAmount = (totalSupply * 10) / 100;     // 10% (100M)
        uint256 bountyAmount = (totalSupply * 10) / 100;      // 10% (100M)
        uint256 liquidityAmount = totalSupply - founderAmount - bountyAmount; // 80% (800M)

        balanceOf[founderTreasury] = founderAmount;
        emit Transfer(address(0), founderTreasury, founderAmount);

        balanceOf[bountyReserve] = bountyAmount;
        emit Transfer(address(0), bountyReserve, bountyAmount);

        balanceOf[liquidityDistributor] = liquidityAmount;
        emit Transfer(address(0), liquidityDistributor, liquidityAmount);
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
