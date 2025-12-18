"""
AI Scenarios Router

Хендлеры для работы с торговыми сценариями от Syntra AI.
Вынесено из ai_scenarios.py для модульности.
"""
import html
import math
import uuid

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from loguru import logger
from typing import Optional

import config
from bot.states.trade_states import AIScenarioStates
from bot.keyboards import ai_scenarios_kb
from bot.keyboards.main_menu import get_main_menu
from datetime import datetime
from services.syntra_client import (
    get_syntra_client,
    SyntraAPIError,
    SyntraAnalysisResponse,
    NoTradeSignal,
    MarketContext
)
from services.bybit import BybitClient
from services.risk_calculator import RiskCalculator
from services.trade_logger import TradeRecord
from services.entry_plan import EntryPlan, EntryOrder
from services.scenarios_cache import get_scenarios_cache
from services.charts import get_chart_generator
from services.risk_percent import (
    get_equity_cached,
    calc_risk_usd_from_pct,
    validate_risk_pct,
    validate_risk_usd,
    MIN_RISK_PCT,
    MAX_RISK_PCT,
)
from services.real_ev import get_gate_checker, GateStatus
from services.trading_modes import get_mode_registry, MEME_SYMBOLS
from services.trading_modes.safety_checker import get_safety_checker, SafetyCheckResult
from services.supervisor_client import SupervisorClient
from services.universe import get_universe_service, MAJOR_SYMBOLS
from utils.validators import round_qty, round_price

# Импорт утилит
from bot.handlers.ai_scenarios.utils import (
    parse_leverage as _parse_leverage,
    calculate_confidence_adjusted_risk,
    parse_entry_plan
)

router = Router()


async def _get_symbols_keyboard(
    user_id: int,
    current_mode: str,
    current_category: str = "trending",
):
    """
    Хелпер для получения клавиатуры символов.

    Пытается использовать динамическую клавиатуру с Universe,
    fallback на статическую если Universe недоступен.
    """
    # Получить закэшированные пары
    cache = get_scenarios_cache()
    cached_pairs_raw = cache.get_user_cached_pairs(user_id)
    cached_pairs = []
    for symbol, timeframe, cached_at in cached_pairs_raw:
        age_mins = int((datetime.utcnow() - cached_at).total_seconds() / 60)
        cached_pairs.append((symbol, timeframe, age_mins))
    cached_pairs.sort(key=lambda x: x[2])

    # Попробовать получить динамические символы
    try:
        # Создаём bybit client для Universe
        bybit_client = BybitClient(testnet=config.DEFAULT_TESTNET_MODE)
        universe_service = get_universe_service(bybit_client)
        dynamic_symbols = await universe_service.get_symbols_with_metrics(
            mode=current_mode,
            category=current_category,
            limit=5
        )

        if dynamic_symbols:
            # Используем динамическую клавиатуру
            return ai_scenarios_kb.get_dynamic_symbols_keyboard(
                dynamic_symbols=dynamic_symbols,
                current_mode=current_mode,
                current_category=current_category,
                cached_pairs=cached_pairs,
            )
    except Exception as e:
        logger.warning(f"Failed to get dynamic symbols, using fallback: {e}")

    # Fallback на статическую клавиатуру
    meme_symbols = MEME_SYMBOLS if current_mode == "meme" else None
    return ai_scenarios_kb.get_symbols_keyboard(
        cached_pairs,
        current_mode=current_mode,
        meme_symbols=meme_symbols
    )


@router.message(Command("ai_scenarios"))
@router.message(F.text == "🤖 AI Сценарии")
async def ai_scenarios_start(message: Message, state: FSMContext, settings_storage):
    """Начало AI Scenarios flow - выбор символа"""

    # Проверка включены ли AI сценарии
    if not config.AI_SCENARIOS_ENABLED:
        await message.answer(
            "❌ AI Scenarios отключены.\n\n"
            "Включите в .env: AI_SCENARIOS_ENABLED=true"
        )
        return

    user_id = message.from_user.id

    # Получить текущий trading mode из settings
    settings = await settings_storage.get_settings(user_id)
    current_mode = settings.default_trading_mode
    current_category = "trending"

    # Сохраняем mode и category в state
    await state.update_data(trading_mode=current_mode, category=current_category)
    await state.set_state(AIScenarioStates.choosing_symbol)

    # Получаем mode info для header
    registry = get_mode_registry()
    mode = registry.get_or_default(current_mode)

    # Формируем текст
    text = (
        f"🤖 <b>AI Trading Scenarios</b>\n"
        f"{mode.emoji} Mode: <b>{mode.name}</b>\n\n"
        "Syntra AI проанализирует рынок и предложит торговые сценарии "
        "с конкретными уровнями входа, стопа и целей.\n\n"
        "📊 Выбери символ и таймфрейм для анализа:"
    )

    # Получить клавиатуру (динамическую или статическую)
    keyboard = await _get_symbols_keyboard(user_id, current_mode, current_category)

    await message.answer(text, reply_markup=keyboard)


@router.callback_query(AIScenarioStates.choosing_symbol, F.data == "ai:mode:toggle")
async def ai_mode_toggle(callback: CallbackQuery, state: FSMContext):
    """Показать меню выбора trading mode"""
    data = await state.get_data()
    current_mode = data.get("trading_mode", "standard")

    registry = get_mode_registry()
    mode = registry.get_or_default(current_mode)

    text = (
        f"⚙️ <b>Выбор Trading Mode</b>\n\n"
        f"Текущий: {mode.emoji} <b>{mode.name}</b>\n\n"
        f"🛡️ <b>Conservative</b> - низкий риск, строгие условия\n"
        f"⚖️ <b>Standard</b> - сбалансированный режим\n"
        f"🔥 <b>High Risk</b> - высокое плечо, тесные стопы\n"
        f"🚀 <b>Meme</b> - для волатильных мемкоинов\n"
    )

    await callback.message.edit_text(
        text,
        reply_markup=ai_scenarios_kb.get_mode_toggle_keyboard(current_mode)
    )
    await callback.answer()


