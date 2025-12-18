"""
Клавиатуры для AI Scenarios

Inline клавиатуры для работы с торговыми сценариями от Syntra AI.
"""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict, Any, Optional

from services.trading_modes import get_mode_registry, ALL_MODES
from services.universe import SymbolMetrics, MAJOR_SYMBOLS, CATEGORY_LABELS


def get_mode_toggle_keyboard(current_mode: str = "standard") -> InlineKeyboardMarkup:
    """
    Клавиатура выбора trading mode.

    Args:
        current_mode: Текущий режим (conservative, standard, high_risk, meme)

    Returns:
        InlineKeyboardMarkup с режимами
    """
    builder = InlineKeyboardBuilder()
    registry = get_mode_registry()

    for mode_id in ["conservative", "standard", "high_risk", "meme"]:
        mode = registry.get(mode_id)
        is_current = mode_id == current_mode
        check = "✓ " if is_current else ""
        builder.button(
            text=f"{check}{mode.emoji} {mode.name}",
            callback_data=f"ai:mode:{mode_id}"
        )

    builder.button(text="🔙 Назад", callback_data="ai:mode:back")
    builder.adjust(2, 2, 1)

    return builder.as_markup()


def get_symbols_keyboard(
    cached_pairs: list[tuple[str, str, int]] = None,
    current_mode: str = "standard",
    meme_symbols: Optional[list] = None,
) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора символа для AI анализа.

    Args:
        cached_pairs: Список (symbol, timeframe, age_mins) закэшированных пар
        current_mode: Текущий trading mode
        meme_symbols: Whitelist символов для MEME режима
    """
    builder = InlineKeyboardBuilder()
    rows = []
    registry = get_mode_registry()
    mode = registry.get_or_default(current_mode)

    # Mode toggle кнопка в header
    builder.button(
        text=f"{mode.emoji} Mode: {mode.name} ▼",
        callback_data="ai:mode:toggle"
    )
    rows.append(1)

    # Показать закэшированные пары если есть
    if cached_pairs:
        for symbol, timeframe, age_mins in cached_pairs[:3]:  # Макс 3 пары
            # Для MEME режима - только whitelist символы
            if current_mode == "meme" and meme_symbols and symbol not in meme_symbols:
                continue
            coin = symbol.replace("USDT", "")
            if age_mins < 60:
                age_str = f"{age_mins}m"
            else:
                age_str = f"{age_mins // 60}h"
            builder.button(
                text=f"📦 {coin} {timeframe} ({age_str})",
                callback_data=f"ai:analyze:{symbol}:{timeframe}"
            )
        if cached_pairs:
            rows.append(min(len(cached_pairs), 3))

    # Символы в зависимости от режима
    if current_mode == "meme" and meme_symbols:
        # Только MEME символы
        for symbol in meme_symbols[:6]:
            coin = symbol.replace("USDT", "")
            builder.button(text=coin, callback_data=f"ai:symbol:{symbol}")
        rows.extend([3, 3] if len(meme_symbols) > 3 else [len(meme_symbols)])
    else:
        # Основные символы
        builder.button(text="BTC", callback_data="ai:symbol:BTCUSDT")
        builder.button(text="ETH", callback_data="ai:symbol:ETHUSDT")
        builder.button(text="SOL", callback_data="ai:symbol:SOLUSDT")
        builder.button(text="BNB", callback_data="ai:symbol:BNBUSDT")
        builder.button(text="HYPE", callback_data="ai:symbol:HYPEUSDT")
        rows.extend([2, 2, 1])

    # Выбор таймфрейма
    builder.button(text="⏰ 1H", callback_data="ai:timeframe:1h")
    builder.button(text="⏰ 4H", callback_data="ai:timeframe:4h")
    builder.button(text="⏰ 1D", callback_data="ai:timeframe:1d")
    rows.append(3)

    builder.adjust(*rows)

    return builder.as_markup()


def get_dynamic_symbols_keyboard(
    dynamic_symbols: List[SymbolMetrics],
    current_mode: str = "standard",
    current_category: str = "trending",
    cached_pairs: list[tuple[str, str, int]] = None,
) -> InlineKeyboardMarkup:
    """
    Динамическая клавиатура выбора символа с категориями.

    Args:
        dynamic_symbols: Список символов из UniverseService
        current_mode: Текущий trading mode
        current_category: Текущая категория (trending, popular, pumping, dumping, volatile)
        cached_pairs: Закэшированные пары для быстрого доступа

    UI Layout:
        ┌─────────────────────────────────────┐
        │ 📊 Mode: Standard ▼                 │
        ├─────────────────────────────────────┤
        │ 🌊 Trending                         │
        ├─────────────────────────────────────┤
        │ [SUI +12%] [PEPE +8%] [WIF +6%]    │
        ├─────────────────────────────────────┤
        │ [BTC] [ETH] [SOL] [BNB]            │
        ├─────────────────────────────────────┤
        │ [📊 Pop] [🔥 Pump] [🧊 Dump] [⚡ Vol]│
        ├─────────────────────────────────────┤
        │ [⏰ 1H] [⏰ 4H] [⏰ 1D]             │
        └─────────────────────────────────────┘
    """
    builder = InlineKeyboardBuilder()
    rows = []
    registry = get_mode_registry()
    mode = registry.get_or_default(current_mode)

    # Row 1: Mode toggle
    builder.button(
        text=f"{mode.emoji} Mode: {mode.name} ▼",
        callback_data="ai:mode:toggle"
    )
    rows.append(1)

    # Row 2: Current category label
    category_label = CATEGORY_LABELS.get(current_category, "🌊 Trending")
    builder.button(
        text=category_label,
        callback_data="ai:noop"  # Just a label, not clickable
    )
    rows.append(1)

    # Row 3: Cached pairs (if any)
    if cached_pairs:
        cached_count = 0
        for symbol, timeframe, age_mins in cached_pairs[:2]:  # Max 2 cached
            coin = symbol.replace("USDT", "")
            age_str = f"{age_mins}m" if age_mins < 60 else f"{age_mins // 60}h"
            builder.button(
                text=f"📦 {coin} {timeframe} ({age_str})",
                callback_data=f"ai:analyze:{symbol}:{timeframe}"
            )
            cached_count += 1
        if cached_count > 0:
            rows.append(cached_count)

    # Row 4-5: Dynamic symbols from Universe (3-5 symbols)
    if dynamic_symbols:
        dynamic_row = []
        for m in dynamic_symbols[:5]:  # Max 5 dynamic symbols
            coin = m.symbol.replace("USDT", "")
            # Show price change for pumping/dumping
            if current_category in ("pumping", "gainers"):
                label = f"{coin} +{m.price_change_pct:.0f}%" if m.price_change_pct > 0 else f"{coin} {m.price_change_pct:.0f}%"
            elif current_category in ("dumping", "losers"):
                label = f"{coin} {m.price_change_pct:.0f}%"
            elif current_category == "volatile":
                label = f"{coin} ±{m.range_pct:.0f}%"
            else:
                # Trending/Popular - show volume in millions
                vol_m = m.turnover_24h / 1_000_000
                if vol_m >= 100:
                    label = f"{coin} ${vol_m:.0f}M"
                else:
                    label = f"{coin}"

            builder.button(
                text=label,
                callback_data=f"ai:symbol:{m.symbol}"
            )
            dynamic_row.append(1)

        # Layout: 3+2 or 3 depending on count
        if len(dynamic_row) > 3:
            rows.extend([3, len(dynamic_row) - 3])
        elif len(dynamic_row) > 0:
            rows.append(len(dynamic_row))

    # Row 6: Majors (anchor)
    for symbol in MAJOR_SYMBOLS[:4]:  # BTC, ETH, SOL, BNB
        coin = symbol.replace("USDT", "")
        builder.button(text=coin, callback_data=f"ai:symbol:{symbol}")
    rows.append(4)

    # Row 7: Category buttons
    categories = [
        ("📊", "popular"),
        ("🔥", "pumping"),
        ("🧊", "dumping"),
        ("⚡", "volatile"),
    ]
    for emoji, cat in categories:
        is_current = "•" if cat == current_category else ""
        builder.button(
            text=f"{is_current}{emoji}",
            callback_data=f"ai:cat:{cat}:{current_mode}"
        )
    rows.append(4)

    # Row 8: Timeframes
    builder.button(text="⏰ 1H", callback_data="ai:timeframe:1h")
    builder.button(text="⏰ 4H", callback_data="ai:timeframe:4h")
    builder.button(text="⏰ 1D", callback_data="ai:timeframe:1d")
    rows.append(3)

    builder.adjust(*rows)
    return builder.as_markup()


def get_category_keyboard(
    current_category: str = "trending",
    current_mode: str = "standard"
) -> InlineKeyboardMarkup:
    """
    Клавиатура переключения категорий.

    Args:
        current_category: Текущая категория
        current_mode: Текущий режим

    Returns:
        InlineKeyboardMarkup с категориями
    """
    builder = InlineKeyboardBuilder()

    categories = [
        ("🌊 Trending", "trending"),
        ("📊 Popular", "popular"),
        ("🔥 Pumping", "pumping"),
        ("🧊 Dumping", "dumping"),
        ("⚡ Volatile", "volatile"),
    ]

    for label, cat in categories:
        is_current = "✓ " if cat == current_category else ""
        builder.button(
            text=f"{is_current}{label}",
            callback_data=f"ai:cat:{cat}:{current_mode}"
        )

    builder.button(text="🔙 Назад", callback_data="ai:symbols")
    builder.adjust(2, 2, 1, 1)

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


def get_scenario_detail_keyboard(
    scenario_index: int,
    show_chart_button: bool = False,
    is_blocked: bool = False,
) -> InlineKeyboardMarkup:
    """
    Клавиатура для детального просмотра сценария

    Args:
        scenario_index: Индекс сценария в списке
        show_chart_button: Показывать ли кнопку графика (если текст длинный)
        is_blocked: Заблокирован ли сценарий по Real EV

    Returns:
        InlineKeyboardMarkup с действиями
    """
    builder = InlineKeyboardBuilder()
    rows = []

    # Кнопка графика (только если текст длинный и график не прикреплён)
    if show_chart_button:
        builder.button(text="📊 График", callback_data=f"ai:chart:{scenario_index}")
        rows.append(1)

    # Если заблокировано - только кнопка назад
    if is_blocked:
        builder.button(text="🔙 К сценариям", callback_data="ai:back_to_list")
        rows.append(1)
        builder.adjust(*rows)
        return builder.as_markup()

    # Выбор риска для quick trade
    builder.button(text="💰 Trade $5", callback_data=f"ai:trade:{scenario_index}:5")
    builder.button(text="💰 Trade $10", callback_data=f"ai:trade:{scenario_index}:10")
    builder.button(text="💰 Trade $20", callback_data=f"ai:trade:{scenario_index}:20")
    builder.button(text="💰 Trade $50", callback_data=f"ai:trade:{scenario_index}:50")

    # Custom риск
    builder.button(text="✏️ Custom Risk", callback_data=f"ai:custom_risk:{scenario_index}")

    # Кнопки управления
    builder.button(text="🔙 К сценариям", callback_data="ai:back_to_list")

    # Layout: [график если есть], 2+2 пресета риска, custom, назад
    rows.extend([2, 2, 1, 1])
    builder.adjust(*rows)

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
