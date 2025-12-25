# How to Deploy "Ok Boomer" Bot (Free 24/7 Hosting)

This guide will show you how to host your Telegram bot for **FREE** on **Render.com** and keep it running 24/7 using **UptimeRobot**.

---

## 🚀 Phase 1: Push to GitHub

1.  **Create a New Repo**: Go to GitHub and create a new repository called `ok-boomer-bot`.
2.  **Push Code**: Run these commands in your bot folder:
    ```bash
    git init
    git add .
    git commit -m "Initial commit"
    git branch -M main
    git remote add origin https://github.com/YOUR_USERNAME/ok-boomer-bot.git
    git push -u origin main
    ```

---

## ☁️ Phase 2: Deploy on Render

1.  **Sign Up**: Go to [dashboard.render.com](https://dashboard.render.com/) and log in with GitHub.
2.  **New Service**: Click **New +** -> **Web Service** (Do NOT choose background worker or static site).
3.  **Connect Repo**: Select your `ok-boomer-bot` repository.
4.  **Configure**:
    *   **Name**: `ok-boomer-bot`
    *   **Drag and drop these files** into the browser:
        *   `package.json`
        *   `boomer_bot.js`
        *   `Dockerfile`
        *   `README_DEPLOY.md`
    *   **Build Command**: `npm install`
    *   **Start Command**: `npm start`
    *   **Plan**: Select **Free**.
5.  **Environment Variables**:
    *   Scroll down to **Environment Variables**.
    *   Key: `TELEGRAM_BOT_TOKEN`
    *   Value: `(Paste your actual bot token from BotFather here)`
6.  **Deploy**: Click **Create Web Service**.

> ⏳ **Wait**: Render will build your bot. Once done, you should see "Your service is live" and a URL like `https://ok-boomer-bot.onrender.com`.

---

## ⚡ Phase 3: Keep It Alive (CRITICAL)

**The Problem**: On the Free Tier, Render puts your bot to sleep if no one visits that URL for 15 minutes.
**The Solution**: We use a free "pinger" service to visit that URL every 5 minutes, keeping it awake forever.

1.  **Go to UptimeRobot**: Visit [uptimerobot.com](https://uptimerobot.com/) and create a free account.
2.  **Add Monitor**:
    *   Click **Add New Monitor**.
    *   **Monitor Type**: `HTTP(s)`
    *   **Friendly Name**: `Ok Boomer Bot`
    *   **URL (or IP)**: Paste your Render URL (e.g., `https://ok-boomer-bot.onrender.com`).
    *   **Monitoring Interval**: `5 minutes` (This is important!).
    *   **Alert Contacts**: Uncheck (you don't need emails when it's working).
3.  **Start**: Click **Create Monitor**.

---

## ✅ Verification

1.  Wait 10 minutes.
2.  Send `/start` to your bot on Telegram.
3.  If it replies instantly, **congratulations!** You have a free, 24/7 Telegram bot.
