"""Manually trigger the medal assignment job.

By default it processes the previous MSK day. Pass a date (YYYY-MM-DD or
DD.MM.YYYY) to backfill medals for a specific day.

Usage (from project root or inside the container):
    python -m utils.trigger_medal_report                # previous MSK day
    python -m utils.trigger_medal_report 2026-07-17     # specific day
    docker exec -it tracker_bot python -m utils.trigger_medal_report 17.07.2026
"""

import asyncio
import sys
from datetime import date, datetime
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


def _parse_date(value: str) -> date:
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date: {value!r} (use YYYY-MM-DD or DD.MM.YYYY)")


async def main(target_date: date | None) -> None:
    logger.info("Connecting to MongoDB...")
    await MongoDB.connect(
        mongodb_uri=settings.mongodb_uri,
        document_models=[TelegramMessage, TelegramUser, StepReport, MedalRecord],
    )

    sheets_service = SheetsService(
        credentials_path=settings.google_credentials_path,
        spreadsheet_id=settings.google_sheet_id,
    )

    async with Bot(token=settings.telegram_api_key) as bot:
        context = SimpleNamespace(
            bot=bot,
            bot_data={"sheets_service": sheets_service},
        )
        logger.info("Triggering medal assignment job...",
                    target_date=str(target_date) if target_date else "yesterday")
        await assign_medals_job(context, target_date)

    await MongoDB.close()
    logger.info("Done.")


if __name__ == "__main__":
    target = None
    if len(sys.argv) > 1:
        try:
            target = _parse_date(sys.argv[1])
        except ValueError as exc:
            logger.error("Invalid date argument", error=str(exc))
            sys.exit(2)
    try:
        asyncio.run(main(target))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.error("trigger_medal_report failed", error=str(exc))
        sys.exit(1)
