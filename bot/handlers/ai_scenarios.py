"""
AI Scenarios Handler

Хендлер для работы с торговыми сценариями от Syntra AI.
Quick execution flow: выбор сценария → выбор риска → подтверждение → execute.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from loguru import logger

import config
from bot.states.trade_states import AIScenarioStates
from bot.keyboards import ai_scenarios_kb
from bot.keyboards.main_menu import get_main_menu
from datetime import datetime
from services.syntra_client import get_syntra_client, SyntraAPIError
from services.bybit import BybitClient
from services.risk_calculator import RiskCalculator
from services.trade_logger import TradeRecord
from utils.validators import round_qty, round_price

router = Router()


@router.message(Command("ai_scenarios"))
@router.message(F.text == "🤖 AI Сценарии")
async def ai_scenarios_start(message: Message, state: FSMContext):
    """Начало AI Scenarios flow - выбор символа"""

    # Проверка включены ли AI сценарии
    if not config.AI_SCENARIOS_ENABLED:
        await message.answer(
            "❌ AI Scenarios отключены.\n\n"
            "Включите в .env: AI_SCENARIOS_ENABLED=true"
        )
        return

    await state.set_state(AIScenarioStates.choosing_symbol)

    await message.answer(
        "🤖 <b>AI Trading Scenarios</b>\n\n"
        "Syntra AI проанализирует рынок и предложит торговые сценарии "
        "с конкретными уровнями входа, стопа и целей.\n\n"
        "📊 Выбери символ и таймфрейм для анализа:",
        reply_markup=ai_scenarios_kb.get_symbols_keyboard()
    )


@router.callback_query(AIScenarioStates.choosing_symbol, F.data.startswith("ai:symbol:"))
async def ai_symbol_selected(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора символа"""
    symbol = callback.data.split(":")[2]

    await state.update_data(symbol=symbol)
    await state.set_state(AIScenarioStates.choosing_timeframe)

    await callback.message.edit_text(
        f"📊 <b>Символ:</b> {symbol}\n\n"
        f"⏰ Выбери таймфрейм для анализа:",
        reply_markup=ai_scenarios_kb.get_timeframe_keyboard(symbol)
    )

    await callback.answer()


