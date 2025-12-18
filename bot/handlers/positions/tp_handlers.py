"""
Хендлеры для управления Take Profit ордерами позиций.
"""
import html
import logging
import time

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.keyboards.positions_kb import (
    get_tp_management_kb,
    get_tp_percent_kb,
    get_tp_confirm_kb,
)
from bot.keyboards.main_menu import get_main_menu
from services.bybit import BybitClient, BybitError
from bot.handlers.positions.states import PositionStates
from utils.validators import round_qty, round_price

logger = logging.getLogger(__name__)
router = Router()


# ============================================================
# CALLBACK: Modify TP (главная точка входа)
# ============================================================

@router.callback_query(F.data.startswith("pos_modify_tp:"))
async def modify_tp_menu(callback: CallbackQuery, settings_storage, state: FSMContext):
    """Показать меню управления TP для позиции"""
    await callback.answer()
    await state.clear()

    symbol = callback.data.split(":")[1]
    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)

        # Получаем позицию
        positions = await client.get_positions(symbol=symbol)
        if not positions:
            await callback.message.edit_text(
                f"❌ Позиция {symbol} не найдена"
            )
            return

        position = positions[0]
        side = position.get('side')
        size = float(position.get('size', 0))
        entry_price = float(position.get('avgPrice', 0))
        mark_price = float(position.get('markPrice', 0))

        # Получаем открытые ордера (ищем TP)
        orders = await client.get_open_orders(symbol=symbol)
        tp_orders = []
        for order in orders:
            # TP = reduceOnly Limit ордер противоположной стороны
            if order.get('reduceOnly') and order.get('orderType') == 'Limit':
                order_side = order.get('side')
                # Для Long позиции TP = Sell, для Short = Buy
                is_tp = (side == 'Buy' and order_side == 'Sell') or \
                        (side == 'Sell' and order_side == 'Buy')
                if is_tp:
                    tp_orders.append(order)

        # Формируем сообщение
        side_emoji = "🟢" if side == "Buy" else "🔴"
        side_text = "LONG" if side == "Buy" else "SHORT"

        msg = f"""
🎯 <b>Управление Take Profit</b>

{side_emoji} <b>{symbol}</b> {side_text}
📦 Size: {size}
⚡ Entry: ${entry_price:.4f}
💹 Mark: ${mark_price:.4f}

"""
        if tp_orders:
            msg += f"<b>Активные TP ордера ({len(tp_orders)}):</b>\n"
            for i, tp in enumerate(tp_orders, 1):
                tp_price = float(tp.get('price', 0))
                tp_qty = float(tp.get('qty', 0))
                tp_pct = (tp_qty / size * 100) if size > 0 else 0
                msg += f"  🎯 TP{i}: ${tp_price:.4f} ({tp_qty} = {tp_pct:.0f}%)\n"
        else:
            msg += "<i>Нет активных TP ордеров</i>\n"

        msg += "\n<i>Выбери действие:</i>"

        # Сохраняем данные позиции в state
        await state.update_data(
            tp_symbol=symbol,
            tp_side=side,
            tp_size=size,
            tp_entry=entry_price
        )

        await callback.message.edit_text(
            msg,
            reply_markup=get_tp_management_kb(symbol, has_tp_orders=len(tp_orders) > 0)
        )

    except BybitError as e:
        logger.error(f"Error getting position for TP: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка: {html.escape(str(e))}"
        )


# ============================================================
# CALLBACK: Добавить TP
# ============================================================

@router.callback_query(F.data.startswith("tp_add:"))
async def add_tp_start(callback: CallbackQuery, state: FSMContext):
    """Начать процесс добавления TP - запрос цены"""
    await callback.answer()

    symbol = callback.data.split(":")[1]

    # Получаем данные из state
    data = await state.get_data()
    side = data.get('tp_side', 'Buy')
    entry_price = data.get('tp_entry', 0)

    side_text = "выше entry" if side == "Buy" else "ниже entry"

    await state.set_state(PositionStates.entering_tp_price)

    await callback.message.edit_text(
        f"🎯 <b>Добавление Take Profit для {symbol}</b>\n\n"
        f"⚡ Entry: ${entry_price:.4f}\n\n"
        f"Введи цену TP ({side_text}):\n\n"
        f"<i>Например: {entry_price * 1.05:.2f}</i>\n\n"
        f"Или /cancel для отмены"
    )


