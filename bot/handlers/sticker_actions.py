import html
import logging
import secrets
import time
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

# Storage for sticker actions (keeps callback_data well under 64 bytes)
# token -> dict(file_id, emoji, format, pack_id, set_name, created_at)
ACTION_SESSIONS: dict[str, dict] = {}


def create_action_session(data: dict) -> str:
    now = time.time()
    # Evict sessions older than 10 minutes
    expired = [k for k, v in ACTION_SESSIONS.items() if now - v.get("created_at", now) > 600]
    for k in expired:
        ACTION_SESSIONS.pop(k, None)
    while len(ACTION_SESSIONS) > 100:
        oldest = next(iter(ACTION_SESSIONS))
        ACTION_SESSIONS.pop(oldest, None)

    token = secrets.token_hex(4)  # 8 characters
    data["created_at"] = now
    ACTION_SESSIONS[token] = data
    return token


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
        token = create_action_session({
            "file_id": file_id,
            "emoji": emoji,
            "format": fmt,
            "pack_id": pack.id,
            "pack_name": pack.name,
            "set_name": set_name
        })

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
                InlineKeyboardButton(text="🎯 Сменить эмодзи", callback_data=f"stk_emoji:{token}"),
                InlineKeyboardButton(text="🔝 Сделать обложкой", callback_data=f"stk_thumb:{token}")
            ],
            [
                InlineKeyboardButton(text="🔀 На 1-е место в паке", callback_data=f"stk_first:{token}"),
                InlineKeyboardButton(text="📋 Скопировать в другой пак", callback_data=f"stk_copy:{token}")
            ],
            [
                InlineKeyboardButton(text="🗑 Удалить этот стикер", callback_data=f"stk_del_ask:{token}")
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

    token = create_action_session({
        "file_id": file_id,
        "emoji": emoji,
        "format": fmt,
        "pack_id": None,
        "pack_name": None,
        "set_name": set_name
    })

    title_esc = html.escape(set_title)
    active_pack = await repo.get_pack(user.active_pack_id) if user.active_pack_id else None
    active_str = f"«{html.escape(active_pack.title)}»" if active_pack else "не выбран"

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
                callback_data=f"stk_add_act:{token}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="📂 Выбрать пак для добавления",
            callback_data=f"stk_copy:{token}"
        )
    ])

    if set_name:
        buttons.append([
            InlineKeyboardButton(
                text=f"📥 Клонировать весь этот пак ({set_count} шт.)",
                callback_data=f"stk_clone:{token}"
            )
        ])

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@router.callback_query(F.data.startswith("stk_emoji:"))
async def callback_stk_change_emoji(callback: CallbackQuery, state: FSMContext, repo: Repository):
    token = callback.data.split(":")[1]
    sess = ACTION_SESSIONS.get(token)
    if not sess:
        await callback.answer("Сессия действия устарела. Отправьте стикер заново.", show_alert=True)
        return

    pack = await repo.get_pack(sess["pack_id"])
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    await state.update_data(stk_token=token)
    await state.set_state(ChangeStickerEmojiSG.waiting_for_emoji)

    await callback.message.edit_text(
        "🎯 Отправьте <b>новый эмодзи</b> (1–3 символа), который будет привязан к этому стикеру:\n"
        "(Например: 🔥 или 😎)",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
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
        await message.answer("⚠️ Пожалуйста, отправьте хотя бы один валидный эмодзи:")
        return

    data = await state.get_data()
    token = data.get("stk_token")
    sess = ACTION_SESSIONS.get(token) if token else None
    if not sess:
        await state.clear()
        await message.answer("⚠️ Сессия истекла. Отправьте стикер заново.")
        return

    pack = await repo.get_pack(sess["pack_id"])
    if not pack or not is_authorized(message.from_user.id, pack.user_id):
        await state.clear()
        await message.answer("⚠️ Пак не найден или у вас нет прав.")
        return

    file_id = sess["file_id"]
    sticker_service = StickerService(bot)
    success = await sticker_service.change_sticker_emoji(file_id, emojis)

    if success:
        stk_item = await repo.get_sticker_by_file_id(file_id)
        if stk_item:
            await repo.update_sticker_emoji(stk_item.id, emojis[0])

        await state.clear()
        title_esc = html.escape(pack.title)
        await message.answer(
            f"✅ <b>Эмодзи стикера успешно изменен на:</b> {' '.join(emojis)}\n"
            f"В паке «{title_esc}».",
            parse_mode="HTML"
        )
    else:
        await message.answer("❌ Не удалось изменить эмодзи в Telegram. Попробуйте еще раз.")


@router.callback_query(F.data.startswith("stk_thumb:"))
async def callback_stk_make_thumb(callback: CallbackQuery, bot: Bot, repo: Repository):
    token = callback.data.split(":")[1]
    sess = ACTION_SESSIONS.get(token)
    if not sess:
        await callback.answer("Сессия действия устарела.", show_alert=True)
        return

    pack = await repo.get_pack(sess["pack_id"])
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    sticker_service = StickerService(bot)
    try:
        await sticker_service.set_pack_thumbnail(
            name=pack.name,
            user_id=callback.from_user.id,
            thumbnail_data=sess["file_id"],
            format_=pack.format
        )
        title_esc = html.escape(pack.title)
        await callback.answer(f"🎉 Стикер установлен как обложка пака «{title_esc}»!", show_alert=True)
    except Exception as e:
        logger.error("Error setting thumb: %s", e)
        await callback.answer(f"❌ Ошибка установки обложки: {e}", show_alert=True)


@router.callback_query(F.data.startswith("stk_first:"))
async def callback_stk_make_first(callback: CallbackQuery, bot: Bot, repo: Repository):
    token = callback.data.split(":")[1]
    sess = ACTION_SESSIONS.get(token)
    if not sess:
        await callback.answer("Сессия действия устарела.", show_alert=True)
        return

    pack = await repo.get_pack(sess["pack_id"])
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    sticker_service = StickerService(bot)
    success = await sticker_service.set_sticker_position(sess["file_id"], position=0)
    if success:
        title_esc = html.escape(pack.title)
        await callback.answer(f"🔀 Стикер перемещен на 1-е место в паке «{title_esc}»!", show_alert=True)
    else:
        await callback.answer("❌ Не удалось переместить стикер.", show_alert=True)


@router.callback_query(F.data.startswith("stk_del_ask:"))
async def callback_stk_delete_ask(callback: CallbackQuery, repo: Repository):
    token = callback.data.split(":")[1]
    sess = ACTION_SESSIONS.get(token)
    if not sess:
        await callback.answer("Сессия действия устарела.", show_alert=True)
        return

    pack = await repo.get_pack(sess["pack_id"])
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Да, удалить стикер", callback_data=f"stk_del_do:{token}")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_action")]
    ])

    title_esc = html.escape(pack.title)
    await callback.message.edit_text(
        f"⚠️ <b>Вы уверены, что хотите удалить этот стикер из пака «{title_esc}»?</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stk_del_do:"))
