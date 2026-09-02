# Adding Twelve Data API Key to GitHub

## ⚠️ SECURITY WARNING
Your API key `2d0afc09cfa64b3fb45f86cb17c11da8` was shared in this conversation.

**Action Required:** After setup, regenerate your API key at:
https://twelvedata.com/account → API Keys → Regenerate

---

## Step 1: Add Secret to GitHub Repository

1. Go to your repository: https://github.com/amanaman3786/XAUUSD-Bot-2

2. Click **Settings** (top right)

3. In left sidebar, click **Secrets and variables** → **Actions**

4. Click **New repository secret** button

5. Add the secret:
   - **Name:** `TWELVE_DATA_API_KEY`
   - **Value:** `2d0afc09cfa64b3fb45f86cb17c11da8`
   - Click **Add secret**

---

## Step 2: Verify Secret is Added

You should see three secrets in your repository:
- ✅ `TELEGRAM_BOT_TOKEN` (already exists)
- ✅ `TELEGRAM_CHAT_ID` (already exists)  
- ✅ `TWELVE_DATA_API_KEY` (just added)

---

## What This Enables

### **Data Source Priority (Automatic):**

1. **Primary:** yfinance (GC=F) - Gold Futures, 15-min delay
2. **Fallback:** Twelve Data (XAUUSD) - Real-time spot gold, < 1-min delay

### **When Twelve Data Activates:**
- If yfinance fails (network issue, rate limit, etc.)
- Automatically switches to Twelve Data
- Gets real-time spot gold price
- Continues analysis without interruption

### **Free Tier Limits:**
- 800 API calls per day
- Bot runs every 15 minutes = 96 calls/day
- **You're well within limits!** ✅

---

## Testing

After adding the secret to GitHub, the bot will automatically use Twelve Data as fallback.

You'll see in the logs:
```
INFO - Twelve Data client initialized as fallback
INFO - Fetching from yfinance: M15 (interval=15m, period=1d)
INFO - ✓ yfinance: 15 candles for M15
```

If yfinance fails:
```
WARNING - yfinance failed for M15: [error]
INFO - Falling back to Twelve Data for M15
INFO - ✓ Twelve Data: 96 candles for M15
```

---

## After Setup - Regenerate API Key

**IMPORTANT:** Once the bot is working, regenerate your API key:

1. Go to https://twelvedata.com/account
2. Click on your API key
3. Click **Regenerate**
4. Copy new key
5. Update GitHub secret: `TWELVE_DATA_API_KEY` with new value

This invalidates the old key that was exposed in this conversation.

---

## Summary

✅ API key added to local `.env.template`  
⏳ **YOU NEED TO:** Add secret to GitHub (see Step 1 above)  
⏳ **AFTER WORKING:** Regenerate API key for security  

---

**Next:** Add the secret to GitHub, then push all code changes.
