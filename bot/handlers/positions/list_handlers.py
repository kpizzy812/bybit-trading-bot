"""
Хендлеры для списка позиций и ордеров.
"""
import html
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.keyboards.positions_kb import (
    get_positions_with_plans_kb,
    get_empty_positions_kb
)
from services.bybit import BybitClient
from utils.order_filters import filter_user_orders
from bot.handlers.positions.formatters import (
    format_positions_list,
    format_entry_plans_list,
    format_orders_list
)
from bot.utils.safe_edit import safe_edit_text

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "pos_refresh")
async def refresh_positions(callback: CallbackQuery, settings_storage, entry_plan_monitor=None):
    """Обновить список позиций, ордеров и Entry Plans"""
    await callback.answer("🔄 Обновление...")

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)
        positions = await client.get_positions()
        all_orders = await client.get_open_orders()

        # Фильтруем только entry ордера (не reduce_only, не entry plan ордера)
        orders = filter_user_orders(all_orders)

        # Получаем активные Entry Plans
        entry_plans = []
        if entry_plan_monitor:
            for plan_id, plan in entry_plan_monitor.active_plans.items():
                if plan.user_id == user_id:
                    entry_plans.append({
                        'plan_id': plan_id,
                        'symbol': plan.symbol,
                        'side': plan.side,
                        'status': plan.status,
                        'fill_percentage': plan.fill_percentage,
                        'mode': plan.mode
                    })

        if not positions and not orders and not entry_plans:
            await safe_edit_text(
                callback.message,
                "📊 <b>Открытых позиций и ордеров нет</b>\n\n"
                "Используй <b>➕ Открыть сделку</b> чтобы начать торговлю",
                reply_markup=get_empty_positions_kb()
            )
            return

        # Формируем список
        text = ""
        if positions:
            text += "📊 <b>Открытые позиции:</b>\n\n"
            text += await format_positions_list(positions)

        if entry_plans:
            text += "📋 <b>Активные Entry Plans:</b>\n\n"
            text += format_entry_plans_list(entry_plans)

        if orders:
            text += "⏳ <b>Ожидающие ордера:</b>\n\n"
            text += await format_orders_list(orders)

        text += "💡 <i>Нажми для управления</i>"

        await safe_edit_text(
            callback.message, text,
            reply_markup=get_positions_with_plans_kb(positions, orders, entry_plans)
        )

    except Exception as e:
        logger.error(f"Error refreshing positions: {e}")
        await safe_edit_text(callback.message, f"❌ Ошибка при обновлении позиций:\n{html.escape(str(e))}")


@router.callback_query(F.data == "pos_back_to_list")
async def back_to_positions_list(callback: CallbackQuery, settings_storage, entry_plan_monitor=None):
    """Вернуться к списку позиций, ордеров и Entry Plans"""
    await callback.answer()

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)
        positions = await client.get_positions()
        all_orders = await client.get_open_orders()

        # Фильтруем только entry ордера (не reduce_only, не entry plan ордера)
        orders = filter_user_orders(all_orders)

        # Получаем активные Entry Plans
        entry_plans = []
        if entry_plan_monitor:
            for plan_id, plan in entry_plan_monitor.active_plans.items():
                if plan.user_id == user_id:
                    entry_plans.append({
                        'plan_id': plan_id,
                        'symbol': plan.symbol,
                        'side': plan.side,
                        'status': plan.status,
                        'fill_percentage': plan.fill_percentage,
                        'mode': plan.mode
                    })

        if not positions and not orders and not entry_plans:
            await safe_edit_text(
                callback.message,
                "📊 <b>Открытых позиций и ордеров нет</b>\n\n"
                "Используй <b>➕ Открыть сделку</b> чтобы начать торговлю",
                reply_markup=get_empty_positions_kb()
            )
            return

        text = ""
        if positions:
            text += "📊 <b>Открытые позиции:</b>\n\n"
            text += await format_positions_list(positions)

        if entry_plans:
            text += "📋 <b>Активные Entry Plans:</b>\n\n"
            text += format_entry_plans_list(entry_plans)

        if orders:
            text += "⏳ <b>Ожидающие ордера:</b>\n\n"
            text += await format_orders_list(orders)

        text += "💡 <i>Нажми для управления</i>"

        await safe_edit_text(
            callback.message, text,
            reply_markup=get_positions_with_plans_kb(positions, orders, entry_plans)
        )

    except Exception as e:
        logger.error(f"Error going back to positions list: {e}")
        await safe_edit_text(callback.message, f"❌ Ошибка:\n{html.escape(str(e))}")
