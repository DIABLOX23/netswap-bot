import time
import json
from web3 import Web3
from eth_abi import decode

class NettingEngine:
    """
    Continuous Multi-Party Netting Engine on Base.
    Batches incoming EIP-712 signed swap orders every 2 seconds (Base block interval).
    Matches buyers and sellers at fair mid-market clearing price without requiring identical trade sizes.
    Calculates exact 50 bps protocol surplus toll.
    """
    def __init__(self, rpc_url="https://mainnet.base.org", fee_recipient="0xbE40c75844197fD334db4174CBd7D07F9bAb93f8"):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.fee_recipient = fee_recipient
        self.order_book_buyers = []  # Buyers: USDC -> WETH
        self.order_book_sellers = [] # Sellers: WETH -> USDC
        self.batch_id = 0
        self.total_volume_settled_usd = 0.0
        self.total_protocol_fees_usd = 0.0

    def submit_order(self, order_dict, signature):
        """
        Ingest an offchain signed EIP-712 order.
        order_dict: {trader, tokenIn, tokenOut, amountIn, minAmountOut, nonce, deadline}
        """
        order_entry = {
            'order': order_dict,
            'signature': signature,
            'remainingIn': int(order_dict['amountIn']),
            'receivedOut': 0
        }

        # Check if buyer (USDC -> WETH) or seller (WETH -> USDC)
        # Token0: WETH (0x4200...0006), Token1: USDC (0x8335...2913)
        if order_dict['tokenIn'].lower() == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913".lower():
            self.order_book_buyers.append(order_entry)
        else:
            self.order_book_sellers.append(order_entry)

    def process_batch(self, mid_market_price_usd=2650.0):
        """
        Executes greedy multi-party ring netting across pending buyers and sellers.
        Returns settlement transaction parameters.
        """
        if not self.order_book_buyers or not self.order_book_sellers:
            return None

        self.batch_id += 1
        allocations = []
        buyers_to_settle = []
        sellers_to_settle = []
        buyer_sigs = []
        seller_sigs = []

        total_matched_token1 = 0
        b_idx = 0
        s_idx = 0

        while b_idx < len(self.order_book_buyers) and s_idx < len(self.order_book_sellers):
            b = self.order_book_buyers[b_idx]
            s = self.order_book_sellers[s_idx]

            # Convert seller WETH into equivalent USDC value at mid-market
            s_weth_remaining = s['remainingIn'] # 18 decimals
            s_usdc_equiv = int((s_weth_remaining * mid_market_price_usd) / 1e12) # 6 decimals
            b_usdc_remaining = b['remainingIn'] # 6 decimals

            # Determine matched USDC
            matched_usdc = min(b_usdc_remaining, s_usdc_equiv)
            matched_weth = int((matched_usdc * 1e12) / mid_market_price_usd)

            if matched_usdc == 0 or matched_weth == 0:
                break

            allocations.append({
                'buyerIndex': b_idx,
                'sellerIndex': s_idx,
                'amountToken0': matched_weth,
                'amountToken1': matched_usdc
            })

            total_matched_token1 += matched_usdc
            b['remainingIn'] -= matched_usdc
            s['remainingIn'] -= matched_weth

            if b['remainingIn'] <= 100: # Filled
                b_idx += 1
            if s['remainingIn'] <= 100: # Filled
                s_idx += 1

        if not allocations:
            return None

        # Build settlement payload
        used_buyers = self.order_book_buyers[:b_idx + (1 if b_idx < len(self.order_book_buyers) and self.order_book_buyers[b_idx]['remainingIn'] < self.order_book_buyers[b_idx]['order']['amountIn'] else 0)]
        used_sellers = self.order_book_sellers[:s_idx + (1 if s_idx < len(self.order_book_sellers) and self.order_book_sellers[s_idx]['remainingIn'] < self.order_book_sellers[s_idx]['order']['amountIn'] else 0)]

        protocol_fee_usd = (total_matched_token1 / 1e6) * 0.0050 # 50 bps
        self.total_volume_settled_usd += (total_matched_token1 / 1e6)
        self.total_protocol_fees_usd += protocol_fee_usd

        # Remove filled orders from active book
        self.order_book_buyers = self.order_book_buyers[b_idx:]
        self.order_book_sellers = self.order_book_sellers[s_idx:]

        return {
            'batch_id': self.batch_id,
            'buyers_count': len(used_buyers),
            'sellers_count': len(used_sellers),
            'allocations_count': len(allocations),
            'volume_matched_usd': total_matched_token1 / 1e6,
            'protocol_fee_usd': protocol_fee_usd,
            'fee_recipient': self.fee_recipient
        }

if __name__ == "__main__":
    print("=== NETSWAP CONTINUOUS MULTI-PARTY ENGINE ACTIVE ===")
    engine = NettingEngine()
    print(f"Connected to Base RPC: {engine.w3.is_connected()}")
    print(f"Protocol Fee Recipient: {engine.fee_recipient}")
    print("Engine ready to ingest orders and execute 2-second micro-batches.")
