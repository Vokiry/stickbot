import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message


class ThrottlingMiddleware(BaseMiddleware):
    """
    Limits the rate of heavy media processing requests per user
    to prevent CPU exhaustion and ensure co-hosted services remain responsive.
    """
    def __init__(self, rate_limit_seconds: float = 1.2):
        self.rate_limit = rate_limit_seconds
        self.user_last_action: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            is_heavy_media = bool(event.photo or event.video or event.document or event.animation or event.sticker)
            if is_heavy_media:
                now = time.time()
                user_id = event.from_user.id
                last_time = self.user_last_action.get(user_id, 0.0)

                if now - last_time < self.rate_limit:
                    await event.answer("⏳ Пожалуйста, подождите секунду перед отправкой следующего медиафайла.")
                    return None

                self.user_last_action[user_id] = now

                # Evict old entries periodically
                if len(self.user_last_action) > 1000:
                    cutoff = now - 60
                    self.user_last_action = {u: t for u, t in self.user_last_action.items() if t > cutoff}

        return await handler(event, data)
