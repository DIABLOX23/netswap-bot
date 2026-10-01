// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address recipient, uint256 amount) external returns (bool);
    function approve(address spender, uint256 amount) external returns (bool);
}

interface IWETH is IERC20 {
    function deposit() external payable;
    function withdraw(uint256 amount) external;
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

interface IUniswapV3Pool {
    function token0() external view returns (address);
    function token1() external view returns (address);
    function flash(
        address recipient,
        uint256 amount0,
        uint256 amount1,
        bytes calldata data
    ) external;
}

contract FlashArbExecutor {
    address public immutable owner;
    address public constant WETH = 0x4200000000000000000000000000000000000006;
    address public constant AERO_ROUTER = 0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43;
    address public constant UNI_ROUTER = 0x2626664c2603336E57B271c5C0b26F421741e481;
    address public constant OPERATOR = 0xbE40c75844197fD334db4174CBd7D07F9bAb93f8;
    address public aeternaToken;

    receive() external payable {}

    modifier onlyOwner() {
        require(msg.sender == owner, "!owner");
        _;
    }

    function setAeternaToken(address _token) external onlyOwner {
        aeternaToken = _token;
    }

    constructor() {
        owner = msg.sender;
        IERC20(WETH).approve(AERO_ROUTER, type(uint256).max);
        IERC20(WETH).approve(UNI_ROUTER, type(uint256).max);
    }

    function uniswapV3FlashCallback(
        uint256 fee0,
        uint256 fee1,
        bytes calldata data
    ) external {
        (
            address targetToken,
            uint256 borrowAmount,
            uint24 uniFee,
            bool aeroFirst,
            bool aeroStable,
            address aeroFactory,
            uint256 minProfit
        ) = abi.decode(data, (address, uint256, uint24, bool, bool, address, uint256));

        uint256 totalOwed = borrowAmount + (fee0 > 0 ? fee0 : fee1);

        IERC20(targetToken).approve(AERO_ROUTER, type(uint256).max);
        IERC20(targetToken).approve(UNI_ROUTER, type(uint256).max);

        if (aeroFirst) {
            IAeroRouter.Route[] memory routes = new IAeroRouter.Route[](1);
            routes[0] = IAeroRouter.Route(WETH, targetToken, aeroStable, aeroFactory);
            uint256[] memory amounts = IAeroRouter(AERO_ROUTER).swapExactTokensForTokens(
                borrowAmount,
                0,
                routes,
                address(this),
                block.timestamp
            );
            uint256 tokensReceived = amounts[amounts.length - 1];

            ISwapRouter02.ExactInputSingleParams memory params = ISwapRouter02.ExactInputSingleParams({
                tokenIn: targetToken,
                tokenOut: WETH,
                fee: uniFee,
                recipient: address(this),
                amountIn: tokensReceived,
                amountOutMinimum: totalOwed + minProfit,
                sqrtPriceLimitX96: 0
            });
            ISwapRouter02(UNI_ROUTER).exactInputSingle(params);
        } else {
            ISwapRouter02.ExactInputSingleParams memory params = ISwapRouter02.ExactInputSingleParams({
                tokenIn: WETH,
                tokenOut: targetToken,
                fee: uniFee,
                recipient: address(this),
                amountIn: borrowAmount,
                amountOutMinimum: 0,
                sqrtPriceLimitX96: 0
            });
            uint256 tokensReceived = ISwapRouter02(UNI_ROUTER).exactInputSingle(params);

            IAeroRouter.Route[] memory routes = new IAeroRouter.Route[](1);
            routes[0] = IAeroRouter.Route(targetToken, WETH, aeroStable, aeroFactory);
            IAeroRouter(AERO_ROUTER).swapExactTokensForTokens(
                tokensReceived,
                totalOwed + minProfit,
                routes,
                address(this),
                block.timestamp
            );
        }

        uint256 currentWeth = IERC20(WETH).balanceOf(address(this));
        require(currentWeth >= totalOwed + minProfit, "INSUFFICIENT_PROFIT");
        
        // Repay flash loan pool
        IERC20(WETH).transfer(msg.sender, totalOwed);

        // Sweep net profit: 50% to Aeterna Real Yield dividend pool, 50% to Operator
        uint256 profit = IERC20(WETH).balanceOf(address(this));
        if (profit > 0) {
            if (aeternaToken != address(0)) {
                uint256 yieldShare = profit / 2;
                uint256 operatorShare = profit - yieldShare;

                // Unwrap WETH to raw ETH for dividend deposit
                IWETH(WETH).withdraw(yieldShare);
                (bool success, ) = aeternaToken.call{value: yieldShare}(abi.encodeWithSignature("depositDividends()"));
                require(success, "DIVIDEND_DEPOSIT_FAILED");

                IERC20(WETH).transfer(OPERATOR, operatorShare);
            } else {
                IERC20(WETH).transfer(OPERATOR, profit);
            }
        }
    }

    function executeArb(
        address flashPool,
        address targetToken,
        uint256 borrowAmount,
        uint24 uniFee,
        bool aeroFirst,
        bool aeroStable,
        address aeroFactory,
        uint256 minProfit
    ) external onlyOwner {
        bytes memory data = abi.encode(
            targetToken,
            borrowAmount,
            uniFee,
            aeroFirst,
            aeroStable,
            aeroFactory,
            minProfit
        );

        address t0 = IUniswapV3Pool(flashPool).token0();
        uint256 amount0 = (t0 == WETH) ? borrowAmount : 0;
        uint256 amount1 = (t0 == WETH) ? 0 : borrowAmount;

        IUniswapV3Pool(flashPool).flash(address(this), amount0, amount1, data);
    }

    // Emergency rescue function
    function rescueToken(address token) external onlyOwner {
        uint256 bal = IERC20(token).balanceOf(address(this));
        if (bal > 0) {
            IERC20(token).transfer(OPERATOR, bal);
        }
    }
}
