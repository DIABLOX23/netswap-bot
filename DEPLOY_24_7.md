# 🌐 NETSWAP 24/7/365 ZERO-DOWNTIME SETUP GUIDE

This guide answers your questions and gives you the exact **100% FREE** setups to keep your entire NetSwap ecosystem running **24/7/365 non-stop**, even when your laptop is closed, sleeping, or turned completely off.

---

## 1. What Stays Online 24/7/365?

| Component | Status | Does it need your laptop? | Monthly Cost |
| :--- | :--- | :--- | :--- |
| **NetSwap Website & DEX** (`https://netswap.vercel.app`) | 🟢 **100% LIVE 24/7** | **NO.** Hosted on Vercel's global edge cloud. Always on worldwide. | **$0.00** |
| **Loss Audit Tool** (`/audit.html`) | 🟢 **100% LIVE 24/7** | **NO.** Serverless edge execution. | **$0.00** |
| **VIP Alpha Mall** (`/store.html`) | 🟢 **100% LIVE 24/7** | **NO.** Web3 client-side + Edge. | **$0.00** |
| **Telegram Bot** (`@NetSwapBaseBot`) | 🟢 **Runs 24/7** once deployed via Method 1 or 2 below. | Depends on method (Method 1: laptop closed, Method 2: cloud). | **$0.00** |
| **Flash-Arb Profit Hunter** (`runner.py`) | 🟢 **Runs 24/7** once deployed via Method 1 or 2. | Continuously checks Base DEX pools for zero-risk spreads. | **$0.00** |
| **Fee Routing & Wallets** (MetaMask & Phantom) | 🟢 **100% AUTOMATIC** | Dual treasury routes 0.85% to MetaMask & 100% of VIP to Phantom. | **$0.00** |

---

## 🏆 METHOD 1: The "Lid Closed" Laptop Server (100% Free, 0 Signups, Ready in 30 Seconds)

If you don't want to sign up for any cloud services or push code to GitHub right now, you can turn your Windows laptop into a **dedicated 24/7 server** in 30 seconds:

1. Press `Windows Key + R`, type `control`, and hit **Enter** (opens Control Panel).
2. Go to **Hardware and Sound** ➔ **Power Options**.
3. In the left sidebar, click **"Choose what closing the lid does"**.
4. Change **"When I close the lid"** to:
   - On battery: **Do nothing**
   - Plugged in: **Do nothing**
5. Click **"Save changes"**.
6. Under your current plan, click **"Change plan settings"**:
   - Set **"Turn off the display"**: 5 minutes (saves power & protects your screen).
   - Set **"Put the computer to sleep"**: **Never** (keeps the bot and background processes running).
7. **Done!** Now plug your laptop into the charger and close the screen. 
   - The screen turns off to save electricity.
   - The bot (`@NetSwapBaseBot`) and flash-arb engine keep responding 24/7/365 without stopping.

---

## ☁️ METHOD 2: Cloud 24/7 on Render.com + UptimeRobot (100% Free Forever, No Credit Card)

If you want your laptop completely powered off while the bot runs on high-speed cloud servers:

### Why Render is 100% Free:
Render gives **750 free instance hours every month** (a full 31-day month is only 744 hours, so it never runs out). We added a built-in health ping server on port 10000 into `bot.py` so Render treats it as a Free Web Service.

### Step-by-Step Cloud Deployment:
1. **Create a GitHub Repository:**
   - Go to [github.com/new](https://github.com/new).
   - Name it `netswap-bot` (Private or Public).
   - Upload the files in `scratch/netswap/bot` (`bot.py`, `solana_engine.py`, `requirements.txt`, `Procfile`, `Dockerfile`, `netswap_bot.db`).
2. **Deploy on Render:**
   - Go to [render.com](https://render.com) and click **"Sign In with GitHub"** (100% free, no credit card required).
   - Click **"New +"** ➔ **"Web Service"**.
   - Select your `netswap-bot` GitHub repository.
   - Settings:
     - **Runtime:** `Python 3`
     - **Build Command:** `pip install -r requirements.txt`
     - **Start Command:** `python -u bot.py`
     - **Instance Type:** `Free ($0/month)`
   - Click **"Deploy Web Service"**.
   - Once deployed, Render gives you a free URL (e.g. `https://netswap-bot.onrender.com`).
3. **Keep Awake Forever with UptimeRobot (Free):**
   - Render Free services sleep after 15 minutes of inactivity if no HTTP traffic arrives.
   - Go to [uptimerobot.com](https://uptimerobot.com) (100% free forever, no credit card).
   - Click **"Add New Monitor"**:
     - Monitor Type: `HTTP(s)`
     - Friendly Name: `NetSwap Bot`
     - URL: `https://netswap-bot.onrender.com`
     - Monitoring Interval: `Every 5 minutes`
   - Click **"Create Monitor"**.
   - **Result:** UptimeRobot pings the bot every 5 minutes. The bot never sleeps and runs 24 hours a day, 365 days a year without costing a cent!

---

## ⚡ Summary
- **Website:** ALREADY running 24/7 on Vercel Edge (`https://netswap.vercel.app`).
- **Bot & Flash-Arb:** Ready to run 24/7 via Method 1 (instant) or Method 2 (cloud).