@router.callback_query(AIScenarioStates.choosing_symbol, F.data.startswith("ai:mode:"))
async def ai_mode_selected(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Выбор нового trading mode"""
    mode_id = callback.data.split(":")[2]

    # Проверка на back
    if mode_id == "back":
        # Возврат к выбору символа
        user_id = callback.from_user.id
        data = await state.get_data()
        current_mode = data.get("trading_mode", "standard")
        current_category = data.get("category", "trending")

        registry = get_mode_registry()
        mode = registry.get_or_default(current_mode)

        text = (
            f"🤖 <b>AI Trading Scenarios</b>\n"
            f"{mode.emoji} Mode: <b>{mode.name}</b>\n\n"
            "📊 Выбери символ и таймфрейм для анализа:"
        )

        keyboard = await _get_symbols_keyboard(user_id, current_mode, current_category)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()
        return

    # Валидация mode_id
    registry = get_mode_registry()
    if not registry.is_valid_mode(mode_id):
        await callback.answer("❌ Неизвестный режим", show_alert=True)
        return

    user_id = callback.from_user.id

    # Сохраняем в user_settings (persistent)
    await settings_storage.update_setting(user_id, "default_trading_mode", mode_id)

    # Сохраняем в state (session)
    await state.update_data(trading_mode=mode_id)

    mode = registry.get(mode_id)

    # Показать предупреждение для high_risk/meme
    warning = ""
    if mode_id == "high_risk":
        warning = (
            "\n\n⚠️ <b>HIGH RISK MODE:</b>\n"
            "• Leverage до 50x\n"
            "• Тесные стопы (0.8-1.5x ATR)\n"
            "• Быстрая реакция на инвалидацию\n"
            "<i>Подходит для опытных трейдеров!</i>"
        )
    elif mode_id == "meme":
        warning = (
            "\n\n⚠️ <b>MEME MODE:</b>\n"
            "• Только whitelist символов (DOGE, SHIB, PEPE...)\n"
            "• Широкие стопы (2-5x ATR)\n"
            "• Уменьшенный размер позиции\n"
            "<i>Высокая волатильность!</i>"
        )

    await callback.answer(f"✅ Mode: {mode.name}")

    # Возврат к выбору символа с новым mode
    cache = get_scenarios_cache()
    cached_pairs_raw = cache.get_user_cached_pairs(user_id)
    cached_pairs = []
    for symbol, timeframe, cached_at in cached_pairs_raw:
        age_mins = int((datetime.utcnow() - cached_at).total_seconds() / 60)
        cached_pairs.append((symbol, timeframe, age_mins))
    cached_pairs.sort(key=lambda x: x[2])

    text = (
        f"🤖 <b>AI Trading Scenarios</b>\n"
        f"{mode.emoji} Mode: <b>{mode.name}</b>{warning}\n\n"
        "📊 Выбери символ и таймфрейм для анализа:"
    )

    # Получить клавиатуру
    data = await state.get_data()
    current_category = data.get("category", "trending")
    keyboard = await _get_symbols_keyboard(user_id, mode_id, current_category)

    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(AIScenarioStates.choosing_symbol, F.data.startswith("ai:cat:"))
async def ai_category_selected(callback: CallbackQuery, state: FSMContext):
    """Открыть экран с топ-20 символами категории"""
    parts = callback.data.split(":")
    # ai:cat:pumping:standard
    category = parts[2]
    mode_id = parts[3] if len(parts) > 3 else "standard"

    # Сохраняем категорию в state
    await state.update_data(category=category, trading_mode=mode_id)

    # Получаем mode info
    registry = get_mode_registry()
    mode = registry.get_or_default(mode_id)

    # Формируем текст с категорией
    category_labels = {
        "trending": "🌊 Trending (топ по комбо-скору)",
        "popular": "📊 Popular (топ по объёму)",
        "pumping": "🔥 Pumping (топ растущих)",
        "dumping": "🧊 Dumping (топ падающих)",
        "volatile": "⚡ Volatile (топ волатильных)",
    }
    category_label = category_labels.get(category, "🌊 Trending")

    # Получаем символы из UniverseService
    try:
        bybit_client = BybitClient(testnet=config.DEFAULT_TESTNET_MODE)
        universe_service = get_universe_service(bybit_client)
        symbols = await universe_service.get_symbols_with_metrics(
            mode=mode_id,
            category=category,
            limit=20
        )
    except Exception as e:
        logger.warning(f"Universe service error: {e}")
        symbols = []

    if not symbols:
        await callback.answer("❌ Нет данных для этой категории", show_alert=True)
        return

    # Формируем текст с данными о символах
    lines = [
        f"🤖 <b>AI Trading Scenarios</b>",
        f"{mode.emoji} Mode: <b>{mode.name}</b>\n",
        f"<b>{category_label}</b>\n",
    ]

    for i, m in enumerate(symbols[:20], 1):
        coin = m.symbol.replace("USDT", "")
        vol_m = m.turnover_24h / 1_000_000

        # Формат зависит от категории
        if category == "pumping":
            chg = f"+{m.price_change_pct:.1f}%" if m.price_change_pct > 0 else f"{m.price_change_pct:.1f}%"
            lines.append(f"{i}. <b>{coin}</b> {chg} (${vol_m:.0f}M)")
        elif category == "dumping":
            lines.append(f"{i}. <b>{coin}</b> {m.price_change_pct:.1f}% (${vol_m:.0f}M)")
        elif category == "volatile":
            lines.append(f"{i}. <b>{coin}</b> ±{m.range_pct:.1f}% (${vol_m:.0f}M)")
        elif category == "popular":
            chg = f"+{m.price_change_pct:.1f}%" if m.price_change_pct > 0 else f"{m.price_change_pct:.1f}%"
            lines.append(f"{i}. <b>{coin}</b> ${vol_m:.0f}M ({chg})")
        else:
            # trending
            chg = f"+{m.price_change_pct:.1f}%" if m.price_change_pct > 0 else f"{m.price_change_pct:.1f}%"
            lines.append(f"{i}. <b>{coin}</b> {chg} (${vol_m:.0f}M)")

    lines.append("\n📊 Выбери символ для анализа:")
    text = "\n".join(lines)

    keyboard = ai_scenarios_kb.get_category_symbols_keyboard(symbols, category, mode_id)

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(AIScenarioStates.choosing_symbol, F.data == "ai:symbols")
async def ai_back_to_symbols(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Вернуться на главный экран выбора символа"""
    user_id = callback.from_user.id

    # Получить текущий mode из state или settings
    data = await state.get_data()
    current_mode = data.get("trading_mode")
    if not current_mode:
        settings = await settings_storage.get_settings(user_id)
        current_mode = settings.default_trading_mode

    registry = get_mode_registry()
    mode = registry.get_or_default(current_mode)

    text = (
        f"🤖 <b>AI Trading Scenarios</b>\n"
        f"{mode.emoji} Mode: <b>{mode.name}</b>\n\n"
        "📊 Выбери символ и таймфрейм для анализа:"
    )

    keyboard = await _get_symbols_keyboard(user_id, current_mode, "trending")

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "ai:noop")
async def ai_noop(callback: CallbackQuery):
    """Пустой хэндлер для некликабельных кнопок-меток"""
    await callback.answer()


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
async def ai_analyze_market(
    callback: CallbackQuery,
    state: FSMContext,
    settings_storage,
    force_refresh: bool = False,
    symbol: str = None,
    timeframe: str = None
):
    """Запросить сценарии от Syntra AI (с кэшированием)"""
    # Парсинг callback: ai:analyze:BTCUSDT:4h (если symbol/timeframe не переданы явно)
    if symbol is None or timeframe is None:
        parts = callback.data.split(":")
        symbol = parts[2]
        timeframe = parts[3]

    user_id = callback.from_user.id
    settings = await settings_storage.get_settings(user_id)
    cache = get_scenarios_cache()

    await state.update_data(symbol=symbol, timeframe=timeframe)
    await state.set_state(AIScenarioStates.viewing_scenarios)

    # КРИТИЧНО: Ответить на callback СРАЗУ, ДО долгого запроса!
    await callback.answer()

    # === ПРОВЕРКА КЭША ===
    if not force_refresh:
        cached = cache.get(user_id, symbol, timeframe)
        if cached and cached.scenarios:
            logger.info(f"Using cached scenarios for {symbol}:{timeframe}")

            # Сохранить в state из кэша
            await state.update_data(
                scenarios=cached.scenarios,
                analysis_id=cached.analysis_id,
                current_price=cached.current_price,
                market_context=cached.market_context,
                no_trade=cached.no_trade,
                key_levels=cached.key_levels,
            )

            # Конвертируем market_context dict обратно в объект для show_scenarios_list
            mc = cached.market_context
            market_context_obj = MarketContext(
                trend=mc.get("trend", "neutral"),
                phase=mc.get("phase", ""),
                sentiment=mc.get("sentiment", "neutral"),
                volatility=mc.get("volatility", "medium"),
                bias=mc.get("bias", "neutral"),
                strength=mc.get("strength", 0),
                rsi=mc.get("rsi"),
                funding_rate_pct=mc.get("funding_rate_pct"),
            )

            # Конвертируем no_trade
            no_trade_obj = None
            if cached.no_trade and cached.no_trade.get("should_not_trade"):
                no_trade_obj = NoTradeSignal(
                    should_not_trade=cached.no_trade.get("should_not_trade", False),
                    confidence=cached.no_trade.get("confidence", 0),
                    category=cached.no_trade.get("category", ""),
                    reasons=cached.no_trade.get("reasons", []),
                    wait_for=cached.no_trade.get("wait_for"),
                )

            # Показать время кэша
            age_mins = int((datetime.utcnow() - cached.cached_at).total_seconds() / 60)

            await show_scenarios_list(
                callback.message,
                cached.scenarios,
                symbol,
                timeframe,
                market_context=market_context_obj,
                no_trade=no_trade_obj,
                current_price=cached.current_price,
                cached_age_mins=age_mins
            )
            return

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

        # Запросить полный анализ (не только сценарии)
        analysis = await syntra.get_analysis(
            symbol=symbol,
            timeframe=timeframe,
            max_scenarios=3,
            user_params=user_params
        )

        scenarios = analysis.scenarios

        if not scenarios:
            await callback.message.edit_text(
                f"❌ <b>Нет сценариев</b>\n\n"
                f"Syntra AI не нашёл подходящих торговых сценариев для {symbol} на {timeframe}.\n\n"
                f"Попробуй другой символ или таймфрейм.",
                reply_markup=ai_scenarios_kb.get_symbols_keyboard()
            )
            await state.set_state(AIScenarioStates.choosing_symbol)
            return

        # Подготовить market_context dict для кэша
        market_context_dict = {
            "trend": analysis.market_context.trend,
            "phase": analysis.market_context.phase,
            "sentiment": analysis.market_context.sentiment,
            "volatility": analysis.market_context.volatility,
            "bias": analysis.market_context.bias,
            "strength": analysis.market_context.strength,
            "rsi": analysis.market_context.rsi,
            "funding_rate_pct": analysis.market_context.funding_rate_pct,
        }

        # Подготовить no_trade dict
        no_trade_dict = {
            "should_not_trade": analysis.no_trade.should_not_trade if analysis.no_trade else False,
            "confidence": analysis.no_trade.confidence if analysis.no_trade else 0,
            "category": analysis.no_trade.category if analysis.no_trade else "",
            "reasons": analysis.no_trade.reasons if analysis.no_trade else [],
            "wait_for": analysis.no_trade.wait_for if analysis.no_trade else None,
        } if analysis.no_trade else None

        # === СОХРАНИТЬ В КЭШ ===
        cache.set(
            user_id=user_id,
            symbol=symbol,
            timeframe=timeframe,
            scenarios=scenarios,
            analysis_id=analysis.analysis_id,
            current_price=analysis.current_price,
            market_context=market_context_dict,
            no_trade=no_trade_dict,
            key_levels=analysis.key_levels,
        )

        # Сохранить полный анализ в state
        await state.update_data(
            scenarios=scenarios,
            analysis_id=analysis.analysis_id,
            current_price=analysis.current_price,
            market_context=market_context_dict,
            no_trade=no_trade_dict,
            key_levels=analysis.key_levels,
        )

        # Показать список сценариев с market_context и no_trade
        await show_scenarios_list(
            callback.message,
            scenarios,
            symbol,
            timeframe,
            market_context=analysis.market_context,
            no_trade=analysis.no_trade,
            current_price=analysis.current_price
        )

    except SyntraAPIError as e:
        logger.error(f"Syntra API error: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка Syntra AI:</b>\n\n{html.escape(str(e))}\n\n"
            f"Проверь, что Syntra AI запущен и доступен по адресу:\n"
            f"<code>{config.SYNTRA_API_URL}</code>",
            reply_markup=ai_scenarios_kb.get_symbols_keyboard()
        )
        await state.set_state(AIScenarioStates.choosing_symbol)

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ <b>Неожиданная ошибка:</b>\n\n{html.escape(str(e))}",
            reply_markup=ai_scenarios_kb.get_symbols_keyboard()
        )
        await state.set_state(AIScenarioStates.choosing_symbol)


