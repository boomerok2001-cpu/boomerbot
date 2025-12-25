import asyncio
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os
from dotenv import load_dotenv
from datetime import datetime
import logging

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
POLYMARKET_API = "https://gamma-api.polymarket.com/markets"
CHECK_INTERVAL = 30  # Check every 30 seconds

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class NewMarketBot:
    def __init__(self):
        self.seen_markets = set()
        self.first_run = True

    async def fetch_markets(self):
        """Fetch newest markets from Polymarket"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    POLYMARKET_API,
                    params={
                        "limit": 20,
                        "active": "true",
                        "order": "createdAt",  # Sort by creation time
                        "ascending": "false"   # Newest first
                    }
                ) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
        return []

    async def monitor_markets(self, context: ContextTypes.DEFAULT_TYPE):
        """Check for new markets and alert"""
        markets = await self.fetch_markets()
        
        # On first run, just mark everything as seen to avoid spam
        if self.first_run:
            for market in markets:
                self.seen_markets.add(market.get('id'))
            self.first_run = False
            logger.info(f"✅ Bot initialized. Tracking {len(self.seen_markets)} existing markets.")
            return

        # Check for new markets
        for market in markets:
            market_id = market.get('id')
            
            if market_id not in self.seen_markets:
                self.seen_markets.add(market_id)
                await self.send_alert(context, market)

    async def send_alert(self, context: ContextTypes.DEFAULT_TYPE, market):
        """Send formatted alert to all users"""
        question = market.get('question', 'Unknown Market')
        slug = market.get('slug', '')
        # Handle cases where slug might be missing or ID used
        url = f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"
        
        # Try to parse creation time for "Just now" effect
        created_at = market.get('createdAt')
        
        msg = f"🆕 **JUST LISTED**\n"
        msg += f"━━━━━━━━━━━━━━\n"
        msg += f"📊 **{question}**\n\n"
        msg += f"🔗 [Trade Now]({url})"

        # Send to all users who started the bot
        # Note: In a real prod bot we'd use a database. 
        # For simplicity, we broadcast to the current chat if triggered, 
        # but since this is a job, we need a stored chat_id. 
        # We'll use a globally stored chat_id from the /start command.
        
        # Access the global chat_ids set from the application context if possible, 
        # or simplified global list for this script
        if 'chat_ids' in context.bot_data:
            for chat_id in context.bot_data['chat_ids']:
                try:
                    await context.bot.send_message(
                        chat_id=chat_id, 
                        text=msg, 
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Failed to send to {chat_id}: {e}")

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    chat_id = update.effective_chat.id
    
    # Store chat_id in bot_data persistence
    if 'chat_ids' not in context.bot_data:
        context.bot_data['chat_ids'] = set()
    
    context.bot_data['chat_ids'].add(chat_id)
    
    await update.message.reply_text(
        "🦅 **PolyHawk New Market Alerts**\n\n"
        "✅ You are now subscribed.\n"
        "I will alert you as soon as a new market appears on Polymarket."
    )

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN not found in .env")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    bot_instance = NewMarketBot()

    # Handlers
    application.add_handler(CommandHandler("start", start_cmd))

    # Jobs
    application.job_queue.run_repeating(bot_instance.monitor_markets, interval=CHECK_INTERVAL, first=5)

    print("🦅 Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
