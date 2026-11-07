import html
import io
import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from bot.config import settings
from bot.database.models import User, StickerPack
from bot.database.repository import Repository
from bot.services.sticker_service import StickerService
from bot.services.image_processor import process_image
from bot.services.video_processor import process_video
from bot.utils.helpers import format_pack_link
from bot.utils.keyboards import (
    get_packs_list_keyboard,
    get_pack_details_keyboard,
    get_cancel_keyboard
)

logger = logging.getLogger(__name__)

router = Router(name="pack_management")


class EditTitleSG(StatesGroup):
    enter_new_title = State()


class SetThumbSG(StatesGroup):
    send_thumb = State()


def is_authorized(user_id: int, pack_owner_id: int) -> bool:
    """Checks if user is owner of the pack or superadmin."""
    return user_id == pack_owner_id or user_id in settings.admin_ids


def render_pack_details_html(pack: StickerPack, is_active: bool) -> str:
    title_esc = html.escape(pack.title)
    pack_name_esc = html.escape(pack.name)
    pack_url = format_pack_link(pack.name)

    status_str = "✅ Активен (новые стикеры идут сюда)" if is_active else "⏸ Не активен"
    type_str = "⭐️ Custom Emoji" if pack.sticker_type == "custom_emoji" else (
        "🔀 Смешанный (видео + фото)" if pack.format == "mixed" else (
            "🎬 Видео" if pack.format == "video" else "🖼 Статика"
        )
    )

    return (
        f"📦 <b>Стикерпак:</b> {title_esc}\n\n"
        f"• <b>Статус:</b> {status_str}\n"
        f"• <b>Тип:</b> {type_str}\n"
        f"• <b>Количество стикеров:</b> {pack.stickers_count} шт.\n"
        f"• <b>Адрес:</b> <code>{pack_name_esc}</code>\n"
        f"• <b>Ссылка:</b> {pack_url}"
    )


@router.message(Command("packs"))
@router.message(F.text == "📂 Мои паки")
async def show_user_packs(message: Message, repo: Repository, user: User, state: FSMContext):
    await state.clear()
    packs = await repo.get_user_packs(message.from_user.id)
    if not packs:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Создать первый пак", callback_data="create_new_pack")]
        ])
        await message.answer(
            "📂 У вас пока нет созданных стикерпаков.\n\n"
            "Нажмите кнопку ниже, чтобы создать свой первый набор!",
            reply_markup=keyboard
        )
        return

    active_pack = await repo.get_pack(user.active_pack_id) if user.active_pack_id else None
    active_title = html.escape(active_pack.title) if active_pack else "Не выбран"

    await message.answer(
        f"📂 <b>Ваши стикерпаки:</b>\n\n"
        f"📌 <b>Текущий активный пак:</b> {active_title}\n"
        f"<i>(В него автоматически добавляются новые стикеры)</i>\n\n"
        f"Выберите пак для управления:",
        reply_markup=get_packs_list_keyboard(packs, user.active_pack_id),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "back_to_packs")
