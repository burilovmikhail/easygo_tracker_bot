from datetime import time, timezone

import structlog
from telegram.ext import Application, MessageHandler, filters

from bot.ai import AIService
from bot.config import settings
from bot.database import MongoDB
from bot.disk_monitor import check_disk_space_job
from bot.handlers import handle_message
from bot.medals import assign_medals_job
from bot.models import TelegramMessage, TelegramUser, StepReport, MedalRecord
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
        document_models=[TelegramMessage, TelegramUser, StepReport, MedalRecord],
    )

    application.bot_data["sheets_service"] = SheetsService(
        credentials_path=settings.google_credentials_path,
        spreadsheet_id=settings.google_sheet_id,
    )

    if settings.openai_api_key:
        application.bot_data["ai_service"] = AIService(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
        logger.info("AIService initialised", model=settings.openai_model)
    else:
        logger.info("OPENAI_API_KEY not set — AI features disabled")

    # Schedule daily medal assignment at 20:00 MSK (17:00 UTC)
    _20_MSK_IN_UTC = time(hour=17, minute=0, tzinfo=timezone.utc)
    application.job_queue.run_daily(assign_medals_job, time=_20_MSK_IN_UTC)
    logger.info("Medal assignment job scheduled", utc_time="17:00")

    application.job_queue.run_repeating(
        check_disk_space_job,
        interval=settings.disk_check_interval_minutes * 60,
        first=10,
    )
    logger.info(
        "Disk space check scheduled",
        interval_minutes=settings.disk_check_interval_minutes,
        threshold_mb=settings.disk_free_threshold_mb,
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

    # Handle text messages and photo/media messages with captions
    application.add_handler(
        MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, handle_message)
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