@router.callback_query(F.data.startswith("ai:analyze:"))
async def ai_analyze_market(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Запросить сценарии от Syntra AI"""
    # Парсинг callback: ai:analyze:BTCUSDT:4h
    parts = callback.data.split(":")
    symbol = parts[2]
    timeframe = parts[3]

    user_id = callback.from_user.id
    settings = await settings_storage.get_settings(user_id)

    await state.update_data(symbol=symbol, timeframe=timeframe)
    await state.set_state(AIScenarioStates.viewing_scenarios)

    # КРИТИЧНО: Ответить на callback СРАЗУ, ДО долгого запроса!
    await callback.answer()

    # Показать загрузку
    await callback.message.edit_text(
        f"🔄 <b>Анализирую {symbol} на {timeframe}...</b>\n\n"
        f"⏳ Syntra AI изучает рынок...",
        reply_markup=None
    )

    try:
        # Получить Syntra client
        syntra = get_syntra_client()

        # Опционально: передать user_params для фильтрации
        user_params = {
            "risk_usd": settings.default_risk_usd,
            "max_leverage": config.MAX_LEVERAGE,
        }

        # Запросить сценарии
        scenarios = await syntra.get_scenarios(
            symbol=symbol,
            timeframe=timeframe,
            max_scenarios=3,
            user_params=user_params
        )

        if not scenarios:
            await callback.message.edit_text(
                f"❌ <b>Нет сценариев</b>\n\n"
                f"Syntra AI не нашёл подходящих торговых сценариев для {symbol} на {timeframe}.\n\n"
                f"Попробуй другой символ или таймфрейм.",
                reply_markup=ai_scenarios_kb.get_symbols_keyboard()
            )
            await state.set_state(AIScenarioStates.choosing_symbol)
            return

        # Сохранить сценарии в state
        await state.update_data(scenarios=scenarios)

        # Показать список сценариев
        await show_scenarios_list(callback.message, scenarios, symbol, timeframe)

    except SyntraAPIError as e:
        logger.error(f"Syntra API error: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка Syntra AI:</b>\n\n{str(e)}\n\n"
            f"Проверь, что Syntra AI запущен и доступен по адресу:\n"
            f"<code>{config.SYNTRA_API_URL}</code>",
            reply_markup=ai_scenarios_kb.get_symbols_keyboard()
        )
        await state.set_state(AIScenarioStates.choosing_symbol)

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ <b>Неожиданная ошибка:</b>\n\n{str(e)}",
            reply_markup=ai_scenarios_kb.get_symbols_keyboard()
        )
        await state.set_state(AIScenarioStates.choosing_symbol)


async def show_scenarios_list(message: Message, scenarios: list, symbol: str, timeframe: str):
    """Показать список сценариев"""
    # Формируем текст со списком
    text = f"🤖 <b>AI Scenarios: {symbol} ({timeframe})</b>\n\n"

    for i, scenario in enumerate(scenarios, 1):
        bias = scenario.get("bias", "neutral")
        bias_emoji = "🟢" if bias == "long" else "🔴" if bias == "short" else "⚪"

        name = scenario.get("name", f"Scenario {i}")
        confidence = scenario.get("confidence", 0) * 100

        # Entry zone
        entry = scenario.get("entry", {})
        entry_min = entry.get("price_min", 0)
        entry_max = entry.get("price_max", 0)

        # Stop Loss
        stop_loss = scenario.get("stop_loss", {})
        sl_price = stop_loss.get("recommended", 0)

        # Все TP targets (показываем все 3)
        targets = scenario.get("targets", [])

        # Формируем текст сценария
        text += f"{i}. {bias_emoji} <b>{name}</b> ({confidence:.0f}%)\n"
        text += f"   Entry: ${entry_min:.2f} - ${entry_max:.2f}\n"
        text += f"   Stop: ${sl_price:.2f}\n"

        # Показываем каждый TP с его RR и % закрытия
        if targets:
            for idx, target in enumerate(targets[:3], 1):
                tp_price = target.get("price", 0)
                tp_rr = target.get("rr", 0)
                partial_pct = target.get("partial_close_pct", 100)
                text += f"   TP{idx}: ${tp_price:.2f} (RR {tp_rr:.1f}x) - {partial_pct}%\n"
        else:
            text += f"   TP: N/A\n"

        text += "\n"  # Пустая строка между сценариями

    text += "📌 Выбери сценарий для деталей:"

    await message.edit_text(
        text,
        reply_markup=ai_scenarios_kb.get_scenarios_keyboard(scenarios)
    )


@router.callback_query(AIScenarioStates.viewing_scenarios, F.data.startswith("ai:scenario:"))
async def ai_scenario_selected(callback: CallbackQuery, state: FSMContext):
    """Показать детали выбранного сценария"""
    scenario_index = int(callback.data.split(":")[2])

    data = await state.get_data()
    scenarios = data.get("scenarios", [])

    if scenario_index >= len(scenarios):
        await callback.answer("❌ Сценарий не найден", show_alert=True)
        return

    scenario = scenarios[scenario_index]

    await state.update_data(selected_scenario_index=scenario_index)
    await state.set_state(AIScenarioStates.viewing_detail)

    # Показать детали сценария
    await show_scenario_detail(callback.message, scenario, scenario_index)

    await callback.answer()


async def show_scenario_detail(message: Message, scenario: dict, scenario_index: int):
    """Показать детальную карточку сценария"""

    # Базовая информация
    name = scenario.get("name", "Unknown Scenario")
    bias = scenario.get("bias", "neutral")
    bias_emoji = "🟢" if bias == "long" else "🔴" if bias == "short" else "⚪"
    confidence = scenario.get("confidence", 0) * 100

    # Entry
    entry = scenario.get("entry", {})
    entry_min = entry.get("price_min", 0)
    entry_max = entry.get("price_max", 0)
    entry_avg = (entry_min + entry_max) / 2 if entry_min and entry_max else 0
    entry_type = entry.get("type", "market_order")

    # Stop Loss
    stop_loss = scenario.get("stop_loss", {})
    sl_price = stop_loss.get("recommended", 0)
    sl_reason = stop_loss.get("reason", "")

    # Targets
    targets = scenario.get("targets", [])
    targets_text = ""
    for target in targets:
        level = target.get("level", 0)
        price = target.get("price", 0)
        partial_close = target.get("partial_close_pct", 100)
        rr = target.get("rr", 0)
        targets_text += f"   TP{level}: ${price:.2f} ({partial_close}%) - RR {rr:.1f}\n"

    # Leverage
    leverage_info = scenario.get("leverage", {})
    lev_recommended = leverage_info.get("recommended", "5x")
    lev_max_safe = leverage_info.get("max_safe", "10x")

    # Why
    why = scenario.get("why", {})
    bullish_factors = why.get("bullish_factors", [])
    bearish_factors = why.get("bearish_factors", [])
    risks = why.get("risks", [])

    # Формируем карточку
    card = f"""
{bias_emoji} <b>{name}</b>
📊 Confidence: {confidence:.0f}%

💹 <b>Entry Zone:</b> ${entry_min:.2f} - ${entry_max:.2f}
   Avg: ${entry_avg:.2f} ({entry_type})

🛑 <b>Stop Loss:</b> ${sl_price:.2f}
   {sl_reason if sl_reason else ""}

🎯 <b>Targets:</b>
{targets_text}

📊 <b>Leverage:</b> {lev_recommended} (max safe: {lev_max_safe})
"""

    # Добавляем факторы если есть
    if bullish_factors:
        card += "\n🟢 <b>Bullish factors:</b>\n"
        for factor in bullish_factors[:2]:  # Первые 2
            card += f"   • {factor}\n"

    if bearish_factors:
        card += "\n🔴 <b>Bearish factors:</b>\n"
        for factor in bearish_factors[:2]:
            card += f"   • {factor}\n"

    if risks:
        card += "\n⚠️ <b>Risks:</b>\n"
        for risk in risks[:2]:
            card += f"   • {risk}\n"

    card += "\n💰 <b>Выбери риск для открытия:</b>"

    await message.edit_text(
        card,
        reply_markup=ai_scenarios_kb.get_scenario_detail_keyboard(scenario_index)
    )


@router.callback_query(AIScenarioStates.viewing_detail, F.data.startswith("ai:trade:"))
async def ai_trade_with_risk(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Пользователь выбрал риск - показать подтверждение"""
    # Парсинг: ai:trade:0:10
    parts = callback.data.split(":")
    scenario_index = int(parts[2])
    risk_usd = float(parts[3])

    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "BTCUSDT")  # Берем symbol из state!

    user_id = callback.from_user.id
    settings = await settings_storage.get_settings(user_id)

    # Используем дефолтное плечо из settings
    leverage = settings.default_leverage

    await state.update_data(risk_usd=risk_usd, leverage=leverage)
    await state.set_state(AIScenarioStates.confirmation)

    # Рассчитать позицию
    await show_trade_confirmation(callback.message, scenario, symbol, risk_usd, leverage, settings)

    await callback.answer()


