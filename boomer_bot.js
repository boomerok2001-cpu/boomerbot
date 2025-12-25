require('dotenv').config();
const TelegramBot = require('node-telegram-bot-api');
const axios = require('axios');
const express = require('express');

// Configuration
const token = process.env.TELEGRAM_BOT_TOKEN;
const POLYMARKET_API = 'https://gamma-api.polymarket.com/markets';
const CHECK_INTERVAL = 30000; // 30 seconds

// Health Check Server for Render
const app = express();
const PORT = process.env.PORT || 3000;

app.get('/', (req, res) => {
    res.send('👴 Ok Boomer Bot is Flying');
});

app.listen(PORT, () => {
    console.log(`Server is running on port ${PORT}`);
});

if (!token) {
    console.error('❌ Error: TELEGRAM_BOT_TOKEN not found in .env');
    process.exit(1);
}

// Initialize Bot
const bot = new TelegramBot(token, { polling: true });

// State
const seenMarkets = new Set();
let firstRun = true;

// User Preferences: chatId -> { crypto: true, politics: true, ... }
const userPrefs = new Map();

const CATEGORIES = {
    POLITICS: 'Politics',
    CRYPTO: 'Crypto',
    SPORTS: 'Sports',
    BUSINESS: 'Business',
    SCIENCE: 'Science',
    POPCULTURE: 'Pop Culture',
    NEWS: 'News',
    OTHER: 'Other'
};

function getUserPrefs(chatId) {
    if (!userPrefs.has(chatId)) {
        userPrefs.set(chatId, {
            [CATEGORIES.POLITICS]: true,
            [CATEGORIES.CRYPTO]: true,
            [CATEGORIES.SPORTS]: true,
            [CATEGORIES.BUSINESS]: true,
            [CATEGORIES.SCIENCE]: true,
            [CATEGORIES.POPCULTURE]: true,
            [CATEGORIES.NEWS]: true,
            [CATEGORIES.OTHER]: true
        });
    }
    return userPrefs.get(chatId);
}

console.log('👴 Ok Boomer Bot (Node.js) Starting...');

// Helper: Get Main Keyboard
function getSettingsKeyboard(chatId) {
    const prefs = getUserPrefs(chatId);

    return {
        inline_keyboard: [
            [
                { text: `${prefs[CATEGORIES.POLITICS] ? '✅' : '❌'} Politics`, callback_data: `toggle_${CATEGORIES.POLITICS}` },
                { text: `${prefs[CATEGORIES.CRYPTO] ? '✅' : '❌'} Crypto`, callback_data: `toggle_${CATEGORIES.CRYPTO}` }
            ],
            [
                { text: `${prefs[CATEGORIES.SPORTS] ? '✅' : '❌'} Sports`, callback_data: `toggle_${CATEGORIES.SPORTS}` },
                { text: `${prefs[CATEGORIES.BUSINESS] ? '✅' : '❌'} Business`, callback_data: `toggle_${CATEGORIES.BUSINESS}` }
            ],
            [
                { text: `${prefs[CATEGORIES.SCIENCE] ? '✅' : '❌'} Science`, callback_data: `toggle_${CATEGORIES.SCIENCE}` },
                { text: `${prefs[CATEGORIES.POPCULTURE] ? '✅' : '❌'} Pop Culture`, callback_data: `toggle_${CATEGORIES.POPCULTURE}` }
            ],
            [
                { text: `${prefs[CATEGORIES.NEWS] ? '✅' : '❌'} News`, callback_data: `toggle_${CATEGORIES.NEWS}` },
                { text: `${prefs[CATEGORIES.OTHER] ? '✅' : '❌'} Other`, callback_data: `toggle_${CATEGORIES.OTHER}` }
            ]
        ]
    };
}

// Command Handlers
bot.onText(/\/start/, (msg) => {
    const chatId = msg.chat.id;
    getUserPrefs(chatId); // Init prefs

    console.log(`✅ New user subscribed: ${chatId}`);

    bot.sendMessage(chatId,
        "👴 **Ok Boomer New Market Alerts**\n\n" +
        "✅ You are now subscribed.\n" +
        "Configure your alert preferences below:",
        {
            parse_mode: 'Markdown',
            reply_markup: getSettingsKeyboard(chatId)
        }
    );
});

bot.onText(/\/settings/, (msg) => {
    const chatId = msg.chat.id;
    bot.sendMessage(chatId, "⚙️ **Alert Preferences**", {
        parse_mode: 'Markdown',
        reply_markup: getSettingsKeyboard(chatId)
    });
});

