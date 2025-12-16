"""
AI Scenarios Handler

Хендлер для работы с торговыми сценариями от Syntra AI.
Quick execution flow: выбор сценария → выбор риска → подтверждение → execute.

Включает:
- Confidence-based Risk Scaling (масштабирование риска от уверенности AI)
- Smart order routing (Market/Limit в зависимости от зоны)
- Ladder TP support
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


def calculate_confidence_adjusted_risk(
    base_risk: float,
    confidence: float,
    scaling_enabled: bool = True
) -> tuple[float, float]:
    """
    Масштабировать риск на основе confidence AI сценария.

    Логика:
    - Высокий confidence (0.9+) → увеличиваем риск до 130%
    - Средний confidence (0.6-0.8) → риск около базового
    - Низкий confidence (<0.6) → уменьшаем риск до 70%

    Args:
        base_risk: Базовый риск в USD
        confidence: Confidence от 0 до 1
        scaling_enabled: Включено ли масштабирование

    Returns:
        (adjusted_risk, multiplier)
    """
    if not scaling_enabled:
        return base_risk, 1.0

    # Проверка минимального confidence
    if confidence < config.MIN_CONFIDENCE_THRESHOLD:
        logger.warning(f"Confidence {confidence:.2f} below threshold {config.MIN_CONFIDENCE_THRESHOLD}")

    # Линейная интерполяция между MIN и MAX multiplier
    # confidence=0 → MIN_MULTIPLIER, confidence=1 → MAX_MULTIPLIER
    min_mult = config.MIN_CONFIDENCE_MULTIPLIER
    max_mult = config.MAX_CONFIDENCE_MULTIPLIER

    multiplier = min_mult + (confidence * (max_mult - min_mult))

    # Ограничиваем в пределах [MIN, MAX]
    multiplier = max(min_mult, min(max_mult, multiplier))

    adjusted_risk = base_risk * multiplier

    # Не превышаем max_risk_per_trade
    adjusted_risk = min(adjusted_risk, config.MAX_RISK_PER_TRADE)

    logger.info(
        f"Risk scaling: base=${base_risk:.2f}, confidence={confidence:.2f}, "
        f"multiplier={multiplier:.2f}, adjusted=${adjusted_risk:.2f}"
    )

    return adjusted_risk, multiplier


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


@router.callback_query(AIScenarioStates.viewing_detail, F.data.startswith("ai:custom_risk:"))
async def ai_custom_risk_start(callback: CallbackQuery, state: FSMContext):
    """Начать ввод custom риска"""
    scenario_index = int(callback.data.split(":")[2])

    await state.update_data(selected_scenario_index=scenario_index)
    await state.set_state(AIScenarioStates.entering_custom_risk)

    await callback.message.edit_text(
        "💰 <b>Custom Risk</b>\n\n"
        "Введи сумму риска в USD (от 1 до 500):\n\n"
        "Например: <code>15</code> или <code>75.5</code>",
        reply_markup=ai_scenarios_kb.get_custom_risk_cancel_keyboard(scenario_index)
    )

    await callback.answer()


@router.message(AIScenarioStates.entering_custom_risk)
async def ai_custom_risk_process(message: Message, state: FSMContext, settings_storage):
    """Обработать введённый пользователем custom риск"""
    user_id = message.from_user.id

    try:
        # Парсим риск
        risk_text = message.text.strip().replace(",", ".").replace("$", "")
        custom_risk = float(risk_text)

        # Валидация
        if custom_risk <= 0:
            await message.answer("⚠️ Риск должен быть положительным числом!")
            return

        if custom_risk < 1:
            await message.answer("⚠️ Минимальный риск: $1")
            return

        if custom_risk > 500:
            await message.answer("⚠️ Максимальный риск: $500")
            return

        # Получаем данные
        data = await state.get_data()
        scenarios = data.get("scenarios", [])
        scenario_index = data.get("selected_scenario_index", 0)
        scenario = scenarios[scenario_index]
        symbol = data.get("symbol", "BTCUSDT")

        settings = await settings_storage.get_settings(user_id)
        leverage = settings.default_leverage

        # === CONFIDENCE-BASED RISK SCALING ===
        confidence = scenario.get("confidence", 0.5)

        adjusted_risk, multiplier = calculate_confidence_adjusted_risk(
            base_risk=custom_risk,
            confidence=confidence,
            scaling_enabled=settings.confidence_risk_scaling
        )

        # Сохраняем в state
        await state.update_data(
            base_risk_usd=custom_risk,
            risk_usd=adjusted_risk,
            risk_multiplier=multiplier,
            leverage=leverage
        )
        await state.set_state(AIScenarioStates.confirmation)

        # Удаляем сообщение с вводом
        try:
            await message.delete()
        except Exception:
            pass

        # Показываем подтверждение
        await show_trade_confirmation_message(
            message,
            scenario,
            symbol,
            adjusted_risk,
            leverage,
            base_risk=custom_risk,
            multiplier=multiplier,
            scaling_enabled=settings.confidence_risk_scaling
        )

        logger.info(f"User {user_id} set custom risk ${custom_risk:.2f} → ${adjusted_risk:.2f}")

    except ValueError:
        await message.answer(
            "⚠️ Неверный формат!\n\n"
            "Введи число, например: <code>25</code> или <code>15.5</code>"
        )


@router.callback_query(AIScenarioStates.entering_custom_risk, F.data.startswith("ai:cancel_custom:"))
async def ai_custom_risk_cancel(callback: CallbackQuery, state: FSMContext):
    """Отменить ввод custom риска и вернуться к деталям сценария"""
    scenario_index = int(callback.data.split(":")[2])

    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario = scenarios[scenario_index]

    await state.set_state(AIScenarioStates.viewing_detail)

    # Показываем детали сценария
    await show_scenario_detail(callback.message, scenario, scenario_index)

    await callback.answer("Отменено")


@router.callback_query(AIScenarioStates.viewing_detail, F.data.startswith("ai:trade:"))
async def ai_trade_with_risk(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Пользователь выбрал риск - показать подтверждение с confidence scaling"""
    # Парсинг: ai:trade:0:10
    parts = callback.data.split(":")
    scenario_index = int(parts[2])
    base_risk_usd = float(parts[3])

    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "BTCUSDT")  # Берем symbol из state!

    user_id = callback.from_user.id
    settings = await settings_storage.get_settings(user_id)

    # Используем дефолтное плечо из settings
    leverage = settings.default_leverage

    # === CONFIDENCE-BASED RISK SCALING ===
    confidence = scenario.get("confidence", 0.5)

    # Применяем масштабирование если включено
    adjusted_risk, multiplier = calculate_confidence_adjusted_risk(
        base_risk=base_risk_usd,
        confidence=confidence,
        scaling_enabled=settings.confidence_risk_scaling
    )

    # Сохраняем оба значения в state
    await state.update_data(
        base_risk_usd=base_risk_usd,
        risk_usd=adjusted_risk,
        risk_multiplier=multiplier,
        leverage=leverage
    )
    await state.set_state(AIScenarioStates.confirmation)

    # Показать подтверждение с информацией о масштабировании
    await show_trade_confirmation(
        callback.message,
        scenario,
        symbol,
        adjusted_risk,
        leverage,
        base_risk=base_risk_usd,
        multiplier=multiplier,
        scaling_enabled=settings.confidence_risk_scaling
    )

    await callback.answer()


