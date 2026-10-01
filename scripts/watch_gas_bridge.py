"""
AETERNA GAS BRIDGE WATCHER
==========================
Monitors Base Mainnet wallet 0xcc12fD53A0ba26f42FEA6fF8b285a77aa54B170d
for incoming ETH / USDC tips from the Warpcast crowdfund.
"""

import urllib.request
import json
import time
import sys

TARGET_ADDRESS = "0xcc12fD53A0ba26f42FEA6fF8b285a77aa54B170d"
RPC_URL = "https://mainnet.base.org"

def check_balance():
    data = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBalance",
        "params": [TARGET_ADDRESS, "latest"]
    }).encode("utf-8")
    
    req = urllib.request.Request(RPC_URL, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    })
    
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            bal_wei = int(res_data.get("result", "0x0"), 16)
            return bal_wei / 1e18
    except Exception as e:
        return None

if __name__ == "__main__":
    bal = check_balance()
    if bal is not None:
        print(f"Current Base ETH Balance: {bal:.8f} ETH")
    else:
        print("Failed to query Base RPC")
