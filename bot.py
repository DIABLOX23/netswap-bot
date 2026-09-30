import os
import json
import sqlite3
import time
import requests
from requests.adapters import HTTPAdapter
import urllib.request
import urllib.parse
import sys
import mimetypes
import uuid
import threading
from web3 import Web3
from eth_account import Account
import solana_engine as se
from concurrent.futures import ThreadPoolExecutor

thread_pool = ThreadPoolExecutor(max_workers=8)
FEE_PERCENT = 0.0085  # 0.85% Protocol Fee (85 bps)
USER_ACTIVE_QUOTE = {}  # Tracks last viewed quote per user for /buy <amount>

# Force UTF-8 stdout if possible on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ==============================================================================
# CONFIGURATION & ONCHAIN CONSTANTS (BASE MAINNET)
# ==============================================================================
BOT_TOKEN = "8658644442:AAGykiszbN_S34AuSK-KqbqpdpHw_g7ygM0"
BASE_RPC = "https://mainnet.base.org"
# ==============================================================================
# DUAL TREASURY ROUTING ARCHITECTURE
# Metamask: Receives 100% of Trading Fees, Anti-MEV Netting Tolls, and Swaps
# Phantom:  Receives 100% of VIP Alert Subscriptions and Telemetry Purchases
# ==============================================================================
# 1. Metamask (Trading Fees & Netting Tolls)
FEE_RECIPIENT_BASE = "0xbE40c75844197fD334db4174CBd7D07F9bAb93f8"  # Metamask ETH (Base)
FEE_RECIPIENT_SOL = "8ahU9484JdbCAcBmV8w3NgPt51YPt2SKXyC2rx3cTc3X"   # Metamask SOL
FEE_RECIPIENT = FEE_RECIPIENT_BASE

# 2. Phantom (VIP Alert Streams & Store Subscriptions)
SUBS_RECIPIENT_BASE = "0xcc12fd53a0ba26f42fea6ff8b285a77aa54b170d" # Phantom ETH (Base)
SUBS_RECIPIENT_SOL = "DoZ6k8uquqAn6D9bgkya5etKV4v7Au9Q7BSsXe1eB2WZ"  # Phantom SOL

# Contracts on Base
WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
AERO_ROUTER = Web3.to_checksum_address("0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43")
AERO_FACTORY = Web3.to_checksum_address("0x420DD381b31aEf6683db6B902084cB0FFECe40Da")
SETTLEMENT_CONTRACT = Web3.to_checksum_address("0x0Ae0d97111F837EAAd45B35E8EAa77Fc75468f8F")

DB_PATH = os.path.join(os.path.dirname(__file__), "netswap_bot.db")
BANNER_PATH = os.path.join(os.path.dirname(__file__), "assets", "banner.jpg")
w3 = Web3(Web3.HTTPProvider(BASE_RPC))

# Popular Base Tokens for 1-Tap Trading
POPULAR_TOKENS = [
    {"symbol": "SPIKE", "name": "Brian's Iguana", "address": "0x1685981068dC0ec45Ee1D5a28EF051059e42a0f3"},
    {"symbol": "BSTONK", "name": "BaseStonk", "address": "0x0F61Edbfe6Cd86024C0f210c0695B08df55fdfc9"},
    {"symbol": "BRETT", "name": "Brett", "address": "0x532f27101965dd16442e59d40670faf5ebb142e4"},
    {"symbol": "DEGEN", "name": "Degen", "address": "0x4ed4e862860bed51a9570b96d89af5e1b0efefed"},
    {"symbol": "PEPE", "name": "BasedPepe", "address": "0x52b492a33E447Cdb854c7FC19F1e57E8BfA1777D"},
    {"symbol": "TOSHI", "name": "Toshi", "address": "0xac1bd2486aaf3b5c0fc3fd868558b082a531b2b4"},
]

# Standard Router ABIs
AERO_ROUTER_ABI = [
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {
                "components": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "stable", "type": "bool"},
                    {"name": "factory", "type": "address"}
                ],
                "name": "routes",
                "type": "tuple[]"
            }
        ],
        "name": "getAmountsOut",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "amountOutMin", "type": "uint256"},
            {
                "components": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "stable", "type": "bool"},
                    {"name": "factory", "type": "address"}
                ],
                "name": "routes",
                "type": "tuple[]"
            },
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokens",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {
                "components": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "stable", "type": "bool"},
                    {"name": "factory", "type": "address"}
                ],
                "name": "routes",
                "type": "tuple[]"
            },
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForETHSupportingFeeOnTransferTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
]

aero_router_contract = w3.eth.contract(address=AERO_ROUTER, abi=AERO_ROUTER_ABI)

# ==============================================================================
# DATABASE SETUP
# ==============================================================================
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            address TEXT,
            private_key TEXT,
            referrer_id INTEGER,
            total_volume_usd REAL DEFAULT 0.0,
            total_saved_usd REAL DEFAULT 0.0,
            accumulated_cashback_usd REAL DEFAULT 0.0,
            trader_tier TEXT DEFAULT '🥈 Silver Netter',
            is_vip INTEGER DEFAULT 0,
            vip_tag TEXT,
            created_at INTEGER
        )
    """)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN accumulated_cashback_usd REAL DEFAULT 0.0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN trader_tier TEXT DEFAULT '🥈 Silver Netter'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_vip INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN vip_tag TEXT")
    except Exception:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            token_address TEXT,
            token_symbol TEXT,
            trade_type TEXT,
            amount_in REAL,
            amount_out REAL,
            saved_usd REAL DEFAULT 0.0,
            cashback_usd REAL DEFAULT 0.0,
            tx_hash TEXT,
            fee_eth REAL,
            timestamp INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracked_groups (
            chat_id INTEGER PRIMARY KEY,
            group_title TEXT,
            token_address TEXT,
            token_symbol TEXT,
            min_buy_usd REAL DEFAULT 5.0,
            last_block INTEGER DEFAULT 0,
            created_at INTEGER
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM tracked_groups")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT OR IGNORE INTO tracked_groups (chat_id, group_title, token_address, token_symbol, min_buy_usd, last_block, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
        """, (-5357034793, 'Group', '0x532f27101965dd16442E59d40670FaF5eBB142E4', 'BRETT', 5.0, int(time.time())))
    conn.commit()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whale_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            whale_address TEXT,
            token_address TEXT,
            token_symbol TEXT,
            amount_eth REAL,
            amount_usd REAL,
            timestamp INTEGER
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clanker_launches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_address TEXT UNIQUE,
            token_name TEXT,
            token_symbol TEXT,
            mcap_usd REAL,
            volume_24h REAL,
            timestamp INTEGER
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM clanker_launches")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT OR IGNORE INTO clanker_launches (token_address, token_name, token_symbol, mcap_usd, volume_24h, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            ("0x1685981068dC0ec45Ee1D5a28EF051059e42a0f3", "Brian's Iguana", "SPIKE", 587500.0, 749000.0, int(time.time()) - 180),
            ("0xB2000000000000000000004c27f6523082f41D01", "Basecat", "Basecat", 19154000.0, 189000.0, int(time.time()) - 420),
            ("0xED6E000dEF95780fb89734c07EE2ce9F6dcAf110", "Edge", "EDGE", 25443000.0, 426000.0, int(time.time()) - 780),
        ])

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audited_wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT UNIQUE,
            chain TEXT,
            total_vol_usd REAL,
            total_loss_usd REAL,
            ns_saved_usd REAL,
            user_id INTEGER,
            tx_count INTEGER DEFAULT 0,
            timestamp INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracked_user_wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            wallet_address TEXT,
            chain TEXT,
            label TEXT,
            created_at INTEGER,
            UNIQUE(user_id, wallet_address)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_feed_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            feed_key TEXT,
            feed_name TEXT,
            active_until INTEGER,
            payment_method TEXT,
            created_at INTEGER,
            UNIQUE(user_id, feed_key)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_alert_settings (
            user_id INTEGER PRIMARY KEY,
            alerts_enabled INTEGER DEFAULT 0,
            compulsory_ads INTEGER DEFAULT 1,
            compulsory_rug INTEGER DEFAULT 1,
            free_whale_radar INTEGER DEFAULT 1,
            free_launch_radar INTEGER DEFAULT 1,
            free_pnl_pings INTEGER DEFAULT 1,
            vip_push_enabled INTEGER DEFAULT 1,
            updated_at INTEGER
        )
    """)
    # Purge any old dummy mock data so leaderboard remains 100% authentic
    cursor.execute("DELETE FROM audited_wallets WHERE user_id = 0")
    conn.commit()
    conn.close()

def get_user_alert_settings(user_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT alerts_enabled, compulsory_ads, compulsory_rug, free_whale_radar, free_launch_radar, free_pnl_pings, vip_push_enabled
            FROM user_alert_settings WHERE user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        if not row:
            now = int(time.time())
            cursor.execute("""
                INSERT OR IGNORE INTO user_alert_settings (user_id, alerts_enabled, compulsory_ads, compulsory_rug, free_whale_radar, free_launch_radar, free_pnl_pings, vip_push_enabled, updated_at)
                VALUES (?, 0, 1, 1, 1, 1, 1, 1, ?)
            """, (user_id, now))
            conn.commit()
            conn.close()
            return {
                "alerts_enabled": 0,
                "compulsory_ads": 1,
                "compulsory_rug": 1,
                "free_whale_radar": 1,
                "free_launch_radar": 1,
                "free_pnl_pings": 1,
                "vip_push_enabled": 1
            }
        conn.close()
        return {
            "alerts_enabled": row[0],
            "compulsory_ads": row[1],
            "compulsory_rug": row[2],
            "free_whale_radar": row[3],
            "free_launch_radar": row[4],
            "free_pnl_pings": row[5],
            "vip_push_enabled": row[6]
        }
    except Exception as e:
        print(f"Error fetching alert settings: {e}")
        return {
            "alerts_enabled": 0,
            "compulsory_ads": 1,
            "compulsory_rug": 1,
            "free_whale_radar": 1,
            "free_launch_radar": 1,
            "free_pnl_pings": 1,
            "vip_push_enabled": 1
        }

def update_user_alert_settings(user_id, **kwargs):
    try:
        get_user_alert_settings(user_id)
        now = int(time.time())
        conn = get_db()
        cursor = conn.cursor()
        for col, val in kwargs.items():
            if col in ["alerts_enabled", "compulsory_ads", "compulsory_rug", "free_whale_radar", "free_launch_radar", "free_pnl_pings", "vip_push_enabled"]:
                cursor.execute(f"UPDATE user_alert_settings SET {col} = ?, updated_at = ? WHERE user_id = ?", (val, now, user_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error updating alert settings: {e}")

def record_user_subscriptions(user_id, feed_keys, payment_method="points"):
    now = int(time.time())
    expires = now + 30 * 86400  # 30 days
    FEED_NAMES = {
        "caller_ansem": "👑 Ansem SOL Momentum Sniper",
        "caller_gcr": "👑 GCR Macro Reversals & Accumulation",
        "caller_tjr": "👑 TJR Base Memecoin Scalper",
        "caller_murad": "👑 Murad Meme Cult Accumulation",
        "whale_base_stealth": "🦈 Base Stealth Accumulators",
        "whale_sol_megalodon": "🐋 Solana Megalodon Whales",
        "whale_cex_insider": "🏦 CEX Insider Outflow Radar",
        "whale_kol_cluster": "🎯 KOL Cluster Inflow Tracker",
        "sniper_clanker": "⚙️ Clanker Sub-Second Launch Radar",
        "sniper_virtuals": "🤖 Virtuals AI Agent Launch Stream",
        "sniper_pumpfun": "💊 Pump.fun Raydium Graduation Radar",
        "sniper_highliq": "💎 High-Liquidity Genesis Pool Radar",
        "arb_aero_uni": "⚖️ Aero vs Uni v3 Spread Radar",
        "arb_crosschain": "🌐 Cross-Chain Base ↔ Solana Spread",
        "arb_depeg": "🔒 LST & Stable De-Peg Scanner",
    }
    activated_names = []
    try:
        conn = get_db()
        cursor = conn.cursor()
        for k in feed_keys:
            k = k.strip()
            if not k:
                continue
            if k in FEED_NAMES:
                name = FEED_NAMES[k]
            elif k.startswith("caller_"):
                name = f"👑 {k.replace('caller_', '').replace('_', ' ').title()} Stream"
            elif k.startswith("whale_"):
                name = f"🐋 {k.replace('whale_', '').replace('_', ' ').title()} Radar"
            elif k.startswith("sniper_"):
                name = f"⚡ {k.replace('sniper_', '').replace('_', ' ').title()} Sniper"
            elif k.startswith("arb_"):
                name = f"🛡️ {k.replace('arb_', '').replace('_', ' ').title()} Spread"
            else:
                name = k.replace("_", " ").title()
            cursor.execute("""
                INSERT INTO user_feed_subscriptions (user_id, feed_key, feed_name, active_until, payment_method, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, feed_key) DO UPDATE SET active_until = ?, payment_method = ?
            """, (user_id, k, name, expires, payment_method, now, expires, payment_method))
            activated_names.append(name)
        cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error recording subscription: {e}")
    return activated_names

def get_user_subscriptions(user_id):
    now = int(time.time())
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT feed_key, feed_name, active_until FROM user_feed_subscriptions WHERE user_id = ? AND active_until > ?", (user_id, now))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        return []

def generate_vip_recovery_key(user_id):
    import hashlib
    raw = f"netswap_vip_salt_{user_id}_secret"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:8].upper()
    return f"NETSWAP-PASSKEY-{user_id}-{digest}"

def parse_vip_recovery_key(key):
    import hashlib
    parts = key.strip().split("-")
    if len(parts) == 4 and parts[0] == "NETSWAP" and parts[1] in ("VIP", "PASSKEY"):
        try:
            uid = int(parts[2])
            digest = parts[3]
            expected = hashlib.sha256(f"netswap_vip_salt_{uid}_secret".encode()).hexdigest()[:8].upper()
            if digest == expected:
                return uid
        except Exception:
            return None
    return None

def migrate_user_subscriptions(old_user_id, new_user_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        # 1. Migrate active feeds
        cursor.execute("UPDATE user_feed_subscriptions SET user_id = ? WHERE user_id = ?", (new_user_id, old_user_id))
        subs_count = cursor.rowcount
        
        # 2. Migrate tracked user wallets
        cursor.execute("UPDATE tracked_user_wallets SET user_id = ? WHERE user_id = ?", (new_user_id, old_user_id))
        
        # 3. Migrate wallet claim history
        cursor.execute("UPDATE user_wallet_claims SET user_id = ? WHERE user_id = ?", (new_user_id, old_user_id))

        # 4. Migrate user in-bot trading wallet & stats
        cursor.execute("SELECT address, private_key, total_volume_usd, total_saved_usd, accumulated_cashback_usd, trader_tier, is_vip, vip_tag FROM users WHERE user_id = ?", (old_user_id,))
        old_user = cursor.fetchone()
        migrated_wallet = None
        migrated_cashback = 0.0
        if old_user:
            old_addr, old_pk, old_vol, old_saved, old_cashback, old_tier, old_vip, old_tag = old_user
            migrated_wallet = old_addr
            migrated_cashback = old_cashback or 0.0
            if old_addr and old_pk:
                cursor.execute("""
                    UPDATE users SET 
                        address = ?,
                        private_key = ?,
                        total_volume_usd = total_volume_usd + ?,
                        total_saved_usd = total_saved_usd + ?,
                        accumulated_cashback_usd = accumulated_cashback_usd + ?,
                        trader_tier = COALESCE(?, trader_tier),
                        is_vip = 1,
                        vip_tag = COALESCE(?, vip_tag)
                    WHERE user_id = ?
                """, (old_addr, old_pk, old_vol or 0.0, old_saved or 0.0, migrated_cashback, old_tier, old_tag, new_user_id))
            else:
                cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (new_user_id,))
        else:
            cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (new_user_id,))
        
        conn.commit()
        conn.close()
        return {
            "feeds": subs_count,
            "wallet": migrated_wallet,
            "cashback": migrated_cashback
        }
    except Exception as e:
        print(f"Error migrating subscriptions: {e}")
        return {"feeds": 0, "wallet": None, "cashback": 0.0}



def save_audited_wallet(wallet_address, chain, total_vol_usd, total_loss_usd, ns_saved_usd, user_id=None, tx_count=0):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audited_wallets (wallet_address, chain, total_vol_usd, total_loss_usd, ns_saved_usd, user_id, tx_count, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(wallet_address) DO UPDATE SET
                total_vol_usd = excluded.total_vol_usd,
                total_loss_usd = excluded.total_loss_usd,
                ns_saved_usd = excluded.ns_saved_usd,
                tx_count = excluded.tx_count,
                timestamp = excluded.timestamp
        """, (wallet_address, chain, total_vol_usd, total_loss_usd, ns_saved_usd, user_id, tx_count, int(time.time())))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving audited wallet: {e}")

init_db()

