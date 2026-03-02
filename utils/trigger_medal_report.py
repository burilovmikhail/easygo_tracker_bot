"""Manually trigger the medal assignment job for the previous MSK day.

Usage (from project root or inside the container):
    python -m utils.trigger_medal_report
    docker exec -it tracker_bot python -m utils.trigger_medal_report
"""

import asyncio
import sys
from types import SimpleNamespace

import structlog
from telegram import Bot

from bot.config import settings
from bot.database import MongoDB
from bot.medals import assign_medals_job
from bot.models import MedalRecord, StepReport, TelegramMessage, TelegramUser
from bot.sheets import SheetsService
from bot.utils.logger import setup_logging

setup_logging()
logger = structlog.get_logger()


async def main() -> None:
    logger.info("Connecting to MongoDB...")
    await MongoDB.connect(
        mongodb_uri=settings.mongodb_uri,
        document_models=[TelegramMessage, TelegramUser, StepReport, MedalRecord],
    )

    sheets_service = SheetsService(
        credentials_path=settings.google_credentials_path,
        spreadsheet_id=settings.google_sheet_id,
        steps_worksheet=settings.worksheet_name,
    )

    async with Bot(token=settings.telegram_api_key) as bot:
        context = SimpleNamespace(
            bot=bot,
            bot_data={"sheets_service": sheets_service},
        )
        logger.info("Triggering medal assignment job...")
        await assign_medals_job(context)

    await MongoDB.close()
    logger.info("Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.error("trigger_medal_report failed", error=str(exc))
        sys.exit(1)