async def callback_stk_delete_do(callback: CallbackQuery, bot: Bot, repo: Repository):
    token = callback.data.split(":")[1]
    sess = ACTION_SESSIONS.pop(token, None)
    if not sess:
        await callback.answer("Сессия действия устарела.", show_alert=True)
        return

    pack = await repo.get_pack(sess["pack_id"])
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    file_id = sess["file_id"]
    sticker_service = StickerService(bot)
    success = await sticker_service.delete_sticker(file_id)

    if success:
        stk_item = await repo.get_sticker_by_file_id(file_id)
        if stk_item:
            await repo.delete_sticker(stk_item.id, pack.id)
        else:
            await repo.decrement_stickers_count(pack.id)

        title_esc = html.escape(pack.title)
        await callback.message.edit_text(
            f"🗑 <b>Стикер успешно удален из пака «{title_esc}».</b>",
            parse_mode="HTML"
        )
        await callback.answer("Удалено!")
    else:
        await callback.answer("❌ Ошибка удаления стикера из Telegram.", show_alert=True)


@router.callback_query(F.data.startswith("stk_copy:"))
async def callback_stk_copy_menu(callback: CallbackQuery, repo: Repository):
    token = callback.data.split(":")[1]
    sess = ACTION_SESSIONS.get(token)
    if not sess:
        await callback.answer("Сессия действия устарела.", show_alert=True)
        return

    fmt = sess["format"]
    user_packs = await repo.get_user_packs(callback.from_user.id, format_=fmt)
    if not user_packs:
        await callback.answer(f"У вас нет других {fmt}-паков.", show_alert=True)
        return

    buttons = []
    for p in user_packs:
        buttons.append([
            InlineKeyboardButton(
                text=f"{p.title} ({p.stickers_count} шт)",
                callback_data=f"stk_add_to:{token}:{p.id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_action")])

    await callback.message.edit_text(
        "📂 <b>Выберите пак, в который хотите скопировать этот стикер:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stk_add_act:"))
