import asyncio
import io
import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from bot.config import settings
from bot.database.models import User
from bot.database.repository import Repository
from bot.services.sticker_service import StickerService
from bot.utils.helpers import (
    extract_pack_name_from_text,
    generate_random_pack_name,
    format_pack_link
)
from bot.utils.keyboards import (
    get_cancel_keyboard,
    get_pack_details_keyboard,
    get_confirm_import_keyboard
)

logger = logging.getLogger(__name__)

router = Router(name="pack_import")


class ImportPackSG(StatesGroup):
    waiting_for_pack = State()


@router.message(Command("import"))
@router.message(F.text == "📥 Импорт пака")
async def start_import_command(message: Message, state: FSMContext):
    await state.set_state(ImportPackSG.waiting_for_pack)
    await message.answer(
        "📥 **Импорт и клонирование стикерпака**\n\n"
        "Отправьте мне **ссылку на стикерпак** (например: `t.me/addstickers/animals`),\n"
        "его короткое имя или **просто перешлите любой стикер** из набора, который хотите редактировать:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )


@router.message(ImportPackSG.waiting_for_pack, F.sticker)
async def process_sticker_for_import(message: Message, state: FSMContext, bot: Bot, repo: Repository, user: User):
    if not message.sticker.set_name:
        await message.answer("⚠️ У этого стикера нет привязанного набора. Отправьте ссылку на пак:")
        return
    await handle_pack_lookup(message.sticker.set_name, message, state, bot, repo, user)


@router.message(ImportPackSG.waiting_for_pack, F.text)
async def process_link_for_import(message: Message, state: FSMContext, bot: Bot, repo: Repository, user: User):
    pack_name = extract_pack_name_from_text(message.text)
    if not pack_name:
        await message.answer(
            "⚠️ Не удалось распознать ссылку. Отправьте ссылку вида `t.me/addstickers/name` или перешлите стикер:",
            reply_markup=get_cancel_keyboard()
        )
        return
    await handle_pack_lookup(pack_name, message, state, bot, repo, user)


@router.message(F.text.regexp(r"(?:https?://)?t\.me/addstickers/([a-zA-Z0-9_]+)"))
async def process_direct_pack_link(message: Message, state: FSMContext, bot: Bot, repo: Repository, user: User):
    pack_name = extract_pack_name_from_text(message.text)
    if pack_name:
        await handle_pack_lookup(pack_name, message, state, bot, repo, user)


async def handle_pack_lookup(
    pack_name: str,
    message: Message,
    state: FSMContext,
    bot: Bot,
    repo: Repository,
    user: User
):
    sticker_service = StickerService(bot)
    set_info = await sticker_service.get_pack_info(pack_name)

    if not set_info:
        await message.answer(
            f"⚠️ Стикерпак `{pack_name}` не найден в Telegram. Проверьте правильность ссылки.",
            parse_mode="Markdown"
        )
        return

    bot_user = await bot.get_me()
    bot_username = bot_user.username or settings.BOT_USERNAME or "vokistickbot"
    is_our_bot_pack = pack_name.lower().endswith(f"_by_{bot_username.lower()}")

    # Case 1: Already created by this bot! Simply link into user database
    if is_our_bot_pack:
        existing = await repo.get_pack_by_name(pack_name)
        if not existing:
            format_ = "video" if set_info.is_video else ("animated" if set_info.is_animated else "static")
            pack = await repo.create_pack(
                user_id=message.from_user.id,
                name=pack_name,
                title=set_info.title,
                sticker_type=set_info.sticker_type,
                format_=format_,
                initial_stickers_count=len(set_info.stickers)
            )
            for s in set_info.stickers:
                await repo.add_sticker(pack.id, s.file_id, s.file_unique_id, s.emoji or "✨")
        else:
            pack = existing
            await repo.set_active_pack(message.from_user.id, pack.id)

        await state.clear()
        await message.answer(
            f"✅ **Стикерпак успешно подключен!**\n\n"
            f"Пак «**{set_info.title}**» ({len(set_info.stickers)} шт.) уже управляется этим ботом. "
            f"Он добавлен в ваш список и сделан **активным**.\n\n"
            f"Теперь вы можете свободно добавлять в него стикеры или удалять их через /packs!",
            reply_markup=get_pack_details_keyboard(pack, is_active=True),
            parse_mode="Markdown"
        )
        return

    # Case 2: External pack (created by @Stickers or other bot)
    await state.clear()
    format_name = "🎬 Видео" if set_info.is_video else ("✨ Анимация" if set_info.is_animated else "🖼 Статика")

    text = (
        f"📦 **Найден стикерпак:** {set_info.title}\n\n"
        f"• **Формат:** {format_name}\n"
        f"• **Стикеров:** {len(set_info.stickers)} шт.\n"
        f"• **Оригинальная ссылка:** {format_pack_link(pack_name)}\n\n"
        f"ℹ️ _Этот пак создан через другого бота/интерфейс, поэтому Telegram запрещает изменять его напрямую._\n\n"
        f"💡 **Решение:** Нажмите кнопку ниже — бот скопирует все стикеры в ваш личный пак под управлением @{bot_username}. "
        f"После этого вы сможете добавлять, удалять и менять в нем любые стикеры!"
    )

    await message.answer(
        text,
        reply_markup=get_confirm_import_keyboard(pack_name),
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("clone_source:"))
async def callback_clone_source(callback: CallbackQuery, bot: Bot, repo: Repository, user: User, state: FSMContext):
    source_name = callback.data.split(":")[1]
    await handle_pack_lookup(source_name, callback.message, state, bot, repo, user)
    await callback.answer()


@router.callback_query(F.data.startswith("do_clone_pack:"))
async def callback_do_clone_pack(callback: CallbackQuery, bot: Bot, repo: Repository, user: User):
    source_pack_name = callback.data.split(":")[1]
    sticker_service = StickerService(bot)
    set_info = await sticker_service.get_pack_info(source_pack_name)

    if not set_info or not set_info.stickers:
        await callback.answer("⚠️ Не удалось получить стикеры из этого пака.", show_alert=True)
        return

    bot_user = await bot.get_me()
    bot_username = bot_user.username or settings.BOT_USERNAME or "vokistickbot"

    # Generate new unique pack name
    slug_prefix = source_pack_name.split("_by_")[0][:12]
    new_pack_name = generate_random_pack_name(bot_username, prefix=slug_prefix)
    new_title = f"{set_info.title}"
    format_ = "video" if set_info.is_video else ("animated" if set_info.is_animated else "static")
    sticker_type = set_info.sticker_type

    total = len(set_info.stickers)
    await callback.message.edit_text(f"⏳ Начинаю клонирование пака (0/{total} стикеров)...")

    # Step 1: Create new sticker set with the first sticker
    first_stk = set_info.stickers[0]
    first_emoji = [first_stk.emoji] if first_stk.emoji else ["✨"]

    try:
        # Try direct file_id first
        await sticker_service.create_new_pack(
            user_id=callback.from_user.id,
            name=new_pack_name,
            title=new_title,
            sticker_data=first_stk.file_id,
            format_=format_,
            sticker_type=sticker_type,
            emojis=first_emoji
        )
    except TelegramBadRequest as e:
        logger.warning("Direct file_id createNewStickerSet failed (%s), falling back to download bytes", e.message)
        # Download bytes fallback
        f_info = await bot.get_file(first_stk.file_id)
        buf = io.BytesIO()
        await bot.download_file(f_info.file_path, buf)
        await sticker_service.create_new_pack(
            user_id=callback.from_user.id,
            name=new_pack_name,
            title=new_title,
            sticker_data=buf.getvalue(),
            format_=format_,
            sticker_type=sticker_type,
            emojis=first_emoji
        )

    # Persist in DB
    pack = await repo.create_pack(
        user_id=callback.from_user.id,
        name=new_pack_name,
        title=new_title,
        sticker_type=sticker_type,
        format_=format_,
        initial_stickers_count=1
    )

    # Save first sticker to DB
    new_set_info = await sticker_service.get_pack_info(new_pack_name)
    if new_set_info and new_set_info.stickers:
        await repo.add_sticker(pack.id, new_set_info.stickers[0].file_id, new_set_info.stickers[0].file_unique_id, first_emoji[0])

    # Step 2: Loop remaining stickers
    cloned_count = 1
    for idx, stk in enumerate(set_info.stickers[1:], start=2):
        emojis = [stk.emoji] if stk.emoji else ["✨"]
        try:
            # Try direct file_id
            await sticker_service.add_sticker(
                user_id=callback.from_user.id,
                name=new_pack_name,
                sticker_data=stk.file_id,
                format_=format_,
                emojis=emojis
            )
        except TelegramBadRequest:
            # Fallback download bytes
            try:
                f_info = await bot.get_file(stk.file_id)
                buf = io.BytesIO()
                await bot.download_file(f_info.file_path, buf)
                await sticker_service.add_sticker(
                    user_id=callback.from_user.id,
                    name=new_pack_name,
                    sticker_data=buf.getvalue(),
                    format_=format_,
                    emojis=emojis
                )
            except Exception as e:
                logger.error("Failed to clone sticker %d: %s", idx, e)
                continue

        cloned_count += 1
        # Update progress every 5 stickers
        if idx % 5 == 0 or idx == total:
            try:
                await callback.message.edit_text(f"⏳ Переношу стикеры ({idx}/{total})...")
            except Exception:
                pass

        await asyncio.sleep(0.3)  # Rate limiting protection

    # Populate rest of stickers in DB
    final_info = await sticker_service.get_pack_info(new_pack_name)
    if final_info:
        for s in final_info.stickers[1:]:
            await repo.add_sticker(pack.id, s.file_id, s.file_unique_id, s.emoji or "✨")

    pack_link = format_pack_link(new_pack_name)
    await callback.message.edit_text(
        f"🎉 **Стикерпак успешно импортирован!**\n\n"
        f"📦 **Название:** {new_title}\n"
        f"📊 **Стикеров перенесено:** {cloned_count}/{total} шт.\n"
        f"🔗 **Ссылка:** {pack_link}\n\n"
        f"Пак сделан **активным** в боте. Теперь вы можете отправлять любые новые фото/видео, и они добавятся сюда, "
        f"а также удалять ненужные стикеры через меню /packs!",
        reply_markup=get_pack_details_keyboard(pack, is_active=True),
        parse_mode="Markdown"
    )
