import tempfile
from pathlib import Path
import pytest
from bot.database.db import Database
from bot.database.repository import Repository


@pytest.mark.asyncio
async def test_repository_user_and_packs():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        db = Database(db_path)
        await db.init()

        conn = await db.get_connection()
        repo = Repository(conn)

        # 1. User creation
        user = await repo.get_or_create_user(telegram_id=12345, username="testuser", first_name="Tester")
        assert user.telegram_id == 12345
        assert user.username == "testuser"
        assert user.settings_quick_mode is True

        # 2. Update settings
        await repo.update_settings(12345, quick_mode=False, auto_outline=True, default_emoji="🔥")
        updated_user = await repo.get_user(12345)
        assert updated_user.settings_quick_mode is False
        assert updated_user.settings_auto_outline is True
        assert updated_user.settings_default_emoji == "🔥"

        # 3. Create Sticker Pack
        pack = await repo.create_pack(
            user_id=12345,
            name="cool_cats_by_vokistickbot",
            title="Cool Cats",
            sticker_type="regular",
            format_="static",
            initial_stickers_count=1
        )
        assert pack.id is not None
        assert pack.name == "cool_cats_by_vokistickbot"

        # Check active pack auto-set
        user_after_pack = await repo.get_user(12345)
        assert user_after_pack.active_pack_id == pack.id

        # 4. Add Sticker
        sticker = await repo.add_sticker(
            pack_id=pack.id,
            file_id="tg_file_id_123",
            file_unique_id="unique_123",
            emoji="🔥"
        )
        assert sticker.id is not None

        pack_after_add = await repo.get_pack(pack.id)
        assert pack_after_add.stickers_count == 2

        # 5. Get last sticker and delete
        last_sticker = await repo.get_last_sticker(pack.id)
        assert last_sticker.file_id == "tg_file_id_123"

        await repo.delete_sticker(last_sticker.id, pack.id)
        pack_after_del = await repo.get_pack(pack.id)
        assert pack_after_del.stickers_count == 1

        # 6. Delete pack
        await repo.delete_pack(pack.id)
        assert await repo.get_pack(pack.id) is None

        await conn.close()
