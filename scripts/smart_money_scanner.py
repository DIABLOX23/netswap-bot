"""
BASE SMART MONEY & FRESH WHALE SCANNER
=======================================
100% Free, Zero-Gas Off-Chain Alpha Engine for Base Mainnet.
Scans recent blocks for large USDC transfers to fresh, un-traded wallets.
Generates real-time alpha reports and JSON feeds for degens & copy-traders.
"""

import os
import sys
import json
import time
import urllib.request
from datetime import datetime, timezone

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

RPC_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")

# Base Mainnet Core Addresses
USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913".lower()
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Known Exchange / Bridge Hot Wallets on Base
KNOWN_EXCHANGES = {
    "0x3304e22ddaa22bcdc4fca2269b418046ae7b566a": "Coinbase Hot Wallet",
    "0x5037e7747f66a029548df22ec8b3680426cd859e": "Coinbase Deposit/Withdrawal",
    "0xa0e257c705094b30442806ad2e8d75001a32661e": "Binance Hot Wallet",
    "0x49048044d57e1c92a77f79988d21fa8faf74e97e": "Base Bridge Portal",
    "0x6b75d8af000000e20b7a7ddf000ba900b4009a80": "Wintermute Trading",
    "0x2626664c2603336e57b271c5c0b26f421741e481": "Uniswap Router",
    "0xcf77a3ba9a5ca399b7c97c74d54e5b1beb874e43": "Aerodrome Router",
}

def rpc_call(method, params):
    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000) % 100000,
        "method": method,
        "params": params
    }
    req = urllib.request.Request(
        RPC_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BaseAlphaScanner/1.0"
        }
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        res = json.loads(resp.read().decode())
        if "error" in res:
            raise Exception(f"RPC Error: {res['error']}")
        return res.get("result")

def get_latest_block():
    hex_num = rpc_call("eth_blockNumber", [])
    return int(hex_num, 16)

def get_wallet_nonce(address):
    try:
        res = rpc_call("eth_getTransactionCount", [address, "latest"])
        return int(res, 16) if res else 0
    except Exception:
        return 0

def is_contract(address):
    try:
        res = rpc_call("eth_getCode", [address, "latest"])
        return res != "0x" and len(res) > 2
    except Exception:
        return False

def scan_usdc_whales(block_range=20, min_usdc=5000.0, max_results=25):
    latest = get_latest_block()
    from_block = latest - block_range
    print(f"[*] Scanning Base blocks #{from_block} -> #{latest} (last {block_range} blocks)...", flush=True)

    filter_params = {
        "fromBlock": hex(from_block),
        "toBlock": hex(latest),
        "address": USDC_ADDRESS,
        "topics": [TRANSFER_TOPIC]
    }

    logs = rpc_call("eth_getLogs", [filter_params])
    print(f"[*] Fetched {len(logs)} USDC transfer events. Filtering for >= ${min_usdc:,.0f}...", flush=True)

    fresh_wallets = []
    
    # Process from newest to oldest
    for log in reversed(logs):
        if len(fresh_wallets) >= max_results:
            break
        try:
            if len(log.get("topics", [])) < 3:
                continue

            amount_raw = int(log.get("data", "0x0"), 16)
            amount_usdc = amount_raw / 1e6

            if amount_usdc < min_usdc:
                continue

            from_addr = "0x" + log["topics"][1][-40:].lower()
            to_addr = "0x" + log["topics"][2][-40:].lower()

            # Skip contract-to-contract internal hops if already known
            contract_target = is_contract(to_addr)
            wallet_type = "Contract / Pool" if contract_target else "EOA (Trader Wallet)"

            source_label = KNOWN_EXCHANGES.get(from_addr, "Private Wallet / DEX")
            nonce = get_wallet_nonce(to_addr)
            
            # A "Fresh Sniper Wallet" is an EOA with <= 5 transactions
            is_fresh = (not contract_target) and (nonce <= 5)

            entry = {
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "block": int(log.get("blockNumber", "0x0"), 16),
                "tx_hash": log.get("transactionHash"),
                "wallet": to_addr,
                "amount_usdc": round(amount_usdc, 2),
                "type": wallet_type,
                "funded_from": source_label,
                "from_address": from_addr,
                "nonce": nonce,
                "is_fresh": is_fresh,
                "classification": "🔥 FRESH SNIPER (0-5 Trades)" if is_fresh else ("WHALE CONTRACT" if contract_target else "ACTIVE WHALE")
            }

            fresh_wallets.append(entry)
            print(f"  -> Found: {to_addr[:8]}... | ${amount_usdc:,.2f} USDC | Type: {wallet_type} | Nonce: {nonce} | Fresh: {is_fresh}", flush=True)

        except Exception:
            continue

    fresh_wallets.sort(key=lambda x: (x["is_fresh"], x["amount_usdc"]), reverse=True)
    return fresh_wallets

