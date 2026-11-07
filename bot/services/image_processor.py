import io
import logging
from typing import Optional, Tuple
from PIL import Image, ImageOps, ImageFilter, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Prevent decompression bomb DoS attacks (max 25 megapixels)
Image.MAX_IMAGE_PIXELS = 25_000_000


def calculate_sticker_dimensions(width: int, height: int, max_dim: int = 512) -> Tuple[int, int]:
    """
    Telegram requirements:
    One side must be exactly 512px, the other side <= 512px.
    """
    if width <= 0 or height <= 0:
        return max_dim, max_dim

    if width >= height:
        new_width = max_dim
        new_height = max(1, round(height * (max_dim / width)))
    else:
        new_height = max_dim
        new_width = max(1, round(width * (max_dim / height)))

    return new_width, new_height


def resize_to_sticker(image: Image.Image, max_dim: int = 512) -> Image.Image:
    """Resize image preserving aspect ratio with one side exactly max_dim."""
    target_width, target_height = calculate_sticker_dimensions(image.width, image.height, max_dim)
    return image.resize((target_width, target_height), Image.Resampling.LANCZOS)


def resize_to_custom_emoji(image: Image.Image, size: int = 100) -> Image.Image:
    """
    Telegram custom emoji requirements: exactly 100x100 pixels.
    Fits image centered into 100x100 transparent canvas.
    """
    img = image.copy()
    img.thumbnail((size, size), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset_x = (size - img.width) // 2
    offset_y = (size - img.height) // 2
    canvas.paste(img, (offset_x, offset_y))
    return canvas


def add_white_outline(
    image: Image.Image,
    stroke_width: int = 10,
    shadow: bool = True
) -> Image.Image:
    """
    Adds a clean white contour outline and subtle drop shadow around transparent artwork.
    """
    img = image.convert("RGBA")
    alpha = img.split()[-1]

    # If image has no transparency (alpha all 255), outline is not applicable
    min_alpha, max_alpha = alpha.getextrema()
    if min_alpha == 255:
        # Full rectangular image without transparency
        return img

    # Expand the alpha channel using morphological dilation (MaxFilter)
    filter_size = max(3, stroke_width * 2 + 1)
    dilated_alpha = alpha.filter(ImageFilter.MaxFilter(filter_size))

    # White border layer
    border_img = Image.new("RGBA", img.size, (255, 255, 255, 255))
    border_img.putalpha(dilated_alpha)

    if shadow:
        # Drop shadow from dilated border
        shadow_alpha = dilated_alpha.filter(ImageFilter.GaussianBlur(radius=5))
        shadow_img = Image.new("RGBA", img.size, (0, 0, 0, 110))
        shadow_img.putalpha(shadow_alpha)

        # Composite: shadow -> border -> original artwork
        result = Image.alpha_composite(shadow_img, border_img)
        result = Image.alpha_composite(result, img)
    else:
        result = Image.alpha_composite(border_img, img)

    return result


def get_font(size: int) -> ImageFont.ImageFont:
    candidate_paths = [
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/JetBrainsMonoNerdFontPropo-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidate_paths:
        try:
            return ImageFont.truetype(path, size=size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def render_caption_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    position_y: int,
    image_width: int,
    font_size: int = 36
) -> None:
    font = get_font(font_size)
    stroke_w = max(2, font_size // 14)

    # Calculate text width
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    pos_x = (image_width - text_w) // 2

    # Draw with black outline and white fill
    draw.text(
        (pos_x, position_y),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        stroke_width=stroke_w,
        stroke_fill=(0, 0, 0, 255)
    )


def add_text_captions(
    image: Image.Image,
    top_text: str = "",
    bottom_text: str = ""
) -> Image.Image:
    if not top_text and not bottom_text:
        return image

    img = image.convert("RGBA").copy()
    draw = ImageDraw.Draw(img)

    base_font_size = max(24, int(img.width * 0.08))

    if top_text:
        render_caption_text(draw, top_text.strip(), 12, img.width, base_font_size)

    if bottom_text:
        font = get_font(base_font_size)
        bbox = draw.textbbox((0, 0), bottom_text, font=font)
        text_h = bbox[3] - bbox[1]
        pos_y = max(0, img.height - text_h - 18)
        render_caption_text(draw, bottom_text.strip(), pos_y, img.width, base_font_size)

    return img


def process_image(
    input_bytes: bytes,
    add_outline: bool = False,
    is_custom_emoji: bool = False,
    top_text: str = "",
    bottom_text: str = ""
) -> bytes:
    """
    Full pipeline to turn raw image bytes into compliant Telegram sticker WebP bytes.
    """
    with Image.open(io.BytesIO(input_bytes)) as raw_image:
        # Respect EXIF rotation tags from phone cameras
        image = ImageOps.exif_transpose(raw_image)
        image = image.convert("RGBA")

        # Autocrop transparent borders so the actual subject takes maximum possible space
        bbox = image.getbbox()
        if bbox:
            image = image.crop(bbox)

        # 1. Resize to Telegram standards FIRST (prevents CPU/RAM exhaustion on large images)
        if is_custom_emoji:
            image = resize_to_custom_emoji(image, size=100)
        else:
            image = resize_to_sticker(image, max_dim=512)

        # 2. Add outline on the pre-scaled canvas (runs in ~2ms instead of seconds)
        if add_outline:
            image = add_white_outline(image)

        # 3. Add text captions if requested
        if top_text or bottom_text:
            image = add_text_captions(image, top_text, bottom_text)

        # 4. Save to WEBP with size guarantee <= 512 KB
        quality = 95
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=quality, method=6)
        result = output.getvalue()

        # If somehow > 512KB, reduce quality iteratively
        while len(result) > 512 * 1024 and quality > 30:
            quality -= 15
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=quality, method=6)
            result = output.getvalue()

        logger.debug(
            "Processed image: %dx%d, final size: %d bytes (quality: %d)",
            image.width, image.height, len(result), quality
        )
        return result