async def show_trade_confirmation(
    message: Message,
    scenario: dict,
    symbol: str,
    risk_usd: float,
    leverage: int,
    base_risk: float = None,
    multiplier: float = 1.0,
    scaling_enabled: bool = False
):
    """Показать карточку подтверждения с расчётами и информацией о масштабировании"""

    # Получить параметры сценария
    bias = scenario.get("bias", "long")
    confidence = scenario.get("confidence", 0.5)
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

    # Формируем информацию о риске с масштабированием
    if scaling_enabled and base_risk and multiplier != 1.0:
        # Показываем масштабирование
        multiplier_pct = (multiplier - 1) * 100
        sign = "+" if multiplier_pct >= 0 else ""
        risk_info = (
            f"💰 <b>Risk:</b> ${risk_usd:.2f}\n"
            f"   <i>(${base_risk:.0f} × {multiplier:.2f} = ${risk_usd:.2f}, "
            f"conf {confidence*100:.0f}% → {sign}{multiplier_pct:.0f}%)</i>"
        )
    else:
        risk_info = f"💰 <b>Risk:</b> ${risk_usd:.2f}"

    # Карточка подтверждения
    card = f"""
✅ <b>Подтверждение сделки</b>

{side_emoji} <b>{symbol}</b> {bias.upper()}
📊 <b>Confidence:</b> {confidence*100:.0f}%

⚡ <b>Entry:</b> Market @ ${entry_price:.2f}
🛑 <b>Stop:</b> ${stop_price:.2f}
{tp_info}
{risk_info}
📊 <b>Leverage:</b> {leverage}x
📦 <b>Qty:</b> ~{qty_estimate:.4f} {coin}
💵 <b>Margin:</b> ~${margin_estimate:.2f}

<i>⚠️ Проверь все параметры перед подтверждением!</i>
"""

    await message.edit_text(
        card,
        reply_markup=ai_scenarios_kb.get_confirm_trade_keyboard(0, risk_usd)  # scenario_index уже в state
    )


