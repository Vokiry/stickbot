import re
import secrets
from typing import Optional


def sanitize_pack_slug(raw_name: str, bot_username: str) -> str:
    """
    Transforms user input into a valid Telegram sticker set short name:
    - 1-64 characters total length
    - Starts with a letter
    - Contains only [a-z0-9_]
    - No consecutive underscores
    - Ends with `_by_<bot_username>`
    """
    bot_suffix = f"_by_{bot_username.lower()}"
    max_slug_len = 64 - len(bot_suffix)

    # Convert to lowercase and replace invalid chars with underscore
    slug = raw_name.lower().strip()
    slug = re.sub(r"[^a-z0-9_]", "_", slug)
    # Collapse consecutive underscores
    slug = re.sub(r"_+", "_", slug)
    # Strip leading/trailing underscores
    slug = slug.strip("_")

    # If starts with a digit or empty, prepend 's'
    if not slug or not slug[0].isalpha():
        slug = f"s_{slug}" if slug else f"s_{secrets.token_hex(4)}"

    # Truncate to max allowed length
    slug = slug[:max_slug_len].rstrip("_")

    return f"{slug}{bot_suffix}"


def generate_random_pack_name(bot_username: str, prefix: str = "pack") -> str:
    """Generates a random unique pack name."""
    rand_id = secrets.token_hex(4)
    return sanitize_pack_slug(f"{prefix}_{rand_id}", bot_username)


def extract_emojis(text: Optional[str], default: str = "✨") -> list[str]:
    """
    Extracts emoji characters from a string (e.g. caption).
    Falls back to [default] if no emojis found.
    """
    if not text:
        return [default]

    # Regex matching broad Unicode emoji ranges
    emoji_pattern = re.compile(
        r"["
        r"\U0001F1E0-\U0001F1FF"  # flags
        r"\U0001F300-\U0001F5FF"  # symbols & pictographs
        r"\U0001F600-\U0001F64F"  # emoticons
        r"\U0001F680-\U0001F6FF"  # transport & map
        r"\U0001F700-\U0001F77F"  # alchemical
        r"\U0001F780-\U0001F7FF"  # geometric shapes
        r"\U0001F800-\U0001F8FF"  # arrows
        r"\U0001F900-\U0001F9FF"  # supplemental symbols
        r"\U0001FA00-\U0001FA6F"  # chess symbols
        r"\U0001FA70-\U0001FAFF"  # symbols and pictographs extended-a
        r"\U00002702-\U000027B0"  # dingbats
        r"\U000024C2-\U0001F251"
        r"]+",
        flags=re.UNICODE
    )

    found = emoji_pattern.findall(text)
    if not found:
        return [default]

    # Flatten into list of individual emojis, capped at 10
    emojis = []
    for item in found:
        for char in item:
            if char.strip() and char not in emojis:
                emojis.append(char)
            if len(emojis) >= 10:
                break

    return emojis if emojis else [default]


def format_pack_link(pack_name: str) -> str:
    return f"https://t.me/addstickers/{pack_name}"
