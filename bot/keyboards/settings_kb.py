"""
Inline клавиатуры для настроек
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import config


def get_settings_menu_kb() -> InlineKeyboardMarkup:
    """
    Главное меню настроек с категориями

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Категории настроек
    builder.row(
        InlineKeyboardButton(text="💰 Default Risk", callback_data="set_default_risk"),
        InlineKeyboardButton(text="📊 Default Leverage", callback_data="set_default_leverage")
    )

    builder.row(
        InlineKeyboardButton(text="🎯 TP Mode", callback_data="set_tp_mode"),
        InlineKeyboardButton(text="🔴 Shorts", callback_data="set_shorts_enabled")
    )

    builder.row(
        InlineKeyboardButton(text="🛡 Safety Limits", callback_data="set_safety_limits")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="set_back_to_main")
    )

    return builder.as_markup()


def get_default_risk_kb(current_risk: float) -> InlineKeyboardMarkup:
    """
    Клавиатура для выбора дефолтного риска

    Args:
        current_risk: Текущий риск

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Пресеты риска
    risk_presets = [5, 10, 15, 20]

    for risk in risk_presets:
        # Отметка текущего выбора
        text = f"${risk}"
        if risk == current_risk:
            text = f"✅ ${risk}"

        builder.button(
            text=text,
            callback_data=f"set_risk:{risk}"
        )

    # По 2 кнопки в строку
    builder.adjust(2)

    # Назад
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="set_back_to_menu")
    )

    return builder.as_markup()


def get_default_leverage_kb(current_leverage: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для выбора дефолтного плеча

    Args:
        current_leverage: Текущее плечо

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Пресеты плеча
    leverage_presets = [2, 3, 5, 10]

    for lev in leverage_presets:
        # Отметка текущего выбора
        text = f"{lev}x"
        if lev == current_leverage:
            text = f"✅ {lev}x"

        builder.button(
            text=text,
            callback_data=f"set_leverage:{lev}"
        )

    # По 2 кнопки в строку
    builder.adjust(2)

    # Назад
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="set_back_to_menu")
    )

    return builder.as_markup()


def get_tp_mode_kb(current_tp_mode: str) -> InlineKeyboardMarkup:
    """
    Клавиатура для выбора TP режима

    Args:
        current_tp_mode: Текущий TP режим

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    tp_modes = {
        'single': '🎯 Single TP',
        'ladder': '🪜 Ladder',
        'rr': '📐 By RR'
    }

    for mode, label in tp_modes.items():
        # Отметка текущего выбора
        text = label
        if mode == current_tp_mode:
            text = f"✅ {label}"

        builder.button(
            text=text,
            callback_data=f"set_tp_mode:{mode}"
        )

    # По одной кнопке в строку
    builder.adjust(1)

    # Назад
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="set_back_to_menu")
    )

    return builder.as_markup()


def get_shorts_enabled_kb(current_shorts: bool) -> InlineKeyboardMarkup:
    """
    Клавиатура для включения/выключения шортов

    Args:
        current_shorts: Текущее состояние шортов

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Включить/Выключить
    builder.row(
        InlineKeyboardButton(
            text="✅ Включить" if not current_shorts else "✅ Включены",
            callback_data="set_shorts:true"
        ),
        InlineKeyboardButton(
            text="❌ Выключены" if not current_shorts else "❌ Выключить",
            callback_data="set_shorts:false"
        )
    )

    # Назад
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="set_back_to_menu")
    )

    return builder.as_markup()


def get_safety_limits_kb() -> InlineKeyboardMarkup:
    """
    Клавиатура для управления лимитами безопасности

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Лимиты (показываем текущие значения из config)
    builder.row(
        InlineKeyboardButton(
            text=f"Max Risk: ${config.MAX_RISK_PER_TRADE}",
            callback_data="set_max_risk"
        )
    )

    builder.row(
        InlineKeyboardButton(
            text=f"Max Margin: ${config.MAX_MARGIN_PER_TRADE}",
            callback_data="set_max_margin"
        )
    )

    builder.row(
        InlineKeyboardButton(
            text=f"Max Leverage: {config.MAX_LEVERAGE}x",
            callback_data="set_max_leverage"
        )
    )

    # Назад
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="set_back_to_menu")
    )

    return builder.as_markup()


def get_max_risk_kb(current_max_risk: float) -> InlineKeyboardMarkup:
    """
    Клавиатура для выбора максимального риска

    Args:
        current_max_risk: Текущий максимальный риск

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Пресеты
    risk_presets = [10, 20, 30, 50]

    for risk in risk_presets:
        text = f"${risk}"
        if risk == current_max_risk:
            text = f"✅ ${risk}"

        builder.button(
            text=text,
            callback_data=f"set_max_risk_val:{risk}"
        )

    builder.adjust(2)

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="set_safety_limits")
    )

    return builder.as_markup()


def get_max_margin_kb(current_max_margin: float) -> InlineKeyboardMarkup:
    """
    Клавиатура для выбора максимальной маржи

    Args:
        current_max_margin: Текущая максимальная маржа

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Пресеты
    margin_presets = [100, 150, 200, 300]

    for margin in margin_presets:
        text = f"${margin}"
        if margin == current_max_margin:
            text = f"✅ ${margin}"

        builder.button(
            text=text,
            callback_data=f"set_max_margin_val:{margin}"
        )

    builder.adjust(2)

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="set_safety_limits")
    )

    return builder.as_markup()


def get_max_leverage_kb(current_max_leverage: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для выбора максимального плеча

    Args:
        current_max_leverage: Текущее максимальное плечо

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Пресеты
    leverage_presets = [5, 10, 20, 50]

    for lev in leverage_presets:
        text = f"{lev}x"
        if lev == current_max_leverage:
            text = f"✅ {lev}x"

        builder.button(
            text=text,
            callback_data=f"set_max_leverage_val:{lev}"
        )

    builder.adjust(2)

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="set_safety_limits")
    )

    return builder.as_markup()