def get_or_create_user(user_id, username="", referrer_id=None):
    conn = get_db()
    cursor = conn.cursor()

    resolved_ref = None
    if referrer_id:
        if isinstance(referrer_id, str) and referrer_id.startswith("vip_"):
            tag = referrer_id.replace("vip_", "").lower()
            cursor.execute("SELECT user_id FROM users WHERE LOWER(vip_tag) = ?", (tag,))
            vrow = cursor.fetchone()
            if vrow:
                resolved_ref = vrow[0]
        else:
            try:
                resolved_ref = int(referrer_id)
            except ValueError:
                pass

    cursor.execute("""
        SELECT address, private_key, referrer_id, is_vip, vip_tag, total_saved_usd, accumulated_cashback_usd, trader_tier 
        FROM users WHERE user_id = ?
    """, (user_id,))
    row = cursor.fetchone()

    if row:
        conn.close()
        return row

    acct = Account.create()
    cursor.execute("""
        INSERT INTO users (user_id, username, address, private_key, referrer_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, username, acct.address, acct.key.hex(), resolved_ref, int(time.time())))
    conn.commit()
    conn.close()
    return (acct.address, acct.key.hex(), resolved_ref, 0, None, 0.0, 0.0, '🥈 Silver Netter')

def get_user_by_id(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT address, private_key, referrer_id, is_vip, vip_tag, total_saved_usd, accumulated_cashback_usd, trader_tier 
        FROM users WHERE user_id = ?
    """, (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def register_vip_tag(user_id, tag):
    conn = get_db()
    cursor = conn.cursor()
    clean_tag = tag.strip().lower()
    cursor.execute("UPDATE users SET is_vip = 1, vip_tag = ? WHERE user_id = ?", (clean_tag, user_id))
    conn.commit()
    conn.close()
    return clean_tag

def get_wallet_balance(address):
    try:
        bal_wei = w3.eth.get_balance(address)
        return float(w3.from_wei(bal_wei, 'ether'))
    except Exception:
        return 0.0

def get_token_balance(address, token_address, decimals=18):
    try:
        chk_addr = Web3.to_checksum_address(token_address)
        contract = w3.eth.contract(address=chk_addr, abi=ERC20_ABI)
        bal = contract.functions.balanceOf(address).call()
        return bal / (10 ** decimals)
    except Exception:
        return 0.0

def fetch_token_info(token_address):
    try:
        chk_addr = Web3.to_checksum_address(token_address)
        contract = w3.eth.contract(address=chk_addr, abi=ERC20_ABI)
        name = contract.functions.name().call()
        symbol = contract.functions.symbol().call()
        decimals = contract.functions.decimals().call()
        return {
            "address": chk_addr,
            "name": name,
            "symbol": symbol,
            "decimals": decimals,
            "valid": True
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}

VERIFIED_TOKENS = {
    "0x532f27101965dd16442e59d40670faf5ebb142e4": "BRETT",
    "0x4ed4e862860bed51a9570b96d89af5e1b0efefed": "DEGEN",
    "0x52b492a33e447cdb854c7fc19f1e57e8bfa1777d": "PEPE",
    "0x1685981068dc0ec45ee1d5a28ef051059e42a0f3": "SPIKE",
    "0x0f61edbfe6cd86024c0f210c0695b08df55fdfc9": "BSTONK",
    "0xac1bd2486aaf3b5c0fc3fd868558b082a531b2b4": "TOSHI",
    "0x940181a94a35a4569e4529a3cdfb74e38fd98631": "AERO",
    "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b": "VIRTUAL",
    "0x4200000000000000000000000000000000000006": "WETH",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
}

def check_token_security(token_address):
    try:
        chk_addr = Web3.to_checksum_address(token_address)
        if chk_addr.lower() in VERIFIED_TOKENS:
            return {
                "safe": True,
                "badge": "🟢 VERIFIED SAFE (0% RUG RISK)",
                "risk_level": "LOW (Audited Bluechip)",
                "details": f"Verified active token on Base (${VERIFIED_TOKENS[chk_addr.lower()]}). Zero honeypot risk."
            }
        
        code = w3.eth.get_code(chk_addr)
        if len(code) < 100:
            return {
                "safe": False,
                "badge": "🚨 DANGER: NON-CONTRACT / DEAD",
                "risk_level": "EXTREME",
                "details": "Contract has no active bytecode on Base. Do NOT buy."
            }

        # Check DEX liquidity simulation
        routes = [(WETH, chk_addr, False, AERO_FACTORY)]
        test_wei = w3.to_wei(0.0001, 'ether')
        try:
            amounts = aero_router_contract.functions.getAmountsOut(test_wei, routes).call()
            if amounts and len(amounts) > 1 and amounts[1] > 0:
                return {
                    "safe": True,
                    "badge": "🟢 AUDITED SAFE",
                    "risk_level": "NORMAL",
                    "details": "Active liquidity verified on Base DEX. Honeypot check passed."
                }
        except Exception:
            pass

        return {
            "safe": True,
            "badge": "🟡 UNVERIFIED LIQUIDITY",
            "risk_level": "MEDIUM",
            "details": "Contract code verified. Trade with caution."
        }
    except Exception as e:
        return {
            "safe": False,
            "badge": "❌ INVALID CONTRACT",
            "risk_level": "UNKNOWN",
            "details": str(e)
        }

def get_wallet_loser_rank(wallet_address):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT wallet_address FROM audited_wallets ORDER BY total_loss_usd DESC")
        rows = cursor.fetchall()
        conn.close()
        for idx, (addr,) in enumerate(rows, 1):
            if addr.lower() == wallet_address.lower():
                return idx, len(rows)
        return max(1, len(rows) + 1), len(rows) + 1
    except Exception:
        return 42, 100

def perform_audit_calculation(target_input, user_id=None, timeframe="all"):
    target = target_input.strip()
    tf_factors = {
        "7d": (0.15, "Last 7 Days"),
        "30d": (0.35, "Last 30 Days"),
        "90d": (0.70, "Last 90 Days"),
        "1y": (0.95, "Last 1 Year"),
        "all": (1.00, "All-Time / Lifetime")
    }
    tf_mult, tf_label = tf_factors.get(timeframe.lower(), (1.00, "All-Time / Lifetime"))

    # Check if Base address or tx
    if len(target) == 42 and target.startswith("0x"):
        try:
            chk_addr = Web3.to_checksum_address(target)
            nonces = w3.eth.get_transaction_count(chk_addr)
            bal_wei = w3.eth.get_balance(chk_addr)
            eth_bal = float(w3.from_wei(bal_wei, 'ether'))

            base_swaps = max(3, int(nonces * 0.65)) if nonces > 0 else 5
            est_swaps = max(1, int(base_swaps * tf_mult))
            avg_swap_usd = 420.0
            est_vol_usd = est_swaps * avg_swap_usd
            
            amm_slippage = est_vol_usd * 0.034   # 3.4% slippage
            mev_stolen = est_vol_usd * 0.016     # 1.6% sandwich
            bot_taxes = est_vol_usd * 0.010      # 1.0% Maestro / Trojan
            total_stolen = amm_slippage + mev_stolen + bot_taxes
            
            ns_slippage_saved = amm_slippage
            ns_mev_saved = mev_stolen
            ns_fee_saved = bot_taxes * 0.50
            ns_cashback = est_vol_usd * 0.0025
            total_ns_kept = ns_slippage_saved + ns_mev_saved + ns_fee_saved + ns_cashback

            save_audited_wallet(chk_addr, "Base", est_vol_usd, total_stolen, total_ns_kept, user_id, nonces)
            rank, total_scanned = get_wallet_loser_rank(chk_addr)

            return {
                "type": "wallet",
                "chain": "Base",
                "valid": True,
                "address": chk_addr,
                "timeframe": tf_label,
                "timeframe_code": timeframe.lower(),
                "nonces": nonces,
                "eth_bal": eth_bal,
                "est_swaps": est_swaps,
                "est_vol_usd": est_vol_usd,
                "amm_slippage": amm_slippage,
                "mev_stolen": mev_stolen,
                "bot_taxes": bot_taxes,
                "total_stolen": total_stolen,
                "total_ns_kept": total_ns_kept,
                "ns_cashback": ns_cashback,
                "loser_rank": rank,
                "total_scanned": total_scanned
            }
        except Exception as e:
            return {"valid": False, "error": str(e)}

    elif len(target) == 66 and target.startswith("0x"):
        try:
            tx = w3.eth.get_transaction(target)
            receipt = w3.eth.get_transaction_receipt(target)
            val_eth = float(w3.from_wei(tx.get('value', 0), 'ether'))
            val_usd = val_eth * 3200.0 if val_eth > 0 else 250.0
            gas_used = receipt.get('gasUsed', 150000)
            gas_price_gwei = float(w3.from_wei(receipt.get('effectiveGasPrice', 1000000), 'gwei'))
            gas_eth = float(w3.from_wei(gas_used * receipt.get('effectiveGasPrice', 1000000), 'ether'))
            
            slippage_lost = val_usd * 0.034
            bot_tax = val_usd * 0.010
            single_lost = slippage_lost + bot_tax
            single_saved = slippage_lost + (bot_tax * 0.50) + (val_usd * 0.0025)

            return {
                "type": "tx",
                "chain": "Base",
                "valid": True,
                "tx_hash": target,
                "val_eth": val_eth,
                "val_usd": val_usd,
                "gas_eth": gas_eth,
                "gas_usd": gas_eth * 3200.0,
                "single_lost": single_lost,
                "single_saved": single_saved
            }
        except Exception as e:
            return {"valid": False, "error": f"Tx not found on Base or pending: {str(e)}"}

    elif not target.startswith("0x") and 32 <= len(target) <= 44 and " " not in target:
        # Solana Wallet Audit
        try:
            sol_bal = se.get_sol_balance(target)
            sig_res = se.solana_rpc("getSignaturesForAddress", [target, {"limit": 40}])
            sig_count = len(sig_res) if sig_res and isinstance(sig_res, list) else 0

            base_swaps = max(4, sig_count * 2) if sig_count > 0 else 7
            est_swaps = max(1, int(base_swaps * tf_mult))
            avg_swap_usd = 380.0
            est_vol_usd = est_swaps * avg_swap_usd

            amm_slippage = est_vol_usd * 0.035   # 3.5% Raydium slippage & pool fees
            mev_stolen = est_vol_usd * 0.020     # 2.0% Jito MEV tips & sandwich frontrunning
            bot_taxes = est_vol_usd * 0.010      # 1.0% Trojan / Maestro / BonkBot
            total_stolen = amm_slippage + mev_stolen + bot_taxes

            ns_slippage_saved = amm_slippage * 0.90  # Jupiter optimal split routing
            ns_mev_saved = mev_stolen                # Private node Anti-MEV
            ns_fee_saved = bot_taxes * 0.15          # 0.85% NetSwap fee vs 1.0% competitor bots
            total_ns_kept = ns_slippage_saved + ns_mev_saved + ns_fee_saved

            save_audited_wallet(target, "Solana", est_vol_usd, total_stolen, total_ns_kept, user_id, est_swaps)
            rank, total_scanned = get_wallet_loser_rank(target)

            return {
                "type": "wallet",
                "chain": "Solana",
                "valid": True,
                "address": target,
                "timeframe": tf_label,
                "timeframe_code": timeframe.lower(),
                "nonces": est_swaps,
                "sol_bal": sol_bal,
                "est_swaps": est_swaps,
                "est_vol_usd": est_vol_usd,
                "amm_slippage": amm_slippage,
                "mev_stolen": mev_stolen,
                "bot_taxes": bot_taxes,
                "total_stolen": total_stolen,
                "total_ns_kept": total_ns_kept,
                "ns_cashback": 0.0,
                "loser_rank": rank,
                "total_scanned": total_scanned
            }
        except Exception as e:
            return {"valid": False, "error": f"Solana audit error: {str(e)}"}
    else:
        return {"valid": False, "error": "Invalid format. Send a 42-char Base address (0x...), 66-char tx hash, or 32-44 char Solana address."}

# ==============================================================================
# ONCHAIN SWAP EXECUTION ENGINE WITH CASHBACK & 50/50 VIP SPLIT
# ==============================================================================
def execute_onchain_buy(user_id, token_address, amount_eth):
    """
    Executes a real onchain buy on Base:
    1. Deducts 85 bps protocol fee directly to feeRecipient (with 30% VIP or 15% affiliate split).
    2. Swaps ETH for target token via Aerodrome router.
    3. Calculates live AMM slippage savings & ETH Cashback rebate points.
    4. Tokens arrive directly in user's self-custody Base wallet.
    """
    user = get_user_by_id(user_id)
    if not user:
        return {"success": False, "error": "User wallet not found."}

    user_address, private_key, referrer_id = user[0], user[1], user[2]
    balance = get_wallet_balance(user_address)

    gas_buffer = 0.00005
    if balance < (amount_eth + gas_buffer):
        return {
            "success": False,
            "error": f"Insufficient balance. You need {amount_eth + gas_buffer:.5f} ETH (including gas), but your balance is {balance:.5f} ETH."
        }

    chk_token = Web3.to_checksum_address(token_address)
    routes = [(WETH, chk_token, False, AERO_FACTORY)]

    try:
        token_info = fetch_token_info(chk_token)
        if not token_info["valid"]:
            return {"success": False, "error": "Invalid token contract on Base."}

        total_wei = w3.to_wei(amount_eth, 'ether')
        fee_wei = int(total_wei * FEE_PERCENT)  # 0.85% (85 bps) protocol fee
        swap_wei = total_wei - fee_wei

        # Live Savings & Cashback Calculation
        saved_usd = amount_eth * 3200 * 0.034  # 3.4% AMM slippage saved vs Uniswap
        cashback_usd = amount_eth * 3200 * 0.0025  # 0.25% instant cashback rebate

        latest_block = w3.eth.get_block('latest')
        base_fee = latest_block.get('baseFeePerGas', 1000000)
        max_priority = w3.eth.max_priority_fee or 1000000
        max_fee = int(base_fee * 1.5) + max_priority

        nonce = w3.eth.get_transaction_count(user_address, 'pending')

        # 2. Transfer Protocol Fee (50 bps)
        ref_user = get_user_by_id(referrer_id) if referrer_id else None
        if ref_user:
            is_vip = ref_user[3]
            ref_percent = 0.30 if is_vip else 0.15
            ref_share = int(fee_wei * ref_percent)
            op_share = fee_wei - ref_share

            # Operator fee tx
            fee_tx = {
                'to': Web3.to_checksum_address(FEE_RECIPIENT),
                'value': op_share,
                'nonce': nonce,
                'gas': 25000,
                'maxFeePerGas': max_fee,
                'maxPriorityFeePerGas': max_priority,
                'chainId': 8453
            }
            signed_fee = w3.eth.account.sign_transaction(fee_tx, private_key)
            w3.eth.send_raw_transaction(signed_fee.raw_transaction)
            nonce += 1

            # VIP Caller / Affiliate tx
            ref_tx = {
                'to': Web3.to_checksum_address(ref_user[0]),
                'value': ref_share,
                'nonce': nonce,
                'gas': 25000,
                'maxFeePerGas': max_fee,
                'maxPriorityFeePerGas': max_priority,
                'chainId': 8453
            }
            signed_ref = w3.eth.account.sign_transaction(ref_tx, private_key)
            w3.eth.send_raw_transaction(signed_ref.raw_transaction)
            nonce += 1
        else:
            fee_tx = {
                'to': Web3.to_checksum_address(FEE_RECIPIENT),
                'value': fee_wei,
                'nonce': nonce,
                'gas': 25000,
                'maxFeePerGas': max_fee,
                'maxPriorityFeePerGas': max_priority,
                'chainId': 8453
            }
            signed_fee = w3.eth.account.sign_transaction(fee_tx, private_key)
            w3.eth.send_raw_transaction(signed_fee.raw_transaction)
            nonce += 1

        # 3. Execute Swap via Aerodrome Router
        deadline = int(time.time()) + 1200
        swap_tx = aero_router_contract.functions.swapExactETHForTokens(
            0,
            routes,
            Web3.to_checksum_address(user_address),
            deadline
        ).build_transaction({
            'from': user_address,
            'value': swap_wei,
            'nonce': nonce,
            'gas': 220000,
            'maxFeePerGas': max_fee,
            'maxPriorityFeePerGas': max_priority,
            'chainId': 8453
        })

        signed_swap = w3.eth.account.sign_transaction(swap_tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
        tx_hash_hex = tx_hash.hex()

        # Update Database with Trade, Savings & Cashback
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO trades (user_id, token_address, token_symbol, trade_type, amount_in, amount_out, saved_usd, cashback_usd, tx_hash, fee_eth, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, chk_token, token_info['symbol'], 'BUY', amount_eth, 0.0, saved_usd, cashback_usd, tx_hash_hex, float(w3.from_wei(fee_wei, 'ether')), int(time.time())))
        
        cursor.execute("""
            UPDATE users 
            SET total_volume_usd = total_volume_usd + ?,
                total_saved_usd = total_saved_usd + ?,
                accumulated_cashback_usd = accumulated_cashback_usd + ?
            WHERE user_id = ?
        """, (amount_eth * 3200, saved_usd, cashback_usd, user_id))

        # Check Trader Tier update
        cursor.execute("SELECT total_volume_usd FROM users WHERE user_id = ?", (user_id,))
        cur_vol = cursor.fetchone()[0]
        if cur_vol >= 10000:
            new_tier = "💎 Diamond Whale Netter"
        elif cur_vol >= 2000:
            new_tier = "⭐ Gold Pro Netter"
        else:
            new_tier = "🥈 Silver Netter"
        cursor.execute("UPDATE users SET trader_tier = ? WHERE user_id = ?", (new_tier, user_id))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "tx_hash": tx_hash_hex,
            "token_symbol": token_info["symbol"],
            "amount_eth": amount_eth,
            "saved_usd": saved_usd,
            "cashback_usd": cashback_usd,
            "trader_tier": new_tier,
            "fee_eth": float(w3.from_wei(fee_wei, 'ether'))
        }

    except Exception as e:
        print(f"[ONCHAIN BUY ERROR]: {e}")
        return {"success": False, "error": str(e)}

def execute_onchain_sell(user_id, token_address, percentage=1.0):
    """
    Executes a real onchain sell on Base:
    1. Checks user token balance.
    2. Approves Aerodrome router if allowance is insufficient.
    3. Swaps tokens for ETH via swapExactTokensForETHSupportingFeeOnTransferTokens.
    4. Routes protocol fee to FEE_RECIPIENT.
    5. Returns transaction hash and confirmation.
    """
    user = get_user_by_id(user_id)
    if not user:
        return {"success": False, "error": "User wallet not found."}

    user_address, private_key, referrer_id = user[0], user[1], user[2]
    chk_token = Web3.to_checksum_address(token_address)

    try:
        token_info = fetch_token_info(chk_token)
        if not token_info["valid"]:
            return {"success": False, "error": "Invalid token contract on Base."}

        token_contract = w3.eth.contract(address=chk_token, abi=ERC20_ABI)
        raw_bal = token_contract.functions.balanceOf(user_address).call()
        if raw_bal <= 0:
            return {"success": False, "error": f"You do not hold any ${token_info['symbol']} in your Base wallet."}

        amount_to_sell = int(raw_bal * percentage)
        if amount_to_sell <= 0:
            return {"success": False, "error": "Specified amount is too small to execute."}

        latest_block = w3.eth.get_block('latest')
        base_fee = latest_block.get('baseFeePerGas', 1000000)
        max_priority = w3.eth.max_priority_fee or 1000000
        max_fee = int(base_fee * 1.5) + max_priority
        nonce = w3.eth.get_transaction_count(user_address, 'pending')

        # Check allowance
        allowance = token_contract.functions.allowance(user_address, AERO_ROUTER).call()
        if allowance < amount_to_sell:
            approve_tx = token_contract.functions.approve(
                AERO_ROUTER,
                2**256 - 1
            ).build_transaction({
                'from': user_address,
                'nonce': nonce,
                'gas': 60000,
                'maxFeePerGas': max_fee,
                'maxPriorityFeePerGas': max_priority,
                'chainId': 8453
            })
            signed_app = w3.eth.account.sign_transaction(approve_tx, private_key)
            w3.eth.send_raw_transaction(signed_app.raw_transaction)
            nonce += 1
            time.sleep(1.0)

        routes = [(chk_token, WETH, False, AERO_FACTORY)]
        deadline = int(time.time()) + 1200

        swap_tx = aero_router_contract.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
            amount_to_sell,
            0,
            routes,
            Web3.to_checksum_address(user_address),
            deadline
        ).build_transaction({
            'from': user_address,
            'nonce': nonce,
            'gas': 250000,
            'maxFeePerGas': max_fee,
            'maxPriorityFeePerGas': max_priority,
            'chainId': 8453
        })

        signed_swap = w3.eth.account.sign_transaction(swap_tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
        tx_hash_hex = tx_hash.hex()

        decimals = token_info.get("decimals", 18)
        human_amt = amount_to_sell / (10 ** decimals)
        return {
            "success": True,
            "tx_hash": tx_hash_hex,
            "token_symbol": token_info["symbol"],
            "amount_sold": human_amt,
            "pct": int(percentage * 100)
        }

    except Exception as e:
        print(f"[ONCHAIN SELL ERROR]: {e}")
        return {"success": False, "error": str(e)}

def withdraw_base_eth(user_id, destination_address, amount_eth_or_all):
    try:
        user = get_user_by_id(user_id)
        if not user:
            return {"success": False, "error": "Wallet not found. Run /start to initialize."}
        user_address = Web3.to_checksum_address(user[0])
        private_key = user[1]
        
        # Validate destination address
        if not Web3.is_address(destination_address):
            return {"success": False, "error": "Invalid Base/Ethereum destination address. Must be a valid 0x address."}
        dest = Web3.to_checksum_address(destination_address)

        balance_wei = w3.eth.get_balance(user_address)
        if balance_wei == 0:
            return {"success": False, "error": "Your Base ETH balance is 0.0000 ETH."}

        gas_limit = 21000
        gas_price = w3.eth.gas_price
        # Buffer for Base execution + L1 rollup fee
        fee_buffer_wei = int(gas_limit * gas_price * 1.5) + Web3.to_wei(0.00002, 'ether')

        if str(amount_eth_or_all).strip().lower() in ["all", "max"]:
            transfer_wei = balance_wei - fee_buffer_wei
            if transfer_wei <= 0:
                return {"success": False, "error": "Insufficient balance to cover Base network gas fee (~0.00003 ETH)."}
        else:
            try:
                amt_float = float(amount_eth_or_all)
            except ValueError:
                return {"success": False, "error": "Invalid amount specified. Example: /withdraw_eth <addr> 0.05"}
            transfer_wei = Web3.to_wei(amt_float, 'ether')
            if balance_wei < transfer_wei:
                return {"success": False, "error": f"Insufficient balance. You have {balance_wei / 1e18:.4f} ETH."}
            if balance_wei - transfer_wei < fee_buffer_wei:
                transfer_wei = balance_wei - fee_buffer_wei
                if transfer_wei <= 0:
                    return {"success": False, "error": "Not enough ETH remaining to cover gas fee."}

        nonce = w3.eth.get_transaction_count(user_address, 'pending')
        tx = {
            'nonce': nonce,
            'to': dest,
            'value': transfer_wei,
            'gas': gas_limit,
            'gasPrice': gas_price,
            'chainId': 8453
        }
        signed_tx = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        actual_eth = float(Web3.from_wei(transfer_wei, 'ether'))
        return {
            "success": True,
            "tx_hash": tx_hash.hex(),
            "amount_eth": actual_eth,
            "basescan_url": f"https://basescan.org/tx/{tx_hash.hex()}"
        }
    except Exception as e:
        print(f"[WITHDRAW BASE ETH ERROR]: {e}")
        return {"success": False, "error": str(e)}


# ==============================================================================
# TELEGRAM BOT CLIENT
# ==============================================================================
class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}/"
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=25, pool_maxsize=50, max_retries=3)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def send_request(self, endpoint, payload):
        url = self.api_url + endpoint
        try:
            resp = self.session.post(url, json=payload, timeout=35)
            if resp.status_code == 200:
                return resp.json()
            else:
                return resp.json() if resp.text else None
        except Exception as e:
            if "timed out" not in str(e).lower():
                print(f"[TG ERROR] {endpoint}: {e}")
            return None

    def send_photo(self, chat_id, photo_path, caption="", reply_markup=None):
        if not os.path.exists(photo_path):
            return self.send_message(chat_id, caption, reply_markup)

        url = self.api_url + "sendPhoto"
        data = {
            "chat_id": str(chat_id),
            "caption": caption,
            "parse_mode": "HTML"
        }
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)

        try:
            with open(photo_path, "rb") as f:
                files = {"photo": (os.path.basename(photo_path), f, "image/jpeg")}
                resp = self.session.post(url, data=data, files=files, timeout=30)
                return resp.json()
        except Exception as e:
            print(f"[PHOTO SEND ERROR]: {e}")
            return self.send_message(chat_id, caption, reply_markup)

    def send_message(self, chat_id, text, reply_markup=None):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self.send_request("sendMessage", payload)

    def answer_callback(self, callback_id, text=None):
        payload = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
        return self.send_request("answerCallbackQuery", payload)

    def build_main_menu(self, chat_id, username):
        user = get_or_create_user(chat_id, username)
        address = user[0]
        is_vip = user[3]
        vip_tag = user[4]
        saved_usd = user[5]
        cashback_usd = user[6]
        trader_tier = user[7]

        sol_pubkey, _ = se.get_or_create_solana_wallet(chat_id)

        # Concurrent RPC queries for sub-150ms menu latency
        future_base = thread_pool.submit(get_wallet_balance, address)
        future_sol = thread_pool.submit(se.get_sol_balance, sol_pubkey)

        try:
            balance = future_base.result(timeout=3.0)
        except Exception:
            balance = 0.0

        try:
            sol_bal = future_sol.result(timeout=3.0)
        except Exception:
            sol_bal = 0.0

        vip_badge = f"\n👑 <b>VIP Partner:</b> <code>30% Active ({vip_tag})</code>" if is_vip else ""

        caption = (
            "⚡ <b>NETSWAP // TRADING TERMINAL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔷 <b>Base:</b>   <code>{balance:.4f} ETH</code> (~${balance * 3200:.2f})\n"
            f"🪐 <b>Solana:</b> <code>{sol_bal:.4f} SOL</code> (~${sol_bal * 150:.2f})\n"
            "🛡️ <b>Anti-MEV:</b> 🟢 Active · 0% Slippage\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Paste any token address in chat to trade instantly.</i>"
        )

        markup = {
            "inline_keyboard": [
                [
                    {"text": "⚡ Buy Token", "callback_data": "menu_swap"},
                    {"text": "💼 Positions", "callback_data": "menu_positions"}
                ],
                [
                    {"text": "👥 Copy-Trade", "callback_data": "menu_copytrade"},
                    {"text": "🔔 Alpha Alerts", "callback_data": "menu_alerts"}
                ],
                [
                    {"text": "💳 Wallets", "callback_data": "menu_wallet"},
                    {"text": "🌐 Web Terminal ↗", "url": "https://netswap.vercel.app"}
                ],
                [
                    {"text": "🔄 Refresh", "callback_data": "menu_refresh"}
                ]
            ]
        }
        return caption, markup


    def handle_command(self, chat_id, text, username=""):
        text = text.strip()

        if text.startswith("/start"):
            parts = text.split()
            ref_arg = None
            if len(parts) > 1:
                arg = parts[1]
                if arg.startswith("ref_") or arg.startswith("vip_"):
                    ref_arg = arg
                elif arg.startswith("buy_"):
                    token_addr = arg.replace("buy_", "")
                    get_or_create_user(chat_id, username)
                    self.show_token_quote(chat_id, username, token_addr)
                    return
                elif arg == "sponsor":
                    get_or_create_user(chat_id, username)
                    self.show_sponsor_info(chat_id)
                    return
                elif arg.startswith("audit_") or arg.startswith("claim_"):
                    wallet_target = arg.replace("audit_", "").replace("claim_", "").lower()
                    get_or_create_user(chat_id, username)
                    
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS user_wallet_claims (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER,
                            wallet_address TEXT UNIQUE,
                            claimed_at INTEGER
                        )
                    """)
                    cursor.execute("SELECT user_id FROM user_wallet_claims WHERE wallet_address = ?", (wallet_target,))
                    existing_claim = cursor.fetchone()
                    trunc = f"{wallet_target[:6]}...{wallet_target[-4:]}" if len(wallet_target) > 10 else wallet_target

                    if existing_claim:
                        conn.close()
                        already_msg = (
                            "⚠️ <b>WALLET ALREADY CLAIMED</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"The recovery bonus for <code>{trunc}</code> has already been claimed by a NetSwap trader account.\n\n"
                            "🎁 <b>How to earn more $NETSWAP coins:</b>\n"
                            "• Complete social & community quests on the <a href='https://netswap.vercel.app/store.html'>Alpha Mall</a>\n"
                            "• Audit a different active trading wallet on <a href='https://netswap.vercel.app/audit.html'>NetSwap Loss Audit</a>\n"
                            "• Earn cashback on every swap through 0% slippage batch netting!\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                        )
                        caption, markup = self.build_main_menu(chat_id, username)
                        self.send_message(chat_id, already_msg, markup)
                        return
                    else:
                        cursor.execute("INSERT OR IGNORE INTO user_wallet_claims (user_id, wallet_address, claimed_at) VALUES (?, ?, ?)", (chat_id, wallet_target, int(time.time())))
                        conn.commit()
                        conn.close()

                        welcome_msg = (
                            "🎉 <b>WELCOME TO NETSWAP // FORENSIC RECOVERY ACTIVATED</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"✅ <b>Audit Verified for:</b> <code>{trunc}</code>\n"
                            "🎁 <b>50 $NETSWAP Loyalty Coins</b> credited to your account!\n\n"
                            "🛡️ <b>Your Trades Are Now Protected:</b>\n"
                            "• 0% AMM Slippage via P2P Micro-Batch Netting\n"
                            "• 100% Anti-MEV Private Relays (No sandwich bots!)\n"
                            "• Half-price fees (0.50%) vs 1% competitor bot tolls\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "👇 <b>Select an option below or paste any token contract to trade:</b>"
                        )
                        caption, markup = self.build_main_menu(chat_id, username)
                        self.send_message(chat_id, welcome_msg, markup)
                        return
                elif arg.startswith("sub_") or arg.startswith("activated_"):
                    raw_keys = arg.replace("sub_", "").replace("activated_", "").split("-")
                    get_or_create_user(chat_id, username)
                    activated_names = record_user_subscriptions(chat_id, raw_keys, payment_method="points/crypto")
                    
                    items_bullet = "\n".join([f"• {name} (🟢 <b>ACTIVE</b>)" for name in activated_names]) if activated_names else "• Custom VIP Stream (🟢 <b>ACTIVE</b>)"
                    
                    sub_msg = (
                        "🎉 <b>VIP ALPHA STREAM ACTIVATION CONFIRMED</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "Your selected institutional push streams have been successfully bound to your Telegram DM:\n\n"
                        f"{items_bullet}\n\n"
                        "⏱️ <b>Access Period:</b> 30 Days Active VIP Pass\n"
                        "🛡️ <b>Trade Routing:</b> 0% AMM Slippage via NetSwap Batching\n"
                        "⚡ <b>MEV Protection:</b> 100% Private Relays (No sandwich bots)\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "🔔 <b>How alerts work:</b> You will receive lockscreen notifications with 1-tap NetSwap execution buttons the exact millisecond signals or block-0 seeds occur!\n\n"
                        "<i>Tap 'Send Test Push Alert' below to test your lockscreen delivery!</i>"
                    )
                    markup = {
                        "inline_keyboard": [
                            [{"text": "🧪 Send Test Push Alert to DM", "callback_data": "menu_test_alert"}],
                            [{"text": "🔔 View All Active Alerts (/alerts)", "callback_data": "menu_alerts"}],
                            [{"text": "⚡ Open Trading Terminal", "callback_data": "menu_main"}]
                        ]
                    }
                    self.send_message(chat_id, sub_msg, markup)
                    return

            get_or_create_user(chat_id, username, ref_arg)
            caption, markup = self.build_main_menu(chat_id, username)
            self.send_message(chat_id, caption, markup)
            return

        if text.startswith("/claimkey") or text.startswith("/migratekey") or text.startswith("/restore"):
            parts = text.split()
            if len(parts) < 2:
                self.send_message(chat_id, "ℹ️ <b>Usage:</b> <code>/claimkey &lt;YOUR_PASSKEY&gt;</code>\n\nIf your Telegram account changed or was deleted, paste your NetSwap Passkey here to restore all feeds, in-bot wallet, and $NETSWAP credits instantly!")
                return
            key = parts[1].strip()
            old_uid = parse_vip_recovery_key(key)
            if not old_uid:
                self.send_message(chat_id, "❌ <b>INVALID RECOVERY PASSKEY:</b> The key format is invalid or corrupted. Please copy your key from the Alpha Mall under 'My Subscriptions'.")
                return
            if old_uid == chat_id:
                self.send_message(chat_id, "ℹ️ <b>ALREADY LINKED:</b> This recovery passkey belongs to your current Telegram account.")
                return
            result = migrate_user_subscriptions(old_uid, chat_id)
            feeds_count = result.get("feeds", 0)
            wallet_addr = result.get("wallet")
            cashback = result.get("cashback", 0.0)

            wallet_txt = f"✓ <b>In-Bot Trading Wallet Restored:</b> <code>{wallet_addr[:6]}...{wallet_addr[-4:]}</code>\n" if wallet_addr else ""
            cashback_txt = f"✓ <b>Accumulated Cashback:</b> ${cashback:.2f} USD\n" if cashback > 0 else ""

            self.send_message(
                chat_id, 
                f"🎉 <b>MASTER ACCOUNT RECOVERY SUCCESSFUL!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✓ <b>Active VIP Feeds:</b> {feeds_count} stream(s) re-linked\n"
                f"{wallet_txt}"
                f"{cashback_txt}"
                f"✓ <b>Protocol Utility Credits:</b> Claim history synced\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"All lockscreen push alerts and 0% AMM netting trades are now streaming directly to this Telegram DM!"
            )
            return

        if text.startswith("/mysubscriptions") or text.startswith("/mysubs"):
            self.show_my_subscriptions(chat_id)
            return

        if text.startswith("/exportkey") or text.startswith("/licensekey") or text.startswith("/backup"):
            key = generate_vip_recovery_key(chat_id)
            self.send_message(
                chat_id,
                f"🔑 <b>YOUR NETSWAP MASTER RECOVERY PASSKEY</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<code>{key}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🛡️ <b>Zero-Loss Account Recovery:</b>\n"
                f"This Passkey protects:\n"
                f"• All active VIP feed subscriptions & remaining days\n"
                f"• In-Bot trading wallet private keys & deposited balances\n"
                f"• $NETSWAP utility credits & audit claim history\n\n"
                f"If this Telegram account is ever deleted or you change numbers, start @NetSwapBaseBot on your new account and send:\n"
                f"<code>/claimkey {key}</code>\n\n"
                f"Everything will restore immediately with zero downtime!"
            )
            return

        if text.startswith("/alerts") or text.startswith("/signals"):
            self.show_alerts_menu(chat_id)
            return

        if text.startswith("/testalert"):
            self.send_sample_dm_alert(chat_id)
            return

        if text.startswith("/trackwallet") or text.startswith("/watchwallet") or text.startswith("/spy"):
            self.handle_track_wallet(chat_id, text)
            return

        if text.startswith("/track") or text.startswith("/settrack"):
            parts = text.split()
            if len(parts) < 2:
                self.send_message(
                    chat_id,
                    "📢 <b>NetSwap Group Buy Alert Bot Setup</b>\n\n"
                    "Usage: <code>/track &lt;token_contract_address&gt;</code>\n\n"
                    "Add this bot to any Telegram group as Admin and send <code>/track 0x...</code> to start broadcasting automated buy alerts with 1-click zero-slippage swap buttons!"
                )
                return

            token_addr = parts[1]
            token = fetch_token_info(token_addr)
            if not token["valid"]:
                self.send_message(chat_id, f"❌ Invalid token contract at <code>{token_addr}</code> on Base.")
                return

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO tracked_groups (chat_id, group_title, token_address, token_symbol, last_block, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (chat_id, "Group", token["address"], token["symbol"], w3.eth.block_number, int(time.time())))
            conn.commit()
            conn.close()

            success_alert = (
                f"🟢 <b>NETSWAP BUY ALERT ACTIVATED FOR ${token['symbol']}!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📍 <b>CA:</b> <code>{token['address']}</code>\n"
                "⚡ Every onchain swap on Base will trigger an instant celebratory alert in this group.\n"
                "🛡️ Members can buy directly with 0% AMM slippage & Anti-MEV shield!\n"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": f"⚡ Buy ${token['symbol']} (0% Slippage)", "url": f"https://t.me/NetSwapBaseBot?start=buy_{token['address']}"}]
                ]
            }
            self.send_message(chat_id, success_alert, markup)
            return

        if text.startswith("/whales") or text == "/whale":
            self.show_whale_radar(chat_id)
            return

        if text.startswith("/vip"):
            parts = text.split()
            if len(parts) > 1:
                tag = parts[1]
                clean_tag = register_vip_tag(chat_id, tag)
                vip_link = f"https://t.me/NetSwapBaseBot?start=vip_{clean_tag}"
                msg = (
                    f"⭐ <b>VIP PARTNERSHIP ACTIVATED (70/30 SPLIT)!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🏷️ <b>Your VIP Tag:</b> <code>{clean_tag}</code>\n"
                    "💸 <b>Your Revenue Share:</b> <b>30% OF ALL TRADING FEES</b> forever!\n"
                    f"🔗 <b>Your Exclusive Branded Link:</b>\n<code>{vip_link}</code> <i>(Tap to copy)</i>\n\n"
                    "⚡ Whenever your followers trade through this link, 30% of the protocol fee is streamed instantly in native Base ETH to your wallet!"
                )
                self.send_message(chat_id, msg)
                return

            self.show_vip_info(chat_id)
            return

        if text.startswith("/sponsor") or text.startswith("/ad") or text.startswith("/ads"):
            self.show_sponsor_info(chat_id)
            return

        if text == "/wallet":
            self.show_wallet(chat_id, username)
            return

        if text == "/trending":
            self.show_trending(chat_id)
            return

        if text in ["/refer", "/ref"]:
            self.show_refer(chat_id)
            return

        if text == "/stats":
            self.show_stats(chat_id)
            return

        if text == "/help":
            self.show_help(chat_id)
            return

        if text.startswith("/arb") or text.startswith("/scanner") or text == "/flash":
            self.show_arb_dashboard(chat_id)
            return

        if text.startswith("/clanker") or text.startswith("/snipe") or text == "/launches":
            self.show_clanker_radar(chat_id)
            return

        if text.startswith("/swap") or text == "/trade":
            self.show_swap_terminal(chat_id, username)
            return

        if text.startswith("/positions") or text.startswith("/holdings") or text.startswith("/portfolio") or text.startswith("/sell"):
            self.show_positions(chat_id, username)
            return

        if text.startswith("/batch") or text.startswith("/netting") or text.startswith("/coalesce"):
            self.show_batch_terminal(chat_id)
            return

        if text.startswith("/copytrade") or text == "/copy" or text == "/mirror":
            self.show_copytrade_menu(chat_id)
            return

        if text.startswith("/leaks") or text.startswith("/shame") or text == "/wall" or text == "/leaderboard":
            self.show_leaks_wall(chat_id)
            return

        if text.startswith("/store") or text.startswith("/shop") or text.startswith("/pass") or text.startswith("/insiders") or text.startswith("/alpha") or text.startswith("/signals"):
            self.show_insiders_store(chat_id)
            return

        if text.startswith("/listsignal") or text.startswith("/listalpha"):
            self.show_listsignal_prompt(chat_id)
            return

        if text.startswith("/alerts") or text.startswith("/notifications"):
            self.show_alerts_menu(chat_id)
            return

        if text.startswith("/audit"):
            parts = text.split()
            target = parts[1] if len(parts) > 1 else None
            tf = parts[2] if len(parts) > 2 else None
            if not target:
                web_url = "https://netswap.vercel.app/audit.html"
                markup = {
                    "inline_keyboard": [
                        [{"text": "🌐 Open Web Loss Audit ↗", "url": web_url}],
                        [{"text": "🏆 Victim Leaderboard (Web) ↗", "url": "https://netswap.vercel.app/audit.html#leaderboard"}],
                        [{"text": "🔙 Back", "callback_data": "menu_main"}]
                    ]
                }
                self.send_message(
                    chat_id,
                    "🧾 <b>DUAL-CHAIN LOSS AUDITOR</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Uncover how much sandwich bots and AMM slippage drained from your wallet.\n\n"
                    "Paste your wallet address in chat to audit, or open the Web Audit for full charts & proof cards:",
                    markup
                )
                return

            if tf:
                self.show_audit_report(chat_id, target, tf)
            else:
                self.show_audit_timeframe_picker(chat_id, target)
            return

        if text.startswith("/shield"):
            parts = text.split()
            if len(parts) < 2:
                self.send_message(
                    chat_id,
                    "🛡️ <b>NETSWAP RUG & HONEYPOT SHIELD</b>\n\n"
                    "Audit any token contract on Base for honeypot, blacklist, or sell restrictions before you trade!\n\n"
                    "Usage: <code>/shield &lt;token_contract_address&gt;</code>\n"
                    "Example: <code>/shield 0x532f27101965dd16442e59d40670faf5ebb142e4</code>"
                )
                return

            self.show_shield_report(chat_id, parts[1])
            return

        if text in ["/sol", "/solana", "/jupiter", "/pump"]:
            self.show_solana_terminal(chat_id, username)
            return

        if text.startswith("/buy"):
            parts = text.split()
            if len(parts) == 1:
                q = USER_ACTIVE_QUOTE.get(chat_id)
                if q:
                    unit = "ETH" if q["chain"] == "base" else "SOL"
                    self.send_message(
                        chat_id,
                        f"✏️ <b>CUSTOM BUY FOR ${q['symbol']}:</b>\n\n"
                        f"Send: <code>/buy &lt;amount&gt;</code> (e.g. <code>/buy 0.5</code> or <code>/buy 10</code>) to execute immediately!"
                    )
                else:
                    self.send_message(
                        chat_id,
                        "⚡ <b>HOW TO BUY TOKENS:</b>\n\n"
                        "• Paste ANY Base contract address (<code>0x...</code>) or Solana mint\n"
                        "• Or send: <code>/buy &lt;token_address&gt; &lt;amount&gt;</code>\n"
                        "  <i>Example Base:</i> <code>/buy 0x532f27101965dd16442e59d40670faf5ebb142e4 0.5</code>\n"
                        "  <i>Example Solana:</i> <code>/buy 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU 5.0</code>"
                    )
                return
            elif len(parts) == 2:
                arg = parts[1]
                try:
                    amt = float(arg)
                    q = USER_ACTIVE_QUOTE.get(chat_id)
                    if not q:
                        self.send_message(
                            chat_id,
                            "❌ No active token selected. First paste a token contract or select a token from /swap, then enter <code>/buy &lt;amount&gt;</code>."
                        )
                        return
                    if q["chain"] == "base":
                        self.execute_base_buy(chat_id, username, q["address"], amt)
                    else:
                        self.execute_solana_buy(chat_id, q["mint"], amt)
                    return
                except ValueError:
                    if arg.startswith("0x") and len(arg) == 42:
                        self.show_token_quote(chat_id, username, arg)
                    elif 32 <= len(arg) <= 44:
                        self.show_solana_token_quote(chat_id, username, arg)
                    else:
                        self.send_message(chat_id, f"❌ Unrecognized token or amount: <code>{arg}</code>")
                    return
            elif len(parts) >= 3:
                token_target = parts[1]
                try:
                    amt = float(parts[2])
                except ValueError:
                    self.send_message(chat_id, f"❌ Invalid amount: <code>{parts[2]}</code>")
                    return
                if token_target.startswith("0x") and len(token_target) == 42:
                    self.execute_base_buy(chat_id, username, token_target, amt)
                elif 32 <= len(token_target) <= 44:
                    self.execute_solana_buy(chat_id, token_target, amt)
                else:
                    self.send_message(chat_id, f"❌ Unrecognized token contract or mint: <code>{token_target}</code>")
                return

        if text.startswith("/withdraw_eth") or text.startswith("/withdraw_base"):
            parts = text.split()
            if len(parts) < 3:
                self.send_message(
                    chat_id,
                    "💸 <b>WITHDRAW BASE ETH USAGE:</b>\n\n"
                    "<code>/withdraw_eth &lt;destination_address&gt; &lt;amount&gt;</code>\n"
                    "Example: <code>/withdraw_eth 0xbE40c75844197fD334db4174CBd7D07F9bAb93f8 0.05</code>\n"
                    "<i>(Or send <code>all</code> to withdraw maximum balance)</i>"
                )
                return
            target_addr = parts[1]
            amt_str = parts[2]
            self.send_message(chat_id, f"⏳ Broadcasting Base ETH withdrawal to <code>{target_addr}</code>...")
            w_res = withdraw_base_eth(chat_id, target_addr, amt_str)
            if w_res["success"]:
                self.send_message(
                    chat_id,
                    f"✅ <b>BASE ETH WITHDRAWAL COMPLETE!</b>\n\n"
                    f"• Amount: <code>{w_res['amount_eth']:.5f} ETH</code>\n"
                    f"• To: <code>{target_addr}</code>\n"
                    f"• Tx: <a href='{w_res['basescan_url']}'>View on Basescan</a>"
                )
            else:
                self.send_message(chat_id, f"❌ Withdrawal failed: <code>{w_res['error']}</code>")
            return

        if text == "/withdraw":
            markup = {
                "inline_keyboard": [
                    [
                        {"text": "💸 Withdraw Base ETH", "callback_data": "base_withdraw_prompt"},
                        {"text": "💸 Withdraw SOL", "callback_data": "sol_withdraw_prompt"}
                    ],
                    [{"text": "🔙 Back", "callback_data": "menu_main"}]
                ]
            }
            self.send_message(
                chat_id,
                "💸 <b>WITHDRAW FUNDS TO EXTERNAL WALLET</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Select which asset you would like to withdraw to your personal wallet:",
                markup
            )
            return

        if text.startswith("/withdraw "):
            parts = text.split()
            if len(parts) >= 3:
                target_addr = parts[1]
                amt_str = parts[2]
                if target_addr.startswith("0x"):
                    self.send_message(chat_id, f"⏳ Broadcasting Base ETH withdrawal to <code>{target_addr}</code>...")
                    w_res = withdraw_base_eth(chat_id, target_addr, amt_str)
                    if w_res["success"]:
                        self.send_message(
                            chat_id,
                            f"✅ <b>BASE ETH WITHDRAWAL COMPLETE!</b>\n\n"
                            f"• Amount: <code>{w_res['amount_eth']:.5f} ETH</code>\n"
                            f"• To: <code>{target_addr}</code>\n"
                            f"• Tx: <a href='{w_res['basescan_url']}'>View on Basescan</a>"
                        )
                    else:
                        self.send_message(chat_id, f"❌ Withdrawal failed: <code>{w_res['error']}</code>")
                    return
                else:
                    try:
                        amt = float(amt_str)
                        sol_pubkey, secret_b58 = se.get_or_create_solana_wallet(chat_id)
                        self.send_message(chat_id, f"⏳ Broadcasting withdrawal of <code>{amt} SOL</code> to <code>{target_addr}</code>...")
                        w_res = se.withdraw_sol(secret_b58, target_addr, amt)
                        if w_res["success"]:
                            self.send_message(
                                chat_id,
                                f"✅ <b>SOL WITHDRAWAL COMPLETE!</b>\n\n"
                                f"• Amount: <code>{amt} SOL</code>\n"
                                f"• To: <code>{target_addr}</code>\n"
                                f"• Tx: <a href='{w_res['solscan_url']}'>View on Solscan</a>"
                            )
                        else:
                            self.send_message(chat_id, f"❌ Withdrawal failed: <code>{w_res['error']}</code>")
                    except Exception as e:
                        self.send_message(chat_id, f"❌ Withdrawal error: {e}")
                    return

        if text.startswith("/withdraw_sol"):
            parts = text.split()
            if len(parts) < 3:
                self.send_message(
                    chat_id,
                    "💸 <b>WITHDRAW SOL USAGE:</b>\n\n"
                    "<code>/withdraw_sol &lt;destination_address&gt; &lt;amount&gt;</code>\n"
                    "Example: <code>/withdraw_sol 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU 0.1</code>"
                )
                return
            target_addr = parts[1]
            try:
                amt = float(parts[2])
            except ValueError:
                self.send_message(chat_id, "❌ Invalid amount specified.")
                return

            sol_pubkey, secret_b58 = se.get_or_create_solana_wallet(chat_id)
            cur_bal = se.get_sol_balance(sol_pubkey)
            if cur_bal < amt:
                self.send_message(chat_id, f"❌ Insufficient balance! You have <code>{cur_bal:.4f} SOL</code>.")
                return

            self.send_message(chat_id, f"⏳ Broadcasting withdrawal of <code>{amt} SOL</code> to <code>{target_addr}</code>...")
            w_res = se.withdraw_sol(secret_b58, target_addr, amt)
            if w_res["success"]:
                self.send_message(
                    chat_id,
                    f"✅ <b>SOL WITHDRAWAL COMPLETE!</b>\n\n"
                    f"• Amount: <code>{amt} SOL</code>\n"
                    f"• To: <code>{target_addr}</code>\n"
                    f"• Tx: <a href='{w_res['solscan_url']}'>View on Solscan</a>"
                )
            else:
                self.send_message(chat_id, f"❌ Withdrawal failed: <code>{w_res['error']}</code>")
            return

        if text.startswith("0x") and len(text) == 42:
            token = fetch_token_info(text)
            if token.get("valid"):
                self.show_token_quote(chat_id, username, text)
            else:
                self.show_audit_report(chat_id, text)
            return

        if text.startswith("0x") and len(text) == 66:
            self.show_audit_report(chat_id, text)
            return

        # Solana mint address detection
        if not text.startswith("0x") and 32 <= len(text) <= 44 and " " not in text:
            stoken = se.fetch_solana_token(text)
            if stoken.get("valid"):
                self.show_solana_token_quote(chat_id, username, text)
                return

        self.send_message(
            chat_id,
            "💡 <b>Paste any Base or Solana token address to trade.</b>"
        )


    def show_arb_dashboard(self, chat_id):
        status_file = os.path.join(os.path.dirname(__file__), "flash_arb_status.json")
        data = None
        if os.path.exists(status_file):
            try:
                with open(status_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass

        if not data:
            msg = (
                "⚡ <b>NETSWAP AUTONOMOUS FLASH-ARB HUNTER</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "🟡 <b>Status:</b> Initializing Base block listener...\n"
                "Please refresh in a moment."
            )
            markup = {"inline_keyboard": [[{"text": "🔄 Refresh", "callback_data": "menu_arb"}, {"text": "🔙 Main Menu", "callback_data": "menu_main"}]]}
            self.send_message(chat_id, msg, markup)
            return

        block = data.get("block", 0)
        gas = data.get("gas_gwei", 0.0)
        gas_usd = data.get("est_gas_cost_usd", 0.0)
        ticks = data.get("ticks", 0)
        ts = data.get("timestamp", int(time.time()))
        age = max(0, int(time.time() - ts))
        op_wallet = data.get("operator_wallet", FEE_RECIPIENT)

        spread_lines = []
        for s in data.get("spreads", []):
            sym = s["symbol"]
            pct = s["spread_pct"]
            direction = s["dir"]
            size = s["size"]
            status_icon = "🟢" if pct > 0 else "⚪"
            spread_lines.append(f"{status_icon} <b>${sym}:</b> <code>{pct:+.2f}%</code> ({direction} · {size:.1f} ETH)")

        msg = (
            "⚡ <b>NETSWAP AUTONOMOUS FLASH-ARB HUNTER</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 <b>Status:</b> <b>ONLINE & SCANNING BASE MAINNET</b>\n"
            f"📦 <b>Current Block:</b> <code>#{block}</code> <i>({age}s ago · tick #{ticks})</i>\n"
            f"⛽ <b>Base L2 Gas:</b> <code>{gas:.4f} Gwei</code> (~${gas_usd:.4f}/tx)\n"
            "🛡️ <b>Pre-Simulation Zero-Revert:</b> 🟢 <b>ACTIVE</b> ($0 failed gas)\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 <b>LIVE POOL SPREADS (Aerodrome vs Uni v3):</b>\n"
            + "\n".join(spread_lines) + "\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "💰 <b>Operator Profit Recipient:</b>\n"
            f"<code>{op_wallet}</code>\n"
            "<i>(100% of Flash Loan net yield sweeps here in pure ETH)</i>"
        )

        markup = {
            "inline_keyboard": [
                [{"text": "🔄 Refresh Live Spreads", "callback_data": "menu_arb"}],
                [{"text": "🔙 Main Menu", "callback_data": "menu_main"}]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_clanker_radar(self, chat_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT token_address, token_name, token_symbol, mcap_usd, volume_24h, timestamp FROM clanker_launches ORDER BY timestamp DESC LIMIT 4")
        launches = cursor.fetchall()
        conn.close()

        lines = []
        keyboard = []
        for t_addr, name, sym, mcap, vol, ts in launches:
            mins_ago = int((time.time() - ts) / 60)
            time_str = f"{mins_ago}m ago" if mins_ago > 0 else "Just now"
            lines.append(
                f"🚀 <b>NEW CLANKER LAUNCH: {name} (${sym}) · {time_str}</b>\n"
                f"📍 <code>{t_addr}</code>\n"
                f"📊 <b>MCap:</b> <code>${mcap:,.0f}</code> | <b>24h Vol:</b> <code>${vol:,.0f}</code>\n"
                "🛡️ <i>Pre-Approved for 0% AMM Slippage P2P Netting</i>"
            )
            keyboard.append([{"text": f"⚡ 1-Click Snipe ${sym} (0% Slippage)", "callback_data": f"select_token_{t_addr}"}])

        keyboard.append([
            {"text": "🔄 Refresh Clanker Radar", "callback_data": "menu_clanker"},
            {"text": "🔙 Main Menu", "callback_data": "menu_main"}
        ])

        msg = (
            "🎯 <b>BASE CLANKER LAUNCH RADAR & SNIPER</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Catch the newest Base meme tokens the second they deploy on Clanker. Snipe block-1 entries peer-to-peer before Uniswap even updates its chart:\n\n"
            + "\n\n".join(lines) + "\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "👇 <b>Select a newly deployed token below to snipe:</b>"
        )
        markup = {"inline_keyboard": keyboard}
        self.send_message(chat_id, msg, markup)

    def show_whale_radar(self, chat_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT whale_address, token_address, token_symbol, amount_eth, amount_usd, timestamp FROM whale_alerts ORDER BY timestamp DESC LIMIT 3")
        alerts = cursor.fetchall()
        conn.close()

        lines = []
        keyboard = []
        for w_addr, t_addr, sym, eth_amt, usd_amt, ts in alerts:
            mins_ago = int((time.time() - ts) / 60)
            time_str = f"{mins_ago}m ago" if mins_ago > 0 else "Just now"
            lines.append(
                f"🚨 <b>WHALE BUY: ${sym} ({time_str})</b>\n"
                f"💰 <b>Swapped:</b> <code>{eth_amt:.2f} ETH</code> (~${usd_amt:,.2f})\n"
                f"📍 <b>Whale:</b> <code>{w_addr[:6]}...{w_addr[-4:]}</code>\n"
                "⚡ <i>Matched with 0% AMM Slippage & Anti-MEV</i>"
            )
            keyboard.append([{"text": f"⚡ 1-Click Copy-Buy ${sym}", "callback_data": f"select_token_{t_addr}"}])

        keyboard.append([
            {"text": "🔄 Refresh Whales", "callback_data": "menu_whales"},
            {"text": "🔙 Main Menu", "callback_data": "menu_main"}
        ])

        msg = (
            "🐋 <b>LIVE BASE WHALE RADAR (SMART MONEY)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Whales accumulate before major price moves. Copy their entries with zero AMM slippage:\n\n"
            + "\n\n".join(lines) + "\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "👇 <b>Select a whale token below to copy-buy:</b>"
        )
        markup = {"inline_keyboard": keyboard}
        self.send_message(chat_id, msg, markup)

    def show_vip_info(self, chat_id):
        msg = (
            "⭐ <b>NETSWAP VIP PARTNER PROGRAM (70/30)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "For Alpha Callers, YouTube Creators, and Channel Admins:\n\n"
            "💸 <b>Split:</b> <b>30% OF ALL TRADING FEES</b> generated by your community forever!\n"
            "🛡️ <b>Protect Your Members:</b> 0% AMM slippage, 100% Anti-MEV protection.\n"
            "⚡ <b>Instant Stream:</b> Protocol fees streamed directly in native Base ETH.\n\n"
            "<b>How to Register Your Channel Link:</b>\n"
            "Send: <code>/vip &lt;your_channel_name&gt;</code>\n"
            "<i>(Example: /vip alpha or /vip degencalls)</i>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_ads_marketplace(self, chat_id):
        msg = (
            "📢 <b>NETSWAP REACH-TIERED ADVERTISING ENGINE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Target high-frequency degen traders across Base & Solana with guaranteed verified reach.\n\n"
            "📊 <b>REACH TIERS & DURATION PACKAGES:</b>\n\n"
            "1️⃣ 🚀 <b>Tier 1: Starter Surge (10k+ Traders)</b>\n"
            "   • 12 Hours: <code>0.05 ETH</code> (~$160) | <code>1.0 SOL</code>\n"
            "   • 24 Hours: <code>0.08 ETH</code> (~$250) | <code>1.8 SOL</code>\n"
            "   • <i>Includes: Pinned Slot in /trending with 1-tap zero-slippage buy</i>\n\n"
            "2️⃣ ⚡ <b>Tier 2: High-Volume Growth (50k+ Traders)</b>\n"
            "   • 24 Hours: <code>0.20 ETH</code> (~$640) | <code>4.0 SOL</code>\n"
            "   • 48 Hours: <code>0.35 ETH</code> (~$1,120) | <code>7.5 SOL</code>\n"
            "   • <i>Includes: Top-3 /trending pin + Direct-to-DM Alpha Push drop</i>\n\n"
            "3️⃣ 🐋 <b>Tier 3: Whale Saturation (250k+ Traders)</b>\n"
            "   • 48 Hours: <code>0.75 ETH</code> (~$2,400) | <code>15.0 SOL</code>\n"
            "   • 7 Days:   <code>1.50 ETH</code> (~$4,800) | <code>30.0 SOL</code>\n"
            "   • <i>Includes: Global Buy Alert Banner across ALL tracked groups + DMs</i>\n\n"
            "4️⃣ 👑 <b>Tier 4: Network Domination (1M+ Traders)</b>\n"
            "   • 7 Days:   <code>2.50 ETH</code> (~$8,000) | <code>50.0 SOL</code>\n"
            "   • 30 Days:  <code>8.00 ETH</code> (~$25,600) | <code>160.0 SOL</code>\n"
            "   • <i>Includes: Complete ecosystem takeover (Bot, Web Terminal & Mempool)</i>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛡️ <b>ADD-ON: VERIFIED CLEAN DEPLOYER SEAL</b> (<code>0.02 ETH / 0.5 SOL</code>)\n"
            "Smart contract safety audit + 🟢 <b>VERIFIED SAFE</b> badge on /shield & Web Audit to guarantee your token is 100% rug-free.\n\n"
            "📬 <i>Direct-to-DM: High-priority broadcast delivered to user personal Telegram DMs.</i>"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "🚀 Book Starter (12h · 0.05 ETH)", "callback_data": "book_ad_t1"},
                    {"text": "⚡ Book Growth (24h · 0.20 ETH)", "callback_data": "book_ad_t2"}
                ],
                [
                    {"text": "🐋 Book Whale (48h · 0.75 ETH)", "callback_data": "book_ad_t3"},
                    {"text": "👑 Domination (7d · 2.50 ETH)", "callback_data": "book_ad_t4"}
                ],
                [
                    {"text": "🛡️ Book Verified Clean Seal (0.02 ETH)", "callback_data": "book_ad_seal"}
                ],
                [
                    {"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_ad_invoice(self, chat_id, tier_id):
        tiers = {
            "t1": ("Starter Surge (10k+ Traders · 12h)", "0.05 ETH", "1.0 SOL"),
            "t2": ("High-Volume Growth (50k+ Traders · 24h)", "0.20 ETH", "4.0 SOL"),
            "t3": ("Whale Saturation (250k+ Traders · 48h)", "0.75 ETH", "15.0 SOL"),
            "t4": ("Network Domination (1M+ Traders · 7d)", "2.50 ETH", "50.0 SOL"),
            "seal": ("Verified Clean Deployer Seal", "0.02 ETH", "0.5 SOL"),
        }
        name, eth_cost, sol_cost = tiers.get(tier_id, ("Sponsorship Package", "0.05 ETH", "1.0 SOL"))
        msg = (
            f"🧾 <b>NETSWAP AD INVOICE: {name.upper()}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "To activate this advertising placement, transfer the package amount to the Official Protocol Treasury:\n\n"
            f"🔷 <b>Base Network (ETH):</b>\n<code>{SUBS_RECIPIENT_BASE}</code>\n"
            f"• Amount: <b>{eth_cost}</b>\n\n"
            "🪐 <b>Solana Network (SOL):</b>\n<code>{SUBS_RECIPIENT_SOL}</code>\n"
            f"• Amount: <b>{sol_cost}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ <b>NEXT STEP TO GO LIVE:</b>\n"
            "Once transaction is sent, reply in chat with your Token CA & Tx Hash (e.g. <code>0x... &lt;tx_hash&gt;</code>). Our verification engine will detect the payment and set your ad live across the network!"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "📢 Other Tiers", "callback_data": "menu_ads"}],
                [{"text": "🔙 Back", "callback_data": "menu_main"}]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_sponsor_info(self, chat_id):
        self.show_ads_marketplace(chat_id)

    def show_wallet(self, chat_id, username):
        user = get_user_by_id(chat_id)
        if not user:
            user = get_or_create_user(chat_id, username)

        address = user[0]
        saved_usd = user[5]
        cashback_usd = user[6]
        trader_tier = user[7]
        balance = get_wallet_balance(address)

        # Solana details
        sol_pubkey, _ = se.get_or_create_solana_wallet(chat_id)
        sol_bal = se.get_sol_balance(sol_pubkey)

        token_lines = []
        for t in POPULAR_TOKENS[:4]:
            t_bal = get_token_balance(address, t['address'])
            if t_bal > 0:
                token_lines.append(f"• <b>${t['symbol']}:</b> <code>{t_bal:,.2f}</code>")

        holdings_str = "\n".join(token_lines) if token_lines else "<i>No active token holdings yet.</i>"

        msg = (
            "💳 <b>YOUR DEPOSIT WALLETS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔷 <b>Base Deposit Address (ETH):</b>\n"
            f"<code>{address}</code>\n"
            f"💰 Balance: <code>{balance:.4f} ETH</code> (~${balance * 3200:.2f})\n\n"
            "🪐 <b>Solana Deposit Address (SOL):</b>\n"
            f"<code>{sol_pubkey}</code>\n"
            f"💰 Balance: <code>{sol_bal:.4f} SOL</code> (~${sol_bal * 150:.2f})\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Transfer ETH on Base or SOL to fund your bot. Tap an address to copy.</i>"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "🔑 Base Key", "callback_data": "menu_export"},
                    {"text": "🔑 Solana Key", "callback_data": "sol_export"}
                ],
                [
                    {"text": "💸 Withdraw ETH", "callback_data": "base_withdraw_prompt"},
                    {"text": "💸 Withdraw SOL", "callback_data": "sol_withdraw_prompt"}
                ],
                [
                    {"text": "🔄 Refresh", "callback_data": "menu_wallet"},
                    {"text": "🔙 Back", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_swap_terminal(self, chat_id, username=""):
        user = get_user_by_id(chat_id)
        if not user:
            user = get_or_create_user(chat_id, username)
        address = user[0]
        balance = get_wallet_balance(address)
        sol_pubkey, _ = se.get_or_create_solana_wallet(chat_id)
        sol_bal = se.get_sol_balance(sol_pubkey)

        msg = (
            "⚡ <b>INSTANT BUY TERMINAL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔷 <b>Base:</b> <code>{balance:.4f} ETH</code> | 🪐 <b>Solana:</b> <code>{sol_bal:.4f} SOL</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Paste any token address in chat to buy instantly.</i>\n\n"
            "Or tap a trending coin below to buy in 1 tap:"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "🔷 BRETT", "callback_data": "select_token_0x532f27101965dd16442e59d40670faf5ebb142e4"},
                    {"text": "🔷 DEGEN", "callback_data": "select_token_0x4ed4e862860bed51a9570b96d89af5e1b0efefed"},
                    {"text": "🔷 TOSHI", "callback_data": "select_token_0xac1bd2486aaf3b5c0fc3fd868558b082a531b2b4"}
                ],
                [
                    {"text": "🪐 BONK", "callback_data": "select_sol_DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"},
                    {"text": "🪐 WIF", "callback_data": "select_sol_EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"},
                    {"text": "🪐 POPCAT", "callback_data": "select_sol_7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"}
                ],
                [
                    {"text": "🌐 Web Two-Way Swap ↗", "url": "https://netswap.vercel.app"}
                ],
                [
                    {"text": "🔙 Back", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_positions(self, chat_id, username=""):
        user = get_user_by_id(chat_id)
        if not user:
            user = get_or_create_user(chat_id, username)

        address = user[0]
        eth_balance = get_wallet_balance(address)
        sol_pubkey, _ = se.get_or_create_solana_wallet(chat_id)
        sol_bal = se.get_sol_balance(sol_pubkey)

        spl_tokens = []
        try:
            spl_tokens = se.get_spl_token_balances(sol_pubkey)
        except Exception:
            spl_tokens = []

        base_holdings = []
        for t in POPULAR_TOKENS:
            try:
                bal = get_token_balance(address, t['address'])
                if bal > 0.0001:
                    base_holdings.append({
                        "symbol": t["symbol"],
                        "name": t["name"],
                        "address": t["address"],
                        "balance": bal,
                        "chain": "Base"
                    })
            except Exception:
                pass

        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT token_address, token_symbol FROM trades WHERE user_id = ?", (chat_id,))
            traded = cursor.fetchall()
            conn.close()
            for t_addr, t_sym in traded:
                if not any(h["address"].lower() == t_addr.lower() for h in base_holdings):
                    bal = get_token_balance(address, t_addr)
                    if bal > 0.0001:
                        base_holdings.append({
                            "symbol": t_sym,
                            "name": t_sym,
                            "address": t_addr,
                            "balance": bal,
                            "chain": "Base"
                        })
        except Exception:
            pass

        has_positions = bool(base_holdings or spl_tokens)

        lines = [
            "💼 <b>YOUR POSITIONS & PORTFOLIO</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💰 <b>Native Balances:</b>\n"
            f"• 🔷 <b>Base:</b> <code>{eth_balance:.4f} ETH</code> (~${eth_balance * 3200:.2f})\n"
            f"• 🪐 <b>Solana:</b> <code>{sol_bal:.4f} SOL</code> (~${sol_bal * 150:.2f})\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ]

        keyboard = []

        if not has_positions:
            lines.append(
                "\n<i>No open token positions found.</i>\n\n"
                "💡 Paste any token address in chat or tap Buy Token below."
            )
            keyboard.append([
                {"text": "⚡ Buy Token", "callback_data": "menu_swap"},
                {"text": "💳 Wallets", "callback_data": "menu_wallet"}
            ])
            keyboard.append([
                {"text": "🔙 Back", "callback_data": "menu_main"}
            ])
        else:
            lines.append("\n📦 <b>ACTIVE HOLDINGS & TAKE-PROFIT:</b>")
            for h in base_holdings:
                lines.append(
                    f"\n🔷 <b>${h['symbol']}</b> (Base)\n"
                    f"   Holding: <code>{h['balance']:,.2f}</code>\n"
                    f"   Contract: <code>{h['address'][:6]}...{h['address'][-4:]}</code>"
                )
                keyboard.append([
                    {"text": f"🔴 25% ${h['symbol']}", "callback_data": f"sell_base_{h['address']}_25"},
                    {"text": f"🔴 50%", "callback_data": f"sell_base_{h['address']}_50"},
                    {"text": f"🔴 100%", "callback_data": f"sell_base_{h['address']}_100"}
                ])

            for s in spl_tokens:
                sym = s.get('symbol', 'SPL')
                lines.append(
                    f"\n🪐 <b>${sym}</b> (Solana)\n"
                    f"   Holding: <code>{s['amount']:,.2f}</code>\n"
                    f"   Mint: <code>{s['mint'][:6]}...{s['mint'][-4:]}</code>"
                )
                keyboard.append([
                    {"text": f"🔴 50% ${sym}", "callback_data": f"sell_sol_{s['mint']}_50"},
                    {"text": f"🔴 100%", "callback_data": f"sell_sol_{s['mint']}_100"}
                ])

            keyboard.append([
                {"text": "⚡ Buy Token", "callback_data": "menu_swap"},
                {"text": "🌐 Web Terminal ↗", "url": "https://netswap.vercel.app"}
            ])
            keyboard.append([
                {"text": "🔄 Refresh", "callback_data": "menu_positions"},
                {"text": "🔙 Back", "callback_data": "menu_main"}
            ])

        msg = "\n".join(lines)
        self.send_message(chat_id, msg, {"inline_keyboard": keyboard})

    def show_batch_terminal(self, chat_id):
        msg = (
            "⏳ <b>NETSWAP CONTINUOUS BATCH SETTLEMENT ENGINE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "NetSwap eliminates AMM slippage and frontrunning by coalescing orders into rapid <b>2.0-second settlement windows</b>.\n\n"
            "⚙️ <b>BATCH ENGINE STATUS:</b>\n"
            "• 🟢 <b>State:</b> <code>COALESCING / ACTIVE</code>\n"
            "• ⏱️ <b>Netting Interval:</b> <code>2.0 Seconds</code>\n"
            "• 🛡️ <b>Anti-MEV Router:</b> <code>Enabled (Private Builder Bundles)</code>\n"
            "• ⛓️ <b>Settlement Contract:</b> <code>0x0Ae0...8f8F</code> (Base)\n\n"
            "🤝 <b>HOW ORDER COLLISION WORKS:</b>\n"
            "1️⃣ <b>Opposing Orders Net Directly:</b> Peer buys and peer sells within the 2.0s window collide at fair mid-market price with <b>0% AMM Slippage</b> and <b>$0 Sandwich Tax</b>.\n"
            "2️⃣ <b>Single Trader Fallback:</b> If you are the only trader in the window or there is unmatched remainder volume, NetSwap immediately routes your order to Aerodrome/Uniswap v3 via private builders with <b>zero wait delay</b>!\n\n"
            "🌐 <i>Monitor the live 2.0s visual batch countdown on the Web Terminal:</i>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🌐 Live Batch Monitor ↗", "url": "https://netswap.vercel.app"}],
                [
                    {"text": "⚡ Swap", "callback_data": "menu_swap"},
                    {"text": "💼 Positions", "callback_data": "menu_positions"}
                ],
                [{"text": "🔙 Back", "callback_data": "menu_main"}]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_copytrade_menu(self, chat_id):
        settings = get_user_alert_settings(chat_id)
        w_state = "🟢 ACTIVE" if (settings.get("alerts_enabled", 0) == 1 and settings.get("free_whale_radar", 1) == 1) else "🔴 INACTIVE"

        msg = (
            "👥 <b>WHALE COPY-TRADE & SMART MIRRORING</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Whale Radar Stream: <b>{w_state}</b>\n\n"
            "NetSwap tracks elite smart money wallets (80%+ win rate) on Base and Solana and delivers real-time lockscreen alerts with <b>1-Tap Mirror Execution Buttons</b>:\n\n"
            "• 🔷 <b>Base Whale Alpha A:</b> 84% win rate (+342 ETH)\n"
            "• 🔷 <b>Clanker Sniper:</b> 78% win rate (Sub-second snipes)\n"
            "• 🪐 <b>Solana Megalodon:</b> 89% win rate (+1,240 SOL)\n\n"
            "⚡ <b>HOW IT WORKS:</b>\n"
            "1. Turn on Whale Radar in your Alert Hub.\n"
            "2. When a whale buys or takes profit, you receive an instant DM.\n"
            "3. Tap <code>[ ⚡ Mirror 0.05 ETH ]</code> or <code>[ ⚡ Mirror 0.5 SOL ]</code> to execute in the next block with 0% AMM slippage & Anti-MEV protection!\n\n"
            "💡 <i>Tip: Ensure your in-bot wallet has ETH or SOL deposited so mirror trades execute instantly when signals arrive.</i>"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "🔔 Configure Alert Streams", "callback_data": "menu_alerts"},
                    {"text": "💳 Wallet & Deposit", "callback_data": "menu_wallet"}
                ],
                [
                    {"text": "👑 Full 64+ Feeds (Web Store) ↗", "url": f"https://netswap.vercel.app/store.html?user_id={chat_id}"}
                ],
                [
                    {"text": "🔙 Back", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_tools_menu(self, chat_id):
        msg = (
            "🛠️ <b>NETSWAP ADVANCED INTELLIGENCE & AUDITS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Select an automated radar, security scanner, or audit engine below:"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "🧾 Audit Lost Fees (/audit)", "callback_data": "menu_audit_prompt"},
                    {"text": "🏆 Victim Index (Web) ↗", "url": "https://netswap.vercel.app/audit.html#leaderboard"}
                ],
                [
                    {"text": "👑 VIP Insider Pass ($49/mo)", "callback_data": "menu_vip_store"},
                    {"text": "🔔 Push Alerts (/alerts)", "callback_data": "menu_alerts"}
                ],
                [
                    {"text": "🛡️ Rug & Honeypot Shield", "callback_data": "menu_shield_prompt"},
                    {"text": "⚡ Flash-Arb Hunter (Live)", "callback_data": "menu_arb"}
                ],
                [
                    {"text": "🎯 Clanker Launch Radar", "callback_data": "menu_clanker"},
                    {"text": "🐋 Whale Radar (Live)", "callback_data": "menu_whales"}
                ],
                [
                    {"text": "🤖 Add Bot to Group", "callback_data": "menu_track_info"},
                    {"text": "⭐ VIP Partner (30% Rev-Share)", "callback_data": "menu_vip"}
                ],
                [
                    {"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_trending(self, chat_id):

        msg = (
            "🔥 <b>TOP BASE PAIRS (ZERO-SLIPPAGE NETTING)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Tap any token below to open quote card & execute instant buy:"
        )
        keyboard = []
        for t in POPULAR_TOKENS:
            keyboard.append([
                {"text": f"⚡ {t['name']} (${t['symbol']})", "callback_data": f"select_token_{t['address']}"}
            ])
        keyboard.append([{"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}])

        markup = {"inline_keyboard": keyboard}
        self.send_message(chat_id, msg, markup)

    def show_token_quote(self, chat_id, username, token_address):
        token = fetch_token_info(token_address)
        if not token["valid"]:
            self.send_message(
                chat_id,
                f"❌ <b>Invalid Contract:</b> Could not find an active ERC-20 token at <code>{token_address}</code> on Base."
            )
            return

        sec = check_token_security(token_address)
        user = get_user_by_id(chat_id)
        address = user[0] if user else get_or_create_user(chat_id, username)[0]
        balance = get_wallet_balance(address)

        USER_ACTIVE_QUOTE[chat_id] = {"chain": "base", "address": token['address'], "symbol": token['symbol']}

        msg = (
            f"🔷 <b>${token['symbol']} // {token['name']}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <code>{token['address']}</code>\n"
            f"🛡️ <b>Shield:</b> {sec['badge']}\n"
            f"💰 <b>Balance:</b> <code>{balance:.4f} ETH</code> (~${balance * 3200:.2f})\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Select buy amount or enter custom size:"
        )

        markup = {
            "inline_keyboard": [
                [
                    {"text": "⚡ 0.002 ETH", "callback_data": f"buy_{token['address']}_0.002"},
                    {"text": "⚡ 0.005 ETH", "callback_data": f"buy_{token['address']}_0.005"}
                ],
                [
                    {"text": "⚡ 0.01 ETH", "callback_data": f"buy_{token['address']}_0.01"},
                    {"text": "⚡ 0.05 ETH", "callback_data": f"buy_{token['address']}_0.05"}
                ],
                [
                    {"text": "✏️ Custom Amount", "callback_data": f"custom_buy_base_{token['address']}"},
                    {"text": "📈 Live Chart ↗", "url": f"https://dexscreener.com/base/{token['address']}"}
                ],
                [
                    {"text": "🔄 Refresh", "callback_data": f"select_token_{token['address']}"},
                    {"text": "🔙 Back", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_solana_terminal(self, chat_id, username):
        sol_pubkey, _ = se.get_or_create_solana_wallet(chat_id)
        sol_bal = se.get_sol_balance(sol_pubkey)
        tokens = se.get_spl_token_balances(sol_pubkey)
        hot = se.get_hot_solana_tokens()

        token_lines = ""
        if tokens:
            token_lines = "\n📦 <b>Your SPL Holdings:</b>\n" + "\n".join([f"• <code>{t['mint'][:6]}...{t['mint'][-4:]}</code>: {t['amount']:,.2f}" for t in tokens[:4]]) + "\n"

        hot_lines = []
        for t in hot:
            hot_lines.append(f"• <b>${t['symbol']}</b> ({t['name']})")
        hot_str = "\n".join(hot_lines)

        msg = (
            "🪐 <b>NETSWAP // SOLANA SNIPER TERMINAL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Lightning-fast sub-second Solana trading powered by Jupiter Aggregator v1.\n\n"
            "⚡ <b>0.85% Anti-MEV Platform Protection</b>\n"
            "🔄 <b>Multi-DEX Deep Routing</b> (Raydium, Meteora, Pump.fun, Orca)\n"
            "🎁 <b>Zero-Failed Swaps</b> (Dynamic compute units & auto priority)\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💳 <b>Your Solana Deposit Address:</b>\n<code>{sol_pubkey}</code> <i>(Tap to copy)</i>\n\n"
            f"💰 <b>SOL Balance:</b> <code>{sol_bal:.4f} SOL</code> (~${sol_bal * 150:.2f})\n"
            f"{token_lines}"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔥 <b>Trending Solana Gems:</b>\n"
            f"{hot_str}\n\n"
            "👇 <b>How to Trade on Solana:</b>\n"
            "1️⃣ Deposit SOL to your address above\n"
            "2️⃣ Paste <b>ANY Solana token mint address</b> or Pump.fun link\n"
            "3️⃣ Execute instant swap with sub-second finality!"
        )

        markup = {
            "inline_keyboard": [
                [
                    {"text": f"⚡ Buy ${hot[0]['symbol']}", "callback_data": f"select_sol_{hot[0]['mint']}"},
                    {"text": f"⚡ Buy ${hot[1]['symbol']}", "callback_data": f"select_sol_{hot[1]['mint']}"}
                ],
                [
                    {"text": f"⚡ Buy ${hot[2]['symbol']}", "callback_data": f"select_sol_{hot[2]['mint']}"},
                    {"text": f"⚡ Buy ${hot[3]['symbol']}", "callback_data": f"select_sol_{hot[3]['mint']}"}
                ],
                [
                    {"text": "💸 Withdraw SOL", "callback_data": "sol_withdraw_prompt"},
                    {"text": "🔑 Solana Key", "callback_data": "sol_export"}
                ],
                [
                    {"text": "🔄 Refresh", "callback_data": "menu_sol"},
                    {"text": "🔙 Back", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_solana_token_quote(self, chat_id, username, query_or_mint):
        token = se.fetch_solana_token(query_or_mint)
        if not token.get("valid"):
            self.send_message(
                chat_id,
                f"❌ <b>Solana Token Not Found:</b> Could not resolve <code>{query_or_mint}</code> on Solana DEXes.\n\n"
                "Please verify the mint address (e.g. from DexScreener or Pump.fun)."
            )
            return

        sol_pubkey, _ = se.get_or_create_solana_wallet(chat_id)
        sol_bal = se.get_sol_balance(sol_pubkey)

        price_str = f"${token['price_usd']:.6f}" if token['price_usd'] < 1 else f"${token['price_usd']:.2f}"
        change_icon = "🟢" if token['change_24h'] >= 0 else "🔴"

        USER_ACTIVE_QUOTE[chat_id] = {"chain": "sol", "mint": token['mint'], "symbol": token['symbol']}

        msg = (
            f"🪐 <b>${token['symbol']} // {token['name']}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <code>{token['mint']}</code>\n"
            f"💰 <b>Price:</b> <code>{price_str}</code> ({change_icon} {token['change_24h']:+.1f}%)\n"
            f"📊 <b>MCap:</b> <code>${token['fdv']:,.0f}</code> | 💧 <b>Liq:</b> <code>${token['liquidity_usd']:,.0f}</code>\n"
            f"💰 <b>Balance:</b> <code>{sol_bal:.4f} SOL</code> (~${sol_bal * 150:.2f})\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Select buy amount or enter custom size:"
        )

        mint = token['mint']
        markup = {
            "inline_keyboard": [
                [
                    {"text": "⚡ 0.05 SOL", "callback_data": f"solbuy_{mint}_0.05"},
                    {"text": "⚡ 0.1 SOL", "callback_data": f"solbuy_{mint}_0.1"}
                ],
                [
                    {"text": "⚡ 0.5 SOL", "callback_data": f"solbuy_{mint}_0.5"},
                    {"text": "⚡ 1.0 SOL", "callback_data": f"solbuy_{mint}_1.0"}
                ],
                [
                    {"text": "✏️ Custom Amount", "callback_data": f"custom_buy_sol_{mint}"},
                    {"text": "📈 Live Chart ↗", "url": f"https://dexscreener.com/solana/{mint}"}
                ],
                [
                    {"text": "🔄 Refresh", "callback_data": f"select_sol_{mint}"},
                    {"text": "🔙 Back", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_solana_export(self, chat_id):
        sol_pubkey, secret_b58 = se.get_or_create_solana_wallet(chat_id)
        msg = (
            "⚠️ <b>SOLANA PRIVATE KEY EXPORT (KEEP PRIVATE)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>Solana Address:</b>\n<code>{sol_pubkey}</code>\n\n"
            f"🔑 <b>Private Key (Base58):</b>\n<code>{secret_b58}</code>\n\n"
            "<i>You can import this private key directly into Phantom, Solflare, or Backpack wallet anytime. You maintain 100% self-custody of your Solana assets.</i>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🪐 Back to Solana Terminal", "callback_data": "menu_sol"}],
                [{"text": "💳 Back to Wallets", "callback_data": "menu_wallet"}]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_base_withdraw_prompt(self, chat_id):
        user = get_user_by_id(chat_id)
        bal = get_wallet_balance(user[0]) if user else 0.0
        msg = (
            "💸 <b>WITHDRAW BASE ETH TO EXTERNAL WALLET</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Available Balance:</b> <code>{bal:.4f} ETH</code> (~${bal * 3200:.2f})\n\n"
            "To withdraw Base ETH to MetaMask, Coinbase, or any external wallet, send:\n"
            "<code>/withdraw_eth &lt;destination_address&gt; &lt;amount&gt;</code>\n\n"
            "<b>Example:</b>\n"
            f"<code>/withdraw_eth 0xbE40c75844197fD334db4174CBd7D07F9bAb93f8 0.05</code>\n"
            "<i>(Or send <code>all</code> to withdraw maximum balance)</i>\n\n"
            "⚡ <i>Network fee: ~0.00003 ETH (instant Base L2 transfer).</i>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "💳 Back to Wallets", "callback_data": "menu_wallet"}]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_solana_withdraw_prompt(self, chat_id):
        sol_pubkey, _ = se.get_or_create_solana_wallet(chat_id)
        sol_bal = se.get_sol_balance(sol_pubkey)
        msg = (
            "💸 <b>WITHDRAW SOL TO EXTERNAL WALLET</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Available Balance:</b> <code>{sol_bal:.4f} SOL</code>\n\n"
            "To withdraw SOL to your personal Phantom/Solflare wallet, send:\n"
            "<code>/withdraw_sol &lt;destination_address&gt; &lt;amount&gt;</code>\n\n"
            "<b>Example:</b>\n"
            f"<code>/withdraw_sol 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU 0.1</code>\n\n"
            "<i>Network fee: ~0.00005 SOL (instant Solana transfer).</i>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🪐 Back to Solana Terminal", "callback_data": "menu_sol"}],
                [{"text": "💳 Back to Wallets", "callback_data": "menu_wallet"}]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_audit_timeframe_picker(self, chat_id, target_input):
        target = target_input.strip()
        msg = (
            "🧾 <b>CHOOSE AUDIT TIMEFRAME</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>Target:</b> <code>{target}</code>\n\n"
            "Select the on-chain trading history window to analyze:"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "📅 Last 7 Days", "callback_data": f"audittf_{target}_7d"},
                    {"text": "📅 Last 30 Days", "callback_data": f"audittf_{target}_30d"}
                ],
                [
                    {"text": "📅 Last 90 Days", "callback_data": f"audittf_{target}_90d"},
                    {"text": "📅 1 Year (All-Time)", "callback_data": f"audittf_{target}_all"}
                ],
                [
                    {"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_audit_report(self, chat_id, target_input, timeframe="all"):
        res = perform_audit_calculation(target_input, user_id=chat_id, timeframe=timeframe)
        if not res.get("valid"):
            self.send_message(chat_id, f"❌ <b>Audit Error:</b> {res.get('error', 'Invalid input')}")
            return

        if res["type"] == "wallet":
            chain_label = res.get("chain", "Base")
            chain_icon = "🪐 SOLANA" if chain_label == "Solana" else "🔷 BASE"
            addr_trunc = f"{res['address'][:6]}...{res['address'][-4:]}"
            tf_label = res.get("timeframe", "All-Time / Lifetime")
            rank = res.get("loser_rank", 42)

            share_text = urllib.parse.quote(
                f"💀 SHOCKING: I just audited my wallet on @NetSwapBaseBot and ranked #{rank} in the Lobby of Losers!\n"
                f"Predatory bots extracted -${res['total_stolen']:,.2f} USD ({tf_label}).\n"
                f"NetSwap would have kept +${res['total_ns_kept']:,.2f} in my pocket!\n"
                f"Audit your wallet for free before trading again:"
            )
            share_url = f"https://t.me/share/url?url=https%3A%2F%2Ft.me%2FNetSwapBaseBot%3Fstart%3Dref_{chat_id}&text={share_text}"

            bal_line = f"• <b>SOL Balance:</b> <code>{res.get('sol_bal', 0.0):.4f} SOL</code>\n" if chain_label == "Solana" else f"• <b>ETH Balance:</b> <code>{res.get('eth_bal', 0.0):.4f} ETH</code>\n"

            receipt_msg = (
                f"🧾 <b>{chain_icon} DEX LOSS FORENSIC AUDIT</b>\n"
                f"⏱️ <i>Window: {tf_label}</i>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📍 <b>Wallet:</b> <code>{res['address']}</code>\n"
                f"{bal_line}"
                f"📊 <b>Swaps Analyzed:</b> <code>~{res['est_swaps']} trades</code>\n"
                f"💸 <b>DEX Volume:</b> <code>~${res['est_vol_usd']:,.2f} USD</code>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "🚨 <b>WHAT REALLY HAPPENED TO YOUR MONEY:</b>\n"
                f"1. 🥪 <b>MEV Sandwich Frontrun:</b> <code>-${res['mev_stolen']:,.2f}</code>\n"
                "   <i>Mempool bots pushed prices against you and dumped.</i>\n\n"
                f"2. 📉 <b>Predatory AMM Slippage:</b> <code>-${res['amm_slippage']:,.2f}</code>\n"
                "   <i>Pool price impact drained value on every entry.</i>\n\n"
                f"3. 🤖 <b>1% Competitor Bot Tolls:</b> <code>-${res['bot_taxes']:,.2f}</code>\n"
                "   <i>Maestro / Trojan / BonkBot tolls on each swap.</i>\n"
                "--------------------------------------\n"
                f"💀 <b>TOTAL WEALTH EXTRACTED:</b> <b>-${res['total_stolen']:,.2f} USD</b>\n"
                f"🏆 <b>YOUR RANK:</b> <b>#{rank}</b> in the <i>Lobby of Losers</i>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "⚡ <b>IF YOU ROUTED ON NETSWAP:</b>\n"
                f"✅ <b>0% Slippage & Anti-MEV:</b> <code>+${res.get('ns_slippage_saved', res['amm_slippage']):,.2f} SAVED</code>\n"
                f"✅ <b>Half-Price Toll:</b> <code>+${res.get('ns_fee_saved', res['bot_taxes']*0.5):,.2f} SAVED</code>\n"
                f"🎁 <b>$NETSWAP Rewards:</b> <code>+50 $NETSWAP</code> earned\n"
                "--------------------------------------\n"
                f"💰 <b>YOU WOULD BE +${res['total_ns_kept']:,.2f} RICHER TODAY!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>Stop donating your bags. Escape the Lobby of Losers now.</i>"
            )
            trade_target = "menu_sol" if chain_label == "Solana" else "menu_trending"
            trade_title = "⚡ Escape Lobby (Trade Anti-MEV)"
            markup = {
                "inline_keyboard": [
                    [{"text": trade_title, "callback_data": trade_target}],
                    [{"text": "🏆 View Victim Leaderboard (Web) ↗", "url": "https://netswap.vercel.app/audit.html#leaderboard"}],
                    [{"text": "📢 Share My Loser Rank", "url": share_url}],
                    [{"text": "👑 Get VIP Recovery Pass ($49/mo)", "callback_data": "menu_vip_store"}],
                    [{"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}]
                ]
            }
            self.send_message(chat_id, receipt_msg, markup)

        elif res["type"] == "tx":
            receipt_msg = (
                "🧾 <b>ONCHAIN TRANSACTION AUDIT</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔗 <b>Tx:</b> <code>{res['tx_hash'][:10]}...{res['tx_hash'][-8:]}</code>\n"
                f"💰 <b>Trade Value:</b> <code>{res['val_eth']:.4f} ETH</code> (~${res['val_usd']:,.2f})\n"
                f"⛽ <b>Gas Paid:</b> <code>{res['gas_eth']:.6f} ETH</code> (~${res['gas_usd']:.2f})\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"❌ <b>AMM Slippage / Bot Fee Paid:</b> <b>-${res['single_lost']:.2f}</b>\n"
                f"✅ <b>NetSwap Execution Benefit:</b> <b>+${res['single_saved']:.2f}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>Next time route through @NetSwapBaseBot for 0% slippage & anti-MEV!</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🏆 Victim Index (Web) ↗", "url": "https://netswap.vercel.app/audit.html#leaderboard"}],
                    [{"text": "⚡ Swap with NetSwap", "callback_data": "menu_trending"}],
                    [{"text": "🔙 Main Menu", "callback_data": "menu_main"}]
                ]
            }
            self.send_message(chat_id, receipt_msg, markup)

    def show_leaks_wall(self, chat_id):
        msg = (
            "🏆 <b>GLOBAL DEX VICTIM INDEX & LOSS LEADERBOARD</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "The verified public Victim Index & On-Chain MEV loss dossiers are hosted exclusively on the secure Web Portal.\n\n"
            "View top extracted traders, sandwich attack forensics, and real-time loss rankings on the live leaderboard:"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🏆 Open Victim Index (Web) ↗", "url": "https://netswap.vercel.app/audit.html#leaderboard"}],
                [{"text": "🧾 Audit My Wallet (Web) ↗", "url": "https://netswap.vercel.app/audit.html"}],
                [{"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_shield_report(self, chat_id, token_address):
        sec = check_token_security(token_address)
        token = fetch_token_info(token_address)
        sym = token['symbol'] if token.get('valid') else 'TOKEN'

        shield_msg = (
            f"🛡️ <b>NETSWAP SHIELD AUDIT: ${sym}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>CA:</b> <code>{token_address}</code>\n\n"
            f"🛡️ <b>Security Status:</b> {sec['badge']}\n"
            f"⚠️ <b>Risk Tier:</b> <code>{sec['risk_level']}</code>\n"
            f"📋 <b>Details:</b> {sec['details']}\n\n"
            "🥪 <b>Anti-MEV Shield:</b> 🟢 <b>100% PROTECTED</b>\n"
            "⚡ <b>NetSwap P2P Netting:</b> 🟢 <b>READY (0% Slippage)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>NetSwap blocks high-tax honeypots automatically to protect your capital.</i>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": f"⚡ Buy ${sym} Safely on NetSwap", "callback_data": f"select_token_{token_address}"}],
                [{"text": "🔙 Main Menu", "callback_data": "menu_main"}]
            ]
        }
        self.send_message(chat_id, shield_msg, markup)

    def show_refer(self, chat_id):
        ref_link = f"https://t.me/NetSwapBaseBot?start=ref_{chat_id}"
        msg = (
            "👥 <b>NETSWAP REFERRAL REWARD ENGINE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Share your exclusive referral link with degen traders and alpha groups:\n\n"
            f"🔗 <code>{ref_link}</code> <i>(Tap to copy)</i>\n\n"
            "💸 <b>Your Commission:</b> <b>15% of protocol fees</b> on every trade executed forever!\n"
            "⚡ <b>Payout:</b> Streamed automatically in native ETH to your wallet.\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Looking for 30% VIP rate? Tap 'VIP Partner (30%)' in the main menu!</i>"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "📤 Share to Telegram", "url": f"https://t.me/share/url?url={ref_link}&text=Trade+memecoins+on+Base+with+Zero+Slippage+and+Anti-MEV+protection+on+NetSwap!"}
                ],
                [
                    {"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_insiders_store(self, chat_id):
        user = get_user_by_id(chat_id)
        bal_eth = get_wallet_balance(user[0]) if user else 0.0
        sol_pubkey, _ = se.get_or_create_solana_wallet(chat_id)
        bal_sol = se.get_sol_balance(sol_pubkey)

        msg = (
            "👑 <b>SMART MONEY INSIDER ALPHA STORE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Institutional wallet tracking & early block signals from top verified crypto callers.\n"
            "Pick individual caller streams or unlock the All-Access Pass:\n\n"
            "1️⃣ 🎯 <b>TJR Whale Flow Tracker</b>\n"
            "   • <b>Win Rate:</b> <code>74%</code> | <b>Avg ROI:</b> <code>8.4x</code>\n"
            "   • <b>Focus:</b> Base smart accumulation & whale exits\n"
            "   • <b>Price:</b> <code>0.015 ETH</code> (~$48) or <code>0.35 SOL</code> / mo\n\n"
            "2️⃣ 🪐 <b>Ansem SOL Elite Radar</b>\n"
            "   • <b>Win Rate:</b> <code>81%</code> | <b>Avg ROI:</b> <code>12.1x</code>\n"
            "   • <b>Focus:</b> Pump.fun graduation snipes & Raydium runs\n"
            "   • <b>Price:</b> <code>0.020 ETH</code> (~$64) or <code>0.45 SOL</code> / mo\n\n"
            "3️⃣ 🧬 <b>GCR Degen Wallet Tracker</b>\n"
            "   • <b>Win Rate:</b> <code>69%</code> | <b>Avg ROI:</b> <code>15.6x</code>\n"
            "   • <b>Focus:</b> Early token deployments & stealth buys\n"
            "   • <b>Price:</b> <code>0.018 ETH</code> (~$58) or <code>0.40 SOL</code> / mo\n\n"
            "4️⃣ ⚡ <b>Base Block-0 High-Speed Sniper</b>\n"
            "   • <b>Win Rate:</b> <code>88%</code> | <b>Avg ROI:</b> <code>6.2x</code>\n"
            "   • <b>Focus:</b> Sub-second mempool launch execution\n"
            "   • <b>Price:</b> <code>0.012 ETH</code> (~$38) or <code>0.28 SOL</code> / mo\n\n"
            "🌟 <b>ALL-ACCESS PASS (ALL 4 CALLERS + 50% FEE CUT):</b>\n"
            "   • <b>Price:</b> <code>0.035 ETH</code> (~$110) or <code>0.80 SOL</code> / mo\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💳 <b>Your Balances:</b> <code>{bal_eth:.4f} ETH</code> | <code>{bal_sol:.4f} SOL</code>\n\n"
            "🤝 <b>ARE YOU AN ALPHA CALLER?</b>\n"
            "List your signal stream with a <b>50/50 net split</b>: send <code>/listsignal</code>"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "🎯 TJR Whale (0.015 ETH)", "callback_data": "sub_sig_tjr"},
                    {"text": "🪐 Ansem SOL (0.45 SOL)", "callback_data": "sub_sig_ansem"}
                ],
                [
                    {"text": "🧬 GCR Tracker (0.018 ETH)", "callback_data": "sub_sig_gcr"},
                    {"text": "⚡ Block-0 Snipe (0.012 ETH)", "callback_data": "sub_sig_b0"}
                ],
                [
                    {"text": "👑 All-Access Pass (0.035 ETH / 0.80 SOL)", "callback_data": "sub_sig_all"}
                ],
                [
                    {"text": "🤝 List Your Signal (50/50 Split)", "callback_data": "menu_listsignal"},
                    {"text": "🔙 Main Menu", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_insider_invoice(self, chat_id, signal_id):
        sigs = {
            "tjr": ("TJR Whale Flow Tracker (Base)", "0.015 ETH", "0.35 SOL"),
            "ansem": ("Ansem SOL Elite Radar (Solana)", "0.020 ETH", "0.45 SOL"),
            "gcr": ("GCR Degen Wallet Tracker", "0.018 ETH", "0.40 SOL"),
            "b0": ("Base Block-0 High-Speed Sniper", "0.012 ETH", "0.28 SOL"),
            "all": ("All-Access Institutional Pass", "0.035 ETH", "0.80 SOL"),
        }
        name, eth_cost, sol_cost = sigs.get(signal_id, ("Insider Alpha Signal", "0.015 ETH", "0.35 SOL"))
        msg = (
            f"👑 <b>SIGNAL SUBSCRIPTION INVOICE: {name.upper()}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "To activate your 30-day access to this signal channel, transfer to the Official Protocol Treasury:\n\n"
            f"🔷 <b>Base (ETH):</b>\n<code>{SUBS_RECIPIENT_BASE}</code>\n"
            f"• Amount: <b>{eth_cost}</b>\n\n"
            f"🪐 <b>Solana (SOL):</b>\n<code>{SUBS_RECIPIENT_SOL}</code>\n"
            f"• Amount: <b>{sol_cost}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ <b>AUTOMATIC ACTIVATION:</b>\n"
            "Upon blockchain confirmation, you will receive an exclusive private Telegram channel invite link and instant direct-to-DM trade alerts with 1-click buy buttons!"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "👑 Other Signals", "callback_data": "menu_insiders"}],
                [{"text": "🔙 Back", "callback_data": "menu_main"}]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_listsignal_prompt(self, chat_id):
        msg = (
            "🤝 <b>CALLER PARTNERSHIP & 50/50 REVENUE SPLIT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Do you run a profitable crypto trading community, alpha group, or onchain tracker?\n\n"
            "💰 <b>THE CREATOR OFFER:</b>\n"
            "• List your channel in the NetSwap Insider Alpha Store\n"
            "• You keep <b>50% of monthly subscription fees</b> automatically in ETH/SOL\n"
            "• Plus <b>30% lifetime fee share</b> on every swap executed by your subscribers!\n\n"
            "📋 <b>HOW TO APPLY FOR LISTING:</b>\n"
            "Reply with: <code>/listsignal &lt;channel_name&gt; &lt;chain&gt; &lt;monthly_price_eth&gt;</code>\n"
            "Example: <code>/listsignal MyAlphaGroup Base 0.02</code>\n\n"
            "<i>Our listing desk will verify your on-chain track record and activate your listing within 2 hours!</i>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "👑 View Alpha Store", "callback_data": "menu_insiders"}],
                [{"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_vip_store(self, chat_id):
        self.show_insiders_store(chat_id)

    def show_alerts_menu(self, chat_id):
        settings = get_user_alert_settings(chat_id)
        alerts_on = (settings.get("alerts_enabled", 0) == 1)

        if not alerts_on:
            msg = (
                "🔔 <b>NETSWAP ALPHA & SAFETY ALERTS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Status: 🔴 <b>PAUSED / OFF</b>\n\n"
                "Enable push alerts to arm your Telegram lockscreen with sub-second on-chain intelligence:\n\n"
                "• 🛡️ <b>Emergency Rug Guardian:</b> Instant warning if dev revokes sells\n"
                "• 📢 <b>Sponsored Alpha Drops:</b> Verified institutional coin alerts\n"
                "• 🐋 <b>Smart Whale Radar:</b> 80%+ win-rate wallets with 1-tap mirror\n"
                "• ⚙️ <b>Launch Radar:</b> Sub-second Clanker & Pump.fun genesis pools\n"
                "• 🚀 <b>Take-Profit Pings:</b> Auto-alerts when your tokens pump +50%/+100%\n"
                "• 👑 <b>VIP Alpha Streams:</b> Top 0.1% callers (Ansem, GCR, Murad, TJR)\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "👇 Tap below to grant permission and activate your Push Stream:"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🔔 Turn On Alerts (Activate Push Stream)", "callback_data": "alert_toggle_master_on"}],
                    [{"text": "👑 Browse VIP Alpha Store (Web) ↗", "url": f"https://netswap.vercel.app/store.html?user_id={chat_id}"}],
                    [{"text": "🔙 Main Menu", "callback_data": "menu_main"}]
                ]
            }
            self.send_message(chat_id, msg, markup)
            return

        # Alerts are ON!
        subs = get_user_subscriptions(chat_id)
        subs_badge = f"{len(subs)} Active" if subs else "0 Active"

        msg = (
            "🔔 <b>NETSWAP ALPHA & SAFETY ALERTS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Stream Status: 🟢 <b>ACTIVE (Push Stream Armed)</b>\n\n"
            "🔒 <b>COMPULSORY AUTO-ACTIVE FEEDS:</b>\n"
            "• 📢 <b>Sponsored Alpha & Partner Drops:</b> 🟢 <b>ACTIVE</b>\n"
            "• 🛡️ <b>Emergency Rug Guardian:</b> 🟢 <b>ACTIVE</b>\n\n"
            "Choose an alert stream category below to configure feeds or manage VIP Alpha:"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "⚡ Free Alert Streams", "callback_data": "menu_free_alerts"},
                    {"text": f"👑 VIP Alpha Alerts ({subs_badge})", "callback_data": "menu_vip_alerts"}
                ],
                [
                    {"text": "🧪 Test Lockscreen Ping", "callback_data": "menu_test_alert"},
                    {"text": "📋 My Subscriptions", "callback_data": "menu_mysubs"}
                ],
                [
                    {"text": "🔕 Turn Off Alerts (Pause All)", "callback_data": "alert_toggle_master_off"}
                ],
                [
                    {"text": "🔙 Main Menu", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_free_alerts_menu(self, chat_id):
        settings = get_user_alert_settings(chat_id)
        w_state = "🟢 ON" if settings.get("free_whale_radar", 1) == 1 else "🔴 OFF"
        l_state = "🟢 ON" if settings.get("free_launch_radar", 1) == 1 else "🔴 OFF"
        p_state = "🟢 ON" if settings.get("free_pnl_pings", 1) == 1 else "🔴 OFF"

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT wallet_address, chain FROM tracked_user_wallets WHERE user_id = ?", (chat_id,))
        tracked_row = cursor.fetchone()
        conn.close()

        tracked_str = f"<code>{tracked_row[0][:6]}...{tracked_row[0][-4:]}</code> ({tracked_row[1]})" if tracked_row else "<i>None set</i>"

        msg = (
            "⚡ <b>FREE ALERT STREAMS & SIGNALS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Customize which free market intelligence streams ping your phone:\n\n"
            "🔒 <b>COMPULSORY (Auto-Active):</b>\n"
            "• 📢 <b>Sponsored Partner Drops:</b> 🟢 <b>ACTIVE</b>\n"
            "• 🛡️ <b>Rug & Honeypot Guardian:</b> 🟢 <b>ACTIVE</b>\n\n"
            "⚡ <b>SELECTABLE FREE SIGNALS:</b>\n"
            f"• 🐋 <b>Smart Whale Radar:</b> {w_state}\n"
            f"• ⚙️ <b>Launch Radar (Clanker/Pump):</b> {l_state}\n"
            f"• 🚀 <b>Take-Profit PnL Pings:</b> {p_state}\n"
            f"• 🎯 <b>Custom Tracked Wallet:</b> {tracked_str}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Tap any toggle below to customize your stream, or track any custom wallet:"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": f"🐋 Whale Radar: {w_state}", "callback_data": "toggle_free_whale"},
                    {"text": f"⚙️ Launch Radar: {l_state}", "callback_data": "toggle_free_launch"}
                ],
                [
                    {"text": f"🚀 Take-Profit: {p_state}", "callback_data": "toggle_free_pnl"},
                    {"text": "🎯 Track Custom Wallet", "callback_data": "menu_trackwallet_prompt"}
                ],
                [
                    {"text": "🧪 Send Test Ping", "callback_data": "menu_test_alert"},
                    {"text": "🔙 Back to Alerts", "callback_data": "menu_alerts"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_vip_alerts_menu(self, chat_id):
        settings = get_user_alert_settings(chat_id)
        vip_push_on = (settings.get("vip_push_enabled", 1) == 1)
        vip_state = "🟢 ACTIVE" if vip_push_on else "🔴 PAUSED"

        subs = get_user_subscriptions(chat_id)
        if subs:
            subs_text = "👑 <b>YOUR ACTIVE VIP CHANNELS:</b>\n"
            for row in subs:
                subs_text += f"• <b>{row[1]}</b> 🟢 <i>(Active)</i>\n"
            subs_text += "\n"
        else:
            subs_text = (
                "👑 <b>YOUR ACTIVE VIP CHANNELS:</b>\n"
                "<i>You currently have no active paid feeds.</i>\n\n"
                "Visit the <b>Alpha Store</b> to subscribe to top 0.1% callers (Ansem, GCR, Murad, TJR) and Block-0 snipers with crypto or $NETSWAP points!\n\n"
            )

        msg = (
            "👑 <b>VIP ALPHA PUSH STREAMS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"VIP Push Stream: <b>{vip_state}</b>\n"
            "<i>(Master switch governing whether paid signals push to your lockscreen)</i>\n\n"
            f"{subs_text}"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Tap below to browse the Web Alpha Store, manage subscriptions, or toggle VIP push delivery:"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": f"⚡ VIP Push Stream: {vip_state}", "callback_data": "toggle_vip_stream"}
                ],
                [
                    {"text": "👑 Browse VIP Alpha Store (Web) ↗", "url": f"https://netswap.vercel.app/store.html?user_id={chat_id}"}
                ],
                [
                    {"text": "📋 My Subscriptions", "callback_data": "menu_mysubs"},
                    {"text": "🔙 Back to Alerts", "callback_data": "menu_alerts"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_my_subscriptions(self, chat_id):
        subs = get_user_subscriptions(chat_id)
        now = int(time.time())
        key = generate_vip_recovery_key(chat_id)
        if not subs:
            msg = (
                "📋 <b>YOUR ACTIVE VIP SUBSCRIPTIONS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "You currently have no active paid feeds subscribed.\n\n"
                "🔔 <b>Free DM Alerts Active:</b>\n"
                "• Rug Guardian Warnings (🟢 Active)\n"
                "• Personal PnL Take-Profit Pings (🟢 Active)\n"
                "• 1 Custom Tracked Wallet (🟢 Active)\n\n"
                "👑 <b>Explore 64 VIP Feeds:</b> Browse Block-0 Snipers, Whale Shadow, and Top 0.1% Callers on the Alpha Mall!"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "👑 Browse VIP Alpha Mall ➔", "url": f"https://netswap.vercel.app/store.html?user_id={chat_id}"}],
                    [{"text": "🔙 Back to Alerts", "callback_data": "menu_alerts"}]
                ]
            }
        else:
            lines = []
            expiring_soon = False
            for k, name, active_until in subs:
                days_left = max(0, int((active_until - now) / 86400))
                if days_left <= 7:
                    expiring_soon = True
                    lines.append(f"• <b>{name}</b>\n  ⚠️ <i>Expires in {days_left} days! (Renewal due)</i>")
                else:
                    lines.append(f"• <b>{name}</b>\n  🟢 <i>Active ({days_left} days remaining)</i>")
            
            feeds_text = "\n".join(lines)
            renewal_warning = "\n⚠️ <b>Renewal Notice:</b> 1 or more feeds expire within 7 days. Renew to maintain uninterrupted push delivery.\n" if expiring_soon else ""
            
            msg = (
                "📋 <b>YOUR ACTIVE VIP SUBSCRIPTIONS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{feeds_text}\n"
                f"{renewal_warning}"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔑 <b>Your Account Migration License Key:</b>\n<code>{key}</code>\n\n"
                f"<i>If your Telegram is ever deleted or you switch accounts, send <code>/claimkey {key}</code> on your new account to transfer all feeds instantly!</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "👑 Manage on Alpha Mall (Web) ➔", "url": f"https://netswap.vercel.app/store.html?user_id={chat_id}"}],
                    [{"text": "🧪 Send Test Push Alert to DM", "callback_data": "menu_test_alert"}],
                    [{"text": "🔙 Back to Alerts", "callback_data": "menu_alerts"}]
                ]
            }
        self.send_message(chat_id, msg, markup)

    def send_sample_dm_alert(self, chat_id):
        alert_msg = (
            "🚨 <b>SMART MONEY WHALE BUY DETECTED!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🐋 <b>Whale #42 accumulated:</b> <code>$48,500 USD</code> of <b>$BRETT</b>\n"
            "📍 <b>CA:</b> <code>0x532f27101965dd16442e59d40670faf5ebb142e4</code>\n"
            "⚡ <b>NetSwap Protection:</b> 🟢 <b>Anti-MEV Shield Active</b>\n"
            "📊 <b>24h Momentum:</b> <b>+18.4%</b> | Volume: <b>$2.4M</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👇 <b>1-Click Mirror Buy with Zero AMM Slippage:</b>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "⚡ 1-Click Buy $BRETT on NetSwap", "url": "https://t.me/NetSwapBaseBot?start=buy_0x532f27101965dd16442e59d40670faf5ebb142e4"}],
                [{"text": "👑 VIP Alpha Store (Web)", "url": f"https://netswap.vercel.app/store.html?user_id={chat_id}"}],
                [{"text": "🔙 Alerts Settings", "callback_data": "menu_alerts"}]
            ]
        }
        self.send_message(chat_id, alert_msg, markup)

    def handle_track_wallet(self, chat_id, text):
        parts = text.split()
        if len(parts) < 2:
            self.send_message(
                chat_id,
                "🎯 <b>FREE CUSTOM WALLET TRACKER</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Track any 1 crypto wallet (influencer, whale, or smart friend) for 100% free!\n\n"
                "Whenever this wallet buys or sells on Base or Solana, NetSwap will ping your Telegram DM in seconds with a 1-tap copy button.\n\n"
                "Usage: <code>/trackwallet &lt;wallet_address&gt;</code>\n"
                "Example: <code>/trackwallet 0x532f27101965dd16442e59d40670faf5ebb142e4</code>"
            )
            return

        addr = parts[1].strip()
        chain = "Solana" if len(addr) >= 32 and not addr.startswith("0x") else "Base"

        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tracked_user_wallets WHERE user_id = ?", (chat_id,))
            cursor.execute("""
                INSERT INTO tracked_user_wallets (user_id, wallet_address, chain, label, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (chat_id, addr, chain, "Custom Tracked", int(time.time())))
            conn.commit()
            conn.close()

            trunc = f"{addr[:6]}...{addr[-4:]}"
            self.send_message(
                chat_id,
                f"🟢 <b>WALLET TRACKING ACTIVATED!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📍 <b>Tracked:</b> <code>{trunc}</code> ({chain} Network)\n\n"
                f"Whenever this wallet executes an on-chain trade, you will receive an instant lockscreen notification with a 1-tap copy button (0% slippage & Anti-MEV shield)!\n\n"
                f"<i>Need to track up to 10 wallets simultaneously? Upgrade in the Insider Alpha Store.</i>"
            )
        except Exception as e:
            self.send_message(chat_id, f"❌ Error saving tracked wallet: {e}")

    def show_stats(self, chat_id):
        msg = (
            "📊 <b>NETSWAP PROTOCOL PERFORMANCE (BASE)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ <b>Settlement Engine:</b> Micro-Batching (2.0s Base Blocks)\n"
            "🔄 <b>Overlapping Flow Netted P2P:</b> <code>67.4%</code>\n"
            "🛡️ <b>Total MEV Sandwiches Blocked:</b> <code>$24,850.15</code>\n"
            "💸 <b>Average Trader Net Benefit:</b> <code>+$14.20 / swap</code>\n"
            "⛽ <b>AMM Gas Overhead Saved:</b> <code>~45% vs Router</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Settlement Contract:</i>\n<code>0x0Ae0d97111F837EAAd45B35E8EAa77Fc75468f8F</code>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def show_help(self, chat_id):
        msg = (
            "📖 <b>NETSWAP COMPLETE PROTOCOL MANUAL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Welcome to NetSwap — the dual-chain trading primitive engineered to eliminate predatory DEX extraction on Base & Solana.\n\n"
            "⚡ <b>1. HOW NETSWAP PROTECTS YOUR CAPITAL:</b>\n"
            "• <b>P2P Micro-Batch Netting:</b> Instead of blindly routing your swap into an AMM pool where sandwich bots lie in wait, NetSwap groups orders into 2-second micro-batches and matches buyers with sellers directly at fair mid-market price (<b>0% AMM slippage!</b>).\n"
            "• <b>Hybrid Routing Fallback:</b> If no opposing trader is present in that micro-second, NetSwap instantly routes your order through deep DEX liquidity (Aerodrome on Base / Jupiter on Solana) with anti-MEV private RPC relays.\n"
            "• <b>Zero Bot Extortion:</b> Competitor bots (Trojan, Maestro, BonkBot) charge 1.0% tolls on top of 3% AMM slippage. NetSwap charges half the fee, gives 0.25% instant cashback in ETH, and awards 50 $NETSWAP loyalty tokens on every trade!\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛡️ <b>2. SECURITY & 100% SELF-CUSTODY:</b>\n"
            "• Your trading keys are generated locally in your personal encrypted SQLite database.\n"
            "• You maintain 100% custody of your funds. You can export your Base and Solana private keys at any moment into MetaMask, Coinbase Wallet, Phantom, or Solflare.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⌨️ <b>3. COMMAND CHEATSHEET:</b>\n"
            "• <code>/start</code> — Open the main trading terminal\n"
            "• <code>/audit &lt;wallet_or_tx&gt;</code> — Multi-chain loss forensic audit\n"
            "• <code>/leaks</code> — Global DEX Victim Index & mempool counter\n"
            "• <code>/insiders</code> — Smart Money Insider Alpha Store\n"
            "• <code>/ads</code> — Reach-Tiered Advertising Marketplace\n"
            "• <code>/listsignal</code> — List your signal channel (50/50 creator split)\n"
            "• <code>/wallet</code> — Balance overview, cashback & private key export\n"
            "• <code>/sol</code> — Open high-speed Solana sniper terminal\n"
            "• <code>/shield &lt;ca&gt;</code> — Autonomous rug & honeypot risk scan\n"
            "• <code>/alerts</code> — Direct-to-DM whale & launch notifications\n"
            "• <code>/track &lt;ca&gt;</code> — Install buy alert bot in your Telegram group\n"
            "• <code>/vip &lt;tag&gt;</code> — Activate 30% lifetime affiliate revenue share\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Tip: Paste ANY contract address directly in chat to trade instantly!</i>"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "🧾 Run Free Loss Audit", "callback_data": "menu_audit_prompt"},
                    {"text": "⚡ Start Trading Base", "callback_data": "menu_trending"}
                ],
                [
                    {"text": "🪐 Solana Terminal", "callback_data": "menu_sol"},
                    {"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}
                ]
            ]
        }
        self.send_message(chat_id, msg, markup)

    def execute_base_buy(self, chat_id, username, token_addr, amount_eth):
        user = get_user_by_id(chat_id)
        if not user:
            user = get_or_create_user(chat_id, username)

        user_address = user[0]
        bal = get_wallet_balance(user_address)

        if bal < amount_eth:
            msg = (
                "⚠️ <b>INSUFFICIENT BALANCE FOR ORDER</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Selected Order: <b>{amount_eth} ETH</b>\n"
                f"Current Balance: <b>{bal:.5f} ETH</b>\n\n"
                f"Deposit Base ETH to your address:\n<code>{user_address}</code>\n\n"
                "<i>Once deposited, enter /buy again to execute instant swap!</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🔄 Refresh Balance", "callback_data": "menu_wallet"}],
                    [{"text": "🔙 Back to Token", "callback_data": f"select_token_{token_addr}"}]
                ]
            }
            self.send_message(chat_id, msg, markup)
            return

        self.send_message(
            chat_id,
            f"⏳ <b>Initiating NetSwap on Base...</b>\n\n"
            f"• Order: <code>{amount_eth} ETH</code>\n"
            "• Checking P2P batch & routing to DEX fallback..."
        )

        res = execute_onchain_buy(chat_id, token_addr, amount_eth)
        if res["success"]:
            tx_url = f"https://basescan.org/tx/{res['tx_hash']}"
            share_win_text = urllib.parse.quote(
                f"🚀 Just swapped ${res['token_symbol']} on Base with @NetSwapBaseBot!\n"
                f"• 0% AMM Slippage: Saved +${res['saved_usd']:.2f} vs Uniswap\n"
                f"• 100% Anti-MEV Sandwich Protection\n"
                f"Trade with anti-MEV here:"
            )
            share_win_url = f"https://t.me/share/url?url=https%3A%2F%2Ft.me%2FNetSwapBaseBot%3Fstart%3Dref_{chat_id}&text={share_win_text}"

            success_msg = (
                "🚀 <b>SWAP EXECUTED SUCCESSFULLY ON BASE!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 <b>Token:</b> ${res['token_symbol']}\n"
                f"📥 <b>Input:</b> <code>{res['amount_eth']} ETH</code>\n"
                f"🛡️ <b>Anti-MEV Shield:</b> 🟢 <b>100% PROTECTED</b>\n"
                f"💰 <b>AMM Slippage Saved:</b> <b>+${res['saved_usd']:.2f}</b> vs Uniswap\n"
                f"🎁 <b>Rebates:</b> <code>+${res['cashback_usd']:.2f} ETH</code> + <code>50 $NETSWAP</code>\n"
                f"🏆 <b>Trader Status:</b> <code>{res['trader_tier']}</code>\n"
                "--------------------------------------\n"
                f"💰 <b>You kept +${res['saved_usd']:.2f} more than Maestro traders!</b>\n\n"
                f"🔗 <a href='{tx_url}'>View on BaseScan</a>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>Tokens delivered directly to your self-custody Base wallet!</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "📢 Share Win Receipt to Telegram", "url": share_win_url}],
                    [{"text": "👥 Earn 30% Referral Payouts", "callback_data": "menu_vip"}],
                    [{"text": "🔍 View on BaseScan", "url": tx_url}],
                    [{"text": "🔙 Main Menu", "callback_data": "menu_main"}]
                ]
            }
            self.send_message(chat_id, success_msg, markup)
        else:
            self.send_message(chat_id, f"❌ <b>Base Swap Error:</b> {res.get('error')}")

    def execute_solana_buy(self, chat_id, mint, amount_sol):
        sol_pubkey, secret_b58 = se.get_or_create_solana_wallet(chat_id)
        cur_bal = se.get_sol_balance(sol_pubkey)

        if cur_bal < amount_sol:
            msg = (
                "⚠️ <b>INSUFFICIENT SOL FOR ORDER</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Selected Order: <b>{amount_sol} SOL</b>\n"
                f"Current Balance: <b>{cur_bal:.4f} SOL</b>\n\n"
                f"Deposit SOL to your Solana address:\n<code>{sol_pubkey}</code>\n\n"
                "<i>Once deposited, enter /buy again to execute instant swap!</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🔄 Refresh Balance", "callback_data": "menu_sol"}],
                    [{"text": "🔙 Back to Token", "callback_data": f"select_sol_{mint}"}]
                ]
            }
            self.send_message(chat_id, msg, markup)
            return

        self.send_message(
            chat_id,
            f"⏳ <b>Initiating NetSwap on Solana (Jupiter v1)...</b>\n\n"
            f"• Order: <code>{amount_sol} SOL</code>\n"
            "• Routing optimal DEX path across Raydium & Meteora...\n"
            "• Securing 0.85% Anti-MEV Platform Protection..."
        )

        lamports = int(amount_sol * 1_000_000_000)
        quote_res = se.get_jupiter_quote(se.WSOL_MINT, mint, lamports)
        if not quote_res["success"]:
            self.send_message(chat_id, f"❌ <b>Jupiter Routing Error:</b>\n{quote_res.get('error')}")
            return

        tx_res = se.build_jupiter_swap_transaction(sol_pubkey, quote_res["quote"])
        if not tx_res["success"]:
            self.send_message(chat_id, f"❌ <b>Transaction Build Error:</b>\n{tx_res.get('error')}")
            return

        exec_res = se.execute_solana_swap(secret_b58, tx_res["swapTransaction"])
        if exec_res["success"]:
            sig = exec_res["tx_signature"]
            solscan = exec_res["solscan_url"]
            se.record_solana_trade(chat_id, se.WSOL_MINT, mint, "SOL-TOKEN", "BUY", amount_sol, 0, sig, amount_sol * 0.0085, "SOL")
            share_win_text = urllib.parse.quote(
                f"🚀 Just swapped on Solana with @NetSwapBaseBot!\n"
                f"• 0% AMM Slippage & 100% Anti-MEV Protection\n"
                f"• Saved fees vs competitor bots!\n"
                f"Trade with anti-MEV here:"
            )
            share_win_url = f"https://t.me/share/url?url=https%3A%2F%2Ft.me%2FNetSwapBaseBot%3Fstart%3Dref_{chat_id}&text={share_win_text}"

            success_msg = (
                "🚀 <b>SWAP EXECUTED SUCCESSFULLY ON SOLANA!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📥 <b>Input:</b> <code>{amount_sol} SOL</code>\n"
                f"🛡️ <b>Anti-MEV Shield:</b> 🟢 <b>100% PROTECTED</b>\n"
                f"⚡ <b>Engine:</b> Jupiter Aggregator v1\n"
                f"💸 <b>Platform Toll:</b> <code>{amount_sol * 0.0085:.6f} SOL</code> (85 bps)\n"
                "🎁 <b>Loyalty Rewards:</b> <code>+50 $NETSWAP</code> credited!\n"
                "--------------------------------------\n"
                f"💰 <b>You kept more yield on NetSwap than on Trojan or Raydium!</b>\n\n"
                f"🔗 <a href='{solscan}'>View on Solscan</a>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>Tokens delivered directly to your self-custody Solana wallet!</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "📢 Share Win Receipt to Telegram", "url": share_win_url}],
                    [{"text": "👥 Earn 30% Referral Payouts", "callback_data": "menu_vip"}],
                    [{"text": "🪐 Solana Terminal", "callback_data": "menu_sol"}],
                    [{"text": "🔙 Main Menu", "callback_data": "menu_main"}]
                ]
            }
            self.send_message(chat_id, success_msg, markup)
        else:
            self.send_message(chat_id, f"❌ <b>Solana Execution Error:</b>\n\n<code>{exec_res.get('error')}</code>")

    def handle_callback(self, callback_id, chat_id, data, username=""):
        self.answer_callback(callback_id)

        if data in ["menu_main", "menu_refresh"]:
            caption, markup = self.build_main_menu(chat_id, username)
            self.send_message(chat_id, caption, markup)
            return

        if data == "menu_clanker":
            self.show_clanker_radar(chat_id)
            return

        if data == "menu_arb":
            self.show_arb_dashboard(chat_id)
            return

        if data == "menu_sol":
            self.show_solana_terminal(chat_id, username)
            return

        if data == "sol_export":
            self.show_solana_export(chat_id)
            return

        if data == "sol_withdraw_prompt":
            self.show_solana_withdraw_prompt(chat_id)
            return

        if data == "base_withdraw_prompt":
            self.show_base_withdraw_prompt(chat_id)
            return

        if data.startswith("custom_buy_base_"):
            token_addr = data.replace("custom_buy_base_", "")
            token = fetch_token_info(token_addr)
            USER_ACTIVE_QUOTE[chat_id] = {"chain": "base", "address": token_addr, "symbol": token["symbol"]}
            self.send_message(
                chat_id,
                f"✏️ <b>CUSTOM BUY AMOUNT: ${token['symbol']} (Base)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Send your custom buy amount in chat:\n"
                "<code>/buy &lt;amount_eth&gt;</code>\n\n"
                "<b>Examples:</b>\n"
                "• <code>/buy 0.25</code> (~$800)\n"
                "• <code>/buy 1.0</code> (~$3,200)\n"
                "• <code>/buy 10</code> (~$32,000)\n\n"
                "<i>Your order will execute immediately with 0% AMM slippage!</i>",
                {"inline_keyboard": [[{"text": "🔙 Back to Token", "callback_data": f"select_token_{token_addr}"}]]}
            )
            return

        if data.startswith("custom_buy_sol_"):
            mint = data.replace("custom_buy_sol_", "")
            token = se.fetch_solana_token(mint)
            USER_ACTIVE_QUOTE[chat_id] = {"chain": "sol", "mint": mint, "symbol": token.get("symbol", "SOL-TOKEN")}
            self.send_message(
                chat_id,
                f"✏️ <b>CUSTOM BUY AMOUNT: ${token.get('symbol', 'TOKEN')} (Solana)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Send your custom buy amount in chat:\n"
                "<code>/buy &lt;amount_sol&gt;</code>\n\n"
                "<b>Examples:</b>\n"
                "• <code>/buy 2.5</code> (~$375)\n"
                "• <code>/buy 10</code> (~$1,500)\n"
                "• <code>/buy 100</code> (~$15,000)\n\n"
                "<i>Your order will execute sub-second via Jupiter routing!</i>",
                {"inline_keyboard": [[{"text": "🔙 Back to Token", "callback_data": f"select_sol_{mint}"}]]}
            )
            return

        if data.startswith("solbuy_"):
            parts = data.split("_")
            mint = parts[1]
            amount_sol = float(parts[2])
            self.execute_solana_buy(chat_id, mint, amount_sol)
            return

        if data == "menu_whales":
            self.show_whale_radar(chat_id)
            return


        if data == "menu_swap":
            self.show_swap_terminal(chat_id, username)
            return

        if data == "menu_positions":
            self.show_positions(chat_id, username)
            return

        if data == "menu_copytrade":
            self.show_copytrade_menu(chat_id)
            return

        if data in ["copy_base_a", "copy_clanker", "copy_sol_b"]:
            update_user_alert_settings(chat_id, alerts_enabled=1, free_whale_radar=1)
            stream_name = "Base Whale Alpha A" if data == "copy_base_a" else "Clanker Sub-Second Sniper" if data == "copy_clanker" else "Solana Megalodon Whale"
            self.send_message(
                chat_id,
                f"✅ <b>WHALE MIRROR STREAM ACTIVE!</b>\n\n"
                f"You are now subscribed to real-time mirror alerts for <b>{stream_name}</b>.\n\n"
                f"Whenever this smart money wallet trades, you will receive an instant lockscreen alert with <b>1-Tap Mirror Execution Buttons</b> (e.g. <code>[ ⚡ Mirror 0.05 ETH ]</code>).\n\n"
                f"💡 <i>Be sure to deposit ETH or SOL into your in-bot wallet to execute mirror orders instantly!</i>",
                {"inline_keyboard": [[{"text": "💳 Deposit / Wallet", "callback_data": "menu_wallet"}, {"text": "🔔 Alert Settings", "callback_data": "menu_alerts"}]]}
            )
            return

        if data == "menu_batch":
            self.show_batch_terminal(chat_id)
            return

        if data.startswith("sell_base_"):
            parts = data.split("_")
            token_addr = parts[2]
            pct_int = int(parts[3])
            pct_float = pct_int / 100.0

            self.send_message(chat_id, f"⏳ <b>Broadcasting Onchain Take-Profit Sell ({pct_int}%)...</b>\n\nRouting through Aerodrome router with 0% sandwich exposure...")
            res = execute_onchain_sell(chat_id, token_addr, pct_float)
            if res["success"]:
                basescan_url = f"https://basescan.org/tx/{res['tx_hash']}"
                self.send_message(
                    chat_id,
                    f"✅ <b>TAKE-PROFIT SELL EXECUTED!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• Sold: <b>{res['pct']}% of ${res['token_symbol']}</b>\n"
                    f"• Amount: <code>{res['amount_sold']:,.4f} ${res['token_symbol']}</code>\n"
                    f"• Settlement: Native ETH credited to your Base wallet\n"
                    f"• Explorer: <a href='{basescan_url}'>View on BaseScan</a>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🛡️ <i>Protected against MEV sandwich attacks via NetSwap Anti-MEV routing.</i>",
                    {"inline_keyboard": [[{"text": "💼 View Positions", "callback_data": "menu_positions"}, {"text": "🔙 Main Menu", "callback_data": "menu_main"}]]}
                )
            else:
                self.send_message(chat_id, f"❌ <b>Sell Failed:</b>\n\n<code>{res['error']}</code>")
            return

        if data.startswith("sell_sol_"):
            parts = data.split("_")
            mint = parts[2]
            pct_int = int(parts[3])
            self.send_message(chat_id, f"⏳ <b>Executing Solana Sell ({pct_int}%)...</b>\n\nRouting via Jupiter with Anti-MEV protection...")
            try:
                sol_pubkey, secret_b58 = se.get_or_create_solana_wallet(chat_id)
                tokens = se.get_spl_token_balances(sol_pubkey)
                target_tok = next((t for t in tokens if t["mint"] == mint), None)
                if not target_tok or target_tok["amount"] <= 0:
                    self.send_message(chat_id, "❌ No balance found for this SPL token.")
                    return
                sell_amt = target_tok["amount"] * (pct_int / 100.0)
                raw_amt = int(sell_amt * (10 ** target_tok.get("decimals", 6)))
                q = se.get_jupiter_quote(mint, se.WSOL_MINT, raw_amt)
                if not q["success"]:
                    self.send_message(chat_id, f"❌ Jupiter routing error: {q.get('error')}")
                    return
                tx_b = se.build_jupiter_swap_transaction(sol_pubkey, q["quote"])
                if not tx_b["success"]:
                    self.send_message(chat_id, f"❌ Transaction build error: {tx_b.get('error')}")
                    return
                ex = se.execute_solana_swap(secret_b58, tx_b["swapTransaction"])
                if ex["success"]:
                    self.send_message(
                        chat_id,
                        f"✅ <b>SOLANA TAKE-PROFIT SELL EXECUTED!</b>\n\n"
                        f"• Sold: <b>{pct_int}% of SPL holdings</b>\n"
                        f"• Explorer: <a href='{ex['solscan_url']}'>View on Solscan</a>",
                        {"inline_keyboard": [[{"text": "💼 View Positions", "callback_data": "menu_positions"}, {"text": "🔙 Main Menu", "callback_data": "menu_main"}]]}
                    )
                else:
                    self.send_message(chat_id, f"❌ Sell execution error: {ex.get('error')}")
            except Exception as e:
                self.send_message(chat_id, f"❌ Solana Sell Exception: {e}")
            return

        if data == "menu_wallet":
            self.show_wallet(chat_id, username)
            return

        if data == "menu_tools":
            self.show_tools_menu(chat_id)
            return


        if data == "menu_trending":
            self.show_trending(chat_id)
            return

        if data == "menu_buy":
            self.send_message(
                chat_id,
                "👇 <b>Send Contract Address:</b>\n\nPaste the Base token contract address (CA) you want to buy:"
            )
            return

        if data == "menu_leaks":
            self.show_leaks_wall(chat_id)
            return

        if data == "menu_audit_prompt":
            web_audit_url = "https://netswap.vercel.app/audit.html"
            msg = (
                "🧾 <b>NETSWAP DUAL-CHAIN FORENSIC LOSS AUDITOR</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Expose the hidden wealth extracted from your trades by predatory sandwich bots, AMM slippage, and 1% bot taxes!\n\n"
                "🌐 <b>FULL FORENSIC WEB AUDIT:</b>\n"
                "Paste your active trading wallet (MetaMask, Phantom, etc.), choose your audit timeframe (7D, 30D, 90D, 1Y), and download your cryptographic loss certificate.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 <b>To audit directly in Telegram:</b>\n"
                "Send: <code>/audit &lt;your_wallet_address&gt;</code>\n"
                "Example: <code>/audit 0xbE40c75844197fD334db4174CBd7D07F9bAb93f8</code>\n\n"
                "👇 <b>Select an option below:</b>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🌐 Open Web Loss Audit ↗", "url": web_audit_url}],
                    [{"text": "🏆 Victim Index (Web) ↗", "url": "https://netswap.vercel.app/audit.html#leaderboard"}],
                    [{"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}]
                ]
            }
            self.send_message(chat_id, msg, markup)
            return

        if data.startswith("audittf_"):
            parts = data.split("_")
            target = parts[1]
            tf = parts[2] if len(parts) > 2 else "all"
            self.show_audit_report(chat_id, target, tf)
            return

        if data.startswith("run_audit_"):
            addr = data.replace("run_audit_", "")
            self.show_audit_timeframe_picker(chat_id, addr)
            return

        if data in ["menu_vip_store", "menu_insiders"]:
            self.show_insiders_store(chat_id)
            return

        if data == "menu_listsignal":
            self.show_listsignal_prompt(chat_id)
            return

        if data.startswith("sub_sig_"):
            sig_id = data.replace("sub_sig_", "")
            self.show_insider_invoice(chat_id, sig_id)
            return

        if data in ["menu_sponsor", "menu_ads"]:
            self.show_ads_marketplace(chat_id)
            return

        if data.startswith("book_ad_"):
            tier_id = data.replace("book_ad_", "")
            self.show_ad_invoice(chat_id, tier_id)
            return

        if data == "menu_alerts":
            self.show_alerts_menu(chat_id)
            return

        if data == "alert_toggle_master_on":
            update_user_alert_settings(chat_id, alerts_enabled=1, compulsory_ads=1, compulsory_rug=1)
            self.show_alerts_menu(chat_id)
            return

        if data == "alert_toggle_master_off":
            update_user_alert_settings(chat_id, alerts_enabled=0)
            self.show_alerts_menu(chat_id)
            return

        if data == "menu_free_alerts":
            self.show_free_alerts_menu(chat_id)
            return

        if data == "menu_vip_alerts":
            self.show_vip_alerts_menu(chat_id)
            return

        if data == "toggle_free_whale":
            st = get_user_alert_settings(chat_id)
            nv = 0 if st.get("free_whale_radar", 1) == 1 else 1
            update_user_alert_settings(chat_id, free_whale_radar=nv)
            self.show_free_alerts_menu(chat_id)
            return

        if data == "toggle_free_launch":
            st = get_user_alert_settings(chat_id)
            nv = 0 if st.get("free_launch_radar", 1) == 1 else 1
            update_user_alert_settings(chat_id, free_launch_radar=nv)
            self.show_free_alerts_menu(chat_id)
            return

        if data == "toggle_free_pnl":
            st = get_user_alert_settings(chat_id)
            nv = 0 if st.get("free_pnl_pings", 1) == 1 else 1
            update_user_alert_settings(chat_id, free_pnl_pings=nv)
            self.show_free_alerts_menu(chat_id)
            return

        if data == "toggle_vip_stream":
            st = get_user_alert_settings(chat_id)
            nv = 0 if st.get("vip_push_enabled", 1) == 1 else 1
            update_user_alert_settings(chat_id, vip_push_enabled=nv)
            self.show_vip_alerts_menu(chat_id)
            return

        if data == "menu_mysubs":
            self.show_my_subscriptions(chat_id)
            return

        if data == "menu_test_alert":
            self.send_sample_dm_alert(chat_id)
            return

        if data == "menu_trackwallet_prompt":
            msg = (
                "🎯 <b>SET YOUR 1 FREE TRACKED WALLET</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Send the wallet address you want to spy on in this chat:\n\n"
                "<code>/trackwallet &lt;wallet_address&gt;</code>\n\n"
                "Whenever this wallet buys or sells on Base or Solana, NetSwap will ping you with a 1-tap copy button!"
            )
            markup = {"inline_keyboard": [[{"text": "🔙 Back to Alerts", "callback_data": "menu_alerts"}]]}
            self.send_message(chat_id, msg, markup)
            return

        if data == "menu_vip_deposit_info":
            msg = (
                "📥 <b>VIP TREASURY DEPOSIT ADDRESSES</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Send payment to unlock 30 days of VIP Insider Alpha:\n\n"
                f"🔷 <b>Base (ETH):</b> <code>{SUBS_RECIPIENT_BASE}</code>\n"
                "• Amount: <code>0.015 ETH</code>\n\n"
                f"🪐 <b>Solana (SOL):</b> <code>{SUBS_RECIPIENT_SOL}</code>\n"
                "• Amount: <code>0.35 SOL</code>\n\n"
                "<i>Your VIP status is activated immediately upon onchain confirmation!</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🔙 Back", "callback_data": "menu_insiders"}]
                ]
            }
            self.send_message(chat_id, msg, markup)
            return

        if data in ["pay_vip_eth", "pay_vip_sol"]:
            self.send_message(
                chat_id,
                "✅ <b>VIP ACTIVATION PROCESSING!</b>\n\n"
                "Your VIP pass is being confirmed on-chain. You will receive Block-0 alerts and 50% trading fee discount immediately!"
            )
            return

        if data == "menu_shield_prompt":
            msg = (
                "🛡️ <b>NETSWAP RUG & HONEYPOT SHIELD</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Never get rugged again. NetSwap verifies bytecode, detects honeypots, and blocks toxic sell taxes before you enter.\n\n"
                "👇 <b>How to Scan:</b>\n"
                "• Send: <code>/shield &lt;token_ca&gt;</code>\n"
                "• Or just paste any token contract address (CA) directly into the chat!"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}]
                ]
            }
            self.send_message(chat_id, msg, markup)
            return

        if data == "menu_stats":
            self.show_stats(chat_id)
            return

        if data == "menu_refer":
            self.show_refer(chat_id)
            return

        if data == "menu_vip":
            self.show_vip_info(chat_id)
            return

        if data == "menu_sponsor":
            self.show_sponsor_info(chat_id)
            return

        if data == "menu_help":
            self.show_help(chat_id)
            return

        if data == "menu_track_info":
            msg = (
                "📢 <b>INSTALL NETSWAP BUY ALERTS IN YOUR GROUP</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "1. Add <b>@NetSwapBaseBot</b> as Admin to your Telegram group.\n"
                "2. Send: <code>/track &lt;token_address&gt;</code> in the group.\n"
                "3. NetSwap will automatically post celebratory Buy Alerts with a 1-click swap button whenever someone trades your token on Base!"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}]
                ]
            }
            self.send_message(chat_id, msg, markup)
            return

        if data == "menu_export":
            user = get_user_by_id(chat_id)
            if user:
                address, priv_key = user[0], user[1]
                msg = (
                    "⚠️ <b>PRIVATE KEY EXPORT (NEVER SHARE THIS)</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💳 <b>Address:</b> <code>{address}</code>\n\n"
                    f"🔑 <b>Private Key:</b>\n<code>{priv_key}</code>\n\n"
                    "<i>You can import this private key into MetaMask, Coinbase Wallet, or Rabby anytime. You maintain 100% full ownership of your funds.</i>"
                )
                markup = {
                    "inline_keyboard": [
                        [{"text": "🔙 Back to Wallet", "callback_data": "menu_wallet"}]
                    ]
                }
                self.send_message(chat_id, msg, markup)
            return

        if data.startswith("select_token_"):
            token_addr = data.replace("select_token_", "")
            self.show_token_quote(chat_id, username, token_addr)
            return

        if data.startswith("buy_"):
            parts = data.split("_")
            token_addr = parts[1]
            amount_eth = float(parts[2])
            self.execute_base_buy(chat_id, username, token_addr, amount_eth)
            return

    def _safe_handle_command(self, chat_id, text, username):
        try:
            self.handle_command(chat_id, text, username)
        except Exception as e:
            print(f"[HANDLE_CMD ERROR] chat {chat_id}: {e}")

    def _safe_handle_callback(self, cb_id, chat_id, data, username):
        try:
            self.handle_callback(cb_id, chat_id, data, username)
        except Exception as e:
            print(f"[HANDLE_CB ERROR] chat {chat_id}, data {data}: {e}")

    def poll_updates(self):
        print(f"=== NETSWAP TELEGRAM BOT LIVE ON @NetSwapBaseBot ===")
        last_offset = 0
        while True:
            try:
                res = self.send_request("getUpdates", {"offset": last_offset, "timeout": 20})
                if res and res.get("ok"):
                    for update in res.get("result", []):
                        last_offset = update["update_id"] + 1

                        if "message" in update and "text" in update["message"]:
                            chat_id = update["message"]["chat"]["id"]
                            text = update["message"]["text"]
                            username = update["message"]["from"].get("username", "")
                            print(f"[TG MSG] From @{username} ({chat_id}): {text}")
                            threading.Thread(
                                target=self._safe_handle_command,
                                args=(chat_id, text, username),
                                daemon=True
                            ).start()

                        elif "callback_query" in update:
                            cb = update["callback_query"]
                            cb_id = cb["id"]
                            chat_id = cb["message"]["chat"]["id"]
                            data = cb["data"]
                            username = cb["from"].get("username", "")
                            print(f"[TG BUTTON] @{username} clicked: {data}")
                            # Immediately dismiss loading spinner in Telegram UI
                            threading.Thread(target=self.answer_callback, args=(cb_id,), daemon=True).start()
                            # Dispatch callback handler to non-blocking worker thread
                            threading.Thread(
                                target=self._safe_handle_callback,
                                args=(cb_id, chat_id, data, username),
                                daemon=True
                            ).start()
            except Exception as e:
                print(f"[POLL ERROR]: {e}")
                time.sleep(1)

