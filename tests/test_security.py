import pytest
from unittest.mock import AsyncMock, patch
from PIL import Image
from aiogram.types import Message, User as TgUser, Chat, PhotoSize
from datetime import datetime

from bot.middlewares.throttling_middleware import ThrottlingMiddleware
from bot.services.image_processor import process_image


def test_max_image_pixels_configured():
    # Verify Pillow decompression bomb protection is active
    assert Image.MAX_IMAGE_PIXELS <= 25_000_000


def test_image_processing_order_and_safety():
    # Create large image
    im = Image.new("RGBA", (1920, 1080), (255, 0, 0, 200))
    import io
    buf = io.BytesIO()
    im.save(buf, format="PNG")

    # Should safely process without memory spike and result in exactly 512px
    result_bytes = process_image(buf.getvalue(), add_outline=True)
    assert len(result_bytes) < 512 * 1024

    with Image.open(io.BytesIO(result_bytes)) as out_im:
        assert max(out_im.width, out_im.height) == 512


@pytest.mark.asyncio
async def test_throttling_middleware():
    middleware = ThrottlingMiddleware(rate_limit_seconds=1.0)

    call_count = 0
    async def dummy_handler(event, data):
        nonlocal call_count
        call_count += 1
        return "ok"

    user = TgUser(id=999, is_bot=False, first_name="Tester")
    chat = Chat(id=999, type="private")
    sample_photo = [PhotoSize(file_id="fid1", file_unique_id="uid1", width=100, height=100)]

    # First media message
    msg1 = Message(
        message_id=1,
        date=datetime.now(),
        chat=chat,
        from_user=user,
        photo=sample_photo
    )

    # 1st call should succeed
    res1 = await middleware(dummy_handler, msg1, {})
    assert res1 == "ok"
    assert call_count == 1

    # Immediate 2nd call should be throttled
    msg2 = Message(
        message_id=2,
        date=datetime.now(),
        chat=chat,
        from_user=user,
        photo=sample_photo
    )

    with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
        res2 = await middleware(dummy_handler, msg2, {})
        assert res2 is None
        assert call_count == 1  # Handler was NOT called
        mock_answer.assert_awaited_once()
