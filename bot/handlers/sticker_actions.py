import html
import logging
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from bot.config import settings
from bot.database.models import User, StickerPack
from bot.database.repository import Repository
from bot.services.sticker_service import StickerService
from bot.utils.helpers import extract_emojis, format_pack_link
from bot.utils.keyboards import get_cancel_keyboard

logger = logging.getLogger(__name__)

router = Router(name="sticker_actions")


class ChangeStickerEmojiSG(StatesGroup):
    waiting_for_emoji = State()


def is_authorized(user_id: int, pack_owner_id: int) -> bool:
    return user_id == pack_owner_id or user_id in settings.admin_ids


@router.message(F.sticker)
async def handle_sticker_inspect(
    message: Message,
    bot: Bot,
    repo: Repository,
    user: User,
    state: FSMContext
):
    await state.clear()
    stk = message.sticker
    file_id = stk.file_id
    set_name = stk.set_name
    emoji = stk.emoji or "✨"
    fmt = "video" if stk.is_video else ("animated" if stk.is_animated else "static")
    fmt_str = "🎬 Видео" if stk.is_video else ("✨ Анимация" if stk.is_animated else "🖼 Статика")

    sticker_service = StickerService(bot)

    # Check if this sticker belongs to a pack in our database
    pack = await repo.get_pack_by_name(set_name) if set_name else None

    # CASE 1: Sticker belongs to a pack managed by our bot and owned by user (or sender is admin)
    if pack and is_authorized(message.from_user.id, pack.user_id):
        title_esc = html.escape(pack.title)
        pack_url = format_pack_link(pack.name)
        admin_tag = " (Режим администратора)" if pack.user_id != message.from_user.id else ""

        text = (
            f"🎯 <b>Управление стикером в паке «{title_esc}»</b>{admin_tag}\n\n"
            f"• <b>Привязанный эмодзи:</b> {emoji}\n"
            f"• <b>Формат:</b> {fmt_str}\n"
            f"• <b>Стикерпак:</b> <a href=\"{pack_url}\">{title_esc}</a> ({pack.stickers_count} шт.)\n\n"
            f"Выберите точечное действие для этого стикера:"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🎯 Сменить эмодзи", callback_data=f"stk_change_emoji:{pack.id}:{file_id}"),
                InlineKeyboardButton(text="🔝 Сделать обложкой", callback_data=f"stk_make_thumb:{pack.id}:{file_id}")
            ],
            [
                InlineKeyboardButton(text="🔀 На 1-е место в паке", callback_data=f"stk_make_first:{pack.id}:{file_id}"),
                InlineKeyboardButton(text="📋 Скопировать в другой пак", callback_data=f"stk_copy_menu:{file_id}:{emoji}:{fmt}")
            ],
            [
                InlineKeyboardButton(text="🗑 Удалить этот стикер", callback_data=f"stk_delete_confirm:{pack.id}:{file_id}")
            ],
            [
                InlineKeyboardButton(text="🔗 Открыть пак", url=pack_url)
            ]
        ])

        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        return

    # CASE 2: External sticker (from @Stickers or other bot)
    set_title = set_name or "Без набора"
    set_count = "?"
    if set_name:
        set_info = await sticker_service.get_pack_info(set_name)
        if set_info:
            set_title = set_info.title
            set_count = str(len(set_info.stickers))

    title_esc = html.escape(set_title)
    active_pack = await repo.get_pack(user.active_pack_id) if user.active_pack_id else None
    active_str = f"«{active_pack.title}»" if active_pack else "не выбран"

    text = (
        f"🔍 <b>Стикер из набора: {title_esc}</b>\n\n"
        f"• <b>Эмодзи:</b> {emoji}\n"
        f"• <b>Формат:</b> {fmt_str}\n"
        f"• <b>Всего в наборе:</b> {set_count} шт.\n\n"
        f"Что вы хотите сделать с этим стикером?"
    )

    buttons = []
    if active_pack and active_pack.format == fmt:
        buttons.append([
            InlineKeyboardButton(
                text=f"➕ Добавить в активный пак ({active_str})",
                callback_data=f"stk_add_to_pack:{active_pack.id}:{file_id}:{emoji}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="📂 Выбрать пак для добавления",
            callback_data=f"stk_copy_menu:{file_id}:{emoji}:{fmt}"
        )
    ])

    if set_name:
        buttons.append([
            InlineKeyboardButton(
                text=f"📥 Клонировать весь этот пак ({set_count} шт.)",
                callback_data=f"do_clone_pack:{set_name}"
            )
        ])

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@router.callback_query(F.data.startswith("stk_change_emoji:"))
async def callback_stk_change_emoji(callback: CallbackQuery, state: FSMContext, repo: Repository):
    parts = callback.data.split(":")
    pack_id = int(parts[1])
    file_id = parts[2]

    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    await state.update_data(stk_file_id=file_id, stk_pack_id=pack_id)
    await state.set_state(ChangeStickerEmojiSG.waiting_for_emoji)

    await callback.message.edit_text(
        "🎯 Отправьте **новый эмодзи** (1–3 символа), который будет привязан к этому стикеру:\n"
        "(Например: 🔥 или 😎)",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ChangeStickerEmojiSG.waiting_for_emoji, F.text)