async def callback_back_to_packs(callback: CallbackQuery, repo: Repository, user: User, state: FSMContext):
    await state.clear()
    packs = await repo.get_user_packs(callback.from_user.id)
    if not packs:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Создать первый пак", callback_data="create_new_pack")]
        ])
        await callback.message.edit_text(
            "📂 У вас пока нет созданных стикерпаков.\n\n"
            "Нажмите кнопку ниже, чтобы создать свой первый набор!",
            reply_markup=keyboard
        )
        return

    active_pack = await repo.get_pack(user.active_pack_id) if user.active_pack_id else None
    active_title = html.escape(active_pack.title) if active_pack else "Не выбран"

    await callback.message.edit_text(
        f"📂 <b>Ваши стикерпаки:</b>\n\n"
        f"📌 <b>Текущий активный пак:</b> {active_title}\n"
        f"<i>(В него автоматически добавляются новые стикеры)</i>\n\n"
        f"Выберите пак для управления:",
        reply_markup=get_packs_list_keyboard(packs, user.active_pack_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("view_pack:"))
async def callback_view_pack(callback: CallbackQuery, repo: Repository, user: User):
    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    is_active = (user.active_pack_id == pack.id)
    text = render_pack_details_html(pack, is_active)

    await callback.message.edit_text(
        text,
        reply_markup=get_pack_details_keyboard(pack, is_active),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("activate_pack:"))
async def callback_activate_pack(callback: CallbackQuery, repo: Repository, user: User):
    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    await repo.set_active_pack(callback.from_user.id, pack.id)
    await callback.answer(f"📌 Пак «{pack.title}» теперь активен!", show_alert=False)

    text = render_pack_details_html(pack, is_active=True)
    await callback.message.edit_text(
        text,
        reply_markup=get_pack_details_keyboard(pack, is_active=True),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("del_last_sticker:"))
async def callback_del_last_sticker(callback: CallbackQuery, repo: Repository, bot: Bot):
    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    sticker = await repo.get_last_sticker(pack_id)
    if not sticker:
        await callback.answer("В этом паке нет стикеров для удаления.", show_alert=True)
        return

    sticker_service = StickerService(bot)
    success = await sticker_service.delete_sticker(sticker.file_id)
    if success:
        await repo.delete_sticker(sticker.id, pack_id)
        await callback.answer("🗑 Последний стикер успешно удален из пака!", show_alert=True)
        # Update view
        updated_pack = await repo.get_pack(pack_id)
        if updated_pack:
            is_active = (callback.from_user.id == updated_pack.user_id)
            text = render_pack_details_html(updated_pack, is_active)
            await callback.message.edit_text(
                text,
                reply_markup=get_pack_details_keyboard(updated_pack, is_active=is_active),
                parse_mode="HTML"
            )
    else:
        await callback.answer("❌ Не удалось удалить стикер из Telegram.", show_alert=True)


@router.callback_query(F.data.startswith("confirm_del_pack:"))
async def callback_confirm_del_pack(callback: CallbackQuery, repo: Repository):
    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ Да, удалить пак навсегда", callback_data=f"do_del_pack:{pack.id}")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"view_pack:{pack.id}")]
    ])

    title_esc = html.escape(pack.title)
    await callback.message.edit_text(
        f"⚠️ <b>Вы уверены, что хотите удалить пак «{title_esc}»?</b>\n\n"
        f"Это действие необратимо. Набор будет удален из Telegram и из бота.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("do_del_pack:"))
async def callback_do_del_pack(callback: CallbackQuery, repo: Repository, bot: Bot):
    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return

    sticker_service = StickerService(bot)
    try:
        await sticker_service.delete_pack(pack.name)
    except Exception as e:
        logger.warning("Telegram delete pack warning: %s", e)

    await repo.delete_pack(pack.id)
    await callback.answer("✅ Стикерпак успешно удален!", show_alert=True)

    # Return to packs list
    packs = await repo.get_user_packs(callback.from_user.id)
    await callback.message.edit_text(
        "📂 <b>Ваши стикерпаки:</b>",
        reply_markup=get_packs_list_keyboard(packs, None),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("edit_title:"))
async def callback_edit_title(callback: CallbackQuery, state: FSMContext, repo: Repository):
    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return
    await state.update_data(edit_pack_id=pack_id)
    await state.set_state(EditTitleSG.enter_new_title)

    await callback.message.edit_text(
        "✏️ Введите <b>новое название</b> для стикерпака:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditTitleSG.enter_new_title, F.text)
async def process_new_title(message: Message, state: FSMContext, repo: Repository):
    new_title = message.text.strip()
    if len(new_title) > 64:
        await message.answer("⚠️ Название не должно превышать 64 символа. Попробуйте еще раз:")
        return

    data = await state.get_data()
    pack_id = data["edit_pack_id"]
    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(message.from_user.id, pack.user_id):
        await state.clear()
        await message.answer("⚠️ Пак не найден или у вас нет прав.")
        return

    await repo.update_pack_title(pack_id, new_title)
    await state.clear()

    updated_pack = await repo.get_pack(pack_id)
    new_title_esc = html.escape(new_title)
    await message.answer(
        f"✅ Название пака изменено на: <b>{new_title_esc}</b>",
        reply_markup=get_pack_details_keyboard(updated_pack, is_active=True) if updated_pack else None,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("set_thumb:"))
async def callback_set_thumb(callback: CallbackQuery, state: FSMContext, repo: Repository):
    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(callback.from_user.id, pack.user_id):
        await callback.answer("⚠️ Пак не найден или у вас нет прав.", show_alert=True)
        return
    await state.update_data(thumb_pack_id=pack_id)
    await state.set_state(SetThumbSG.send_thumb)

    await callback.message.edit_text(
        "🖼 Отправьте <b>изображение (или короткое видео)</b>, которое станет иконкой этого стикерпака:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(SetThumbSG.send_thumb)
async def process_set_thumb(message: Message, state: FSMContext, repo: Repository, bot: Bot):
    data = await state.get_data()
    pack_id = data["thumb_pack_id"]
    pack = await repo.get_pack(pack_id)
    if not pack or not is_authorized(message.from_user.id, pack.user_id):
        await state.clear()
        await message.answer("⚠️ Пак не найден или у вас нет прав.")
        return

    status_msg = await message.answer("⏳ Обновляю иконку стикерпака...")

    try:
        sticker_service = StickerService(bot)
        if pack.format == "static":
            file_id = message.photo[-1].file_id if message.photo else (
                message.document.file_id if message.document else None
            )
            if not file_id:
                await status_msg.edit_text("⚠️ Ожидалось фото или картинка. Попробуйте еще раз:")
                return

            file_info = await bot.get_file(file_id)
            if file_info.file_size and file_info.file_size > 25 * 1024 * 1024:
                await status_msg.edit_text("⚠️ Файл слишком большой (максимум 25 МБ).")
                return

            buf = io.BytesIO()
            await bot.download_file(file_info.file_path, buf)
            processed_bytes = process_image(buf.getvalue(), add_outline=False)

            await sticker_service.set_pack_thumbnail(
                user_id=message.from_user.id,
                name=pack.name,
                thumbnail_data=processed_bytes,
                format_="static"
            )
        else:
            file_id = message.video.file_id if message.video else (
                message.animation.file_id if message.animation else None
            )
            if not file_id:
                await status_msg.edit_text("⚠️ Ожидалось видео или GIF. Попробуйте еще раз:")
                return

            file_info = await bot.get_file(file_id)
            if file_info.file_size and file_info.file_size > 25 * 1024 * 1024:
                await status_msg.edit_text("⚠️ Файл слишком большой (максимум 25 МБ).")
                return

            buf = io.BytesIO()
            await bot.download_file(file_info.file_path, buf)
            processed_bytes = await process_video(buf.getvalue(), temp_dir=settings.TEMP_DIR)

            await sticker_service.set_pack_thumbnail(
                user_id=message.from_user.id,
                name=pack.name,
                thumbnail_data=processed_bytes,
                format_="video"
            )

        await state.clear()
        title_esc = html.escape(pack.title)
        await status_msg.edit_text(
            f"🎉 Иконка пака «{title_esc}» успешно обновлена!",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.exception("Error setting thumbnail: %s", e)
        await status_msg.edit_text(f"❌ Не удалось установить обложку: {e}")
