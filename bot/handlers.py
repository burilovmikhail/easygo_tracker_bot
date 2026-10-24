import asyncio
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from beanie.operators import Set
from telegram import ReactionTypeEmoji, Update
from telegram.ext import ContextTypes

from bot.config import settings
from bot.medals import assign_medals_job
from bot.models import TelegramMessage, TelegramUser, StepReport, MedalRecord, MEDAL_SYMBOLS
from bot.parser import ReportData, parse_report
from bot.sheets import NicknameNotFoundError

logger = structlog.get_logger()

# Vladivostok is permanently UTC+10 (no DST since 2014)
_VLADIVOSTOK_TZ = timezone(timedelta(hours=10))

# Upper bound on the number of days in a range report ("21.06-24.06 ...")
_MAX_RANGE_DAYS = 31


# ---------------------------------------------------------------------------
# Public handler — registered in main.py
# ---------------------------------------------------------------------------


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist every text message to MongoDB, then route #отчет messages."""
    message = update.effective_message
    if message is None:
        logger.info("Empty message")
        return

    text = message.text or message.caption
    if not text:
        logger.info("Empty message text")
        return

    logger.info("handle_message", text=text)

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
            text=text,
            date=message.date,
        ).insert()
    except Exception as exc:
        logger.error("Failed to save message to MongoDB", error=str(exc))

    text_lower = text.lower()
    if "#отчет" in text_lower or "#отчёт" in text_lower:
        await _handle_report(update, context, text)
    elif re.search(r'ии[\s\-]*(говно|какашка|гамно)', text_lower):
        await _react_ai_insult(update, context)
    elif re.search(r'ии[\s\-]*(лапочка|умничка|молодец|красавчик|красавица|умник|супер|класс)', text_lower):
        await _react_ai_compliment(update, context)
    elif _is_bot_mentioned(message, context.bot.username):
        if "today-top" in text_lower:
            await _handle_today_top(update, context)
        elif "month-top" in text_lower:
            await _handle_month_top(update, context)
        elif "totals" in text_lower:
            await _handle_totals(update, context)
        elif "generate-medals" in text_lower:
            await _handle_generate_medals(update, context)
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
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    for entity in entities:
        if entity.type == "mention":
            mention = text[entity.offset: entity.offset + entity.length]
            if mention.lstrip("@").lower() == bot_username.lower():
                return True
    return False


# ---------------------------------------------------------------------------
# Internal — query commands (today-top, month-top, totals)
# ---------------------------------------------------------------------------


async def _handle_today_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the top-5 step counts for today, descending."""
    message = update.effective_message

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
    message = update.effective_message

    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(
        year=now.year + 1, month=1) if now.month == 12 else start.replace(month=now.month + 1)

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
    message = update.effective_message

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


async def _handle_generate_medals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually trigger the medal assignment job (same logic as the scheduled run)."""
    message = update.effective_message
    await context.bot.send_message(chat_id=message.chat_id, text="Рассчитываю медали...")
    await assign_medals_job(context)


# ---------------------------------------------------------------------------
# Internal — AI query
# ---------------------------------------------------------------------------


def _strip_bot_mention(text: str, bot_username: str) -> str:
    """Remove @BotName from the message text so the LLM sees only the question."""
    return re.sub(rf"@{re.escape(bot_username)}\s*", "", text, flags=re.IGNORECASE).strip()


