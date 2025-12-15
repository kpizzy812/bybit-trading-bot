"""
Trade Wizard - Шаг 6: Риск и плечо
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.states.trade_states import TradeStates
from bot.keyboards import trade_kb
import config

router = Router()


async def move_to_risk_selection(message_or_query, state: FSMContext):
    """Переход к выбору риска"""
    await state.set_state(TradeStates.choosing_risk_lev)

    data = await state.get_data()
    symbol = data.get('symbol')
    side = data.get('side')
    entry_price = data.get('entry_price')
    stop_price = data.get('stop_price')
    stop_percent = data.get('stop_percent')
    entry_type = data.get('entry_type')

    side_text = "🟢 Long" if side == "Buy" else "🔴 Short"
    stop_distance_percent = abs(entry_price - stop_price) / entry_price * 100

    stop_info = f"${stop_price:.4f}"
    if stop_percent:
        stop_info += f" ({stop_percent}%)"
    else:
        stop_info += f" ({stop_distance_percent:.2f}%)"

    text = (
        f"📊 <b>Символ:</b> {symbol}\n"
        f"🔄 <b>Направление:</b> {side_text}\n"
        f"⚡ <b>Вход:</b> {entry_type} @ ${entry_price:.4f}\n"
        f"🛑 <b>Стоп:</b> {stop_info}\n\n"
        f"💰 <b>Выбери размер риска или позиции:</b>\n"
        f"<i>• Risk - сумма потери при SL\n"
        f"• Position Size - размер позиции напрямую</i>"
    )

    # Определяем, можно ли редактировать сообщение
    # Если это Message от пользователя - отправляем новое, удаляем старое
    # Если это Message бота (из state) или есть last_bot_message_id - редактируем
    from aiogram.types import Message

    if isinstance(message_or_query, Message):
        # Это сообщение пользователя - удаляем его и отправляем новое
        try:
            await message_or_query.delete()
        except:
            pass
        sent = await message_or_query.answer(
            text,
            reply_markup=trade_kb.get_risk_keyboard()
        )
        await state.update_data(last_bot_message_id=sent.message_id)
    else:
        # Это CallbackQuery или другой объект с edit_text
        await message_or_query.edit_text(
            text,
            reply_markup=trade_kb.get_risk_keyboard()
        )


@router.callback_query(TradeStates.choosing_risk_lev, F.data.startswith("risk:"))
async def risk_selected(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Обработка выбора риска"""
    risk_str = callback.data.split(":")[1]

    if risk_str == "custom":
        await callback.message.edit_text(
            "💰 <b>Введи размер риска в USD:</b>\n"
            f"<i>Максимум: ${config.MAX_RISK_PER_TRADE}</i>\n"
            f"<i>Например: 12.50</i>",
            reply_markup=trade_kb.get_skip_button()
        )
        await callback.answer()
        return

    if risk_str == "position_size":
        # Режим Position Size - указываем размер позиции напрямую
        await callback.message.edit_text(
            "💵 <b>Введи размер позиции в USD:</b>\n"
            f"<i>Это будет размер твоей позиции (qty * entry_price)</i>\n"
            f"<i>Например: 5 (для позиции на $5)</i>",
            reply_markup=trade_kb.get_skip_button()
        )
        await state.update_data(input_mode="position_size")
        await callback.answer()
        return

    try:
        risk_usd = float(risk_str)

        user_settings = await settings_storage.get_settings(callback.from_user.id)
        max_risk = user_settings.max_risk_per_trade

        if risk_usd > max_risk:
            await callback.answer(
                f"❌ Риск ${risk_usd} превышает макс. ${max_risk}",
                show_alert=True
            )
            return

        await state.update_data(risk_usd=risk_usd, position_size_usd=None, input_mode="risk")
        await move_to_leverage_selection(callback.message, state)
        await callback.answer()

    except ValueError:
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(TradeStates.choosing_risk_lev, F.text)
async def custom_risk_entered(message: Message, state: FSMContext, settings_storage):
    """Обработка custom риска или position size"""
    try:
        value = float(message.text.strip())

        if value <= 0:
            await message.answer("❌ Значение должно быть больше 0")
            return

        # Проверяем режим ввода
        data = await state.get_data()
        input_mode = data.get('input_mode', 'risk')

        if input_mode == "position_size":
            # Режим Position Size - сохраняем position_size_usd
            await state.update_data(position_size_usd=value, risk_usd=None)
            await move_to_leverage_selection(message, state)
        else:
            # Режим Risk - проверяем лимиты и сохраняем risk_usd
            user_settings = await settings_storage.get_settings(message.from_user.id)
            max_risk = user_settings.max_risk_per_trade

            if value > max_risk:
                await message.answer(f"❌ Риск ${value} превышает макс. ${max_risk}")
                return

            await state.update_data(risk_usd=value, position_size_usd=None)
            await move_to_leverage_selection(message, state)

    except ValueError:
        await message.answer("❌ Введи корректную сумму (например: 12.50)")