async def show_scenarios_list(
    message: Message,
    scenarios: list,
    symbol: str,
    timeframe: str,
    market_context: Optional[MarketContext] = None,
    no_trade: Optional[NoTradeSignal] = None,
    current_price: float = 0.0,
    cached_age_mins: Optional[int] = None
):
    """Показать список сценариев с market context и no_trade предупреждением"""

    # === HEADER с текущей ценой ===
    text = f"🤖 <b>AI Scenarios: {symbol} ({timeframe})</b>\n"
    if current_price > 0:
        text += f"💰 Price: ${current_price:,.2f}\n"

    # Показать что данные из кэша
    if cached_age_mins is not None:
        if cached_age_mins < 60:
            text += f"📦 <i>Cached {cached_age_mins}m ago</i>\n"
        else:
            hours = cached_age_mins // 60
            mins = cached_age_mins % 60
            text += f"📦 <i>Cached {hours}h {mins}m ago</i>\n"

    text += "\n"

    # === MARKET CONTEXT ===
    if market_context:
        trend_emoji = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}.get(market_context.trend, "➡️")
        sentiment_emoji = {"greed": "🟢", "fear": "🔴", "neutral": "⚪", "extreme_greed": "🟢🟢", "extreme_fear": "🔴🔴"}.get(market_context.sentiment, "⚪")
        vol_emoji = {"low": "🔵", "medium": "🟡", "high": "🔴"}.get(market_context.volatility, "🟡")

        text += f"<b>📊 Market:</b> {trend_emoji} {market_context.trend.capitalize()}"
        text += f" | {sentiment_emoji} {market_context.sentiment.capitalize()}"
        text += f" | {vol_emoji} Vol: {market_context.volatility}\n"

        # RSI и Funding если есть
        extras = []
        if market_context.rsi:
            rsi_indicator = "🔴" if market_context.rsi > 70 else "🟢" if market_context.rsi < 30 else ""
            extras.append(f"RSI: {market_context.rsi:.0f}{rsi_indicator}")
        if market_context.funding_rate_pct is not None:
            fund_emoji = "🔴" if abs(market_context.funding_rate_pct) > 0.05 else ""
            extras.append(f"Fund: {market_context.funding_rate_pct:+.3f}%{fund_emoji}")
        if extras:
            text += f"   {' | '.join(extras)}\n"
        text += "\n"

    # === NO-TRADE WARNING ===
    if no_trade and no_trade.should_not_trade:
        category_emoji = {
            "chop": "🌀",
            "extreme_sentiment": "⚠️",
            "low_liquidity": "💧",
            "news_risk": "📰",
            "technical_conflict": "⚔️",
        }.get(no_trade.category, "⚠️")

        text += f"{category_emoji} <b>⚠️ CAUTION: {no_trade.category.upper()}</b> ({no_trade.confidence*100:.0f}%)\n"

        # Показываем первые 2 причины (экранируем HTML)
        for reason in no_trade.reasons[:2]:
            text += f"   • {html.escape(str(reason))}\n"

        # Wait for
        if no_trade.wait_for:
            wait_items = [html.escape(str(w)) for w in no_trade.wait_for[:2]]
            text += f"   <i>Ждать: {', '.join(wait_items)}</i>\n"

        text += "\n"

    # === SCENARIOS LIST ===
    text += "<b>📋 Сценарии:</b>\n\n"

    for i, scenario in enumerate(scenarios, 1):
        bias = scenario.get("bias", "neutral")
        bias_emoji = "🟢" if bias == "long" else "🔴" if bias == "short" else "⚪"

        name = html.escape(scenario.get("name", f"Scenario {i}"))
        confidence = scenario.get("confidence", 0) * 100

        # EV Grade если есть
        ev_metrics = scenario.get("ev_metrics") or {}
        ev_grade = ev_metrics.get("ev_grade", "")
        ev_r = ev_metrics.get("ev_r")
        ev_flags = ev_metrics.get("flags", [])
        ev_info = ""
        if ev_grade:
            grade_emoji = {"A": "🅰️", "B": "🅱️", "C": "©️", "D": "🅳"}.get(ev_grade, "")
            ev_info = f" {grade_emoji}"
            if ev_r is not None:
                ev_info += f" EV:{ev_r:+.2f}R"
            if "tp1_rr_penalty_zone" in ev_flags:
                ev_info += " ⚠️"

        # Class warning
        class_warning = scenario.get("class_warning")
        warning_mark = " ⚠️" if class_warning else ""

        # Entry zone
        entry = scenario.get("entry", {})
        entry_min = entry.get("price_min", 0)
        entry_max = entry.get("price_max", 0)

        # Stop Loss
        stop_loss = scenario.get("stop_loss", {})
        sl_price = stop_loss.get("recommended", 0)

        # Все TP targets
        targets = scenario.get("targets", [])

        # Формируем текст сценария
        text += f"{i}. {bias_emoji} <b>{name}</b> ({confidence:.0f}%){ev_info}{warning_mark}\n"
        text += f"   Entry: ${entry_min:,.2f} - ${entry_max:,.2f}\n"
        text += f"   Stop: ${sl_price:,.2f}\n"

        # Показываем TP
        if targets:
            for idx, target in enumerate(targets[:3], 1):
                tp_price = target.get("price", 0)
                tp_rr = target.get("rr", 0)
                partial_pct = target.get("partial_close_pct", 100)
                text += f"   TP{idx}: ${tp_price:,.2f} (RR {tp_rr:.1f}x) - {partial_pct}%\n"
        else:
            text += f"   TP: N/A\n"

        text += "\n"

    text += "📌 Выбери сценарий для деталей:"

    # Пробуем edit, если не получится (медиа-сообщение) - удаляем и отправляем новое
    try:
        await message.edit_text(
            text,
            reply_markup=ai_scenarios_kb.get_scenarios_keyboard(scenarios)
        )
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(
            text,
            reply_markup=ai_scenarios_kb.get_scenarios_keyboard(scenarios)
        )