async def show_trade_confirmation_message(
    message: Message,
    scenario: dict,
    symbol: str,
    risk_usd: float,
    leverage: int,
    base_risk: float = None,
    multiplier: float = 1.0,
    scaling_enabled: bool = False
):
    """
    Отправить новое сообщение с подтверждением (для случая когда edit невозможен).
    Используется после ввода нового SL.
    """
    # Получить параметры сценария
    bias = scenario.get("bias", "long")
    confidence = scenario.get("confidence", 0.5)
    side_emoji = "🟢" if bias == "long" else "🔴"

    entry = scenario.get("entry", {})
    entry_min = entry.get("price_min", 0)
    entry_max = entry.get("price_max", 0)
    entry_price = (entry_min + entry_max) / 2

    stop_loss = scenario.get("stop_loss", {})
    stop_price = stop_loss.get("recommended", 0)
    is_overridden = stop_loss.get("overridden", False)

    targets = scenario.get("targets", [])

    # Простой расчёт для preview
    stop_distance = abs(entry_price - stop_price)
    qty_estimate = risk_usd / stop_distance if stop_distance > 0 else 0
    margin_estimate = (qty_estimate * entry_price) / leverage if leverage > 0 else 0

    coin = symbol.replace("USDT", "")

    # Формируем TP info
    tp_info = ""
    if targets:
        for idx, target in enumerate(targets, 1):
            tp_price = target.get("price", 0)
            tp_rr = target.get("rr", 0)
            partial_pct = target.get("partial_close_pct", 100)
            tp_info += f"🎯 <b>TP{idx}:</b> ${tp_price:.2f} (RR {tp_rr:.1f}) - {partial_pct}%\n"
    else:
        tp_info = "🎯 <b>TP:</b> N/A\n"

    # Формируем информацию о риске
    if scaling_enabled and base_risk and multiplier != 1.0:
        multiplier_pct = (multiplier - 1) * 100
        sign = "+" if multiplier_pct >= 0 else ""
        risk_info = (
            f"💰 <b>Risk:</b> ${risk_usd:.2f}\n"
            f"   <i>(${base_risk:.0f} × {multiplier:.2f}, conf {confidence*100:.0f}% → {sign}{multiplier_pct:.0f}%)</i>"
        )
    else:
        risk_info = f"💰 <b>Risk:</b> ${risk_usd:.2f}"

    # Индикатор override SL
    sl_indicator = " ✏️<i>(overridden)</i>" if is_overridden else ""

    card = f"""
✅ <b>Подтверждение сделки</b>

{side_emoji} <b>{symbol}</b> {bias.upper()}
📊 <b>Confidence:</b> {confidence*100:.0f}%

⚡ <b>Entry:</b> Market @ ${entry_price:.2f}
🛑 <b>Stop:</b> ${stop_price:.2f}{sl_indicator}
{tp_info}
{risk_info}
📊 <b>Leverage:</b> {leverage}x
📦 <b>Qty:</b> ~{qty_estimate:.4f} {coin}
💵 <b>Margin:</b> ~${margin_estimate:.2f}

<i>⚠️ Проверь все параметры перед подтверждением!</i>
"""

    await message.answer(
        card,
        reply_markup=ai_scenarios_kb.get_confirm_trade_keyboard(0, risk_usd)
    )


