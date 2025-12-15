from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu() -> ReplyKeyboardMarkup:
    """
    Главное меню бота (Reply Keyboard)

    Кнопки:
    - ➕ Открыть сделку
    - 📊 Позиции
    - ⚙️ Настройки
    - 🧾 История
    - 🧪 Testnet/Live
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="➕ Открыть сделку"),
                KeyboardButton(text="📊 Позиции"),
            ],
            [
                KeyboardButton(text="⚙️ Настройки"),
                KeyboardButton(text="🧾 История"),
            ],
            [
                KeyboardButton(text="🧪 Testnet/Live"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )
    return keyboard
