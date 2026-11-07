import io
import logging
import uuid
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from bot.config import settings
from bot.database.models import User, StickerPack
from bot.database.repository import Repository
from bot.services.sticker_service import StickerService
from bot.services.image_processor import process_image, add_text_captions
from bot.services.video_processor import process_video
from bot.utils.helpers import extract_emojis, format_pack_link
from bot.utils.keyboards import get_sticker_added_keyboard, get_interactive_preview_keyboard

import time

logger = logging.getLogger(__name__)

router = Router(name="sticker_upload")

# In-memory storage for interactive previews with automatic TTL cleanup
PREVIEW_CACHE: dict[str, dict] = {}
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB


def cleanup_preview_cache():
    now = time.time()
    expired = [k for k, v in PREVIEW_CACHE.items() if now - v.get("created_at", now) > 300]
    for k in expired:
        PREVIEW_CACHE.pop(k, None)
    while len(PREVIEW_CACHE) > 50:
        oldest = next(iter(PREVIEW_CACHE))
        PREVIEW_CACHE.pop(oldest, None)


async def get_or_resolve_active_pack(
    message: Message,
    repo: Repository,
    user: User,
    media_format: str
) -> Optional[StickerPack]:
    """
    Finds current active pack or automatically selects matching pack for the media format.
    """
    if user.active_pack_id:
        active_pack = await repo.get_pack(user.active_pack_id)
        if active_pack:
            return active_pack

    # If no active pack set, try finding a pack of the required format
    user_packs = await repo.get_user_packs(user.telegram_id, format_=media_format)
    if user_packs:
        # Auto-activate the latest pack of this format
        pack = user_packs[0]
        await repo.set_active_pack(user.telegram_id, pack.id)
        return pack

    # Check if user has ANY packs
    all_packs = await repo.get_user_packs(user.telegram_id)
    if not all_packs:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Создать стикерпак", callback_data="create_new_pack")]
        ])
        await message.answer(
            "⚠️ **У вас пока нет активного стикерпака!**\n\n"
            "Чтобы сохранять стикеры, сначала создайте свой набор.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return None

    # User has packs, but none match the media format
    target_type = "видеопаков" if media_format == "video" else "статических паков"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Создать нужный пак", callback_data="create_new_pack")],
        [InlineKeyboardButton(text="📂 Выбрать из существующих", callback_data="back_to_packs")]
    ])
    await message.answer(
        f"⚠️ У вас нет активного набора для этого формата (нет подходящих {target_type}).\n\n"
        f"Создайте новый пак или выберите другой в меню:",
        reply_markup=keyboard
    )
    return None