async def check_positions_limit(bybit: BybitClient, max_positions: int) -> tuple[bool, int]:
    """
    Проверить лимит активных позиций.

    Returns:
        (can_open, current_count) - можно ли открыть новую позицию и текущее количество
    """
    try:
        positions = await bybit.get_positions()
        current_count = len(positions)
        can_open = current_count < max_positions
        return can_open, current_count
    except Exception as e:
        logger.error(f"Error checking positions limit: {e}")
        # При ошибке разрешаем (fail open)
        return True, 0


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

        # === ПРОВЕРКА ЛИМИТА ПОЗИЦИЙ ===
        bybit = BybitClient(testnet=testnet_mode)

        can_open, current_count = await check_positions_limit(
            bybit,
            settings.max_active_positions
        )

        if not can_open:
            await lock_manager.release_lock(user_id)
            await callback.message.edit_text(
                f"⚠️ <b>Достигнут лимит активных позиций!</b>\n\n"
                f"Текущие позиции: {current_count}\n"
                f"Лимит: {settings.max_active_positions}\n\n"
                f"<i>Закрой существующие позиции перед открытием новых.</i>",
                reply_markup=None
            )
            await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
            await state.clear()
            return

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

        # Используем уже созданный bybit клиент
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
            from services.trade_logger import calculate_fee, calculate_margin

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

            # Рассчитываем margin и fee
            margin_usd = calculate_margin(actual_entry_price, actual_qty, leverage)
            entry_fee = calculate_fee(actual_entry_price, actual_qty, is_taker=True)  # Market = taker

            # Преобразуем side в Long/Short
            position_side = "Long" if side == "Buy" else "Short"

            # Генерируем scenario_id для связки с AI
            scenario_uuid = str(uuid.uuid4())

            trade_record = TradeRecord(
                trade_id=trade_id,
                user_id=user_id,
                symbol=symbol,
                side=position_side,
                opened_at=datetime.utcnow().isoformat(),
                entry_price=actual_entry_price,
                qty=actual_qty,
                leverage=leverage,
                margin_mode=settings.default_margin_mode,
                margin_usd=margin_usd,
                stop_price=stop_price,
                risk_usd=actual_risk,
                tp_price=tp_price_for_log,
                rr_planned=rr_planned,
                entry_fee_usd=entry_fee,
                total_fees_usd=entry_fee,
                status="open",
                testnet=testnet_mode,
                # AI Scenario fields
                scenario_id=scenario_uuid,
                scenario_source="syntra",
                scenario_bias=scenario.get("bias"),
                scenario_confidence=scenario.get("confidence"),
                timeframe=data.get("timeframe"),
                entry_reason=scenario.get("name"),
                scenario_snapshot=scenario  # Сохраняем весь сценарий
            )
            await trade_logger.log_trade(trade_record)
            logger.info(f"Trade entry logged for {symbol} @ ${actual_entry_price:.2f} (scenario: {scenario_uuid})")
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


# ===== Override SL =====

