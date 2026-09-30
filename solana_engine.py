import os
import json
import time
import base64
import requests
import sqlite3
import base58
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solders.system_program import TransferParams, transfer
from solders.message import MessageV0
from solders.hash import Hash

# ==============================================================================
# CONFIGURATION & OPERATOR SETTINGS
# ==============================================================================
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BOT_DIR, "netswap_bot.db")
OPERATOR_FILE = os.path.join(BOT_DIR, "operator_solana.json")

# Public reliable Solana RPC endpoints
SOLANA_RPCS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-mainnet.rpc.extrnode.com"
]
SOLANA_RPC = SOLANA_RPCS[0]

# High-performance persistent connection pooling
solana_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=15, pool_maxsize=30, max_retries=2)
solana_session.mount("https://", adapter)
solana_session.mount("http://", adapter)

WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_SOL_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Default platform fee: 85 basis points = 0.85%
PLATFORM_FEE_BPS = 85

OPERATOR_SOL_PUBKEY = "8ahU9484JdbCAcBmV8w3NgPt51YPt2SKXyC2rx3cTc3X"  # Metamask SOL Recipient


# ==============================================================================
# DATABASE SCHEMA FOR SOLANA
# ==============================================================================
def init_solana_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solana_wallets (
            user_id INTEGER PRIMARY KEY,
            pubkey TEXT UNIQUE,
            secret_key_b58 TEXT,
            created_at INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solana_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            input_mint TEXT,
            output_mint TEXT,
            symbol TEXT,
            trade_type TEXT,
            amount_in REAL,
            amount_out REAL,
            tx_signature TEXT,
            fee_amount REAL,
            fee_symbol TEXT,
            timestamp INTEGER
        )
    """)
    conn.commit()
    conn.close()

init_solana_db()

# ==============================================================================
# USER WALLET MANAGEMENT
# ==============================================================================
def get_or_create_solana_wallet(user_id):
    """Retrieve existing Solana wallet for user or generate a fresh keypair."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT pubkey, secret_key_b58 FROM solana_wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        conn.close()
        return row[0], row[1]
    
    # Generate fresh Solana keypair
    kp = Keypair()
    pubkey = str(kp.pubkey())
    secret_b58 = base58.b58encode(bytes(kp)).decode("ascii")
    
    cursor.execute("""
        INSERT INTO solana_wallets (user_id, pubkey, secret_key_b58, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, pubkey, secret_b58, int(time.time())))
    conn.commit()
    conn.close()
    return pubkey, secret_b58

# ==============================================================================
# SOLANA ON-CHAIN RPC HELPERS
# ==============================================================================
def solana_rpc(method, params):
    """Execute raw JSON-RPC query across fallback endpoints."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    for rpc in SOLANA_RPCS:
        try:
            res = solana_session.post(rpc, json=payload, timeout=6)
            if res.status_code == 200:
                data = res.json()
                if "result" in data:
                    return data["result"]
                elif "error" in data:
                    return {"error": data["error"]}
        except Exception:
            continue
    return None

def get_sol_balance(pubkey):
    """Return SOL balance as a float."""
    res = solana_rpc("getBalance", [pubkey])
    if res and "value" in res:
        return res["value"] / 1_000_000_000.0
    return 0.0

def get_spl_token_balances(pubkey):
    """Return list of tokens owned by pubkey with balances."""
    res = solana_rpc("getTokenAccountsByOwner", [
        pubkey,
        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
        {"encoding": "jsonParsed"}
    ])
    balances = []
    if res and "value" in res:
        for item in res["value"]:
            try:
                info = item["account"]["data"]["parsed"]["info"]
                mint = info["mint"]
                token_amount = info["tokenAmount"]
                ui_amount = token_amount.get("uiAmount", 0.0)
                if ui_amount and ui_amount > 0:
                    balances.append({
                        "mint": mint,
                        "amount": ui_amount,
                        "decimals": token_amount.get("decimals", 0)
                    })
            except Exception:
                continue
    return balances

# ==============================================================================
# TOKEN SEARCH & METADATA VIA DEXSCREENER
# ==============================================================================
def fetch_solana_token(query):
    """Look up a token on Solana by mint address or search term."""
    clean_q = query.strip()
    try:
        # If it looks like a base58 address
        if len(clean_q) >= 32 and not " " in clean_q:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{clean_q}"
        else:
            url = f"https://api.dexscreener.com/latest/dex/search?q={urllib_quote(clean_q)}"
        
        res = solana_session.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            pairs = data.get("pairs", [])
            # Filter for Solana pairs
            sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
            if sol_pairs:
                # Pick the highest liquidity pair
                sol_pairs.sort(key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0), reverse=True)
                top = sol_pairs[0]
                base_token = top.get("baseToken", {})
                return {
                    "valid": True,
                    "mint": base_token.get("address"),
                    "name": base_token.get("name", "Unknown"),
                    "symbol": base_token.get("symbol", "UNKNOWN"),
                    "price_usd": float(top.get("priceUsd", 0) or 0),
                    "price_native": float(top.get("priceNative", 0) or 0),
                    "fdv": float(top.get("fdv", 0) or 0),
                    "liquidity_usd": float(top.get("liquidity", {}).get("usd", 0) or 0),
                    "volume_24h": float(top.get("volume", {}).get("h24", 0) or 0),
                    "change_24h": float(top.get("priceChange", {}).get("h24", 0) or 0),
                    "dex": top.get("dexId", "raydium").capitalize(),
                    "pair_address": top.get("pairAddress")
                }
    except Exception as e:
        return {"valid": False, "error": str(e)}
    
    return {"valid": False, "error": "Token not found on Solana"}

