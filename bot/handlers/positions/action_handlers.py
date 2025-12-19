"""
Хендлеры для действий с позициями: закрытие, partial close, move SL, panic.
"""
import asyncio
import html
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from bot.keyboards.positions_kb import (
    get_close_confirmation_kb,
    get_panic_close_all_confirmation_kb
)
from bot.keyboards.main_menu import get_main_menu
from services.bybit import BybitClient, BybitError
from bot.handlers.positions.states import PositionStates

logger = logging.getLogger(__name__)
router = Router()


async def safe_edit_or_send(callback: CallbackQuery, text: str, reply_markup=None):
    """
    Безопасное редактирование сообщения.
    Если сообщение содержит фото - удаляем и отправляем новое.
    """
    try:
        # Пробуем edit_text
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "no text in the message" in str(e) or "message can't be edited" in str(e):
            # Сообщение с фото - удаляем и отправляем новое
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=reply_markup)
        else:
            raise


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
        await safe_edit_or_send(
            callback,
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
        await safe_edit_or_send(
            callback,
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

    await safe_edit_or_send(
        callback,
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

            # Получаем реальный PnL с биржи
            await asyncio.sleep(0.5)  # Даём время на обработку
            closed_pnl_data = await client.get_closed_pnl(symbol=symbol)

            if closed_pnl_data:
                real_pnl = float(closed_pnl_data.get('closedPnl', unrealized_pnl))
                exit_price = float(closed_pnl_data.get('avgExitPrice', mark_price))
            else:
                real_pnl = unrealized_pnl
                exit_price = mark_price
                logger.warning(f"Could not get closed PnL for {symbol}, using unrealized: {unrealized_pnl}")

            # Логируем полное закрытие с реальным PnL
            try:
                await trade_logger.update_trade_on_close(
                    user_id=user_id,
                    symbol=symbol,
                    exit_price=exit_price,
                    pnl_usd=real_pnl,
                    is_partial=False,
                    testnet=testnet
                )
            except Exception as log_error:
                logger.error(f"Failed to log full close: {log_error}")

            msg = f"✅ <b>Позиция {symbol} закрыта!</b>\nPnL: ${real_pnl:+.2f}"
        else:
            # Partial close
            result = await client.partial_close(symbol=symbol, percent=percent)

            # Получаем реальный PnL с биржи
            await asyncio.sleep(0.5)
            closed_pnl_data = await client.get_closed_pnl(symbol=symbol)

            if closed_pnl_data:
                real_pnl = float(closed_pnl_data.get('closedPnl', 0))
                exit_price = float(closed_pnl_data.get('avgExitPrice', mark_price))
            else:
                real_pnl = unrealized_pnl * (percent / 100)
                exit_price = mark_price
                logger.warning(f"Could not get closed PnL for {symbol} partial, using calculated")

            # Логируем частичное закрытие с реальным PnL
            try:
                await trade_logger.update_trade_on_close(
                    user_id=user_id,
                    symbol=symbol,
                    exit_price=exit_price,
                    pnl_usd=real_pnl,
                    is_partial=True,
                    testnet=testnet
                )
            except Exception as log_error:
                logger.error(f"Failed to log partial close: {log_error}")

            msg = (
                f"✅ <b>Позиция частично закрыта!</b>\n\n"
                f"Symbol: {symbol}\n"
                f"Закрыто: {result['closed_qty']} ({percent}%)\n"
                f"PnL: ${real_pnl:+.2f}"
            )

        await safe_edit_or_send(
            callback,
            msg + "\n\n💡 Используй <b>📊 Позиции</b> чтобы проверить статус"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except BybitError as e:
        logger.error(f"Error closing position: {e}")
        await safe_edit_or_send(
            callback,
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

    await safe_edit_or_send(
        callback,
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

    await safe_edit_or_send(
        callback,
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
            await safe_edit_or_send(
                callback,
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

        await safe_edit_or_send(callback, result_text)
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except Exception as e:
        logger.error(f"Error during panic close all: {e}")
        await safe_edit_or_send(
            callback,
            f"❌ Ошибка при Panic Close:\n{html.escape(str(e))}"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())


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
            await safe_edit_or_send(
                callback,
                f"❌ Ордер не найден (возможно уже исполнен или отменён)"
            )
            await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
            return

        # Отменяем ордер
        await client.cancel_order(symbol=symbol, order_id=order_id)

        await safe_edit_or_send(
            callback,
            f"✅ <b>Ордер отменён!</b>\n\n"
            f"Symbol: {symbol}\n\n"
            f"💡 Используй <b>📊 Позиции</b> для просмотра активных сделок"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except BybitError as e:
        logger.error(f"Error cancelling order: {e}")
        await safe_edit_or_send(
            callback,
            f"❌ <b>Ошибка при отмене ордера</b>\n\n{html.escape(str(e))}"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