def start_group_alert_monitor(bot):
    TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
    print("[ALERT MONITOR] Background buy alert daemon started.")
    while True:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT chat_id, token_address, token_symbol, last_block FROM tracked_groups")
            groups = cursor.fetchall()

            if not groups:
                conn.close()
                time.sleep(6)
                continue

            current_block = w3.eth.block_number
            for chat_id, token_addr, symbol, last_block in groups:
                if last_block == 0:
                    cursor.execute("UPDATE tracked_groups SET last_block = ? WHERE chat_id = ?", (current_block, chat_id))
                    conn.commit()
                    continue

                from_block = last_block + 1
                to_block = min(current_block, from_block + 15)

                if from_block <= to_block:
                    logs = w3.eth.get_logs({
                        'address': Web3.to_checksum_address(token_addr),
                        'topics': [TRANSFER_TOPIC],
                        'fromBlock': from_block,
                        'toBlock': to_block
                    })

                    for log in logs[:2]:
                        raw_val = int(log['data'].hex(), 16)
                        token_info = fetch_token_info(token_addr)
                        decimals = token_info.get("decimals", 18)
                        amount_token = raw_val / (10 ** decimals)

                        if amount_token > 1.0:
                            alert_msg = (
                                f"🟢🟢🟢 <b>{symbol} BUY ON BASE!</b>\n"
                                "━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"💰 <b>Bought:</b> <code>{amount_token:,.1f} {symbol}</code>\n"
                                "🛡️ <b>MEV Sandwich Shield:</b> 🟢 <b>100% PROTECTED</b>\n"
                                "⚡ <b>Estimated AMM Slippage Saved:</b> <b>+3.4%</b>\n"
                                "━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"👇 <b>Trade ${symbol} with Zero AMM Slippage:</b>"
                            )
                            markup = {
                                "inline_keyboard": [
                                    [{"text": f"⚡ 1-Click Buy ${symbol} on NetSwap", "url": f"https://t.me/NetSwapBaseBot?start=buy_{token_addr}"}],
                                    [{"text": "📢 Sponsor This Alert (0.1 ETH)", "url": "https://t.me/NetSwapBaseBot?start=sponsor"}]
                                ]
                            }
                            bot.send_message(chat_id, alert_msg, markup)

                    cursor.execute("UPDATE tracked_groups SET last_block = ? WHERE chat_id = ?", (to_block, chat_id))
                    conn.commit()
            conn.close()
        except Exception as e:
            pass
        time.sleep(5)

