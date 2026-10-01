"""
AETERNA & NETSWAP - AUTONOMOUS TARGET HUNTER & STRIKE DOSSIER GENERATOR
======================================================================
Automates 100% of the research, intelligence gathering, vulnerability audit,
and outreach payload generation for Base tokens.

Filters for REAL crypto & memecoin teams with direct Telegram/X contact points.
"""

import urllib.request
import urllib.parse
import json
import os
import sys

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

SEARCH_KEYWORDS = [
    "clanker", "virtual", "brett", "toshi", "degen", 
    "keycat", "higher", "mfer", "normie", "doginme", "ski", 
    "luna", "crash", "chomp", "keyboardcat", "anon", "based",
    "farcaster", "miggles", "brian", "aero"
]

TREASURY_ADDRESS = "0xcc12fD53A0ba26f42FEA6fF8b285a77aa54B170d"
BOT_USERNAME = "@NetSwapBaseBot"

# Filter out wrapped stocks and stablecoins
EXCLUDED_SYMBOLS = {"GOOGLc", "METAc", "NVDAc", "AAPLc", "AMZNc", "MSFTc", "TSLAc", "USDC", "USDT", "DAI", "WETH", "cbETH", "wstETH"}

def fetch_search_pairs(keyword):
    url = f"https://api.dexscreener.com/latest/dex/search?q={urllib.parse.quote(keyword)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("pairs", [])
    except Exception:
        return []

def hunt_targets(min_vol=15000, min_fdv=50000):
    print(f"[*] Initiating Deep Target Hunt across Base ecosystem...")
    seen_addresses = set()
    targets = []

    for kw in SEARCH_KEYWORDS:
        pairs = fetch_search_pairs(kw)
        for p in pairs:
            if p.get("chainId") != "base":
                continue
            
            base_t = p.get("baseToken", {})
            symbol = base_t.get("symbol", "")
            token_addr = base_t.get("address", "").lower()
            
            if not token_addr or token_addr in seen_addresses:
                continue
            
            if symbol in EXCLUDED_SYMBOLS or symbol.endswith("c") and len(symbol) > 4:
                continue
            
            vol_24h = p.get("volume", {}).get("h24", 0) or 0
            fdv = p.get("fdv", 0) or 0
            liquidity = p.get("liquidity", {}).get("usd", 0) or 0

            if vol_24h < min_vol or fdv < min_fdv:
                continue

            info = p.get("info", {})
            socials = info.get("socials", []) if info else []
            tg = [s["url"] for s in socials if s.get("type") == "telegram"]
            tw = [s["url"] for s in socials if s.get("type") == "twitter"]

            # Must have at least Telegram or Twitter
            if not tg and not tw:
                continue

            seen_addresses.add(token_addr)

            equity_1pct_val = fdv * 0.01

            targets.append({
                "name": base_t.get("name"),
                "symbol": symbol,
                "address": base_t.get("address"),
                "pairAddress": p.get("pairAddress"),
                "priceUsd": p.get("priceUsd"),
                "vol24h": vol_24h,
                "fdv": fdv,
                "liquidity": liquidity,
                "telegram": tg[0] if tg else None,
                "twitter": tw[0] if tw else None,
                "equity_1pct_usd": equity_1pct_val,
                "dexUrl": p.get("url")
            })

    # Prioritize targets with active Telegram first, then by 24h volume
    targets.sort(key=lambda x: (1 if x["telegram"] else 0, x["vol24h"]), reverse=True)
    return targets

def generate_pitch(target):
    name = target["name"]
    symbol = target["symbol"]
    vol = f"${target['vol24h']:,.0f}"
    fdv = f"${target['fdv']:,.0f}"
    equity = f"${target['equity_1pct_usd']:,.0f}"
    
    pitch = f"""Hey {symbol} team, saw {symbol} doing {vol} 24h volume at {fdv} FDV on Base.

Your biggest bottleneck to 10Xing this chart is single-signer dev wallet FUD. Traders are terrified of sudden LP pulls or dev dumping.

We offer an institutional Anti-Rug Certification via Aeterna Protocol & NetSwap:
1. We migrate your treasury / dev reserve into a 2-of-3 Gnosis Safe multisig with a 30-day Timelocked Scream Window.
2. Verified Safe Badge + Buy Bot banner broadcast directly to our institutional trader flow on {BOT_USERNAME}.
3. 100% async. Zero Zoom calls. We deliver the exact Safe execution calldata JSON in 15 minutes.

Terms: $1,000 USDC setup + 1% token supply ({equity} equity value locked in protocol treasury).

If you want your chart bulletproofed against rug FUD before the next run, reply 'PARTNER' and we'll send the calldata payload.
"""
    return pitch.strip()

def main():
    targets = hunt_targets()
    print(f"[+] Hunt completed! Found {len(targets)} qualified high-conviction targets on Base.\n")

    output_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(output_dir)

    # Save Markdown Dossier
    md_path = os.path.join(project_root, "STRIKE_LEADS.md")
    json_path = os.path.join(project_root, "leads_strike_dossier.json")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(targets, f, indent=2)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 🎯 ANTI-RUG EQUITY STRIKE - LIVE TARGET DOSSIER\n\n")
        f.write(f"**Total High-Conviction Base Targets:** {len(targets)}\n")
        f.write(f"**Treasury Deposit Address:** `{TREASURY_ADDRESS}`\n\n")
        f.write("---\n\n")

        for idx, t in enumerate(targets, 1):
            pitch = generate_pitch(t)
            f.write(f"## {idx}. [{t['symbol']}] {t['name']}\n")
            f.write(f"- **Token Address:** `{t['address']}`\n")
            f.write(f"- **24h Volume:** ${t['vol24h']:,.0f}\n")
            f.write(f"- **FDV:** ${t['fdv']:,.0f} | **1% Equity Value:** ${t['equity_1pct_usd']:,.0f}\n")
            f.write(f"- **Telegram:** {t['telegram'] or 'N/A'}\n")
            f.write(f"- **Twitter/X:** {t['twitter'] or 'N/A'}\n")
            f.write(f"- **DexScreener:** [{t['symbol']} Chart]({t['dexUrl']})\n\n")
            f.write("### 📤 Direct Strike Copy (Copy & Paste to TG Admin / X DM):\n")
            f.write("```text\n")
            f.write(pitch + "\n")
            f.write("```\n\n")
            f.write("---\n\n")

    print(f"[✓] Live dossier compiled successfully:")
    print(f"    - Markdown: {md_path}")
    print(f"    - JSON:     {json_path}")
    print("\n" + "="*85)
    print(f"{'#':<3} {'SYMBOL':<10} {'VOL 24H':<14} {'FDV':<14} {'1% EQUITY':<12} {'TELEGRAM / X'}")
    print("="*85)
    for i, t in enumerate(targets[:10], 1):
        contact = t['telegram'] or t['twitter'] or "N/A"
        print(f"{i:<3} {t['symbol']:<10} ${t['vol24h']:>10,.0f}   ${t['fdv']:>10,.0f}   ${t['equity_1pct_usd']:>8,.0f}   {contact}")
    print("="*85)

if __name__ == "__main__":
    main()