async def move_to_leverage_selection(message_or_query, state: FSMContext):
    """Переход к выбору плеча"""
    data = await state.get_data()
    symbol = data.get('symbol')
    side = data.get('side')
    entry_price = data.get('entry_price')
    stop_price = data.get('stop_price')
    risk_usd = data.get('risk_usd')
    entry_type = data.get('entry_type')

    side_text = "🟢 Long" if side == "Buy" else "🔴 Short"
    stop_distance_percent = abs(entry_price - stop_price) / entry_price * 100

    text = (
        f"📊 <b>Символ:</b> {symbol}\n"
        f"🔄 <b>Направление:</b> {side_text}\n"
        f"⚡ <b>Вход:</b> {entry_type} @ ${entry_price:.4f}\n"
        f"🛑 <b>Стоп:</b> ${stop_price:.4f} ({stop_distance_percent:.2f}%)\n"
        f"💰 <b>Риск:</b> ${risk_usd}\n\n"
        f"📊 <b>Выбери плечо (leverage):</b>\n"
        f"<i>Влияет только на маржу, не на PnL!</i>"
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
            reply_markup=trade_kb.get_leverage_keyboard()
        )
        await state.update_data(last_bot_message_id=sent.message_id)
    else:
        # Это CallbackQuery
        await message_or_query.edit_text(
            text,
            reply_markup=trade_kb.get_leverage_keyboard()
        )


@router.callback_query(TradeStates.choosing_risk_lev, F.data.startswith("leverage:"))
async def leverage_selected(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора плеча"""
    lev_str = callback.data.split(":")[1]

    if lev_str == "custom":
        await callback.message.edit_text(
            "📊 <b>Введи плечо:</b>\n"
            f"<i>Максимум: {config.MAX_LEVERAGE}x</i>\n"
            f"<i>Например: 7</i>",
            reply_markup=trade_kb.get_skip_button()
        )
        await callback.answer()
        return

    try:
        leverage = int(lev_str)

        if leverage > config.MAX_LEVERAGE:
            await callback.answer(
                f"❌ Плечо {leverage}x превышает макс. {config.MAX_LEVERAGE}x",
                show_alert=True
            )
            return

        await state.update_data(leverage=leverage)
        await state.set_state(TradeStates.choosing_tp)

        from .take_profit import move_to_tp_selection
        await move_to_tp_selection(callback.message, state)
        await callback.answer()

    except ValueError:
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(TradeStates.choosing_risk_lev, F.text.regexp(r'^\d+$'))
async def custom_leverage_entered(message: Message, state: FSMContext):
    """Обработка custom плеча"""
    try:
        leverage = int(message.text.strip())

        if leverage < 1 or leverage > config.MAX_LEVERAGE:
            await message.answer(f"❌ Плечо должно быть от 1 до {config.MAX_LEVERAGE}")
            return

        await state.update_data(leverage=leverage)
        await state.set_state(TradeStates.choosing_tp)

        from .take_profit import move_to_tp_selection
        await move_to_tp_selection(message, state)

    except ValueError:
        await message.answer("❌ Введи корректное число (например: 7)")
