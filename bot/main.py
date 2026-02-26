import structlog
from telegram.ext import Application, MessageHandler, filters

from bot.config import settings
from bot.database import MongoDB
from bot.handlers import handle_message
from bot.models import TelegramMessage, TelegramUser, StepReport
from bot.sheets import SheetsService
from bot.utils.logger import setup_logging

# Setup logging
setup_logging()
logger = structlog.get_logger()


async def startup(application: Application) -> None:
    """Initialize connections and services."""
    logger.info("Starting EasyGo Bot...")

    await MongoDB.connect(
        mongodb_uri=settings.mongodb_uri,
        document_models=[TelegramMessage, TelegramUser, StepReport],
    )

    application.bot_data["sheets_service"] = SheetsService(
        credentials_path=settings.google_credentials_path,
        spreadsheet_id=settings.google_sheet_id,
    )

    logger.info("Startup complete")


async def shutdown(application: Application) -> None:
    """Cleanup connections and services."""
    logger.info("Shutting down EasyGo Bot...")
    await MongoDB.close()
    logger.info("Shutdown complete")


def main() -> None:
    """Main entry point for the bot."""
    logger.info("Initializing EasyGo Bot", log_level=settings.log_level)

    application = Application.builder().token(settings.telegram_api_key).build()

    application.post_init = startup
    application.post_shutdown = shutdown

    # Handle all text messages — works for both regular chats and channel posts
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Starting polling...")

    application.run_polling(
        allowed_updates=["message", "channel_post"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error("Fatal error", error=str(e))
        raise
