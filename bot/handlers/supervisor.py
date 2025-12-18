"""
Supervisor Handlers

Telegram handlers for supervisor advice notifications and actions.

Callback data format:
    sv:apply:{trade_id}:{action_id}   - Apply recommendation
    sv:reject:{trade_id}:{action_id}  - Reject recommendation
    sv:mute:{trade_id}:{minutes}      - Mute notifications
    sv:details:{trade_id}             - Show details
    sv:confirm:{trade_id}:{action_id} - Confirm action
    sv:cancel:{trade_id}:{action_id}  - Cancel action
    sv:back:{trade_id}                - Back to main view
    sv:refresh:{trade_id}             - Refresh advice
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from aiogram import Router, F
from aiogram.types import CallbackQuery

from services.supervisor_client import get_supervisor_client, AdvicePack
from services.bybit import BybitClient
from services.events import event_bus, SupervisorAdviceEvent
from bot.keyboards.supervisor_kb import (
    get_advice_keyboard,
    get_action_confirm_keyboard,
    get_result_keyboard,
    format_advice_message,
)

import config

logger = logging.getLogger(__name__)

router = Router()


# ============================================================================
# STATE STORAGE (in-memory for simplicity)
# ============================================================================

# Store last advice for each trade
_advice_cache: Dict[str, Dict] = {}


def cache_advice(trade_id: str, advice: Dict):
    """Cache advice for later use."""
    _advice_cache[trade_id] = advice


def get_cached_advice(trade_id: str) -> Optional[Dict]:
    """Get cached advice."""
    return _advice_cache.get(trade_id)


# ============================================================================
# HANDLERS
# ============================================================================


@router.callback_query(F.data.startswith("sv:apply:"))
async def apply_recommendation(callback: CallbackQuery):
    """Handle apply recommendation button."""
    await callback.answer("⏳ Применяю...")

    # Parse callback data: sv:apply:{trade_id}:{action_id}
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("❌ Invalid callback data", show_alert=True)
        return

    trade_id = parts[2]
    action_id = parts[3]

    # Get cached advice
    advice = get_cached_advice(trade_id)
    if not advice:
        await callback.answer("❌ Advice expired", show_alert=True)
        return

    # Find the recommendation
    recommendation = None
    for rec in advice.get('recommendations', []):
        if rec.get('action_id') == action_id:
            recommendation = rec
            break

    if not recommendation:
        await callback.answer("❌ Recommendation not found", show_alert=True)
        return

    # Check guards and validate
    action_type = recommendation.get('type', '')
    params = recommendation.get('params', {})
    user_id = callback.from_user.id

    # Execute action based on type
    try:
        client = BybitClient(testnet=config.DEFAULT_TESTNET_MODE)
        symbol = advice.get('symbol', 'BTCUSDT')
        supervisor_client = get_supervisor_client()

        result = None
        error = None

        if action_type == "move_sl":
            new_sl = params.get('new_sl')
            if new_sl:
                result = await _execute_move_sl(client, symbol, new_sl)

        elif action_type == "set_break_even":
            new_sl = params.get('new_sl')
            if new_sl:
                result = await _execute_move_sl(client, symbol, new_sl)

        elif action_type == "take_partial":
            percent = params.get('percent', 25)
            result = await _execute_partial_close(client, symbol, percent)

        elif action_type == "close_position":
            result = await _execute_close_position(client, symbol)

        elif action_type == "reduce_position":
            percent = params.get('percent', 50)
            result = await _execute_partial_close(client, symbol, percent)

        else:
            error = f"Unknown action type: {action_type}"

        # Log result to supervisor
        if result:
            await supervisor_client.log_action_result(
                trade_id=trade_id,
                action_id=action_id,
                status="applied",
                details=result
            )

            # Update message
            await callback.message.edit_text(
                f"✅ <b>Действие выполнено!</b>\n\n"
                f"<b>{symbol}</b>\n"
                f"Action: {_get_action_name(action_type)}\n"
                f"Result: {result.get('message', 'Success')}\n\n"
                f"<i>⏰ {datetime.utcnow().strftime('%H:%M:%S')} UTC</i>",
                reply_markup=get_result_keyboard(trade_id),
                parse_mode="HTML"
            )

        else:
            await supervisor_client.log_action_result(
                trade_id=trade_id,
                action_id=action_id,
                status="failed",
                details={"error": error or "Unknown error"}
            )

            await callback.answer(f"❌ {error or 'Action failed'}", show_alert=True)

    except Exception as e:
        logger.exception(f"Error applying recommendation: {e}")
        await callback.answer(f"❌ Error: {str(e)[:100]}", show_alert=True)


@router.callback_query(F.data.startswith("sv:reject:"))
async def reject_recommendation(callback: CallbackQuery):
    """Handle reject/ignore button."""
    # Parse callback data: sv:reject:{trade_id}:{action_id}
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("❌ Invalid callback data", show_alert=True)
        return

    trade_id = parts[2]
    action_id = parts[3]

    # Log rejection
    supervisor_client = get_supervisor_client()
    await supervisor_client.log_action_result(
        trade_id=trade_id,
        action_id=action_id,
        status="rejected",
        details={"reason": "user_ignored"}
    )

    await callback.answer("✅ Ignored")

    # Update message
    await callback.message.edit_text(
        f"<i>⏸️ Рекомендации проигнорированы</i>\n\n"
        f"<i>Следующий совет через ~15 минут</i>",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("sv:mute:"))
async def mute_notifications(callback: CallbackQuery):
    """Handle mute button."""
    # Parse callback data: sv:mute:{trade_id}:{minutes}
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("❌ Invalid callback data", show_alert=True)
        return

    trade_id = parts[2]
    minutes = int(parts[3]) if parts[3].isdigit() else 30

    # TODO: Store mute in supervisor state
    await callback.answer(f"🔇 Muted for {minutes} minutes")

    # Update message
    await callback.message.edit_text(
        f"<i>🔇 Уведомления отключены на {minutes} минут</i>",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("sv:details:"))
async def show_details(callback: CallbackQuery):
    """Show detailed advice information."""
    # Parse callback data: sv:details:{trade_id}
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("❌ Invalid callback data", show_alert=True)
        return

    trade_id = parts[2]

    # Get cached advice
    advice = get_cached_advice(trade_id)
    if not advice:
        await callback.answer("❌ Advice expired", show_alert=True)
        return

    # Build detailed message
    recommendations = advice.get('recommendations', [])

    details = f"<b>📊 Детали рекомендаций</b>\n\n"
    details += f"<b>Trade ID:</b> <code>{trade_id[:20]}...</code>\n"
    details += f"<b>Symbol:</b> {advice.get('symbol')}\n"
    details += f"<b>Price:</b> ${advice.get('price_at_creation', 0):.2f}\n"
    details += f"<b>Risk State:</b> {advice.get('risk_state', 'unknown')}\n"
    details += f"<b>Scenario Valid:</b> {'✅' if advice.get('scenario_valid') else '❌'}\n"
    details += f"<b>Time Left:</b> {advice.get('time_valid_left_min', 0)} min\n\n"

    for i, rec in enumerate(recommendations, 1):
        rec_type = rec.get('type', '')
        urgency = rec.get('urgency', 'low')
        confidence = rec.get('confidence', 0)
        reasons = rec.get('reason_bullets', [])

        details += f"<b>{i}. {_get_action_name(rec_type)}</b>\n"
        details += f"   Urgency: {urgency.upper()}\n"
        details += f"   Confidence: {confidence}%\n"

        if reasons:
            details += "   Reasons:\n"
            for r in reasons[:3]:
                details += f"   • {r}\n"

        details += "\n"

    await callback.message.edit_text(
        details,
        parse_mode="HTML",
        reply_markup=get_advice_keyboard(trade_id, recommendations)
    )

    await callback.answer()


@router.callback_query(F.data.startswith("sv:back:"))
async def go_back(callback: CallbackQuery):
    """Go back to main advice view."""
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer()
        return

    trade_id = parts[2]

    # Get cached advice
    advice = get_cached_advice(trade_id)
    if not advice:
        await callback.answer("❌ Advice expired", show_alert=True)
        return

    # Show main advice message
    message_text = format_advice_message(advice)
    recommendations = advice.get('recommendations', [])

    await callback.message.edit_text(
        message_text,
        parse_mode="HTML",
        reply_markup=get_advice_keyboard(trade_id, recommendations)
    )

    await callback.answer()


# ============================================================================
# ACTION EXECUTORS
# ============================================================================


async def _execute_move_sl(
    client: BybitClient,
    symbol: str,
    new_sl: float
) -> Dict[str, Any]:
    """Execute move SL action."""
    try:
        # Get current position to validate
        positions = await client.get_positions(symbol=symbol)

        if not positions:
            return {"success": False, "message": "Position not found"}

        position = positions[0]
        side = position.get('side')
        current_sl = position.get('stopLoss', '')
        entry_price = float(position.get('avgPrice', 0))

        # Validate SL not widening risk
        if current_sl:
            current_sl_float = float(current_sl)
            if side == "Buy":  # Long
                if new_sl < current_sl_float:
                    return {
                        "success": False,
                        "message": "SL would widen risk (Long: new SL must be >= current)"
                    }
            else:  # Short
                if new_sl > current_sl_float:
                    return {
                        "success": False,
                        "message": "SL would widen risk (Short: new SL must be <= current)"
                    }

        # Update SL
        await client.update_trading_stop(
            symbol=symbol,
            stop_loss=str(new_sl),
            sl_trigger_by="MarkPrice"
        )

        return {
            "success": True,
            "message": f"SL moved to ${new_sl:.2f}",
            "new_sl": new_sl
        }

    except Exception as e:
        logger.error(f"Move SL error: {e}")
        return {"success": False, "message": str(e)}


async def _execute_partial_close(
    client: BybitClient,
    symbol: str,
    percent: int
) -> Dict[str, Any]:
    """Execute partial close action."""
    try:
        result = await client.partial_close(symbol, float(percent))

        return {
            "success": True,
            "message": f"Closed {percent}% ({result.get('closed_qty', 0)} qty)",
            "closed_qty": result.get('closed_qty'),
            "percent": percent
        }

    except Exception as e:
        logger.error(f"Partial close error: {e}")
        return {"success": False, "message": str(e)}


async def _execute_close_position(
    client: BybitClient,
    symbol: str
) -> Dict[str, Any]:
    """Execute full close action."""
    try:
        await client.close_position(symbol)

        return {
            "success": True,
            "message": "Position closed"
        }

    except Exception as e:
        logger.error(f"Close position error: {e}")
        return {"success": False, "message": str(e)}


# ============================================================================
# HELPERS
# ============================================================================


def _get_action_name(action_type: str) -> str:
    """Get human-readable action name."""
    names = {
        "move_sl": "Move Stop Loss",
        "set_break_even": "Set Breakeven",
        "take_partial": "Take Partial Profit",
        "close_position": "Close Position",
        "reduce_position": "Reduce Position",
        "adjust_tp": "Adjust Take Profit",
        "hold": "Hold Position"
    }
    return names.get(action_type, action_type)


# ============================================================================
# NOTIFICATION SENDER (called from supervisor monitor)
# ============================================================================


async def send_advice_notification(
    bot,
    user_id: int,
    advice: AdvicePack
) -> Optional[int]:
    """
    Send advice notification to user.

    Args:
        bot: Telegram bot instance
        user_id: Telegram user ID
        advice: AdvicePack to send

    Returns:
        Message ID if sent successfully
    """
    try:
        # Convert to dict if needed
        advice_dict = advice.__dict__ if hasattr(advice, '__dict__') else advice

        # Cache advice for callback handlers
        cache_advice(advice_dict.get('trade_id', ''), advice_dict)

        # Format message
        message_text = format_advice_message(advice_dict)
        recommendations = advice_dict.get('recommendations', [])

        # Send message
        msg = await bot.send_message(
            chat_id=user_id,
            text=message_text,
            parse_mode="HTML",
            reply_markup=get_advice_keyboard(
                advice_dict.get('trade_id', ''),
                recommendations
            )
        )

        logger.info(
            f"Sent supervisor advice to {user_id}: "
            f"{advice_dict.get('symbol')} {advice_dict.get('risk_state')}"
        )

        return msg.message_id

    except Exception as e:
        logger.error(f"Failed to send advice notification: {e}")
        return None


# ============================================================================
# EVENT HANDLERS (called via event_bus from position_monitor)
# ============================================================================

# Bot instance for event handlers (set via setup_supervisor_events)
_bot_instance = None


def setup_supervisor_events(bot):
    """
    Initialize event handlers with bot instance.

    Call this from main.py after creating bot:
        from bot.handlers.supervisor import setup_supervisor_events
        setup_supervisor_events(bot)
    """
    global _bot_instance
    _bot_instance = bot

    # Register event handler
    event_bus.subscribe(SupervisorAdviceEvent, _handle_supervisor_advice_event)
    logger.info("Supervisor event handlers registered")


async def _handle_supervisor_advice_event(event: SupervisorAdviceEvent):
    """Handle SupervisorAdviceEvent from position_monitor"""
    if _bot_instance is None:
        logger.warning("Bot instance not set, skipping advice notification")
        return

    await send_advice_notification(
        bot=_bot_instance,
        user_id=event.user_id,
        advice=event.advice
    )
