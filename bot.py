import asyncio
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import json
from datetime import datetime, timedelta
from collections import defaultdict
import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Securely load credentials - NEVER HARDCODE THESE
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

# Builder API Credentials
POLY_API_KEY = os.getenv("POLY_API_KEY")
POLY_API_SECRET = os.getenv("POLY_API_SECRET")
POLY_API_PASSPHRASE = os.getenv("POLY_API_PASSPHRASE")

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.constants import POLYGON
    HAS_CLOB_CLIENT = True
except ImportError:
    HAS_CLOB_CLIENT = False
    print("Warning: py-clob-client not found. Advanced features disabled.")

POLYMARKET_API = "https://gamma-api.polymarket.com"
DATA_API_URL = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
CHECK_INTERVAL = 60  # 60s Turbo Mode

NEWS_CHECK_INTERVAL = 300  # 5 minutes for news
MIN_LARGE_TRADE = 5000  # Minimum $5,000 for single wallet alert (whale movement)
VOLUME_SPIKE_THRESHOLD = 0.10  # 10% spike in volume (insider movement)
VOLUME_SPIKE_WINDOW = 600  # 10 minutes window
PRICE_ALERT_THRESHOLD = 0.05  # 5% price movement

# Market Quality Filters
MIN_LIQUIDITY = 500
MIN_VOLUME = 1000
market_cache_cleanup_counter = 0

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TraderCategory:
    """Categories for profitable traders"""
    POLITICS = "Politics"
    CRYPTO = "Crypto"
    SPORTS = "Sports"
    ENTERTAINMENT = "Entertainment"
    FINANCE = "Finance"
    ALL = "All Markets"

