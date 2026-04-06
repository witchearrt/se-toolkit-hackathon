import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from handlers import router
from database import init_db

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set in .env file!")


async def main():
    # Initialize database
    await init_db()

    # Create bot
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )

    # Create dispatcher
    dp = Dispatcher()

    # Include our router
    dp.include_router(router)

    # Start polling
    print("🤖 Bot is starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped!")


def run():
    """Entry point for Docker CMD"""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
