export interface AgentWalletConfig {
  privateKey: string;
  rpcUrl?: string;
  network?: 'base' | 'ethereum';
  mevProtection?: boolean;
  routerAddress?: string;
  tollboothAddress?: string;
}

export type WalletConfig = AgentWalletConfig;

export interface SwapParams {
  tokenIn: string;
  tokenOut: string;
  amount: string; // Human-readable amount e.g. "100" USDC or raw units
  slippageBps?: number; // Default 50 (0.50%) or 200 (2.0%)
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
  success?: boolean;
  txHash: string;
  amountIn?: string;
  amountOut?: string;
  expectedOut?: string;
  minAmountOut?: string;
  gasUsed?: string;
  feePaidUsd?: string;
  mevSavedUsd?: string;
  status?: 'FILLED_INTERNAL' | 'ROUTED_DEX' | 'ROUTED_UNISWAP_V3';
  error?: string;
}

export interface PortfolioBalance {
  token: string;
  symbol: string;
  balance: string;
  usdValue: string;
}
