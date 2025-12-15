"""
Trade Wizard - Шаг 8: Подтверждение и Execution
"""
import asyncio
import uuid
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from loguru import logger
from datetime import datetime

import config
from bot.states.trade_states import TradeStates
from bot.keyboards import trade_kb
from bot.keyboards.main_menu import get_main_menu
from services.bybit import BybitClient, BybitError
from services.risk_calculator import RiskCalculator, RiskCalculationError
from services.trade_logger import TradeRecord
from utils.validators import round_qty, round_price

router = Router()


async def move_to_confirmation(message_or_query, state: FSMContext):
    """Показать карточку подтверждения с расчётами"""
    await state.set_state(TradeStates.confirmation)

    data = await state.get_data()

    symbol = data.get('symbol')
    side = data.get('side')
    entry_type = data.get('entry_type')
    entry_price = data.get('entry_price')
    stop_price = data.get('stop_price')
    risk_usd = data.get('risk_usd')
    position_size_usd = data.get('position_size_usd')
    leverage = data.get('leverage')
    tp_mode = data.get('tp_mode')

    side_text = "🟢 Long" if side == "Buy" else "🔴 Short"
    side_emoji = "🟢" if side == "Buy" else "🔴"

    # Простой расчёт
    stop_distance = abs(entry_price - stop_price)

    if position_size_usd:
        # Режим Position Size - рассчитываем от размера позиции
        qty_estimate = position_size_usd / entry_price
        risk_estimate = qty_estimate * stop_distance
        margin_estimate = position_size_usd / leverage
    else:
        # Режим Risk - стандартный расчёт
        qty_estimate = risk_usd / stop_distance
        risk_estimate = risk_usd
        margin_estimate = (qty_estimate * entry_price) / leverage

    # TP info
    tp_info = ""
    if tp_mode == "rr":
        tp_rr = data.get('tp_rr')
        tp_price_calc = entry_price + (stop_distance * tp_rr) if side == "Buy" else entry_price - (stop_distance * tp_rr)
        tp_info = f"🎯 <b>TP:</b> ${tp_price_calc:.4f} (RR {tp_rr})"

    elif tp_mode == "single":
        tp_price = data.get('tp_price')
        tp_distance = abs(tp_price - entry_price)
        rr_calc = tp_distance / stop_distance
        tp_info = f"🎯 <b>TP:</b> ${tp_price:.4f} (RR {rr_calc:.2f})"

    elif tp_mode == "ladder":
        tp_rr_1 = data.get('tp_rr_1', 2.0)
        tp_rr_2 = data.get('tp_rr_2', 3.0)
        tp1 = entry_price + (stop_distance * tp_rr_1) if side == "Buy" else entry_price - (stop_distance * tp_rr_1)
        tp2 = entry_price + (stop_distance * tp_rr_2) if side == "Buy" else entry_price - (stop_distance * tp_rr_2)
        tp_info = f"🪜 <b>TP1:</b> ${tp1:.4f} (50%)\n🪜 <b>TP2:</b> ${tp2:.4f} (50%)"

    # Формируем инфо о риске/размере позиции
    if position_size_usd:
        risk_info = f"💵 <b>Position:</b> ${position_size_usd}\n💰 <b>Risk:</b> ~${risk_estimate:.2f}"
    else:
        risk_info = f"💰 <b>Risk:</b> ${risk_estimate:.2f}"

    card = f"""
📊 <b>Trade Summary</b>

{side_emoji} <b>{symbol}</b> {side_text}

⚡ <b>Entry:</b> {entry_type} @ ${entry_price:.4f}
🛑 <b>Stop:</b> ${stop_price:.4f}
{tp_info}

{risk_info}
📊 <b>Leverage:</b> {leverage}x
📦 <b>Qty:</b> ~{qty_estimate:.4f} {symbol.replace('USDT', '')}
💵 <b>Margin:</b> ~${margin_estimate:.2f}

<i>⚠️ Проверь все параметры перед подтверждением!</i>
"""

    from aiogram.types import Message

    if isinstance(message_or_query, Message):
        # Это сообщение пользователя - удаляем его и отправляем новое
        try:
            await message_or_query.delete()
        except:
            pass
        await message_or_query.answer(
            card,
            reply_markup=trade_kb.get_confirmation_keyboard()
        )
    else:
        # Это CallbackQuery
        await message_or_query.edit_text(
            card,
            reply_markup=trade_kb.get_confirmation_keyboard()
        )


