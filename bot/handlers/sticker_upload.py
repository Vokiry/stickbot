import html
import io
import logging
import time
import uuid
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile
)
from aiogram.exceptions import TelegramBadRequest

from bot.config import settings
from bot.database.models import User, StickerPack
from bot.database.repository import Repository
from bot.services.sticker_service import StickerService
from bot.services.image_processor import process_image
from bot.services.video_processor import process_video
from bot.utils.helpers import extract_emojis, format_pack_link
from bot.utils.keyboards import get_sticker_added_keyboard, get_interactive_preview_keyboard

logger = logging.getLogger(__name__)

router = Router(name="sticker_upload")

# In-memory storage for interactive previews with automatic TTL cleanup
PREVIEW_CACHE: dict[str, dict] = {}
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB


class PreviewChangeEmojiSG(StatesGroup):
    waiting_for_emoji = State()


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
    user: User
) -> Optional[StickerPack]:
    """
    Finds current active pack or automatically selects an existing pack for the user.
    """
    if user.active_pack_id:
        active_pack = await repo.get_pack(user.active_pack_id)
        if active_pack:
            return active_pack

    # If no active pack set, try finding any pack
    all_packs = await repo.get_user_packs(user.telegram_id)
    if all_packs:
        pack = all_packs[0]
        await repo.set_active_pack(user.telegram_id, pack.id)
        return pack

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Создать стикерпак", callback_data="create_new_pack")]
    ])
    await message.answer(
        "⚠️ <b>У вас пока нет активного стикерпака!</b>\n\n"
        "Чтобы сохранять стикеры, сначала создайте свой набор.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    return None


@router.message(F.photo)
@router.message(F.document)
@router.message(F.video)
@router.message(F.animation)
async def handle_media_upload(
    message: Message,
    bot: Bot,
    repo: Repository,
    user: User
):
    # 1. Determine media format and file_id
    is_video = False
    file_id = None

    if message.video or message.animation:
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
    pack = await get_or_resolve_active_pack(message, repo, user)
    if not pack:
        return

    # If pack is purely vector animated (.TGS), it cannot accept raster images/videos
    if pack.format == "animated":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📂 Сменить активный пак", callback_data="back_to_packs")],
            [InlineKeyboardButton(text="🎨 Создать новый пак", callback_data="create_new_pack")]
        ])
        await message.answer(
            f"⚠️ Пак «<b>{html.escape(pack.title)}</b>» является векторным анимированным (.TGS).\n"
            f"В него нельзя добавлять обычные фото или видео. Выберите обычный пак:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    # Check sticker limit (120 for regular, 200 for emoji)
    limit = 200 if pack.sticker_type == "custom_emoji" else 120
    if pack.stickers_count >= limit:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Создать Часть 2", callback_data="create_new_pack")]
        ])
        title_esc = html.escape(pack.title)
        await message.answer(
            f"⚠️ Стикерпак «<b>{title_esc}</b>» полностью заполнен ({pack.stickers_count}/{limit} стикеров)!\n"
            f"Создайте следующий пак для продолжения коллекции.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    # 3. Extract emoji
    emojis = extract_emojis(message.caption, default=user.settings_default_emoji)
    is_custom_emoji = (pack.sticker_type == "custom_emoji")

    # If Quick Mode is ON: process and add immediately
    if user.settings_quick_mode:
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

            # Add to set in Telegram with the actual media_format ('static' or 'video')
            sticker_service = StickerService(bot)
            await sticker_service.add_sticker(
                user_id=message.from_user.id,
                name=pack.name,
                sticker_data=processed_bytes,
                format_=media_format,
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

            await status_msg.delete()

            # Send sticker message to force client cache invalidation
            try:
                await bot.send_sticker(chat_id=message.chat.id, sticker=last_file_id)
            except Exception as e:
                logger.warning("Could not send added sticker: %s", e)

            pack_link = format_pack_link(pack.name)
            title_esc = html.escape(pack.title)
            await message.answer(
                f"✅ <b>Стикер успешно добавлен!</b>\n\n"
                f"📦 Пак: <b>{title_esc}</b> ({pack.stickers_count + 1}/{limit})\n"
                f"🎯 Эмодзи: {' '.join(emojis)}\n"
                f"🔗 {pack_link}",
                reply_markup=get_sticker_added_keyboard(pack, last_file_id),
                parse_mode="HTML"
            )

        except TelegramBadRequest as e:
            logger.error("Telegram error adding sticker: %s", e.message)
            await status_msg.edit_text(f"❌ Ошибка Telegram: `{e.message}`", parse_mode="Markdown")
        except Exception as e:
            logger.exception("Error adding sticker: %s", e)
            await status_msg.edit_text(f"❌ Не удалось добавить стикер: {e}")

    else:
        # Interactive Mode: generate preview and show options for BOTH images and videos
        file_info = await bot.get_file(file_id)
        if file_info.file_size and file_info.file_size > MAX_FILE_SIZE:
            await message.answer("⚠️ Файл слишком большой (максимум 25 МБ). Пожалуйста, отправьте файл меньшего размера.")
            return

        buf = io.BytesIO()
        await bot.download_file(file_info.file_path, buf)
        raw_bytes = buf.getvalue()

        cleanup_preview_cache()
        temp_id = str(uuid.uuid4())[:8]

        title_esc = html.escape(pack.title)

        if is_video:
            status_msg = await message.answer("⏳ Готовлю предпросмотр видеостикера...")
            preview_bytes = await process_video(
                raw_bytes,
                temp_dir=settings.TEMP_DIR,
                is_custom_emoji=is_custom_emoji
            )
            await status_msg.delete()

            PREVIEW_CACHE[temp_id] = {
                "raw_bytes": raw_bytes,
                "processed_bytes": preview_bytes,
                "pack_id": pack.id,
                "format": "video",
                "is_custom_emoji": is_custom_emoji,
                "outline": False,
                "emoji": emojis[0],
                "top_text": "",
                "bottom_text": "",
                "created_at": time.time()
            }

            video_file = BufferedInputFile(preview_bytes, filename="preview.webm")
            await message.answer_video(
                video_file,
                caption=(
                    f"🎨 <b>Предпросмотр видеостикера</b>\n\n"
                    f"Пак: <b>{title_esc}</b>\n"
                    f"Эмодзи: {emojis[0]}\n\n"
                    f"Подтвердите добавление в пак:"
                ),
                reply_markup=get_interactive_preview_keyboard(
                    pack.id,
                    temp_id,
                    outline_enabled=False,
                    emoji=emojis[0],
                    is_video=True
                ),
                parse_mode="HTML"
            )
        else:
            preview_bytes = process_image(
                raw_bytes,
                add_outline=user.settings_auto_outline,
                is_custom_emoji=is_custom_emoji
            )

            PREVIEW_CACHE[temp_id] = {
                "raw_bytes": raw_bytes,
                "processed_bytes": preview_bytes,
                "pack_id": pack.id,
                "format": "static",
                "is_custom_emoji": is_custom_emoji,
                "outline": user.settings_auto_outline,
                "emoji": emojis[0],
                "top_text": "",
                "bottom_text": "",
                "created_at": time.time()
            }

            photo_file = BufferedInputFile(preview_bytes, filename="preview.webp")
            await message.answer_photo(
                photo_file,
                caption=(
                    f"🎨 <b>Предпросмотр стикера</b>\n\n"
                    f"Пак: <b>{title_esc}</b>\n"
                    f"Эмодзи: {emojis[0]}\n\n"
                    f"Настройте параметры или подтвердите добавление:"
                ),
                reply_markup=get_interactive_preview_keyboard(
                    pack.id,
                    temp_id,
                    user.settings_auto_outline,
                    emojis[0],
                    is_video=False
                ),
                parse_mode="HTML"
            )


@router.callback_query(F.data.startswith("preview_change_emoji:"))
async def callback_preview_change_emoji(callback: CallbackQuery, state: FSMContext):
    temp_id = callback.data.split(":")[1]
    if temp_id not in PREVIEW_CACHE:
        await callback.answer("Сессия устарела.", show_alert=True)
        return

    await state.update_data(preview_temp_id=temp_id)
    await state.set_state(PreviewChangeEmojiSG.waiting_for_emoji)
    await callback.message.answer(
        "🎯 Отправьте **новый эмодзи** для этого стикера (например: 🔥 или 😎):",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(PreviewChangeEmojiSG.waiting_for_emoji, F.text)
async def process_preview_new_emoji(message: Message, state: FSMContext):
    emojis = extract_emojis(message.text)
    new_emoji = emojis[0] if emojis else "✨"
    data = await state.get_data()
    temp_id = data.get("preview_temp_id")

    if temp_id and temp_id in PREVIEW_CACHE:
        PREVIEW_CACHE[temp_id]["emoji"] = new_emoji

    await state.clear()
    await message.answer(
        f"✅ Выбран эмодзи: {new_emoji}. Нажмите кнопку «✅ Добавить в пак» под предпросмотром выше."
    )


@router.callback_query(F.data.startswith("preview_toggle_outline:"))
async def callback_preview_toggle_outline(callback: CallbackQuery):
    temp_id = callback.data.split(":")[1]
    item = PREVIEW_CACHE.get(temp_id)
    if not item:
        await callback.answer("Сессия предпросмотра устарела.", show_alert=True)
        return

    if item.get("format") == "video":
        await callback.answer("Обводка поддерживается только для статичных картинок.", show_alert=True)
        return

    item["outline"] = not item["outline"]

    preview_bytes = process_image(
        item["raw_bytes"],
        add_outline=item["outline"],
        is_custom_emoji=item["is_custom_emoji"],
        top_text=item["top_text"],
        bottom_text=item["bottom_text"]
    )
    item["processed_bytes"] = preview_bytes

    from aiogram.types import InputMediaPhoto
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
            item["emoji"],
            is_video=False
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
        media_fmt = item.get("format", "static")
        processed_bytes = item.get("processed_bytes")

        if not processed_bytes:
            if media_fmt == "video":
                processed_bytes = await process_video(
                    item["raw_bytes"],
                    temp_dir=settings.TEMP_DIR,
                    is_custom_emoji=item["is_custom_emoji"]
                )
            else:
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
            format_=media_fmt,  # Strictly 'static' or 'video'
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

        # Send sticker message to force client cache invalidation
        try:
            await bot.send_sticker(chat_id=callback.message.chat.id, sticker=last_file_id)
        except Exception as e:
            logger.warning("Could not send added sticker preview: %s", e)

        pack_link = format_pack_link(pack.name)
        title_esc = html.escape(pack.title)
        await callback.message.edit_caption(
            caption=(
                f"✅ <b>Стикер успешно добавлен!</b>\n\n"
                f"📦 Пак: <b>{title_esc}</b>\n"
                f"🎯 Эмодзи: {item['emoji']}\n"
                f"🔗 {pack_link}"
            ),
            reply_markup=get_sticker_added_keyboard(pack, last_file_id),
            parse_mode="HTML"
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
