import io
import pytest
from PIL import Image, ImageDraw
from bot.services.image_processor import (
    calculate_sticker_dimensions,
    resize_to_sticker,
    resize_to_custom_emoji,
    add_white_outline,
    process_image
)


def test_calculate_sticker_dimensions():
    # Landscape
    w, h = calculate_sticker_dimensions(1920, 1080)
    assert w == 512
    assert h == round(1080 * (512 / 1920))
    assert h <= 512

    # Portrait
    w, h = calculate_sticker_dimensions(1080, 1920)
    assert h == 512
    assert w == round(1080 * (512 / 1920))
    assert w <= 512

    # Square
    w, h = calculate_sticker_dimensions(800, 800)
    assert w == 512
    assert h == 512


def test_resize_to_sticker():
    im = Image.new("RGBA", (1200, 600), (255, 0, 0, 255))
    resized = resize_to_sticker(im)
    assert resized.width == 512
    assert resized.height == 256


def test_resize_to_custom_emoji():
    im = Image.new("RGBA", (300, 150), (0, 255, 0, 255))
    emoji = resize_to_custom_emoji(im)
    assert emoji.width == 100
    assert emoji.height == 100


def test_add_white_outline():
    # Create image with transparent background and red circle in center
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.ellipse((50, 50, 150, 150), fill=(255, 0, 0, 255))

    with_border = add_white_outline(im, stroke_width=6, shadow=True)
    assert with_border.size == im.size

    # Check that a pixel slightly outside the circle now has non-zero alpha (border/shadow)
    border_pixel = with_border.getpixel((46, 100))
    assert border_pixel[3] > 0


def test_process_image_full_pipeline():
    # Create test JPEG bytes
    im = Image.new("RGB", (800, 600), color=(100, 150, 200))
    buf = io.BytesIO()
    im.save(buf, format="JPEG")
    jpeg_bytes = buf.getvalue()

    # Process to sticker
    webp_bytes = process_image(jpeg_bytes, add_outline=False)
    assert len(webp_bytes) < 512 * 1024

    with Image.open(io.BytesIO(webp_bytes)) as out_im:
        assert out_im.format == "WEBP"
        assert max(out_im.width, out_im.height) == 512
        assert out_im.width == 512
        assert out_im.height == round(600 * (512 / 800))
