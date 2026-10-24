"""Periodic free-disk-space check with a complaint to REPORT_CHANNEL_ID."""

import random
import shutil
import time

import structlog
from telegram.ext import ContextTypes

from bot.config import settings

logger = structlog.get_logger()

LOW_DISK_PHRASES = [
    "У меня место закончилось :-(",
    "Мне тут тесновато, помогите!",
    "Диск почти полный, я задыхаюсь 😵",
    "Кажется, я переел байтов. Освободите место, пожалуйста 🙏",
    "Ещё немного — и мне некуда будет записывать ваши шаги 😟",
    "SOS! Свободного места почти не осталось 🆘",
]

_last_alert_at: float | None = None


async def check_disk_space_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Post a random complaint when free space drops below the threshold.

    While space stays low, the alert repeats at most once per
    ``DISK_ALERT_REPEAT_MINUTES``. The cooldown resets once space recovers.
    """
    global _last_alert_at

    try:
        free_mb = shutil.disk_usage(settings.disk_check_path).free / (1024 * 1024)
    except OSError as exc:
        logger.error("Failed to check disk usage", error=str(exc))
        return

    if free_mb >= settings.disk_free_threshold_mb:
        _last_alert_at = None
        return

    logger.warning(
        "Low disk space",
        free_mb=round(free_mb, 1),
        threshold_mb=settings.disk_free_threshold_mb,
    )

    now = time.monotonic()
    if (
        _last_alert_at is not None
        and now - _last_alert_at < settings.disk_alert_repeat_minutes * 60
    ):
        return

    if not settings.report_channel_id:
        return

    text = f"{random.choice(LOW_DISK_PHRASES)}\n(свободно {free_mb:.0f} МБ)"
    try:
        await context.bot.send_message(chat_id=settings.report_channel_id, text=text)
        _last_alert_at = now
        logger.info("Low disk alert sent", channel_id=settings.report_channel_id)
    except Exception as exc:
        logger.error("Failed to send low disk alert", error=str(exc))