async def show_trade_confirmation(message: Message, scenario: dict, symbol: str, risk_usd: float, leverage: int, settings):
    """Показать карточку подтверждения с расчётами"""

    # Получить параметры сценария
    bias = scenario.get("bias", "long")
    side = "Long" if bias == "long" else "Short"
    side_emoji = "🟢" if bias == "long" else "🔴"

    entry = scenario.get("entry", {})
    entry_min = entry.get("price_min", 0)
    entry_max = entry.get("price_max", 0)
    entry_price = (entry_min + entry_max) / 2

    stop_loss = scenario.get("stop_loss", {})
    stop_price = stop_loss.get("recommended", 0)

    targets = scenario.get("targets", [])

    # Простой расчёт для preview
    stop_distance = abs(entry_price - stop_price)
    qty_estimate = risk_usd / stop_distance if stop_distance > 0 else 0
    margin_estimate = (qty_estimate * entry_price) / leverage if leverage > 0 else 0

    coin = symbol.replace("USDT", "")

    # Формируем TP info для ВСЕХ уровней
    tp_info = ""
    if targets:
        for idx, target in enumerate(targets, 1):
            tp_price = target.get("price", 0)
            tp_rr = target.get("rr", 0)
            partial_pct = target.get("partial_close_pct", 100)
            tp_info += f"🎯 <b>TP{idx}:</b> ${tp_price:.2f} (RR {tp_rr:.1f}) - {partial_pct}%\n"
    else:
        tp_info = "🎯 <b>TP:</b> N/A\n"

    # Карточка подтверждения
    card = f"""
✅ <b>Подтверждение сделки</b>

{side_emoji} <b>{symbol}</b> {bias.upper()}

⚡ <b>Entry:</b> Market @ ${entry_price:.2f}
🛑 <b>Stop:</b> ${stop_price:.2f}
{tp_info}
💰 <b>Risk:</b> ${risk_usd}
📊 <b>Leverage:</b> {leverage}x
📦 <b>Qty:</b> ~{qty_estimate:.4f} {coin}
💵 <b>Margin:</b> ~${margin_estimate:.2f}

<i>⚠️ Проверь все параметры перед подтверждением!</i>
"""

    await message.edit_text(
        card,
        reply_markup=ai_scenarios_kb.get_confirm_trade_keyboard(0, risk_usd)  # scenario_index уже в state
    )


