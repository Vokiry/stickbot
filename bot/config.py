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
    ADMIN_IDS: str = Field(default="1045810381", description="Comma-separated Telegram user IDs of admins")
    TELEGRAM_API_SERVER: str | None = Field(default=None, description="Custom Telegram API server / Cloudflare Worker")
    PROXY_URL: str | None = Field(default=None, description="SOCKS5 or HTTP proxy URL")
    DB_PATH: Path = Field(default=Path("data/bot.db"), description="Path to SQLite database")
    TEMP_DIR: Path = Field(default=Path("/tmp/stickbot"), description="Directory for media processing")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")



    @property
    def admin_ids(self) -> set[int]:
        ids = set()
        for x in self.ADMIN_IDS.split(","):
            x = x.strip()
            if x.isdigit():
                ids.add(int(x))
        return ids

settings = Settings()
