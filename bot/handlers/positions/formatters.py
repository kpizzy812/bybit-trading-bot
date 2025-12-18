"""
Форматирование данных позиций, ордеров и Entry Plans для отображения.
"""
import html
import logging

logger = logging.getLogger(__name__)


def format_entry_plan_detail(plan) -> str:
    """Форматирование детальной информации об Entry Plan"""
    side_emoji = "🟢" if plan.side == "Long" else "🔴"

    # Статус
    status_map = {
        "pending": "⏳ Ожидает активации",
        "active": "📋 Активен",
        "partial": "🔄 Частично заполнен",
        "filled": "✅ Заполнен",
        "cancelled": "❌ Отменён"
    }
    status_text = status_map.get(plan.status, plan.status)

    # Экранируем опасные поля
    safe_mode = html.escape(str(plan.mode)) if plan.mode else "N/A"

    text = f"""
📋 <b>Entry Plan</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}
📊 Mode: {safe_mode}
📈 Status: {status_text}

<b>Progress:</b>
Filled: {plan.fill_percentage:.0f}% ({plan.filled_orders_count}/{len(plan.orders)})
"""

    if plan.filled_qty > 0:
        text += f"Qty: {plan.filled_qty:.4f}\n"
        text += f"Avg Entry: ${plan.avg_entry_price:.2f}\n"

    text += f"\n<b>Entry Orders:</b>\n"

    for i, order_dict in enumerate(plan.orders, 1):
        status = order_dict.get('status', 'pending')
        price = order_dict.get('price', 0)
        size_pct = order_dict.get('size_pct', 0)
        tag = order_dict.get('tag', f'E{i}')

        if status == 'filled':
            fill_price = order_dict.get('fill_price', price)
            status_icon = "✅"
            price_text = f"${fill_price:.2f}"
        elif status == 'placed':
            status_icon = "⏳"
            price_text = f"${price:.2f}"
        elif status == 'cancelled':
            status_icon = "❌"
            price_text = f"${price:.2f}"
        else:
            status_icon = "⚪"
            price_text = f"${price:.2f}"

        safe_tag = html.escape(str(tag))
        text += f"  {status_icon} {safe_tag}: {price_text} ({size_pct:.0f}%)\n"

    text += f"""
<b>Risk Management:</b>
🛑 Stop: ${plan.stop_price:.2f}
"""

    if plan.targets:
        text += "<b>Targets:</b>\n"
        for i, t in enumerate(plan.targets, 1):
            text += f"  🎯 TP{i}: ${t['price']:.2f} ({t.get('partial_close_pct', 100)}%)\n"

    # Cancel conditions
    if plan.cancel_if:
        text += f"\n<b>Cancel if:</b>\n"
        for cond in plan.cancel_if:
            safe_cond = html.escape(str(cond))
            text += f"  • {safe_cond}\n"

    text += f"\n⏰ Valid: {plan.time_valid_hours}h"

    if plan.is_activated and plan.activated_at:
        text += f"\n✅ Activated"

    if plan.sl_set:
        text += f"\n🛡️ SL set on position"

    text += "\n\n💡 Выбери действие ниже:"

    return text.strip()


def format_entry_plans_list(entry_plans: list) -> str:
    """Форматирование списка Entry Plans"""
    text = ""

    for ep in entry_plans:
        side_emoji = "🟢" if ep['side'] == "Long" else "🔴"

        if ep['status'] == "partial":
            status_emoji = "🔄"
        elif ep['status'] == "active":
            status_emoji = "📋"
        elif ep['status'] == "pending":
            status_emoji = "⏳"
        else:
            status_emoji = "📋"

        text += (
            f"{status_emoji} {side_emoji} <b>{ep['symbol']}</b> {ep['mode'].upper()}\n"
            f"   Filled: {ep['fill_percentage']:.0f}%\n\n"
        )

    return text


async def format_positions_list(positions: list) -> str:
    """Форматирование списка позиций"""
    text = ""

    for pos in positions:
        symbol = pos.get('symbol')
        side = pos.get('side')
        size = float(pos.get('size', 0))
        entry_price = float(pos.get('avgPrice', 0))
        mark_price = float(pos.get('markPrice', 0))
        unrealized_pnl = float(pos.get('unrealisedPnl', 0))
        leverage = pos.get('leverage', '?')

        # Форматирование liqPrice
        liq_price_raw = pos.get('liqPrice', '')
        try:
            liq_price_float = float(liq_price_raw) if liq_price_raw else 0
            liq_price = f"${liq_price_float:.2f}" if liq_price_float > 0 else "∞"
        except (ValueError, TypeError):
            liq_price = "N/A"

        # ROE%
        roe = 0
        if entry_price > 0:
            roe = (unrealized_pnl / (size * entry_price)) * float(leverage) * 100

        # Эмодзи
        side_emoji = "🟢" if side == "Buy" else "🔴"
        pnl_emoji = "💰" if unrealized_pnl >= 0 else "📉"

        text += (
            f"{side_emoji} <b>{symbol}</b> {side}\n"
            f"  Size: {size} | Leverage: {leverage}x\n"
            f"  Entry: ${entry_price:.4f} | Mark: ${mark_price:.4f}\n"
            f"  {pnl_emoji} PnL: ${unrealized_pnl:.2f} ({roe:+.2f}%)\n"
            f"  Liq: {liq_price}\n\n"
        )

    return text


