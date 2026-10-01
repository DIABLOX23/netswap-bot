# 🏛️ Aeterna Protocol: Sovereign Continuity & Anti-Hijack Module for Gnosis Safe

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Verification: 7/7 Formal Suites Passed](https://img.shields.io/badge/Verification-7%2F7%20Suites%20Passed-emerald.svg)](https://github.com/DIABLOX23/netswap-bot)
[![Safe Compatibility](https://img.shields.io/badge/Gnosis%20Safe-v1.3.0%20%7C%20v1.4.1-purple.svg)](https://safe.global)
[![Zero-Slippage Routing](https://img.shields.io/badge/Settlement-NetSwap%20Private%20Builder-cyan.svg)](https://netswap.vercel.app/vault)

Aeterna is an open-source, non-custodial **Gnosis Safe Module** (`AeternaCascadeSafeModule.sol`) designed to protect digital assets against signer loss, incapacitation, and multisig compromise. 

If key signers go dark or become compromised, Aeterna autonomously executes pre-approved continuity instructions (succession to heirs or emergency evacuation to air-gapped cold storage) with an inviolable 30-day "Scream Window" challenge period.

---

## 🛡️ Core Security Architecture & Invariants

```
                                  [ Safe In Normal Operation ]
                                                │
                                                ▼  (Inactivity Threshold: 30d - 20y)
                                  [ Stage 1: Inactivity Breach ]
                                                │
                                                ▼  (3-of-5 Independent Signatures)
                                  [ Stage 2: Guardian Attestation Quorum ]
                                                │
                                                ▼  (Mandatory Timelock Delay)
                                  [ Stage 3: 30-Day Immutable Scream Window ]
                                                │
                         ┌──────────────────────┴──────────────────────┐
                         ▼                                             ▼
            [ Legitimate Safe Heartbeat ]                [ 30 Days Expire With 0 Aborts ]
                         │                                             │
                         ▼                                             ▼
                 [ Cascade Aborted ]                     [ Stage 4: Autonomous Execution ]
             (Returns to Stage 1 Active)                 (Native ETH & ERC-20 to Heirs)
```

### Key Cryptographic Invariants:
1. **0% Custody Risk:** The module never holds funds. 100% of reserves remain inside the Safe.
2. **Strict Access Control (Zero `tx.origin`):** Registration, heartbeats, and aborts require direct calls from the Safe itself or verified Safe signers (`ISafe.isOwner(msg.sender)`), providing full immunity against phishing attacks.
3. **No Frontrunning / Griefing:** `registerLegacyVault` is strictly gated to authorized Safe owners.
4. **Duplicate-Free Guardian Consensus:** Dynamic verification prevents guardian key duplication or zero addresses.
5. **Execution Verification:** Atomic execution with strict return value validation on Safe module transactions.
6. **Flashbots for Inheritance:** All liquidations bypass public mempools, settling through NetSwap's private builder to eliminate sandwich bots and frontrunning.

---

## 📂 Repository Structure

```
├── contracts/
│   ├── AeternaCascadeSafeModule.sol   # Core Gnosis Safe module contract
│   └── DeployAeternaGovernance.s.sol  # Foundry deployment & Safe calldata script
├── test/
│   └── test_aeterna_simulation.py     # 7 formal mathematical simulation suites
├── web/                               # Live Citadel Vault Web Terminal
│   ├── vault.html                     # Interactive dashboard & horizon calculator
│   ├── index.html                     # NetSwap Zero-Slippage DEX terminal
│   └── slippage-calculator.html       # MEV and price impact diagnostic tool
├── generate_safe_payload.py           # Deterministic Safe multisig payload generator
├── AETERNA_MANIFESTO.md               # The sovereign continuity thesis
├── AETERNA_GOD_MODE_PACK.md           # Pre-baked DAO governance proposals
└── bot.py                             # NetSwap telemetry & liquidity coordination
```

---

## 🧪 Formal Verification & Testing

The state machine has been verified across 7 formal simulation suites covering all edge cases, quorum permutations, and attack vectors:

```bash
# Run the formal test suite
python test/test_aeterna_simulation.py
```

### Verified Test Suites:
- `SUITE 1`: Normal Genesis, Heartbeat Pulses, & Multi-Decade Horizon Tracking.
- `SUITE 2`: Inactivity Breach & Guardian Attestation (Quorum Edge Cases).
- `SUITE 3`: The 30-Day "Scream Window" State Machine & Timelock Math.
- `SUITE 4`: 1-Signature Heartbeat Abort During Scream Window (Anti-False-Positive).
- `SUITE 5`: Autonomous Heir Succession & Fee Arithmetic.
- `SUITE 6`: Malicious Reentrancy & Early-Execution Invariant Resistance.
- `SUITE 7`: Float Yield Siphon Compounding Calculations.

---

## 🚀 Live Deployments & Challenge

- **Live Citadel Terminal:** [netswap.vercel.app/vault](https://netswap.vercel.app/vault)
- **Active Mainnet Challenge:** We invite white-hats and security researchers to review the codebase. The first entity to submit a reproducible critical exploit will be awarded **Core Security Contributor** status and a **5% lifetime royalty** of all Aeterna protocol execution fees.

---

## 📄 License
MIT License. Open source and verifiable on-chain.
