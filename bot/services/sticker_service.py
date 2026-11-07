import logging
from typing import Optional, Union
from aiogram import Bot
from aiogram.types import BufferedInputFile, InputSticker, StickerSet
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
import asyncio

logger = logging.getLogger(__name__)


class StickerService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def create_new_pack(
        self,
        user_id: int,
        name: str,
        title: str,
        sticker_data: Union[bytes, str],
        format_: str = "static",
        sticker_type: str = "regular",
        emojis: list[str] | None = None
    ) -> bool:
        """
        Creates a new sticker set in Telegram with the initial sticker.
        """
        if not emojis:
            emojis = ["✨"]

        if isinstance(sticker_data, bytes):
            ext = "webm" if format_ == "video" else "webp"
            sticker_file = BufferedInputFile(sticker_data, filename=f"sticker.{ext}")
        else:
            sticker_file = sticker_data

        input_sticker = InputSticker(
            sticker=sticker_file,
            format=format_,
            emoji_list=emojis
        )

        try:
            await self.bot.create_new_sticker_set(
                user_id=user_id,
                name=name,
                title=title,
                stickers=[input_sticker],
                sticker_type=sticker_type
            )
            logger.info("Successfully created sticker set '%s' for user %d", name, user_id)
            return True
        except TelegramRetryAfter as e:
            logger.warning("Telegram rate limit: retry after %d seconds", e.retry_after)
            await asyncio.sleep(e.retry_after)
            return await self.create_new_pack(user_id, name, title, sticker_data, format_, sticker_type, emojis)
        except TelegramBadRequest as e:
            logger.error("Failed to create sticker set '%s': %s", name, e.message)
            raise

    async def add_sticker(
        self,
        user_id: int,
        name: str,
        sticker_data: Union[bytes, str],
        format_: str = "static",
        emojis: list[str] | None = None
    ) -> bool:
        """
        Adds a single sticker to an existing sticker set.
        """
        if not emojis:
            emojis = ["✨"]

        if isinstance(sticker_data, bytes):
            ext = "webm" if format_ == "video" else "webp"
            sticker_file = BufferedInputFile(sticker_data, filename=f"sticker.{ext}")
        else:
            sticker_file = sticker_data

        input_sticker = InputSticker(
            sticker=sticker_file,
            format=format_,
            emoji_list=emojis
        )

        try:
            await self.bot.add_sticker_to_set(
                user_id=user_id,
                name=name,
                sticker=input_sticker
            )
            logger.info("Added sticker to set '%s' for user %d", name, user_id)
            return True
        except TelegramRetryAfter as e:
            logger.warning("Telegram rate limit: retry after %d seconds", e.retry_after)
            await asyncio.sleep(e.retry_after)
            return await self.add_sticker(user_id, name, sticker_data, format_, emojis)
        except TelegramBadRequest as e:
            logger.error("Failed to add sticker to set '%s': %s", name, e.message)
            raise

    async def delete_sticker(self, file_id: str) -> bool:
        try:
            await self.bot.delete_sticker_from_set(sticker=file_id)
            return True
        except TelegramBadRequest as e:
            logger.error("Failed to delete sticker %s: %s", file_id, e.message)
            return False

    async def set_pack_thumbnail(
        self,
        user_id: int,
        name: str,
        thumbnail_data: Union[bytes, str],
        format_: str = "static"
    ) -> bool:
        try:
            if isinstance(thumbnail_data, bytes):
                ext = "webm" if format_ == "video" else "webp"
                thumb_file = BufferedInputFile(thumbnail_data, filename=f"thumb.{ext}")
            else:
                thumb_file = thumbnail_data

            await self.bot.set_sticker_set_thumbnail(
                name=name,
                user_id=user_id,
                thumbnail=thumb_file,
                format=format_
            )
            return True
        except TelegramBadRequest as e:
            logger.error("Failed to set thumbnail for %s: %s", name, e.message)
            raise

    async def delete_pack(self, name: str) -> bool:
        try:
            await self.bot.delete_sticker_set(name=name)
            return True
        except TelegramBadRequest as e:
            logger.error("Failed to delete sticker set %s: %s", name, e.message)
            raise

    async def get_pack_info(self, name: str) -> Optional[StickerSet]:
        try:
            return await self.bot.get_sticker_set(name=name)
        except TelegramBadRequest as e:
            logger.warning("Could not fetch sticker set %s: %s", name, e.message)
            return None

    async def change_sticker_emoji(self, file_id: str, emojis: list[str]) -> bool:
        try:
            await self.bot.set_sticker_emoji_list(sticker=file_id, emoji_list=emojis)
            return True
        except TelegramBadRequest as e:
            logger.error("Failed to change emoji for sticker %s: %s", file_id, e.message)
            return False

    async def set_sticker_position(self, file_id: str, position: int = 0) -> bool:
        try:
            await self.bot.set_sticker_position_in_set(sticker=file_id, position=position)
            return True
        except TelegramBadRequest as e:
            logger.error("Failed to set position for sticker %s: %s", file_id, e.message)
            return False
