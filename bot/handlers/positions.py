"""
Хендлеры для управления позициями
"""
import html

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.keyboards.positions_kb import (
    get_positions_list_kb,
    get_positions_with_plans_kb,
    get_position_detail_kb,
    get_order_detail_kb,
    get_entry_plan_detail_kb,
    get_entry_plan_cancel_confirm_kb,
    get_move_sl_confirmation_kb,
    get_close_confirmation_kb,
    get_panic_close_all_confirmation_kb,
    get_empty_positions_kb
)
from bot.keyboards.main_menu import get_main_menu
from services.bybit import BybitClient, BybitError
import logging

logger = logging.getLogger(__name__)
router = Router()


class PositionStates(StatesGroup):
    """Состояния для управления позициями"""
    entering_new_sl = State()  # Ввод новой цены SL


# ============================================================
# CALLBACK: Refresh позиций
# ============================================================

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
        orders = []
        for o in all_orders:
            if o.get('reduceOnly', False):
                continue
            order_link_id = o.get('orderLinkId', '')
            if order_link_id.startswith('EP:'):
                continue
            orders.append(o)

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
            await callback.message.edit_text(
                "📊 <b>Открытых позиций и ордеров нет</b>\n\n"
                "Используй <b>➕ Открыть сделку</b> чтобы начать торговлю",
                reply_markup=get_empty_positions_kb()
            )
            return

        # Формируем список
        text = ""
        if positions:
            text += "📊 <b>Открытые позиции:</b>\n\n"
            text += await _format_positions_list(positions)

        if entry_plans:
            text += "📋 <b>Активные Entry Plans:</b>\n\n"
            text += _format_entry_plans_list(entry_plans)

        if orders:
            text += "⏳ <b>Ожидающие ордера:</b>\n\n"
            text += await _format_orders_list(orders)

        text += "💡 <i>Нажми для управления</i>"

        await callback.message.edit_text(
            text,
            reply_markup=get_positions_with_plans_kb(positions, orders, entry_plans)
        )

    except Exception as e:
        logger.error(f"Error refreshing positions: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при обновлении позиций:\n{html.escape(str(e))}"
        )


# ============================================================
# CALLBACK: Детали позиции
# ============================================================

@router.callback_query(F.data.startswith("pos_detail:"))
async def show_position_detail(callback: CallbackQuery, settings_storage):
    """Показать детали конкретной позиции"""
    await callback.answer()

    # Парсим symbol из callback data
    symbol = callback.data.split(":")[1]

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)
        positions = await client.get_positions(symbol=symbol)

        if not positions:
            await callback.message.edit_text(
                f"❌ Позиция {symbol} не найдена"
            )
            return

        position = positions[0]

        # Ищем ladder TP ордера для этой позиции
        tp_orders = []
        try:
            all_orders = await client.get_open_orders(symbol=symbol)
            for o in all_orders:
                # Ladder TP ордера: reduce_only + цена в нужном направлении
                if o.get('reduceOnly', False):
                    tp_orders.append({
                        'price': float(o.get('price', 0)),
                        'qty': o.get('qty', '0')
                    })
            # Сортируем по цене
            tp_orders.sort(key=lambda x: x['price'])
        except Exception as e:
            logger.warning(f"Error fetching TP orders: {e}")

        # Формируем детальную информацию
        text = await _format_position_detail(position, tp_orders=tp_orders)

        await callback.message.edit_text(
            text,
            reply_markup=get_position_detail_kb(symbol)
        )

    except Exception as e:
        logger.error(f"Error showing position detail: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при получении позиции:\n{html.escape(str(e))}"
        )


# ============================================================
# CALLBACK: Partial Close
# ============================================================