async def process_new_sticker_emoji(
    message: Message,
    state: FSMContext,
    bot: Bot,
    repo: Repository
):
    emojis = extract_emojis(message.text)
    if not emojis:
        await message.answer("⚠️ Пожалуйста, отправьте хотя бы один эмодзи:")
        return

    data = await state.get_data()
    file_id = data["stk_file_id"]
    pack_id = data["stk_pack_id"]

    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(message.from_user.id, pack.user_id):
        await state.clear()
        await message.answer("⚠️ Пак не найден или у вас нет прав.")
        return

    sticker_service = StickerService(bot)
    success = await sticker_service.change_sticker_emoji(file_id, emojis)

    if success:
        stk_item = await repo.get_sticker_by_file_id(file_id)
        if stk_item:
            await repo.update_sticker_emoji(stk_item.id, emojis[0])

        await state.clear()
        await message.answer(
            f"✅ **Эмодзи стикера успешно изменен на:** {' '.join(emojis)}\n"
            f"В паке «{pack.title}».",
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Не удалось изменить эмодзи в Telegram. Попробуйте еще раз.")


@router.callback_query(F.data.startswith("stk_make_thumb:"))
async def callback_stk_make_thumb(callback: CallbackQuery, bot: Bot, repo: Repository):
    parts = callback.data.split(":")
    pack_id = int(parts[1])
    file_id = parts[2]

    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    sticker_service = StickerService(bot)
    try:
        await sticker_service.set_pack_thumbnail(
            name=pack.name,
            user_id=callback.from_user.id,
            thumbnail_data=file_id,
            format_=pack.format
        )
        await callback.answer(f"🎉 Стикер установлен как обложка пака «{pack.title}»!", show_alert=True)
    except Exception as e:
        logger.error("Error setting thumb: %s", e)
        await callback.answer(f"❌ Ошибка установки обложки: {e}", show_alert=True)


@router.callback_query(F.data.startswith("stk_make_first:"))
async def callback_stk_make_first(callback: CallbackQuery, bot: Bot, repo: Repository):
    parts = callback.data.split(":")
    pack_id = int(parts[1])
    file_id = parts[2]

    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    sticker_service = StickerService(bot)
    success = await sticker_service.set_sticker_position(file_id, position=0)
    if success:
        await callback.answer(f"🔀 Стикер успешно перемещен на 1-е место в паке «{pack.title}»!", show_alert=True)
    else:
        await callback.answer("❌ Не удалось переместить стикер.", show_alert=True)


@router.callback_query(F.data.startswith("stk_delete_confirm:"))
async def callback_stk_delete_confirm(callback: CallbackQuery, repo: Repository):
    parts = callback.data.split(":")
    pack_id = int(parts[1])
    file_id = parts[2]

    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Да, удалить стикер", callback_data=f"stk_do_delete:{pack.id}:{file_id}")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_action")]
    ])

    await callback.message.edit_text(
        f"⚠️ <b>Вы уверены, что хотите удалить этот стикер из пака «{html.escape(pack.title)}»?</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stk_do_delete:"))
async def callback_stk_do_delete(callback: CallbackQuery, bot: Bot, repo: Repository):
    parts = callback.data.split(":")
    pack_id = int(parts[1])
    file_id = parts[2]

    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    sticker_service = StickerService(bot)
    success = await sticker_service.delete_sticker(file_id)

    if success:
        stk_item = await repo.get_sticker_by_file_id(file_id)
        if stk_item:
            await repo.delete_sticker(stk_item.id, pack.id)
        else:
            await repo.decrement_stickers_count(pack.id)

        await callback.message.edit_text(
            f"🗑 <b>Стикер успешно удален из пака «{html.escape(pack.title)}».</b>",
            parse_mode="HTML"
        )
        await callback.answer("Удалено!")
    else:
        await callback.answer("❌ Ошибка удаления стикера из Telegram.", show_alert=True)


@router.callback_query(F.data.startswith("stk_copy_menu:"))
async def callback_stk_copy_menu(callback: CallbackQuery, repo: Repository):
    parts = callback.data.split(":")
    file_id = parts[1]
    emoji = parts[2]
    fmt = parts[3]

    user_packs = await repo.get_user_packs(callback.from_user.id, format_=fmt)
    if not user_packs:
        await callback.answer(f"У вас нет других {fmt}-паков.", show_alert=True)
        return

    buttons = []
    for p in user_packs:
        buttons.append([
            InlineKeyboardButton(
                text=f"{p.title} ({p.stickers_count} шт)",
                callback_data=f"stk_add_to_pack:{p.id}:{file_id}:{emoji}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_action")])

    await callback.message.edit_text(
        "📂 <b>Выберите пак, в который хотите скопировать этот стикер:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stk_add_to_pack:"))
async def callback_stk_add_to_pack(callback: CallbackQuery, bot: Bot, repo: Repository):
    parts = callback.data.split(":")
    pack_id = int(parts[1])
    file_id = parts[2]
    emoji = parts[3]

    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    sticker_service = StickerService(bot)
    try:
        await sticker_service.add_sticker(
            user_id=callback.from_user.id,
            name=pack.name,
            sticker_data=file_id,
            format_=pack.format,
            emojis=[emoji]
        )

        set_info = await sticker_service.get_pack_info(pack.name)
        new_fid = set_info.stickers[-1].file_id if set_info and set_info.stickers else file_id
        new_uid = set_info.stickers[-1].file_unique_id if set_info and set_info.stickers else "uid"

        await repo.add_sticker(pack.id, new_fid, new_uid, emoji)

        pack_url = format_pack_link(pack.name)
        await callback.message.edit_text(
            f"✅ <b>Стикер успешно добавлен в пак «{html.escape(pack.title)}»!</b>\n\n"
            f"🎯 <b>Эмодзи:</b> {emoji}\n"
            f"🔗 <a href=\"{pack_url}\">Открыть пак в Telegram</a>",
            parse_mode="HTML"
        )
        await callback.answer("Стикер добавлен!")
    except Exception as e:
        logger.error("Error adding sticker to pack: %s", e)
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