@router.message(PositionStates.entering_tp_price)
async def add_tp_price_entered(message: Message, state: FSMContext, settings_storage):
    """Обработка введённой цены TP"""
    if message.text.lower() == '/cancel':
        await state.clear()
        await message.answer("❌ Добавление TP отменено", reply_markup=get_main_menu())
        return

    # Парсим цену
    try:
        tp_price = float(message.text.strip().replace(',', '.'))
    except ValueError:
        await message.answer(
            "❌ Неверный формат цены. Введи число или /cancel"
        )
        return

    # Получаем данные из state
    data = await state.get_data()
    symbol = data.get('tp_symbol')
    side = data.get('tp_side')
    entry_price = data.get('tp_entry', 0)

    # Валидация направления цены
    if side == 'Buy' and tp_price <= entry_price:
        await message.answer(
            f"❌ Для LONG позиции TP должен быть выше entry (${entry_price:.4f})\n"
            f"Введи корректную цену или /cancel"
        )
        return
    elif side == 'Sell' and tp_price >= entry_price:
        await message.answer(
            f"❌ Для SHORT позиции TP должен быть ниже entry (${entry_price:.4f})\n"
            f"Введи корректную цену или /cancel"
        )
        return

    # Сохраняем цену и переходим к выбору %
    await state.update_data(tp_price=tp_price)
    await state.set_state(None)

    await message.answer(
        f"🎯 <b>Цена TP: ${tp_price:.4f}</b>\n\n"
        f"Выбери какой % от позиции закрыть по этой цене:",
        reply_markup=get_tp_percent_kb(symbol)
    )


# ============================================================
# CALLBACK: Выбор процента
# ============================================================

