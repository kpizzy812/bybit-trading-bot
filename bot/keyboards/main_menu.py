from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import config


def get_main_menu() -> ReplyKeyboardMarkup:
    """
    Главное меню бота (Reply Keyboard)

    Кнопки:
    - ➕ Открыть сделку
    - 🤖 AI Сценарии (если включено)
    - 📊 Позиции
    - ⚙️ Настройки
    - 🧾 История
    - 🧪 Testnet/Live
    """
    # Основные кнопки
    keyboard_buttons = [
        [
            KeyboardButton(text="➕ Открыть сделку"),
            KeyboardButton(text="📊 Позиции"),
        ],
        [
            KeyboardButton(text="⚙️ Настройки"),
            KeyboardButton(text="🧾 История"),
        ],
    ]

    # Добавить AI Сценарии если включено
    if config.AI_SCENARIOS_ENABLED:
        keyboard_buttons.insert(1, [
            KeyboardButton(text="🤖 AI Сценарии"),
        ])

    # Testnet/Live всегда внизу
    keyboard_buttons.append([
        KeyboardButton(text="🧪 Testnet/Live"),
    ])

    keyboard = ReplyKeyboardMarkup(
        keyboard=keyboard_buttons,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )
    return keyboard