@router.callback_query(AIScenarioStates.viewing_scenarios, F.data.startswith("ai:scenario:"))
async def ai_scenario_selected(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Показать детали выбранного сценария"""
    scenario_index = int(callback.data.split(":")[2])

    data = await state.get_data()
    scenarios = data.get("scenarios", [])

    if scenario_index >= len(scenarios):
        await callback.answer("❌ Сценарий не найден", show_alert=True)
        return

    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "")
    timeframe = data.get("timeframe", "")
    current_price = data.get("current_price", 0.0)
    market_context = data.get("market_context")

    # Определяем режим риска
    user_settings = await settings_storage.get_settings(callback.from_user.id)
    risk_mode = 'percent' if user_settings.trading_capital_mode == 'auto' else 'usd'

    await state.update_data(selected_scenario_index=scenario_index, risk_mode=risk_mode)
    await state.set_state(AIScenarioStates.viewing_detail)

    # Показать детали сценария с графиком
    await show_scenario_detail(
        callback.message, scenario, scenario_index,
        symbol=symbol, timeframe=timeframe, current_price=current_price,
        market_context=market_context, user_id=callback.from_user.id,
        risk_mode=risk_mode
    )

    await callback.answer()


async def show_scenario_detail(
    message: Message,
    scenario: dict,
    scenario_index: int,
    symbol: str = "",
    timeframe: str = "",
    current_price: float = 0.0,
    market_context: Optional[dict] = None,
    user_id: Optional[int] = None,
    risk_mode: str = 'usd',
):
    """Показать детальную карточку сценария с графиком и EV метриками"""

    # Базовая информация
    name = html.escape(scenario.get("name", "Unknown Scenario"))
    bias = scenario.get("bias", "neutral")
    bias_emoji = "🟢" if bias == "long" else "🔴" if bias == "short" else "⚪"
    confidence = scenario.get("confidence", 0) * 100

    # Archetype
    archetype = scenario.get("primary_archetype", "")
    archetype_text = f" [{html.escape(str(archetype))}]" if archetype else ""

    # === REAL EV GATE CHECK ===
    real_ev_text = ""
    is_blocked = False
    gate_result = None

    if archetype and timeframe:
        try:
            gate_checker = get_gate_checker()
            # Формируем market_regime из trend + phase
            regime = None
            if market_context:
                trend = market_context.get("trend")
                phase = market_context.get("phase")
                if trend and phase:
                    regime = f"{trend}_{phase}"

            gate_result = await gate_checker.check(
                archetype=archetype,
                timeframe=timeframe,
                market_regime=regime,
                symbol=symbol,
                user_id=user_id,
            )

            # Формируем текст для UI
            if gate_result.status == GateStatus.BLOCK:
                is_blocked = True
                stats = gate_result.stats
                real_ev_text = f"\n🔴 <b>BLOCKED:</b> {html.escape(gate_result.message)}"
                if stats:
                    real_ev_text += f"\n   Real EV: {stats.real_ev:+.2f}R (n={stats.sample_size})"
                real_ev_text += "\n"

            elif gate_result.status == GateStatus.SOFT_BLOCK:
                stats = gate_result.stats
                real_ev_text = f"\n🟠 <b>Warning:</b> {html.escape(gate_result.message)}"
                if stats:
                    real_ev_text += f"\n   Real EV: {stats.real_ev:+.2f}R (n={stats.sample_size})"
                real_ev_text += "\n"

            elif gate_result.status == GateStatus.WARN:
                stats = gate_result.stats
                real_ev_text = f"\n🟡 <b>Real EV:</b> {stats.real_ev:+.2f}R (n={stats.sample_size})"
                if stats.rolling_ev is not None:
                    real_ev_text += f" | Rolling: {stats.rolling_ev:+.2f}R"
                real_ev_text += "\n"

            elif gate_result.status == GateStatus.ALLOWED and gate_result.stats:
                stats = gate_result.stats
                real_ev_text = f"\n✅ <b>Real EV:</b> {stats.real_ev:+.2f}R (n={stats.sample_size})"
                if stats.rolling_ev is not None:
                    real_ev_text += f" | Rolling: {stats.rolling_ev:+.2f}R"
                real_ev_text += "\n"

            elif gate_result.status == GateStatus.NO_DATA:
                real_ev_text = "\n🔘 <b>Real EV:</b> <i>Недостаточно данных</i>\n"

        except Exception as e:
            logger.warning(f"Real EV gate check failed: {e}")

    # Entry Plan (ladder) или обычный Entry
    entry_plan = scenario.get("entry_plan")
    entry = scenario.get("entry", {})

    # Формируем текст для entry
    if entry_plan and entry_plan.get("orders"):
        orders = entry_plan.get("orders", [])
        mode = entry_plan.get("mode", "ladder")

        entry_text = f"💹 <b>Entry Orders ({len(orders)}):</b> [{html.escape(str(mode))}]\n"
        for i, order in enumerate(orders, 1):
            price = order.get("price", 0)
            size_pct = order.get("size_pct", 0)
            tag = html.escape(str(order.get("tag", f"E{i}")))
            entry_text += f"   E{i}: ${price:,.2f} ({size_pct}%) - {tag}\n"

        prices = [o.get("price", 0) for o in orders]
        weights = [o.get("size_pct", 0) for o in orders]
        total_weight = sum(weights)
        if total_weight > 0:
            entry_avg = sum(p * w for p, w in zip(prices, weights)) / total_weight
            entry_text += f"   <i>Avg: ${entry_avg:,.2f}</i>"
    else:
        entry_min = entry.get("price_min", 0)
        entry_max = entry.get("price_max", 0)
        entry_avg = (entry_min + entry_max) / 2 if entry_min and entry_max else 0
        entry_type = html.escape(str(entry.get("type", "market_order")))

        entry_text = f"💹 <b>Entry Zone:</b> ${entry_min:,.2f} - ${entry_max:,.2f}\n"
        entry_text += f"   Avg: ${entry_avg:,.2f} ({entry_type})"

    # Stop Loss
    stop_loss = scenario.get("stop_loss", {})
    sl_price = stop_loss.get("recommended", 0)
    sl_reason = html.escape(str(stop_loss.get("reason", ""))) if stop_loss.get("reason") else ""

    # Targets
    targets = scenario.get("targets", [])
    targets_text = ""
    for target in targets:
        level = target.get("level", 0)
        price = target.get("price", 0)
        partial_close = target.get("partial_close_pct", 100)
        rr = target.get("rr", 0)
        targets_text += f"   TP{level}: ${price:,.2f} ({partial_close}%) - RR {rr:.1f}\n"

    # Leverage
    leverage_info = scenario.get("leverage", {})
    lev_recommended = leverage_info.get("recommended", "5x") if isinstance(leverage_info, dict) else f"{leverage_info}x"
    lev_max_safe = leverage_info.get("max_safe", "10x") if isinstance(leverage_info, dict) else f"{leverage_info}x"

    # === EV METRICS ===
    ev_metrics = scenario.get("ev_metrics") or {}
    ev_text = ""
    if ev_metrics:
        ev_r = ev_metrics.get("ev_r")
        ev_r_after_tp1 = ev_metrics.get("ev_r_after_tp1")
        ev_grade = ev_metrics.get("ev_grade", "")
        scenario_score = ev_metrics.get("scenario_score")
        ev_flags = ev_metrics.get("flags", [])

        grade_emoji = {"A": "🅰️", "B": "🅱️", "C": "©️", "D": "🅳"}.get(ev_grade, "")
        ev_text = f"\n📈 <b>Expected Value:</b> {grade_emoji} Grade {ev_grade}"
        if ev_r is not None:
            ev_color = "+" if ev_r >= 0 else ""
            ev_text += f" | EV: {ev_color}{ev_r:.2f}R"
        if ev_r_after_tp1 is not None and ev_r_after_tp1 != 0:
            ev_text += f" | after_TP1: {ev_r_after_tp1:+.2f}R"
        if scenario_score is not None:
            ev_text += f" | Score: {scenario_score:.0f}"
        # Показываем флаги penalty/adjusted
        if "tp1_rr_penalty_zone" in ev_flags:
            ev_text += " ⚠️<i>RR penalty</i>"
        ev_text += "\n"

    # === OUTCOME PROBS ===
    outcome_probs = scenario.get("outcome_probs") or {}
    probs_text = ""
    if outcome_probs and outcome_probs.get("source"):
        prob_sl = outcome_probs.get("sl", 0)
        prob_tp1 = outcome_probs.get("tp1", 0)
        prob_tp2 = outcome_probs.get("tp2")
        prob_tp3 = outcome_probs.get("tp3")
        probs_source = html.escape(str(outcome_probs.get("source", "")))
        sample_size = outcome_probs.get("sample_size")

        probs_text = f"📊 <b>Outcome Probs</b> <i>({probs_source}"
        if sample_size:
            probs_text += f", n={sample_size}"
        probs_text += ")</i>:\n"
        probs_text += f"   SL: {prob_sl*100:.0f}% | TP1: {prob_tp1*100:.0f}%"
        if prob_tp2:
            probs_text += f" | TP2: {prob_tp2*100:.0f}%"
        if prob_tp3:
            probs_text += f" | TP3: {prob_tp3*100:.0f}%"
        probs_text += "\n"

    # === CLASS STATS / WARNING ===
    class_stats = scenario.get("class_stats") or {}
    class_warning = scenario.get("class_warning")
    class_text = ""

    if class_warning:
        class_text = f"\n⚠️ <b>Warning:</b> {html.escape(str(class_warning))}\n"
    elif class_stats and class_stats.get("sample_size", 0) >= 20:
        winrate = class_stats.get("winrate", 0)
        avg_pnl_r = class_stats.get("avg_pnl_r", 0)
        sample = class_stats.get("sample_size", 0)
        class_text = f"\n📉 <b>Class Stats</b> <i>(n={sample})</i>: WR {winrate*100:.0f}% | Avg: {avg_pnl_r:+.2f}R\n"

    # Why
    why = scenario.get("why", {})
    bullish_factors = why.get("bullish_factors", [])
    bearish_factors = why.get("bearish_factors", [])
    risks = why.get("risks", [])

    # Формируем карточку
    card = f"""
{bias_emoji} <b>{name}</b>{archetype_text}
📊 Confidence: {confidence:.0f}%
{ev_text}{probs_text}{class_text}{real_ev_text}
{entry_text}

🛑 <b>Stop Loss:</b> ${sl_price:,.2f}
   {sl_reason if sl_reason else ""}

🎯 <b>Targets:</b>
{targets_text}

📊 <b>Leverage:</b> {lev_recommended} (max safe: {lev_max_safe})
"""

    # Факторы (экранируем HTML)
    if bullish_factors:
        card += "\n🟢 <b>Bullish:</b>\n"
        for factor in bullish_factors[:2]:
            card += f"   • {html.escape(str(factor))}\n"

    if bearish_factors:
        card += "\n🔴 <b>Bearish:</b>\n"
        for factor in bearish_factors[:2]:
            card += f"   • {html.escape(str(factor))}\n"

    if risks:
        card += "\n⚠️ <b>Risks:</b>\n"
        for risk in risks[:2]:
            card += f"   • {html.escape(str(risk))}\n"

    if is_blocked:
        card += "\n🚫 <b>Торговля заблокирована (Real EV)</b>"
    else:
        card += "\n💰 <b>Выбери риск для открытия:</b>"

    # Лимит caption для фото - 1024 символа
    CAPTION_LIMIT = 1024

    # Генерируем график если есть данные о символе
    chart_png = None
    if symbol and timeframe:
        try:
            bybit = BybitClient(testnet=config.DEFAULT_TESTNET_MODE)
            klines = await bybit.get_klines(
                symbol=symbol,
                interval=timeframe,
                limit=100
            )
            if klines:
                generator = get_chart_generator()
                chart_png = generator.generate_scenario_chart(
                    klines=klines,
                    scenario=scenario,
                    symbol=symbol,
                    timeframe=timeframe,
                    current_price=current_price
                )
        except Exception as e:
            logger.warning(f"Chart generation failed: {e}")

    # Удаляем старое сообщение (текстовое нельзя преобразовать в фото)
    try:
        await message.delete()
    except Exception:
        pass

    # Отправляем в зависимости от длины текста и наличия графика
    if chart_png and len(card) <= CAPTION_LIMIT:
        # Текст короткий - отправляем фото с caption
        photo = BufferedInputFile(chart_png, filename=f"{symbol}_{timeframe}.png")
        await message.answer_photo(
            photo=photo,
            caption=card,
            parse_mode="HTML",
            reply_markup=ai_scenarios_kb.get_scenario_detail_keyboard(
                scenario_index, show_chart_button=False, is_blocked=is_blocked, risk_mode=risk_mode
            )
        )
    elif chart_png:
        # Текст длинный - отправляем фото отдельно, потом текст с кнопкой
        photo = BufferedInputFile(chart_png, filename=f"{symbol}_{timeframe}.png")
        await message.answer_photo(photo=photo)
        await message.answer(
            card,
            parse_mode="HTML",
            reply_markup=ai_scenarios_kb.get_scenario_detail_keyboard(
                scenario_index, show_chart_button=False, is_blocked=is_blocked, risk_mode=risk_mode
            )
        )
    else:
        # Нет графика - просто текст с кнопкой графика
        await message.answer(
            card,
            parse_mode="HTML",
            reply_markup=ai_scenarios_kb.get_scenario_detail_keyboard(
                scenario_index, show_chart_button=True, is_blocked=is_blocked, risk_mode=risk_mode
            )
        )


@router.callback_query(AIScenarioStates.viewing_detail, F.data.startswith("ai:chart:"))
async def ai_show_chart(callback: CallbackQuery, state: FSMContext):
    """Сгенерировать и показать график сценария со стопами и тейками"""
    scenario_index = int(callback.data.split(":")[2])

    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    symbol = data.get("symbol", "BTCUSDT")
    timeframe = data.get("timeframe", "4h")
    current_price = data.get("current_price", 0.0)

    if scenario_index >= len(scenarios):
        await callback.answer("Сценарий не найден", show_alert=True)
        return

    scenario = scenarios[scenario_index]

    await callback.answer("Генерирую график...")

    try:
        # Получаем klines от Bybit
        bybit = BybitClient(testnet=config.DEFAULT_TESTNET_MODE)
        klines = await bybit.get_klines(
            symbol=symbol,
            interval=timeframe,
            limit=100
        )

        if not klines:
            await callback.message.answer("Не удалось получить данные свечей")
            return

        # Генерируем график
        generator = get_chart_generator()
        chart_png = generator.generate_scenario_chart(
            klines=klines,
            scenario=scenario,
            symbol=symbol,
            timeframe=timeframe,
            current_price=current_price
        )

        # Отправляем как фото
        photo = BufferedInputFile(chart_png, filename=f"{symbol}_{timeframe}_chart.png")

        bias = scenario.get("bias", "neutral")
        bias_emoji = "🟢 LONG" if bias == "long" else "🔴 SHORT"
        name = scenario.get("name", "Scenario")

        caption = (
            f"📊 <b>{symbol} {timeframe.upper()}</b>\n"
            f"{bias_emoji} - {name}\n\n"
            f"🟢 Entry Zone\n"
            f"🔴 Stop Loss\n"
            f"🔵 Take Profit\n"
            f"🟠 Current Price"
        )

        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML"
        )

        logger.info(f"Chart generated for {symbol} {timeframe}")

    except Exception as e:
        logger.error(f"Chart generation error: {e}", exc_info=True)
        await callback.message.answer(f"Ошибка генерации графика: {e}")


@router.callback_query(AIScenarioStates.viewing_detail, F.data.startswith("ai:custom_risk:"))
async def ai_custom_risk_start(callback: CallbackQuery, state: FSMContext):
    """Начать ввод custom риска в USD"""
    scenario_index = int(callback.data.split(":")[2])

    await state.update_data(selected_scenario_index=scenario_index, input_mode="risk_usd")
    await state.set_state(AIScenarioStates.entering_custom_risk)

    await callback.message.edit_text(
        "💰 <b>Custom Risk</b>\n\n"
        "Введи сумму риска в USD (от 1 до 500):\n\n"
        "Например: <code>15</code> или <code>75.5</code>",
        reply_markup=ai_scenarios_kb.get_custom_risk_cancel_keyboard(scenario_index)
    )

    await callback.answer()


@router.callback_query(AIScenarioStates.viewing_detail, F.data.startswith("ai:custom_risk_pct:"))
async def ai_custom_risk_pct_start(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Начать ввод custom риска в процентах"""
    scenario_index = int(callback.data.split(":")[2])

    # Получаем баланс для показа в сообщении
    data = await state.get_data()
    user_settings = await settings_storage.get_settings(callback.from_user.id)

    equity_info = ""
    try:
        equity, updated_data = await get_equity_cached(data, user_settings)
        await state.update_data(**updated_data)
        equity_info = f"\n💵 <b>Баланс:</b> ${equity:.2f}\n"
    except ValueError:
        pass

    await state.update_data(selected_scenario_index=scenario_index, input_mode="risk_pct")
    await state.set_state(AIScenarioStates.entering_custom_risk)

    await callback.message.edit_text(
        f"💰 <b>Custom Risk %</b>\n"
        f"{equity_info}\n"
        f"Введи процент риска ({MIN_RISK_PCT}% – {MAX_RISK_PCT}%):\n"
        f"<i>Рекомендуется: 0.5–1%</i>\n\n"
        f"Например: <code>0.75</code>",
        reply_markup=ai_scenarios_kb.get_custom_risk_cancel_keyboard(scenario_index)
    )

    await callback.answer()


@router.message(AIScenarioStates.entering_custom_risk)
async def ai_custom_risk_process(message: Message, state: FSMContext, settings_storage):
    """Обработать введённый пользователем custom риск (USD или %)"""
    user_id = message.from_user.id
    data = await state.get_data()
    input_mode = data.get("input_mode", "risk_usd")

    try:
        # Парсим значение
        value_text = message.text.strip().replace(",", ".").replace("$", "").replace("%", "")
        value = float(value_text)

        if value <= 0:
            await message.answer("⚠️ Значение должно быть положительным числом!")
            return

        settings = await settings_storage.get_settings(user_id)

        # === Режим процентного риска ===
        if input_mode == "risk_pct":
            pct = value

            # Валидация процента
            is_valid, error = validate_risk_pct(pct)
            if not is_valid:
                await message.answer(f"⚠️ {error}")
                return

            # Получаем баланс
            try:
                equity, updated_data = await get_equity_cached(data, settings)
                await state.update_data(**updated_data)
            except ValueError as e:
                await message.answer(f"⚠️ {e}")
                return

            # Рассчитываем риск
            custom_risk = calc_risk_usd_from_pct(equity, pct)

            # Валидация итогового риска
            is_valid, error = validate_risk_usd(custom_risk, settings.max_risk_per_trade)
            if not is_valid:
                await message.answer(f"⚠️ {error}")
                return

            logger.info(f"User {user_id}: custom {pct}% of ${equity:.2f} = ${custom_risk:.2f}")

        # === Режим USD ===
        else:
            custom_risk = value

            if custom_risk < 1:
                await message.answer("⚠️ Минимальный риск: $1")
                return

            if custom_risk > 500:
                await message.answer("⚠️ Максимальный риск: $500")
                return

        # Получаем данные сценария
        scenarios = data.get("scenarios", [])
        scenario_index = data.get("selected_scenario_index", 0)
        scenario = scenarios[scenario_index]
        symbol = data.get("symbol", "BTCUSDT")

        # Используем leverage из сценария (если есть), иначе из settings
        leverage = _parse_leverage(scenario.get("leverage"), settings.default_leverage)

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
        if input_mode == "risk_pct":
            await message.answer(
                "⚠️ Неверный формат!\n\n"
                "Введи процент, например: <code>0.75</code> или <code>1.5</code>"
            )
        else:
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
    symbol = data.get("symbol", "")
    timeframe = data.get("timeframe", "")
    current_price = data.get("current_price", 0.0)
    market_context = data.get("market_context")
    risk_mode = data.get("risk_mode", "usd")

    await state.set_state(AIScenarioStates.viewing_detail)

    # Показываем детали сценария с графиком
    await show_scenario_detail(
        callback.message, scenario, scenario_index,
        symbol=symbol, timeframe=timeframe, current_price=current_price,
        market_context=market_context, user_id=callback.from_user.id,
        risk_mode=risk_mode
    )

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

    # Используем leverage из сценария (если есть), иначе из settings
    leverage = _parse_leverage(scenario.get("leverage"), settings.default_leverage)

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


@router.callback_query(AIScenarioStates.viewing_detail, F.data.startswith("ai:trade_pct:"))
async def ai_trade_with_risk_percent(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Пользователь выбрал процент риска - конвертировать в USD и показать подтверждение"""
    # Парсинг: ai:trade_pct:0:0.5
    parts = callback.data.split(":")
    scenario_index = int(parts[2])
    pct = float(parts[3])

    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "BTCUSDT")

    user_id = callback.from_user.id
    settings = await settings_storage.get_settings(user_id)

    # Валидация процента
    is_valid, error = validate_risk_pct(pct)
    if not is_valid:
        await callback.answer(f"❌ {error}", show_alert=True)
        return

    # Получаем баланс из кэша
    try:
        equity, updated_data = await get_equity_cached(data, settings)
        await state.update_data(**updated_data)
    except ValueError as e:
        await callback.answer(f"❌ {e}", show_alert=True)
        return

    # Рассчитываем risk_usd
    base_risk_usd = calc_risk_usd_from_pct(equity, pct)

    # Валидация итогового риска
    max_risk = settings.max_risk_per_trade
    is_valid, error = validate_risk_usd(base_risk_usd, max_risk)
    if not is_valid:
        await callback.answer(f"❌ {error}", show_alert=True)
        return

    logger.info(f"User {user_id}: AI trade {pct}% of ${equity:.2f} = ${base_risk_usd:.2f}")

    # Используем leverage из сценария (если есть), иначе из settings
    leverage = _parse_leverage(scenario.get("leverage"), settings.default_leverage)

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
        risk_percent=pct,
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

    await callback.answer(f"Риск: {pct}% = ${base_risk_usd:.2f}")


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

    # Пробуем edit, если не получится (медиа-сообщение) - удаляем и отправляем новое
    try:
        await message.edit_text(
            card,
            reply_markup=ai_scenarios_kb.get_confirm_trade_keyboard(0, risk_usd)
        )
    except Exception:
        # Сообщение с графиком - удаляем и отправляем новое
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(
            card,
            reply_markup=ai_scenarios_kb.get_confirm_trade_keyboard(0, risk_usd)
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
async def ai_execute_trade(callback: CallbackQuery, state: FSMContext, settings_storage, lock_manager, trade_logger, order_monitor, entry_plan_monitor=None):
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

        # === 🆕 SAFETY CAPS CHECK ===
        trading_mode = data.get("trading_mode", settings.default_trading_mode or "standard")
        safety_checker = get_safety_checker(trade_logger)
        safety_result = await safety_checker.check_can_trade(
            user_id=user_id,
            mode_id=trading_mode,
            risk_usd=risk_usd
        )

        if not safety_result.allowed:
            await lock_manager.release_lock(user_id)
            cooldown_text = ""
            if safety_result.cooldown_remaining_min:
                cooldown_text = f"\n⏳ Cooldown: {safety_result.cooldown_remaining_min} мин"

            await callback.message.edit_text(
                f"⛔️ <b>Safety Limit Reached</b>\n\n"
                f"<b>Причина:</b> {safety_result.reason}\n"
                f"{cooldown_text}\n\n"
                f"📊 Сегодня: {safety_result.trades_today} сделок, "
                f"{safety_result.losses_today} убытков "
                f"(${safety_result.loss_today_usd:.2f})\n"
                f"🔄 Подряд убытков: {safety_result.consecutive_losses}\n\n"
                f"<i>Это ограничение режима {trading_mode.upper()} для защиты от овертрейдинга.</i>",
                reply_markup=None
            )
            await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
            await state.clear()
            return

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

        # Определяем fallback order_type (используется только если нет entry_plan)
        if in_zone:
            order_type = "Market"
            entry_price = current_price
            logger.debug(f"Zone check: ${current_price:.2f} in zone ${entry_min:.2f}-${entry_max:.2f}")
        else:
            order_type = "Limit"
            if bias == "long":
                entry_price = entry_max
            else:
                entry_price = entry_min
            logger.debug(f"Zone check: ${current_price:.2f} outside zone → fallback entry ${entry_price:.2f}")

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
        trade_id = str(uuid.uuid4())

        # ===== ПРОВЕРКА ENTRY_PLAN (LADDER ENTRY) =====
        # Получаем instrument_info для округления qty
        instrument_info = position_calc.get('instrument_info', {})
        qty_step = instrument_info.get('qtyStep', '0.001')
        tick_size = instrument_info.get('tickSize', '0.01')

        entry_plan = parse_entry_plan(
            scenario=scenario,
            trade_id=trade_id,
            user_id=user_id,
            symbol=symbol,
            side=side,
            risk_usd=risk_usd,
            leverage=leverage,
            testnet=testnet_mode,
            qty_step=qty_step,
            tick_size=tick_size,
            current_price=current_price
        )

        if entry_plan and entry_plan_monitor:
            # === НОВАЯ ЛОГИКА: ENTRY PLAN с Risk-on-plan ===
            logger.info(
                f"Using entry_plan mode: {entry_plan.mode}, "
                f"{len(entry_plan.orders)} orders, Q_total={entry_plan.total_qty:.6f}"
            )

            # Используем qty из entry_plan (рассчитан по P_avg)
            plan_qty = entry_plan.total_qty

            # Создаём TradeRecord заранее (будет обновляться по мере fills)
            try:
                from services.trade_logger import calculate_fee, calculate_margin

                # Используем P_avg для начального расчёта (будет обновлено после fills)
                # P_avg уже рассчитан в entry_plan как средневзвешенная цена
                orders_list = entry_plan.get_orders()
                p_avg = sum(o.price * o.size_pct for o in orders_list) / 100

                margin_usd = calculate_margin(p_avg, plan_qty, leverage)
                entry_fee_estimate = calculate_fee(p_avg, plan_qty, is_taker=False)

                # Extract EV metrics and class stats from scenario (handle None values)
                ev_metrics = scenario.get("ev_metrics") or {}
                class_stats = scenario.get("class_stats") or {}
                outcome_probs = scenario.get("outcome_probs") or {}

                trade_record = TradeRecord(
                    trade_id=trade_id,
                    user_id=user_id,
                    symbol=symbol,
                    side=side,
                    opened_at=datetime.utcnow().isoformat(),
                    entry_price=p_avg,  # Используем P_avg как начальную цену
                    qty=plan_qty,       # Используем Q_total из risk-on-plan
                    leverage=leverage,
                    margin_mode=settings.default_margin_mode,
                    margin_usd=margin_usd,
                    stop_price=stop_price,
                    risk_usd=risk_usd,
                    tp_price=targets[0].get("price") if targets else None,
                    entry_fee_usd=entry_fee_estimate,
                    total_fees_usd=entry_fee_estimate,
                    status="open",
                    testnet=testnet_mode,
                    # Entry Plan fields
                    entry_plan_id=entry_plan.plan_id,
                    entry_mode=entry_plan.mode,
                    entry_orders_count=len(entry_plan.orders),
                    # AI Scenario fields
                    scenario_id=str(uuid.uuid4()),
                    scenario_source="syntra",
                    scenario_bias=scenario.get("bias"),
                    scenario_confidence=scenario.get("confidence"),
                    timeframe=data.get("timeframe"),
                    entry_reason=scenario.get("name"),
                    scenario_snapshot=scenario,
                    # Syntra metadata
                    analysis_id=data.get("analysis_id"),
                    primary_archetype=scenario.get("primary_archetype"),
                    ev_r=ev_metrics.get("ev_r"),
                    ev_grade=ev_metrics.get("ev_grade"),
                    scenario_score=ev_metrics.get("scenario_score"),
                    class_key=class_stats.get("class_key"),
                    class_winrate=class_stats.get("winrate"),
                    class_warning=scenario.get("class_warning"),
                    prob_sl=outcome_probs.get("sl"),
                    prob_tp1=outcome_probs.get("tp1"),
                    probs_source=outcome_probs.get("source"),
                )
                await trade_logger.log_trade(trade_record)
                logger.info(f"Trade record created for entry_plan: {trade_id}")

                # Register scenario with Supervisor for position monitoring
                try:
                    supervisor = SupervisorClient()
                    await supervisor.register_trade(
                        trade_id=trade_id,
                        user_id=user_id,
                        symbol=symbol,
                        timeframe=data.get("timeframe", "1h"),
                        side=side,
                        scenario_data=scenario
                    )
                    logger.info(f"Scenario registered with supervisor: {trade_id}")
                except Exception as sup_error:
                    logger.warning(f"Failed to register with supervisor (non-critical): {sup_error}")

            except Exception as log_error:
                logger.error(f"Failed to create trade record: {log_error}")

            # Регистрируем план в мониторе
            await entry_plan_monitor.register_plan(entry_plan)

            # Формируем сообщение об успехе
            coin = symbol.replace("USDT", "")
            success_text = f"""
📋 <b>Entry Plan создан!</b>

{side_emoji} <b>{symbol}</b> {bias.upper()}
📊 Mode: {entry_plan.mode}

<b>Entry Orders ({len(entry_plan.orders)}):</b>
"""
            for i, order in enumerate(entry_plan.get_orders(), 1):
                success_text += f"   E{i}: ${order.price:.2f} ({order.size_pct:.0f}%) qty={order.qty:.4f}\n"

            success_text += f"""
📈 <b>P_avg:</b> ${p_avg:.2f} (средневзвешенная)
📦 <b>Q_total:</b> {plan_qty:.4f} {coin}
🛑 <b>Stop:</b> ${stop_price:.2f}
"""
            if targets:
                for idx, target in enumerate(targets, 1):
                    tp_price = target.get("price", 0)
                    partial_pct = target.get("partial_close_pct", 0)
                    success_text += f"🎯 <b>TP{idx}:</b> ${tp_price:.2f} ({partial_pct}%)\n"

            activation_info = ""
            if entry_plan.activation_type != "immediate":
                activation_info = f"\n⏳ <b>Activation:</b> {entry_plan.activation_type} @ ${entry_plan.activation_level:.2f}"
            else:
                activation_info = "\n✅ <b>Activation:</b> immediate"

            success_text += f"""
{activation_info}
⏰ <b>Valid:</b> {entry_plan.time_valid_hours}h
💰 <b>Risk:</b> ${risk_usd:.2f}

<i>🔔 Получишь уведомления по мере исполнения ордеров</i>
"""

            await callback.message.edit_text(success_text, reply_markup=None)
            await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

            logger.info(f"Entry plan registered: {entry_plan.plan_id}, {symbol} {side}")

            await lock_manager.release_lock(user_id)
            await state.clear()
            await callback.answer()
            return

        # ===== LEGACY: ОДИНОЧНЫЙ ENTRY (если нет entry_plan) =====

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

            # Extract EV metrics and class stats from scenario (handle None values)
            ev_metrics = scenario.get("ev_metrics") or {}
            class_stats = scenario.get("class_stats") or {}
            outcome_probs = scenario.get("outcome_probs") or {}

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
                scenario_snapshot=scenario,
                # Syntra metadata
                analysis_id=data.get("analysis_id"),
                primary_archetype=scenario.get("primary_archetype"),
                ev_r=ev_metrics.get("ev_r"),
                ev_grade=ev_metrics.get("ev_grade"),
                scenario_score=ev_metrics.get("scenario_score"),
                class_key=class_stats.get("class_key"),
                class_winrate=class_stats.get("winrate"),
                class_warning=scenario.get("class_warning"),
                prob_sl=outcome_probs.get("sl"),
                prob_tp1=outcome_probs.get("tp1"),
                probs_source=outcome_probs.get("source"),
            )
            await trade_logger.log_trade(trade_record)
            logger.info(f"Trade entry logged for {symbol} @ ${actual_entry_price:.2f} (scenario: {scenario_uuid})")
        except Exception as log_error:
            logger.error(f"Failed to log trade entry: {log_error}")

        # Установить Stop Loss (update_trading_stop сохраняет существующий TP если есть)
        await bybit.update_trading_stop(
            symbol=symbol,
            stop_loss=str(stop_price)
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
            f"❌ <b>Ошибка выполнения:</b>\n\n{html.escape(str(e))}",
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
    user_id = callback.from_user.id
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    symbol = data.get("symbol", "BTCUSDT")
    timeframe = data.get("timeframe", "4h")

    # Если нет сценариев в state - попробовать восстановить из кэша
    if not scenarios:
        cache = get_scenarios_cache()
        cached = cache.get(user_id, symbol, timeframe)
        if cached and cached.scenarios:
            scenarios = cached.scenarios
            # Восстановить в state
            await state.update_data(
                scenarios=scenarios,
                analysis_id=cached.analysis_id,
                current_price=cached.current_price,
                market_context=cached.market_context,
                no_trade=cached.no_trade,
                key_levels=cached.key_levels,
            )

    if not scenarios:
        # Нет сценариев - вернуть к выбору символа
        await state.set_state(AIScenarioStates.choosing_symbol)
        text = "🤖 <b>AI Trading Scenarios</b>\n\n📊 Выбери символ и таймфрейм для анализа:"
        kb = ai_scenarios_kb.get_symbols_keyboard()
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except Exception:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=kb)
    else:
        # Показать список сценариев с market_context
        await state.set_state(AIScenarioStates.viewing_scenarios)

        # Получаем market_context из state
        mc_dict = data.get("market_context", {})
        market_context_obj = None
        if mc_dict:
            market_context_obj = MarketContext(
                trend=mc_dict.get("trend", "neutral"),
                phase=mc_dict.get("phase", ""),
                sentiment=mc_dict.get("sentiment", "neutral"),
                volatility=mc_dict.get("volatility", "medium"),
                bias=mc_dict.get("bias", "neutral"),
                strength=mc_dict.get("strength", 0),
                rsi=mc_dict.get("rsi"),
                funding_rate_pct=mc_dict.get("funding_rate_pct"),
            )

        # Получаем no_trade
        no_trade_dict = data.get("no_trade")
        no_trade_obj = None
        if no_trade_dict and no_trade_dict.get("should_not_trade"):
            no_trade_obj = NoTradeSignal(
                should_not_trade=no_trade_dict.get("should_not_trade", False),
                confidence=no_trade_dict.get("confidence", 0),
                category=no_trade_dict.get("category", ""),
                reasons=no_trade_dict.get("reasons", []),
                wait_for=no_trade_dict.get("wait_for"),
            )

        current_price = data.get("current_price", 0)

        await show_scenarios_list(
            callback.message,
            scenarios,
            symbol,
            timeframe,
            market_context=market_context_obj,
            no_trade=no_trade_obj,
            current_price=current_price
        )

    await callback.answer()


@router.callback_query(F.data == "ai:change_symbol")
async def ai_change_symbol(callback: CallbackQuery, state: FSMContext):
    """Выбрать другой символ (из списка сценариев)"""
    user_id = callback.from_user.id

    # Получить закэшированные пары
    cache = get_scenarios_cache()
    cached_pairs_raw = cache.get_user_cached_pairs(user_id)

    # Конвертировать в формат (symbol, timeframe, age_mins)
    cached_pairs = []
    for symbol, timeframe, cached_at in cached_pairs_raw:
        age_mins = int((datetime.utcnow() - cached_at).total_seconds() / 60)
        cached_pairs.append((symbol, timeframe, age_mins))

    cached_pairs.sort(key=lambda x: x[2])

    await state.set_state(AIScenarioStates.choosing_symbol)

    text = "🤖 <b>AI Trading Scenarios</b>\n\n"
    if cached_pairs:
        text += "📦 <b>Сохранённые сценарии:</b>\n\n"
    text += "📊 Выбери символ и таймфрейм для анализа:"

    await callback.message.edit_text(
        text,
        reply_markup=ai_scenarios_kb.get_symbols_keyboard(cached_pairs)
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
    """Обновить сценарии (инвалидировать кэш и запросить заново)"""
    data = await state.get_data()
    symbol = data.get("symbol", "BTCUSDT")
    timeframe = data.get("timeframe", "4h")
    user_id = callback.from_user.id

    # Инвалидировать кэш
    cache = get_scenarios_cache()
    cache.invalidate(user_id, symbol, timeframe)
    logger.info(f"Cache invalidated for {symbol}:{timeframe}, refreshing...")

    # Сохранить флаг force_refresh в state
    await state.update_data(force_refresh=True)

    # Вызываем ai_analyze_market с явными параметрами symbol и timeframe
    await ai_analyze_market(
        callback, state, settings_storage,
        force_refresh=True,
        symbol=symbol,
        timeframe=timeframe
    )


@router.callback_query(AIScenarioStates.confirmation, F.data.startswith("ai:scenario:"))
async def ai_change_risk_from_confirmation(callback: CallbackQuery, state: FSMContext):
    """Изменить риск из экрана подтверждения - вернуться к выбору риска"""
    scenario_index = int(callback.data.split(":")[2])

    data = await state.get_data()
    scenarios = data.get("scenarios", [])

    if scenario_index >= len(scenarios):
        await callback.answer("❌ Сценарий не найден", show_alert=True)
        return

    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "")
    timeframe = data.get("timeframe", "")
    current_price = data.get("current_price", 0.0)
    market_context = data.get("market_context")
    risk_mode = data.get("risk_mode", "usd")

    await state.update_data(selected_scenario_index=scenario_index)
    await state.set_state(AIScenarioStates.viewing_detail)

    # Показать детали сценария с графиком
    await show_scenario_detail(
        callback.message, scenario, scenario_index,
        symbol=symbol, timeframe=timeframe, current_price=current_price,
        market_context=market_context, user_id=callback.from_user.id,
        risk_mode=risk_mode
    )

    await callback.answer()
