# GitHub Actions Workflow - Live Trading Bot

This workflow runs your XAUUSD Trading Bot **live** on GitHub Actions servers, scanning real-time market data and sending signals to your Telegram.

---

## 📋 **How It Works**

### **Schedule:**
- Runs **every 15 minutes** automatically
- Checks if Gold market is open (Monday-Friday, Sunday 22:00+)
- Skips analysis when market is closed (weekends)
- Uses **real-time data from yfinance** (NOT historical CSV)

### **What It Does:**
1. ✅ Fetches live XAUUSD price data from yfinance
2. ✅ Runs all 3 trading methods (Combined, Percentage, Liquidity SAR)
3. ✅ Checks for high-confluence setups
4. ✅ **Sends signals to YOUR Telegram** when found
5. ✅ Automatically skips when market closed

---

## 🔐 **Required Setup**

### **Step 1: Add GitHub Secrets**

You've already added these to GitHub → Settings → Secrets:

1. `TELEGRAM_BOT_TOKEN` - Your Telegram bot token ✅
2. `TELEGRAM_CHAT_ID` - Your Telegram chat ID ✅
3. `TWELVE_DATA_API_KEY` - Your Twelve Data API key (optional backup)

**These secrets are secure and never exposed in logs!**

---

## ⚙️ **Configuration**

### **Current Settings:**
- **Scan Interval:** Every 15 minutes
- **Market Hours Filter:** Enabled (auto-skips weekends)
- **Data Source:** yfinance (primary), Twelve Data (backup)
- **Methods:** All 3 methods enabled
- **Telegram:** Sends text-only notifications (no charts)

### **Customize Schedule:**

Edit `.github/workflows/live-bot.yml` line 5:

```yaml
# Every 15 minutes (current)
- cron: '*/15 * * * *'

# Every 30 minutes
- cron: '*/30 * * * *'

# Every hour
- cron: '0 * * * *'

# Every 5 minutes (more frequent)
- cron: '*/5 * * * *'
```

**Cron format:** `minute hour day month weekday`

---

## 🚀 **Usage**

### **Automatic (Default):**
- Workflow runs every 15 minutes automatically
- No action needed from you
- Signals arrive in your Telegram

### **Manual Trigger:**
1. Go to your repo → **Actions** tab
2. Click **"XAUUSD Live Trading Bot"**
3. Click **"Run workflow"**
4. Click **"Run workflow"** button
5. Bot scans immediately

---

## 📱 **What You'll Receive**

### **When Signal Found:**
```
🟢 Combined Method - Bullish Signal
━━━━━━━━━━━━━━━━━

📍 Entry: 2650.50
🛑 Stop Loss: 2645.00
🎯 Take Profit: 2665.00
⏰ Timeframe: M15

📊 Risk:Reward: 1:2.64

⭐ Confluence Score: 8
Details:
  • Daily OB aligned
  • H4 structure confirmed
  • FVG present at entry
  • Premium zone entry
  • IDM identified

🔄 Aligned TFs: D1, H4, H1, M15

⏱ 2026-08-30 14:30:00
```

### **No Signal:**
- Nothing sent to Telegram (bot stays quiet)
- This is NORMAL - bot is selective
- Typical: 1-5 signals per day across all methods

---

## 🕐 **Market Hours**

The bot automatically checks market hours:

**Market Open (Bot Runs):**
- ✅ Monday 00:00 - Friday 22:00 UTC
- ✅ Sunday 22:00 - 23:59 UTC

**Market Closed (Bot Skips):**
- ❌ Friday 22:00 - Sunday 22:00 UTC
- ❌ Saturday all day

---

## 📊 **Monitoring**

### **Check Workflow Runs:**
1. Go to your repo
2. Click **"Actions"** tab
3. See all workflow runs
4. Green ✅ = Success
5. Red ❌ = Error (check logs)

### **View Logs:**
1. Click on a workflow run
2. Click "Scan Market & Send Signals"
3. See full output:
   - Market status
   - Data fetched
   - Methods analyzed
   - Signals generated

---

## 💰 **Cost**

### **GitHub Actions:**
- **Free Tier:** 2,000 minutes/month
- **Usage:** ~1 minute per run
- **Frequency:** 96 runs/day (every 15 min)
- **Monthly:** ~2,880 runs = ~2,880 minutes

**You'll exceed free tier!** (~880 minutes over)

### **Solutions:**

**Option 1: Reduce Frequency** (Recommended)
```yaml
# Run every 30 minutes instead
- cron: '*/30 * * * *'
# Monthly: ~1,440 minutes (within free tier)
```

**Option 2: GitHub Pro** ($4/month)
- 3,000 minutes/month included
- Covers current usage

**Option 3: Run on Your Computer**
```bash
# Instead of GitHub Actions, run locally:
python src/main.py
```
- Free unlimited
- Uses your internet/power
- Must keep computer on

---

## ⚠️ **Important Notes**

### **Limitations:**
1. **No chart images** - Text-only signals (as configured)
2. **15-minute delay** - yfinance data is 15-min delayed (acceptable)
3. **GitHub Actions timeout** - Max 6 hours per run (won't affect 15-min scans)
4. **Rate limits** - yfinance has rate limits (rarely hit with 15-min intervals)

### **Best Practices:**
1. ✅ Monitor first 24 hours to ensure signals arrive
2. ✅ Keep GitHub Secrets secure
3. ✅ Check Actions tab if signals stop
4. ✅ Consider reducing frequency to stay in free tier

---

## 🔧 **Troubleshooting**

### **No Signals Arriving:**
- Check Actions tab for errors
- Verify secrets are set correctly
- Check Telegram bot is active
- Confirm market is open

### **Workflow Fails:**
- Check error logs in Actions tab
- Verify dependencies in requirements.txt
- Ensure secrets are correct

### **Too Many/Too Few Signals:**
- Adjust confluence thresholds in config/.env.template
- Change scan frequency (every 30 min instead of 15)

---

## 📈 **Expected Results**

### **Typical Day (Monday-Friday):**
```
06:00 - Workflow runs, market open, no signal
06:15 - Workflow runs, no signal
06:30 - Workflow runs, no signal
...
09:45 - 🟢 Combined Method signal sent to Telegram!
...
14:30 - 🔴 Liquidity SAR signal sent to Telegram!
...
21:45 - Workflow runs, no signal
22:00 - Market closes, workflow skips
```

**Total:** 1-5 quality signals per trading day

---

## ✅ **Summary**

This workflow:
- ✅ Runs your live bot on GitHub servers
- ✅ Scans every 15 minutes when market open
- ✅ Uses real-time data (NOT historical CSV)
- ✅ Sends signals to your Telegram
- ✅ Completely automated
- ✅ Free (within limits)

**Your trading bot is now running 24/7 in the cloud!** 🚀

---

**Status:** ✅ Ready to deploy to GitHub!
