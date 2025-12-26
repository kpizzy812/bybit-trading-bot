"""
Supervisor Keyboards

Inline keyboards for supervisor advice notifications.
"""
from typing import List, Dict, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_advice_keyboard(
    trade_id: str,
    recommendations: List[Dict[str, Any]]
) -> InlineKeyboardMarkup:
    """
    Build keyboard for advice notification.

    Layout:
        [Action buttons based on recommendations]
        [Ignore] [Mute 30m]
        [Details]
    """
    builder = InlineKeyboardBuilder()

    # Add action buttons for each recommendation
    for rec in recommendations:
        if rec.get('status') != 'pending':
            continue

        action_id = rec.get('action_id', '')
        action_type = rec.get('type', '')
        params = rec.get('params', {})
        urgency = rec.get('urgency', 'low')

        # Get button text and emoji based on type
        button_text = _get_action_button_text(action_type, params, urgency)

        builder.button(
            text=button_text,
            callback_data=f"sv:apply:{trade_id}:{action_id}"
        )

    # Adjust action buttons layout (max 2 per row)
    if recommendations:
        builder.adjust(2)

    # Add control buttons
    builder.row(
        InlineKeyboardButton(
            text="❌ Ignore",
            callback_data=f"sv:reject:{trade_id}:all"
        ),
        InlineKeyboardButton(
            text="🔇 Mute 24h",
            callback_data=f"sv:mute:{trade_id}:1440"
        )
    )

    # Add details button
    builder.row(
        InlineKeyboardButton(
            text="📊 Details",
            callback_data=f"sv:details:{trade_id}"
        )
    )

    return builder.as_markup()


def get_action_confirm_keyboard(
    trade_id: str,
    action_id: str,
    action_type: str
) -> InlineKeyboardMarkup:
    """Confirmation keyboard for action execution."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="✅ Confirm",
            callback_data=f"sv:confirm:{trade_id}:{action_id}"
        ),
        InlineKeyboardButton(
            text="❌ Cancel",
            callback_data=f"sv:cancel:{trade_id}:{action_id}"
        )
    )

    return builder.as_markup()


def get_details_keyboard(trade_id: str) -> InlineKeyboardMarkup:
    """Keyboard for details view."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="⬅️ Back",
            callback_data=f"sv:back:{trade_id}"
        ),
        InlineKeyboardButton(
            text="🔄 Refresh",
            callback_data=f"sv:refresh:{trade_id}"
        )
    )

    return builder.as_markup()


def get_result_keyboard(trade_id: str) -> InlineKeyboardMarkup:
    """Keyboard after action execution."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="📊 View Position",
            callback_data=f"pos_detail:{trade_id.split('_')[0] if '_' in trade_id else 'BTCUSDT'}"
        )
    )

    return builder.as_markup()


def _get_action_button_text(
    action_type: str,
    params: Dict,
    urgency: str
) -> str:
    """Get button text based on action type."""

    # Urgency emoji
    urgency_emoji = {
        "low": "",
        "med": "⚡",
        "high": "🔥",
        "critical": "🚨"
    }.get(urgency, "")

    # Action text
    if action_type == "move_sl":
        new_sl = params.get('new_sl', 0)
        return f"✅ SL → ${new_sl:.2f}"

    elif action_type == "set_break_even":
        new_sl = params.get('new_sl', 0)
        return f"🛡️ BE → ${new_sl:.2f}"

    elif action_type == "take_partial":
        percent = params.get('percent', 25)
        return f"💰 Take {percent}%"

    elif action_type == "close_position":
        return f"{urgency_emoji} 🚪 Close"

    elif action_type == "reduce_position":
        percent = params.get('percent', 50)
        return f"{urgency_emoji} 📉 Reduce {percent}%"

    elif action_type == "adjust_tp":
        return "🎯 Adjust TP"

    elif action_type == "hold":
        return "✋ Hold"

    else:
        return f"✅ {action_type}"


def format_advice_message(
    advice: Dict[str, Any],
    position_data: Dict[str, Any] = None
) -> str:
    """
    Format advice pack into Telegram message.

    Args:
        advice: AdvicePack dict
        position_data: Optional current position data

    Returns:
        Formatted HTML message
    """
    symbol = advice.get('symbol', 'UNKNOWN')
    trade_id = advice.get('trade_id', '')
    market_summary = advice.get('market_summary', '')
    scenario_valid = advice.get('scenario_valid', False)
    time_left = advice.get('time_valid_left_min', 0)
    risk_state = advice.get('risk_state', 'safe')
    price = advice.get('price_at_creation', 0)
    recommendations = advice.get('recommendations', [])

    # Get side from trade_id or position
    side = "LONG"  # Default
    if position_data:
        side = position_data.get('side', 'Long').upper()

    # Risk state emoji
    risk_emoji = {
        "safe": "🟢",
        "medium": "🟡",
        "high": "🟠",
        "critical": "🔴"
    }.get(risk_state, "⚪")

    # Scenario validity
    scenario_emoji = "✅" if scenario_valid else "❌"

    # Get max urgency
    max_urgency = "low"
    for rec in recommendations:
        rec_urgency = rec.get('urgency', 'low')
        if _urgency_level(rec_urgency) > _urgency_level(max_urgency):
            max_urgency = rec_urgency

    urgency_text = max_urgency.upper()

    # Build message
    message = f"""
