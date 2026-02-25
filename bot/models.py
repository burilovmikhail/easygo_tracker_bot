from datetime import datetime
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
