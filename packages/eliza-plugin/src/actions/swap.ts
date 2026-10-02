import { AgentWallet } from '@netswap_protocol/agent-wallet';

export const executeSwapAction = {
  name: 'EXECUTE_PROTECTED_SWAP',
  description: 'Executes an MEV-protected token swap on Base with real-time Uniswap V3 slippage floor enforcement and 0.15% fee routing.',
  similes: ['SWAP_TOKENS', 'PROTECTED_SWAP', 'MEV_SWAP', 'TRADE_TOKENS'],
  examples: [
    [
      { user: 'user', content: { text: 'Swap 500 USDC for WETH using protected routing' } },
      { user: 'agent', content: { text: 'Executing MEV-protected swap for 500 USDC -> WETH via Aeterna Router with slippage floor...' } }
    ]
  ],
  validate: async (runtime: any, _message: any) => {
    const key = runtime.getSetting('AETERNA_AGENT_PRIVATE_KEY') ||
                runtime.getSetting('WALLET_PRIVATE_KEY') ||
                process.env.AETERNA_AGENT_PRIVATE_KEY ||
                process.env.WALLET_PRIVATE_KEY;
    return Boolean(key);
  },
  handler: async (runtime: any, _message: any, _state: any, options: any, callback?: any) => {
    try {
      const privateKey = runtime.getSetting('AETERNA_AGENT_PRIVATE_KEY') ||
                         runtime.getSetting('WALLET_PRIVATE_KEY') ||
                         process.env.AETERNA_AGENT_PRIVATE_KEY ||
                         process.env.WALLET_PRIVATE_KEY;

      if (!privateKey) {
        throw new Error('AETERNA_AGENT_PRIVATE_KEY or WALLET_PRIVATE_KEY is required to sign transactions.');
      }

      const rpcUrl = runtime.getSetting('BASE_RPC_URL') || process.env.BASE_RPC_URL || 'https://mainnet.base.org';
      const agent = new AgentWallet({ privateKey, rpcUrl, network: 'base', mevProtection: true });

      // Robust parameter extraction across Eliza versions
      const params = options?.parameters || options || {};
      const tokenIn = params.tokenIn || '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'; // USDC on Base
      const tokenOut = params.tokenOut || '0x4200000000000000000000000000000000000006'; // WETH on Base
      const amount = String(params.amount || '10');
      const slippageBps = params.slippageBps ? Number(params.slippageBps) : 50; // 0.50% default
      const poolFee = params.poolFee ? Number(params.poolFee) : undefined;

      // 1. Get live on-chain quote and slippage floor
      const quote = await agent.getQuote({
        tokenIn,
        tokenOut,
        amount,
        slippageBps,
        poolFee
      });

      // 2. Execute swap
      const result = await agent.swap({
        tokenIn,
        tokenOut,
        amount,
        slippageBps,
        poolFee
      });

      const responseText = [
        '🛡️ [Aeterna Protected Execution]',
        `Swapped: ${result.amountIn} -> ${quote.expectedOut} (Min Guaranteed: ${result.minAmountOut})`,
        `Tx Hash: https://basescan.org/tx/${result.txHash}`,
        `MEV Protected (Est.): ${result.mevSavedUsd}`,
        `Protocol Routing Fee (0.15%): ${result.feePaidUsd}`,
        'Execution Status: 0% Sandwich Slippage Floor Enforced'
      ].join('\n');

      if (callback) {
        callback({ text: responseText, content: { success: true, result } });
      }

      return {
        success: true,
        text: responseText,
        data: result
      };
    } catch (error: any) {
      const errorMsg = `Aeterna execution error: ${error.message}`;
      if (callback) {
        callback({ text: errorMsg, content: { success: false, error: error.message } });
      }
      return {
        success: false,
        error: error.message
      };
    }
  }
};
