// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title AeternaIntentRouter
 * @notice The Institutional Intent & MEV-Protected Execution Router for AI Agents.
 * @dev Accepts swap intents, matches via P2P batch netting/solver fill, or routes to
 *      underlying DEXes (Aerodrome / Uniswap V3) with a standard 0.15% (15 bps) protocol fee.
 */

interface IERC20 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address recipient, uint256 amount) external returns (bool);
    function approve(address spender, uint256 amount) external returns (bool);
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
}

interface ISwapRouter02 {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }
    function exactInputSingle(ExactInputSingleParams calldata params) external payable returns (uint256 amountOut);
}

interface IAeroRouter {
    struct Route {
        address from;
        address to;
        bool stable;
        address factory;
    }
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        Route[] calldata routes,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);
}

contract AeternaIntentRouter {
    address public immutable owner;
    address public constant PROTOCOL_TREASURY = 0xcC12Fd53A0bA26F42Fea6Ff8B285a77Aa54B170d;
    
    // Routers on Base Mainnet
    address public constant UNI_ROUTER = 0x2626664c2603336E57B271c5C0b26F421741e481;
    address public constant AERO_ROUTER = 0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43;
    address public constant WETH = 0x4200000000000000000000000000000000000006;

    // 15 basis points = 0.15%
    uint256 public constant PROTOCOL_FEE_BPS = 15;
    uint256 public constant BPS_DENOMINATOR = 10000;

    mapping(address => bool) public authorizedSolvers;

    struct Intent {
        address agent;
        address tokenIn;
        address tokenOut;
        uint256 amountIn;
        uint256 minAmountOut;
        uint256 deadline;
        bytes32 intentHash;
    }

    event IntentExecuted(
        bytes32 indexed intentHash,
        address indexed agent,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 amountOut,
        uint256 feeTaken,
        bool solvedInternally
    );

    event SolverUpdated(address indexed solver, bool status);

    modifier onlyOwner() {
        require(msg.sender == owner, "!owner");
        _;
    }

    constructor() {
        owner = msg.sender;
        authorizedSolvers[msg.sender] = true;
    }

    function setSolver(address solver, bool status) external onlyOwner {
        authorizedSolvers[solver] = true;
        emit SolverUpdated(solver, status);
    }

    /**
     * @notice Fill an AI agent's intent directly via solver (Internal Dark Pool / Netting).
     * Zero DEX slippage, captures the spread for the solver while saving the agent gas.
     */
    function fillIntentDirect(
        Intent calldata intent,
        uint256 solverAmountOut
    ) external {
        require(authorizedSolvers[msg.sender], "NOT_AUTHORIZED_SOLVER");
        require(block.timestamp <= intent.deadline, "INTENT_EXPIRED");
        require(solverAmountOut >= intent.minAmountOut, "SLIPPAGE_EXCEEDED");

        // 1. Pull tokenIn from Agent
        IERC20(intent.tokenIn).transferFrom(intent.agent, address(this), intent.amountIn);

        // 2. Calculate protocol fee (0.15%)
        uint256 fee = (intent.amountIn * PROTOCOL_FEE_BPS) / BPS_DENOMINATOR;
        uint256 netIn = intent.amountIn - fee;

        // 3. Send fee to Protocol Treasury
        IERC20(intent.tokenIn).transfer(PROTOCOL_TREASURY, fee);

        // 4. Send net tokenIn to Solver
        IERC20(intent.tokenIn).transfer(msg.sender, netIn);

        // 5. Solver pays tokenOut directly to Agent
        IERC20(intent.tokenOut).transferFrom(msg.sender, intent.agent, solverAmountOut);

        emit IntentExecuted(
            intent.intentHash,
            intent.agent,
            intent.tokenIn,
            intent.tokenOut,
            intent.amountIn,
            solverAmountOut,
            fee,
            true
        );
    }

    /**
     * @notice Fallback execution via external DEX (Uniswap V3 on Base) with automated fee capture.
     */
    function executeSwapUniV3(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut,
        uint24 poolFee
    ) external returns (uint256 amountOut) {
        require(amountIn > 0, "ZERO_INPUT");

        // 1. Pull tokenIn from Agent
        IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn);

        // 2. Deduct 0.15% protocol fee
        uint256 fee = (amountIn * PROTOCOL_FEE_BPS) / BPS_DENOMINATOR;
        uint256 swapAmount = amountIn - fee;
        IERC20(tokenIn).transfer(PROTOCOL_TREASURY, fee);

        // 3. Approve Uni Router
        IERC20(tokenIn).approve(UNI_ROUTER, swapAmount);

        // 4. Execute Swap with Agent as Recipient
        ISwapRouter02.ExactInputSingleParams memory params = ISwapRouter02.ExactInputSingleParams({
            tokenIn: tokenIn,
            tokenOut: tokenOut,
            fee: poolFee,
            recipient: msg.sender,
            amountIn: swapAmount,
            amountOutMinimum: minAmountOut,
            sqrtPriceLimitX96: 0
        });

        amountOut = ISwapRouter02(UNI_ROUTER).exactInputSingle(params);

        emit IntentExecuted(
            keccak256(abi.encodePacked(msg.sender, tokenIn, tokenOut, block.timestamp)),
            msg.sender,
            tokenIn,
            tokenOut,
            amountIn,
            amountOut,
            fee,
            false
        );
    }
}
