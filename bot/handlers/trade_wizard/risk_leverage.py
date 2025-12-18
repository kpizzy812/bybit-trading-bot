"""
Trade Wizard - Шаг 6: Риск и плечо
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.states.trade_states import TradeStates
from bot.keyboards import trade_kb
from services.risk_percent import (
    get_equity_cached,
    calc_risk_usd_from_pct,
    validate_risk_pct,
    validate_risk_usd,
    MIN_RISK_PCT,
    MAX_RISK_PCT,
)
import config

logger = logging.getLogger(__name__)
router = Router()


async def move_to_risk_selection(message_or_query, state: FSMContext, settings_storage, user_id: int):
    """Переход к выбору риска"""
    await state.set_state(TradeStates.choosing_risk_lev)

    data = await state.get_data()
    symbol = data.get('symbol')
    side = data.get('side')
    entry_price = data.get('entry_price')
    stop_price = data.get('stop_price')
    stop_percent = data.get('stop_percent')
    entry_type = data.get('entry_type')

    # Определяем режим риска
    user_settings = await settings_storage.get_settings(user_id)
    risk_mode = 'percent' if user_settings.trading_capital_mode == 'auto' else 'usd'

    # Сохраняем режим в state
    await state.update_data(risk_mode=risk_mode)

    side_text = "🟢 Long" if side == "Buy" else "🔴 Short"
    stop_distance_percent = abs(entry_price - stop_price) / entry_price * 100

    stop_info = f"${stop_price:.4f}"
    if stop_percent:
        stop_info += f" ({stop_percent}%)"
    else:
        stop_info += f" ({stop_distance_percent:.2f}%)"

    # Базовый текст
    text = (
        f"📊 <b>Символ:</b> {symbol}\n"
        f"🔄 <b>Направление:</b> {side_text}\n"
        f"⚡ <b>Вход:</b> {entry_type} @ ${entry_price:.4f}\n"
        f"🛑 <b>Стоп:</b> {stop_info}\n\n"
    )

    # Если процентный режим - получаем и показываем баланс
    if risk_mode == 'percent':
        try:
            equity, updated_data = await get_equity_cached(data, user_settings)
            await state.update_data(**updated_data)
            text += (
                f"💵 <b>Баланс:</b> ${equity:.2f}\n\n"
                f"💰 <b>Выбери % риска от баланса:</b>\n"
                f"<i>Рекомендуется 0.5–1%</i>"
            )
        except ValueError as e:
            # Ошибка получения баланса - показать сообщение
            text += f"⚠️ {e}\n\n<i>Попробуй позже или используй USD режим</i>"
    else:
        text += (
            f"💰 <b>Выбери размер риска или позиции:</b>\n"
            f"<i>• Risk - сумма потери при SL\n"
            f"• Position Size - размер позиции напрямую</i>"
        )

    # Определяем, можно ли редактировать сообщение
    from aiogram.types import Message

    if isinstance(message_or_query, Message):
        # Это сообщение пользователя - удаляем его и отправляем новое
        try:
            await message_or_query.delete()
        except:
            pass
        sent = await message_or_query.answer(
            text,
            reply_markup=trade_kb.get_risk_keyboard(risk_mode=risk_mode)
        )
        await state.update_data(last_bot_message_id=sent.message_id)
    else:
        # Это CallbackQuery или другой объект с edit_text
        await message_or_query.edit_text(
            text,
            reply_markup=trade_kb.get_risk_keyboard(risk_mode=risk_mode)
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


@router.callback_query(TradeStates.choosing_risk_lev, F.data.startswith("risk_pct:"))
async def risk_percent_selected(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Обработка выбора процентного риска (когда trading_capital_mode == 'auto')"""
    pct_str = callback.data.split(":")[1]

    if pct_str == "custom":
        # Переход к вводу custom процента
        await callback.message.edit_text(
            f"💰 <b>Введи процент риска:</b>\n"
            f"<i>Диапазон: {MIN_RISK_PCT}% – {MAX_RISK_PCT}%</i>\n"
            f"<i>Рекомендуется: 0.5–1%</i>\n\n"
            f"<i>Например: 0.75</i>",
            reply_markup=trade_kb.get_skip_button()
        )
        await state.update_data(input_mode="risk_pct")
        await callback.answer()
        return

    try:
        pct = float(pct_str)

        # Валидация процента
        is_valid, error = validate_risk_pct(pct)
        if not is_valid:
            await callback.answer(f"❌ {error}", show_alert=True)
            return

        # Получаем баланс из кэша
        data = await state.get_data()
        user_settings = await settings_storage.get_settings(callback.from_user.id)

        try:
            equity, updated_data = await get_equity_cached(data, user_settings)
            await state.update_data(**updated_data)
        except ValueError as e:
            await callback.answer(f"❌ {e}", show_alert=True)
            return

        # Рассчитываем risk_usd
        risk_usd = calc_risk_usd_from_pct(equity, pct)

        # Валидация итогового риска
        max_risk = user_settings.max_risk_per_trade
        is_valid, error = validate_risk_usd(risk_usd, max_risk)
        if not is_valid:
            await callback.answer(f"❌ {error}", show_alert=True)
            return

        logger.info(f"User {callback.from_user.id}: {pct}% of ${equity:.2f} = ${risk_usd:.2f}")

        await state.update_data(
            risk_usd=risk_usd,
            risk_percent=pct,
            position_size_usd=None,
            input_mode="risk"
        )
        await move_to_leverage_selection(callback.message, state)
        await callback.answer(f"Риск: {pct}% = ${risk_usd:.2f}")

    except ValueError:
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(TradeStates.choosing_risk_lev, F.text)
async def custom_risk_entered(message: Message, state: FSMContext, settings_storage):
    """Обработка custom риска, position size или custom процента"""
    try:
        value = float(message.text.strip())

        if value <= 0:
            await message.answer("❌ Значение должно быть больше 0")
            return

        # Проверяем режим ввода
        data = await state.get_data()
        input_mode = data.get('input_mode', 'risk')
        user_settings = await settings_storage.get_settings(message.from_user.id)

        if input_mode == "position_size":
            # Режим Position Size - сохраняем position_size_usd
            await state.update_data(position_size_usd=value, risk_usd=None)
            await move_to_leverage_selection(message, state)

        elif input_mode == "risk_pct":
            # Режим процентного риска
            pct = value

            # Валидация процента
            is_valid, error = validate_risk_pct(pct)
            if not is_valid:
                await message.answer(f"❌ {error}")
                return

            # Получаем баланс из кэша
            try:
                equity, updated_data = await get_equity_cached(data, user_settings)
                await state.update_data(**updated_data)
            except ValueError as e:
                await message.answer(f"❌ {e}")
                return

            # Рассчитываем risk_usd
            risk_usd = calc_risk_usd_from_pct(equity, pct)

            # Валидация итогового риска
            max_risk = user_settings.max_risk_per_trade
            is_valid, error = validate_risk_usd(risk_usd, max_risk)
            if not is_valid:
                await message.answer(f"❌ {error}")
                return

            logger.info(f"User {message.from_user.id}: custom {pct}% of ${equity:.2f} = ${risk_usd:.2f}")

            await state.update_data(
                risk_usd=risk_usd,
                risk_percent=pct,
                position_size_usd=None,
                input_mode="risk"
            )
            await message.answer(f"✅ Риск: {pct}% = ${risk_usd:.2f}")
            await move_to_leverage_selection(message, state)

        else:
            # Режим Risk в USD - проверяем лимиты и сохраняем risk_usd
            max_risk = user_settings.max_risk_per_trade

            if value > max_risk:
                await message.answer(f"❌ Риск ${value} превышает макс. ${max_risk}")
                return

            await state.update_data(risk_usd=value, position_size_usd=None)
            await move_to_leverage_selection(message, state)

    except ValueError:
        data = await state.get_data()
        input_mode = data.get('input_mode', 'risk')
        if input_mode == "risk_pct":
            await message.answer("❌ Введи корректный процент (например: 0.75)")
        else:
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
