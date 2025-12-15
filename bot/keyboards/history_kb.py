"""
Inline клавиатуры для истории сделок
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_history_main_kb() -> InlineKeyboardMarkup:
    """
    Главное меню истории сделок

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Основные действия
    builder.row(
        InlineKeyboardButton(text="📋 Последние сделки", callback_data="hist_recent"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="hist_stats")
    )

    # Фильтры
    builder.row(
        InlineKeyboardButton(text="🔍 Фильтры", callback_data="hist_filters")
    )

    return builder.as_markup()


def get_history_list_kb(has_next: bool = False, offset: int = 0) -> InlineKeyboardMarkup:
    """
    Клавиатура для навигации по истории

    Args:
        has_next: Есть ли следующая страница
        offset: Текущее смещение

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Навигация
    buttons = []

    if offset > 0:
        buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"hist_page:{offset-20}"))

    if has_next:
        buttons.append(InlineKeyboardButton(text="Далее ▶️", callback_data=f"hist_page:{offset+20}"))

    if buttons:
        builder.row(*buttons)

    # Управляющие кнопки
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"hist_page:{offset}"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="hist_stats")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="hist_main")
    )

    return builder.as_markup()


def get_history_filters_kb(current_symbol: str = None, current_side: str = None) -> InlineKeyboardMarkup:
    """
    Клавиатура фильтров истории

    Args:
        current_symbol: Текущий фильтр по символу
        current_side: Текущий фильтр по направлению

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Фильтр по символу
    symbol_text = f"Symbol: {current_symbol}" if current_symbol else "All Symbols"
    builder.row(
        InlineKeyboardButton(text=f"📊 {symbol_text}", callback_data="hist_filter_symbol")
    )

    # Фильтр по направлению
    side_text = current_side if current_side else "All Sides"
    builder.row(
        InlineKeyboardButton(text=f"🔄 {side_text}", callback_data="hist_filter_side")
    )

    # Сброс фильтров
    builder.row(
        InlineKeyboardButton(text="🔄 Сбросить фильтры", callback_data="hist_clear_filters")
    )

    # Показать результаты
    builder.row(
        InlineKeyboardButton(text="✅ Применить", callback_data="hist_recent")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="hist_main")
    )

    return builder.as_markup()


def get_stats_kb() -> InlineKeyboardMarkup:
    """
    Клавиатура для статистики

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="📋 Последние сделки", callback_data="hist_recent")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="hist_main")
    )

    return builder.as_markup()