@router.callback_query(F.data.startswith("pos_partial:"))
async def partial_close_position(callback: CallbackQuery, settings_storage, trade_logger):
    """Частичное закрытие позиции"""
    # Парсим: pos_partial:SYMBOL:PERCENT
    parts = callback.data.split(":")
    symbol = parts[1]
    percent = int(parts[2])

    await callback.answer(f"Закрываю {percent}%...")

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)

        # Получаем позицию ДО закрытия для PnL
        positions_before = await client.get_positions(symbol=symbol)
        if positions_before:
            position = positions_before[0]
            unrealized_pnl_total = float(position.get('unrealisedPnl', 0))
            mark_price = float(position.get('markPrice', 0))

            # PnL пропорционально закрытой части
            partial_pnl = unrealized_pnl_total * (percent / 100)
        else:
            mark_price = 0
            partial_pnl = 0

        # Выполняем partial close
        result = await client.partial_close(symbol=symbol, percent=percent)

        # Логируем частичное закрытие
        try:
            await trade_logger.update_trade_on_close(
                user_id=user_id,
                symbol=symbol,
                exit_price=mark_price,
                pnl_usd=partial_pnl,
                is_partial=True,
                testnet=testnet
            )
        except Exception as log_error:
            logger.error(f"Failed to log partial close: {log_error}")

        # Успешное закрытие
        await callback.message.edit_text(
            f"✅ <b>Позиция частично закрыта!</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Закрыто: {result['closed_qty']} ({percent}%)\n"
            f"Было: {result['total_size']}\n"
            f"PnL: ${partial_pnl:+.2f}\n\n"
            f"💡 Используй <b>📊 Позиции</b> чтобы проверить текущее состояние"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except BybitError as e:
        logger.error(f"Error partial closing position: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка при закрытии позиции</b>\n\n"
            f"{html.escape(str(e))}\n\n"
            f"Попробуй снова или обратись к главному меню"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())


# ============================================================
# CALLBACK: Close Market (полное закрытие)
# ============================================================

@router.callback_query(F.data.startswith("pos_close:"))
async def close_position_confirmation(callback: CallbackQuery):
    """Запрос подтверждения закрытия позиции"""
    await callback.answer()

    # Парсим symbol
    symbol = callback.data.split(":")[1]

    await callback.message.edit_text(
        f"⚠️ <b>Подтверждение закрытия</b>\n\n"
        f"Ты уверен, что хочешь закрыть позицию {symbol} по рынку?\n\n"
        f"Это действие нельзя отменить!",
        reply_markup=get_close_confirmation_kb(symbol, percent=100)
    )


@router.callback_query(F.data.startswith("pos_close_confirm:"))
async def close_position_confirmed(callback: CallbackQuery, settings_storage, trade_logger):
    """Закрытие позиции после подтверждения"""
    # Парсим: pos_close_confirm:SYMBOL:PERCENT
    parts = callback.data.split(":")
    symbol = parts[1]
    percent = int(parts[2])

    await callback.answer("Закрываю позицию...")

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)

        # Получаем позицию ДО закрытия для PnL
        positions_before = await client.get_positions(symbol=symbol)
        if positions_before:
            position = positions_before[0]
            unrealized_pnl = float(position.get('unrealisedPnl', 0))
            mark_price = float(position.get('markPrice', 0))
        else:
            unrealized_pnl = 0
            mark_price = 0

        if percent == 100:
            # Полное закрытие
            await client.close_position(symbol=symbol)

            # Логируем полное закрытие
            try:
                await trade_logger.update_trade_on_close(
                    user_id=user_id,
                    symbol=symbol,
                    exit_price=mark_price,
                    pnl_usd=unrealized_pnl,
                    is_partial=False,
                    testnet=testnet
                )
            except Exception as log_error:
                logger.error(f"Failed to log full close: {log_error}")

            msg = f"✅ <b>Позиция {symbol} закрыта!</b>\nPnL: ${unrealized_pnl:+.2f}"
        else:
            # Partial close
            partial_pnl = unrealized_pnl * (percent / 100)
            result = await client.partial_close(symbol=symbol, percent=percent)

            # Логируем частичное закрытие
            try:
                await trade_logger.update_trade_on_close(
                    user_id=user_id,
                    symbol=symbol,
                    exit_price=mark_price,
                    pnl_usd=partial_pnl,
                    is_partial=True,
                    testnet=testnet
                )
            except Exception as log_error:
                logger.error(f"Failed to log partial close: {log_error}")

            msg = (
                f"✅ <b>Позиция частично закрыта!</b>\n\n"
                f"Symbol: {symbol}\n"
                f"Закрыто: {result['closed_qty']} ({percent}%)\n"
                f"PnL: ${partial_pnl:+.2f}"
            )

        await callback.message.edit_text(
            msg + "\n\n💡 Используй <b>📊 Позиции</b> чтобы проверить статус"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except BybitError as e:
        logger.error(f"Error closing position: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка при закрытии</b>\n\n{html.escape(str(e))}"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())


# ============================================================
# CALLBACK: Move SL
# ============================================================

@router.callback_query(F.data.startswith("pos_move_sl:"))
async def move_sl_request(callback: CallbackQuery, state: FSMContext):
    """Запрос на ввод новой цены SL"""
    await callback.answer()

    # Парсим symbol
    symbol = callback.data.split(":")[1]

    # Сохраняем symbol в state
    await state.update_data(move_sl_symbol=symbol)
    await state.set_state(PositionStates.entering_new_sl)

    await callback.message.edit_text(
        f"🧷 <b>Перемещение Stop Loss для {symbol}</b>\n\n"
        f"Введи новую цену стоп-лосса:\n\n"
        f"⚠️ Для Long позиции: SL должен быть ниже entry\n"
        f"⚠️ Для Short позиции: SL должен быть выше entry\n\n"
        f"Отправь цену числом (например: 135.50) или /cancel для отмены"
    )


@router.message(PositionStates.entering_new_sl)
async def move_sl_execute(message: Message, state: FSMContext, settings_storage):
    """Выполнение перемещения SL"""
    # Проверка на отмену
    if message.text.lower() == '/cancel':
        await state.clear()
        await message.answer(
            "❌ Перемещение SL отменено",
            reply_markup=get_main_menu()
        )
        return

    # Получаем данные из state
    data = await state.get_data()
    symbol = data.get('move_sl_symbol')

    # Парсим новую цену SL
    try:
        new_sl = float(message.text.strip())
        new_sl_str = str(new_sl)
    except ValueError:
        await message.answer(
            "❌ Неверный формат цены. Введи число (например: 135.50) или /cancel"
        )
        return

    user_id = message.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)

        # Выполняем move SL
        result = await client.move_sl(symbol=symbol, new_sl_price=new_sl_str)

        # Успех
        await state.clear()
        await message.answer(
            f"✅ <b>Stop Loss перемещён!</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Entry: ${result['entry_price']:.4f}\n"
            f"Новый SL: ${result['new_sl']}\n\n"
            f"💡 Позиция теперь защищена новым стопом\n\n"
            f"Используй главное меню 👇",
            reply_markup=get_main_menu()
        )

    except BybitError as e:
        logger.error(f"Error moving SL: {e}")
        await state.clear()
        await message.answer(
            f"❌ <b>Ошибка при перемещении SL</b>\n\n{html.escape(str(e))}",
            reply_markup=get_main_menu()
        )