async def format_orders_list(orders: list) -> str:
    """Форматирование списка ордеров"""
    text = ""

    for order in orders:
        symbol = order.get('symbol')
        side = order.get('side')
        price = float(order.get('price', 0))
        qty = order.get('qty', '0')
        order_type = order.get('orderType', 'Limit')

        # Эмодзи
        side_emoji = "🟢" if side == "Buy" else "🔴"

        text += (
            f"⏳ {side_emoji} <b>{symbol}</b> {side}\n"
            f"   {order_type} @ ${price:.4f}\n"
            f"   Qty: {qty}\n\n"
        )

    return text


async def format_order_detail(order: dict) -> str:
    """Форматирование детальной информации об ордере"""
    symbol = order.get('symbol')
    side = order.get('side')
    order_type = order.get('orderType', 'Limit')
    price = float(order.get('price', 0))
    qty = order.get('qty', '0')
    created_time = order.get('createdTime', '')
    order_status = order.get('orderStatus', 'New')

    # SL/TP на ордере
    stop_loss = order.get('stopLoss', '')
    take_profit = order.get('takeProfit', '')

    # Эмодзи
    side_emoji = "🟢" if side == "Buy" else "🔴"

    text = f"""
⏳ <b>{symbol} {side_emoji} {side}</b>

<b>Ордер:</b>
Тип: {order_type}
Цена: ${price:.4f}
Количество: {qty}
Статус: {order_status}

<b>Risk Management:</b>
SL: {stop_loss if stop_loss else '❌ Not Set'}
TP: {take_profit if take_profit else '❌ Not Set'}

💡 Нажми "Отменить ордер" чтобы отменить
"""

    return text.strip()


async def format_position_detail(position: dict, tp_orders: list = None) -> str:
    """
    Форматирование детальной информации о позиции.

    Args:
        position: Данные позиции от Bybit API
        tp_orders: Список ladder TP ордеров [{'price': float, 'qty': str}]
    """
    symbol = position.get('symbol')
    side = position.get('side')
    size = float(position.get('size', 0))
    entry_price = float(position.get('avgPrice', 0))
    mark_price = float(position.get('markPrice', 0))
    leverage = position.get('leverage', '?')
    unrealized_pnl = float(position.get('unrealisedPnl', 0))
    realized_pnl = float(position.get('cumRealisedPnl', 0))

    # Форматирование liqPrice
    liq_price_raw = position.get('liqPrice', '')
    try:
        liq_price_float = float(liq_price_raw) if liq_price_raw else 0
        liq_price = f"${liq_price_float:.2f}" if liq_price_float > 0 else "∞"
    except (ValueError, TypeError):
        liq_price = "N/A"

    # SL/TP из позиции (set_trading_stop)
    stop_loss = position.get('stopLoss', '')
    take_profit = position.get('takeProfit', '')

    # ROE%
    roe = 0
    if entry_price > 0:
        roe = (unrealized_pnl / (size * entry_price)) * float(leverage) * 100

    # Эмодзи
    side_emoji = "🟢" if side == "Buy" else "🔴"

    text = f"""
📈 <b>{symbol} {side_emoji} {side}</b>

<b>Позиция:</b>
Entry: ${entry_price:.4f}
Mark Price: ${mark_price:.4f}
Liq Price: {liq_price}

Size: {size}
Leverage: {leverage}x

<b>PnL:</b>
Unrealized: ${unrealized_pnl:.2f} ({roe:+.2f}%)
Realized: ${realized_pnl:.2f}

<b>Risk Management:</b>
SL: {stop_loss if stop_loss else '❌ Not Set'}
"""

    # Форматируем TP
    if take_profit:
        # TP из trading stop (одиночный)
        text += f"TP: {take_profit}\n"
    elif tp_orders:
        # Ladder TP ордера
        text += f"TP: <i>Ladder ({len(tp_orders)} levels)</i>\n"
        for i, tp in enumerate(tp_orders, 1):
            text += f"  🎯 TP{i}: ${tp['price']:.2f} (qty: {tp['qty']})\n"
    else:
        text += "TP: ❌ Not Set\n"

    text += "\n💡 Выбери действие ниже:"

    return text.strip()
