const TelegramBot = require('node-telegram-bot-api');
require('dotenv').config();

const token = process.env.TELEGRAM_BOT_TOKEN;
const bot = new TelegramBot(token);

async function updateProfile() {
    try {
        console.log("Updating Bot Profile...");

        // 1. Set Name (The name at the top of the chat)
        await bot.setMyName({ name: "Ok Boomer" });
        console.log("✅ Name set to: Ok Boomer");

        // 2. Set Description (What people see before they click Start)
        await bot.setMyDescription({ description: "👴 Instant Notifictions for New Polymarket Listings.\n\nBe the first to know. Ok Boomer?" });
        console.log("✅ Description updated.");

        // 3. Set Short Description (The text on the chat info page)
        await bot.setMyShortDescription({ short_description: "👴 Instant Polymarket Alerts" });
        console.log("✅ Short Description updated.");

        console.log("🎉 SUCCESS! You may need to restart your Telegram app to see changes.");
        process.exit(0);
    } catch (error) {
        console.error("❌ Error updating profile:", error.message);
        process.exit(1);
    }
}

updateProfile();
