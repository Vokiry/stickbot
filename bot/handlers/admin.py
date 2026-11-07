import html
import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import settings
from bot.database.models import User
from bot.database.repository import Repository
from bot.services.sticker_service import StickerService
from bot.utils.helpers import format_pack_link, generate_random_pack_name
from bot.utils.keyboards import get_cancel_keyboard

logger = logging.getLogger(__name__)

router = Router(name="admin")


class AdminSearchSG(StatesGroup):
    waiting_for_query = State()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


@router.message(Command("admin"))
@router.message(F.text == "👑 Админ-панель")
async def cmd_admin_panel(message: Message, repo: Repository):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ У вас нет прав администратора.")
        return

    stats = await repo.get_stats()

    text = (
        f"👑 <b>Панель администратора StickBot</b>\n\n"
        f"📊 <b>Статистика системы:</b>\n"
        f"• Пользователей: <b>{stats['users_count']}</b>\n"
        f"• Активных стикерпаков: <b>{stats['packs_count']}</b>\n"
        f"• Всего стикеров в базе: <b>{stats['stickers_count']}</b>\n\n"
        f"Выберите действие для управления:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Все стикерпаки пользователей", callback_data="admin_packs:0")],
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="admin_users:0")],
        [InlineKeyboardButton(text="🔍 Найти пак по ссылке или названию", callback_data="admin_search_pack")],
        [InlineKeyboardButton(text="◀️ Закрыть", callback_data="admin_close")]
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "admin_menu")
async def callback_admin_menu(callback: CallbackQuery, repo: Repository):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Доступ запрещен.", show_alert=True)
        return

    stats = await repo.get_stats()
    text = (
        f"👑 <b>Панель администратора StickBot</b>\n\n"
        f"📊 <b>Статистика системы:</b>\n"
        f"• Пользователей: <b>{stats['users_count']}</b>\n"
        f"• Активных стикерпаков: <b>{stats['packs_count']}</b>\n"
        f"• Всего стикеров в базе: <b>{stats['stickers_count']}</b>\n\n"
        f"Выберите действие для управления:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Все стикерпаки пользователей", callback_data="admin_packs:0")],
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="admin_users:0")],
        [InlineKeyboardButton(text="🔍 Найти пак по ссылке или названию", callback_data="admin_search_pack")],
        [InlineKeyboardButton(text="◀️ Закрыть", callback_data="admin_close")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_packs:"))
async def callback_admin_packs(callback: CallbackQuery, repo: Repository):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Доступ запрещен.", show_alert=True)
        return

    offset = int(callback.data.split(":")[1])
    limit = 8
    items = await repo.get_all_packs(limit=limit, offset=offset)

    if not items and offset == 0:
        await callback.message.edit_text(
            "📂 В базе пока нет созданных паков.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
            ])
        )
        return

    buttons = []
    for item in items:
        p = item["pack"]
        owner = f"@{item['owner_username']}" if item["owner_username"] else f"ID:{p.user_id}"
        fmt_icon = "🎬 " if p.format == "video" else "🖼 "
        btn_text = f"{fmt_icon}{p.title} ({p.stickers_count} шт) | {owner}"
        buttons.append([InlineKeyboardButton(text=btn_text[:40], callback_data=f"admin_view_pack:{p.id}")])

    # Pagination row
    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_packs:{max(0, offset - limit)}"))
    if len(items) == limit:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"admin_packs:{offset + limit}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(text="◀️ В админ-меню", callback_data="admin_menu")])

    await callback.message.edit_text(
        f"📦 <b>Все стикерпаки пользователей (страница {offset // limit + 1}):</b>\n"
        f"Нажмите на пак, чтобы управлять им (своровать, удалить, изменить):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_view_pack:"))
async def callback_admin_view_pack(callback: CallbackQuery, repo: Repository):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Доступ запрещен.", show_alert=True)
        return

    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack:
        await callback.answer("⚠️ Пак не найден.", show_alert=True)
        return

    owner = await repo.get_user(pack.user_id)
    owner_str = f"@{owner.username}" if owner and owner.username else f"ID: <code>{pack.user_id}</code>"
    owner_name = owner.first_name if owner else "Неизвестно"

    title_esc = html.escape(pack.title)
    pack_name_esc = html.escape(pack.name)
    pack_url = format_pack_link(pack.name)
    type_str = "⭐️ Custom Emoji" if pack.sticker_type == "custom_emoji" else (
        "🔀 Смешанный (видео + фото)" if pack.format == "mixed" else (
            "🎬 Видео" if pack.format == "video" else "🖼 Статика"
        )
    )

    text = (
        f"👑 <b>Управление чужим паком (Админ-режим)</b>\n\n"
        f"📦 <b>Название:</b> {title_esc}\n"
        f"👤 <b>Владелец:</b> {owner_name} ({owner_str})\n"
        f"• <b>Тип:</b> {type_str}\n"
        f"• <b>Стикеров:</b> {pack.stickers_count} шт.\n"
        f"• <b>Адрес:</b> <code>{pack_name_esc}</code>\n"
        f"• <b>Ссылка:</b> {pack_url}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Открыть в Telegram", url=pack_url)],
        [InlineKeyboardButton(text="🥷 Своровать / Склонировать себе", callback_data=f"admin_steal_pack:{pack.id}")],
        [
            InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"edit_title:{pack.id}"),
            InlineKeyboardButton(text="🖼 Обложка", callback_data=f"set_thumb:{pack.id}")
        ],
        [InlineKeyboardButton(text="🗑 Удалить последний стикер", callback_data=f"del_last_sticker:{pack.id}")],
        [InlineKeyboardButton(text="❌ Удалить пак навсегда", callback_data=f"confirm_del_pack:{pack.id}")],
        [InlineKeyboardButton(text="◀️ Назад ко всем пакам", callback_data="admin_packs:0")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_steal_pack:"))
async def callback_admin_steal_pack(callback: CallbackQuery, bot: Bot, repo: Repository):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Доступ запрещен.", show_alert=True)
        return

    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack:
        await callback.answer("⚠️ Пак не найден.", show_alert=True)
        return

    # Trigger clone flow for admin
    from bot.handlers.pack_import import handle_pack_lookup
    # Simulate lookup and prompt clone for this pack
    await callback.message.answer(
        f"🥷 <b>Клонирование пака в вашу личную коллекцию:</b>\n"
        f"Нажмите кнопку ниже, чтобы скопировать все стикеры пака «{html.escape(pack.title)}» в ваш личный активный набор:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Скопировать себе", callback_data=f"do_clone_pack:{pack.name}")],
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_menu")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer("Готово к клонированию!")