@router.callback_query(F.data.startswith("tp_pct:"))
async def tp_percent_selected(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Выбран стандартный процент - показать подтверждение"""
    await callback.answer()

    parts = callback.data.split(":")
    symbol = parts[1]
    percent = int(parts[2])

    data = await state.get_data()
    tp_price = data.get('tp_price')
    size = data.get('tp_size', 0)

    tp_qty = size * percent / 100

    await callback.message.edit_text(
        f"🎯 <b>Подтверждение TP</b>\n\n"
        f"Symbol: {symbol}\n"
        f"Цена: ${tp_price:.4f}\n"
        f"Объём: {tp_qty:.4f} ({percent}% от {size:.4f})\n\n"
        f"<i>Подтвердить установку TP?</i>",
        reply_markup=get_tp_confirm_kb(symbol, str(tp_price), percent)
    )


@router.callback_query(F.data.startswith("tp_pct_custom:"))
async def tp_percent_custom(callback: CallbackQuery, state: FSMContext):
    """Запрос кастомного процента"""
    await callback.answer()

    symbol = callback.data.split(":")[1]

    await state.set_state(PositionStates.entering_tp_percent)

    await callback.message.edit_text(
        f"✏️ <b>Введи кастомный % для TP</b>\n\n"
        f"Введи число от 1 до 100:\n\n"
        f"<i>Например: 33</i>\n\n"
        f"Или /cancel для отмены"
    )


@router.message(PositionStates.entering_tp_percent)
async def tp_custom_percent_entered(message: Message, state: FSMContext):
    """Обработка кастомного процента"""
    if message.text.lower() == '/cancel':
        await state.clear()
        await message.answer("❌ Добавление TP отменено", reply_markup=get_main_menu())
        return

    try:
        percent = int(message.text.strip())
        if percent < 1 or percent > 100:
            raise ValueError()
    except ValueError:
        await message.answer(
            "❌ Введи число от 1 до 100 или /cancel"
        )
        return

    data = await state.get_data()
    symbol = data.get('tp_symbol')
    tp_price = data.get('tp_price')
    size = data.get('tp_size', 0)

    tp_qty = size * percent / 100

    await state.set_state(None)

    await message.answer(
        f"🎯 <b>Подтверждение TP</b>\n\n"
        f"Symbol: {symbol}\n"
        f"Цена: ${tp_price:.4f}\n"
        f"Объём: {tp_qty:.4f} ({percent}% от {size:.4f})\n\n"
        f"<i>Подтвердить установку TP?</i>",
        reply_markup=get_tp_confirm_kb(symbol, str(tp_price), percent)
    )


# ============================================================
# CALLBACK: Подтверждение TP
# ============================================================

@router.callback_query(F.data.startswith("tp_confirm:"))
async def tp_confirm_and_place(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Подтверждение и размещение TP ордера"""
    await callback.answer("Устанавливаю TP...")

    parts = callback.data.split(":")
    symbol = parts[1]
    tp_price = float(parts[2])
    percent = int(parts[3])

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    data = await state.get_data()
    side = data.get('tp_side')
    size = data.get('tp_size', 0)

    try:
        client = BybitClient(testnet=testnet)

        # Получаем instrument info для округления
        instrument_info = await client.get_instrument_info(symbol)
        lot_size = instrument_info.get('lotSizeFilter', {})
        price_filter = instrument_info.get('priceFilter', {})
        tick_size = price_filter.get('tickSize', '0.01')
        qty_step = lot_size.get('qtyStep', '0.001')
        min_qty = float(lot_size.get('minOrderQty', '0.001'))

        # Расчёт qty
        tp_qty_raw = size * percent / 100
        tp_qty = round_qty(tp_qty_raw, qty_step, round_down=True)
        tp_price_str = round_price(tp_price, tick_size)

        if float(tp_qty) < min_qty:
            await callback.message.edit_text(
                f"❌ Слишком маленький объём: {tp_qty} < min {min_qty}"
            )
            return

        # Сторона ордера: противоположная позиции
        close_side = "Sell" if side == "Buy" else "Buy"

        # Уникальный client_order_id
        ts = int(time.time() * 1000) % 100000
        client_oid = f"TP:{symbol[:6]}:{ts}"

        # Размещаем Limit reduceOnly ордер
        order = await client.place_order(
            symbol=symbol,
            side=close_side,
            order_type="Limit",
            qty=tp_qty,
            price=tp_price_str,
            reduce_only=True,
            time_in_force="GTC",
            client_order_id=client_oid
        )

        await state.clear()

        await callback.message.edit_text(
            f"✅ <b>TP установлен!</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Цена: ${tp_price:.4f}\n"
            f"Объём: {tp_qty} ({percent}%)\n\n"
            f"💡 Используй 📊 Позиции для проверки"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except BybitError as e:
        logger.error(f"Error placing TP order: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при установке TP:\n{html.escape(str(e))}"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())


# ============================================================
# CALLBACK: Отмена всех TP
# ============================================================

@router.callback_query(F.data.startswith("tp_cancel_all:"))
async def cancel_all_tp(callback: CallbackQuery, settings_storage):
    """Отменить все TP ордера для позиции"""
    await callback.answer("Отменяю TP...")

    symbol = callback.data.split(":")[1]

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)

        # Получаем позицию для определения стороны
        positions = await client.get_positions(symbol=symbol)
        if not positions:
            await callback.message.edit_text(f"❌ Позиция {symbol} не найдена")
            return

        position = positions[0]
        side = position.get('side')

        # Получаем все открытые ордера
        orders = await client.get_open_orders(symbol=symbol)

        cancelled_count = 0
        for order in orders:
            # TP = reduceOnly Limit ордер противоположной стороны
            if order.get('reduceOnly') and order.get('orderType') == 'Limit':
                order_side = order.get('side')
                is_tp = (side == 'Buy' and order_side == 'Sell') or \
                        (side == 'Sell' and order_side == 'Buy')
                if is_tp:
                    try:
                        await client.cancel_order(
                            symbol=symbol,
                            order_id=order.get('orderId')
                        )
                        cancelled_count += 1
                    except Exception as e:
                        logger.error(f"Error cancelling TP order: {e}")

        if cancelled_count > 0:
            await callback.message.edit_text(
                f"✅ Отменено {cancelled_count} TP ордеров для {symbol}\n\n"
                f"💡 Используй 📊 Позиции для проверки"
            )
        else:
            await callback.message.edit_text(
                f"ℹ️ Не найдено TP ордеров для отмены"
            )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except BybitError as e:
        logger.error(f"Error cancelling TP orders: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка: {html.escape(str(e))}"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
