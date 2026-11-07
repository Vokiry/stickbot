import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.config import settings
from bot.database.db import Database
from bot.middlewares.db_middleware import DatabaseMiddleware
from bot.handlers import routers


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )


async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="🚀 Запустить бота"),
        BotCommand(command="newpack", description="🎨 Создать новый стикерпак"),
        BotCommand(command="import", description="📥 Импортировать/склонировать пак"),
        BotCommand(command="packs", description="📂 Мои стикерпаки"),
        BotCommand(command="settings", description="⚙️ Настройки"),
        BotCommand(command="help", description="ℹ️ Инструкция и помощь"),
        BotCommand(command="cancel", description="❌ Отменить текущее действие"),
    ]
    await bot.set_my_commands(commands)


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Initializing StickBot...")

    # Ensure directories exist
    settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Initialize Database
    db = Database(settings.DB_PATH)
    await db.init()

    # Initialize Bot and Dispatcher
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer

    session = None
    if settings.TELEGRAM_API_SERVER or settings.PROXY_URL:
        api_server = (
            TelegramAPIServer.from_base(settings.TELEGRAM_API_SERVER)
            if settings.TELEGRAM_API_SERVER
            else TelegramAPIServer.from_base("https://api.telegram.org")
        )
        session = AiohttpSession(api=api_server, proxy=settings.PROXY_URL)

    bot = Bot(
        token=settings.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=None)
    )
    dp = Dispatcher()

    # Register Middlewares
    from bot.middlewares.throttling_middleware import ThrottlingMiddleware

    db_middleware = DatabaseMiddleware(db)
    dp.message.outer_middleware(db_middleware)
    dp.callback_query.outer_middleware(db_middleware)

    # Throttling to protect server CPU from media flood
    dp.message.middleware(ThrottlingMiddleware(rate_limit_seconds=1.2))

    # Register Routers
    for r in routers:
        dp.include_router(r)

    # Check Bot info
    me = await bot.get_me()
    logger.info("Bot authenticated: @%s (ID: %d)", me.username, me.id)
    settings.BOT_USERNAME = me.username

    # Configure Bot Commands in Telegram Menu
    try:
        await set_bot_commands(bot)
    except Exception as e:
        logger.warning("Could not set bot commands: %s", e)

    # Delete existing webhook if any to allow long polling
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Starting polling loop...")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot interrupted by user.")
