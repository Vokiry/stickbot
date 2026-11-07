import logging
from typing import Optional
import aiosqlite
from bot.database.models import User, StickerPack, StickerItem

logger = logging.getLogger(__name__)


class Repository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    # --- User operations ---

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: str = ""
    ) -> User:
        async with self.conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                # Update username / first_name if changed
                if row["username"] != username or row["first_name"] != first_name:
                    await self.conn.execute(
                        """
                        UPDATE users
                        SET username = ?, first_name = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE telegram_id = ?
                        """,
                        (username, first_name, telegram_id)
                    )
                    await self.conn.commit()
                return User(
                    telegram_id=row["telegram_id"],
                    username=username or row["username"],
                    first_name=first_name or row["first_name"],
                    active_pack_id=row["active_pack_id"],
                    settings_quick_mode=bool(row["settings_quick_mode"]),
                    settings_auto_outline=bool(row["settings_auto_outline"]),
                    settings_default_emoji=row["settings_default_emoji"],
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"])
                )

        # Create new user
        await self.conn.execute(
            """
            INSERT INTO users (telegram_id, username, first_name)
            VALUES (?, ?, ?)
            """,
            (telegram_id, username, first_name)
        )
        await self.conn.commit()
        return User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            active_pack_id=None,
            settings_quick_mode=True,
            settings_auto_outline=False,
            settings_default_emoji="✨"
        )

    async def get_user(self, telegram_id: int) -> Optional[User]:
        async with self.conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return User(
                telegram_id=row["telegram_id"],
                username=row["username"],
                first_name=row["first_name"],
                active_pack_id=row["active_pack_id"],
                settings_quick_mode=bool(row["settings_quick_mode"]),
                settings_auto_outline=bool(row["settings_auto_outline"]),
                settings_default_emoji=row["settings_default_emoji"],
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"])
            )

    async def set_active_pack(self, telegram_id: int, pack_id: Optional[int]) -> None:
        await self.conn.execute(
            "UPDATE users SET active_pack_id = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (pack_id, telegram_id)
        )
        await self.conn.commit()

    async def update_settings(
        self,
        telegram_id: int,
        quick_mode: Optional[bool] = None,
        auto_outline: Optional[bool] = None,
        default_emoji: Optional[str] = None
    ) -> None:
        updates = []
        params = []
        if quick_mode is not None:
            updates.append("settings_quick_mode = ?")
            params.append(1 if quick_mode else 0)
        if auto_outline is not None:
            updates.append("settings_auto_outline = ?")
            params.append(1 if auto_outline else 0)
        if default_emoji is not None:
            updates.append("settings_default_emoji = ?")
            params.append(default_emoji)

        if not updates:
            return

        updates.append("updated_at = CURRENT_TIMESTAMP")
        query = f"UPDATE users SET {', '.join(updates)} WHERE telegram_id = ?"
        params.append(telegram_id)
        await self.conn.execute(query, tuple(params))
        await self.conn.commit()

    # --- Sticker Pack operations ---

    async def create_pack(
        self,
        user_id: int,
        name: str,
        title: str,
        sticker_type: str = "regular",
        format_: str = "static",
        initial_stickers_count: int = 1
    ) -> StickerPack:
        async with self.conn.execute(
            """
            INSERT INTO sticker_packs (user_id, name, title, sticker_type, format, stickers_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, name, title, sticker_type, format_, initial_stickers_count)
        ) as cursor:
            pack_id = cursor.lastrowid

        # Automatically make this new pack active for the user
        await self.set_active_pack(user_id, pack_id)
        await self.conn.commit()

        return StickerPack(
            id=pack_id,
            user_id=user_id,
            name=name,
            title=title,
            sticker_type=sticker_type,
            format=format_,
            stickers_count=initial_stickers_count
        )

    async def get_pack(self, pack_id: int) -> Optional[StickerPack]:
        async with self.conn.execute(
            "SELECT * FROM sticker_packs WHERE id = ? AND is_deleted = 0", (pack_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return StickerPack(
                id=row["id"],
                user_id=row["user_id"],
                name=row["name"],
                title=row["title"],
                sticker_type=row["sticker_type"],
                format=row["format"],
                stickers_count=row["stickers_count"],
                is_deleted=bool(row["is_deleted"]),
                created_at=str(row["created_at"])
            )

    async def get_pack_by_name(self, name: str) -> Optional[StickerPack]:
        async with self.conn.execute(
            "SELECT * FROM sticker_packs WHERE name = ? AND is_deleted = 0", (name,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return StickerPack(
                id=row["id"],
                user_id=row["user_id"],
                name=row["name"],
                title=row["title"],
                sticker_type=row["sticker_type"],
                format=row["format"],
                stickers_count=row["stickers_count"],
                is_deleted=bool(row["is_deleted"]),
                created_at=str(row["created_at"])
            )

    async def get_user_packs(
        self,
        user_id: int,
        format_: Optional[str] = None
    ) -> list[StickerPack]:
        if format_:
            query = "SELECT * FROM sticker_packs WHERE user_id = ? AND format = ? AND is_deleted = 0 ORDER BY id DESC"
            params = (user_id, format_)
        else:
            query = "SELECT * FROM sticker_packs WHERE user_id = ? AND is_deleted = 0 ORDER BY id DESC"
            params = (user_id,)

        async with self.conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [
                StickerPack(
                    id=row["id"],
                    user_id=row["user_id"],
                    name=row["name"],
                    title=row["title"],
                    sticker_type=row["sticker_type"],
                    format=row["format"],
                    stickers_count=row["stickers_count"],
                    is_deleted=bool(row["is_deleted"]),
                    created_at=str(row["created_at"])
                )
                for row in rows
            ]

    async def update_pack_title(self, pack_id: int, new_title: str) -> None:
        await self.conn.execute(
            "UPDATE sticker_packs SET title = ? WHERE id = ?",
            (new_title, pack_id)
        )
        await self.conn.commit()

    async def delete_pack(self, pack_id: int) -> None:
        await self.conn.execute(
            "UPDATE sticker_packs SET is_deleted = 1 WHERE id = ?",
            (pack_id,)
        )
        # Clear active pack for any user pointing to it
        await self.conn.execute(
            "UPDATE users SET active_pack_id = NULL WHERE active_pack_id = ?",
            (pack_id,)
        )
        await self.conn.commit()

    async def increment_stickers_count(self, pack_id: int) -> int:
        async with self.conn.execute(
            "UPDATE sticker_packs SET stickers_count = stickers_count + 1 WHERE id = ? RETURNING stickers_count",
            (pack_id,)
        ) as cursor:
            row = await cursor.fetchone()
            await self.conn.commit()
            return row["stickers_count"] if row else 1

    async def decrement_stickers_count(self, pack_id: int) -> int:
        async with self.conn.execute(
            "UPDATE sticker_packs SET stickers_count = MAX(0, stickers_count - 1) WHERE id = ? RETURNING stickers_count",
            (pack_id,)
        ) as cursor:
            row = await cursor.fetchone()
            await self.conn.commit()
            return row["stickers_count"] if row else 0

    # --- Sticker operations ---

    async def add_sticker(
        self,
        pack_id: int,
        file_id: str,
        file_unique_id: str,
        emoji: str
    ) -> StickerItem:
        async with self.conn.execute(
            """
            INSERT INTO stickers (pack_id, file_id, file_unique_id, emoji)
            VALUES (?, ?, ?, ?)
            """,
            (pack_id, file_id, file_unique_id, emoji)
        ) as cursor:
            sticker_id = cursor.lastrowid

        await self.increment_stickers_count(pack_id)
        await self.conn.commit()

        return StickerItem(
            id=sticker_id,
            pack_id=pack_id,
            file_id=file_id,
            file_unique_id=file_unique_id,
            emoji=emoji
        )

    async def get_last_sticker(self, pack_id: int) -> Optional[StickerItem]:
        async with self.conn.execute(
            "SELECT * FROM stickers WHERE pack_id = ? ORDER BY id DESC LIMIT 1",
            (pack_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return StickerItem(
                id=row["id"],
                pack_id=row["pack_id"],
                file_id=row["file_id"],
                file_unique_id=row["file_unique_id"],
                emoji=row["emoji"],
                created_at=str(row["created_at"])
            )

    async def delete_sticker(self, sticker_id: int, pack_id: int) -> None:
        await self.conn.execute(
            "DELETE FROM stickers WHERE id = ?", (sticker_id,)
        )
        await self.decrement_stickers_count(pack_id)
        await self.conn.commit()
