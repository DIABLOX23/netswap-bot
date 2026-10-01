/**
 * 🛡️ ELIZA MEV-PROTECTED AUTONOMOUS TRADING AGENT
 * ===============================================
 * Powered by @netswap_protocol/agent-wallet
 * 
 * 1-click execution:
 *   node index.js
 */

const { AgentWallet } = require('@netswap_protocol/agent-wallet');
require('dotenv').config();

async function runAgent() {
  const privateKey = process.env.AGENT_PRIVATE_KEY || '0x0000000000000000000000000000000000000000000000000000000000000001';
  
  console.log('===========================================================');
  console.log('🤖 INITIALIZING MEV-PROTECTED ELIZA AGENT (BASE MAINNET)');
  console.log('===========================================================');

  const agent = new AgentWallet({
    privateKey,
    network: 'base'
  });

  console.log(`Agent Address: ${agent.address}`);
  console.log(`Protected Routing: ENABLED (NetSwap Solver + Private Relays)`);
  console.log('-----------------------------------------------------------');

  // Example: Query Balances
  console.log('Auditing portfolio balances...');
  const balances = await agent.getBalances([
    '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913' // USDC on Base
  ]);

  balances.forEach(b => {
    console.log(`• ${b.symbol}: ${b.balance}`);
  });

  console.log('-----------------------------------------------------------');
  console.log('Ready to receive autonomous trading signals.');
  console.log('To execute a protected swap:');
  console.log('  await agent.swap({ tokenIn: USDC, tokenOut: WETH, amount: "100" });');
  console.log('===========================================================');
}

runAgent().catch(console.error);
