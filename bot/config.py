from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    BOT_TOKEN: str = Field(..., description="Telegram bot API token")
    BOT_USERNAME: str | None = Field(default=None, description="Bot username without @")
    TELEGRAM_API_SERVER: str | None = Field(default=None, description="Custom Telegram API server / Cloudflare Worker")
    PROXY_URL: str | None = Field(default=None, description="SOCKS5 or HTTP proxy URL")
    DB_PATH: Path = Field(default=Path("data/bot.db"), description="Path to SQLite database")
    TEMP_DIR: Path = Field(default=Path("/tmp/stickbot"), description="Directory for media processing")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")


settings = Settings()