@router.callback_query(AIScenarioStates.confirmation, F.data.startswith("ai:edit_sl:"))
async def ai_edit_sl_start(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование SL"""
    data = await state.get_data()
    scenario_index = int(callback.data.split(":")[2])
    scenarios = data.get("scenarios", [])
    scenario = scenarios[scenario_index]

    # Получаем текущий SL из сценария
    stop_loss = scenario.get("stop_loss", {})
    current_sl = stop_loss.get("recommended", 0)
    bias = scenario.get("bias", "long")

    await state.set_state(AIScenarioStates.editing_sl)
    await state.update_data(original_sl=current_sl)

    sl_direction = "ниже entry" if bias == "long" else "выше entry"

    await callback.message.edit_text(
        f"✏️ <b>Override Stop Loss</b>\n\n"
        f"Текущий SL от AI: ${current_sl:.2f}\n"
        f"Направление: {bias.upper()}\n\n"
        f"<i>Для {bias.upper()} позиции SL должен быть {sl_direction}</i>\n\n"
        f"Введи новую цену Stop Loss (только число):\n"
        f"Например: <code>{current_sl * 0.98:.2f}</code>",
        reply_markup=ai_scenarios_kb.get_edit_sl_cancel_keyboard(scenario_index)
    )

    await callback.answer()


@router.message(AIScenarioStates.editing_sl)
async def ai_edit_sl_process(message: Message, state: FSMContext, settings_storage):
    """Обработать введённый пользователем SL"""
    user_id = message.from_user.id

    try:
        # Парсим цену
        new_sl_text = message.text.strip().replace(",", ".").replace("$", "")
        new_sl = float(new_sl_text)

        if new_sl <= 0:
            raise ValueError("SL must be positive")

        # Получаем данные
        data = await state.get_data()
        scenarios = data.get("scenarios", [])
        scenario_index = data.get("selected_scenario_index", 0)
        scenario = scenarios[scenario_index]

        # Валидация: SL должен быть в правильном направлении
        entry = scenario.get("entry", {})
        entry_min = entry.get("price_min", 0)
        entry_max = entry.get("price_max", 0)
        entry_price = (entry_min + entry_max) / 2
        bias = scenario.get("bias", "long")

        if bias == "long" and new_sl >= entry_price:
            await message.answer(
                f"⚠️ <b>Неверный SL для LONG!</b>\n\n"
                f"SL (${new_sl:.2f}) должен быть ниже entry (${entry_price:.2f})\n\n"
                f"Введи корректную цену:"
            )
            return

        if bias == "short" and new_sl <= entry_price:
            await message.answer(
                f"⚠️ <b>Неверный SL для SHORT!</b>\n\n"
                f"SL (${new_sl:.2f}) должен быть выше entry (${entry_price:.2f})\n\n"
                f"Введи корректную цену:"
            )
            return

        # Обновляем SL в сценарии
        scenario["stop_loss"]["recommended"] = new_sl
        scenario["stop_loss"]["overridden"] = True

        # Пересчитываем риск и показываем подтверждение
        settings = await settings_storage.get_settings(user_id)
        risk_usd = data.get("risk_usd", 10)
        leverage = data.get("leverage", 5)
        base_risk = data.get("base_risk_usd", risk_usd)
        multiplier = data.get("risk_multiplier", 1.0)

        await state.update_data(
            scenarios=scenarios,
            custom_sl=new_sl
        )
        await state.set_state(AIScenarioStates.confirmation)

        # Показываем обновлённое подтверждение
        symbol = data.get("symbol", "BTCUSDT")
        try:
            await message.delete()
        except Exception:
            pass

        # Отправляем новую карточку подтверждения
        await show_trade_confirmation_message(
            message,
            scenario,
            symbol,
            risk_usd,
            leverage,
            base_risk=base_risk,
            multiplier=multiplier,
            scaling_enabled=settings.confidence_risk_scaling
        )

        logger.info(f"User {user_id} overridden SL to ${new_sl:.2f}")

    except ValueError:
        await message.answer(
            "⚠️ Неверный формат цены!\n\n"
            "Введи число, например: <code>95000.50</code>"
        )


@router.callback_query(AIScenarioStates.editing_sl, F.data.startswith("ai:cancel_edit:"))
async def ai_edit_sl_cancel(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Отменить редактирование SL и вернуться к подтверждению"""
    data = await state.get_data()
    scenario_index = int(callback.data.split(":")[2])
    scenarios = data.get("scenarios", [])
    scenario = scenarios[scenario_index]

    user_id = callback.from_user.id
    settings = await settings_storage.get_settings(user_id)

    risk_usd = data.get("risk_usd", 10)
    leverage = data.get("leverage", 5)
    base_risk = data.get("base_risk_usd", risk_usd)
    multiplier = data.get("risk_multiplier", 1.0)
    symbol = data.get("symbol", "BTCUSDT")

    await state.set_state(AIScenarioStates.confirmation)

    await show_trade_confirmation(
        callback.message,
        scenario,
        symbol,
        risk_usd,
        leverage,
        base_risk=base_risk,
        multiplier=multiplier,
        scaling_enabled=settings.confidence_risk_scaling
    )

    await callback.answer("Редактирование отменено")


@router.callback_query(AIScenarioStates.viewing_scenarios, F.data == "ai:refresh")
async def ai_refresh_scenarios(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Обновить сценарии"""
    data = await state.get_data()
    symbol = data.get("symbol", "BTCUSDT")
    timeframe = data.get("timeframe", "4h")

    # Повторно запросить
    await ai_analyze_market(callback, state, settings_storage)
