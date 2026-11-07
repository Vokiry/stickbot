from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from bot.database.models import User
from bot.database.repository import Repository
from bot.utils.keyboards import get_main_reply_keyboard

router = Router(name="common")

WELCOME_TEXT = """
👋 **Привет, {name}! Я бот для быстрого создания стикеров и эмодзи в Telegram.**

🎨 **Что я умею:**
• Превращать любые **фотографии и картинки** в стикеры за 1 секунду.
• Автоматически соблюдать все требования Telegram (512x512, форматы, сжатие).
• Конвертировать **видео и GIF-анимации** в видеостикеры (VP9 WebM).
• Клонировать стикеры: просто **перешли мне любой стикер**, и я добавлю его в твой пак!
• Добавлять красивую **белую обводку и тень** на прозрачные стикеры.
• Создавать **Custom Emoji** для Telegram Premium.

👇 **С чего начать:**
1. Нажми **«🎨 Создать пак»** (или отправь команду /newpack).
2. После создания пака просто **отправляй мне любые фото, файлы, GIF или видео**, и они мгновенно окажутся в твоем наборе!
"""

HELP_TEXT = """
📖 **Инструкция и команды бота:**

• /newpack — Создать новый стикерпак (статический, видео или кастомные эмодзи).
• /packs — Список твоих паков и управление ими (выбор активного, удаление, обложка).
• /settings — Настройки бота (быстрый режим, авто-обводка, эмодзи по умолчанию).
• /cancel — Отменить текущее действие или создание пака.

💡 **Полезные советы:**
• **Эмодзи к стикеру**: при отправке фото напиши эмодзи в подписи к сообщению (например: `🔥`), и бот привяжет его к стикеру!
• **Кража стикеров**: перешли любой чужой стикер из любого чата — я добавлю его в твой активный пак.
• **Быстрый режим**: включен по умолчанию — стикеры добавляются моментально без лишних подтверждений.
"""


@router.message(CommandStart())
async def cmd_start(message: Message, user: User, state: FSMContext):
    await state.clear()
    await message.answer(
        WELCOME_TEXT.format(name=message.from_user.first_name),
        reply_markup=get_main_reply_keyboard(),
        parse_mode="Markdown"
    )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    await message.answer(
        HELP_TEXT,
        reply_markup=get_main_reply_keyboard(),
        parse_mode="Markdown"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активных действий для отмены.", reply_markup=get_main_reply_keyboard())
        return

    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=get_main_reply_keyboard())


@router.callback_query(F.data == "cancel_action")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Действие отменено.")
    await callback.answer()
