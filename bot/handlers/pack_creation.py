import html
import io
import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from bot.config import settings
from bot.database.models import User
from bot.database.repository import Repository
from bot.services.sticker_service import StickerService
from bot.services.image_processor import process_image
from bot.services.video_processor import process_video
from bot.utils.helpers import (
    sanitize_pack_slug,
    generate_random_pack_name,
    extract_emojis,
    format_pack_link
)
from bot.utils.keyboards import (
    get_pack_type_keyboard,
    get_random_name_keyboard,
    get_cancel_keyboard,
    get_main_reply_keyboard,
    get_pack_details_keyboard
)

logger = logging.getLogger(__name__)

router = Router(name="pack_creation")


class PackCreationSG(StatesGroup):
    choose_type = State()
    enter_title = State()
    enter_name = State()
    send_first_sticker = State()


@router.message(Command("newpack"))
@router.message(F.text == "🎨 Создать пак")
async def start_newpack_command(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(PackCreationSG.choose_type)
    await message.answer(
        "✨ **Создание нового стикерпака**\n\n"
        "Выберите тип создаваемого набора:",
        reply_markup=get_pack_type_keyboard(),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "create_new_pack")
async def start_newpack_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(PackCreationSG.choose_type)
    await callback.message.edit_text(
        "✨ **Создание нового стикерпака**\n\n"
        "Выберите тип создаваемого набора:",
        reply_markup=get_pack_type_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(PackCreationSG.choose_type, F.data.startswith("pack_type:"))
async def process_pack_type(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    sticker_type = parts[1]  # 'regular' | 'custom_emoji'
    format_ = parts[2]        # 'static' | 'video'

    await state.update_data(sticker_type=sticker_type, format=format_)
    await state.set_state(PackCreationSG.enter_title)

    type_name = "⭐️ Кастомные эмодзи" if sticker_type == "custom_emoji" else (
        "🎬 Видеостикеры" if format_ == "video" else "🖼 Статические стикеры"
    )

    await callback.message.edit_text(
        f"Выбран тип: **{type_name}**\n\n"
        "Введите **название** для вашего пака (до 64 символов):\n"
        "Например: *Мои мемы* или *Смешные коты*",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(PackCreationSG.enter_title, F.text)
async def process_pack_title(message: Message, state: FSMContext, bot: Bot):
    title = message.text.strip()
    if len(title) > 64:
        await message.answer("⚠️ Название слишком длинное (максимум 64 символа). Попробуйте еще раз:")
        return

    await state.update_data(title=title)
    await state.set_state(PackCreationSG.enter_name)

    bot_user = await bot.get_me()
    bot_username = bot_user.username or settings.BOT_USERNAME or "vokistickbot"

    await message.answer(
        f"Название: **{title}**\n\n"
        f"Теперь укажите **короткий адрес** для ссылки на пак (только английские буквы, цифры и _).\n"
        f"Ссылка будет иметь вид: `t.me/addstickers/<адрес>_by_{bot_username}`\n\n"
        f"Или нажмите кнопку ниже для автоматической генерации:",
        reply_markup=get_random_name_keyboard(),
        parse_mode="Markdown"
    )


@router.callback_query(PackCreationSG.enter_name, F.data == "auto_pack_name")
async def process_auto_pack_name(callback: CallbackQuery, state: FSMContext, bot: Bot):
    bot_user = await bot.get_me()
    bot_username = bot_user.username or settings.BOT_USERNAME or "vokistickbot"

    pack_name = generate_random_pack_name(bot_username)
    await state.update_data(name=pack_name)
    await state.set_state(PackCreationSG.send_first_sticker)

    data = await state.get_data()
    format_ = data.get("format", "static")

    guide = (
        "🎬 Отправьте **видео (до 3 секунд) или GIF-анимацию**"
        if format_ == "video"
        else "📸 Отправьте **фотографию или файл-картинку (PNG/JPG/WEBP)**"
    )

    await callback.message.edit_text(
        f"Адрес пака: `{pack_name}`\n\n"
        f"✨ **Финальный шаг:** Telegram требует добавить хотя бы 1 стикер для создания пака.\n\n"
        f"{guide}\n\n"
        f"💡 *Совет:* Вы можете указать эмодзи в подписи к медиа (например: 🔥).",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(PackCreationSG.enter_name, F.text)
async def process_custom_pack_name(message: Message, state: FSMContext, bot: Bot):
    bot_user = await bot.get_me()
    bot_username = bot_user.username or settings.BOT_USERNAME or "vokistickbot"

    raw_slug = message.text.strip()
    pack_name = sanitize_pack_slug(raw_slug, bot_username)

    await state.update_data(name=pack_name)
    await state.set_state(PackCreationSG.send_first_sticker)

    data = await state.get_data()
    format_ = data.get("format", "static")

    guide = (
        "🎬 Отправьте **видео (до 3 секунд) или GIF-анимацию**"
        if format_ == "video"
        else "📸 Отправьте **фотографию или файл-картинку (PNG/JPG/WEBP)**"
    )

    await message.answer(
        f"Адрес пака: `{pack_name}`\n\n"
        f"✨ **Финальный шаг:** Telegram требует добавить хотя бы 1 стикер для создания пака.\n\n"
        f"{guide}\n\n"
        f"💡 *Совет:* Вы можете указать эмодзи в подписи к медиа (например: 🔥).",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )


@router.message(PackCreationSG.send_first_sticker)
async def process_first_sticker(
    message: Message,
    state: FSMContext,
    bot: Bot,
    repo: Repository,
    user: User
):
    data = await state.get_data()
    sticker_type = data["sticker_type"]
    format_ = data["format"]
    title = data["title"]
    pack_name = data["name"]

    is_custom_emoji = (sticker_type == "custom_emoji")
    emojis = extract_emojis(message.caption, default=user.settings_default_emoji)

    status_msg = await message.answer("⏳ Обрабатываю медиа и создаю пак в Telegram...")

    try:
        # Static media branch
        if format_ == "static":
            file_id = None
            if message.photo:
                file_id = message.photo[-1].file_id
            elif message.document and (message.document.mime_type or "").startswith("image/"):
                file_id = message.document.file_id
            elif message.sticker and not (message.sticker.is_video or message.sticker.is_animated):
                file_id = message.sticker.file_id

            if not file_id:
                await status_msg.edit_text(
                    "⚠️ Ожидалось фото или картинка! Пожалуйста, отправьте изображение (PNG, JPG или WEBP):",
                    reply_markup=get_cancel_keyboard()
                )
                return

            file_info = await bot.get_file(file_id)
            if file_info.file_size and file_info.file_size > 25 * 1024 * 1024:
                await status_msg.edit_text("⚠️ Файл слишком большой (максимум 25 МБ).", reply_markup=get_cancel_keyboard())
                return
            file_bytes_io = io.BytesIO()
            await bot.download_file(file_info.file_path, file_bytes_io)
            raw_bytes = file_bytes_io.getvalue()

            processed_bytes = process_image(
                raw_bytes,
                add_outline=user.settings_auto_outline,
                is_custom_emoji=is_custom_emoji
            )

        # Video media branch
        else:
            file_id = None
            if message.video:
                file_id = message.video.file_id
            elif message.animation:
                file_id = message.animation.file_id
            elif message.document and (
                (message.document.mime_type or "").startswith("video/") or
                (message.document.file_name or "").lower().endswith((".mp4", ".webm", ".gif", ".mov"))
            ):
                file_id = message.document.file_id
            elif message.sticker and message.sticker.is_video:
                file_id = message.sticker.file_id

            if not file_id:
                await status_msg.edit_text(
                    "⚠️ Ожидалось видео или GIF! Пожалуйста, отправьте короткое видео или GIF-анимацию:",
                    reply_markup=get_cancel_keyboard()
                )
                return

            file_info = await bot.get_file(file_id)
            if file_info.file_size and file_info.file_size > 25 * 1024 * 1024:
                await status_msg.edit_text("⚠️ Файл слишком большой (максимум 25 МБ).", reply_markup=get_cancel_keyboard())
                return
            file_bytes_io = io.BytesIO()
            await bot.download_file(file_info.file_path, file_bytes_io)
            raw_bytes = file_bytes_io.getvalue()

            processed_bytes = await process_video(
                raw_bytes,
                temp_dir=settings.TEMP_DIR,
                is_custom_emoji=is_custom_emoji
            )

        # Create sticker set via StickerService
        sticker_service = StickerService(bot)
        await sticker_service.create_new_pack(
            user_id=message.from_user.id,
            name=pack_name,
            title=title,
            sticker_data=processed_bytes,
            format_=format_,
            sticker_type=sticker_type,
            emojis=emojis
        )

        # Persist in local database
        pack = await repo.create_pack(
            user_id=message.from_user.id,
            name=pack_name,
            title=title,
            sticker_type=sticker_type,
            format_=format_,
            initial_stickers_count=1
        )

        # Fetch newly created set to get sticker's file_id
        set_info = await sticker_service.get_pack_info(pack_name)
        if set_info and set_info.stickers:
            first_sticker = set_info.stickers[0]
            await repo.add_sticker(
                pack_id=pack.id,
                file_id=first_sticker.file_id,
                file_unique_id=first_sticker.file_unique_id,
                emoji=emojis[0]
            )

        await state.clear()
        pack_link = format_pack_link(pack_name)
        await status_msg.delete()

        # Send sticker message to force client cache invalidation
        if set_info and set_info.stickers:
            try:
                await bot.send_sticker(chat_id=message.chat.id, sticker=set_info.stickers[0].file_id)
            except Exception as e:
                logger.warning("Could not send first sticker preview: %s", e)

        title_esc = html.escape(title)
        await message.answer(
            f"🎉 <b>Стикерпак успешно создан!</b>\n\n"
            f"📌 <b>Название:</b> {title_esc}\n"
            f"🔗 <b>Ссылка:</b> {pack_link}\n\n"
            f"Этот пак установлен как <b>активный</b>. Теперь вы можете просто присылать боту любые изображения или видео, "
            f"и они будут сразу добавляться в этот набор!",
            reply_markup=get_pack_details_keyboard(pack, is_active=True),
            parse_mode="HTML"
        )

    except TelegramBadRequest as e:
        logger.error("TelegramBadRequest in process_first_sticker: %s", e.message)
        if "STICKERSET_NAME_OCCUPIED" in e.message or "stickerset name is already occupied" in e.message.lower():
            await status_msg.edit_text(
                "⚠️ К сожалению, адрес этого пака уже занят другим набором в Telegram.\n"
                "Пожалуйста, укажите другой адрес или нажмите кнопку генерации:",
                reply_markup=get_random_name_keyboard()
            )
            await state.set_state(PackCreationSG.enter_name)
        else:
            await status_msg.edit_text(
                f"❌ Ошибка Telegram: `{e.message}`\n"
                f"Попробуйте отправить другой файл или перезапустите создание с /newpack.",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.exception("Unexpected error in process_first_sticker: %s", e)
        await status_msg.edit_text(
            f"❌ Произошла непредвиденная ошибка: {e}\n"
            f"Попробуйте еще раз или перезапустите с /newpack.",
            reply_markup=get_cancel_keyboard()
        )
