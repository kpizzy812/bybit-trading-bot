"""
Базовые обработчики для кнопок главного меню
"""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from bot.states.trade_states import TradeStates
from bot.keyboards.main_menu import get_main_menu
import config

router = Router()


@router.message(F.text == "➕ Открыть сделку")
async def open_trade_handler(message: Message, state: FSMContext):
    """Запуск Trade Wizard"""
    # Импорт здесь для избежания circular import
    from bot.keyboards.trade_kb import get_symbol_keyboard

    await state.set_state(TradeStates.choosing_symbol)

    await message.answer(
        "📊 <b>Выбери инструмент для торговли:</b>\n\n"
        f"Доступные символы: {', '.join(config.SUPPORTED_SYMBOLS)}",
        reply_markup=get_symbol_keyboard()
    )


@router.message(F.text == "📊 Позиции")
async def positions_handler(message: Message, settings_storage, lock_manager, entry_plan_monitor=None):
    """Показать открытые позиции, ордера и Entry Plans"""
    from bot.keyboards.positions_kb import get_positions_with_plans_kb, get_empty_positions_kb

    # Получаем настройки пользователя
    user_settings = await settings_storage.get_settings(message.from_user.id)
    testnet = user_settings.testnet_mode

    try:
        from services.bybit import BybitClient

        client = BybitClient(testnet=testnet)
        positions = await client.get_positions()
        all_orders = await client.get_open_orders()

        # Фильтруем только entry ордера (не reduce_only, не entry plan ордера)
        orders = []
        for o in all_orders:
            if o.get('reduceOnly', False):
                continue
            # Исключаем ордера Entry Plans (начинаются с EP:)
            order_link_id = o.get('orderLinkId', '')
            if order_link_id.startswith('EP:'):
                continue
            orders.append(o)

        # Получаем активные Entry Plans для пользователя
        entry_plans = []
        if entry_plan_monitor:
            user_id = message.from_user.id
            for plan_id, plan in entry_plan_monitor.active_plans.items():
                if plan.user_id == user_id:
                    entry_plans.append({
                        'plan_id': plan_id,
                        'symbol': plan.symbol,
                        'side': plan.side,
                        'status': plan.status,
                        'fill_percentage': plan.fill_percentage,
                        'mode': plan.mode
                    })

        if not positions and not orders and not entry_plans:
            await message.answer(
                "📊 <b>Открытых позиций и ордеров нет</b>\n\n"
                "Используй <b>➕ Открыть сделку</b> чтобы начать торговлю",
                reply_markup=get_empty_positions_kb()
            )
            return

        text = ""

        # Позиции
        if positions:
            text += "📊 <b>Открытые позиции:</b>\n\n"
            for pos in positions:
                symbol = pos.get('symbol')
                side = pos.get('side')  # Buy/Sell
                size = float(pos.get('size', 0))
                entry_price = float(pos.get('avgPrice', 0))
                mark_price = float(pos.get('markPrice', 0))
                unrealized_pnl = float(pos.get('unrealisedPnl', 0))
                leverage = pos.get('leverage', '?')
                liq_price = pos.get('liqPrice', 'N/A')

                # Рассчитываем ROE%
                roe = 0
                if entry_price > 0:
                    roe = (unrealized_pnl / (size * entry_price)) * float(leverage) * 100

                # Эмодзи для направления
                side_emoji = "🟢" if side == "Buy" else "🔴"
                pnl_emoji = "💰" if unrealized_pnl >= 0 else "📉"

                text += (
                    f"{side_emoji} <b>{symbol}</b> {side}\n"
                    f"  Size: {size} | Leverage: {leverage}x\n"
                    f"  Entry: ${entry_price:.4f} | Mark: ${mark_price:.4f}\n"
                    f"  {pnl_emoji} PnL: ${unrealized_pnl:.2f} ({roe:+.2f}%)\n"
                    f"  Liq: ${liq_price}\n\n"
                )

        # Entry Plans
        if entry_plans:
            text += "📋 <b>Активные Entry Plans:</b>\n\n"
            for ep in entry_plans:
                side_emoji = "🟢" if ep['side'] == "Long" else "🔴"
                status_emoji = "🔄" if ep['status'] == "partial" else "📋"
                text += (
                    f"{status_emoji} {side_emoji} <b>{ep['symbol']}</b> {ep['mode'].upper()}\n"
                    f"   Filled: {ep['fill_percentage']:.0f}%\n\n"
                )

        # Ордера (не Entry Plan)
        if orders:
            text += "⏳ <b>Ожидающие ордера:</b>\n\n"
            for order in orders:
                symbol = order.get('symbol')
                side = order.get('side')
                price = float(order.get('price', 0))
                qty = order.get('qty', '0')
                order_type = order.get('orderType', 'Limit')

                side_emoji = "🟢" if side == "Buy" else "🔴"

                text += (
                    f"⏳ {side_emoji} <b>{symbol}</b> {side}\n"
                    f"   {order_type} @ ${price:.4f}\n"
                    f"   Qty: {qty}\n\n"
                )

        text += "💡 <i>Нажми для управления</i>"

        # Inline кнопки для управления
        await message.answer(text, reply_markup=get_positions_with_plans_kb(positions, orders, entry_plans))

    except Exception as e:
        await message.answer(
            f"❌ Ошибка при получении позиций:\n{str(e)}",
            reply_markup=get_main_menu()
        )