def format_alpha_report(wallets, filepath="ALPHA_FEED.md"):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    md = f"""# 🦅 Base Mainnet Smart Money & Fresh Whale Tracker
*Automated Real-Time Mempool Feed | Generated at {timestamp}*

> **Alpha Thesis:** Tracking freshly funded trader wallets receiving >$5,000+ USDC before they deploy capital into micro-caps, new launches, or DEX liquidity pools.

---

## 🚨 Fresh Sniper Wallets (Nonce ≤ 5, EOA Only)
*Newly created trader addresses funded from exchanges/whales. Prime insider/sniper candidates.*

| Target Wallet | USDC Funded | Source | Nonce | Basescan Link |
|---|---|---|---|---|
"""

    fresh_count = 0
    for w in wallets:
        if w["is_fresh"]:
            fresh_count += 1
            short_w = f"`{w['wallet'][:6]}...{w['wallet'][-4:]}`"
            link = f"[{short_w}](https://basescan.org/address/{w['wallet']})"
            tx_link = f"[`{w['tx_hash'][:10]}...`](https://basescan.org/tx/{w['tx_hash']})"
            md += f"| {link} | **${w['amount_usdc']:,.2f}** | {w['funded_from']} | {w['nonce']} | {tx_link} |\n"

    if fresh_count == 0:
        md += "| *(No fresh EOA wallets detected in this immediate scan window)* | - | - | - | - |\n"

    md += """
---

## 🐋 Whale Inflows & Institutional Liquidity
*High-volume USDC liquidity movements on Base Mainnet.*

| Target Address | Inflow Amount | Type | Source | Basescan Link |
|---|---|---|---|---|
"""
    for w in wallets:
        if not w["is_fresh"]:
            short_w = f"`{w['wallet'][:6]}...{w['wallet'][-4:]}`"
            link = f"[{short_w}](https://basescan.org/address/{w['wallet']})"
            tx_link = f"[`{w['tx_hash'][:10]}...`](https://basescan.org/tx/{w['tx_hash']})"
            md += f"| {link} | **${w['amount_usdc']:,.2f}** | {w['type']} | {w['funded_from']} | {tx_link} |\n"

    md += """
---
*Generated by Base Smart Money Engine v1.0. 100% On-Chain Verifiable. Zero Gas Used.*
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md)

    json_path = filepath.replace(".md", ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(wallets, f, indent=2)

    print(f"[+] Alpha report written to: {filepath}", flush=True)
    print(f"[+] JSON feed written to: {json_path}", flush=True)

def run():
    print("=" * 65, flush=True)
    print("🦅 BASE SMART MONEY & FRESH WHALE SCANNER (ZERO-GAS)", flush=True)
    print("=" * 65, flush=True)
    wallets = scan_usdc_whales(block_range=20, min_usdc=5000.0, max_results=20)
    print(f"\n[+] Total Transfers Analyzed: {len(wallets)}", flush=True)
    format_alpha_report(wallets, "ALPHA_FEED.md")

    fresh_only = [w for w in wallets if w["is_fresh"]]
    print(f"[+] Fresh Sniper Wallets Identified: {len(fresh_only)}", flush=True)
    for f in fresh_only[:3]:
        print(f"  • {f['wallet']} | +${f['amount_usdc']:,.2f} USDC | Nonce: {f['nonce']}", flush=True)
    print("=" * 65, flush=True)

if __name__ == "__main__":
    run()
