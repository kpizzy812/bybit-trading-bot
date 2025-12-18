"""
Inline клавиатуры для Trade Wizard
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import config


def get_symbol_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора символа

    Symbols:
    - BTCUSDT | ETHUSDT
    - SOLUSDT | BNBUSDT
    - HYPEUSDT
    """
    builder = InlineKeyboardBuilder()

    # Первая строка: BTC, ETH
    builder.row(
        InlineKeyboardButton(text="₿ BTC", callback_data="symbol:BTCUSDT"),
        InlineKeyboardButton(text="Ξ ETH", callback_data="symbol:ETHUSDT")
    )

    # Вторая строка: SOL, BNB
    builder.row(
        InlineKeyboardButton(text="◎ SOL", callback_data="symbol:SOLUSDT"),
        InlineKeyboardButton(text="◆ BNB", callback_data="symbol:BNBUSDT")
    )

    # Третья строка: HYPE
    builder.row(
        InlineKeyboardButton(text="⚡ HYPE", callback_data="symbol:HYPEUSDT")
    )

    # Отмена
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="trade:cancel")
    )

    return builder.as_markup()


def get_side_keyboard(shorts_enabled: bool = False) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора направления (Long/Short)

    Args:
        shorts_enabled: Разрешены ли шорты в настройках
    """
    builder = InlineKeyboardBuilder()

    # Long всегда доступен
    builder.row(
        InlineKeyboardButton(text="🟢 Long", callback_data="side:Buy")
    )

    # Short только если включён
    if shorts_enabled:
        builder.row(
            InlineKeyboardButton(text="🔴 Short", callback_data="side:Sell")
        )

    # Назад и отмена
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="trade:back"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="trade:cancel")
    )

    return builder.as_markup()


def get_entry_type_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора типа входа (Market/Limit)
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="⚡ Market", callback_data="entry_type:Market"),
        InlineKeyboardButton(text="🎯 Limit", callback_data="entry_type:Limit")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="trade:back"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="trade:cancel")
    )

    return builder.as_markup()


def get_stop_mode_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора режима установки стопа

    Режимы:
    - 📐 Stop % (быстро, пресеты)
    - ✍️ Цена вручную (по структуре)
    - 🤖 AI сценарии (будущая фича)
    """
    builder = InlineKeyboardBuilder()

    # Режимы стопа
    builder.row(
        InlineKeyboardButton(text="📐 Stop % (быстро)", callback_data="stop_mode:percent")
    )

    builder.row(
        InlineKeyboardButton(text="✍️ Цена вручную", callback_data="stop_mode:manual")
    )

    # AI сценарии (пока disabled, будет в будущем)
    # builder.row(
    #     InlineKeyboardButton(text="🤖 AI сценарии", callback_data="stop_mode:ai")
    # )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="trade:back"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="trade:cancel")
    )

    return builder.as_markup()


