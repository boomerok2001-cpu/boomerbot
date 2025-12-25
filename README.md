# 🦅 PolyHawk Intelligence Bot

High-speed intelligence terminal for Polymarket.

## 🚀 "Degen Terminal" Features

- **💼 Portfolio Tracker**: Real-time wallet analysis with all-time PnL, win rates, and open positions.
- **🐋 Whale Watcher**: Automatic alerts for trades >$10k and smart-money identification.
- **🏴‍☠️ Degen News Scope**: Specialized news engine that filters for alpha-heavy keywords (insider, breakout, leaked) and matches them to active markets.
- **📊 Insider Detection**: Real-time Monitoring for 20%+ volume spikes in 10-minute windows.
- **📈 Price Action**: Instant alerts for >5% price movements in tracked markets.

## 🛠 Commands

- `/start`: Open the Intelligence Terminal.
- `/portfolio <address>`: Instant wallet performance snapshot.
- `/track <address>`: Monitor a specific wallet for all future movements.
- `/whales`: View the top-performing whale leaderboard.

## ⚙️ Setup

1. Copy `.env.example` to `.env`
2. Add your `TELEGRAM_BOT_TOKEN` (from @BotFather)
3. Add your `NEWS_API_KEY` (from newsapi.org)
4. Install dependencies: `pip install -r requirements.txt`
5. Run the bot: `python bot.py`

## 📡 Intelligence Feed Status
- **Gamma API**: Connected
- **CLOB API**: Connected
- **News Engine**: Active (Degen Mode)
