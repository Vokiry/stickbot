from dataclasses import dataclass
from datetime import datetime


@dataclass
class User:
    telegram_id: int
    username: str | None = None
    first_name: str = ""
    active_pack_id: int | None = None
    settings_quick_mode: bool = True
    settings_auto_outline: bool = False
    settings_default_emoji: str = "✨"
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class StickerPack:
    id: int
    user_id: int
    name: str
    title: str
    sticker_type: str = "regular"  # 'regular' | 'custom_emoji'
    format: str = "static"         # 'static' | 'video'
    stickers_count: int = 0
    is_deleted: bool = False
    created_at: str | None = None


@dataclass
class StickerItem:
    id: int
    pack_id: int
    file_id: str
    file_unique_id: str
    emoji: str
    created_at: str | None = None