<b>🤖 Syntra Supervisor</b>

<b>{symbol}</b> {side}
Price: <code>${price:.2f}</code>

Сценарий: {scenario_emoji} {"valid" if scenario_valid else "invalid"}
Риск: {risk_emoji} {risk_state}
Осталось: {_format_time(time_left)}

<b>📋 Рекомендации ({urgency_text}):</b>
"""

    # Add recommendations
    for rec in recommendations:
        rec_type = rec.get('type', '')
        params = rec.get('params', {})
        reasons = rec.get('reason_bullets', [])

        action_text = _get_action_description(rec_type, params)
        message += f"• {action_text}\n"

    # Add reasons
    if recommendations and recommendations[0].get('reason_bullets'):
        message += "\n<b>Причины:</b>\n"
        for reason in recommendations[0]['reason_bullets'][:3]:
            message += f"• <i>{reason}</i>\n"

    # Add market summary
    if market_summary:
        message += f"\n<i>{market_summary}</i>"

    return message.strip()


def _get_action_description(action_type: str, params: Dict) -> str:
    """Get human-readable action description."""

    if action_type == "move_sl":
        new_sl = params.get('new_sl', 0)
        return f"Перенести SL → ${new_sl:.2f}"

    elif action_type == "set_break_even":
        new_sl = params.get('new_sl', 0)
        return f"Установить Breakeven → ${new_sl:.2f}"

    elif action_type == "take_partial":
        percent = params.get('percent', 25)
        target = params.get('target_price')
        if target:
            return f"Зафиксировать {percent}% @ ${target:.2f}"
        return f"Зафиксировать {percent}%"

    elif action_type == "close_position":
        return "🚨 Закрыть позицию полностью"

    elif action_type == "reduce_position":
        percent = params.get('percent', 50)
        return f"Сократить позицию на {percent}%"

    elif action_type == "adjust_tp":
        return "Скорректировать Take Profit"

    elif action_type == "hold":
        return "Удерживать позицию"

    else:
        return f"Action: {action_type}"


def _format_time(minutes: int) -> str:
    """Format minutes to human-readable time."""
    if minutes <= 0:
        return "❌ Истекло"
    elif minutes < 60:
        return f"{minutes}m"
    elif minutes < 1440:
        hours = minutes // 60
        return f"{hours}h"
    else:
        days = minutes // 1440
        return f"{days}d"


def _urgency_level(urgency: str) -> int:
    """Get numeric urgency level for comparison."""
    levels = {"low": 0, "med": 1, "high": 2, "critical": 3}
    return levels.get(urgency.lower(), 0)
