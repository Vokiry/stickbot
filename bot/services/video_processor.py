import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MAX_VIDEO_SIZE = 256 * 1024  # 256 KB limit in Telegram


async def convert_video_to_webm(
    input_path: Path,
    output_path: Path,
    is_custom_emoji: bool = False,
    crf: int = 32,
    bitrate: str = "220k"
) -> bool:
    """
    Encodes video/GIF to compliant WebM VP9 sticker video.
    """
    if is_custom_emoji:
        scale_filter = "fps=30,scale=100:100:flags=lanczos"
    else:
        # One side exactly 512, other side <= 512 and even
        scale_filter = "fps=30,scale='if(gte(iw,ih),512,-2)':'if(gte(iw,ih),-2,512)':flags=lanczos"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-t", "00:00:03",
        "-vf", scale_filter,
        "-c:v", "libvpx-vp9",
        "-crf", str(crf),
        "-b:v", bitrate,
        "-maxrate", "250k",
        "-bufsize", "500k",
        "-an",
        "-f", "webm",
        str(output_path)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error("FFmpeg error (code %d): %s", proc.returncode, stderr.decode("utf-8", errors="ignore"))
        return False

    return True


async def process_video(
    input_bytes: bytes,
    temp_dir: Path,
    is_custom_emoji: bool = False
) -> bytes:
    """
    Converts incoming video or GIF bytes into Telegram-compliant WebM VP9 bytes <= 256KB.
    """
    temp_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(dir=temp_dir, suffix="_in.tmp", delete=False) as in_file:
        in_file.write(input_bytes)
        in_path = Path(in_file.name)

    out_path = temp_dir / f"{in_path.stem}_out.webm"

    try:
        # First pass with standard quality
        success = await convert_video_to_webm(
            in_path,
            out_path,
            is_custom_emoji=is_custom_emoji,
            crf=32,
            bitrate="220k"
        )
        if not success or not out_path.exists():
            raise RuntimeError("Failed to encode video sticker with FFmpeg")

        file_size = out_path.stat().st_size
        logger.debug("First pass video size: %d bytes (limit: %d)", file_size, MAX_VIDEO_SIZE)

        # Fallback second pass if size exceeds 256 KB
        if file_size > MAX_VIDEO_SIZE:
            logger.warning("Video size %d exceeds 256KB, running compression fallback", file_size)
            success = await convert_video_to_webm(
                in_path,
                out_path,
                is_custom_emoji=is_custom_emoji,
                crf=40,
                bitrate="150k"
            )
            if not success:
                raise RuntimeError("Failed to compress video sticker on second pass")

            file_size = out_path.stat().st_size
            logger.info("Second pass video size: %d bytes", file_size)

        with open(out_path, "rb") as f:
            result = f.read()

        return result

    finally:
        # Cleanup temp files
        if in_path.exists():
            try:
                os.remove(in_path)
            except OSError:
                pass
        if out_path.exists():
            try:
                os.remove(out_path)
            except OSError:
                pass