// Callback Handler for Settings
bot.on('callback_query', (query) => {
    const chatId = query.message.chat.id;
    const data = query.data;

    if (data.startsWith('toggle_')) {
        const category = data.replace('toggle_', '');
        const prefs = getUserPrefs(chatId);

        // Toggle
        prefs[category] = !prefs[category];
        userPrefs.set(chatId, prefs);

        // Update keyboard
        bot.editMessageReplyMarkup(getSettingsKeyboard(chatId), {
            chat_id: chatId,
            message_id: query.message.message_id
        });

        bot.answerCallbackQuery(query.id, { text: `${category} alerts ${prefs[category] ? 'enabled' : 'disabled'}` });
    }
});

// Determine Category
function detectCategory(market) {
    const text = (market.question + ' ' + (market.group || '') + ' ' + (market.tags || [])).toLowerCase();

    if (text.includes('bitcoin') || text.includes('crypto') || text.includes('eth') || text.includes('solana') || text.includes('coin') || text.includes('token')) return CATEGORIES.CRYPTO;
    if (text.includes('election') || text.includes('trump') || text.includes('biden') || text.includes('senate') || text.includes('politics') || text.includes('vote')) return CATEGORIES.POLITICS;
    if (text.includes('nfl') || text.includes('nba') || text.includes('football') || text.includes('soccer') || text.includes('sport') || text.includes('f1') || text.includes('ufc')) return CATEGORIES.SPORTS;
    if (text.includes('stock') || text.includes('fed') || text.includes('rate') || text.includes('recession') || text.includes('economy') || text.includes('business') || text.includes('price')) return CATEGORIES.BUSINESS;
    if (text.includes('science') || text.includes('space') || text.includes('nasa') || text.includes('apple') || text.includes('gpt') || text.includes('ai ') || text.includes('tech')) return CATEGORIES.SCIENCE;
    if (text.includes('movie') || text.includes('music') || text.includes('song') || text.includes('grammy') || text.includes('oscar') || text.includes('celebrity') || text.includes('spotify')) return CATEGORIES.POPCULTURE;
    if (text.includes('war') || text.includes('weather') || text.includes('climate') || text.includes('news') || text.includes('global')) return CATEGORIES.NEWS;

    return CATEGORIES.OTHER;
}

// Fetch Markets Function
async function fetchMarkets() {
    try {
        const response = await axios.get(POLYMARKET_API, {
            params: {
                limit: 20,
                active: true,
                order: 'createdAt',
                ascending: false
            }
        });
        return response.data || [];
    } catch (error) {
        console.error('Error fetching markets:', error.message);
        return [];
    }
}

// Monitor Loop
async function monitorMarkets() {
    console.log(`Checking markets at ${new Date().toISOString()}...`);
    const markets = await fetchMarkets();

    if (firstRun) {
        markets.forEach(m => seenMarkets.add(m.id));
        firstRun = false;
        console.log(`✅ Initialized. Tracking ${seenMarkets.size} existing markets.`);
        return;
    }

    for (const market of markets) {
        if (!seenMarkets.has(market.id)) {
            console.log(`🆕 New market found: ${market.question}`);
            seenMarkets.add(market.id);
            await sendAlert(market);
        }
    }
}

// Alert Function
async function sendAlert(market) {
    const question = market.question || 'Unknown Market';
    const slug = market.slug || '';
    const url = slug ? `https://polymarket.com/event/${slug}` : 'https://polymarket.com';
    const category = detectCategory(market);

    const categoryEmoji = {
        [CATEGORIES.POLITICS]: "🏛️",
        [CATEGORIES.CRYPTO]: "₿",
        [CATEGORIES.SPORTS]: "⚽",
        [CATEGORIES.BUSINESS]: "💹",
        [CATEGORIES.SCIENCE]: "🧪",
        [CATEGORIES.POPCULTURE]: "🎬",
        [CATEGORIES.NEWS]: "📰",
        [CATEGORIES.OTHER]: "📊"
    }[category];

    const msg = `🆕 **JUST LISTED** ${categoryEmoji}\n` +
        `━━━━━━━━━━━━━━\n` +
        `📊 **${question}**\n\n` +
        `🔗 [View on Polymarket](${url})`;

    // Broadcast to relevant subscribers
    for (const [chatId, prefs] of userPrefs.entries()) {
        if (prefs[category]) {
            try {
                await bot.sendMessage(chatId, msg, {
                    parse_mode: 'Markdown',
                    disable_web_page_preview: true
                });
            } catch (error) {
                console.error(`Failed to send to ${chatId}:`, error.message);
            }
        }
    }
}

// Start Loop
setInterval(monitorMarkets, CHECK_INTERVAL);
// Run immediately on start
monitorMarkets();

// Error handling
bot.on('polling_error', (error) => {
    // Ignore common timeout errors
});
