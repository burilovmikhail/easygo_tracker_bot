import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from beanie.operators import Set
from telegram import Update
from telegram.ext import ContextTypes

from bot.config import settings
from bot.models import TelegramMessage, TelegramUser, StepReport
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

    text_lower = message.text.lower()
    if "#отчет" in text_lower:
        await _handle_report(update, context)
    elif _is_bot_mentioned(message, context.bot.username):
        if "today-top" in text_lower:
            await _handle_today_top(update, context)
        elif "month-top" in text_lower:
            await _handle_month_top(update, context)
        elif "totals" in text_lower:
            await _handle_totals(update, context)
        else:
            await _handle_ai_query(update, context)


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
# Internal — mention detection
# ---------------------------------------------------------------------------


def _is_bot_mentioned(message, bot_username: str) -> bool:
    """Return True if the bot is explicitly @mentioned in the message."""
    if not message.entities:
        return False
    for entity in message.entities:
        if entity.type == "mention":
            mention = message.text[entity.offset : entity.offset + entity.length]
            if mention.lstrip("@").lower() == bot_username.lower():
                return True
    return False


# ---------------------------------------------------------------------------
# Internal — query commands (today-top, month-top, totals)
# ---------------------------------------------------------------------------


async def _handle_today_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the top-5 step counts for today, descending."""
    message = update.message or update.channel_post
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    try:
        reports = (
            await StepReport.find(StepReport.date >= start, StepReport.date < end)
            .sort("-steps")
            .limit(5)
            .to_list()
        )
    except Exception as exc:
        logger.error("Failed to query today-top", error=str(exc))
        return

    if not reports:
        text = "Нет данных за сегодня"
    else:
        lines = ["Топ-5 за сегодня:"]
        for i, r in enumerate(reports, 1):
            lines.append(f"{i}. #{r.nickname} — {r.steps:,} шагов")
        text = "\n".join(lines)

    await context.bot.send_message(chat_id=message.chat_id, text=text)


async def _handle_month_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the top-5 step totals for the current month, descending."""
    message = update.message or update.channel_post
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=now.year + 1, month=1) if now.month == 12 else start.replace(month=now.month + 1)

    try:
        results = await StepReport.aggregate([
            {"$match": {"date": {"$gte": start, "$lt": end}}},
            {"$group": {"_id": "$nickname", "total": {"$sum": "$steps"}}},
            {"$sort": {"total": -1}},
            {"$limit": 5},
        ]).to_list()
    except Exception as exc:
        logger.error("Failed to query month-top", error=str(exc))
        return

    if not results:
        text = "Нет данных за этот месяц"
    else:
        lines = ["Топ-5 за месяц:"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. #{r['_id']} — {r['total']:,} шагов")
        text = "\n".join(lines)

    await context.bot.send_message(chat_id=message.chat_id, text=text)


async def _handle_totals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with total steps per nickname (all time, unordered)."""
    message = update.message or update.channel_post

    try:
        results = await StepReport.aggregate([
            {"$group": {"_id": "$nickname", "total": {"$sum": "$steps"}}},
        ]).to_list()
    except Exception as exc:
        logger.error("Failed to query totals", error=str(exc))
        return

    if not results:
        text = "Нет данных"
    else:
        lines = ["Итого шагов:"]
        for r in results:
            lines.append(f"#{r['_id']} — {r['total']:,}")
        text = "\n".join(lines)

    await context.bot.send_message(chat_id=message.chat_id, text=text)


# ---------------------------------------------------------------------------
# Internal — AI query
# ---------------------------------------------------------------------------


def _strip_bot_mention(text: str, bot_username: str) -> str:
    """Remove @BotName from the message text so the LLM sees only the question."""
    return re.sub(rf"@{re.escape(bot_username)}\s*", "", text, flags=re.IGNORECASE).strip()


async def _handle_ai_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forward the question to the AI service and reply with its answer."""
    message = update.message or update.channel_post

    ai_service = context.bot_data.get("ai_service")
    if ai_service is None:
        await context.bot.send_message(
            chat_id=message.chat_id,
            text="AI не настроен.",
            reply_to_message_id=message.message_id,
        )
        return

    question = _strip_bot_mention(message.text, context.bot.username)
    if not question:
        return

    user_id = message.from_user.id if message.from_user else None

    try:
        answer = await ai_service.handle_question(question, user_id)
    except Exception as exc:
        logger.error("AI query failed", error=str(exc))
        answer = "Произошла ошибка при обращении к ИИ."

    await context.bot.send_message(
        chat_id=message.chat_id,
        text=answer,
        reply_to_message_id=message.message_id,
    )


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
    except Exception as exc:
        logger.error("Failed to write to Google Sheets", error=str(exc))
        await context.bot.send_message(
            chat_id=chat_id,
            text="Ошибка сохранения данных",
            reply_to_message_id=message_id,
        )
        return

    try:
        await StepReport.find_one(
            StepReport.nickname == nickname,
            StepReport.date == report_date,
        ).upsert(
            Set({StepReport.steps: report.steps}),
            on_insert=StepReport(
                user_id=user_id,
                nickname=nickname,
                date=report_date,
                steps=report.steps,
            ),
        )
    except Exception as exc:
        logger.error("Failed to save report to MongoDB", error=str(exc))

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"#{nickname} - принято",
        reply_to_message_id=message_id,
    )
