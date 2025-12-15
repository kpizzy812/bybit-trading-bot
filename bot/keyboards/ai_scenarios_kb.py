"""
Клавиатуры для AI Scenarios

Inline клавиатуры для работы с торговыми сценариями от Syntra AI.
"""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict, Any


def get_symbols_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора символа для AI анализа"""
    builder = InlineKeyboardBuilder()

    # Основные символы
    builder.button(text="BTC", callback_data="ai:symbol:BTCUSDT")
    builder.button(text="ETH", callback_data="ai:symbol:ETHUSDT")
    builder.button(text="SOL", callback_data="ai:symbol:SOLUSDT")
    builder.button(text="BNB", callback_data="ai:symbol:BNBUSDT")
    builder.button(text="HYPE", callback_data="ai:symbol:HYPEUSDT")

    # Выбор таймфрейма
    builder.button(text="⏰ 1H", callback_data="ai:timeframe:1h")
    builder.button(text="⏰ 4H", callback_data="ai:timeframe:4h")
    builder.button(text="⏰ 1D", callback_data="ai:timeframe:1d")

    # Layout: 2 символа в ряд, потом таймфреймы
    builder.adjust(2, 2, 1, 3)

    return builder.as_markup()


def get_scenarios_keyboard(scenarios: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """
    Клавиатура со списком сценариев

    Args:
        scenarios: Список сценариев от Syntra AI

    Returns:
        InlineKeyboardMarkup со сценариями
    """
    builder = InlineKeyboardBuilder()

    for i, scenario in enumerate(scenarios):
        # Emoji в зависимости от bias
        bias = scenario.get("bias", "neutral")
        emoji = "🟢" if bias == "long" else "🔴" if bias == "short" else "⚪"

        # Название сценария + confidence
        name = scenario.get("name", f"Scenario {i+1}")
        confidence = scenario.get("confidence", 0) * 100

        # Кнопка сценария
        button_text = f"{emoji} {name} ({confidence:.0f}%)"
        builder.button(
            text=button_text,
            callback_data=f"ai:scenario:{i}"
        )

    # Кнопки управления
    builder.button(text="🔄 Обновить", callback_data="ai:refresh")
    builder.button(text="🔙 Выбрать другой символ", callback_data="ai:change_symbol")

    # Layout: по 1 сценарию в ряд, потом управление
    builder.adjust(1)

    return builder.as_markup()


def get_scenario_detail_keyboard(scenario_index: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для детального просмотра сценария

    Args:
        scenario_index: Индекс сценария в списке

    Returns:
        InlineKeyboardMarkup с действиями
    """
    builder = InlineKeyboardBuilder()

    # Выбор риска для quick trade
    builder.button(text="💰 Trade $5", callback_data=f"ai:trade:{scenario_index}:5")
    builder.button(text="💰 Trade $10", callback_data=f"ai:trade:{scenario_index}:10")
    builder.button(text="💰 Trade $20", callback_data=f"ai:trade:{scenario_index}:20")
    builder.button(text="💰 Trade $50", callback_data=f"ai:trade:{scenario_index}:50")

    # Custom риск
    builder.button(text="✏️ Custom Risk", callback_data=f"ai:custom_risk:{scenario_index}")

    # Кнопки управления
    builder.button(text="🔙 К сценариям", callback_data="ai:back_to_list")

    # Layout: 2 пресета риска в ряд, custom, назад
    builder.adjust(2, 2, 1, 1)

    return builder.as_markup()


def get_timeframe_keyboard(symbol: str) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора таймфрейма для символа

    Args:
        symbol: Выбранный символ (BTCUSDT)

    Returns:
        InlineKeyboardMarkup с таймфреймами
    """
    builder = InlineKeyboardBuilder()

    # Таймфреймы
    builder.button(text="⏰ 1 Hour", callback_data=f"ai:analyze:{symbol}:1h")
    builder.button(text="⏰ 4 Hours", callback_data=f"ai:analyze:{symbol}:4h")
    builder.button(text="⏰ 1 Day", callback_data=f"ai:analyze:{symbol}:1d")

    builder.adjust(1)

    return builder.as_markup()


def get_edit_sl_cancel_keyboard(scenario_index: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для отмены редактирования SL

    Args:
        scenario_index: Индекс сценария

    Returns:
        InlineKeyboardMarkup с кнопкой отмены
    """
    builder = InlineKeyboardBuilder()

    builder.button(
        text="❌ Отмена (оставить AI SL)",
        callback_data=f"ai:cancel_edit:{scenario_index}"
    )

    return builder.as_markup()


def get_confirm_trade_keyboard(scenario_index: int, risk_usd: float) -> InlineKeyboardMarkup:
    """
    Клавиатура подтверждения сделки на основе сценария

    Args:
        scenario_index: Индекс сценария
        risk_usd: Выбранный риск

    Returns:
        InlineKeyboardMarkup с подтверждением
    """
    builder = InlineKeyboardBuilder()

    # Подтверждение
    builder.button(
        text="✅ Подтвердить",
        callback_data=f"ai:confirm:{scenario_index}:{risk_usd}"
    )

    # Редактирование уровней
    builder.button(
        text="✏️ Override SL",
        callback_data=f"ai:edit_sl:{scenario_index}"
    )

    # Изменить риск
    builder.button(
        text="💰 Изменить риск",
        callback_data=f"ai:scenario:{scenario_index}"
    )

    # Отмена
    builder.button(
        text="❌ Отмена",
        callback_data="ai:back_to_list"
    )

    builder.adjust(1)

    return builder.as_markup()