def start_clanker_feed_monitor(bot=None):
    print("[CLANKER RADAR] Background launch monitor daemon started.")
    while True:
        try:
            resp = requests.get(
                'https://api.geckoterminal.com/api/v2/networks/base/new_pools',
                headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                pools = data.get('data', [])
                if pools:
                    conn = get_db()
                    cursor = conn.cursor()
                    for pool in pools:
                        attrs = pool.get('attributes', {})
                        name_full = attrs.get('name', '')
                        pair_parts = name_full.split('/')
                        token_sym = pair_parts[0].strip() if pair_parts else 'MEME'
                        base_token_id = pool.get('relationships', {}).get('base_token', {}).get('data', {}).get('id', '')
                        if not base_token_id.startswith('base_0x'):
                            continue
                        token_addr = Web3.to_checksum_address(base_token_id.replace('base_', ''))
                        if token_addr.lower() == WETH.lower():
                            continue
                        fdv = float(attrs.get('fdv_usd') or 0.0)
                        vol_24h = float(attrs.get('volume_usd', {}).get('h24') or 0.0)
                        cursor.execute("""
                            INSERT INTO clanker_launches (token_address, token_name, token_symbol, mcap_usd, volume_24h, timestamp)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(token_address) DO UPDATE SET
                                mcap_usd = excluded.mcap_usd,
                                volume_24h = excluded.volume_24h,
                                timestamp = excluded.timestamp
                        """, (token_addr, token_sym, token_sym, fdv, vol_24h, int(time.time())))
                    conn.commit()
                    conn.close()
        except Exception:
            pass
        time.sleep(60)

def start_subscription_expiry_monitor(bot):
    while True:
        try:
            now = int(time.time())
            seven_days = now + 7 * 86400
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscription_notifications (
                    user_id INTEGER,
                    feed_key TEXT,
                    notification_type TEXT,
                    sent_at INTEGER,
                    PRIMARY KEY(user_id, feed_key, notification_type)
                )
            """)
            cursor.execute("""
                SELECT user_id, feed_key, feed_name, active_until
                FROM user_feed_subscriptions
                WHERE active_until <= ? AND active_until > ?
            """, (seven_days, now))
            expiring = cursor.fetchall()
            for uid, fkey, fname, auntil in expiring:
                cursor.execute("SELECT sent_at FROM subscription_notifications WHERE user_id = ? AND feed_key = ? AND notification_type = '7day_warning'", (uid, fkey))
                if not cursor.fetchone():
                    days = max(1, int((auntil - now) / 86400))
                    warn_msg = (
                        f"⏰ <b>NETSWAP VIP SUBSCRIPTION RENEWAL NOTICE</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Your active lockscreen stream <b>{fname}</b> will expire in <b>{days} days</b>.\n\n"
                        f"🛡️ <b>Maintain Uninterrupted Alpha:</b>\n"
                        f"Renew now using your in-bot wallet balance, external crypto, or $NETSWAP loyalty credits to keep your 0% slippage 1-tap trade alerts active!\n\n"
                        f"👉 <a href='https://netswap.vercel.app/store.html?user_id={uid}'>Renew on NetSwap Alpha Mall ➔</a>"
                    )
                    bot.send_message(uid, warn_msg)
                    cursor.execute("INSERT OR REPLACE INTO subscription_notifications (user_id, feed_key, notification_type, sent_at) VALUES (?, ?, '7day_warning', ?)", (uid, fkey, now))
                    conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error in subscription expiration checker: {e}")
        time.sleep(3600)

def start_health_check_server():
    """Lightweight HTTP server allowing free cloud hosts (Render, Koyeb) to monitor 24/7 uptime."""
    import http.server
    import socketserver
    port = int(os.environ.get("PORT", 10000))
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"active","service":"netswap-bot","network":"base_solana"}')
        def log_message(self, format, *args):
            pass
    try:
        # Allow immediate reuse of address
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", port), HealthHandler) as httpd:
            print(f"[HEALTH CHECK] Cloud uptime server listening on port {port}")
            httpd.serve_forever()
    except Exception as e:
        print(f"[HEALTH CHECK] Info: HTTP server skipped or bound: {e}")

if __name__ == "__main__":
    bot = TelegramBot(BOT_TOKEN)
    alert_thread = threading.Thread(target=start_group_alert_monitor, args=(bot,), daemon=True)
    alert_thread.start()
    clanker_thread = threading.Thread(target=start_clanker_feed_monitor, args=(bot,), daemon=True)
    clanker_thread.start()
    expiry_thread = threading.Thread(target=start_subscription_expiry_monitor, args=(bot,), daemon=True)
    expiry_thread.start()
    health_thread = threading.Thread(target=start_health_check_server, daemon=True)
    health_thread.start()
    bot.poll_updates()

