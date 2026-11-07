import pytest
from bot.utils.helpers import sanitize_pack_slug, extract_emojis, format_pack_link, generate_random_pack_name


def test_sanitize_pack_slug():
    bot_name = "vokistickbot"

    # Standard clean name
    assert sanitize_pack_slug("memes", bot_name) == "memes_by_vokistickbot"

    # Name with spaces and uppercase
    assert sanitize_pack_slug("My Cool Cats", bot_name) == "my_cool_cats_by_vokistickbot"

    # Name starting with number should get 's_' prefix
    res = sanitize_pack_slug("123cats", bot_name)
    assert res.startswith("s_")
    assert res.endswith("_by_vokistickbot")

    # Double underscores collapsed
    assert sanitize_pack_slug("cool____memes", bot_name) == "cool_memes_by_vokistickbot"

    # Very long name truncated within 64 chars
    long_name = "a" * 100
    res_long = sanitize_pack_slug(long_name, bot_name)
    assert len(res_long) <= 64
    assert res_long.endswith("_by_vokistickbot")


def test_generate_random_pack_name():
    name = generate_random_pack_name("vokistickbot")
    assert name.startswith("pack_")
    assert name.endswith("_by_vokistickbot")
    assert len(name) <= 64


def test_extract_emojis():
    # Caption with emoji
    assert extract_emojis("Hello world! 🔥") == ["🔥"]

    # Multiple emojis
    assert extract_emojis("🐱 and 🐶 are cute") == ["🐱", "🐶"]

    # No emojis -> default fallback
    assert extract_emojis("Just plain text", default="✨") == ["✨"]

    # None caption
    assert extract_emojis(None, default="⭐️") == ["⭐️"]


def test_format_pack_link():
    assert format_pack_link("animals_by_vokistickbot") == "https://t.me/addstickers/animals_by_vokistickbot"


def test_extract_pack_name_from_text():
    from bot.utils.helpers import extract_pack_name_from_text

    assert extract_pack_name_from_text("https://t.me/addstickers/animals") == "animals"
    assert extract_pack_name_from_text("t.me/addstickers/cats_and_dogs") == "cats_and_dogs"
    assert extract_pack_name_from_text("tg://addstickers?set=hot_memes") == "hot_memes"
    assert extract_pack_name_from_text("just_a_slug_123") == "just_a_slug_123"
    assert extract_pack_name_from_text("invalid link http://example.com/test") is None
    assert extract_pack_name_from_text(None) is None
