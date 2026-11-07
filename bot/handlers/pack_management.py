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
    active_title = active_pack.title if active_pack else "Не выбран"

    await message.answer(
        f"📂 **Ваши стикерпаки:**\n\n"
        f"📌 **Текущий активный пак:** {active_title}\n"
        f"_(В него автоматически добавляются новые стикеры)_\n\n"
        f"Выберите пак для управления:",
        reply_markup=get_packs_list_keyboard(packs, user.active_pack_id),
        parse_mode="Markdown"
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
    active_title = active_pack.title if active_pack else "Не выбран"

    await callback.message.edit_text(
        f"📂 **Ваши стикерпаки:**\n\n"
        f"📌 **Текущий активный пак:** {active_title}\n"
        f"_(В него автоматически добавляются новые стикеры)_\n\n"
        f"Выберите пак для управления:",
        reply_markup=get_packs_list_keyboard(packs, user.active_pack_id),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("view_pack:"))
async def callback_view_pack(callback: CallbackQuery, repo: Repository, user: User):
    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack:
        await callback.answer("⚠️ Пак не найден или был удален.", show_alert=True)
        return

    is_active = (user.active_pack_id == pack.id)
    status_str = "✅ Активен (новые стикеры идут сюда)" if is_active else "⏸ Не активен"
    type_str = "⭐️ Custom Emoji" if pack.sticker_type == "custom_emoji" else (
        "🎬 Видео" if pack.format == "video" else "🖼 Статика"
    )

    text = (
        f"📦 **Стикерпак:** {pack.title}\n\n"
        f"• **Статус:** {status_str}\n"
        f"• **Тип:** {type_str}\n"
        f"• **Количество стикеров:** {pack.stickers_count} шт.\n"
        f"• **Адрес:** `{pack.name}`\n"
        f"• **Ссылка:** {format_pack_link(pack.name)}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_pack_details_keyboard(pack, is_active),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("activate_pack:"))
async def callback_activate_pack(callback: CallbackQuery, repo: Repository, user: User):
    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack:
        await callback.answer("⚠️ Пак не найден.", show_alert=True)
        return

    await repo.set_active_pack(callback.from_user.id, pack.id)
    await callback.answer(f"📌 Пак «{pack.title}» теперь активен!", show_alert=False)

    # Refresh details
    type_str = "⭐️ Custom Emoji" if pack.sticker_type == "custom_emoji" else (
        "🎬 Видео" if pack.format == "video" else "🖼 Статика"
    )
    text = (
        f"📦 **Стикерпак:** {pack.title}\n\n"
        f"• **Статус:** ✅ Активен (новые стикеры идут сюда)\n"
        f"• **Тип:** {type_str}\n"
        f"• **Количество стикеров:** {pack.stickers_count} шт.\n"
        f"• **Адрес:** `{pack.name}`\n"
        f"• **Ссылка:** {format_pack_link(pack.name)}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_pack_details_keyboard(pack, is_active=True),
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("del_last_sticker:"))
async def callback_del_last_sticker(callback: CallbackQuery, repo: Repository, bot: Bot):
    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack:
        await callback.answer("⚠️ Пак не найден.", show_alert=True)
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
            type_str = "⭐️ Custom Emoji" if updated_pack.sticker_type == "custom_emoji" else (
                "🎬 Видео" if updated_pack.format == "video" else "🖼 Статика"
            )
            text = (
                f"📦 **Стикерпак:** {updated_pack.title}\n\n"
                f"• **Тип:** {type_str}\n"
                f"• **Количество стикеров:** {updated_pack.stickers_count} шт.\n"
                f"• **Адрес:** `{updated_pack.name}`\n"
                f"• **Ссылка:** {format_pack_link(updated_pack.name)}"
            )
            await callback.message.edit_text(
                text,
                reply_markup=get_pack_details_keyboard(updated_pack, is_active=is_active),
                parse_mode="Markdown"
            )
    else:
        await callback.answer("❌ Не удалось удалить стикер из Telegram.", show_alert=True)


@router.callback_query(F.data.startswith("confirm_del_pack:"))
async def callback_confirm_del_pack(callback: CallbackQuery, repo: Repository):
    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack:
        await callback.answer("⚠️ Пак не найден.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ Да, удалить пак навсегда", callback_data=f"do_del_pack:{pack.id}")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"view_pack:{pack.id}")]
    ])

    await callback.message.edit_text(
        f"⚠️ **Вы уверены, что хотите удалить пак «{pack.title}»?**\n\n"
        f"Это действие необратимо. Набор будет удален из Telegram и из бота.",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("do_del_pack:"))
async def callback_do_del_pack(callback: CallbackQuery, repo: Repository, bot: Bot):
    pack_id = int(callback.data.split(":")[1])
    pack = await repo.get_pack(pack_id)
    if not pack:
        await callback.answer("⚠️ Пак уже удален.", show_alert=True)
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
        "📂 **Ваши стикерпаки:**",
        reply_markup=get_packs_list_keyboard(packs, None)
    )


@router.callback_query(F.data.startswith("edit_title:"))
async def callback_edit_title(callback: CallbackQuery, state: FSMContext):
    pack_id = int(callback.data.split(":")[1])
    await state.update_data(edit_pack_id=pack_id)
    await state.set_state(EditTitleSG.enter_new_title)

    await callback.message.edit_text(
        "✏️ Введите **новое название** для стикерпака:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
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
    await repo.update_pack_title(pack_id, new_title)
    await state.clear()

    pack = await repo.get_pack(pack_id)
    await message.answer(
        f"✅ Название пака изменено на: **{new_title}**",
        reply_markup=get_pack_details_keyboard(pack, is_active=True) if pack else None,
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("set_thumb:"))
async def callback_set_thumb(callback: CallbackQuery, state: FSMContext):
    pack_id = int(callback.data.split(":")[1])
    await state.update_data(thumb_pack_id=pack_id)
    await state.set_state(SetThumbSG.send_thumb)

    await callback.message.edit_text(
        "🖼 Отправьте **изображение (или короткое видео)**, которое станет иконкой (обложкой) этого стикерпака:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(SetThumbSG.send_thumb)
async def process_set_thumb(message: Message, state: FSMContext, repo: Repository, bot: Bot):
    data = await state.get_data()
    pack_id = data["thumb_pack_id"]
    pack = await repo.get_pack(pack_id)
    if not pack:
        await state.clear()
        await message.answer("⚠️ Пак не найден.")
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
        await status_msg.edit_text(f"🎉 Иконка пака «{pack.title}» успешно обновлена!")

    except Exception as e:
        logger.exception("Error setting thumbnail: %s", e)
        await status_msg.edit_text(f"❌ Не удалось установить обложку: {e}")