@router.callback_query(TradeStates.confirmation, F.data == "trade:confirm")
async def trade_confirm(callback: CallbackQuery, state: FSMContext, settings_storage, lock_manager, trade_logger):
    """Выполнение сделки - полная реализация"""
    user_id = callback.from_user.id

    # ===== Race condition protection =====
    if not await lock_manager.acquire_lock(user_id):
        await callback.answer("⏳ Trade in progress, please wait...", show_alert=True)
        return

    bybit = None
    trade_id = None
    actual_entry_price = None
    actual_qty = None

    try:
        await callback.answer("⏳ Размещаю ордер...")
        await callback.message.edit_text("⏳ <b>Выполняю сделку...</b>")

        # ===== 1. Получить данные из FSM =====
        data = await state.get_data()
        symbol = data.get('symbol')
        side = data.get('side')  # "Buy" or "Sell"
        entry_type = data.get('entry_type')  # "Market" or "Limit"
        entry_price = data.get('entry_price')  # float
        stop_price = data.get('stop_price')  # float
        risk_usd = data.get('risk_usd')  # float
        leverage = data.get('leverage')  # int
        tp_mode = data.get('tp_mode')  # "single", "ladder", "rr"

        logger.info(f"Trade execution started: {symbol} {side} {entry_type}, risk=${risk_usd}, lev={leverage}x")

        # Конвертируем side для RiskCalculator (Buy->Long, Sell->Short)
        position_side = "Long" if side == "Buy" else "Short"

        # ===== 2. Получить user settings =====
        settings = await settings_storage.get_settings(user_id)
        testnet_mode = settings.testnet_mode
        max_risk = settings.max_risk_per_trade
        max_margin = settings.max_margin_per_trade

        # ===== 3. Создать Bybit клиент =====
        bybit = BybitClient(testnet=testnet_mode)
        risk_calc = RiskCalculator(bybit)

        # ===== 3.5. Проверка лимита позиций =====
        positions = await bybit.get_positions()
        current_positions_count = len(positions)

        if current_positions_count >= settings.max_active_positions:
            await callback.message.edit_text(
                f"⚠️ <b>Достигнут лимит активных позиций!</b>\n\n"
                f"Текущие позиции: {current_positions_count}\n"
                f"Лимит: {settings.max_active_positions}\n\n"
                f"<i>Закрой существующие позиции перед открытием новых.</i>",
                reply_markup=None
            )
            await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
            return

        # ===== 4. Получить текущую цену для Market =====
        if entry_type == "Market":
            ticker = await bybit.get_tickers(symbol)
            mark_price = float(ticker.get('markPrice'))
            entry_price = mark_price
            logger.info(f"Market order: using mark price ${mark_price:.4f}")

        # ===== 5. Risk calculation & validation =====
        await callback.message.edit_text("📊 <b>Расчёт позиции...</b>")

        # Проверяем режим: risk_usd или position_size_usd
        position_size_usd = data.get('position_size_usd')

        if position_size_usd:
            # Режим Position Size - рассчитываем от размера позиции
            position_calc = await risk_calc.calculate_position_from_size(
                symbol=symbol,
                side=position_side,  # Long/Short для RiskCalculator
                entry_price=entry_price,
                stop_price=stop_price,
                position_size_usd=position_size_usd,
                leverage=leverage
            )
        else:
            # Режим Risk - стандартный расчёт
            position_calc = await risk_calc.calculate_position(
                symbol=symbol,
                side=position_side,  # Long/Short для RiskCalculator
                entry_price=entry_price,
                stop_price=stop_price,
                risk_usd=risk_usd,
                leverage=leverage
            )

        qty = position_calc['qty']
        margin_required = position_calc['margin_required']
        instrument_info = position_calc['instrument_info']

        logger.info(f"Position calculated: qty={qty}, margin=${margin_required:.2f}")

        # Валидация баланса
        is_valid, error_msg = await risk_calc.validate_balance(
            required_margin=margin_required,
            actual_risk_usd=position_calc['actual_risk_usd'],
            max_risk_per_trade=max_risk,
            max_margin_per_trade=max_margin,
            trading_capital=settings.trading_capital_usd  # Фиксированный капитал для Manual режима
        )

        if not is_valid:
            logger.warning(f"Balance validation failed: {error_msg}")
            await callback.message.edit_text(
                f"❌ <b>Недостаточно средств:</b>\n\n{error_msg}",
                reply_markup=None
            )
            await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
            return

        # ===== 6. Setup - установка margin mode и leverage =====
        margin_mode = settings.default_margin_mode
        await callback.message.edit_text(f"⚙️ <b>Установка {margin_mode} margin и плеча {leverage}x...</b>")
        await bybit.set_margin_mode(symbol, margin_mode, leverage)
        logger.info(f"Margin mode set to {margin_mode} with {leverage}x leverage")

        # ===== 7. Entry Order =====
        trade_id = str(uuid.uuid4())
        entry_client_order_id = f"{trade_id}_entry"[:36]

        await callback.message.edit_text(f"🚀 <b>Размещение {entry_type} ордера...</b>")

        entry_order = await bybit.place_order(
            symbol=symbol,
            side=side,
            order_type=entry_type,
            qty=qty,
            price=str(entry_price) if entry_type == "Limit" else None,
            client_order_id=entry_client_order_id
        )

        order_id = entry_order['orderId']
        logger.info(f"Entry order placed: {order_id}")

        # Для Market - ждём fill
        if entry_type == "Market":
            await callback.message.edit_text("⏳ <b>Ожидание исполнения...</b>")

            filled_order = await bybit.wait_until_filled(
                symbol=symbol,
                order_id=order_id,
                timeout=config.MARKET_ORDER_TIMEOUT
            )

            # Получаем РЕАЛЬНУЮ цену входа
            actual_entry_price = float(filled_order['avgPrice'])
            actual_qty = float(filled_order['qty'])
            logger.info(f"Market order filled: price=${actual_entry_price:.4f}, qty={actual_qty}")
        else:
            # Для Limit - используем заданную цену
            actual_entry_price = entry_price
            actual_qty = float(qty)
            logger.info(f"Limit order placed at ${actual_entry_price:.4f}")

        # ===== 8-9. Stop Loss & Take Profit (атомарная установка) =====
        await callback.message.edit_text("🛑 <b>Установка SL/TP...</b>")

        tp_success = True
        stop_distance = abs(actual_entry_price - stop_price)

        try:
            if tp_mode == "single":
                # Single TP - цена указана пользователем
                tp_price = data.get('tp_price')

                # ✅ АТОМАРНО: один вызов для SL + TP
                try:
                    await bybit.set_trading_stop(
                        symbol=symbol,
                        stop_loss=str(stop_price),
                        take_profit=str(tp_price),
                        sl_trigger_by="MarkPrice",
                        tp_trigger_by="MarkPrice"
                    )
                    logger.info(f"SL/TP set: SL=${stop_price:.4f}, TP=${tp_price:.4f}")

                except Exception as sl_tp_error:
                    # PANIC! SL/TP не установились - закрываем позицию
                    logger.error(f"CRITICAL: Failed to set SL/TP: {sl_tp_error}")

                    try:
                        await bybit.close_position(symbol)
                        logger.warning(f"Position closed due to SL/TP failure")
                    except Exception as close_error:
                        logger.error(f"Failed to close position: {close_error}")

                    await callback.message.edit_text(
                        f"❌ <b>Критическая ошибка!</b>\n\n"
                        f"Не удалось установить Stop Loss / Take Profit.\n"
                        f"Позиция была экстренно закрыта.\n\n"
                        f"Ошибка: {str(sl_tp_error)}",
                        reply_markup=None
                    )
                    await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
                    return

            elif tp_mode == "rr":
                # TP по RR
                tp_rr = data.get('tp_rr', 2.0)

                if side == "Buy":
                    tp_price = actual_entry_price + (stop_distance * tp_rr)
                else:
                    tp_price = actual_entry_price - (stop_distance * tp_rr)

                # Округлить до tickSize
                tp_price_str = round_price(tp_price, instrument_info['tickSize'])

                # ✅ АТОМАРНО: один вызов для SL + TP
                try:
                    await bybit.set_trading_stop(
                        symbol=symbol,
                        stop_loss=str(stop_price),
                        take_profit=tp_price_str,
                        sl_trigger_by="MarkPrice",
                        tp_trigger_by="MarkPrice"
                    )
                    logger.info(f"SL/TP set: SL=${stop_price:.4f}, TP=${tp_price_str} (RR {tp_rr})")

                except Exception as sl_tp_error:
                    # PANIC! SL/TP не установились - закрываем позицию
                    logger.error(f"CRITICAL: Failed to set SL/TP: {sl_tp_error}")

                    try:
                        await bybit.close_position(symbol)
                        logger.warning(f"Position closed due to SL/TP failure")
                    except Exception as close_error:
                        logger.error(f"Failed to close position: {close_error}")

                    await callback.message.edit_text(
                        f"❌ <b>Критическая ошибка!</b>\n\n"
                        f"Не удалось установить Stop Loss / Take Profit.\n"
                        f"Позиция была экстренно закрыта.\n\n"
                        f"Ошибка: {str(sl_tp_error)}",
                        reply_markup=None
                    )
                    await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
                    return

            elif tp_mode == "ladder":
                # Ladder TP - два уровня
                # ✅ СНАЧАЛА: Установить SL на позицию (КРИТИЧНО!)
                try:
                    await bybit.set_trading_stop(
                        symbol=symbol,
                        stop_loss=str(stop_price),
                        sl_trigger_by="MarkPrice"
                    )
                    logger.info(f"Stop Loss set at ${stop_price:.4f}")

                except Exception as sl_error:
                    # PANIC! SL не установился - закрываем позицию
                    logger.error(f"CRITICAL: Failed to set SL for ladder: {sl_error}")

                    try:
                        await bybit.close_position(symbol)
                        logger.warning(f"Position closed due to SL failure (ladder mode)")
                    except Exception as close_error:
                        logger.error(f"Failed to close position: {close_error}")

                    await callback.message.edit_text(
                        f"❌ <b>Критическая ошибка!</b>\n\n"
                        f"Не удалось установить Stop Loss.\n"
                        f"Позиция была экстренно закрыта.\n\n"
                        f"Ошибка: {str(sl_error)}",
                        reply_markup=None
                    )
                    await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
                    return

                # Рассчитать уровни TP
                tp_rr_1 = data.get('tp_rr_1', 2.0)
                tp_rr_2 = data.get('tp_rr_2', 3.0)

                if side == "Buy":
                    tp1_price = actual_entry_price + (stop_distance * tp_rr_1)
                    tp2_price = actual_entry_price + (stop_distance * tp_rr_2)
                else:
                    tp1_price = actual_entry_price - (stop_distance * tp_rr_1)
                    tp2_price = actual_entry_price - (stop_distance * tp_rr_2)

                # Округлить цены
                tick_size = instrument_info['tickSize']
                tp1_price_str = round_price(tp1_price, tick_size)
                tp2_price_str = round_price(tp2_price, tick_size)

                # Разделить qty пополам
                qty_step = instrument_info['qtyStep']
                qty_half = actual_qty / 2

                # Проверка: можем ли разделить позицию на 2 части?
                # Минимальная qty для каждого уровня должна быть >= qtyStep
                min_qty_per_level = float(qty_step)

                if qty_half >= min_qty_per_level:
                    # Можем разделить
                    qty1 = round_qty(qty_half, qty_step, round_down=True)
                    qty2 = round_qty(actual_qty - float(qty1), qty_step, round_down=True)

                    # Проверка после округления: оба должны быть > 0
                    if float(qty1) > 0 and float(qty2) > 0:
                        # Разместить ladder TP
                        await bybit.place_ladder_tp(
                            symbol=symbol,
                            position_side=side,
                            tp_levels=[
                                {'price': tp1_price_str, 'qty': qty1},
                                {'price': tp2_price_str, 'qty': qty2}
                            ],
                            client_order_id_prefix=trade_id
                        )
                        logger.info(f"Ladder TP set: TP1=${tp1_price_str} ({qty1}), TP2=${tp2_price_str} ({qty2})")
                    else:
                        # Fallback: один TP на первом уровне (100% позиции)
                        logger.warning(f"Qty too small for ladder after rounding. Using single TP at level 1")
                        await bybit.place_ladder_tp(
                            symbol=symbol,
                            position_side=side,
                            tp_levels=[
                                {'price': tp1_price_str, 'qty': str(actual_qty)}
                            ],
                            client_order_id_prefix=trade_id
                        )
                        logger.info(f"Single TP (fallback) set: TP1=${tp1_price_str} ({actual_qty})")
                else:
                    # Позиция слишком маленькая для ladder - используем один TP на первом уровне
                    logger.warning(f"Position size too small for ladder TP (min {min_qty_per_level} per level). Using single TP.")
                    await bybit.place_ladder_tp(
                        symbol=symbol,
                        position_side=side,
                        tp_levels=[
                            {'price': tp1_price_str, 'qty': str(actual_qty)}
                        ],
                        client_order_id_prefix=trade_id
                    )
                    logger.info(f"Single TP (size limit) set: TP1=${tp1_price_str} ({actual_qty})")

        except Exception as tp_error:
            logger.error(f"Error setting Take Profit: {tp_error}", exc_info=True)
            tp_success = False

        # ===== 10. Success! Получить liq price из позиции =====
        positions = await bybit.get_positions(symbol=symbol)
        liq_price = "N/A"
        if positions:
            logger.info(f"Position data: {positions[0]}")
            liq_price_raw = positions[0].get('liqPrice', '')
            logger.info(f"liqPrice from Bybit: '{liq_price_raw}' (type: {type(liq_price_raw)})")
            if liq_price_raw and liq_price_raw != '' and liq_price_raw != '0':
                try:
                    liq_price_float = float(liq_price_raw)
                    if liq_price_float > 0:
                        liq_price = f"${liq_price_float:.4f}"
                except (ValueError, TypeError):
                    logger.warning(f"Cannot convert liqPrice to float: {liq_price_raw}")

        # Пересчитать actual risk и RR от РЕАЛЬНОЙ цены входа
        actual_stop_distance = abs(actual_entry_price - stop_price)
        actual_risk = actual_stop_distance * actual_qty

        # Формируем TP info для карточки
        tp_info = ""
        if tp_mode == "single":
            tp_price = data.get('tp_price')
            tp_distance = abs(tp_price - actual_entry_price)
            rr_actual = tp_distance / actual_stop_distance
            tp_info = f"🎯 <b>TP:</b> ${tp_price:.4f} (RR {rr_actual:.2f})"

        elif tp_mode == "rr":
            tp_rr = data.get('tp_rr', 2.0)
            if side == "Buy":
                tp_price = actual_entry_price + (actual_stop_distance * tp_rr)
            else:
                tp_price = actual_entry_price - (actual_stop_distance * tp_rr)
            tp_info = f"🎯 <b>TP:</b> ${tp_price:.4f} (RR {tp_rr})"

        elif tp_mode == "ladder":
            tp_rr_1 = data.get('tp_rr_1', 2.0)
            tp_rr_2 = data.get('tp_rr_2', 3.0)
            if side == "Buy":
                tp1 = actual_entry_price + (actual_stop_distance * tp_rr_1)
                tp2 = actual_entry_price + (actual_stop_distance * tp_rr_2)
            else:
                tp1 = actual_entry_price - (actual_stop_distance * tp_rr_1)
                tp2 = actual_entry_price - (actual_stop_distance * tp_rr_2)
            tp_info = f"🪜 <b>TP1:</b> ${tp1:.4f} (50%)\n🪜 <b>TP2:</b> ${tp2:.4f} (50%)"

        # Success card
        side_emoji = "🟢" if side == "Buy" else "🔴"
        side_text = "Long" if side == "Buy" else "Short"

        success_text = f"""
✅ <b>Сделка открыта!</b>

{side_emoji} <b>{symbol}</b> {side_text}

⚡ <b>Entry:</b> ${actual_entry_price:.4f} (filled)
🛑 <b>Stop:</b> ${stop_price:.4f}
{tp_info}

💰 <b>Risk:</b> ${actual_risk:.2f}
📊 <b>Leverage:</b> {leverage}x
📦 <b>Qty:</b> {actual_qty} {symbol.replace('USDT', '')}
💵 <b>Margin:</b> ${margin_required:.2f}
🔥 <b>Liq:</b> {liq_price}

"""
        # Добавляем статус установки SL/TP
        if tp_success:
            success_text += "<i>✅ SL и TP установлены</i>\n"
        else:
            success_text += "<i>⚠️ SL установлен, но ошибка при установке TP!</i>\n<i>Проверь позицию вручную!</i>\n"

        await callback.message.edit_text(success_text, reply_markup=None)
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

        # ===== Логирование сделки =====
        try:
            # Рассчитываем TP цену для логирования
            tp_price_for_log = None
            rr_planned = None

            if tp_mode == "single":
                tp_price_for_log = data.get('tp_price')
                tp_distance = abs(tp_price_for_log - actual_entry_price)
                rr_planned = tp_distance / actual_stop_distance

            elif tp_mode == "rr":
                tp_rr = data.get('tp_rr', 2.0)
                rr_planned = tp_rr
                if side == "Buy":
                    tp_price_for_log = actual_entry_price + (actual_stop_distance * tp_rr)
                else:
                    tp_price_for_log = actual_entry_price - (actual_stop_distance * tp_rr)

            elif tp_mode == "ladder":
                # Для ladder берем средний RR
                tp_rr_1 = data.get('tp_rr_1', 2.0)
                tp_rr_2 = data.get('tp_rr_2', 3.0)
                rr_planned = (tp_rr_1 + tp_rr_2) / 2

            # Создаем запись о сделке
            trade_record = TradeRecord(
                trade_id=trade_id,
                user_id=user_id,
                timestamp=datetime.utcnow().isoformat(),
                symbol=symbol,
                side=position_side,  # Long/Short для логов
                entry_price=actual_entry_price,
                exit_price=None,  # Будет заполнено при закрытии
                qty=actual_qty,
                leverage=leverage,
                margin_mode=settings.default_margin_mode,
                stop_price=stop_price,
                tp_price=tp_price_for_log,
                risk_usd=actual_risk,
                pnl_usd=None,  # Будет заполнено при закрытии
                pnl_percent=None,  # Будет заполнено при закрытии
                roe_percent=None,  # Будет заполнено при закрытии
                outcome=None,  # Будет заполнено при закрытии
                rr_planned=rr_planned,
                rr_actual=None,  # Будет заполнено при закрытии
                status="open",  # Статус: открыта
                testnet=testnet_mode  # Режим торговли
            )

            # Логируем сделку
            await trade_logger.log_trade(trade_record)
            logger.info(f"Trade logged: {trade_id}")

        except Exception as log_error:
            # Не падаем, если логирование не удалось
            logger.error(f"Failed to log trade: {log_error}")

        logger.info(f"Trade executed successfully: {symbol} {side} @ ${actual_entry_price:.4f}")

    except BybitError as e:
        # Bybit API ошибки
        logger.error(f"Bybit API error: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка Bybit API:</b>\n\n{str(e)}",
            reply_markup=None
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except TimeoutError as e:
        # Market order timeout
        logger.error(f"Order timeout: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ордер не исполнился вовремя:</b>\n\n{str(e)}\n\n"
            f"Ордер был отменён. Попробуй ещё раз.",
            reply_markup=None
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except RiskCalculationError as e:
        # Ошибки расчёта риска
        logger.error(f"Risk calculation error: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка расчёта риска:</b>\n\n{str(e)}",
            reply_markup=None
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except Exception as e:
        # Общие ошибки
        logger.error(f"Trade execution error: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ <b>Неожиданная ошибка:</b>\n\n{str(e)}",
            reply_markup=None
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    finally:
        await lock_manager.release_lock(user_id)
        await state.clear()


@router.callback_query(TradeStates.confirmation, F.data == "trade:edit")
async def trade_edit(callback: CallbackQuery, state: FSMContext):
    """Редактирование параметров сделки"""
    # TODO: Реализовать навигацию назад к конкретным шагам
    await callback.answer("⚠️ Редактирование в разработке. Используй ❌ Cancel и начни заново", show_alert=True)