async def _handle_ai_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forward the question to the AI service and reply with its answer."""
    message = update.effective_message

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

    asking_nickname: Optional[str] = None
    if user_id is not None:
        try:
            user = await TelegramUser.find_one(TelegramUser.user_id == user_id)
            if user:
                asking_nickname = user.nickname
        except Exception as exc:
            logger.warning(
                "Failed to resolve asking user nickname", error=str(exc))

    try:
        answer = await ai_service.handle_question(question, user_id, asking_nickname)
    except Exception as exc:
        logger.error("AI query failed", error=str(exc))
        answer = "Произошла ошибка при обращении к ИИ."

    await context.bot.send_message(
        chat_id=message.chat_id,
        text=answer,
        reply_to_message_id=message.message_id,
    )


# ---------------------------------------------------------------------------
# Internal — AI-insult reaction
# ---------------------------------------------------------------------------


async def _react_ai_insult(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """React with 🖕 or 💩 when someone says ИИ говно / ии-говно."""
    message = update.effective_message
    emoji = random.choice(["🖕", "💩"])
    try:
        await context.bot.set_message_reaction(
            chat_id=message.chat_id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception as exc:
        logger.warning("Failed to set reaction", error=str(exc))


async def _react_ai_compliment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """React with 🔥 when someone compliments the bot (ИИ лапочка / умничка / молодец etc.)."""
    message = update.effective_message
    try:
        await context.bot.set_message_reaction(
            chat_id=message.chat_id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji(emoji="🔥")],
        )
    except Exception as exc:
        logger.warning("Failed to set reaction", error=str(exc))


# ---------------------------------------------------------------------------
# Internal — report processing
# ---------------------------------------------------------------------------


async def _handle_report(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Parse the #отчет message, validate, and write to Google Sheets."""
    message = update.effective_message
    chat_id = message.chat_id
    message_id = message.message_id
    user_id = message.from_user.id if message.from_user else None

    logger.info("Parsing report...", text=text)

    report = parse_report(text)

    # Several candidate nicknames — refuse rather than guess (and don't touch
    # the stored nickname).
    if report.ambiguous_nicknames:
        tags = ", ".join(f"#{t}" for t in report.ambiguous_nicknames)
        logger.warning("Ambiguous nickname in report", text=text, candidates=tags)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Непонятно, чей это отчёт: несколько ников ({tags}). "
                 f"Оставьте в отчёте только один #ник. Отчёт не принят.",
            reply_to_message_id=message_id,
        )
        return

    try:
        nickname = await _resolve_nickname(user_id, report.nickname)
    except Exception as exc:
        logger.error("Failed to resolve nickname from DB", error=str(exc))
        nickname = report.nickname

    # Validate required fields
    if not nickname:
        logger.warning("Missing nickname in report", text=text)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Отсутствует #ник",
            reply_to_message_id=message_id,
        )
        return

    if report.is_range:
        entries, error = _range_entries(report)
    else:
        entries, error = _single_entries(report)

    if error:
        logger.warning("Invalid report", text=text, error=error)
        await context.bot.send_message(
            chat_id=chat_id,
            text=error,
            reply_to_message_id=message_id,
        )
        return

    sheets_service = context.bot_data.get("sheets_service")
    if sheets_service is None:
        logger.error("SheetsService not initialised in bot_data")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Ошибка сохранения данных",
            reply_to_message_id=message_id,
        )
        return

    logger.info("Recording steps", nickname=nickname,
                entries=[(d.strftime("%d.%m.%Y"), st) for d, st in entries])

    try:
        await asyncio.to_thread(
            sheets_service.write_steps_many,
            nickname,
            entries,
        )
    except NicknameNotFoundError:
        logger.warning("Nickname not found in sheet", nickname=nickname,
                       dates=[d.strftime("%d.%m.%Y") for d, _ in entries])
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Ник {nickname} не найден в таблице — строка не добавлена. "
                 f"Проверьте, что ник есть в списке участников.",
            reply_to_message_id=message_id,
        )
        return
    except Exception as exc:
        logger.error("Failed to write to Google Sheets", error=str(exc))
        await context.bot.send_message(
            chat_id=chat_id,
            text="Ошибка сохранения данных",
            reply_to_message_id=message_id,
        )
        return

    for report_date, steps in entries:
        try:
            await StepReport.find_one(
                StepReport.nickname == nickname,
                StepReport.date == report_date,
            ).upsert(
                Set({StepReport.steps: steps}),
                on_insert=StepReport(
                    user_id=user_id,
                    nickname=nickname,
                    date=report_date,
                    steps=steps,
                ),
            )
        except Exception as exc:
            logger.error("Failed to save report to MongoDB",
                         report_date=report_date, error=str(exc))

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"#{nickname} - принято" + (
            f" ({entries[0][0]:%d.%m}–{entries[-1][0]:%d.%m}, дней: {len(entries)})"
            if report.is_range else ""
        ),
        reply_to_message_id=message_id,
    )


def _validate_report_date(report_date: datetime) -> Optional[str]:
    """Return an error text if the date is outside the current year or in the future."""
    vladivostok_today = datetime.now(_VLADIVOSTOK_TZ).date()
    if report_date.date().year != vladivostok_today.year:
        return "Недопустимая дата: принимаются отчёты только за текущий год"
    if report_date.date() > vladivostok_today:
        return "Недопустимая дата: дата ещё не наступила"
    return None


def _single_entries(report: ReportData) -> tuple[list[tuple[datetime, int]], Optional[str]]:
    """Build the (date, steps) list for a single-day report, or return an error text."""
    if report.steps is None:
        return [], "Отсутствует количество шагов"

    if report.date is not None:
        error = _validate_report_date(report.date)
        if error:
            return [], error

    # Default date to today (UTC) when not present in the message
    return [(report.date or datetime.now(timezone.utc), report.steps)], None


def _range_entries(report: ReportData) -> tuple[list[tuple[datetime, int]], Optional[str]]:
    """Build the (date, steps) list for a date-range report, or return an error text.

    Both range ends are inclusive; the number of step values must equal the
    number of days in the range.
    """
    if report.date is None or report.date_to is None:
        return [], "Недопустимый диапазон дат"
    if report.date > report.date_to:
        return [], "Недопустимый диапазон дат: начало позже конца"
    if not report.steps_list:
        return [], "Отсутствует количество шагов"

    for d in (report.date, report.date_to):
        error = _validate_report_date(d)
        if error:
            return [], error

    days = (report.date_to - report.date).days + 1
    if days > _MAX_RANGE_DAYS:
        return [], f"Слишком длинный диапазон: не больше {_MAX_RANGE_DAYS} дней"
    if len(report.steps_list) != days:
        return [], (
            f"Количество значений шагов ({len(report.steps_list)}) не совпадает "
            f"с числом дней {report.date:%d.%m}–{report.date_to:%d.%m} ({days})"
        )

    return [
        (report.date + timedelta(days=i), steps)
        for i, steps in enumerate(report.steps_list)
    ], None