def urllib_quote(s):
    import urllib.parse
    return urllib.parse.quote(s)

def get_hot_solana_tokens():
    """Curated list of high-velocity Solana trading targets."""
    return [
        {"symbol": "BONK", "name": "Bonk", "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"},
        {"symbol": "WIF", "name": "dogwifhat", "mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"},
        {"symbol": "POPCAT", "name": "Popcat", "mint": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"},
        {"symbol": "FARTCOIN", "name": "Fartcoin", "mint": "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"},
        {"symbol": "JUP", "name": "Jupiter", "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"},
    ]

# ==============================================================================
# JUPITER ROUTING & PLATFORM TOLL SWAPS
# ==============================================================================
def get_jupiter_quote(input_mint, output_mint, amount_lamports, slippage_bps=100, platform_fee_bps=PLATFORM_FEE_BPS):
    """
    Query Jupiter Swap API v1 with automatic platform fee deduction.
    Platform fee lands atomically into Operator's Solana Wallet.
    """
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount_lamports),
        "slippageBps": slippage_bps,
        "platformFeeBps": platform_fee_bps
    }
    try:
        res = solana_session.get("https://api.jup.ag/swap/v1/quote", params=params, timeout=7)
        if res.status_code == 200:
            return {"success": True, "quote": res.json()}
        else:
            return {"success": False, "error": res.text}
    except Exception as e:
        return {"success": False, "error": str(e)}

def build_jupiter_swap_transaction(user_pubkey, quote_response, fee_account=OPERATOR_SOL_PUBKEY):
    """
    Build Jupiter Versioned Transaction with platform fee destination.
    """
    payload = {
        "userPublicKey": user_pubkey,
        "quoteResponse": quote_response,
        "feeAccount": fee_account,
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": "auto"
    }
    try:
        res = solana_session.post("https://api.jup.ag/swap/v1/swap", json=payload, timeout=8)
        if res.status_code == 200:
            data = res.json()
            return {"success": True, "swapTransaction": data["swapTransaction"]}
        else:
            return {"success": False, "error": res.text}
    except Exception as e:
        return {"success": False, "error": str(e)}

