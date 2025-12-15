from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from bot.keyboards.main_menu import get_main_menu

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start"""

    welcome_text = """
🤖 **Bybit Trading Bot**

Привет! Я помогу тебе торговать на Bybit с правильным управлением рисками.

**Что я умею:**
✅ Автоматический расчёт размера позиции от риска
✅ One-tap execution с обязательными SL/TP
✅ Мониторинг открытых позиций
✅ Статистика и история сделок
✅ Testnet режим для тестирования

**⚠️ Важно перед началом:**
1. Убедись, что твой Bybit API ключ имеет только права **Trade** (БЕЗ Withdraw!)
2. Начни с Testnet режима для проверки
3. Никогда не рискуй больше, чем готов потерять

Используй меню ниже для начала работы 👇
"""

    await message.answer(
        welcome_text,
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )
