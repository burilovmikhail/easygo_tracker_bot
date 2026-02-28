import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from openai import AsyncOpenAI

from bot.models import StepReport, TelegramMessage, TelegramUser

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

Analyse the user's question and return JSON with exactly two fields:
  "context":  one of "none", "message_history", "user_steps", "all_steps"
  "nickname": null, or the nickname mentioned in the question (lowercase, without #)

Rules:
- Set "nickname" only when "context" is "user_steps" AND the question names a specific person.
- If the user asks about themselves without naming anyone, set "nickname" to null.
- Prefer "user_steps" over "all_steps" when the question is clearly about one person.\
"""

_ANSWER_SYSTEM = """\
You are a helpful assistant for a step-tracking fitness challenge in a Telegram channel.
Today is {today}. Answer in the same language as the question (usually Russian).
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
    ) -> str:
        """Two-step flow: classify required context, then answer with it."""
        decision = await self._classify_context(question)
        context_type = decision.get("context", "none")
        nickname: Optional[str] = decision.get("nickname") or None

        # When the user asks about their own steps but no name was extracted,
        # resolve nickname from their stored Telegram profile.
        if context_type == "user_steps" and nickname is None and asking_user_id is not None:
            user = await TelegramUser.find_one(TelegramUser.user_id == asking_user_id)
            if user:
                nickname = user.nickname

        context_text = await self._fetch_context(context_type, nickname)
        return await self._answer(question, context_text)

    # ------------------------------------------------------------------
    # Step 1 — classify
    # ------------------------------------------------------------------

    async def _classify_context(self, question: str) -> dict:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _CLASSIFIER_SYSTEM},
                    {"role": "user", "content": question},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as exc:
            logger.error("Context classification failed", error=str(exc))
            return {"context": "none", "nickname": None}

    # ------------------------------------------------------------------
    # Step 1.5 — fetch context data from MongoDB
    # ------------------------------------------------------------------

    async def _fetch_context(self, context_type: str, nickname: Optional[str]) -> str:
        try:
            if context_type == "message_history":
                return await self._fetch_message_history()
            if context_type in ("user_steps", "all_steps"):
                return await self._fetch_step_reports(nickname)
        except Exception as exc:
            logger.error("Failed to fetch context", context=context_type, error=str(exc))
        return ""

    async def _fetch_message_history(self) -> str:
        msgs = await TelegramMessage.find().sort("-date").limit(200).to_list()
        if not msgs:
            return "No messages in the last 24 hours."
        lines = [
            f"[{m.date.strftime('%d.%m %H:%M')}] @{m.username or '?'}: {m.text}"
            for m in reversed(msgs)
        ]
        return "Channel messages (last 24 h):\n" + "\n".join(lines)

    async def _fetch_step_reports(self, nickname: Optional[str]) -> str:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        if nickname:
            reports = (
                await StepReport.find(
                    StepReport.date >= since,
                    StepReport.nickname == nickname,
                )
                .sort("date")
                .to_list()
            )
            header = f"Step reports for #{nickname} (last 30 days):"
            empty_msg = f"No step data found for #{nickname} in the last 30 days."
        else:
            reports = (
                await StepReport.find(StepReport.date >= since)
                .sort("date")
                .to_list()
            )
            header = "Step reports for all users (last 30 days):"
            empty_msg = "No step data in the last 30 days."

        if not reports:
            return empty_msg

        lines = [
            f"{r.date.strftime('%d.%m.%Y')}: #{r.nickname} — {r.steps:,} steps"
            for r in reports
        ]
        return header + "\n" + "\n".join(lines)

    # ------------------------------------------------------------------
    # Step 2 — answer
    # ------------------------------------------------------------------

    async def _answer(self, question: str, context: str) -> str:
        today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
        system = _ANSWER_SYSTEM.format(today=today)
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
