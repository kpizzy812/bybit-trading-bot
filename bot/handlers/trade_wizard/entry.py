"""
Trade Wizard - Шаги 3-4: Тип входа и цена
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from loguru import logger

from bot.states.trade_states import TradeStates
from bot.keyboards import trade_kb
from services.bybit import BybitClient
from .utils import get_current_price
import config

router = Router()


# ============================================================
# Шаг 3: Выбор типа входа (Market/Limit)
# ============================================================

@router.callback_query(TradeStates.choosing_entry_type, F.data.startswith("entry_type:"))
async def entry_type_selected(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Обработка выбора типа входа"""
    entry_type = callback.data.split(":")[1]  # "Market" or "Limit"

    if entry_type not in ["Market", "Limit"]:
        await callback.answer("❌ Неверный тип", show_alert=True)
        return

    # Сохраняем
    await state.update_data(entry_type=entry_type)

    data = await state.get_data()
    symbol = data.get('symbol')
    side = data.get('side')
    side_text = "🟢 Long" if side == "Buy" else "🔴 Short"

    if entry_type == "Market":
        # Market вход - получаем текущую цену и переходим к выбору режима стопа
        try:
            user_settings = await settings_storage.get_settings(callback.from_user.id)
            testnet = user_settings.testnet_mode

            client = BybitClient(testnet=testnet)
            current_price = await get_current_price(client, symbol)

            # Сохраняем текущую цену как entry (примерную)
            await state.update_data(entry_price=current_price)

            # Переходим к выбору режима стопа
            await state.set_state(TradeStates.choosing_stop_mode)

            await callback.message.edit_text(
                f"📊 <b>Символ:</b> {symbol}\n"
                f"🔄 <b>Направление:</b> {side_text}\n"
                f"⚡ <b>Вход:</b> Market (≈${current_price:.4f})\n\n"
                f"🛑 <b>Как установить стоп?</b>",
                reply_markup=trade_kb.get_stop_mode_keyboard()
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Error getting current price: {e}")
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
            return

    else:  # Limit
        # Переходим к вводу цены входа
        await state.set_state(TradeStates.entering_entry_price)

        await callback.message.edit_text(
            f"📊 <b>Символ:</b> {symbol}\n"
            f"🔄 <b>Направление:</b> {side_text}\n"
            f"⚡ <b>Вход:</b> Limit\n\n"
            f"💵 <b>Введи цену входа:</b>\n"
            f"<i>Например: 130.50</i>",
            reply_markup=trade_kb.get_skip_button()
        )
        await callback.answer()


# ============================================================
# Шаг 4: Ввод цены входа (только для Limit)
# ============================================================

@router.message(TradeStates.entering_entry_price, F.text)
async def entry_price_entered(message: Message, state: FSMContext):
    """Обработка ввода цены входа для Limit ордера"""
    try:
        entry_price = float(message.text.strip())

        if entry_price <= 0:
            await message.answer("❌ Цена должна быть больше 0")
            return

        # Сохраняем
        await state.update_data(entry_price=entry_price)

        # Переходим к выбору режима стопа
        await state.set_state(TradeStates.choosing_stop_mode)

        data = await state.get_data()
        symbol = data.get('symbol')
        side = data.get('side')
        side_text = "🟢 Long" if side == "Buy" else "🔴 Short"

        await message.answer(
            f"📊 <b>Символ:</b> {symbol}\n"
            f"🔄 <b>Направление:</b> {side_text}\n"
            f"⚡ <b>Вход:</b> Limit @ ${entry_price:.4f}\n\n"
            f"🛑 <b>Как установить стоп?</b>",
            reply_markup=trade_kb.get_stop_mode_keyboard()
        )

    except ValueError:
        await message.answer("❌ Введи корректную цену (например: 130.50)")