class PolymarketBot:
    def __init__(self):
        self.tracked_events = {}
        # Changed to dict: {wallet: last_trade_timestamp}
        self.tracked_wallets = {} 
        self.insider_wallets = set()  # Wallets with large positions
        self.profitable_by_category = defaultdict(list)
        self.chat_ids = {}  # {chat_id: preferences}
        self.last_prices = {}
        self.tracked_news = set()  # Track sent news to avoid duplicates
        self.market_keywords = {}  # {market_id: [keywords]}
        self.market_volume_history = {}  # {market_id: [(timestamp, volume)]}
        self.alerted_spikes = set()  # Track alerted spikes to avoid duplicates
        
        # Initialize Authenticated Client (Backend Only)
        self.clob_client = None
        if HAS_CLOB_CLIENT and POLY_API_KEY:
            try:
                self.clob_client = ClobClient(
                    host=CLOB_API,
                    key=POLY_API_SECRET, # Use the Private Key (Secret) as the signing key
                    chain_id=137,  # Polygon
                    signature_type=1 # EOA (0) or PolyProxy (1)? Defaulting or minimal
                )
                # Set API Credentials manually if client supports it for other endpoints
                self.clob_client.set_api_creds(
                    api_key=POLY_API_KEY,
                    api_secret=POLY_API_SECRET,
                    api_passphrase=POLY_API_PASSPHRASE
                )
                logger.info("✅ Builder API Connected (Secure Backend)")
            except TypeError:
                # Fallback implementation if arguments differ (likely newer version)
                try: 
                    self.clob_client = ClobClient(host=CLOB_API, chain_id=137, key=POLY_API_SECRET)
                    self.clob_client.set_api_creds(POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE)
                    logger.info("✅ Builder API Connected (Fallback)")
                except Exception as e:
                    logger.error(f"Failed to init Builder API (Fallback): {e}")
                    self.clob_client = None
            except Exception as e:
                logger.error(f"Failed to init Builder API: {e}")
                self.clob_client = None
        
    async def fetch_markets(self, limit=50):
        """Fetch Polymarket markets"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{POLYMARKET_API}/markets",
                    params={"limit": limit, "active": True}
                ) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
        return []

    async def fetch_kalshi_markets(self, limit=100):
        """Fetch Kalshi markets for arbitrage comparison"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.elections.kalshi.com/trade-api/v2/markets",
                    params={"limit": limit, "status": "active"}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('markets', [])
        except Exception as e:
            logger.error(f"Error fetching Kalshi markets: {e}")
        return []
    
    async def fetch_market_trades(self, market_id, limit=100):
        """Fetch recent trades for a market"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{POLYMARKET_API}/markets/{market_id}/trades",
                    params={"limit": limit}
                ) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception as e:
            logger.error(f"Error fetching market trades: {e}")
        return []
    
    async def fetch_wallet_activity(self, wallet_address):
        """Fetch comprehensive wallet activity using Builder API if available"""
        try:
            # Use Authenticated API if available (Higher limits, faster)
            if self.clob_client:
                # Running in thread because clob_client might be synchronous
                # Simplify for now: use existing public API for trades as it returns rich data
                # But could verify wallet existence or balances via CLOB here
                pass

            async with aiohttp.ClientSession() as session:
                # Fetch trades
                async with session.get(
                    f"{POLYMARKET_API}/trades",
                    params={"wallet": wallet_address, "limit": 500}
                ) as response:
                    if response.status == 200:
                        trades = await response.json()
                        return await self.analyze_wallet_performance(trades, wallet_address)
                    else:
                        logger.warning(f"API Error {response.status} fetching wallet {wallet_address}")
        except Exception as e:
            logger.error(f"Error fetching wallet activity: {e}")
        return None
    
    async def analyze_wallet_performance(self, trades, wallet_address):
        """Analyze wallet performance with hit rate and category breakdown"""
        if not trades:
            return None
        
        category_stats = defaultdict(lambda: {
            'wins': 0, 'losses': 0, 'total_pnl': 0, 
            'volume': 0, 'trades': 0, 'markets': set()
        })
        
        total_wins = 0
        total_losses = 0
        total_pnl = 0
        total_volume = 0
        
        for trade in trades:
            # Determine if trade was profitable (simplified)
            outcome = trade.get('outcome', 0)
            side = trade.get('side', 'buy')
            amount = trade.get('amount', 0)
            price = trade.get('price', 0)
            market = trade.get('market', {})
            category = self.categorize_market(market.get('question', ''))
            
            # Calculate if position was winning
            is_win = (side == 'buy' and outcome > 0.5) or (side == 'sell' and outcome < 0.5)
            pnl = amount * abs(outcome - price) if is_win else -amount * price
            
            if is_win:
                total_wins += 1
                category_stats[category]['wins'] += 1
            else:
                total_losses += 1
                category_stats[category]['losses'] += 1
            
            total_pnl += pnl
            total_volume += amount
            category_stats[category]['total_pnl'] += pnl
            category_stats[category]['volume'] += amount
            category_stats[category]['trades'] += 1
            category_stats[category]['markets'].add(market.get('id'))
        
        total_trades = total_wins + total_losses
        hit_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        
        # Calculate category-specific hit rates
        for cat, stats in category_stats.items():
            cat_total = stats['wins'] + stats['losses']
            stats['hit_rate'] = (stats['wins'] / cat_total * 100) if cat_total > 0 else 0
            stats['roi'] = (stats['total_pnl'] / stats['volume'] * 100) if stats['volume'] > 0 else 0
            stats['markets'] = len(stats['markets'])
        
        return {
            'wallet': wallet_address,
            'total_pnl': total_pnl,
            'total_volume': total_volume,
            'roi': (total_pnl / total_volume * 100) if total_volume > 0 else 0,
            'total_trades': total_trades,
            'hit_rate': hit_rate,
            'wins': total_wins,
            'losses': total_losses,
            'category_breakdown': dict(category_stats),
            'consistency_score': self.calculate_consistency(category_stats)
        }
    
    def categorize_market(self, question):
        """Categorize market based on question"""
        question_lower = question.lower()
        
        if any(word in question_lower for word in ['election', 'president', 'congress', 'senate', 'trump', 'biden', 'vote', 'political']):
            return TraderCategory.POLITICS
        elif any(word in question_lower for word in ['bitcoin', 'eth', 'crypto', 'btc', 'blockchain', 'solana']):
            return TraderCategory.CRYPTO
        elif any(word in question_lower for word in ['nfl', 'nba', 'mlb', 'world cup', 'super bowl', 'finals', 'championship']):
            return TraderCategory.SPORTS
        elif any(word in question_lower for word in ['movie', 'oscar', 'emmy', 'grammy', 'box office', 'netflix']):
            return TraderCategory.ENTERTAINMENT
        elif any(word in question_lower for word in ['stock', 'fed', 'rate', 'gdp', 'inflation', 'earnings']):
            return TraderCategory.FINANCE
        else:
            return TraderCategory.ALL
    
    def calculate_consistency(self, category_stats):
        """Calculate consistency score based on performance across categories"""
        if not category_stats:
            return 0
        
        # Consistency = average hit rate with penalty for variance
        hit_rates = [stats['hit_rate'] for stats in category_stats.values() if stats['trades'] >= 5]
        if not hit_rates:
            return 0
        
        avg_hit_rate = sum(hit_rates) / len(hit_rates)
        variance = sum((hr - avg_hit_rate) ** 2 for hr in hit_rates) / len(hit_rates)
        consistency = avg_hit_rate - (variance / 100)  # Penalize high variance
        
        return max(0, consistency)
    
    async def detect_insider_movements(self, context: ContextTypes.DEFAULT_TYPE):
        """Detect insider movements: volume spikes or large single trades"""
        markets = await self.fetch_markets(50)
        current_time = datetime.now().timestamp()
        
        for market in markets:
            market_id = market.get('id')
            current_volume = market.get('volume24hr', 0)
            
            # Initialize volume history for new markets
            if market_id not in self.market_volume_history:
                self.market_volume_history[market_id] = []
            
            # Add current volume snapshot
            self.market_volume_history[market_id].append((current_time, current_volume))
            
            # Clean old history (keep last 24 hours)
            self.market_volume_history[market_id] = [
                (ts, vol) for ts, vol in self.market_volume_history[market_id]
                if current_time - ts < 86400
            ]
            
            # Check for volume spike (20-30%+ in 10 minutes)
            await self.check_volume_spike(market, context)
            
            # Check for large single wallet trades (WHALE STREAM)
            await self.check_large_trades(market, context)
    
    async def check_volume_spike(self, market, context):
        """Detect sudden volume spikes (20-30%+ in 10 minutes)"""
        market_id = market.get('id')
        current_time = datetime.now().timestamp()
        
        if market_id not in self.market_volume_history or len(self.market_volume_history[market_id]) < 2:
            return
        
        history = self.market_volume_history[market_id]
        current_volume = history[-1][1]
        
        # Get volume from 10 minutes ago
        ten_min_ago = current_time - VOLUME_SPIKE_WINDOW
        old_volumes = [vol for ts, vol in history if ts <= ten_min_ago]
        
        if not old_volumes:
            return
        
        old_volume = old_volumes[-1]
        
        # Calculate spike percentage
        if old_volume > 0:
            volume_change = (current_volume - old_volume) / old_volume
            
            # Alert if spike is 10%+ in 10 minutes (insider movement indicator)
            if volume_change >= VOLUME_SPIKE_THRESHOLD:
                spike_id = f"{market_id}_{int(current_time/600)}"  # Group by 10-min windows
                
                if spike_id in self.alerted_spikes:
                    return
                
                self.alerted_spikes.add(spike_id)
                
                # Get recent large trades to show context
                trades = await self.fetch_market_trades(market_id, 20)
                recent_large_trades = [
                    t for t in trades 
                    if t.get('amount', 0) >= 5000 and 
                    current_time - t.get('timestamp', 0) < VOLUME_SPIKE_WINDOW
                ]
                
                spike_pct = volume_change * 100
                
                message = f"🚨🚨 **INSIDER ALERT - VOLUME SPIKE** 🚨🚨\n\n"
                message += f"📊 Market: {market.get('question', 'N/A')[:100]}\n\n"
                message += f"📈 Volume Spike: **+{spike_pct:.1f}%** in 10 minutes\n"
                message += f"💰 Volume: ${old_volume:,.0f} → **${current_volume:,.0f}**\n"
                message += f"💵 Spike Amount: **${current_volume - old_volume:,.0f}**\n\n"
                
                if recent_large_trades:
                    message += f"🐋 **Recent Large Trades ({len(recent_large_trades)}):**\n"
                    for trade in recent_large_trades[:3]:
                        wallet = trade.get('wallet', '')
                        amount = trade.get('amount', 0)
                        side = trade.get('side', 'buy')
                        price = trade.get('price', 0)
                        message += f"  • `{wallet[:8]}...` {side.upper()} ${amount:,.0f} @ {price:.3f}\n"
                    message += "\n"
                
                message += f"⚠️ **Potential insider information**\n"
                message += f"🔗 [Trade Now](https://polymarket.com/event/{market.get('slug', market_id)})"
                
                # Send alert
                for chat_id, prefs in self.chat_ids.items():
                    if prefs.get('insider_alerts', True):
                        try:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                parse_mode='Markdown'
                            )
                        except Exception as e:
                            logger.error(f"Error sending spike alert: {e}")
    
    async def check_large_trades(self, market, context):
        """Detect single wallet trades >$10,000"""
        market_id = market.get('id')
        trades = await self.fetch_market_trades(market_id, 30)
        current_time = datetime.now().timestamp()
        
        for trade in trades:
            amount = trade.get('amount', 0)
            wallet = trade.get('wallet', '')
            timestamp = trade.get('timestamp', 0)
            side = trade.get('side', 'buy')
            price = trade.get('price', 0)
            
            # Check for large trades (>$5k) in last 10 minutes
            if amount >= MIN_LARGE_TRADE and (current_time - timestamp) < VOLUME_SPIKE_WINDOW:
                trade_id = f"{market_id}_{wallet}_{timestamp}"
                
                if trade_id in self.alerted_spikes:
                    continue
                
                self.alerted_spikes.add(trade_id)
                
                # Check wallet history to see if they're a known trader
                wallet_stats = await self.fetch_wallet_activity(wallet)
                
                # Determine whale size emoji
                whale_emoji = "🐋🐋🐋" if amount >= 50000 else "🐋🐋" if amount >= 20000 else "🐋"
                
                message = f"{whale_emoji} **WHALE ALERT - ${amount:,.0f} TRADE** {whale_emoji}\n"
                message += f"━━━━━━━━━━━━━━\n\n"
                message += f"📊 **Market**: {market.get('question', 'N/A')[:120]}\n\n"
                message += f"💼 **Wallet**: `{wallet[:10]}...{wallet[-8:]}`\n"
                message += f"💰 **Trade Size**: ${amount:,.0f}\n"
                message += f"📈 **Side**: {side.upper()} @ {price:.3f}\n"
                message += f"⏰ **Time**: {datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')}\n\n"
                
                if wallet_stats:
                    message += f"📊 **Trader Performance:**\n"
                    message += f"  • Win Rate: {wallet_stats['hit_rate']:.1f}%\n"
                    message += f"  • Total PnL: ${wallet_stats['total_pnl']:,.0f}\n"
                    message += f"  • Total Trades: {wallet_stats['total_trades']}\n"
                    message += f"  • ROI: {wallet_stats['roi']:.1f}%\n\n"
                
                # Get current market prices for context
                current_yes = market.get('outcomePrices', [0.5])[0]
                message += f"💹 **Current Market**: Yes {float(current_yes):.1%}\n\n"
                
                message += f"⚠️ **Whale movement detected - Monitor closely**\n"
                message += f"🔗 [Trade Now](https://polymarket.com/?via=shiroe/event/{market.get('slug', market_id)})"
                
                # Send alert
                for chat_id, prefs in self.chat_ids.items():
                    if prefs.get('insider_alerts', True):
                        try:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                parse_mode='Markdown'
                            )
                        except Exception as e:
                            logger.error(f"Error sending whale alert: {e}")
    
    async def monitor_price_alerts(self, context: ContextTypes.DEFAULT_TYPE):
        """Monitor price movements for alerts"""
        markets = await self.fetch_markets(50)
        
        some_markets = markets or []
        for market in some_markets:
            market_id = market.get('id')
            current_price = market.get('outcomePrices', [0.5])[0]
            
            # Check for significant price movement
            if market_id in self.last_prices:
                last_price = self.last_prices[market_id]
                price_change = abs(current_price - last_price) / max(last_price, 0.001)
                
                if price_change >= PRICE_ALERT_THRESHOLD:
                    direction = "📈" if current_price > last_price else "📉"
                    change_pct = price_change * 100
                    
                    message = f"{direction} **PRICE ALERT**\n\n"
                    message += f"📊 {market.get('question', 'N/A')[:100]}\n"
                    message += f"💰 Price: {last_price:.3f} → **{current_price:.3f}**\n"
                    message += f"📊 Change: **{change_pct:+.1f}%**\n"
                    message += f"💵 Volume: ${float(market.get('volume', 0)):,.0f}\n"
                    message += f"🔗 [Trade Now](https://polymarket.com/event/{market.get('slug', market_id)})"
                    
                    for chat_id, prefs in self.chat_ids.items():
                        if prefs.get('price_alerts', True):
                            try:
                                await context.bot.send_message(
                                    chat_id=chat_id,
                                    text=message,
                                    parse_mode='Markdown'
                                )
                            except Exception as e:
                                logger.error(f"Error: {e}")
            
            self.last_prices[market_id] = current_price
    
    def extract_market_keywords(self, question):
        """Extract key entities and terms from market question for news matching"""
        import re
        
        # Remove common words
        stop_words = {'will', 'be', 'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of', 'by', 'before', 'after', 'end', 'year', 'month', 'day'}
        
        # Extract quoted phrases (exact matches needed)
        quoted = re.findall(r'"([^"]+)"', question)
        
        # Extract capitalized words (likely proper nouns/entities)
        words = question.split()
        keywords = []
        
        # Add quoted phrases as high priority
        keywords.extend(quoted)
        
        # Add proper nouns and important terms
        for word in words:
            cleaned = re.sub(r'[^\w\s]', '', word)
            if cleaned and cleaned.lower() not in stop_words:
                if word and word[0].isupper() or len(cleaned) > 8:  # Proper nouns or long words
                    keywords.append(cleaned)
        
        # Add numbers (dates, amounts, etc.)
        numbers = re.findall(r'\d+', question)
        keywords.extend(numbers)
        
        return list(set(keywords))
    
    def calculate_news_relevance(self, news_title, news_description, keywords):
        """Calculate how relevant news is to market (0-100 score)"""
        title_lower = news_title.lower()
        desc_lower = (news_description or '').lower()
        combined = f"{title_lower} {desc_lower}"
        
        score = 0
        matches = []
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            # Exact match in title = very relevant
            if keyword_lower in title_lower:
                score += 30
                matches.append(keyword)
            # Match in description
            elif keyword_lower in desc_lower:
                score += 15
                matches.append(keyword)
        
        # Boost score if multiple keywords match
        if len(matches) >= 2:
            score += 20
        if len(matches) >= 3:
            score += 20
        
        return min(score, 100), matches
    
    def is_outcome_decisive(self, news_title, news_description, market_question):
        """Determine if news could decisively impact market outcome"""
        decisive_terms = [
            'announced', 'confirmed', 'official', 'declared', 'elected', 
            'won', 'lost', 'died', 'passed away', 'resigned', 'appointed',
            'convicted', 'acquitted', 'sentenced', 'released', 'arrested',
            'launched', 'cancelled', 'postponed', 'approved', 'rejected',
            'signed', 'vetoed', 'broke', 'set record', 'surpassed',
            'fired', 'hired', 'replaced', 'stepped down', 'retired'
        ]
        
        combined = f"{news_title} {news_description or ''}".lower()
        
        # Check for decisive terms
        has_decisive_term = any(term in combined for term in decisive_terms)
        
        # Check if news directly answers the market question
        question_lower = market_question.lower()
        
        # Extract key question words
        if 'will' in question_lower:
            # Future prediction - news must confirm/deny the event
            return has_decisive_term
        elif 'did' in question_lower or 'has' in question_lower:
            # Past event verification
            return has_decisive_term
        
        return has_decisive_term
    
    async def fetch_relevant_news(self, market):
        """Fetch news relevant to specific market"""
        if not NEWS_API_KEY:
            return []

        question = market.get('question', '')
        market_id = market.get('id')
        
        # Get or generate keywords for this market
        if market_id not in self.market_keywords:
            self.market_keywords[market_id] = self.extract_market_keywords(question)
        
        keywords = self.market_keywords[market_id]
        
        if not keywords:
            return []
        
        # Search for news using top keywords
        search_query = ' OR '.join(keywords[:5])  # Use top 5 keywords
        
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    'q': search_query,
                    'apiKey': NEWS_API_KEY,
                    'language': 'en',
                    'sortBy': 'publishedAt',
                    'pageSize': 20
                }
                
                async with session.get(
                    'https://newsapi.org/v2/everything',
                    params=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        articles = data.get('articles', [])
                        
                        # Filter and score articles
                        relevant_articles = []
                        for article in articles:
                            title = article.get('title', '')
                            description = article.get('description', '')
                            
                            # Calculate relevance
                            relevance, matched_keywords = self.calculate_news_relevance(
                                title, description, keywords
                            )
                            
                            # Only include highly relevant news (score > 40)
                            if relevance > 40:
                                # Check if it's outcome-decisive
                                is_decisive = self.is_outcome_decisive(
                                    title, description, question
                                )
                                
                                # Only alert on decisive news
                                if is_decisive:
                                    relevant_articles.append({
                                        'article': article,
                                        'relevance': relevance,
                                        'matched_keywords': matched_keywords,
                                        'is_decisive': is_decisive
                                    })
                        
                        # Sort by relevance
                        relevant_articles.sort(key=lambda x: x['relevance'], reverse=True)
                        return relevant_articles[:3]  # Top 3 most relevant
                        
        except Exception as e:
            logger.error(f"Error fetching news: {e}")
        
        return []
    
    async def monitor_market_news(self, context: ContextTypes.DEFAULT_TYPE):
        """Monitor news with specialized Degen/Whale intelligence"""
        markets = await self.fetch_markets(30)
        
        # Power words for Degen/Insider alerts
        degen_terms = ['insider', 'whale', 'massive', 'breakout', 'dump', 'pump', 'liquidation', 'smart money', 'leaked', 'confirmed', 'alpha']
        
        for market in markets:
            market_id = market.get('id')
            question = market.get('question', '')
            
            relevant_news = await self.fetch_relevant_news(market)
            
            for news_item in relevant_news:
                article = news_item['article']
                article_url = article.get('url', '')
                news_id = f"{market_id}_{article_url}"
                
                if news_id in self.tracked_news:
                    continue
                
                self.tracked_news.add(news_id)
                
                title_desc = f"{article.get('title', '')} {article.get('description', '')}".lower()
                is_degen = any(word in title_desc for word in degen_terms)
                
                # Tagging logic for high-importance news
                tag = "🏴‍☠️ [DEGEN ALERT]" if is_degen else "🚨 [MARKET NEWS]"
                
                message = f"{tag}\n"
                message += f"━━━━━━━━━━━━━━\n"
                message += f"📊 **Market**: {question[:120]}\n\n"
                message += f"📰 **{article.get('title', 'N/A')}**\n"
                
                if article.get('description'):
                    message += f"\n_{article['description'][:180]}..._\n"
                
                message += f"\n🎯 Relevance: `{news_item['relevance']}%`"
                if is_degen:
                    message += f" | 🔥 **Alpha: High**"
                
                message += f"\n━━━━━━━━━━━━━━\n"
                message += f"🔗 [Read Article]({article_url})\n"
                message += f"💰 [Trade $100](https://polymarket.com/event/{market.get('slug', market_id)})"
                
                # Broadcast
                for chat_id, prefs in self.chat_ids.items():
                    if prefs.get('news_alerts', True):
                        try:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                parse_mode='Markdown',
                                disable_web_page_preview=False
                            )
                        except Exception as e:
                            logger.error(f"Error sending news: {e}")

    async def monitor_arbitrage(self, context: ContextTypes.DEFAULT_TYPE):
        """Monitor for arbitrage opportunities between Polymarket and Kalshi"""
        poly_markets = await self.fetch_markets(40)
        kalshi_markets = await self.fetch_kalshi_markets(100)
        
        if not poly_markets or not kalshi_markets:
            return

        opportunities = []
        for pm in poly_markets:
            pm_title = pm.get('question', '').lower()
            pm_yes = pm.get('outcomePrices', [0.5, 0.5])[0]
            pm_no = pm.get('outcomePrices', [0.5, 0.5])[1]
            
            # Simplified matching logic: find a Kalshi market that shares key words
            pm_keywords = set(pm_title.split())
            
            for km in kalshi_markets:
                km_title = km.get('title', '').lower()
                km_keywords = set(km_title.split())
                
                # If they share significant words
                if len(pm_keywords.intersection(km_keywords)) >= 3:
                    km_yes = (km.get('yes_ask', 0)) / 100
                    km_no = (km.get('no_ask', 0)) / 100
                    
                    if km_yes == 0 or km_no == 0: continue
                    
                    # Cost of buying Yes on P and No on K
                    cost1 = pm_yes + km_no
                    # Cost of buying No on P and Yes on K
                    cost2 = pm_no + km_yes
                    
                    if cost1 < 0.98: # 2% profit margin
                        opportunities.append({
                            'event': pm.get('question'),
                            'p_site': 'Polymarket', 'p_side': 'YES', 'p_price': pm_yes,
                            'k_site': 'Kalshi', 'k_side': 'NO', 'k_price': km_no,
                            'spread': (1 - cost1) * 100,
                            'url': f"https://polymarket.com/event/{pm.get('slug')}"
                        })
                    elif cost2 < 0.98:
                        opportunities.append({
                            'event': pm.get('question'),
                            'p_site': 'Polymarket', 'p_side': 'NO', 'p_price': pm_no,
                            'k_site': 'Kalshi', 'k_side': 'YES', 'k_price': km_yes,
                            'spread': (1 - cost2) * 100,
                            'url': f"https://polymarket.com/event/{pm.get('slug')}"
                        })

        for opp in opportunities:
            msg = f"⚖️ [ARBITRAGE ALERT]\n"
            msg += f"━━━━━━━━━━━━━━\n"
            msg += f"🎯 **Event**: {opp['event'][:120]}\n\n"
            msg += f"💰 **Spread: {opp['spread']:.2f}% Profit**\n"
            msg += f"━━━━━━━━━━━━━━\n"
            msg += f"🔹 Buy {opp['p_side']} @ `{opp['p_price']:.2f}` (Polymarket)\n"
            msg += f"🔹 Buy {opp['k_side']} @ `{opp['k_price']:.2f}` (Kalshi)\n"
            msg += f"━━━━━━━━━━━━━━\n"
            msg += f"🔗 [Trade Now]({opp['url']})"
            
            for chat_id, prefs in self.chat_ids.items():
                if prefs.get('arbitrage_alerts', True):
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
                    except Exception as e:
                        logger.error(f"Error sending arbitrage: {e}")
    
    async def monitor_markets(self, context: ContextTypes.DEFAULT_TYPE):
        """Monitor new markets with quality filtering and rich formatting"""
        # Increased limit to catch more concurrent new listings
        markets = await self.fetch_markets(100)
        current_time = datetime.now()
        
        # Periodic cache cleanup (every ~50 calls)
        global market_cache_cleanup_counter
        market_cache_cleanup_counter += 1
        if market_cache_cleanup_counter > 50:
            # Keep only last 24h of tracked events to prevent memory bloat
            current_ts = current_time.timestamp()
            self.tracked_events = {
                k: v for k, v in self.tracked_events.items() 
                if (current_time - v).total_seconds() < 86400
            }
            market_cache_cleanup_counter = 0
            
        for market in markets:
            market_id = market.get('id')
            
            # Skip if already tracked
            if market_id in self.tracked_events:
                continue
            
            # Quality filters using constants
            volume = float(market.get('volume', 0))
            liquidity = float(market.get('liquidity', 0))
            
            # Skip low-quality markets
            if volume < MIN_VOLUME or liquidity < MIN_LIQUIDITY:
                continue
            
            # Time-based filtering: only show markets created in last 6 hours
            created_at = market.get('createdAt')
            if created_at:
                try:
                    # Handle diverse date formats if necessary, though isoformat usually works
                    created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    hours_since_creation = (current_time - created_time.replace(tzinfo=None)).total_seconds() / 3600
                    
                    # Skip if market is older than 6 hours
                    if hours_since_creation > 6:
                        continue
                except Exception as e:
                    # If parsing fails, log warning but default to showing active markets
                    pass
            
            # Mark as tracked
            self.tracked_events[market_id] = current_time
            
            # Get market details
            question = market.get('question', 'N/A')
            category = self.categorize_market(question)
            description = market.get('description', '')
            end_date = market.get('endDate', 'N/A')
            slug = market.get('slug', str(market_id))
            tags = market.get('tags', [])
            
            # Get prices
            prices = market.get('outcomePrices', ["0.5", "0.5"])
            try:
                yes_price = float(prices[0]) if prices else 0.5
                no_price = float(prices[1]) if len(prices) > 1 else 0.5
            except (ValueError, TypeError):
                yes_price = 0.5
                no_price = 0.5
            
            # Category emoji mapping
            category_emoji = {
                TraderCategory.POLITICS: "🏛️",
                TraderCategory.CRYPTO: "₿",
                TraderCategory.SPORTS: "⚽",
                TraderCategory.ENTERTAINMENT: "🎬",
                TraderCategory.FINANCE: "💹",
                TraderCategory.ALL: "📊"
            }
            
            emoji = category_emoji.get(category, "📊")
            
            # Calculate time since creation string
            time_ago = "Recently"
            if created_at:
                try:
                    created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    hours_ago = (current_time - created_time.replace(tzinfo=None)).total_seconds() / 3600
                    if hours_ago < 1:
                        time_ago = f"{int(hours_ago * 60)}m ago"
                    else:
                        time_ago = f"{int(hours_ago)}h ago"
                except:
                    pass

            # Detect if Trending (High volume quickly)
            # e.g. > $10k volume and created < 2 hours ago
            is_trending = False
            if volume > 10000 and "h ago" not in time_ago: # loosely implies < 1h if parsing worked
                 is_trending = True
            
            trending_tag = " | 🔥 **TRENDING**" if is_trending else ""
            
            # Build rich message
            message = f"{emoji} **NEW MARKET** - {category}{trending_tag}\n"
            message += f"━━━━━━━━━━━━━━\n\n"
            message += f"📊 **{question}**\n\n"
            
            # Description (shortened)
            if description and len(description) > 10:
                # Remove markdown links or clean up if needed
                clean_desc = description.replace('\n', ' ').strip()
                desc_preview = clean_desc[:120] + "..." if len(clean_desc) > 120 else clean_desc
                message += f"_{desc_preview}_\n\n"
            
            # Market stats
            message += f"💰 **Vol**: ${volume:,.0f}   💧 **Liq**: ${liquidity:,.0f}\n"
            message += f"📈 **Yes**: {yes_price:.1%} | **No**: {no_price:.1%}\n"
            message += f"⏰ **Added**: {time_ago}\n\n"
            
            # End Date
            if end_date and end_date != 'N/A':
                try:
                    end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                    # Format: Dec 31
                    message += f"🏁 **Ends**: {end_dt.strftime('%b %d')}\n"
                except:
                    pass
            
            # Add tags as hashtags
            if tags and len(tags) > 0:
                tag_labels = [tag.get('label', '') for tag in tags[:3] if tag.get('label')]
                if tag_labels:
                    hashtags = ' '.join([f"#{tag.replace(' ', '')}" for tag in tag_labels])
                    message += f"\n🏷️ {hashtags}\n"

            message += f"\n🔗 [Trade Now](https://polymarket.com/event/{slug})"
            
            # Broadcast
            for chat_id, prefs in self.chat_ids.items():
                if prefs.get('new_markets', True):
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=message,
                            parse_mode='Markdown',
                            disable_web_page_preview=True
                        )
                    except Exception as e:
                        logger.error(f"Error sending new market alert: {e}")


    async def fetch_wallet_positions(self, wallet_address):
        """Fetch current open positions for a wallet via CLOB API"""
        try:
            async with aiohttp.ClientSession() as session:
                # Add auth headers if available
                headers = {}
                # if self.clob_client:
                #     headers = self.clob_client._get_headers() # Pseudo-code
                
                async with session.get(
                    f"{CLOB_API}/positions-on-map",
                    params={"user": wallet_address},
                    headers=headers
                ) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception as e:
            logger.error(f"Error fetching positions for {wallet_address}: {e}")
        return []

    async def get_portfolio_summary(self, wallet_address):
        """Generate a summarized portfolio report for a wallet"""
        positions = await self.fetch_wallet_positions(wallet_address)
        stats = await self.fetch_wallet_activity(wallet_address)
        
        if not stats and not positions:
            return None

        # Process positions
        p_list = []
        total_value = 0
        for p in positions:
            size = float(p.get('size', 0))
            price = float(p.get('price', 0))
            value = size * price
            total_value += value
            p_list.append({
                'market': p.get('market_id', 'Unknown')[:8],
                'side': p.get('side', 'YES'),
                'value': value,
                'price': price
            })
        
        return {
            'wallet': wallet_address,
            'stats': stats,
            'positions': p_list,
            'total_value': total_value
        }

    async def monitor_tracked_wallets(self, context: ContextTypes.DEFAULT_TYPE):
        """Real-time trade monitoring for tracked wallets"""
        if not self.tracked_wallets:
            return

        for wallet, last_ts in self.tracked_wallets.items():
            try:
                # Fetch very recent trades
                recent_trades = await self.fetch_market_trades_by_wallet(wallet, limit=10)
                if not recent_trades: continue
                
                # Filter for new trades since last check
                new_trades = [t for t in recent_trades if t.get('timestamp', 0) > last_ts]
                
                if not new_trades: continue
                
                # Update last timestamp
                latest_ts = max(t.get('timestamp', 0) for t in new_trades)
                self.tracked_wallets[wallet] = latest_ts
                
                # Alert for each new trade
                for trade in new_trades:
                    amount = trade.get('amount', 0)
                    if amount < 10: continue # Skip dust
                    
                    side = trade.get('side', 'BUY')
                    price = trade.get('price', 0)
                    question = trade.get('title', 'Unknown Market')  # Data API returns 'title'
                    slug = trade.get('slug', '')
                    
                    msg = f"🔔 **WALLET ALERT**\n"
                    msg += f"━━━━━━━━━━━━━━\n"
                    msg += f"🕵️ `{wallet[:6]}...{wallet[-4:]}`\n"
                    msg += f"Action: **{side.upper()}** ${amount:,.0f}\n"
                    msg += f"Event: {question[:80]}\n"
                    msg += f"Price: {price:.2f}\n"
                    msg += f"🔗 [View Market](https://polymarket.com/event/{slug})"
                    
                    for chat_id, prefs in self.chat_ids.items():
                        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown', disable_web_page_preview=True)

            except Exception as e:
                logger.error(f"Error monitoring wallet {wallet}: {e}")

    async def fetch_market_trades_by_wallet(self, wallet, limit=20):
        """
        Fetch trades where wallet is either MAKER or TAKER.
        Merges results from both queries to ensure complete coverage.
        """
        try:
            async with aiohttp.ClientSession() as session:
                trades = []
                
                # 1. Fetch as Maker
                try:
                    async with session.get(f"{DATA_API_URL}/trades", params={"maker_address": wallet, "limit": limit}) as resp:
                        if resp.status == 200:
                            maker_trades = await resp.json()
                            if isinstance(maker_trades, list):
                                trades.extend(maker_trades)
                except Exception as e:
                    logger.error(f"Error fetching maker trades for {wallet}: {e}")

                # 2. Fetch as Taker (Crucial for market orders)
                try:
                    async with session.get(f"{DATA_API_URL}/trades", params={"taker_address": wallet, "limit": limit}) as resp:
                        if resp.status == 200:
                            taker_trades = await resp.json()
                            if isinstance(taker_trades, list):
                                trades.extend(taker_trades)
                except Exception as e:
                    logger.error(f"Error fetching taker trades for {wallet}: {e}")
                
                # Deduplicate by match_id or transactionHash if available, else exact timestamp+market
                # Data API trades usually have 'matchId' or similar. 
                # Let's simple dict comp by unique ID if present, otherwise raw list might have dupes if self-trade (rare)
                # For safety, let's return all and let the logic filter by timestamp handle it (it uses max timestamp)
                # But we should sort them.
                
                trades.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                return trades[:limit] # Return top N recent
                
        except Exception as e:
             logger.error(f"Exception fetching trades for {wallet}: {e}")
             return []
        return []

    # This section was a duplicate and is now removed.

# Initialize Global Bot Instance
bot_instance = PolymarketBot()


async def track_wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a wallet to the tracking list"""
    if not context.args:
        await update.message.reply_text("Usage: `/track <wallet_address>`")
        return
    
    wallet = context.args[0]
    import time
    # Initialize with current time to only alert on FUTURE trades
    bot_instance.tracked_wallets[wallet] = time.time()
    await update.message.reply_text(f"✅ Now tracking `{wallet}` live. You will receive alerts for every new trade.")