@router.callback_query(F.data.startswith("admin_users:"))
async def callback_admin_users(callback: CallbackQuery, repo: Repository):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Доступ запрещен.", show_alert=True)
        return

    offset = int(callback.data.split(":")[1])
    limit = 10
    users_data = await repo.get_all_users(limit=limit, offset=offset)

    buttons = []
    text_lines = [f"👥 <b>Пользователи бота (стр. {offset // limit + 1}):</b>\n"]

    for row in users_data:
        u = row["user"]
        uname = f"@{u.username}" if u.username else "без username"
        fname = html.escape(u.first_name or "Пользователь")
        text_lines.append(f"• <b>{fname}</b> ({uname}) — ID: <code>{u.telegram_id}</code> | Паков: {row['packs_count']}")

    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_users:{max(0, offset - limit)}"))
    if len(users_data) == limit:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"admin_users:{offset + limit}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(text="◀️ В админ-меню", callback_data="admin_menu")])

    await callback.message.edit_text(
        "\n".join(text_lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_search_pack")
async def callback_admin_search_pack(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Доступ запрещен.", show_alert=True)
        return

    await state.set_state(AdminSearchSG.waiting_for_query)
    await callback.message.edit_text(
        "🔍 Отправьте <b>ссылку на стикерпак</b> или <b>название / slug</b> для поиска и управления:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminSearchSG.waiting_for_query, F.text)
async def process_admin_search(message: Message, state: FSMContext, repo: Repository, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    from bot.utils.helpers import extract_pack_name_from_text
    query = extract_pack_name_from_text(message.text) or message.text.strip()
    await state.clear()

    # Search in DB first
    pack = await repo.get_pack_by_name(query)
    if pack:
        # Show pack in admin view
        owner = await repo.get_user(pack.user_id)
        owner_str = f"@{owner.username}" if owner and owner.username else f"ID: {pack.user_id}"
        pack_url = format_pack_link(pack.name)

        text = (
            f"👑 <b>Найден пак в базе данных:</b>\n\n"
            f"📦 <b>Название:</b> {html.escape(pack.title)}\n"
            f"👤 <b>Владелец:</b> {owner_str}\n"
            f"• <b>Стикеров:</b> {pack.stickers_count} шт.\n"
            f"• <b>Адрес:</b> <code>{html.escape(pack.name)}</code>\n"
            f"• <b>Ссылка:</b> {pack_url}"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Открыть в Telegram", url=pack_url)],
            [InlineKeyboardButton(text="🥷 Своровать / Клонировать себе", callback_data=f"admin_steal_pack:{pack.id}")],
            [
                InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"edit_title:{pack.id}"),
                InlineKeyboardButton(text="🖼 Обложка", callback_data=f"set_thumb:{pack.id}")
            ],
            [InlineKeyboardButton(text="🗑 Удалить последний стикер", callback_data=f"del_last_sticker:{pack.id}")],
            [InlineKeyboardButton(text="❌ Удалить пак навсегда", callback_data=f"confirm_del_pack:{pack.id}")],
            [InlineKeyboardButton(text="◀️ В админ-меню", callback_data="admin_menu")]
        ])

        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        return

    # If not in DB, search via Telegram API
    sticker_service = StickerService(bot)
    set_info = await sticker_service.get_pack_info(query)
    if set_info:
        from bot.handlers.pack_import import handle_pack_lookup
        await handle_pack_lookup(query, message, state, bot, repo, await repo.get_or_create_user(message.from_user.id))
    else:
        await message.answer(
            f"⚠️ Стикерпак «{html.escape(query)}» не найден ни в локальной базе, ни в Telegram.",
            parse_mode="HTML"
        )


@router.callback_query(F.data == "admin_close")
async def callback_admin_close(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()
