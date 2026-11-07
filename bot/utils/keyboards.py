from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from bot.database.models import StickerPack, User
from bot.utils.helpers import format_pack_link


def get_main_reply_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🎨 Создать пак"), KeyboardButton(text="📥 Импорт пака")],
        [KeyboardButton(text="📂 Мои паки"), KeyboardButton(text="⚙️ Настройки")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="ℹ️ Помощь"), KeyboardButton(text="👑 Админ-панель")])
    else:
        rows.append([KeyboardButton(text="ℹ️ Помощь")])

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def get_pack_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🖼 Статические (Фото/PNG)", callback_data="pack_type:regular:static")
            ],
            [
                InlineKeyboardButton(text="🎬 Видеостикеры (GIF/MP4)", callback_data="pack_type:regular:video")
            ],
            [
                InlineKeyboardButton(text="⭐️ Custom Emoji (Static)", callback_data="pack_type:custom_emoji:static"),
                InlineKeyboardButton(text="⭐️ Custom Emoji (Video)", callback_data="pack_type:custom_emoji:video")
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")
            ]
        ]
    )


def get_random_name_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Сгенерировать имя автоматически", callback_data="auto_pack_name")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
        ]
    )


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
        ]
    )


def get_packs_list_keyboard(packs: list[StickerPack], active_pack_id: int | None) -> InlineKeyboardMarkup:
    buttons = []
    for pack in packs:
        is_active = (pack.id == active_pack_id)
        icon = "📌 " if is_active else ("🎬 " if pack.format == "video" else "🖼 ")
        star = " ⭐️" if pack.sticker_type == "custom_emoji" else ""
        text = f"{icon}{pack.title}{star} ({pack.stickers_count} шт.)"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"view_pack:{pack.id}")])

    buttons.append([
        InlineKeyboardButton(text="🎨 Создать новый пак", callback_data="create_new_pack")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_pack_details_keyboard(pack: StickerPack, is_active: bool) -> InlineKeyboardMarkup:
    pack_url = format_pack_link(pack.name)
    buttons = []

    # First row: Link and Activate
    row1 = [InlineKeyboardButton(text="🔗 Открыть в Telegram", url=pack_url)]
    if not is_active:
        row1.append(InlineKeyboardButton(text="📌 Сделать активным", callback_data=f"activate_pack:{pack.id}"))
    buttons.append(row1)

    # Second row: Edit options
    buttons.append([
        InlineKeyboardButton(text="🖼 Установить иконку", callback_data=f"set_thumb:{pack.id}"),
        InlineKeyboardButton(text="✏️ Название", callback_data=f"edit_title:{pack.id}")
    ])

    # Third row: Delete last sticker or full pack
    buttons.append([
        InlineKeyboardButton(text="🗑 Удалить последний стикер", callback_data=f"del_last_sticker:{pack.id}")
    ])
    buttons.append([
        InlineKeyboardButton(text="❌ Удалить пак", callback_data=f"confirm_del_pack:{pack.id}")
    ])

    # Back
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад к списку", callback_data="back_to_packs")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_sticker_added_keyboard(
    pack: StickerPack,
    sticker_file_id: str | None = None,
    source_set_name: str | None = None
) -> InlineKeyboardMarkup:
    pack_url = format_pack_link(pack.name)
    buttons = [
        [
            InlineKeyboardButton(text="🔗 Открыть пак", url=pack_url),
            InlineKeyboardButton(text="🗑 Удалить этот стикер", callback_data=f"del_last_sticker:{pack.id}")
        ]
    ]

    if source_set_name and not source_set_name.endswith(f"_by_{pack.name.split('_by_')[-1]}"):
        buttons.append([
            InlineKeyboardButton(text="📥 Клонировать весь этот пак", callback_data=f"clone_source:{source_set_name}")
        ])

    buttons.append([
        InlineKeyboardButton(text="📂 Все мои паки", callback_data="back_to_packs")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_confirm_import_keyboard(pack_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Клонировать для редактирования", callback_data=f"do_clone_pack:{pack_name}")
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")
            ]
        ]
    )


def get_settings_keyboard(user: User) -> InlineKeyboardMarkup:
    quick_status = "ВКЛ ⚡️" if user.settings_quick_mode else "ВЫКЛ ⏸"
    outline_status = "ВКЛ ✨" if user.settings_auto_outline else "ВЫКЛ ⚪️"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Быстрый режим: {quick_status}",
                    callback_data="toggle_quick_mode"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"Белая обводка: {outline_status}",
                    callback_data="toggle_outline"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"Эмодзи по умолчанию: {user.settings_default_emoji}",
                    callback_data="change_default_emoji"
                )
            ],
            [
                InlineKeyboardButton(text="◀️ Закрыть", callback_data="close_settings")
            ]
        ]
    )


def get_interactive_preview_keyboard(
    pack_id: int,
    temp_id: str,
    outline_enabled: bool,
    emoji: str
) -> InlineKeyboardMarkup:
    outline_text = "✨ Обводка: ВКЛ" if outline_enabled else "⚪️ Обводка: ВЫКЛ"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=outline_text, callback_data=f"preview_toggle_outline:{temp_id}"),
                InlineKeyboardButton(text=f"🎯 Эмодзи: {emoji}", callback_data=f"preview_change_emoji:{temp_id}")
            ],
            [
                InlineKeyboardButton(text="💬 Добавить текст", callback_data=f"preview_add_text:{temp_id}")
            ],
            [
                InlineKeyboardButton(text="✅ Добавить в пак", callback_data=f"preview_confirm_add:{temp_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"preview_cancel:{temp_id}")
            ]
        ]
    )
