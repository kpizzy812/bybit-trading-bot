"""
Хендлеры для отображения деталей позиций и ордеров.
"""
import html
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile
from aiogram.exceptions import TelegramBadRequest

from bot.keyboards.positions_kb import (
    get_position_detail_kb,
    get_order_detail_kb
)
from services.bybit import BybitClient
from bot.handlers.positions.formatters import (
    format_position_detail,
    format_order_detail
)
from bot.handlers.positions.chart_generators import generate_position_chart

logger = logging.getLogger(__name__)
router = Router()


async def safe_edit_or_send(callback: CallbackQuery, text: str, reply_markup=None):
    """Безопасное редактирование сообщения (для сообщений с фото)."""
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "no text in the message" in str(e) or "message can't be edited" in str(e):
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=reply_markup)
        else:
            raise


@router.callback_query(F.data.startswith("pos_detail:"))
async def show_position_detail(callback: CallbackQuery, settings_storage):
    """Показать детали конкретной позиции с графиком"""
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
            await safe_edit_or_send(
                callback,
                f"❌ Позиция {symbol} не найдена"
            )
            return

        position = positions[0]

        # Ищем ladder TP ордера для этой позиции
        tp_orders = []
        try:
            all_orders = await client.get_open_orders(symbol=symbol)
            for o in all_orders:
                order_type = o.get('orderType', '')
                price = float(o.get('price', 0))

                if (o.get('reduceOnly', False) and
                    order_type == 'Limit' and
                    price > 0):
                    tp_orders.append({
                        'price': price,
                        'qty': o.get('qty', '0')
                    })
            tp_orders.sort(key=lambda x: x['price'])
        except Exception as e:
            logger.warning(f"Error fetching TP orders: {e}")

        # Формируем детальную информацию
        text = await format_position_detail(position, tp_orders=tp_orders)

        # Генерируем график
        chart_png = await generate_position_chart(client, position, tp_orders)

        # Удаляем старое сообщение и отправляем новое с фото
        try:
            await callback.message.delete()
        except Exception:
            pass

        if chart_png:
            photo = BufferedInputFile(chart_png, filename=f"{symbol}_position.png")
            await callback.message.answer_photo(
                photo=photo,
                caption=text if len(text) <= 1024 else None,
                parse_mode="HTML",
                reply_markup=get_position_detail_kb(symbol)
            )
            if len(text) > 1024:
                await callback.message.answer(
                    text,
                    parse_mode="HTML",
                    reply_markup=get_position_detail_kb(symbol)
                )
        else:
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=get_position_detail_kb(symbol)
            )

    except Exception as e:
        logger.error(f"Error showing position detail: {e}")
        await callback.message.answer(
            f"❌ Ошибка при получении позиции:\n{html.escape(str(e))}"
        )


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
            await safe_edit_or_send(
                callback,
                f"❌ Ордер не найден (возможно уже исполнен или отменён)"
            )
            return

        # Формируем детали ордера
        text = await format_order_detail(order)
        order_id = order.get('orderId')

        await safe_edit_or_send(
            callback,
            text,
            reply_markup=get_order_detail_kb(symbol, order_id)
        )

    except Exception as e:
        logger.error(f"Error showing order detail: {e}")
        await safe_edit_or_send(
            callback,
            f"❌ Ошибка при получении ордера:\n{html.escape(str(e))}"
        )