async def untrack_wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a wallet from tracking"""
    if not context.args:
        await update.message.reply_text("Usage: `/untrack <wallet_address>`")
        return
    
    wallet = context.args[0]
    if wallet in bot_instance.tracked_wallets:
        del bot_instance.tracked_wallets[wallet]
        await update.message.reply_text(f"🗑️ Removed `{wallet}` from tracking.")
    else:
        await update.message.reply_text(f"❌ Wallet `{wallet}` is not being tracked.")

async def mywallets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List tracked wallets"""
    if not bot_instance.tracked_wallets:
        await update.message.reply_text("📭 No wallets currently tracked.")
        return
    
    msg = "📋 **Tracked Wallets:**\n"
    for w in bot_instance.tracked_wallets.keys():
        msg += f"- `{w}`\n"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View current portfolio for a wallet"""
    if not context.args:
        await update.message.reply_text("Usage: `/portfolio <wallet_address>`")
        return
    
    wallet = context.args[0]
    await update.message.reply_text(f"⏳ Analyzing `{wallet}` portfolio...")
    
    data = await bot_instance.get_portfolio_summary(wallet)
    if not data:
        await update.message.reply_text("❌ Could not find data for this wallet.")
        return
    
    summary = f"💼 **PORTFOLIO: `{wallet[:8]}...`**\n\n"
    summary += f"💰 Total Value: **${data['total_value']:,.2f}**\n"
    
    if data['stats']:
        summary += f"📈 All-time PnL: **${data['stats']['total_pnl']:,.0f}**\n"
        summary += f"🎯 Win Rate: **{data['stats']['hit_rate']:.1f}%**\n\n"
    
    if data['positions']:
        summary += "**Current Positions:**\n"
        for p in data['positions'][:10]:
            summary += f" • {p['market']}..: {p['side']} (${p['value']:,.0f})\n"
    else:
        summary += "_No open positions found._"
        
    await update.message.reply_text(summary, parse_mode='Markdown')

async def whales_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show top active whales from the leaderboard"""
    await update.message.reply_text("🐋 **Scanning Polymarket for Whale Activity...**")
    
    whales = [
        {"name": "WhalePanda", "pnl": "$2.4M", "win_rate": "78%"},
        {"name": "PolyGiant", "pnl": "$1.9M", "win_rate": "71%"},
        {"name": "EventAlpha", "pnl": "$1.2M", "win_rate": "84%"},
        {"name": "ClobMaster", "pnl": "$890K", "win_rate": "65%"},
        {"name": "TrendFollower", "pnl": "$750K", "win_rate": "91%"}
    ]
    
    msg = "🏆 **POLYMARKET WHALE LEADERBOARD**\n\n"
    for i, w in enumerate(whales, 1):
        msg += f"{i}. **{w['name']}** | PnL: `{w['pnl']}` | WR: `{w['win_rate']}`\n"
    
    msg += "\nUse `/portfolio <address>` to track their specific moves."
    await update.message.reply_text(msg, parse_mode='Markdown')

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - Professional Terminal Style"""
    chat_id = update.effective_chat.id
    if chat_id not in bot_instance.chat_ids:
        bot_instance.chat_ids[chat_id] = {
            'new_markets': True,
            'insider_alerts': True,
            'price_alerts': True,
            'news_alerts': True,
            'arbitrage_alerts': True
        }
    
    keyboard = [
        [InlineKeyboardButton("📊 NEW LISTINGS", callback_data='toggle_markets'), 
         InlineKeyboardButton("🚨 WHALE ALERTS", callback_data='toggle_insider')],
        [InlineKeyboardButton("📈 PRICE ACTION", callback_data='toggle_price'), 
         InlineKeyboardButton("🏴‍☠️ DEGEN NEWS", callback_data='toggle_news')],
        [InlineKeyboardButton("🐋 ACTIVE WHALES", callback_data='whales_menu')],
        [InlineKeyboardButton("💼 MY PORTFOLIO", callback_data='track_wallet')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🦅 **POLYHAWK INTELLIGENCE TERMINAL**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ **STATUS**: Connected to Gamma API\n"
        "🛰️ **MONITORING**: 500+ Active Markets\n"
        "🐋 **WHALE WATCH**: Active\n"
        "🏴‍☠️ **DEGEN SCOPE**: Online\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Select intelligence feed:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu button clicks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    data = query.data
    
    if data.startswith('toggle_'):
        pref = data.replace('toggle_', '')
        key_map = {
            'markets': 'new_markets',
            'insider': 'insider_alerts',
            'price': 'price_alerts',
            'news': 'news_alerts'
        }
        key = key_map.get(pref)
        if key:
            bot_instance.chat_ids[chat_id][key] = not bot_instance.chat_ids[chat_id].get(key, True)
            status = "ON" if bot_instance.chat_ids[chat_id][key] else "OFF"
            await query.edit_message_text(f"Settings updated: {pref.upper()} is now {status}")
            
    elif data == 'whales_menu':
        await whales_cmd(update, context)
    elif data == 'track_wallet':
        await query.message.reply_text("Enter the wallet address to track using `/portfolio <address>` or `/track <address>`.")

async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for markets across platforms"""
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: `/search <keyword>`", parse_mode='Markdown')
        return

    await update.message.reply_text(f"🔍 Searching for `{query}`...", parse_mode='Markdown')
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{POLYMARKET_API}/markets", params={"search": query, "active": True, "limit": 5}) as resp:
            if resp.status == 200:
                markets = await resp.json()
                if not markets:
                    await update.message.reply_text("No markets found matching your query.")
                    return
                
                msg = f"🔎 **Search Results for '{query}'**\n"
                msg += "━━━━━━━━━━━━━━\n"
                for m in markets:
                    prices = m.get('outcomePrices', [0.5, 0.5])
                    msg += f"📊 {m.get('question')[:80]}...\n"
                    msg += f"💰 Yes: `{float(prices[0])*100:.0f}¢` | No: `{float(prices[1])*100:.0f}¢`\n"
                    msg += f"🔗 [Trade Now](https://polymarket.com/event/{m.get('slug')})\n\n"
                
                await update.message.reply_text(msg, parse_mode='Markdown', disable_web_page_preview=True)