@router.message(F.text == "⚙️ Настройки")
async def settings_handler(message: Message, settings_storage):
    """Показать меню настроек"""
    from bot.keyboards.settings_kb import get_settings_menu_kb

    user_settings = await settings_storage.get_settings(message.from_user.id)

    # Формируем текст с текущими настройками
    testnet_mode = user_settings.testnet_mode
    default_risk = user_settings.default_risk_usd
    default_leverage = user_settings.default_leverage
    default_margin_mode = user_settings.default_margin_mode
    shorts_enabled = user_settings.shorts_enabled
    default_tp_mode = user_settings.default_tp_mode

    mode_text = "🧪 <b>Testnet</b>" if testnet_mode else "🔴 <b>Live Trading</b>"
    shorts_text = "✅ Включены" if shorts_enabled else "❌ Выключены"

    text = f"""
⚙️ <b>Настройки бота</b>

<b>Текущие параметры:</b>

🌐 Режим: {mode_text}
💰 Дефолтный риск: ${default_risk}
📊 Дефолтное плечо: {default_leverage}x
🔀 Режим маржи: {default_margin_mode}
🔴 Шорты: {shorts_text}
🎯 TP режим: {default_tp_mode}

<b>Лимиты безопасности:</b>
🛡 Макс. риск на сделку: ${user_settings.max_risk_per_trade}
🛡 Макс. маржа на сделку: ${user_settings.max_margin_per_trade}

💡 Выбери категорию для изменения:
"""

    await message.answer(text.strip(), reply_markup=get_settings_menu_kb())


@router.message(F.text == "🧾 История")
async def history_handler(message: Message):
    """Показать историю сделок"""
    from bot.keyboards.history_kb import get_history_main_kb

    text = """
🧾 <b>История сделок</b>

Здесь ты можешь:
• Просмотреть закрытые сделки
• Проанализировать статистику
• Отфильтровать по символам

Выбери действие ниже:
"""

    await message.answer(
        text.strip(),
        reply_markup=get_history_main_kb()
    )


@router.message(F.text == "🧪 Testnet/Live")
async def toggle_mode_handler(message: Message, settings_storage):
    """Переключение между Testnet и Live режимами"""
    user_id = message.from_user.id
    user_settings = await settings_storage.get_settings(user_id)

    # Текущий режим
    current_testnet = user_settings.testnet_mode

    # Переключаем
    new_testnet = not current_testnet

    # Сохраняем
    await settings_storage.update_setting(user_id, 'testnet_mode', new_testnet)

    # Сообщение
    if new_testnet:
        await message.answer(
            "🧪 <b>Testnet режим ВКЛЮЧЕН</b>\n\n"
            "✅ Все сделки будут выполняться на testnet\n"
            "✅ Используй testnet баланс для тестирования\n"
            "✅ Реальные деньги не затрагиваются\n\n"
            "⚠️ Убедись, что в .env установлены BYBIT_TESTNET_API_KEY и BYBIT_TESTNET_API_SECRET",
            reply_markup=get_main_menu()
        )
    else:
        await message.answer(
            "🔴 <b>LIVE TRADING режим ВКЛЮЧЕН</b>\n\n"
            "⚠️⚠️⚠️ <b>ВНИМАНИЕ!</b> ⚠️⚠️⚠️\n\n"
            "Сейчас используется РЕАЛЬНЫЙ баланс!\n"
            "Все сделки будут выполняться с реальными деньгами!\n\n"
            "✅ Убедись, что твой API ключ имеет ТОЛЬКО права Trade (БЕЗ Withdraw!)\n"
            "✅ Проверь лимиты безопасности в настройках\n"
            "✅ Начни с малых позиций\n\n"
            "Используй <b>🧪 Testnet/Live</b> чтобы вернуться в testnet",
            reply_markup=get_main_menu()
        )
