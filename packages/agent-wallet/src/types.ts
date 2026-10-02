export interface AgentWalletConfig {
  privateKey: string;
  rpcUrl?: string;
  network?: 'base' | 'ethereum';
  mevProtection?: boolean;
  routerAddress?: string;
}

export interface SwapParams {
  tokenIn: string;
  tokenOut: string;
  amount: string; // Human-readable amount e.g. "100" USDC
  slippageBps?: number; // Default 50 (0.50%)
  poolFee?: number; // 500 (0.05%), 3000 (0.3%), 10000 (1%)
  minAmountOut?: bigint | string; // Optional custom minAmountOut floor
}

export interface QuoteResult {
  amountIn: string;
  rawAmountIn: bigint;
  netAmountIn: bigint;
  expectedOut: string;
  rawExpectedOut: bigint;
  minAmountOut: bigint;
  formattedMinOut: string;
  feeAmount: string;
  slippageBps: number;
  poolFee: number;
}

export interface SwapResult {
  txHash: string;
  amountIn: string;
  expectedOut: string;
  minAmountOut: string;
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
