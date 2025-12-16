"""
Inline клавиатуры для управления позициями
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_positions_list_kb(positions: list, orders: list = None) -> InlineKeyboardMarkup:
    """
    Клавиатура со списком позиций и ордеров + управляющие кнопки

    Args:
        positions: Список позиций от Bybit API
        orders: Список открытых ордеров от Bybit API

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Кнопка для каждой позиции
    for pos in positions:
        symbol = pos.get('symbol')
        side = pos.get('side')  # "Buy" or "Sell"
        unrealized_pnl = float(pos.get('unrealisedPnl', 0))

        # Эмодзи
        side_emoji = "🟢" if side == "Buy" else "🔴"
        pnl_emoji = "💰" if unrealized_pnl >= 0 else "📉"

        # Текст кнопки
        button_text = f"{side_emoji} {symbol} | {pnl_emoji} ${unrealized_pnl:+.2f}"

        # Callback data: pos_detail:{symbol}
        builder.button(
            text=button_text,
            callback_data=f"pos_detail:{symbol}"
        )

    # Кнопки для ордеров
    if orders:
        for order in orders:
            symbol = order.get('symbol')
            side = order.get('side')  # "Buy" or "Sell"
            price = float(order.get('price', 0))
            qty = order.get('qty', '0')
            order_id = order.get('orderId')

            # Эмодзи
            side_emoji = "🟢" if side == "Buy" else "🔴"

            # Текст кнопки - показываем что это ордер
            button_text = f"⏳ {side_emoji} {symbol} @ ${price:.2f}"

            builder.button(
                text=button_text,
                callback_data=f"order_detail:{symbol}:{order_id[:20]}"
            )

    # По одной кнопке на строку
    builder.adjust(1)

    # Управляющие кнопки (в одной строке)
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="pos_refresh"),
        InlineKeyboardButton(text="🧯 Закрыть всё", callback_data="pos_panic_close_all")
    )

    return builder.as_markup()


def get_order_detail_kb(symbol: str, order_id: str) -> InlineKeyboardMarkup:
    """
    Клавиатура для управления ордером

    Args:
        symbol: Торговая пара
        order_id: ID ордера

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Отмена ордера
    builder.row(
        InlineKeyboardButton(
            text="❌ Отменить ордер",
            callback_data=f"order_cancel:{symbol}:{order_id[:20]}"
        )
    )

    # Назад
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="pos_back_to_list")
    )

    return builder.as_markup()


def get_position_detail_kb(symbol: str) -> InlineKeyboardMarkup:
    """
    Клавиатура для управления конкретной позицией

    Args:
        symbol: Торговая пара (например, SOLUSDT)

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Управление позицией
    builder.row(
        InlineKeyboardButton(text="🧷 Move SL", callback_data=f"pos_move_sl:{symbol}"),
        InlineKeyboardButton(text="🎯 Modify TP", callback_data=f"pos_modify_tp:{symbol}")
    )

    # Partial Close
    builder.row(
        InlineKeyboardButton(text="25%", callback_data=f"pos_partial:{symbol}:25"),
        InlineKeyboardButton(text="50%", callback_data=f"pos_partial:{symbol}:50"),
        InlineKeyboardButton(text="75%", callback_data=f"pos_partial:{symbol}:75")
    )

    # Close Market
    builder.row(
        InlineKeyboardButton(text="❌ Close Market", callback_data=f"pos_close:{symbol}")
    )

    # Назад
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="pos_back_to_list")
    )

    return builder.as_markup()


def get_move_sl_confirmation_kb(symbol: str, new_sl: str) -> InlineKeyboardMarkup:
    """
    Подтверждение перемещения Stop Loss

    Args:
        symbol: Торговая пара
        new_sl: Новая цена SL

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"pos_sl_confirm:{symbol}:{new_sl}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"pos_detail:{symbol}")
    )

    return builder.as_markup()


def get_close_confirmation_kb(symbol: str, percent: int = 100) -> InlineKeyboardMarkup:
    """
    Подтверждение закрытия позиции

    Args:
        symbol: Торговая пара
        percent: Процент для закрытия (100 = полное закрытие)

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="✅ Да, закрыть", callback_data=f"pos_close_confirm:{symbol}:{percent}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"pos_detail:{symbol}")
    )

    return builder.as_markup()


