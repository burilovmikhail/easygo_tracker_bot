"""Daily medal assignment job (runs at 20:00 MSK = 17:00 UTC)."""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import structlog
from telegram.ext import ContextTypes

from bot.config import settings
from bot.models import MedalRecord, MedalType, MEDAL_SYMBOLS, StepReport

logger = structlog.get_logger()

_MSK = timezone(timedelta(hours=3))


async def assign_medals_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Award gold 🥇, silver 🥈, bronze 🥉 for the previous MSK calendar day.

    Uses dense ranking: tied step counts share the same medal.
    Only the top 3 distinct step values receive medals.
    """
    now_msk = datetime.now(_MSK)
    yesterday = (now_msk - timedelta(days=1)).date()

    day_start = datetime(yesterday.year, yesterday.month,
                         yesterday.day)
    day_end = day_start + timedelta(days=1)

    logger.info("Running medal assignment", date=str(yesterday))

    try:
        reports = await StepReport.find(
            StepReport.date >= day_start,
            StepReport.date < day_end,
        ).to_list()
    except Exception as exc:
        logger.error("Failed to query step reports for medals", error=str(exc))
        return

    if not reports:
        logger.info("No step reports found, skipping medals",
                    date=str(yesterday))
        return

    # Dense ranking: sort descending, assign medal by distinct step rank
    reports.sort(key=lambda r: r.steps, reverse=True)
    medal_order = [MedalType.GOLD, MedalType.SILVER, MedalType.BRONZE]

    ranked: list[tuple[StepReport, MedalType]] = []
    rank = 0
    prev_steps: int | None = None
    for report in reports:
        if report.steps != prev_steps:
            rank += 1
            prev_steps = report.steps
        if rank > 3:
            break
        ranked.append((report, medal_order[rank - 1]))

    sheets_service = context.bot_data.get("sheets_service")

    for report, medal in ranked:
        symbol = MEDAL_SYMBOLS[medal]

        # Upsert medal record in MongoDB
        try:
            existing = await MedalRecord.find_one(
                MedalRecord.nickname == report.nickname,
                MedalRecord.date == day_start,
            )
            if existing is None:
                await MedalRecord(
                    user_id=report.user_id,
                    nickname=report.nickname,
                    date=day_start,
                    medal=medal,
                ).insert()
            else:
                existing.medal = medal
                await existing.save()
        except Exception as exc:
            logger.error("Failed to save medal record",
                         nickname=report.nickname, error=str(exc))

        # Write medal symbol into the steps sheet cell
        if sheets_service:
            try:
                await asyncio.to_thread(
                    sheets_service.write_medal,
                    report.nickname,
                    day_start,
                    symbol,
                )
            except Exception as exc:
                logger.error(
                    "Failed to write medal to sheet",
                    nickname=report.nickname,
                    error=str(exc),
                )

    logger.info(
        "Medal assignment complete",
        date=str(yesterday),
        awarded=[(r.nickname, m.value) for r, m in ranked],
    )

    if settings.report_channel_id:
        await _post_medal_report(context, ranked, yesterday)


async def _post_medal_report(
    context: ContextTypes.DEFAULT_TYPE,
    ranked: list[tuple[StepReport, MedalType]],
    date,
) -> None:
    """Send a medal summary message to REPORT_CHANNEL_ID."""
    # Group winners by medal type to handle ties on one line
    by_medal: dict[MedalType, list[StepReport]] = defaultdict(list)
    for report, medal in ranked:
        by_medal[medal].append(report)

    lines = [f"Медали за {date.strftime('%d.%m.%Y')}:"]
    for medal in (MedalType.GOLD, MedalType.SILVER, MedalType.BRONZE):
        if medal not in by_medal:
            continue
        winners = by_medal[medal]
        symbol = MEDAL_SYMBOLS[medal]
        nicks = ", ".join(
            f"#{r.nickname}" if not r.nickname.startswith("#") else r.nickname
            for r in winners
        )
        steps = f"{winners[0].steps:,}".replace(",", " ")
        lines.append(f"{symbol} {nicks} — {steps} шагов")

    try:
        await context.bot.send_message(
            chat_id=settings.report_channel_id,
            text="\n".join(lines),
        )
        logger.info("Medal report sent to channel",
                    channel_id=settings.report_channel_id)
    except Exception as exc:
        logger.error("Failed to send medal report to channel", error=str(exc))
