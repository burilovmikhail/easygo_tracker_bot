from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram Bot Configuration
    telegram_api_key: str

    # Allowlist of Telegram chat IDs the bot will respond to.
    # Channel IDs look like -1001234567890.
    # Set to an empty list to disable the restriction (not recommended).
    allowed_chat_ids: List[int] = []

    @field_validator("allowed_chat_ids", mode="before")
    @classmethod
    def _parse_chat_ids(cls, v):
        """Accept both a JSON list and a comma-separated string from .env."""
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    # MongoDB Configuration
    mongodb_uri: str

    # Google Sheets Configuration
    google_sheet_id: str
    google_credentials_path: str = "credentials.json"
    report_channel_id: Optional[int] = None

    # OpenAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"

    # Disk space monitoring (alerts go to REPORT_CHANNEL_ID)
    disk_check_path: str = "."
    disk_free_threshold_mb: int = 100
    disk_check_interval_minutes: int = 5
    disk_alert_repeat_minutes: int = 60

    # Logging
    log_level: str = "INFO"

    # MongoDB Authentication (for docker-compose)
    mongo_initdb_root_username: str = "easygo_user"
    mongo_initdb_root_password: str = "easygo_pass"
    mongo_initdb_database: str = "easygo_bot"


# Global settings instance
settings = Settings()
