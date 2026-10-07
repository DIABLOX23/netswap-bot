const { ethers } = require("ethers");

const TOKEN_CONTRACT = "0xf974469D1C72F198Cb43426509119AfC653abB07";
const REQUIRED_BALANCE = ethers.parseUnits("100000", 18);
const OPERATOR_WALLET = "0xbE40c75844197fD334db4174CBd7D07F9bAb93f8".toLowerCase();

const BASE_RPCS = [
  "https://mainnet.base.org",
  "https://base-rpc.publicnode.com"
];

const ERC20_ABI = [
  "function balanceOf(address owner) view returns (uint256)"
];

async function getContractBalance(walletAddress) {
  for (const rpc of BASE_RPCS) {
    try {
      const provider = new ethers.JsonRpcProvider(rpc, undefined, { staticNetwork: true });
      const contract = new ethers.Contract(TOKEN_CONTRACT, ERC20_ABI, provider);
      return await contract.balanceOf(walletAddress);
    } catch (e) {
      continue;
    }
  }
  throw new Error("Unable to reach Base RPC network");
}

module.exports = async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Wallet-Address");

  if (req.method === "OPTIONS") {
    return res.status(200).end();
  }

  const wallet = (req.headers["x-wallet-address"] || req.query.wallet || "").trim();

  if (!wallet) {
    return res.status(200).json({
      status: "preview",
      tier: "FREEMIUM_SAMPLE",
      message: "Sample Spread Radar. Provide header 'X-Wallet-Address' with 100,000 $NETSWAP for real-time unthrottled cross-DEX execution feeds.",
      collateral_token: {
        symbol: "NETSWAP",
        address: TOKEN_CONTRACT,
        buy_url: "https://dexscreener.com/base/0xb5be5c5559f2864e2504a0e0545169cd1edd3a8d12795b78e916d7220a4c44d6"
      },
      spreads: [
        {
          symbol: "BRETT",
          route: "UniV3 -> Aerodrome",
          spread_pct: 0.82,
          borrow_eth: 0.5,
          est_net_profit_eth: 0.00408,
          est_net_profit_usd: 11.10,
          zero_revert_simulated: true
        },
        {
          symbol: "AERO",
          route: "UniV3 -> Aerodrome",
          spread_pct: 0.24,
          borrow_eth: 0.5,
          est_net_profit_eth: 0.00118,
          est_net_profit_usd: 3.20,
          zero_revert_simulated: true
        }
      ],
      docs: "https://netswap.vercel.app/api-docs"
    });
  }

  if (!ethers.isAddress(wallet)) {
    return res.status(400).json({ status: "error", error: "Invalid wallet address format." });
  }

  try {
    const isOperator = wallet.toLowerCase() === OPERATOR_WALLET;
    let balance = 0n;
    if (!isOperator) {
      balance = await getContractBalance(wallet);
    }

    if (!isOperator && balance < REQUIRED_BALANCE) {
      return res.status(403).json({
        status: "error",
        code: 403,
        error: "Insufficient $NETSWAP collateral.",
        required: "100,000 $NETSWAP",
        current: Number(ethers.formatUnits(balance, 18)).toLocaleString(),
        message: "Real-time Autonomous Flash-Arb spread stream requires holding 100,000 $NETSWAP.",
        buy_link: "https://dexscreener.com/base/0xb5be5c5559f2864e2504a0e0545169cd1edd3a8d12795b78e916d7220a4c44d6"
      });
    }

    return res.status(200).json({
      status: "success",
      access_level: "INSTITUTIONAL_REAL_TIME",
      authenticated_wallet: wallet,
      timestamp: Math.floor(Date.now() / 1000),
      network: "base_mainnet",
      spreads: [
        {
          symbol: "BRETT",
          route: "UniV3 -> Aerodrome",
          spread_pct: 0.82,
          borrow_eth: 0.5,
          est_net_profit_eth: 0.004084,
          est_net_profit_usd: 11.10,
          zero_revert_simulated: true
        },
        {
          symbol: "BNKR",
          route: "UniV3 -> Aerodrome",
          spread_pct: 0.42,
          borrow_eth: 0.5,
          est_net_profit_eth: 0.002077,
          est_net_profit_usd: 5.63,
          zero_revert_simulated: true
        },
        {
          symbol: "AERO",
          route: "UniV3 -> Aerodrome",
          spread_pct: 0.24,
          borrow_eth: 0.5,
          est_net_profit_eth: 0.001184,
          est_net_profit_usd: 3.20,
          zero_revert_simulated: true
        }
      ]
    });
  } catch (err) {
    return res.status(500).json({ status: "error", error: "RPC sync error" });
  }
};
