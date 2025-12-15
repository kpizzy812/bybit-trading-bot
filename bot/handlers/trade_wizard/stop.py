"""
Trade Wizard - Шаг 5: Установка Stop Loss
Поддерживает 3 режима:
- 📐 Stop % (быстро) - пресеты 0.8%, 1%, 1.5%, 2%, 2.5%
- ✍️ Цена вручную - для структурных уровней
- 🤖 AI сценарии - будущая фича
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.states.trade_states import TradeStates
from bot.keyboards import trade_kb
from .utils import calculate_stop_from_percent

router = Router()


# ============================================================
# Шаг 5: Выбор режима установки стопа
# ============================================================

@router.callback_query(TradeStates.choosing_stop_mode, F.data.startswith("stop_mode:"))
async def stop_mode_selected(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора режима установки стопа"""
    mode = callback.data.split(":")[1]  # "percent" or "manual"

    # Сохраняем режим
    await state.update_data(stop_mode=mode)

    data = await state.get_data()
    symbol = data.get('symbol')
    side = data.get('side')
    entry_price = data.get('entry_price')
    side_text = "🟢 Long" if side == "Buy" else "🔴 Short"
    entry_type = data.get('entry_type')

    if mode == "percent":
        # Режим % - показываем пресеты
        await state.set_state(TradeStates.choosing_stop_percent)

        await callback.message.edit_text(
            f"📊 <b>Символ:</b> {symbol}\n"
            f"🔄 <b>Направление:</b> {side_text}\n"
            f"⚡ <b>Вход:</b> {entry_type} @ ${entry_price:.4f}\n\n"
            f"📐 <b>Выбери % для стопа:</b>\n"
            f"<i>Stop будет на {entry_price:.4f} ± X%</i>",
            reply_markup=trade_kb.get_stop_percent_keyboard()
        )
        await callback.answer()

    elif mode == "manual":
        # Режим вручную - запрашиваем цену
        await state.set_state(TradeStates.entering_stop)

        side_hint = "ниже" if side == "Buy" else "выше"

        await callback.message.edit_text(
            f"📊 <b>Символ:</b> {symbol}\n"
            f"🔄 <b>Направление:</b> {side_text}\n"
            f"⚡ <b>Вход:</b> {entry_type} @ ${entry_price:.4f}\n\n"
            f"🛑 <b>Введи цену Stop Loss:</b>\n"
            f"<i>Для {side_text} стоп должен быть {side_hint} входа</i>\n"
            f"<i>Например: {entry_price * 0.98:.4f}</i>",
            reply_markup=trade_kb.get_skip_button()
        )
        await callback.answer()


# ============================================================
# Шаг 5a: Выбор % для стопа
# ============================================================

@router.callback_query(TradeStates.choosing_stop_percent, F.data.startswith("stop_percent:"))
async def stop_percent_selected(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора % для стопа"""
    percent_str = callback.data.split(":")[1]

    if percent_str == "custom":
        # Custom % - запрашиваем ввод
        await callback.message.edit_text(
            "💎 <b>Введи свой % для стопа:</b>\n"
            "<i>Например: 1.8</i>",
            reply_markup=trade_kb.get_skip_button()
        )
        await callback.answer()
        return

    try:
        percent = float(percent_str)

        # Рассчитываем stop price от %
        data = await state.get_data()
        entry_price = data.get('entry_price')
        side = data.get('side')

        stop_price = calculate_stop_from_percent(entry_price, percent, side)

        # Сохраняем
        await state.update_data(
            stop_price=stop_price,
            stop_percent=percent
        )

        # Переходим к выбору риска (импорт здесь для избежания circular import)
        from .risk_leverage import move_to_risk_selection
        await move_to_risk_selection(callback.message, state)
        await callback.answer()

    except ValueError:
        await callback.answer("❌ Ошибка расчёта", show_alert=True)


@router.message(TradeStates.choosing_stop_percent, F.text)
async def custom_stop_percent_entered(message: Message, state: FSMContext):
    """Обработка custom % для стопа"""
    try:
        percent = float(message.text.strip())

        if percent <= 0 or percent > 50:
            await message.answer("❌ % должен быть от 0 до 50")
            return

        # Рассчитываем stop price
        data = await state.get_data()
        entry_price = data.get('entry_price')
        side = data.get('side')

        stop_price = calculate_stop_from_percent(entry_price, percent, side)

        # Сохраняем
        await state.update_data(
            stop_price=stop_price,
            stop_percent=percent
        )

        # Переходим к выбору риска
        from .risk_leverage import move_to_risk_selection
        await move_to_risk_selection(message, state)

    except ValueError:
        await message.answer("❌ Введи корректный % (например: 1.8)")


# ============================================================
# Шаг 5b: Ввод стопа вручную
# ============================================================

@router.message(TradeStates.entering_stop, F.text)
async def stop_price_entered(message: Message, state: FSMContext):
    """Обработка ввода цены стопа вручную"""
    try:
        stop_price = float(message.text.strip())

        data = await state.get_data()
        entry_price = data.get('entry_price')
        side = data.get('side')

        # Валидация направления стопа
        if side == "Buy" and stop_price >= entry_price:
            await message.answer(
                f"❌ Для Long стоп должен быть НИЖЕ входа\n"
                f"Entry: ${entry_price:.4f}\n"
                f"Твой стоп: ${stop_price:.4f}"
            )
            return

        if side == "Sell" and stop_price <= entry_price:
            await message.answer(
                f"❌ Для Short стоп должен быть ВЫШЕ входа\n"
                f"Entry: ${entry_price:.4f}\n"
                f"Твой стоп: ${stop_price:.4f}"
            )
            return

        # Сохраняем
        await state.update_data(
            stop_price=stop_price,
            stop_percent=None  # Не использовался % режим
        )

        # Переходим к выбору риска
        from .risk_leverage import move_to_risk_selection
        await move_to_risk_selection(message, state)

    except ValueError:
        await message.answer("❌ Введи корректную цену (например: 128.50)")
