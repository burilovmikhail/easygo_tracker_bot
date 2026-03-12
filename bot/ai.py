import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from openai import AsyncOpenAI

from bot.models import MedalRecord, StepReport, TelegramMessage, TelegramUser

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_CLASSIFIER_SYSTEM = """\
You are a context router for a Telegram step-tracking fitness bot.

The bot stores the following data:
- "none"             — no database data needed (greetings, general questions, etc.)
- "message_history"  — all text messages posted in the channel in the last 24 h
- "user_steps"       — step reports for a single user, identified by nickname
- "all_steps"        — step reports for every user (last 30 days)
- "user_medals"      — medals earned by a single user (last 30 days)
- "all_medals"       — medals earned by every user (last 30 days)

Analyse the user's question and return JSON with exactly two fields:
  "contexts": array of one or more of the above values; use ["none"] when no data needed
  "nickname": null, or the nickname mentioned in the question (lowercase, without #, preserve original script — do NOT transliterate Cyrillic to Latin)

Rules:
- Include multiple contexts when the question spans different data types (e.g. steps AND medals).
- Use "user_*" variants over "all_*" when the question is clearly about one person.
- "nickname" applies to all "user_*" contexts simultaneously.
- If the user asks about themselves without naming anyone, set "nickname" to null.
{asking_hint}\
"""

_ANSWER_SYSTEM = """\
You are a helpful assistant for a step-tracking fitness challenge in a Telegram channel.
Today is {today}. Yesterday was {yesterday}.
Answer in the same language as the question (usually Russian).
Be concise and precise. If the provided data is insufficient to answer, say so clearly.\
"""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AIService:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def handle_question(
        self,
        question: str,
        asking_user_id: Optional[int],
        asking_nickname: Optional[str] = None,
    ) -> str:
        logger.info("Handling question", question)

        """Two-step flow: classify required context, then answer with it."""
        decision = await self._classify_context(question, asking_nickname)

        logger.info(".. decision made", decision=decision)

        # Support both old "context" (str) and new "contexts" (list) formats.
        raw = decision.get("contexts") or decision.get("context") or "none"
        contexts: list[str] = raw if isinstance(raw, list) else [raw]

        nickname: Optional[str] = decision.get("nickname") or None

        # When any user-specific context is requested but no name was extracted,
        # resolve nickname from the passed asking_nickname or stored Telegram profile.
        if any(c.startswith("user_") for c in contexts) and nickname is None:
            if asking_nickname:
                nickname = asking_nickname
            elif asking_user_id is not None:
                user = await TelegramUser.find_one(TelegramUser.user_id == asking_user_id)
                if user:
                    nickname = user.nickname

        logger.info(".. using contexts and nickname", contexts=contexts, nickname=nickname)

        context_text = await self._fetch_context(contexts, nickname)
        return await self._answer(question, context_text)

    # ------------------------------------------------------------------
    # Step 1 — classify
    # ------------------------------------------------------------------

    async def _classify_context(self, question: str, asking_nickname: Optional[str] = None) -> dict:
        if asking_nickname:
            hint = f'\nThe person asking is #{asking_nickname}. When they refer to themselves (e.g. "я", "мои", "I", "me"), treat it as referring to #{asking_nickname}.'
        else:
            hint = ""
        system = _CLASSIFIER_SYSTEM.format(asking_hint=hint)
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as exc:
            logger.error("Context classification failed", error=str(exc))
            return {"contexts": ["none"], "nickname": None}

    # ------------------------------------------------------------------
    # Step 1.5 — fetch context data from MongoDB
    # ------------------------------------------------------------------

    async def _fetch_context(self, contexts: list[str], nickname: Optional[str]) -> str:
        parts: list[str] = []
        for ctx in contexts:
            if ctx == "none":
                continue
            try:
                if ctx == "message_history":
                    parts.append(await self._fetch_message_history())
                elif ctx in ("user_steps", "all_steps"):
                    parts.append(await self._fetch_step_reports(
                        nickname if ctx == "user_steps" else None
                    ))
                elif ctx in ("user_medals", "all_medals"):
                    parts.append(await self._fetch_medal_records(
                        nickname if ctx == "user_medals" else None
                    ))
            except Exception as exc:
                logger.error("Failed to fetch context", context=ctx, error=str(exc))
        return "\n\n".join(parts)

    async def _fetch_message_history(self) -> str:
        msgs = await TelegramMessage.find().sort("-date").limit(200).to_list()
        if not msgs:
            return "No messages in the last 24 hours."
        lines = [
            f"[{m.date.strftime('%d.%m %H:%M')}] @{m.username or '?'}: {m.text}"
            for m in reversed(msgs)
        ]
        logger.info("Fetched message history", lines_count=len(lines))
        return "Channel messages (last 24 h):\n" + "\n".join(lines)

    async def _fetch_step_reports(self, nickname: Optional[str]) -> str:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        if nickname:
            reports = (
                await StepReport.find(
                    StepReport.date >= since,
                    {"nickname": {"$regex": f"^{re.escape(nickname)}$", "$options": "i"}},
                )
                .sort("date")
                .to_list()
            )
            logger.info(f"Fetched steps for {nickname}", reports_count=len(reports))
            header = f"Step reports for #{nickname} (last 30 days):"
            empty_msg = f"No step data found for #{nickname} in the last 30 days."
        else:
            reports = (
                await StepReport.find(StepReport.date >= since)
                .sort("date")
                .to_list()
            )
            logger.info("Fetched steps for all users", reports_count=len(reports))
            header = "Step reports for all users (last 30 days):"
            empty_msg = "No step data in the last 30 days."

        if not reports:
            return empty_msg
        lines = [
            f"{r.date.strftime('%d.%m.%Y')}: #{r.nickname} — {r.steps:,} steps"
            for r in reports
        ]
        return header + "\n" + "\n".join(lines)

    async def _fetch_medal_records(self, nickname: Optional[str]) -> str:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        if nickname:
            records = (
                await MedalRecord.find(
                    MedalRecord.date >= since,
                    {"nickname": {"$regex": f"^{re.escape(nickname)}$", "$options": "i"}},
                )
                .sort("date")
                .to_list()
            )
            logger.info(f"Fetched medals for {nickname}", records_count=len(records))
            header = f"Medal records for #{nickname} (last 30 days):"
            empty_msg = f"No medals found for #{nickname} in the last 30 days."
        else:
            records = (
                await MedalRecord.find(MedalRecord.date >= since)
                .sort("date")
                .to_list()
            )
            logger.info("Fetched medals for all users", records_count=len(records))
            header = "Medal records for all users (last 30 days):"
            empty_msg = "No medals in the last 30 days."

        if not records:
            return empty_msg
        lines = [
            f"{r.date.strftime('%d.%m.%Y')}: #{r.nickname} — {r.medal.value}"
            for r in records
        ]
        return header + "\n" + "\n".join(lines)

    # ------------------------------------------------------------------
    # Step 2 — answer
    # ------------------------------------------------------------------

    async def _answer(self, question: str, context: str) -> str:
        now = datetime.now(timezone.utc)
        today = now.strftime("%d.%m.%Y")
        yesterday = (now - timedelta(days=1)).strftime("%d.%m.%Y")
        system = _ANSWER_SYSTEM.format(today=today, yesterday=yesterday)
        user_content = (
            f"{question}\n\n<data>\n{context}\n</data>" if context else question
        )
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.error("LLM answer step failed", error=str(exc))
            return "Произошла ошибка при обращении к ИИ."
