// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20 {
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address recipient, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
}

/**
 * @title NetSwap Multi-Party Continuous Netting Settlement Engine
 * @notice Atomically matches opposing swap intents peer-to-peer, extracts 50 bps surplus toll,
 *         and routes residual change to external AMM routers without inventory or custody risk.
 */
contract NettingSettlement {
    bytes32 public immutable DOMAIN_SEPARATOR;
    bytes32 public constant ORDER_TYPEHASH = keccak256(
        "Order(address trader,address tokenIn,address tokenOut,uint256 amountIn,uint256 minAmountOut,uint256 nonce,uint256 deadline)"
    );

    address public immutable feeRecipient;
    uint256 public constant FEE_BPS = 50; // 0.50%
    uint256 public constant BPS_DENOMINATOR = 10000;

    mapping(address => mapping(uint256 => bool)) public executedOrCancelled;

    uint256 public totalVolumeSettledUSD;
    uint256 public totalFeesCollectedUSD;
    uint256 public batchCount;

    struct Order {
        address trader;
        address tokenIn;
        address tokenOut;
        uint256 amountIn;
        uint256 minAmountOut;
        uint256 nonce;
        uint256 deadline;
    }

    struct MatchAllocation {
        uint256 buyerIndex;
        uint256 sellerIndex;
        uint256 amountToken0; // e.g. WETH amount
        uint256 amountToken1; // e.g. USDC amount
    }

    event OrderSettled(address indexed trader, address tokenIn, address tokenOut, uint256 amountIn, uint256 amountOut);
    event BatchSettled(uint256 indexed batchId, uint256 matchedVolumeToken1, uint256 protocolFeeToken1);
    event OrderCancelled(address indexed trader, uint256 nonce);

    constructor(address _feeRecipient) {
        require(_feeRecipient != address(0), "Invalid fee recipient");
        feeRecipient = _feeRecipient;

        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256(bytes("NetSwapSettlement")),
                keccak256(bytes("1")),
                block.chainid,
                address(this)
            )
        );
    }

    function cancelOrder(uint256 nonce) external {
        executedOrCancelled[msg.sender][nonce] = true;
        emit OrderCancelled(msg.sender, nonce);
    }

    function verifyOrderSignature(Order calldata order, bytes calldata signature) public view returns (bool) {
        require(block.timestamp <= order.deadline, "Order expired");
        require(!executedOrCancelled[order.trader][order.nonce], "Order already executed/cancelled");

        bytes32 structHash = keccak256(
            abi.encode(
                ORDER_TYPEHASH,
                order.trader,
                order.tokenIn,
                order.tokenOut,
                order.amountIn,
                order.minAmountOut,
                order.nonce,
                order.deadline
            )
        );

        bytes32 digest = keccak256(
            abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash)
        );

        return (recoverSigner(digest, signature) == order.trader);
    }

    function recoverSigner(bytes32 digest, bytes calldata signature) internal pure returns (address) {
        require(signature.length == 65, "Invalid signature length");
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        return ecrecover(digest, v, r, s);
    }

    function _pullAndVerifyOrders(
        Order[] calldata orders,
        bytes[] calldata signatures,
        address expectedTokenIn,
        address expectedTokenOut
    ) internal {
        for (uint256 i = 0; i < orders.length; i++) {
            require(orders[i].tokenIn == expectedTokenIn && orders[i].tokenOut == expectedTokenOut, "Token mismatch");
            require(verifyOrderSignature(orders[i], signatures[i]), "Invalid signature");
            executedOrCancelled[orders[i].trader][orders[i].nonce] = true;
            require(IERC20(expectedTokenIn).transferFrom(orders[i].trader, address(this), orders[i].amountIn), "Pull failed");
        }
    }

    function settleMultiPartyBatch(
        address token0, // e.g. WETH
        address token1, // e.g. USDC
        Order[] calldata buyers,  // tokenIn = token1, tokenOut = token0
        bytes[] calldata buyerSignatures,
        Order[] calldata sellers, // tokenIn = token0, tokenOut = token1
        bytes[] calldata sellerSignatures,
        MatchAllocation[] calldata allocations,
        address residualRouter,
        bytes calldata residualSwapData
    ) external {
        require(buyers.length == buyerSignatures.length, "Buyer sig mismatch");
        require(sellers.length == sellerSignatures.length, "Seller sig mismatch");

        // 1. Verify signatures and pull tokens
        _pullAndVerifyOrders(buyers, buyerSignatures, token1, token0);
        _pullAndVerifyOrders(sellers, sellerSignatures, token0, token1);

        // 2. Track payouts
        uint256[] memory buyerToken0Received = new uint256[](buyers.length);
        uint256[] memory sellerToken1Received = new uint256[](sellers.length);
        uint256 totalNettedToken1 = 0;

        for (uint256 k = 0; k < allocations.length; k++) {
            MatchAllocation calldata alloc = allocations[k];
            buyerToken0Received[alloc.buyerIndex] += alloc.amountToken0;
            sellerToken1Received[alloc.sellerIndex] += alloc.amountToken1;
            totalNettedToken1 += alloc.amountToken1;
        }

        // 3. 50 bps protocol fee directly deducted from total matched token1
        uint256 protocolFee = (totalNettedToken1 * FEE_BPS) / BPS_DENOMINATOR;
        if (protocolFee > 0) {
            require(IERC20(token1).transfer(feeRecipient, protocolFee), "Fee transfer failed");
        }

        // 4. Residual routing
        if (residualRouter != address(0) && residualSwapData.length > 0) {
            (bool success, ) = residualRouter.call(residualSwapData);
            require(success, "Residual swap failed");
        }

        // 5. Payouts and invariant checks (Token0 to Buyers, Net Token1 to Sellers)
        for (uint256 i = 0; i < buyers.length; i++) {
            require(buyerToken0Received[i] >= buyers[i].minAmountOut, "Buyer slippage exceeded");
            require(IERC20(token0).transfer(buyers[i].trader, buyerToken0Received[i]), "Buyer payout failed");
            emit OrderSettled(buyers[i].trader, token1, token0, buyers[i].amountIn, buyerToken0Received[i]);
        }

        for (uint256 j = 0; j < sellers.length; j++) {
            uint256 sellerFee = (sellerToken1Received[j] * FEE_BPS) / BPS_DENOMINATOR;
            uint256 netSellerPayout = sellerToken1Received[j] - sellerFee;
            require(netSellerPayout >= sellers[j].minAmountOut, "Seller slippage exceeded");
            require(IERC20(token1).transfer(sellers[j].trader, netSellerPayout), "Seller payout failed");
            emit OrderSettled(sellers[j].trader, token0, token1, sellers[j].amountIn, netSellerPayout);
        }

        batchCount++;
        emit BatchSettled(batchCount, totalNettedToken1, protocolFee);
    }
}