def get_stop_percent_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора % для стопа

    Пресеты:
    - 0.8%, 1.0%, 1.5%
    - 2.0%, 2.5%
    - Custom
    """
    builder = InlineKeyboardBuilder()

    # Первая строка: 0.8%, 1.0%, 1.5%
    builder.row(
        InlineKeyboardButton(text="0.8%", callback_data="stop_percent:0.8"),
        InlineKeyboardButton(text="1.0%", callback_data="stop_percent:1.0"),
        InlineKeyboardButton(text="1.5%", callback_data="stop_percent:1.5")
    )

    # Вторая строка: 2.0%, 2.5%
    builder.row(
        InlineKeyboardButton(text="2.0%", callback_data="stop_percent:2.0"),
        InlineKeyboardButton(text="2.5%", callback_data="stop_percent:2.5")
    )

    # Custom
    builder.row(
        InlineKeyboardButton(text="💎 Custom %", callback_data="stop_percent:custom")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="trade:back"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="trade:cancel")
    )

    return builder.as_markup()


def get_risk_keyboard(risk_mode: str = 'usd') -> InlineKeyboardMarkup:
    """
    Клавиатура выбора риска.

    Args:
        risk_mode: 'usd' для фиксированных сумм, 'percent' для % от баланса

    USD mode (manual capital):
        Пресеты: $5, $10, $15, Custom

    Percent mode (auto capital):
        Пресеты: 0.25%, 0.5%, 0.75%, 1%, 1.5%, 2%
    """
    builder = InlineKeyboardBuilder()

    if risk_mode == 'percent':
        # Процентные пресеты (когда trading_capital_mode == 'auto')
        builder.row(
            InlineKeyboardButton(text="0.25%", callback_data="risk_pct:0.25"),
            InlineKeyboardButton(text="0.5%", callback_data="risk_pct:0.5"),
            InlineKeyboardButton(text="0.75%", callback_data="risk_pct:0.75")
        )
        builder.row(
            InlineKeyboardButton(text="1%", callback_data="risk_pct:1"),
            InlineKeyboardButton(text="1.5%", callback_data="risk_pct:1.5"),
            InlineKeyboardButton(text="2%", callback_data="risk_pct:2")
        )
        builder.row(
            InlineKeyboardButton(text="💰 Custom %", callback_data="risk_pct:custom")
        )
    else:
        # USD пресеты (когда trading_capital_mode == 'manual')
        builder.row(
            InlineKeyboardButton(text="$5", callback_data="risk:5"),
            InlineKeyboardButton(text="$10", callback_data="risk:10"),
            InlineKeyboardButton(text="$15", callback_data="risk:15")
        )
        builder.row(
            InlineKeyboardButton(text="💰 Custom Risk", callback_data="risk:custom")
        )

    # Новая опция: указать размер позиции напрямую
    builder.row(
        InlineKeyboardButton(text="💵 Position Size", callback_data="risk:position_size")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="trade:back"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="trade:cancel")
    )

    return builder.as_markup()


def get_leverage_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора плеча
    Пресеты: 2x, 3x, 5x, 10x, Custom
    """
    builder = InlineKeyboardBuilder()

    # Пресеты плеча
    builder.row(
        InlineKeyboardButton(text="2x", callback_data="leverage:2"),
        InlineKeyboardButton(text="3x", callback_data="leverage:3")
    )

    builder.row(
        InlineKeyboardButton(text="5x", callback_data="leverage:5"),
        InlineKeyboardButton(text="10x", callback_data="leverage:10")
    )

    builder.row(
        InlineKeyboardButton(text="⚙️ Custom", callback_data="leverage:custom")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="trade:back"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="trade:cancel")
    )

    return builder.as_markup()


def get_tp_mode_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора режима Take Profit
    - Single TP (одна цена)
    - Ladder (2 уровня: 50%/50%)
    - By RR (Risk/Reward)
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="🎯 Single TP", callback_data="tp_mode:single")
    )

    builder.row(
        InlineKeyboardButton(text="🪜 Ladder (50/50)", callback_data="tp_mode:ladder")
    )

    builder.row(
        InlineKeyboardButton(text="📐 By RR", callback_data="tp_mode:rr")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="trade:back"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="trade:cancel")
    )

    return builder.as_markup()


def get_tp_rr_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора Risk/Reward ratio
    Пресеты: 1.5, 2.0, 3.0, Custom
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="RR 1.5", callback_data="tp_rr:1.5"),
        InlineKeyboardButton(text="RR 2.0", callback_data="tp_rr:2.0"),
        InlineKeyboardButton(text="RR 3.0", callback_data="tp_rr:3.0")
    )

    builder.row(
        InlineKeyboardButton(text="💎 Custom", callback_data="tp_rr:custom")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="trade:back"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="trade:cancel")
    )

    return builder.as_markup()


def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура подтверждения сделки
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="✅ Place Order", callback_data="trade:confirm")
    )

    builder.row(
        InlineKeyboardButton(text="✏️ Edit", callback_data="trade:edit"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="trade:cancel")
    )

    return builder.as_markup()


def get_skip_button() -> InlineKeyboardMarkup:
    """
    Кнопка пропуска (например, для опционального ввода)
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="⏭ Skip", callback_data="trade:skip")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="trade:back"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="trade:cancel")
    )

    return builder.as_markup()
