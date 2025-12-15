"""
Хендлеры для управления позициями
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.keyboards.positions_kb import (
    get_positions_list_kb,
    get_position_detail_kb,
    get_move_sl_confirmation_kb,
    get_close_confirmation_kb,
    get_panic_close_all_confirmation_kb
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
async def refresh_positions(callback: CallbackQuery, settings_storage):
    """Обновить список позиций"""
    await callback.answer("🔄 Обновление...")

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)
        positions = await client.get_positions()

        if not positions:
            await callback.message.edit_text(
                "📊 <b>Открытых позиций нет</b>\n\n"
                "Используй <b>➕ Открыть сделку</b> чтобы начать торговлю"
            )
            return

        # Формируем список позиций
        text = "📊 <b>Твои открытые позиции:</b>\n\n"
        text += await _format_positions_list(positions)

        await callback.message.edit_text(
            text,
            reply_markup=get_positions_list_kb(positions)
        )

    except Exception as e:
        logger.error(f"Error refreshing positions: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при обновлении позиций:\n{str(e)}"
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

        # Формируем детальную информацию
        text = await _format_position_detail(position)

        await callback.message.edit_text(
            text,
            reply_markup=get_position_detail_kb(symbol)
        )

    except Exception as e:
        logger.error(f"Error showing position detail: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при получении позиции:\n{str(e)}"
        )


# ============================================================
# CALLBACK: Partial Close
# ============================================================

@router.callback_query(F.data.startswith("pos_partial:"))
async def partial_close_position(callback: CallbackQuery, settings_storage):
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

        # Выполняем partial close
        result = await client.partial_close(symbol=symbol, percent=percent)

        # Успешное закрытие
        await callback.message.edit_text(
            f"✅ <b>Позиция частично закрыта!</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Закрыто: {result['closed_qty']} ({percent}%)\n"
            f"Было: {result['total_size']}\n\n"
            f"💡 Используй <b>📊 Позиции</b> чтобы проверить текущее состояние",
            reply_markup=get_main_menu()
        )

    except BybitError as e:
        logger.error(f"Error partial closing position: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка при закрытии позиции</b>\n\n"
            f"{str(e)}\n\n"
            f"Попробуй снова или обратись к главному меню",
            reply_markup=get_main_menu()
        )


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
async def close_position_confirmed(callback: CallbackQuery, settings_storage):
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

        if percent == 100:
            # Полное закрытие
            await client.close_position(symbol=symbol)
            msg = f"✅ <b>Позиция {symbol} закрыта!</b>"
        else:
            # Partial close
            result = await client.partial_close(symbol=symbol, percent=percent)
            msg = (
                f"✅ <b>Позиция частично закрыта!</b>\n\n"
                f"Symbol: {symbol}\n"
                f"Закрыто: {result['closed_qty']} ({percent}%)"
            )

        await callback.message.edit_text(
            msg + "\n\n💡 Используй <b>📊 Позиции</b> чтобы проверить статус",
            reply_markup=get_main_menu()
        )

    except BybitError as e:
        logger.error(f"Error closing position: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка при закрытии</b>\n\n{str(e)}",
            reply_markup=get_main_menu()
        )


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
            f"💡 Позиция теперь защищена новым стопом",
            reply_markup=get_main_menu()
        )

    except BybitError as e:
        logger.error(f"Error moving SL: {e}")
        await state.clear()
        await message.answer(
            f"❌ <b>Ошибка при перемещении SL</b>\n\n{str(e)}",
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
async def panic_close_all_execute(callback: CallbackQuery, settings_storage):
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
                "📊 Нет открытых позиций для закрытия",
                reply_markup=get_main_menu()
            )
            return

        # Закрываем все позиции
        closed_symbols = []
        errors = []

        for position in positions:
            symbol = position.get('symbol')
            try:
                await client.close_position(symbol=symbol)
                closed_symbols.append(symbol)
                logger.info(f"Panic closed: {symbol}")
            except Exception as e:
                logger.error(f"Error panic closing {symbol}: {e}")
                errors.append(f"{symbol}: {str(e)}")

        # Результат
        result_text = "🧯 <b>Panic Close All выполнен</b>\n\n"

        if closed_symbols:
            result_text += f"✅ Закрыто позиций: {len(closed_symbols)}\n"
            result_text += "• " + "\n• ".join(closed_symbols) + "\n\n"

        if errors:
            result_text += f"❌ Ошибки ({len(errors)}):\n"
            result_text += "• " + "\n• ".join(errors) + "\n\n"

        result_text += "💡 Проверь статус в <b>📊 Позиции</b>"

        await callback.message.edit_text(
            result_text,
            reply_markup=get_main_menu()
        )

    except Exception as e:
        logger.error(f"Error during panic close all: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при Panic Close:\n{str(e)}",
            reply_markup=get_main_menu()
        )


# ============================================================
# CALLBACK: Назад к списку
# ============================================================

@router.callback_query(F.data == "pos_back_to_list")
async def back_to_positions_list(callback: CallbackQuery, settings_storage):
    """Вернуться к списку позиций"""
    await callback.answer()

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    try:
        client = BybitClient(testnet=testnet)
        positions = await client.get_positions()

        if not positions:
            await callback.message.edit_text(
                "📊 <b>Открытых позиций нет</b>\n\n"
                "Используй <b>➕ Открыть сделку</b> чтобы начать торговлю"
            )
            return

        text = "📊 <b>Твои открытые позиции:</b>\n\n"
        text += await _format_positions_list(positions)

        await callback.message.edit_text(
            text,
            reply_markup=get_positions_list_kb(positions)
        )

    except Exception as e:
        logger.error(f"Error going back to positions list: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка:\n{str(e)}",
            reply_markup=get_main_menu()
        )


# ============================================================
# HELPER FUNCTIONS
# ============================================================

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
        liq_price = pos.get('liqPrice', 'N/A')

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
            f"  Liq: ${liq_price}\n\n"
        )

    return text


async def _format_position_detail(position: dict) -> str:
    """Форматирование детальной информации о позиции"""
    symbol = position.get('symbol')
    side = position.get('side')
    size = float(position.get('size', 0))
    entry_price = float(position.get('avgPrice', 0))
    mark_price = float(position.get('markPrice', 0))
    liq_price = position.get('liqPrice', 'N/A')
    leverage = position.get('leverage', '?')
    unrealized_pnl = float(position.get('unrealisedPnl', 0))
    realized_pnl = float(position.get('cumRealisedPnl', 0))

    # SL/TP
    stop_loss = position.get('stopLoss', 'None')
    take_profit = position.get('takeProfit', 'None')

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
Liq Price: ${liq_price}

Size: {size}
Leverage: {leverage}x

<b>PnL:</b>
Unrealized: ${unrealized_pnl:.2f} ({roe:+.2f}%)
Realized: ${realized_pnl:.2f}

<b>Risk Management:</b>
SL: {stop_loss if stop_loss != 'None' else '❌ Not Set'}
TP: {take_profit if take_profit != 'None' else '❌ Not Set'}

💡 Выбери действие ниже:
"""

    return text.strip()