def execute_solana_swap(user_secret_b58, swap_transaction_b64):
    """
    Sign Jupiter swap transaction and broadcast to Solana Mainnet.
    Returns transaction signature.
    """
    try:
        secret_bytes = base58.b58decode(user_secret_b58)
        kp = Keypair.from_bytes(secret_bytes)
        
        raw_tx = base64.b64decode(swap_transaction_b64)
        tx = VersionedTransaction.from_bytes(raw_tx)
        
        # Sign the message
        sig = kp.sign_message(bytes(tx.message))
        signed_tx = VersionedTransaction.populate(tx.message, [sig])
        signed_b64 = base64.b64encode(bytes(signed_tx)).decode("ascii")
        
        # Broadcast via Solana RPC
        res = solana_rpc("sendTransaction", [
            signed_b64,
            {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"}
        ])
        
        if res and isinstance(res, str):
            return {
                "success": True,
                "tx_signature": res,
                "solscan_url": f"https://solscan.io/tx/{res}"
            }
        elif res and isinstance(res, dict) and "error" in res:
            return {"success": False, "error": str(res["error"])}
        else:
            return {"success": False, "error": f"Broadcast failed: {res}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_recent_blockhash():
    """Fetch latest blockhash for transaction building."""
    res = solana_rpc("getLatestBlockhash", [{"commitment": "confirmed"}])
    if res and "value" in res:
        return res["value"]["blockhash"]
    return None

def withdraw_sol(user_secret_b58, to_pubkey_str, amount_sol):
    """
    Transfer native SOL from user's bot wallet to external wallet.
    Leaves 0.0005 SOL for network fees.
    """
    try:
        secret_bytes = base58.b58decode(user_secret_b58)
        sender_kp = Keypair.from_bytes(secret_bytes)
        target_pubkey = Pubkey.from_string(to_pubkey_str)
        
        lamports = int(amount_sol * 1_000_000_000)
        if lamports <= 5000:
            return {"success": False, "error": "Amount too small (below network fee)."}
            
        bh_str = get_recent_blockhash()
        if not bh_str:
            return {"success": False, "error": "Failed to fetch recent blockhash from Solana RPC."}
            
        bh = Hash.from_string(bh_str)
        ix = transfer(TransferParams(
            from_pubkey=sender_kp.pubkey(),
            to_pubkey=target_pubkey,
            lamports=lamports
        ))
        
        msg = MessageV0.try_compile(
            payer=sender_kp.pubkey(),
            instructions=[ix],
            address_lookup_table_accounts=[],
            recent_blockhash=bh
        )
        
        sig = sender_kp.sign_message(bytes(msg))
        signed_tx = VersionedTransaction.populate(msg, [sig])
        signed_b64 = base64.b64encode(bytes(signed_tx)).decode("ascii")
        
        res = solana_rpc("sendTransaction", [
            signed_b64,
            {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"}
        ])
        
        if res and isinstance(res, str):
            return {
                "success": True,
                "tx_signature": res,
                "solscan_url": f"https://solscan.io/tx/{res}"
            }
        elif res and isinstance(res, dict) and "error" in res:
            return {"success": False, "error": str(res["error"])}
        else:
            return {"success": False, "error": f"Broadcast failed: {res}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def record_solana_trade(user_id, input_mint, output_mint, symbol, trade_type, amount_in, amount_out, tx_signature, fee_amount, fee_symbol):
    """Log Solana trade in SQLite for volume tracking and affiliate splits."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO solana_trades 
        (user_id, input_mint, output_mint, symbol, trade_type, amount_in, amount_out, tx_signature, fee_amount, fee_symbol, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, input_mint, output_mint, symbol, trade_type, amount_in, amount_out, tx_signature, fee_amount, fee_symbol, int(time.time())))
    conn.commit()
    conn.close()

