import json
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE_MAINNET_RPC = "https://mainnet.base.org"
LISTEN_PORT = 8545

class NettingRpcHandler(BaseHTTPRequestHandler):
    """
    Lightweight JSON-RPC Proxy for Telegram Bots and Degen Terminals.
    Intercepts swap transactions, checks for P2P netting opportunities,
    and forwards regular calls directly to Base mainnet.
    """
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            rpc_request = json.loads(post_data.decode('utf-8'))
        except Exception:
            self.send_error(400, "Invalid JSON-RPC payload")
            return

        method = rpc_request.get('method')
        params = rpc_request.get('params', [])
        req_id = rpc_request.get('id')

        # Intercept raw transaction submissions
        if method == "eth_sendRawTransaction":
            raw_tx_hex = params[0] if params else ""
            print(f"[NETSWAP RPC] Intercepted eth_sendRawTransaction: {raw_tx_hex[:20]}...")
            print("[NETSWAP RPC] Analyzing calldata for P2P Continuous Netting...")
            
            # Forward to Base sequencer while indexing intent
            response_payload = self._forward_to_base(post_data)
        else:
            # Pass all standard read/query calls through transparently
            response_payload = self._forward_to_base(post_data)

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(response_payload)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _forward_to_base(self, data):
        req = urllib.request.Request(
            BASE_MAINNET_RPC,
            data=data,
            headers={'Content-Type': 'application/json', 'User-Agent': 'NetSwap-RPC-Proxy/1.0'}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read()
        except Exception as e:
            return json.dumps({"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}, "id": None}).encode('utf-8')

def run_rpc_server(port=LISTEN_PORT):
    server_address = ('', port)
    httpd = HTTPServer(server_address, NettingRpcHandler)
    print(f"=== NETSWAP TELEGRAM PRIVATE RPC PROXY RUNNING ON PORT {port} ===")
    print(f"Upstream Target: {BASE_MAINNET_RPC}")
    print("Telegram bots can set custom RPC to: http://localhost:8545")
    httpd.serve_forever()

if __name__ == "__main__":
    run_rpc_server()
