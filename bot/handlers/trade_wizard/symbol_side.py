"""
Trade Wizard - Шаги 1-2: Выбор символа и направления
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.states.trade_states import TradeStates
from bot.keyboards import trade_kb
import config

router = Router()


# ============================================================
# Шаг 1: Выбор символа
# ============================================================

@router.callback_query(TradeStates.choosing_symbol, F.data.startswith("symbol:"))
async def symbol_selected(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Обработка выбора символа"""
    symbol = callback.data.split(":")[1]

    if symbol not in config.SUPPORTED_SYMBOLS_SET:
        await callback.answer("❌ Неподдерживаемый символ", show_alert=True)
        return

    # Сохраняем в FSM context
    await state.update_data(symbol=symbol)

    # Переходим к выбору направления
    await state.set_state(TradeStates.choosing_side)

    # Получаем настройки для проверки shorts_enabled
    user_settings = await settings_storage.get_settings(callback.from_user.id)
    shorts_enabled = user_settings.get('shorts_enabled', config.DEFAULT_SHORTS_ENABLED)

    await callback.message.edit_text(
        f"📊 <b>Символ:</b> {symbol}\n\n"
        f"🔄 <b>Выбери направление:</b>",
        reply_markup=trade_kb.get_side_keyboard(shorts_enabled=shorts_enabled)
    )
    await callback.answer()


# ============================================================
# Шаг 2: Выбор направления (Long/Short)
# ============================================================

@router.callback_query(TradeStates.choosing_side, F.data.startswith("side:"))
async def side_selected(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора направления"""
    side = callback.data.split(":")[1]  # "Buy" or "Sell"

    if side not in ["Buy", "Sell"]:
        await callback.answer("❌ Неверное направление", show_alert=True)
        return

    # Сохраняем
    await state.update_data(side=side)

    # Переходим к выбору типа входа
    await state.set_state(TradeStates.choosing_entry_type)

    side_text = "🟢 Long" if side == "Buy" else "🔴 Short"
    data = await state.get_data()
    symbol = data.get('symbol')

    await callback.message.edit_text(
        f"📊 <b>Символ:</b> {symbol}\n"
        f"🔄 <b>Направление:</b> {side_text}\n\n"
        f"⚡ <b>Выбери тип входа:</b>",
        reply_markup=trade_kb.get_entry_type_keyboard()
    )
    await callback.answer()