def get_panic_close_all_confirmation_kb() -> InlineKeyboardMarkup:
    """
    Подтверждение Panic Close All (закрыть все позиции)

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="🧯 Да, закрыть ВСЁ!", callback_data="pos_panic_confirm"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="pos_back_to_list")
    )

    return builder.as_markup()


# ============================================================
# ENTRY PLANS KEYBOARDS
# ============================================================

def get_positions_with_plans_kb(
    positions: list,
    orders: list = None,
    entry_plans: list = None
) -> InlineKeyboardMarkup:
    """
    Клавиатура со списком позиций, ордеров и Entry Plans

    Args:
        positions: Список позиций от Bybit API
        orders: Список открытых ордеров от Bybit API
        entry_plans: Список активных Entry Plans

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    # Кнопка для каждой позиции
    for pos in positions:
        symbol = pos.get('symbol')
        side = pos.get('side')
        unrealized_pnl = float(pos.get('unrealisedPnl', 0))

        side_emoji = "🟢" if side == "Buy" else "🔴"
        pnl_emoji = "💰" if unrealized_pnl >= 0 else "📉"

        button_text = f"{side_emoji} {symbol} | {pnl_emoji} ${unrealized_pnl:+.2f}"

        builder.button(
            text=button_text,
            callback_data=f"pos_detail:{symbol}"
        )

    # Кнопки для Entry Plans
    if entry_plans:
        for plan in entry_plans:
            symbol = plan.get('symbol', '')
            side = plan.get('side', 'Long')
            status = plan.get('status', 'pending')
            fill_pct = plan.get('fill_percentage', 0)
            plan_id = plan.get('plan_id', '')[:8]

            side_emoji = "🟢" if side == "Long" else "🔴"

            # Статус-emoji
            if status == "active":
                status_emoji = "📋"
            elif status == "partial":
                status_emoji = "🔄"
            elif status == "pending":
                status_emoji = "⏳"
            else:
                status_emoji = "📋"

            button_text = f"{status_emoji} {side_emoji} {symbol} Plan ({fill_pct:.0f}%)"

            builder.button(
                text=button_text,
                callback_data=f"eplan_detail:{plan_id}"
            )

    # Кнопки для ордеров
    if orders:
        for order in orders:
            symbol = order.get('symbol')
            side = order.get('side')
            price = float(order.get('price', 0))
            order_id = order.get('orderId')

            side_emoji = "🟢" if side == "Buy" else "🔴"
            button_text = f"⏳ {side_emoji} {symbol} @ ${price:.2f}"

            builder.button(
                text=button_text,
                callback_data=f"order_detail:{symbol}:{order_id[:20]}"
            )

    # По одной кнопке на строку
    builder.adjust(1)

    # Управляющие кнопки
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="pos_refresh"),
        InlineKeyboardButton(text="🧯 Закрыть всё", callback_data="pos_panic_close_all")
    )

    return builder.as_markup()


def get_entry_plan_detail_kb(plan_id: str, is_activated: bool = True) -> InlineKeyboardMarkup:
    """
    Клавиатура для управления Entry Plan

    Args:
        plan_id: ID плана (полный или короткий)
        is_activated: Активирован ли план (если нет - показать кнопку активации)

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    short_id = plan_id[:8]

    # Кнопка активации (если план ожидает)
    if not is_activated:
        builder.row(
            InlineKeyboardButton(
                text="🚀 Активировать сейчас",
                callback_data=f"eplan_activate:{short_id}"
            )
        )

    # Отмена плана
    builder.row(
        InlineKeyboardButton(
            text="❌ Отменить план",
            callback_data=f"eplan_cancel:{short_id}"
        )
    )

    # Назад
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="pos_back_to_list")
    )

    return builder.as_markup()


def get_entry_plan_cancel_confirm_kb(plan_id: str) -> InlineKeyboardMarkup:
    """
    Подтверждение отмены Entry Plan

    Args:
        plan_id: ID плана

    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    short_id = plan_id[:8]

    builder.row(
        InlineKeyboardButton(
            text="✅ Да, отменить",
            callback_data=f"eplan_cancel_confirm:{short_id}"
        ),
        InlineKeyboardButton(
            text="❌ Нет",
            callback_data=f"eplan_detail:{short_id}"
        )
    )

    return builder.as_markup()


def get_empty_positions_kb() -> InlineKeyboardMarkup:
    """
    Клавиатура для пустого списка позиций (только кнопка обновления)
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="pos_refresh")
    )

    return builder.as_markup()
