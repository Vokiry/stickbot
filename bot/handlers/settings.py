import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from bot.database.models import User
from bot.database.repository import Repository
from bot.utils.helpers import extract_emojis
from bot.utils.keyboards import get_settings_keyboard, get_cancel_keyboard

logger = logging.getLogger(__name__)

router = Router(name="settings")


class EmojiSettingSG(StatesGroup):
    enter_new_emoji = State()


@router.message(Command("settings"))
@router.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message, user: User, state: FSMContext):
    await state.clear()
    await message.answer(
        "⚙️ **Настройки бота**\n\n"
        "• **Быстрый режим**: мгновенное добавление присланных картинок в пак без диалога предпросмотра.\n"
        "• **Белая обводка**: автоматическое создание аккуратного белого контура вокруг вырезанных прозрачных картинок.\n"
        "• **Эмодзи по умолчанию**: используется, если вы не указали свой эмодзи в описании фото.",
        reply_markup=get_settings_keyboard(user),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "toggle_quick_mode")
async def callback_toggle_quick_mode(callback: CallbackQuery, repo: Repository, user: User):
    new_val = not user.settings_quick_mode
    await repo.update_settings(user.telegram_id, quick_mode=new_val)
    user.settings_quick_mode = new_val
    await callback.message.edit_reply_markup(reply_markup=get_settings_keyboard(user))
    status_text = "включен ⚡️" if new_val else "выключен ⏸"
    await callback.answer(f"Быстрый режим {status_text}")


@router.callback_query(F.data == "toggle_outline")
async def callback_toggle_outline(callback: CallbackQuery, repo: Repository, user: User):
    new_val = not user.settings_auto_outline
    await repo.update_settings(user.telegram_id, auto_outline=new_val)
    user.settings_auto_outline = new_val
    await callback.message.edit_reply_markup(reply_markup=get_settings_keyboard(user))
    status_text = "включена ✨" if new_val else "выключена ⚪️"
    await callback.answer(f"Авто-обводка {status_text}")


@router.callback_query(F.data == "change_default_emoji")
async def callback_change_default_emoji(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EmojiSettingSG.enter_new_emoji)
    await callback.message.edit_text(
        "🎯 Отправьте **один эмодзи**, который будет использоваться по умолчанию при создании стикеров:\n"
        "(Например: ✨, 🔥, 🐱, 😎)",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(EmojiSettingSG.enter_new_emoji, F.text)
async def process_new_emoji(message: Message, state: FSMContext, repo: Repository, user: User):
    emojis = extract_emojis(message.text)
    new_emoji = emojis[0] if emojis else "✨"

    await repo.update_settings(user.telegram_id, default_emoji=new_emoji)
    user.settings_default_emoji = new_emoji
    await state.clear()

    await message.answer(
        f"✅ Новый эмодзи по умолчанию сохранен: {new_emoji}",
        reply_markup=get_settings_keyboard(user)
    )


@router.callback_query(F.data == "close_settings")
async def callback_close_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.answer()
