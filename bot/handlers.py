import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.config import settings
from bot.models import TelegramMessage, TelegramUser
from bot.parser import parse_report

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Public handler — registered in main.py
# ---------------------------------------------------------------------------


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist every text message to MongoDB, then route #отчет messages."""
    message = update.message or update.channel_post
    if message is None or not message.text:
        return

    # Allowlist check — silently drop anything not from a configured chat.
    if settings.allowed_chat_ids and message.chat_id not in settings.allowed_chat_ids:
        logger.warning(
            "Message from unauthorized chat ignored",
            chat_id=message.chat_id,
        )
        return

    # Save to MongoDB (TTL index on `date` ensures 24 h auto-expiry)
    try:
        await TelegramMessage(
            message_id=message.message_id,
            chat_id=message.chat_id,
            user_id=message.from_user.id if message.from_user else None,
            username=message.from_user.username if message.from_user else None,
            text=message.text,
            date=message.date,
        ).insert()
    except Exception as exc:
        logger.error("Failed to save message to MongoDB", error=str(exc))

    if "#отчет" in message.text.lower():
        await _handle_report(update, context)


# ---------------------------------------------------------------------------
# Internal — helpers
# ---------------------------------------------------------------------------


async def _resolve_nickname(user_id: Optional[int], parsed_nickname: Optional[str]) -> Optional[str]:
    """Return the nickname for this report; upsert TelegramUser as a side-effect.

    Resolution order:
    1. Use ``parsed_nickname`` from the message text if present.
    2. Fall back to the stored nickname for ``user_id`` when no nickname was parsed.

    When ``user_id`` is known and ``parsed_nickname`` is provided, the stored
    profile is created or updated to keep it in sync.
    """
    if parsed_nickname:
        if user_id is not None:
            user = await TelegramUser.find_one(TelegramUser.user_id == user_id)
            if user is None:
                await TelegramUser(user_id=user_id, nickname=parsed_nickname).insert()
            elif user.nickname != parsed_nickname:
                user.nickname = parsed_nickname
                await user.save()
        return parsed_nickname

    if user_id is not None:
        user = await TelegramUser.find_one(TelegramUser.user_id == user_id)
        if user:
            return user.nickname

    return None


# ---------------------------------------------------------------------------
# Internal — report processing
# ---------------------------------------------------------------------------


async def _handle_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse the #отчет message, validate, and write to Google Sheets."""
    message = update.message or update.channel_post
    chat_id = message.chat_id
    message_id = message.message_id
    user_id = message.from_user.id if message.from_user else None

    report = parse_report(message.text)

    try:
        nickname = await _resolve_nickname(user_id, report.nickname)
    except Exception as exc:
        logger.error("Failed to resolve nickname from DB", error=str(exc))
        nickname = report.nickname

    # Validate required fields
    if not nickname:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Отсутствует #ник",
            reply_to_message_id=message_id,
        )
        return

    if report.steps is None:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Отсутствует количество шагов",
            reply_to_message_id=message_id,
        )
        return

    # Default date to today (UTC) when not present in the message
    report_date = report.date or datetime.now(timezone.utc)

    sheets_service = context.bot_data.get("sheets_service")
    if sheets_service is None:
        logger.error("SheetsService not initialised in bot_data")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Ошибка сохранения данных",
            reply_to_message_id=message_id,
        )
        return

    try:
        await asyncio.to_thread(
            sheets_service.write_steps,
            nickname,
            report_date,
            report.steps,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"#{nickname} - принято",
            reply_to_message_id=message_id,
        )
    except Exception as exc:
        logger.error("Failed to write to Google Sheets", error=str(exc))
        await context.bot.send_message(
            chat_id=chat_id,
            text="Ошибка сохранения данных",
            reply_to_message_id=message_id,
        )
