from datetime import datetime
from enum import Enum
from typing import Optional

from beanie import Document
from pymongo import ASCENDING, IndexModel


class TelegramMessage(Document):
    """All incoming Telegram messages, auto-expired after 24 hours."""

    message_id: int
    chat_id: int
    user_id: Optional[int] = None
    username: Optional[str] = None
    text: str
    date: datetime

    class Settings:
        name = "messages"
        indexes = [
            IndexModel(
                [("date", ASCENDING)],
                expireAfterSeconds=86400,  # 24 hours
            )
        ]


class TelegramUser(Document):
    """Persistent user profile storing the preferred report nickname."""

    user_id: int
    nickname: str

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("user_id", ASCENDING)], unique=True),
        ]


class StepReport(Document):
    """Parsed step report submitted via #отчет."""

    user_id: Optional[int] = None
    nickname: str
    date: datetime
    steps: int

    class Settings:
        name = "reports"
        indexes = [
            IndexModel([("nickname", ASCENDING), ("date", ASCENDING)]),
        ]


class MedalType(str, Enum):
    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"


MEDAL_SYMBOLS: dict[MedalType, str] = {
    MedalType.GOLD: "🥇",
    MedalType.SILVER: "🥈",
    MedalType.BRONZE: "🥉",
}


class MedalRecord(Document):
    """Medal awarded to a user for a specific day."""

    user_id: Optional[int] = None
    nickname: str
    date: datetime  # the calendar day the medal is for (MSK midnight, UTC-stored)
    medal: MedalType

    class Settings:
        name = "medals"
        indexes = [
            IndexModel(
                [("date", ASCENDING), ("nickname", ASCENDING)],
                unique=True,
            ),
        ]