# ============================================================
# CALLBACK: Panic Close All
# ============================================================

@router.callback_query(F.data == "pos_panic_close_all")
async def panic_close_all_confirmation(callback: CallbackQuery):
    """Запрос подтверждения Panic Close All"""
    await callback.answer()

    await callback.message.edit_text(
        "🧯 <b>PANIC CLOSE ALL</b>\n\n"
        "⚠️⚠️⚠️ <b>ВНИМАНИЕ!</b> ⚠️⚠️⚠️\n\n"
        "Ты уверен, что хочешь закрыть ВСЕ открытые позиции по рынку?\n\n"
        "Это действие нельзя отменить!",
        reply_markup=get_panic_close_all_confirmation_kb()
    )


@router.callback_query(F.data == "pos_panic_confirm")
async def panic_close_all_execute(callback: CallbackQuery, settings_storage, trade_logger):
    """Выполнение Panic Close All"""
    await callback.answer("🧯 Закрываю все позиции...")

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)

        # Получаем все позиции
        positions = await client.get_positions()

        if not positions:
            await callback.message.edit_text(
                "📊 Нет открытых позиций для закрытия"
            )
            await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
            return

        # Закрываем все позиции
        closed_symbols = []
        errors = []

        for position in positions:
            symbol = position.get('symbol')
            unrealized_pnl = float(position.get('unrealisedPnl', 0))
            mark_price = float(position.get('markPrice', 0))

            try:
                await client.close_position(symbol=symbol)
                closed_symbols.append(f"{symbol} (${unrealized_pnl:+.2f})")

                # Логируем закрытие
                try:
                    await trade_logger.update_trade_on_close(
                        user_id=user_id,
                        symbol=symbol,
                        exit_price=mark_price,
                        pnl_usd=unrealized_pnl,
                        is_partial=False,
                        testnet=testnet
                    )
                except Exception as log_error:
                    logger.error(f"Failed to log panic close for {symbol}: {log_error}")

                logger.info(f"Panic closed: {symbol}")
            except Exception as e:
                logger.error(f"Error panic closing {symbol}: {e}")
                errors.append(f"{symbol}: {html.escape(str(e))}")

        # Результат
        result_text = "🧯 <b>Panic Close All выполнен</b>\n\n"

        if closed_symbols:
            result_text += f"✅ Закрыто позиций: {len(closed_symbols)}\n"
            result_text += "• " + "\n• ".join(closed_symbols) + "\n\n"

        if errors:
            result_text += f"❌ Ошибки ({len(errors)}):\n"
            result_text += "• " + "\n• ".join(errors) + "\n\n"

        result_text += "💡 Проверь статус в <b>📊 Позиции</b>"

        await callback.message.edit_text(result_text)
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except Exception as e:
        logger.error(f"Error during panic close all: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при Panic Close:\n{html.escape(str(e))}"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())