@router.message(F.photo)
@router.message(F.document)
@router.message(F.video)
@router.message(F.animation)
@router.message(F.sticker)
async def handle_media_upload(
    message: Message,
    bot: Bot,
    repo: Repository,
    user: User
):
    # 1. Determine media format and file_id
    is_video = False
    is_sticker = False
    sticker_emoji = None
    file_id = None

    if message.sticker:
        is_sticker = True
        sticker_emoji = message.sticker.emoji
        is_video = message.sticker.is_video
        file_id = message.sticker.file_id
    elif message.video or message.animation:
        is_video = True
        file_id = message.video.file_id if message.video else message.animation.file_id
    elif message.document:
        mime = (message.document.mime_type or "").lower()
        name = (message.document.file_name or "").lower()
        if mime.startswith("video/") or name.endswith((".mp4", ".webm", ".gif", ".mov")):
            is_video = True
            file_id = message.document.file_id
        elif mime.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp")):
            is_video = False
            file_id = message.document.file_id
        else:
            await message.answer("⚠️ Неподдерживаемый тип файла. Отправьте картинку (PNG/JPG/WEBP) или видео (MP4/GIF).")
            return
    elif message.photo:
        is_video = False
        file_id = message.photo[-1].file_id

    media_format = "video" if is_video else "static"

    # 2. Resolve active pack
    pack = await get_or_resolve_active_pack(message, repo, user, media_format)
    if not pack:
        return

    # Check format match
    if pack.format != media_format:
        expected = "видео/GIF" if pack.format == "video" else "картинок"
        received = "видео" if media_format == "video" else "картинку"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📂 Сменить активный пак", callback_data="back_to_packs")],
            [InlineKeyboardButton(text="🎨 Создать новый пак", callback_data="create_new_pack")]
        ])
        await message.answer(
            f"⚠️ **Несоответствие форматов:**\n"
            f"Активный пак «**{pack.title}**» предназначен для **{expected}**, а вы прислали **{received}**.\n\n"
            f"Переключите активный пак или создайте новый:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    # Check sticker limit (120 for regular, 200 for emoji)
    limit = 200 if pack.sticker_type == "custom_emoji" else 120
    if pack.stickers_count >= limit:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Создать Часть 2", callback_data="create_new_pack")]
        ])
        await message.answer(
            f"⚠️ Стикерпак «**{pack.title}**» полностью заполнен ({pack.stickers_count}/{limit} стикеров)!\n"
            f"Создайте следующий пак для продолжения коллекции.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    # 3. Extract emoji
    if sticker_emoji:
        emojis = [sticker_emoji]
    else:
        emojis = extract_emojis(message.caption, default=user.settings_default_emoji)

    is_custom_emoji = (pack.sticker_type == "custom_emoji")

    # If Quick Mode is ON or it's a direct sticker forward: process and add immediately
    if user.settings_quick_mode or is_sticker or is_video:
        status_msg = await message.answer("⏳ Обрабатываю и добавляю в стикерпак...")

        try:
            # Download file with size validation
            file_info = await bot.get_file(file_id)
            if file_info.file_size and file_info.file_size > MAX_FILE_SIZE:
                await status_msg.edit_text("⚠️ Файл слишком большой (максимум 25 МБ). Пожалуйста, отправьте файл меньшего размера.")
                return
            buf = io.BytesIO()
            await bot.download_file(file_info.file_path, buf)
            raw_bytes = buf.getvalue()

            if is_video:
                processed_bytes = await process_video(
                    raw_bytes,
                    temp_dir=settings.TEMP_DIR,
                    is_custom_emoji=is_custom_emoji
                )
            else:
                processed_bytes = process_image(
                    raw_bytes,
                    add_outline=user.settings_auto_outline,
                    is_custom_emoji=is_custom_emoji
                )

            # Add to set in Telegram
            sticker_service = StickerService(bot)
            await sticker_service.add_sticker(
                user_id=message.from_user.id,
                name=pack.name,
                sticker_data=processed_bytes,
                format_=pack.format,
                emojis=emojis
            )

            # Get updated set info to retrieve newly added sticker file_id
            set_info = await sticker_service.get_pack_info(pack.name)
            last_file_id = set_info.stickers[-1].file_id if set_info and set_info.stickers else file_id
            last_unique_id = set_info.stickers[-1].file_unique_id if set_info and set_info.stickers else str(uuid.uuid4())

            # Update DB
            await repo.add_sticker(
                pack_id=pack.id,
                file_id=last_file_id,
                file_unique_id=last_unique_id,
                emoji=emojis[0]
            )

            pack_link = format_pack_link(pack.name)
            await status_msg.delete()
            source_set = message.sticker.set_name if message.sticker else None
            await message.answer(
                f"✅ **Стикер успешно добавлен!**\n\n"
                f"📦 Пак: **{pack.title}** ({pack.stickers_count + 1}/{limit})\n"
                f"🎯 Эмодзи: {' '.join(emojis)}\n"
                f"🔗 {pack_link}",
                reply_markup=get_sticker_added_keyboard(pack, last_file_id, source_set_name=source_set),
                parse_mode="Markdown"
            )

        except TelegramBadRequest as e:
            logger.error("Telegram error adding sticker: %s", e.message)
            await status_msg.edit_text(f"❌ Ошибка Telegram: `{e.message}`", parse_mode="Markdown")
        except Exception as e:
            logger.exception("Error adding sticker: %s", e)
            await status_msg.edit_text(f"❌ Не удалось добавить стикер: {e}")

    else:
        # Interactive Mode: generate preview and show options
        file_info = await bot.get_file(file_id)
        if file_info.file_size and file_info.file_size > MAX_FILE_SIZE:
            await message.answer("⚠️ Файл слишком большой (максимум 25 МБ). Пожалуйста, отправьте файл меньшего размера.")
            return

        buf = io.BytesIO()
        await bot.download_file(file_info.file_path, buf)
        raw_bytes = buf.getvalue()

        cleanup_preview_cache()
        temp_id = str(uuid.uuid4())[:8]
        PREVIEW_CACHE[temp_id] = {
            "raw_bytes": raw_bytes,
            "pack_id": pack.id,
            "format": pack.format,
            "is_custom_emoji": is_custom_emoji,
            "outline": user.settings_auto_outline,
            "emoji": emojis[0],
            "top_text": "",
            "bottom_text": "",
            "created_at": time.time()
        }

        # Render preview image
        preview_bytes = process_image(
            raw_bytes,
            add_outline=user.settings_auto_outline,
            is_custom_emoji=is_custom_emoji
        )

        from aiogram.types import BufferedInputFile
        photo_file = BufferedInputFile(preview_bytes, filename="preview.webp")

        await message.answer_photo(
            photo_file,
            caption=(
                f"🎨 **Предпросмотр стикера**\n\n"
                f"Пак: **{pack.title}**\n"
                f"Эмодзи: {emojis[0]}\n\n"
                f"Настройте параметры или подтвердите добавление:"
            ),
            reply_markup=get_interactive_preview_keyboard(
                pack.id,
                temp_id,
                user.settings_auto_outline,
                emojis[0]
            ),
            parse_mode="Markdown"
        )


@router.callback_query(F.data.startswith("preview_toggle_outline:"))
async def callback_preview_toggle_outline(callback: CallbackQuery):
    temp_id = callback.data.split(":")[1]
    item = PREVIEW_CACHE.get(temp_id)
    if not item:
        await callback.answer("Сессия предпросмотра устарела.", show_alert=True)
        return

    item["outline"] = not item["outline"]

    preview_bytes = process_image(
        item["raw_bytes"],
        add_outline=item["outline"],
        is_custom_emoji=item["is_custom_emoji"],
        top_text=item["top_text"],
        bottom_text=item["bottom_text"]
    )

    from aiogram.types import InputMediaPhoto, BufferedInputFile
    media = InputMediaPhoto(
        media=BufferedInputFile(preview_bytes, filename="preview.webp"),
        caption=callback.message.caption
    )
    await callback.message.edit_media(
        media=media,
        reply_markup=get_interactive_preview_keyboard(
            item["pack_id"],
            temp_id,
            item["outline"],
            item["emoji"]
        )
    )
    await callback.answer()


@router.callback_query(F.data.startswith("preview_confirm_add:"))
async def callback_preview_confirm_add(callback: CallbackQuery, bot: Bot, repo: Repository):
    temp_id = callback.data.split(":")[1]
    item = PREVIEW_CACHE.pop(temp_id, None)
    if not item:
        await callback.answer("Сессия устарела. Отправьте медиа заново.", show_alert=True)
        return

    pack = await repo.get_pack(item["pack_id"])
    if not pack or pack.user_id != callback.from_user.id:
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    await callback.message.edit_caption(caption="⏳ Добавляю стикер в пак...")

    try:
        processed_bytes = process_image(
            item["raw_bytes"],
            add_outline=item["outline"],
            is_custom_emoji=item["is_custom_emoji"],
            top_text=item["top_text"],
            bottom_text=item["bottom_text"]
        )

        sticker_service = StickerService(bot)
        await sticker_service.add_sticker(
            user_id=callback.from_user.id,
            name=pack.name,
            sticker_data=processed_bytes,
            format_=pack.format,
            emojis=[item["emoji"]]
        )

        set_info = await sticker_service.get_pack_info(pack.name)
        last_file_id = set_info.stickers[-1].file_id if set_info and set_info.stickers else "file"
        last_unique_id = set_info.stickers[-1].file_unique_id if set_info and set_info.stickers else str(uuid.uuid4())

        await repo.add_sticker(
            pack_id=pack.id,
            file_id=last_file_id,
            file_unique_id=last_unique_id,
            emoji=item["emoji"]
        )

        pack_link = format_pack_link(pack.name)
        await callback.message.edit_caption(
            caption=(
                f"✅ **Стикер успешно добавлен!**\n\n"
                f"📦 Пак: **{pack.title}**\n"
                f"🎯 Эмодзи: {item['emoji']}\n"
                f"🔗 {pack_link}"
            ),
            reply_markup=get_sticker_added_keyboard(pack, last_file_id),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.exception("Error in preview_confirm_add: %s", e)
        await callback.message.edit_caption(caption=f"❌ Ошибка добавления: {e}")


@router.callback_query(F.data.startswith("preview_cancel:"))
async def callback_preview_cancel(callback: CallbackQuery):
    temp_id = callback.data.split(":")[1]
    PREVIEW_CACHE.pop(temp_id, None)
    await callback.message.delete()
    await callback.answer("Отменено.")


@router.callback_query(F.data.startswith("del_sticker_fid:"))
async def callback_delete_sticker_by_fid(callback: CallbackQuery, bot: Bot, repo: Repository):
    parts = callback.data.split(":")
    pack_id = int(parts[1])
    file_id = parts[2]

    pack = await repo.get_pack(pack_id)
    if not pack or pack.user_id != callback.from_user.id:
        await callback.answer("⛔️ У вас нет прав для изменения этого набора.", show_alert=True)
        return

    sticker_service = StickerService(bot)
    success = await sticker_service.delete_sticker(file_id)
    if success:
        last_sticker = await repo.get_last_sticker(pack_id)
        if last_sticker:
            await repo.delete_sticker(last_sticker.id, pack_id)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("🗑 Стикер успешно удален из набора!", show_alert=True)
    else:
        await callback.answer("❌ Не удалось удалить стикер.", show_alert=True)
