// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title ShadowLiquidator
 * @notice High-Performance Atomic Flash Loan Liquidator for Base Mainnet.
 * @dev Integrates with Aave V3 and Seamless Protocol pools on Base (8453).
 *      Executes atomic liquidation + DEX swap + flash loan repayment in a single transaction.
 *      Protected by the Shadow Simulation Gate (zero execution unless net profitable).
 */

interface IERC20 {
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address recipient, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
}

interface IPool {
    function flashLoanSimple(
        address receiverAddress,
        address asset,
        uint256 amount,
        bytes calldata params,
        uint16 referralCode
    ) external;

    function liquidationCall(
        address collateralAsset,
        address debtAsset,
        address user,
        uint256 debtToCover,
        bool receiveAToken
    ) external;

    function getUserAccountData(address user)
        external
        view
        returns (
            uint256 totalCollateralBase,
            uint256 totalDebtBase,
            uint256 availableBorrowsBase,
            uint256 currentLiquidationThreshold,
            uint256 ltv,
            uint256 healthFactor
        );
}

interface ISwapRouter {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }

    function exactInputSingle(ExactInputSingleParams calldata params) external returns (uint256 amountOut);
}

contract ShadowLiquidator {
    address public immutable owner;
    
    // Base Mainnet Verified Protocol Addresses
    address public constant AAVE_POOL_BASE = 0xA238Dd80C259a72e81d7e4664a9801593F98d1c5;
    address public constant SEAMLESS_POOL_BASE = 0x8f44Fd754285aa6A2b8B9B97739B79746e0475a7;
    address public constant UNISWAP_ROUTER_BASE = 0x2626664c2603336E57B271c5C0b26F421741e481;

    event LiquidationExecuted(
        address indexed borrower,
        address indexed debtAsset,
        address indexed collateralAsset,
        uint256 debtCovered,
        uint256 netProfit
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can execute");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    /**
     * @notice Initiates atomic flashloan liquidation.
     * @dev Triggered by the Python bot only after local eth_call proves net profitability.
     */
    function executeShadowLiquidation(
        address poolAddress,
        address debtAsset,
        uint256 debtToCover,
        address collateralAsset,
        address borrower,
        uint24 dexPoolFee,
        uint256 minNetProfit
    ) external onlyOwner {
        bytes memory params = abi.encode(
            poolAddress,
            debtAsset,
            debtToCover,
            collateralAsset,
            borrower,
            dexPoolFee,
            minNetProfit
        );

        IPool(poolAddress).flashLoanSimple(
            address(this),
            debtAsset,
            debtToCover,
            params,
            0
        );
    }

    /**
     * @notice Aave/Seamless Flash Loan callback.
     * @dev Executes: 1. Liquidation -> 2. Swap Collateral -> 3. Repay Loan -> 4. Send Profit.
     */
    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external returns (bool) {
        require(initiator == address(this), "Untrusted flashloan initiator");

        (
            address poolAddress,
            address debtAsset,
            uint256 debtToCover,
            address collateralAsset,
            address borrower,
            uint24 dexPoolFee,
            uint256 minNetProfit
        ) = abi.decode(params, (address, address, uint256, address, address, uint24, uint256));

        require(msg.sender == poolAddress, "Untrusted lending pool");

        // Step 1: Approve pool to spend flashloaned debt tokens
        IERC20(debtAsset).approve(poolAddress, debtToCover);

        // Step 2: Liquidate underwater borrower (Seizes discounted collateral)
        IPool(poolAddress).liquidationCall(
            collateralAsset,
            debtAsset,
            borrower,
            debtToCover,
            false // Receive underlying token, not aToken
        );

        // Step 3: Swap seized collateral back to debtAsset (if different)
        uint256 seizedCollateralBalance = IERC20(collateralAsset).balanceOf(address(this));
        if (collateralAsset != debtAsset && seizedCollateralBalance > 0) {
            IERC20(collateralAsset).approve(UNISWAP_ROUTER_BASE, seizedCollateralBalance);
            
            ISwapRouter.ExactInputSingleParams memory swapParams = ISwapRouter.ExactInputSingleParams({
                tokenIn: collateralAsset,
                tokenOut: debtAsset,
                fee: dexPoolFee,
                recipient: address(this),
                amountIn: seizedCollateralBalance,
                amountOutMinimum: 0, // Checked atomically below by total repayment requirement
                sqrtPriceLimitX96: 0
            });

            ISwapRouter(UNISWAP_ROUTER_BASE).exactInputSingle(swapParams);
        }

        // Step 4: Atomic Profit & Repayment Verification
        uint256 totalOwed = amount + premium;
        uint256 currentBalance = IERC20(debtAsset).balanceOf(address(this));

        // THE GOD MODE ATOMIC INVARIANT: Must repay flashloan AND hit minimum profit
        require(currentBalance >= totalOwed + minNetProfit, "Net profit threshold breached");

        // Step 5: Approve pool to take repayment
        IERC20(debtAsset).approve(poolAddress, totalOwed);

        // Step 6: Extract pure net profit to owner wallet
        uint256 netProfit = currentBalance - totalOwed;
        if (netProfit > 0) {
            IERC20(debtAsset).transfer(owner, netProfit);
        }

        emit LiquidationExecuted(borrower, debtAsset, collateralAsset, debtToCover, netProfit);

        return true;
    }

    /**
     * @notice Emergency withdrawal for any residual tokens.
     */
    function withdrawToken(address token) external onlyOwner {
        uint256 balance = IERC20(token).balanceOf(address(this));
        if (balance > 0) {
            IERC20(token).transfer(owner, balance);
        }
    }

    /**
     * @notice Emergency withdrawal for native ETH.
     */
    function withdrawETH() external onlyOwner {
        uint256 balance = address(this).balance;
        if (balance > 0) {
            payable(owner).transfer(balance);
        }
    }

    receive() external payable {}
}
