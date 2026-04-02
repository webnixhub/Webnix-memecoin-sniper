# Memecoin Sniper Bot — Railway Deploy Guide

## Files in this folder
- memecoin_sniper_bot.py  ← main bot
- requirements.txt        ← dependencies
- Procfile                ← tells Railway how to run

---

## STEP 1 — GitHub Setup (one time)

1. Go to github.com → Sign up free
2. Click "New repository"
3. Name it: memecoin-sniper
4. Set to Private
5. Click "Create repository"
6. Upload all 3 files from this folder

---

## STEP 2 — Railway Deploy

1. Go to railway.com → Sign up with GitHub
2. Click "New Project"
3. Click "Deploy from GitHub repo"
4. Select your memecoin-sniper repo
5. Railway will auto-detect and deploy

---

## STEP 3 — Add Environment Variables (IMPORTANT)

In Railway dashboard:
1. Click your project
2. Click "Variables" tab
3. Add these:

   BOT_TOKEN   = your_telegram_bot_token
   CHAT_ID     = your_telegram_chat_id
   BIRDEYE_KEY = your_birdeye_key (optional)

DO NOT paste tokens directly in the code when deploying online.

---

## STEP 4 — Make sure Worker is running

1. In Railway → click your service
2. Click "Settings"
3. Under "Deploy" → check Start Command is:
   python memecoin_sniper_bot.py
4. Or it reads from Procfile automatically

---

## STEP 5 — Check logs

In Railway dashboard → click your service → "Logs" tab
You should see:
   MEMECOIN SNIPER BOT v3.0 - STARTING
   --- Cycle 1 ---
   DexScreener: 78 unique -> 10 within 120m

---

## Troubleshooting

Bot not starting?
→ Check Variables tab — BOT_TOKEN and CHAT_ID must be set

No alerts after 10 minutes?
→ Lower MIN_SCORE to 2 in the code

Railway sleeping?
→ Free tier stays awake as long as you have credit
→ Check Usage tab — $5 free credit resets monthly

---

## Cost
Railway free tier = $5 credit/month
This bot uses ~$0.50-1.00/month (very lightweight)
So it runs FREE for months on free credit.