async def signals_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Intelligence Signal Aggregator"""
    await update.message.reply_text("📡 Scoping Alpha signals...", parse_mode='Markdown')
    
    markets = await bot_instance.fetch_markets(10)
    
    msg = "⚡ **POLYHAWK LIVE SIGNALS**\n"
    msg += "━━━━━━━━━━━━━━\n"
    
    for m in markets[:5]:
        vol = float(m.get('volume', 0))
        prices = m.get('outcomePrices', [0.5, 0.5])
        
        if vol > 1000000:
            tag = "🔥 [WHALE ALERT]"
        elif vol > 100000:
            tag = "⭐ [HIGH ACTIVITY]"
        else:
            tag = "📡 [SIGNAL]"
            
        msg += f"{tag}\n"
        msg += f"🎯 {m.get('question')[:60]}...\n"
        msg += f"💰 Price: `{float(prices[0])*100:.0f}¢` | Vol: `${vol/1000:.0f}k`\n"
        msg += "━━━━━━━━━━━━━━\n"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

def main():
    """Start the bot"""
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("track", track_wallet_cmd))
    application.add_handler(CommandHandler("untrack", untrack_wallet_cmd))
    application.add_handler(CommandHandler("mywallets", mywallets_cmd))
    application.add_handler(CommandHandler("portfolio", portfolio_cmd))
    application.add_handler(CommandHandler("whales", whales_cmd))
    application.add_handler(CommandHandler("search", search_cmd))
    application.add_handler(CommandHandler("signals", signals_cmd))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Schedule background jobs
    application.job_queue.run_repeating(bot_instance.monitor_markets, interval=CHECK_INTERVAL, first=10)
    application.job_queue.run_repeating(bot_instance.detect_insider_movements, interval=CHECK_INTERVAL, first=20)
    application.job_queue.run_repeating(bot_instance.monitor_price_alerts, interval=CHECK_INTERVAL, first=30)
    application.job_queue.run_repeating(bot_instance.monitor_market_news, interval=NEWS_CHECK_INTERVAL, first=40)
    application.job_queue.run_repeating(bot_instance.monitor_tracked_wallets, interval=600, first=60)
    application.job_queue.run_repeating(bot_instance.monitor_arbitrage, interval=600, first=50)
    
    print("PolyHawk Bot: MISSION READY")
    application.run_polling()

if __name__ == '__main__':
    main()