async def callback_stk_add_active(callback: CallbackQuery, bot: Bot, repo: Repository, user: User):
    token = callback.data.split(":")[1]
    sess = ACTION_SESSIONS.get(token)
    if not sess:
        await callback.answer("Сессия действия устарела.", show_alert=True)
        return

    if not user.active_pack_id:
        await callback.answer("У вас нет активного пака.", show_alert=True)
        return

    pack = await repo.get_pack(user.active_pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("Активный пак не найден или нет прав.", show_alert=True)
        return

    await do_add_sticker_to_pack(callback, bot, repo, pack, sess["file_id"], sess["emoji"], sess.get("format", "static"))


@router.callback_query(F.data.startswith("stk_add_to:"))
async def callback_stk_add_to_specific(callback: CallbackQuery, bot: Bot, repo: Repository):
    parts = callback.data.split(":")
    token = parts[1]
    pack_id = int(parts[2])

    sess = ACTION_SESSIONS.get(token)
    if not sess:
        await callback.answer("Сессия действия устарела.", show_alert=True)
        return

    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("Пак не найден или нет прав.", show_alert=True)
        return

    await do_add_sticker_to_pack(callback, bot, repo, pack, sess["file_id"], sess["emoji"], sess.get("format", "static"))


async def do_add_sticker_to_pack(
    callback: CallbackQuery,
    bot: Bot,
    repo: Repository,
    pack: StickerPack,
    file_id: str,
    emoji: str,
    media_format: str = "static"
):
    sticker_service = StickerService(bot)
    try:
        valid_fmt = "video" if media_format == "video" else "static"
        await sticker_service.add_sticker(
            user_id=callback.from_user.id,
            name=pack.name,
            sticker_data=file_id,
            format_=valid_fmt,
            emojis=[emoji]
        )

        set_info = await sticker_service.get_pack_info(pack.name)
        new_fid = set_info.stickers[-1].file_id if set_info and set_info.stickers else file_id
        new_uid = set_info.stickers[-1].file_unique_id if set_info and set_info.stickers else "uid"

        await repo.add_sticker(pack.id, new_fid, new_uid, emoji)

        # Send sticker message to force client cache invalidation
        try:
            await bot.send_sticker(chat_id=callback.message.chat.id, sticker=new_fid)
        except Exception as e:
            logger.warning("Could not send added sticker preview: %s", e)

        title_esc = html.escape(pack.title)
        pack_url = format_pack_link(pack.name)
        await callback.message.edit_text(
            f"✅ <b>Стикер успешно добавлен в пак «{title_esc}»!</b>\n\n"
            f"🎯 <b>Эмодзи:</b> {emoji}\n"
            f"🔗 <a href=\"{pack_url}\">Открыть пак в Telegram</a>",
            parse_mode="HTML"
        )
        await callback.answer("Стикер добавлен!")
    except Exception as e:
        logger.error("Error adding sticker to pack: %s", e)
        await callback.answer(f"❌ Ошибка добавления: {e}", show_alert=True)


@router.callback_query(F.data.startswith("stk_clone:"))
async def callback_stk_clone(callback: CallbackQuery, bot: Bot, repo: Repository, user: User, state: FSMContext):
    token = callback.data.split(":")[1]
    sess = ACTION_SESSIONS.get(token)
    if not sess or not sess.get("set_name"):
        await callback.answer("Сессия действия устарела.", show_alert=True)
        return

    from bot.handlers.pack_import import handle_pack_lookup
    await handle_pack_lookup(sess["set_name"], callback.message, state, bot, repo, user)
    await callback.answer()