@router.callback_query(AIScenarioStates.confirmation, F.data.startswith("ai:confirm:"))
async def ai_execute_trade(callback: CallbackQuery, state: FSMContext, settings_storage, lock_manager, trade_logger, order_monitor):
    """Выполнить сделку на основе AI сценария"""
    user_id = callback.from_user.id

    # Race condition protection
    if not await lock_manager.acquire_lock(user_id):
        await callback.answer("⏳ Trade in progress, please wait...", show_alert=True)
        return

    try:
        # Получить данные
        data = await state.get_data()
        scenarios = data.get("scenarios", [])
        scenario_index = data.get("selected_scenario_index", 0)
        scenario = scenarios[scenario_index]
        risk_usd = data.get("risk_usd", 10)
        leverage = data.get("leverage", 5)

        settings = await settings_storage.get_settings(user_id)
        testnet_mode = settings.testnet_mode

        # Извлечь параметры сценария
        symbol = data.get("symbol", "BTCUSDT")
        bias = scenario.get("bias", "long")
        side = "Long" if bias == "long" else "Short"  # Для RiskCalculator
        order_side = "Buy" if bias == "long" else "Sell"  # Для Bybit API

        entry = scenario.get("entry", {})
        entry_min = entry.get("price_min", 0)
        entry_max = entry.get("price_max", 0)
        entry_price = (entry_min + entry_max) / 2

        stop_loss_obj = scenario.get("stop_loss", {})
        stop_price = stop_loss_obj.get("recommended", 0)

        # ===== ВЫПОЛНЕНИЕ ЧЕРЕЗ TRADE BOT (не через Syntra API!) =====
        await callback.message.edit_text("⏳ <b>Выполняю сделку...</b>")

        # Создать Bybit клиент
        bybit = BybitClient(testnet=testnet_mode)
        risk_calc = RiskCalculator(bybit)

        # Получить текущую цену
        ticker = await bybit.get_tickers(symbol)
        mark_price = float(ticker.get('markPrice', 0))
        index_price = float(ticker.get('indexPrice', 0))

        # Умная проверка: если markPrice отличается от indexPrice > 5%, используем indexPrice
        # (на testnet markPrice может быть битым)
        price_diff_pct = abs(mark_price - index_price) / index_price * 100 if index_price > 0 else 0
        if price_diff_pct > 5:
            current_price = index_price
            logger.warning(f"markPrice ({mark_price}) differs from indexPrice ({index_price}) by {price_diff_pct:.1f}%, using indexPrice")
        else:
            current_price = mark_price

        logger.info(f"Current price: ${current_price:.2f} (mark: {mark_price}, index: {index_price})")

        # ===== ОПРЕДЕЛЕНИЕ ТИПА ОРДЕРА И ENTRY PRICE =====
        # Логика:
        # - Цена в зоне → Market order по текущей цене
        # - Цена вне зоны → Limit order на границе зоны

        in_zone = entry_min <= current_price <= entry_max

        if in_zone:
            # Цена в зоне - используем Market order
            order_type = "Market"
            entry_price = current_price
            logger.info(f"Price ${current_price:.2f} in entry zone ${entry_min:.2f}-${entry_max:.2f} → Market order")
        else:
            # Цена вне зоны - используем Limit order на границе
            order_type = "Limit"
            if bias == "long":
                # Long: ждём снижения цены до верхней границы зоны
                entry_price = entry_max
                logger.info(f"Price ${current_price:.2f} above zone ${entry_min:.2f}-${entry_max:.2f} → Limit order at ${entry_price:.2f}")
            else:
                # Short: ждём роста цены до нижней границы зоны
                entry_price = entry_min
                logger.info(f"Price ${current_price:.2f} below zone ${entry_min:.2f}-${entry_max:.2f} → Limit order at ${entry_price:.2f}")

        # Рассчитать позицию
        position_calc = await risk_calc.calculate_position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            stop_price=stop_price,
            risk_usd=risk_usd,
            leverage=leverage
        )

        qty = position_calc['qty']
        margin_required = position_calc['margin_required']
        actual_risk_usd = position_calc['actual_risk_usd']

        # Определяем emoji и targets для сообщений
        side_emoji = "🟢" if bias == "long" else "🔴"
        targets = scenario.get("targets", [])

        # Валидация баланса
        is_valid, error_msg = await risk_calc.validate_balance(
            required_margin=margin_required,
            actual_risk_usd=position_calc['actual_risk_usd'],
            max_risk_per_trade=settings.max_risk_per_trade,
            max_margin_per_trade=settings.max_margin_per_trade
        )

        if not is_valid:
            await callback.message.edit_text(
                f"❌ <b>Недостаточно средств:</b>\n\n{error_msg}",
                reply_markup=None
            )
            await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
            return

        # Установить leverage
        await bybit.set_leverage(symbol, leverage)

        # Разместить ордер (Market или Limit)
        import uuid
        trade_id = str(uuid.uuid4())

        if order_type == "Market":
            # Market order - размещаем и ждём fill
            entry_order = await bybit.place_order(
                symbol=symbol,
                side=order_side,
                order_type="Market",
                qty=qty,
                client_order_id=f"{trade_id}_entry"[:36]
            )

            order_id = entry_order['orderId']

            # Ждём fill
            filled_order = await bybit.wait_until_filled(
                symbol=symbol,
                order_id=order_id,
                timeout=config.MARKET_ORDER_TIMEOUT
            )

            actual_entry_price = float(filled_order['avgPrice'])
            actual_qty = float(filled_order['qty'])
        else:
            # Limit order - размещаем БЕЗ ожидания fill
            # SL ставим на ордер, TP через ladder после fill
            tick_size = position_calc.get('instrument_info', {}).get('tickSize', '0.01')
            entry_price_str = round_price(entry_price, tick_size)
            stop_price_str = round_price(stop_price, tick_size)

            # TP НЕ ставим на ордер - используем ladder TP после fill
            # (Bybit TP на ордере закрывает всю позицию, нам нужны partial closes)

            entry_order = await bybit.place_order(
                symbol=symbol,
                side=order_side,
                order_type="Limit",
                qty=qty,
                price=entry_price_str,
                client_order_id=f"{trade_id}_entry"[:36],
                stop_loss=stop_price_str  # SL сразу на ордер!
            )

            order_id = entry_order['orderId']

            # Регистрируем ордер для мониторинга и автоматической установки ladder TP
            order_monitor.register_order({
                'order_id': order_id,
                'symbol': symbol,
                'side': side,
                'order_side': order_side,
                'qty': qty,
                'entry_price': entry_price,
                'stop_price': stop_price,
                'targets': targets,
                'leverage': leverage,
                'user_id': user_id,
                'sl_already_set': True,  # SL уже на ордере
                'testnet': testnet_mode  # Режим торговли
            })
            logger.info(f"Order {order_id} registered with OrderMonitor for auto ladder TP (SL on order)")

            # Для limit order не ждём fill - показываем success и выходим
            success_text = f"""
✅ <b>Лимитный ордер размещён!</b>

{side_emoji} <b>{symbol}</b> {bias.upper()}

📊 <b>Limit Entry:</b> ${entry_price:.2f}
💰 <b>Current Price:</b> ${current_price:.2f}
🛑 <b>Stop:</b> ${stop_price:.2f}
"""
            # Добавляем информацию о всех TP
            if targets:
                for idx, target in enumerate(targets, 1):
                    tp_price = target.get("price", 0)
                    partial_pct = target.get("partial_close_pct", 0)
                    success_text += f"🎯 <b>TP{idx}:</b> ${tp_price:.2f} ({partial_pct}%)\n"

            success_text += f"""
💰 <b>Risk:</b> ${actual_risk_usd:.2f}
📊 <b>Leverage:</b> {leverage}x
📦 <b>Qty:</b> {qty}

<i>⏳ Ордер будет исполнен когда цена достигнет ${entry_price:.2f}
📊 Order ID: {order_id}
🔔 Получишь уведомление когда ордер сработает</i>
"""
            await callback.message.edit_text(success_text, reply_markup=None)
            await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

            logger.info(f"AI Limit order placed: {symbol} {side} @ ${entry_price:.2f}, order_id: {order_id}")
            return

        # Код ниже выполняется только для Market orders
        actual_entry_price = float(filled_order['avgPrice'])
        actual_qty = float(filled_order['qty'])
        actual_risk = abs(actual_entry_price - stop_price) * actual_qty

        # Зарегистрировать вход в позицию в trade_logger
        try:
            # TP price для лога - первый таргет или None
            tp_price_for_log = None
            rr_planned = None
            if targets:
                tp_price_for_log = targets[0].get("price")
                # RR planned = avg of targets
                rrs = []
                for t in targets:
                    tp = t.get("price", 0)
                    if stop_price != actual_entry_price:
                        rr = abs(tp - actual_entry_price) / abs(actual_entry_price - stop_price)
                        rrs.append(rr)
                if rrs:
                    rr_planned = sum(rrs) / len(rrs)

            trade_record = TradeRecord(
                trade_id=trade_id,
                user_id=user_id,
                timestamp=datetime.utcnow().isoformat(),
                symbol=symbol,
                side=side,
                entry_price=actual_entry_price,
                exit_price=None,
                qty=actual_qty,
                leverage=leverage,
                margin_mode=settings.default_margin_mode,
                stop_price=stop_price,
                tp_price=tp_price_for_log,
                risk_usd=actual_risk,
                pnl_usd=None,
                pnl_percent=None,
                roe_percent=None,
                outcome=None,
                rr_planned=rr_planned,
                rr_actual=None,
                status="open",
                testnet=testnet_mode  # Режим торговли
            )
            await trade_logger.log_trade(trade_record)
            logger.info(f"Trade entry logged for {symbol} @ ${actual_entry_price:.2f}")
        except Exception as log_error:
            logger.error(f"Failed to log trade entry: {log_error}")

        # Установить Stop Loss
        await bybit.set_trading_stop(
            symbol=symbol,
            stop_loss=str(stop_price),
            sl_trigger_by="MarkPrice"
        )

        # ===== УСТАНОВИТЬ LADDER TAKE PROFIT =====
        tp_success = True
        if targets:
            try:
                # Получить instrument info для округления
                instrument_info = position_calc.get('instrument_info', {})
                tick_size = instrument_info.get('tickSize', '0.01')
                qty_step = instrument_info.get('qtyStep', '0.001')

                # Подготовить уровни TP
                tp_levels = []
                total_pct = 0

                for target in targets:
                    tp_price = target.get("price", 0)
                    partial_pct = target.get("partial_close_pct", 0)

                    # Рассчитать qty для этого уровня
                    tp_qty_raw = (actual_qty * partial_pct) / 100
                    tp_qty = round_qty(tp_qty_raw, qty_step, round_down=True)

                    # Округлить цену
                    tp_price_str = round_price(tp_price, tick_size)

                    tp_levels.append({
                        'price': tp_price_str,
                        'qty': tp_qty
                    })

                    total_pct += partial_pct

                # Валидация: сумма % должна быть ~100
                if abs(total_pct - 100) > 1:  # Допуск 1%
                    logger.warning(f"TP percentages sum to {total_pct}%, expected 100%")

                # Разместить ladder TP ордера
                await bybit.place_ladder_tp(
                    symbol=symbol,
                    position_side=order_side,
                    tp_levels=tp_levels,
                    client_order_id_prefix=trade_id
                )
                logger.info(f"Ladder TP set: {len(tp_levels)} levels")
            except Exception as tp_error:
                logger.error(f"Error setting ladder TP: {tp_error}", exc_info=True)
                tp_success = False

        # Success!
        actual_risk = abs(actual_entry_price - stop_price) * actual_qty

        # Формируем success message
        success_text = f"""
✅ <b>Сделка открыта!</b>

{side_emoji} <b>{symbol}</b> {bias.upper()}

⚡ <b>Entry:</b> ${actual_entry_price:.2f} (filled)
🛑 <b>Stop:</b> ${stop_price:.2f}
"""

        # Добавляем информацию о всех TP
        if targets:
            for idx, target in enumerate(targets, 1):
                tp_price = target.get("price", 0)
                partial_pct = target.get("partial_close_pct", 0)
                success_text += f"🎯 <b>TP{idx}:</b> ${tp_price:.2f} ({partial_pct}%)\n"
        else:
            success_text += "🎯 <b>TP:</b> N/A\n"

        success_text += f"""
💰 <b>Risk:</b> ${actual_risk:.2f}
📊 <b>Leverage:</b> {leverage}x
📦 <b>Qty:</b> {actual_qty}

"""
        # Статус установки SL/TP
        if targets:
            if tp_success:
                success_text += f"<i>✅ SL/TP установлены автоматически ({len(targets)} уровня TP) | AI сценарий</i>\n"
            else:
                success_text += "<i>⚠️ SL установлен, но ошибка при установке TP!</i>\n<i>Проверь позицию вручную!</i>\n"
        else:
            success_text += "<i>✅ SL установлен автоматически | AI сценарий</i>\n"

        await callback.message.edit_text(success_text, reply_markup=None)
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

        logger.info(f"AI scenario trade executed: {symbol} {side} @ ${actual_entry_price:.2f}")

    except Exception as e:
        logger.error(f"AI trade execution error: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ <b>Ошибка выполнения:</b>\n\n{str(e)}",
            reply_markup=None
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    finally:
        await lock_manager.release_lock(user_id)
        await state.clear()

    await callback.answer()


# ===== Навигация =====

@router.callback_query(F.data == "ai:back_to_list")
async def ai_back_to_list(callback: CallbackQuery, state: FSMContext):
    """Вернуться к списку сценариев (из деталей)"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    symbol = data.get("symbol", "BTCUSDT")
    timeframe = data.get("timeframe", "4h")

    if not scenarios:
        # Нет сценариев - вернуть к выбору символа
        await state.set_state(AIScenarioStates.choosing_symbol)
        await callback.message.edit_text(
            "🤖 <b>AI Trading Scenarios</b>\n\n"
            "📊 Выбери символ и таймфрейм для анализа:",
            reply_markup=ai_scenarios_kb.get_symbols_keyboard()
        )
    else:
        # Показать список сценариев
        await state.set_state(AIScenarioStates.viewing_scenarios)
        await show_scenarios_list(callback.message, scenarios, symbol, timeframe)

    await callback.answer()


@router.callback_query(F.data == "ai:change_symbol")
async def ai_change_symbol(callback: CallbackQuery, state: FSMContext):
    """Выбрать другой символ (из списка сценариев)"""
    await state.set_state(AIScenarioStates.choosing_symbol)

    await callback.message.edit_text(
        "🤖 <b>AI Trading Scenarios</b>\n\n"
        "📊 Выбери символ и таймфрейм для анализа:",
        reply_markup=ai_scenarios_kb.get_symbols_keyboard()
    )

    await callback.answer()


@router.callback_query(AIScenarioStates.viewing_scenarios, F.data == "ai:refresh")
async def ai_refresh_scenarios(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Обновить сценарии"""
    data = await state.get_data()
    symbol = data.get("symbol", "BTCUSDT")
    timeframe = data.get("timeframe", "4h")

    # Повторно запросить
    await ai_analyze_market(callback, state, settings_storage)
