import logging
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser
from bot.database.db import Database
from bot.database.repository import Repository

logger = logging.getLogger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    def __init__(self, db: Database):
        self.db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        conn = await self.db.get_connection()
        repo = Repository(conn)
        data["repo"] = repo

        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user:
            user = await repo.get_or_create_user(
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name
            )
            data["user"] = user

        try:
            return await handler(event, data)
        finally:
            await conn.close()
