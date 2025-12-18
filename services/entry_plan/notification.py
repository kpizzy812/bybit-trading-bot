"""
Entry Plan Notifications

Уведомления пользователям о статусе Entry Plans.
"""
import html
import logging
from aiogram import Bot

from services.entry_plan.models import EntryPlan, EntryOrder

logger = logging.getLogger(__name__)


async def notify_plan_activated(bot: Bot, plan: EntryPlan, placed_count: int):
    """Уведомление об активации плана"""
    try:
        side_emoji = "🟢" if plan.side == "Long" else "🔴"
        orders = plan.get_orders()

        message = f"""
📋 <b>Entry Plan активирован!</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}
📊 Mode: {plan.mode}

<b>Entry Orders ({placed_count}):</b>
"""
        for i, order in enumerate(orders, 1):
            status_icon = "✅" if order.status == "placed" else "❌"
            message += f"{status_icon} E{i}: ${order.price:.2f} ({order.size_pct:.0f}%)\n"

        message += f"""
🛑 <b>Stop:</b> ${plan.stop_price:.2f}
⏰ <b>Valid:</b> {plan.time_valid_hours}h

<i>Ожидаю исполнения ордеров...</i>
"""

        await bot.send_message(
            chat_id=plan.user_id,
            text=message.strip(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send activation notification: {e}")


async def notify_order_filled(bot: Bot, plan: EntryPlan, order: EntryOrder):
    """Уведомление о fill одного ордера"""
    try:
        side_emoji = "🟢" if plan.side == "Long" else "🔴"

        message = f"""
🔔 <b>Entry Order Filled!</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}

⚡ <b>{order.tag}:</b> ${order.fill_price:.2f}
📦 <b>Qty:</b> {order.qty:.4f}

📊 <b>Progress:</b> {plan.fill_percentage:.0f}% ({plan.filled_orders_count}/{len(plan.orders)})
💰 <b>Avg Entry:</b> ${plan.avg_entry_price:.2f}
"""

        await bot.send_message(
            chat_id=plan.user_id,
            text=message.strip(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send fill notification: {e}")


async def notify_plan_completed(bot: Bot, plan: EntryPlan):
    """Уведомление о полном завершении плана"""
    try:
        side_emoji = "🟢" if plan.side == "Long" else "🔴"

        message = f"""
✅ <b>Entry Plan Complete!</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}

⚡ <b>Avg Entry:</b> ${plan.avg_entry_price:.2f}
📦 <b>Total Qty:</b> {plan.filled_qty:.4f}
🛑 <b>Stop:</b> ${plan.stop_price:.2f}

<b>Entry Fills:</b>
"""
        for order in plan.get_filled_orders():
            message += f"   • {order.tag}: ${order.fill_price:.2f} x {order.qty:.4f}\n"

        if plan.targets:
            message += "\n<b>TP Levels:</b>\n"
            for i, target in enumerate(plan.targets, 1):
                message += f"   🎯 TP{i}: ${target['price']:.2f} ({target.get('partial_close_pct', 100)}%)\n"

        message += "\n<i>✅ SL/TP установлены автоматически</i>"

        await bot.send_message(
            chat_id=plan.user_id,
            text=message.strip(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send completion notification: {e}")


async def notify_plan_cancelled(bot: Bot, plan: EntryPlan, reason: str):
    """Уведомление об отмене плана (без позиции)"""
    try:
        reason_escaped = html.escape(str(reason))

        message = f"""
❌ <b>Entry Plan Cancelled</b>

<b>{html.escape(plan.symbol)}</b> {plan.side.upper()}
📋 Mode: {plan.mode}

<b>Reason:</b> {reason_escaped}

<i>Все ордера отменены. Позиция не открыта.</i>
"""

        await bot.send_message(
            chat_id=plan.user_id,
            text=message.strip(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send cancel notification: {e}")


async def notify_plan_cancelled_with_position(bot: Bot, plan: EntryPlan, reason: str):
    """Уведомление об отмене плана с частичной позицией"""
    try:
        side_emoji = "🟢" if plan.side == "Long" else "🔴"
        reason_escaped = html.escape(str(reason))

        message = f"""
⚠️ <b>Entry Plan Cancelled (Partial Position)</b>

{side_emoji} <b>{html.escape(plan.symbol)}</b> {plan.side.upper()}

<b>Reason:</b> {reason_escaped}

📊 <b>Filled:</b> {plan.fill_percentage:.0f}% ({plan.filled_orders_count}/{len(plan.orders)})
⚡ <b>Avg Entry:</b> ${plan.avg_entry_price:.2f}
📦 <b>Qty:</b> {plan.filled_qty:.4f}

🛑 <b>Stop:</b> ${plan.stop_price:.2f}

<i>✅ SL/TP установлены на частичную позицию</i>
"""

        await bot.send_message(
            chat_id=plan.user_id,
            text=message.strip(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send partial cancel notification: {e}")


async def notify_plan_cancelled_position_closed(bot: Bot, plan: EntryPlan, reason: str):
    """Уведомление об отмене плана с закрытием маленькой позиции"""
    try:
        side_emoji = "🟢" if plan.side == "Long" else "🔴"
        reason_escaped = html.escape(str(reason))

        message = f"""
⚠️ <b>Entry Plan Cancelled (Position Closed)</b>

{side_emoji} <b>{html.escape(plan.symbol)}</b> {plan.side.upper()}

<b>Reason:</b> {reason_escaped}

📊 <b>Filled:</b> {plan.fill_percentage:.0f}% ({plan.filled_orders_count}/{len(plan.orders)})
⚡ <b>Avg Entry:</b> ${plan.avg_entry_price:.2f}
📦 <b>Qty:</b> {plan.filled_qty:.4f}

<i>🔄 Позиция закрыта market (fill &lt; {plan.min_fill_pct_to_keep:.0f}%)</i>
"""

        await bot.send_message(
            chat_id=plan.user_id,
            text=message.strip(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send position closed notification: {e}")


async def notify_sl_tp_set_early(bot: Bot, plan: EntryPlan):
    """Уведомление об установке SL и TP после первого fill"""
    try:
        side_emoji = "🟢" if plan.side == "Long" else "🔴"

        message = f"""
🛡️ <b>SL/TP установлены!</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}
📊 <b>Filled:</b> {plan.fill_percentage:.0f}% ({plan.filled_orders_count}/{len(plan.orders)})
📦 <b>Qty:</b> {plan.filled_qty:.4f}

🛑 <b>Stop:</b> ${plan.stop_price:.2f}
"""
        if plan.targets:
            message += f"🎯 <b>TP:</b> {len(plan.targets)} уровней\n"
            for i, t in enumerate(plan.targets, 1):
                message += f"   TP{i}: ${t['price']:.2f} ({t.get('partial_close_pct', 100)}%)\n"

        message += "\n<i>✅ Позиция защищена. Ожидаю остальные entry ордера...</i>"

        await bot.send_message(
            chat_id=plan.user_id,
            text=message.strip(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send SL/TP notification: {e}")


async def notify_tp_updated(bot: Bot, plan: EntryPlan):
    """Уведомление об обновлении TP после добора позиции"""
    try:
        side_emoji = "🟢" if plan.side == "Long" else "🔴"

        message = f"""
🔄 <b>TP обновлены!</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}
📊 <b>Filled:</b> {plan.fill_percentage:.0f}% ({plan.filled_orders_count}/{len(plan.orders)})
📦 <b>New Qty:</b> {plan.filled_qty:.4f}

<i>TP ордера пересчитаны на новый объём позиции.</i>
"""
        await bot.send_message(
            chat_id=plan.user_id,
            text=message.strip(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send TP updated notification: {e}")


async def notify_tp_update_failed(bot: Bot, plan: EntryPlan):
    """Уведомление о неудаче обновления TP"""
    try:
        side_emoji = "🟢" if plan.side == "Long" else "🔴"

        message = f"""
⚠️ <b>Ошибка обновления TP!</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}
📊 <b>Filled:</b> {plan.fill_percentage:.0f}% ({plan.filled_orders_count}/{len(plan.orders)})
📦 <b>Qty:</b> {plan.filled_qty:.4f}

<i>Не удалось пересчитать TP ордера. SL активен. Проверьте позицию!</i>
"""
        await bot.send_message(
            chat_id=plan.user_id,
            text=message.strip(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send TP update failed notification: {e}")
