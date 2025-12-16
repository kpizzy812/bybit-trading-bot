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


def get_custom_risk_cancel_keyboard(scenario_index: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для отмены ввода custom риска

    Args:
        scenario_index: Индекс сценария

    Returns:
        InlineKeyboardMarkup с кнопкой отмены
    """
    builder = InlineKeyboardBuilder()

    builder.button(
        text="❌ Отмена",
        callback_data=f"ai:cancel_custom:{scenario_index}"
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

    # Редактирование сценария
    builder.button(
        text="✏️ Редактировать",
        callback_data=f"ai:edit_scenario:{scenario_index}"
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


def get_edit_scenario_keyboard(scenario: Dict[str, Any]) -> InlineKeyboardMarkup:
    """
    Клавиатура экрана редактирования сценария

    Args:
        scenario: Данные сценария

    Returns:
        InlineKeyboardMarkup с параметрами для редактирования
    """
    builder = InlineKeyboardBuilder()

    # Entry
    entry = scenario.get("entry", {})
    entry_min = entry.get("price_min", 0)
    entry_max = entry.get("price_max", 0)
    entry_price = (entry_min + entry_max) / 2
    entry_overridden = entry.get("overridden", False)
    entry_mark = " ✏️" if entry_overridden else ""
    builder.button(
        text=f"⚡ Entry: ${entry_price:.2f}{entry_mark}",
        callback_data="ai:edit:entry"
    )

    # Stop Loss
    stop_loss = scenario.get("stop_loss", {})
    stop_price = stop_loss.get("recommended", 0)
    sl_overridden = stop_loss.get("overridden", False)
    sl_mark = " ✏️" if sl_overridden else ""
    builder.button(
        text=f"🛑 Stop Loss: ${stop_price:.2f}{sl_mark}",
        callback_data="ai:edit:sl"
    )

    # Take Profit (показываем количество уровней)
    targets = scenario.get("targets", [])
    tp_count = len(targets)
    any_tp_overridden = any(t.get("overridden", False) for t in targets)
    tp_mark = " ✏️" if any_tp_overridden else ""
    builder.button(
        text=f"🎯 Take Profit ({tp_count} уровней){tp_mark}",
        callback_data="ai:edit:tp"
    )

    # Leverage
    leverage = scenario.get("leverage", {})
    lev_value = leverage.get("recommended", "5x") if isinstance(leverage, dict) else f"{leverage}x"
    lev_overridden = leverage.get("overridden", False) if isinstance(leverage, dict) else False
    lev_mark = " ✏️" if lev_overridden else ""
    builder.button(
        text=f"📊 Leverage: {lev_value}{lev_mark}",
        callback_data="ai:edit:leverage"
    )

    # Разделитель
    builder.button(text="─────────────", callback_data="ai:noop")

    # Назад к подтверждению
    builder.button(
        text="✅ Готово",
        callback_data="ai:edit:done"
    )

    # Сбросить изменения
    builder.button(
        text="🔄 Сбросить всё",
        callback_data="ai:edit:reset"
    )

    builder.adjust(1)

    return builder.as_markup()


def get_edit_entry_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура отмены редактирования Entry"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="ai:edit:cancel")
    return builder.as_markup()


def get_edit_tp_keyboard(targets: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора TP уровня для редактирования

    Args:
        targets: Список TP уровней

    Returns:
        InlineKeyboardMarkup с TP уровнями
    """
    builder = InlineKeyboardBuilder()

    for idx, target in enumerate(targets):
        tp_price = target.get("price", 0)
        partial_pct = target.get("partial_close_pct", 100)
        rr = target.get("rr", 0)
        overridden = target.get("overridden", False)
        mark = " ✏️" if overridden else ""

        builder.button(
            text=f"TP{idx+1}: ${tp_price:.2f} ({partial_pct}%) RR {rr:.1f}{mark}",
            callback_data=f"ai:edit:tp:{idx}"
        )

    # Добавить новый TP
    if len(targets) < 5:
        builder.button(text="➕ Добавить TP", callback_data="ai:edit:tp:add")

    # Назад
    builder.button(text="🔙 Назад", callback_data="ai:edit:back")

    builder.adjust(1)

    return builder.as_markup()


def get_edit_tp_level_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура отмены редактирования TP уровня"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Удалить TP", callback_data="ai:edit:tp:delete")
    builder.button(text="❌ Отмена", callback_data="ai:edit:tp:cancel")
    builder.adjust(2)
    return builder.as_markup()


def get_edit_leverage_keyboard(current: int, max_safe: int = 20) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора Leverage

    Args:
        current: Текущее плечо
        max_safe: Максимально безопасное плечо

    Returns:
        InlineKeyboardMarkup с вариантами плеча
    """
    builder = InlineKeyboardBuilder()

    # Стандартные варианты плеча
    leverage_options = [3, 5, 7, 10, 15, 20]

    for lev in leverage_options:
        if lev <= max_safe:
            is_current = "✓ " if lev == current else ""
            builder.button(
                text=f"{is_current}{lev}x",
                callback_data=f"ai:edit:lev:{lev}"
            )

    # Custom
    builder.button(text="✏️ Custom", callback_data="ai:edit:lev:custom")

    # Назад
    builder.button(text="🔙 Назад", callback_data="ai:edit:back")

    builder.adjust(3, 3, 2)

    return builder.as_markup()
