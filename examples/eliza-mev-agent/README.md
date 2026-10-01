# 🛡️ MEV-Protected AI Trading Agent (Eliza Edition)
### Built with the ai16z Eliza Framework & [@netswap_protocol/agent-wallet](https://www.npmjs.com/package/@netswap_protocol/agent-wallet)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![NPM](https://img.shields.io/badge/npm-@netswap__protocol/agent--wallet-green.svg)](https://www.npmjs.com/package/@netswap_protocol/agent-wallet)
[![Base Mainnet](https://img.shields.io/badge/Network-Base%20Mainnet-blue)](https://base.org)

Standard open-source trading agents built with raw `viem` or `ethers.js` bleed 1% to 3% on every trade to predatory MEV sandwich bots in the public mempool.

This repository is a **1-click, drop-in replacement** for Eliza trading bots. It replaces vulnerable public DEX swaps with **Aeterna Intent-Based Solver Netting**, delivering:
- **0% Sandwich Slippage:** Swaps are matched peer-to-peer or routed privately.
- **Pre-Execution Simulation:** No wasted gas on reverted transactions.
- **3-Line Plug & Play:** Drop into your existing character without refactoring your codebase.

---

## ⚡ 1-Click Quickstart

### 1. Clone & Install
```bash
git clone https://github.com/DIABLOX23/netswap-bot.git
cd netswap-bot/examples/eliza-mev-agent
npm install
```

### 2. Configure Environment
Create a `.env` file:
```env
AGENT_PRIVATE_KEY=0x_your_private_key_here
BASE_RPC=https://mainnet.base.org
```

### 3. Run the Protected Agent
```bash
npm start
```

---

## 🤖 Replacing Raw Swaps in Your Own Agent

If you already have an existing agent, replace your swap execution block with this:

```typescript
// ❌ BEFORE (Vulnerable to Sandwiches):
// const tx = await uniswapRouter.exactInputSingle(...);

// ✅ AFTER (100% MEV-Shielded):
import { AgentWallet } from '@netswap_protocol/agent-wallet';

const agent = new AgentWallet({ privateKey: process.env.AGENT_KEY });
const result = await agent.swap({
  tokenIn: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', // USDC
  tokenOut: '0x4200000000000000000000000000000000000006', // WETH
  amount: '100'
});

console.log(`Protected Tx: https://basescan.org/tx/${result.txHash}`);
console.log(`MEV Saved: ${result.mevSavedUsd}`);
```

---

## 📜 License
MIT - Free for all autonomous agents.
