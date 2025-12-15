"""
Trade Wizard - Шаг 7: Take Profit
Поддерживает 3 режима:
- 🎯 Single TP - одна цена
- 🪜 Ladder - 2 уровня (50%/50%)
- 📐 By RR - расчёт от Risk/Reward ratio
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.states.trade_states import TradeStates
from bot.keyboards import trade_kb

router = Router()


async def move_to_tp_selection(message_or_query, state: FSMContext):
    """Переход к выбору TP"""
    data = await state.get_data()
    symbol = data.get('symbol')
    side = data.get('side')
    entry_price = data.get('entry_price')
    stop_price = data.get('stop_price')
    risk_usd = data.get('risk_usd')
    leverage = data.get('leverage')
    entry_type = data.get('entry_type')

    side_text = "🟢 Long" if side == "Buy" else "🔴 Short"

    # Рассчитываем примерный qty для информации
    stop_distance = abs(entry_price - stop_price)
    qty_estimate = risk_usd / stop_distance
    margin_estimate = (qty_estimate * entry_price) / leverage

    text = (
        f"📊 <b>Символ:</b> {symbol}\n"
        f"🔄 <b>Направление:</b> {side_text}\n"
        f"⚡ <b>Вход:</b> {entry_type} @ ${entry_price:.4f}\n"
        f"🛑 <b>Стоп:</b> ${stop_price:.4f}\n"
        f"💰 <b>Риск:</b> ${risk_usd}\n"
        f"📊 <b>Плечо:</b> {leverage}x\n"
        f"📦 <b>Примерный размер:</b> ~{qty_estimate:.4f} {symbol.replace('USDT', '')}\n"
        f"💵 <b>Требуемая маржа:</b> ~${margin_estimate:.2f}\n\n"
        f"🎯 <b>Выбери режим Take Profit:</b>"
    )

    from aiogram.types import Message

    if isinstance(message_or_query, Message):
        # Это сообщение пользователя - удаляем его и отправляем новое
        try:
            await message_or_query.delete()
        except:
            pass
        sent = await message_or_query.answer(
            text,
            reply_markup=trade_kb.get_tp_mode_keyboard()
        )
        await state.update_data(last_bot_message_id=sent.message_id)
    else:
        # Это CallbackQuery
        await message_or_query.edit_text(
            text,
            reply_markup=trade_kb.get_tp_mode_keyboard()
        )


@router.callback_query(TradeStates.choosing_tp, F.data.startswith("tp_mode:"))
async def tp_mode_selected(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора режима TP"""
    tp_mode = callback.data.split(":")[1]  # "single", "ladder", "rr"

    await state.update_data(tp_mode=tp_mode)

    if tp_mode == "rr":
        # RR режим - показываем пресеты
        await callback.message.edit_text(
            "📐 <b>Выбери Risk/Reward ratio:</b>\n"
            "<i>RR 2.0 = профит в 2 раза больше риска</i>",
            reply_markup=trade_kb.get_tp_rr_keyboard()
        )
        await callback.answer()

    elif tp_mode == "single":
        # Single TP - запрашиваем цену
        data = await state.get_data()
        entry_price = data.get('entry_price')
        side = data.get('side')
        side_text = "🟢 Long" if side == "Buy" else "🔴 Short"
        hint = "выше" if side == "Buy" else "ниже"

        await callback.message.edit_text(
            f"🎯 <b>Введи цену Take Profit:</b>\n"
            f"<i>Для {side_text} TP должен быть {hint} входа</i>\n"
            f"<i>Entry: ${entry_price:.4f}</i>\n"
            f"<i>Например: {entry_price * 1.05:.4f}</i>",
            reply_markup=trade_kb.get_skip_button()
        )
        await callback.answer()

    elif tp_mode == "ladder":
        # Ladder TP - по умолчанию используем RR 2.0 и 3.0 для двух уровней
        await state.update_data(
            tp_rr_1=2.0,
            tp_rr_2=3.0
        )
        from .confirmation import move_to_confirmation
        await move_to_confirmation(callback.message, state)
        await callback.answer()


@router.callback_query(TradeStates.choosing_tp, F.data.startswith("tp_rr:"))
async def tp_rr_selected(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора RR"""
    rr_str = callback.data.split(":")[1]

    if rr_str == "custom":
        await callback.message.edit_text(
            "💎 <b>Введи свой RR:</b>\n"
            "<i>Например: 2.5</i>",
            reply_markup=trade_kb.get_skip_button()
        )
        await callback.answer()
        return

    try:
        rr = float(rr_str)
        await state.update_data(tp_rr=rr)

        from .confirmation import move_to_confirmation
        await move_to_confirmation(callback.message, state)
        await callback.answer()

    except ValueError:
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(TradeStates.choosing_tp, F.text)
async def tp_value_entered(message: Message, state: FSMContext):
    """Обработка ввода TP (цена или custom RR)"""
    data = await state.get_data()
    tp_mode = data.get('tp_mode')

    try:
        value = float(message.text.strip())

        if tp_mode == "rr":
            # Custom RR
            if value <= 0:
                await message.answer("❌ RR должен быть больше 0")
                return

            await state.update_data(tp_rr=value)

        elif tp_mode == "single":
            # Single TP цена
            entry_price = data.get('entry_price')
            side = data.get('side')

            # Валидация
            if side == "Buy" and value <= entry_price:
                await message.answer(f"❌ Для Long TP должен быть ВЫШЕ входа (${entry_price:.4f})")
                return

            if side == "Sell" and value >= entry_price:
                await message.answer(f"❌ Для Short TP должен быть НИЖЕ входа (${entry_price:.4f})")
                return

            await state.update_data(tp_price=value)

        # Переходим к подтверждению
        from .confirmation import move_to_confirmation
        await move_to_confirmation(message, state)

    except ValueError:
        await message.answer("❌ Введи корректное число")