# ============================================================
# CALLBACK: Детали ордера
# ============================================================

@router.callback_query(F.data.startswith("order_detail:"))
async def show_order_detail(callback: CallbackQuery, settings_storage):
    """Показать детали ордера"""
    await callback.answer()

    # Парсим: order_detail:SYMBOL:ORDER_ID
    parts = callback.data.split(":")
    symbol = parts[1]
    order_id_prefix = parts[2]

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)
        orders = await client.get_open_orders(symbol=symbol)

        # Ищем ордер по префиксу ID
        order = None
        for o in orders:
            if o.get('orderId', '').startswith(order_id_prefix):
                order = o
                break

        if not order:
            await callback.message.edit_text(
                f"❌ Ордер не найден (возможно уже исполнен или отменён)"
            )
            return

        # Формируем детали ордера
        text = await _format_order_detail(order)
        order_id = order.get('orderId')

        await callback.message.edit_text(
            text,
            reply_markup=get_order_detail_kb(symbol, order_id)
        )

    except Exception as e:
        logger.error(f"Error showing order detail: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при получении ордера:\n{html.escape(str(e))}"
        )


# ============================================================
# CALLBACK: Отмена ордера
# ============================================================

@router.callback_query(F.data.startswith("order_cancel:"))
async def cancel_order(callback: CallbackQuery, settings_storage):
    """Отменить ордер"""
    # Парсим: order_cancel:SYMBOL:ORDER_ID
    parts = callback.data.split(":")
    symbol = parts[1]
    order_id_prefix = parts[2]

    await callback.answer("Отменяю ордер...")

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)

        # Получаем полный order_id
        orders = await client.get_open_orders(symbol=symbol)
        order_id = None
        for o in orders:
            if o.get('orderId', '').startswith(order_id_prefix):
                order_id = o.get('orderId')
                break

        if not order_id:
            await callback.message.edit_text(
                f"❌ Ордер не найден (возможно уже исполнен или отменён)"
            )
            await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
            return

        # Отменяем ордер
        await client.cancel_order(symbol=symbol, order_id=order_id)

        await callback.message.edit_text(
            f"✅ <b>Ордер отменён!</b>\n\n"
            f"Symbol: {symbol}\n\n"
            f"💡 Используй <b>📊 Позиции</b> для просмотра активных сделок"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except BybitError as e:
        logger.error(f"Error cancelling order: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка при отмене ордера</b>\n\n{html.escape(str(e))}"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())


# ============================================================
# CALLBACK: Назад к списку
# ============================================================

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
        orders = []
        for o in all_orders:
            if o.get('reduceOnly', False):
                continue
            order_link_id = o.get('orderLinkId', '')
            if order_link_id.startswith('EP:'):
                continue
            orders.append(o)

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
            await callback.message.edit_text(
                "📊 <b>Открытых позиций и ордеров нет</b>\n\n"
                "Используй <b>➕ Открыть сделку</b> чтобы начать торговлю",
                reply_markup=get_empty_positions_kb()
            )
            return

        text = ""
        if positions:
            text += "📊 <b>Открытые позиции:</b>\n\n"
            text += await _format_positions_list(positions)

        if entry_plans:
            text += "📋 <b>Активные Entry Plans:</b>\n\n"
            text += _format_entry_plans_list(entry_plans)

        if orders:
            text += "⏳ <b>Ожидающие ордера:</b>\n\n"
            text += await _format_orders_list(orders)

        text += "💡 <i>Нажми для управления</i>"

        await callback.message.edit_text(
            text,
            reply_markup=get_positions_with_plans_kb(positions, orders, entry_plans)
        )

    except Exception as e:
        logger.error(f"Error going back to positions list: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка:\n{html.escape(str(e))}",
            reply_markup=get_main_menu()
        )


# ============================================================
# CALLBACK: Entry Plan Detail
# ============================================================

@router.callback_query(F.data.startswith("eplan_detail:"))
async def show_entry_plan_detail(callback: CallbackQuery, entry_plan_monitor):
    """Показать детали Entry Plan"""
    await callback.answer()

    # Парсим plan_id (короткий, 8 символов)
    short_plan_id = callback.data.split(":")[1]

    # Ищем план по короткому ID
    plan = None
    for pid, p in entry_plan_monitor.active_plans.items():
        if pid.startswith(short_plan_id):
            plan = p
            break

    if not plan:
        await callback.message.edit_text(
            f"❌ Entry Plan не найден (возможно уже завершён)"
        )
        return

    # Форматируем детали плана
    text = _format_entry_plan_detail(plan)

    await callback.message.edit_text(
        text,
        reply_markup=get_entry_plan_detail_kb(plan.plan_id, is_activated=plan.is_activated)
    )


@router.callback_query(F.data.startswith("eplan_activate:"))
async def activate_entry_plan_now(callback: CallbackQuery, entry_plan_monitor):
    """Принудительно активировать Entry Plan (поставить лимитки сейчас)"""
    await callback.answer("Активирую план...")

    short_plan_id = callback.data.split(":")[1]

    # Ищем план
    plan = None
    for pid, p in entry_plan_monitor.active_plans.items():
        if pid.startswith(short_plan_id):
            plan = p
            break

    if not plan:
        await callback.message.edit_text("❌ Entry Plan не найден")
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
        return

    if plan.is_activated:
        await callback.message.edit_text("⚠️ План уже активирован")
        return

    try:
        # Принудительная активация
        await entry_plan_monitor._activate_plan(plan)

        side_emoji = "🟢" if plan.side == "Long" else "🔴"
        await callback.message.edit_text(
            f"✅ <b>Entry Plan активирован!</b>\n\n"
            f"{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}\n"
            f"📊 Mode: {plan.mode}\n"
            f"📦 Orders: {len(plan.orders)}\n\n"
            f"🔔 Лимитки выставлены, ожидай исполнения"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except Exception as e:
        logger.error(f"Error activating entry plan: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при активации:\n{html.escape(str(e))}"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())


@router.callback_query(F.data.startswith("eplan_cancel:"))
async def cancel_entry_plan_confirmation(callback: CallbackQuery, entry_plan_monitor):
    """Запрос подтверждения отмены Entry Plan"""
    await callback.answer()

    short_plan_id = callback.data.split(":")[1]

    # Ищем план
    plan = None
    for pid, p in entry_plan_monitor.active_plans.items():
        if pid.startswith(short_plan_id):
            plan = p
            break

    if not plan:
        await callback.message.edit_text(
            f"❌ Entry Plan не найден"
        )
        return

    side_emoji = "🟢" if plan.side == "Long" else "🔴"

    await callback.message.edit_text(
        f"⚠️ <b>Подтверждение отмены Entry Plan</b>\n\n"
        f"{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}\n"
        f"📊 Mode: {plan.mode}\n"
        f"📈 Filled: {plan.fill_percentage:.0f}%\n\n"
        f"Ты уверен, что хочешь отменить этот план?\n\n"
        f"⚠️ Все pending ордера будут отменены.\n"
        f"{'✅ Частичная позиция получит SL/TP' if plan.has_fills else ''}",
        reply_markup=get_entry_plan_cancel_confirm_kb(plan.plan_id)
    )


@router.callback_query(F.data.startswith("eplan_cancel_confirm:"))
async def cancel_entry_plan_execute(callback: CallbackQuery, entry_plan_monitor):
    """Выполнить отмену Entry Plan"""
    await callback.answer("Отменяю план...")

    short_plan_id = callback.data.split(":")[1]

    # Ищем план
    plan = None
    full_plan_id = None
    for pid, p in entry_plan_monitor.active_plans.items():
        if pid.startswith(short_plan_id):
            plan = p
            full_plan_id = pid
            break

    if not plan:
        await callback.message.edit_text(
            f"❌ Entry Plan не найден"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
        return

    try:
        # Отменяем план (это вызовет _cancel_plan в мониторе)
        await entry_plan_monitor._cancel_plan(plan, "user_cancelled")

        side_emoji = "🟢" if plan.side == "Long" else "🔴"

        result_text = (
            f"✅ <b>Entry Plan отменён</b>\n\n"
            f"{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}\n"
            f"📊 Mode: {plan.mode}\n"
        )

        if plan.has_fills:
            result_text += (
                f"\n📈 <b>Partial position:</b>\n"
                f"  Filled: {plan.fill_percentage:.0f}%\n"
                f"  Qty: {plan.filled_qty:.4f}\n"
                f"  Avg: ${plan.avg_entry_price:.2f}\n"
                f"\n✅ SL/TP установлены на позицию"
            )
        else:
            result_text += "\n<i>Все ордера отменены, позиция не открыта</i>"

        await callback.message.edit_text(result_text)
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except Exception as e:
        logger.error(f"Error cancelling entry plan: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при отмене плана:\n{html.escape(str(e))}"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _format_entry_plan_detail(plan) -> str:
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

    text = f"""
📋 <b>Entry Plan</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}
📊 Mode: {plan.mode}
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

        text += f"  {status_icon} {tag}: {price_text} ({size_pct:.0f}%)\n"

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
            text += f"  • {cond}\n"

    text += f"\n⏰ Valid: {plan.time_valid_hours}h"

    if plan.is_activated and plan.activated_at:
        text += f"\n✅ Activated"

    if plan.sl_set:
        text += f"\n🛡️ SL set on position"

    text += "\n\n💡 Выбери действие ниже:"

    return text.strip()


def _format_entry_plans_list(entry_plans: list) -> str:
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


async def _format_positions_list(positions: list) -> str:
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


async def _format_orders_list(orders: list) -> str:
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


async def _format_order_detail(order: dict) -> str:
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


async def _format_position_detail(position: dict, tp_orders: list = None) -> str:
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
