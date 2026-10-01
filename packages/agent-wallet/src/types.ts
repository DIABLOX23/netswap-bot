export interface AgentWalletConfig {
  privateKey: string;
  rpcUrl?: string;
  network?: 'base' | 'ethereum';
  mevProtection?: boolean;
}

export interface SwapParams {
  tokenIn: string;
  tokenOut: string;
  amount: string; // Human-readable amount e.g. "100" USDC
  slippageBps?: number; // Default 50 (0.50%)
  poolFee?: number; // 500, 3000, 10000 (Uniswap V3)
}

export interface SwapResult {
  txHash: string;
  amountIn: string;
  expectedOut: string;
  feePaidUsd: string;
  mevSavedUsd: string;
  status: 'FILLED_INTERNAL' | 'ROUTED_DEX';
}

export interface PortfolioBalance {
  token: string;
  symbol: string;
  balance: string;
  usdValue: string;
}
