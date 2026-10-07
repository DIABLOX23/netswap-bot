# ⚡ NetSwap Protocol: Autonomous Zero-Revert Execution Router & Mempool Telemetry Engine

[![Network: Base Mainnet](https://img.shields.io/badge/Network-Base%20Mainnet%20(8453)-blue.svg)](https://base.org)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-yellow.svg)](https://python.org)
[![Execution: Zero--Revert Pre--Simulation](https://img.shields.io/badge/Pre--Simulation-Zero--Revert%20Guaranteed-emerald.svg)](https://netswap.vercel.app)
[![API Gateway](https://img.shields.io/badge/API%20Gateway-Vercel%20Edge%20REST-purple.svg)](https://netswap.vercel.app/docs)
[![License: MIT](https://img.shields.io/badge/License-MIT-gray.svg)](LICENSE)

**NetSwap** is an open-source, high-throughput liquidity execution router and Machine-to-Machine (M2M) mempool telemetry platform purpose-built for **Base Mainnet (Coinbase L2)**.

In volatile decentralized markets, algorithmic bots and traders lose thousands of dollars daily to **reverted transactions (`status == 0`)** caused by stale AMM prices, low default slippage tolerances, and router congestion across Uniswap V3 and Aerodrome. NetSwap eliminates transaction reverts through local pre-simulation and dynamic slippage routing, while providing real-time REST telemetry streams for automated bot builders.

---

## 🏛️ Ecosystem Architecture

```
                             [ Base L2 Mempool / RPC ]
                                        │
                    ┌───────────────────┴───────────────────┐
                    ▼                                       ▼
        [ Reverted TX Interceptor ]              [ Live Whale Accumulation ]
        (Detects status == 0 swaps)              (Tracks $50k+ AMM entries)
                    │                                       │
                    ▼                                       ▼
      [ Dynamic Slippage Resolver ]            [ Token-Gated M2M Gateway ]
      (Pre-simulates against pools)            (/api/whales & /api/spreads)
                    │                                       │
                    ▼                                       ▼
       [ NetSwap Batch Router ]                 [ Autonomous Bot Desks ]
    (Zero-revert onchain settlement)            (5-line drop-in Python SDK)
```

---

## 🚀 Key Features

### 1. 🚑 Failed Trade Interceptor (`scripts/failed_trade_interceptor.py`)
Autonomous block scanner monitoring Base Mainnet for reverted swap transactions:
* Identifies target tokens and failed router contracts (Uniswap V3 SwapRouter02, Universal Router, Aerodrome Slipstream, Odos).
* Calculates exact burned gas losses in ETH and USD.
* Generates 1-click zero-revert rescue routes with dynamic slippage pre-simulation.

```bash
# Run real-time block scanner
python scripts/failed_trade_interceptor.py --blocks 10

# Generate demonstration rescue pack
python scripts/failed_trade_interceptor.py --demo
```

### 2. 📡 Tiered REST API Gateway ([Docs](https://netswap.vercel.app/docs))
Token-gated, machine-to-machine telemetry streams hosted serverless on Vercel Edge:
* **`/api/whales`**: Real-time smart-money buy accumulation ($50k–$500k+ entries) across Base AMMs.
* **`/api/spreads`**: Sub-second cross-DEX flash-arbitrage spreads between Aerodrome and Uniswap V3.
* **Access Tiers**:
  * **Tier 1 (Scout):** Holds $\ge 100,000\text{ } \$NETSWAP$ — 50 calls/day.
  * **Tier 2 (Whale Hunter):** Holds $\ge 500,000\text{ } \$NETSWAP$ — 1,000 calls/day + live spreads.
  * **Tier 3 (Institutional):** Holds $\ge 1,000,000\text{ } \$NETSWAP$ — Unlimited calls, 0s latency mempool cluster.

### 3. 🤖 High-Speed Telegram Execution Engine (`bot.py`)
Production-grade Telegram interface with native Base DEX execution:
* **Zero-Revert Router:** Pre-simulates transactions locally to prevent burnt gas fees.
* **Anti-MEV Batching:** Protects swaps against public mempool sandwich bots.
* **1-Click Deep Links:** Instant swap cards via `/start buy_[TOKEN]` and `/start rescue_[TOKEN]`.
* **Institutional Audit Card:** Real-time node telemetry and ecosystem metrics via `/status`.

---

## ⚡ 5-Line Python SDK Integration

Any algorithmic bot or Python script can ingest NetSwap telemetry in seconds:

```python
import requests

# Header: Server wallet holding your $NETSWAP access collateral
HEADERS = {"X-Wallet-Address": "0xYourServerWalletAddress"}

# Ingest live Base whale telemetry
response = requests.get("https://netswap.vercel.app/api/whales", headers=HEADERS).json()

if response.get("status") == "success":
    print(f"🔥 [{response['tier']}] Live Whale Entry:", response["live_whale_entries"][0])
else:
    print("🔒 Paywall:", response.get("message"), "Deficit:", response.get("deficit"))
```

---

## 🛠️ Quickstart & Local Installation

### Prerequisites
* Python 3.10 or higher
* Git

### Installation
```bash
# Clone the repository
git clone https://github.com/DIABLOX23/netswap-bot.git
cd netswap-bot

# Install dependencies
pip install -r requirements.txt
```

### Running the Trade Interceptor
```bash
python scripts/failed_trade_interceptor.py --demo
```

### Running the Telegram Bot Locally
```bash
# Set your Telegram Bot token
export TELEGRAM_BOT_TOKEN="your_botfather_token_here"

# Start the bot
python bot.py
```

---

## 🔗 Official Protocol Links

* 🌐 **Web Terminal:** [netswap.vercel.app](https://netswap.vercel.app)
* 📡 **Interactive API Documentation:** [netswap.vercel.app/docs](https://netswap.vercel.app/docs)
* 🔓 **Leaked Alpha Stream:** [netswap.vercel.app/alpha-leak](https://netswap.vercel.app/alpha-leak)
* 🤖 **Telegram Execution Bot:** [@NetSwapBaseBot](https://t.me/NetSwapBaseBot)
* 📊 **DexScreener Chart:** [0xb5be...44d6](https://dexscreener.com/base/0xb5be5c5559f2864e2504a0e0545169cd1edd3a8d12795b78e916d7220a4c44d6)
* 📍 **Base Mainnet Contract:** `0xf974469D1C72F198Cb43426509119AfC653abB07`

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).
