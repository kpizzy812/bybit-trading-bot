"""
Scenario Editor Handler

Хендлеры для редактирования параметров AI сценария перед одобрением.
Позволяет изменить: Entry, Stop Loss, Take Profit, Leverage.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from loguru import logger
from copy import deepcopy

from bot.states.trade_states import AIScenarioStates
from bot.keyboards import ai_scenarios_kb

router = Router()


# ===== Утилиты =====

def get_entry_price(scenario: dict) -> float:
    """Получить среднюю цену входа из сценария"""
    entry = scenario.get("entry", {})
    entry_min = entry.get("price_min", 0)
    entry_max = entry.get("price_max", 0)
    return (entry_min + entry_max) / 2


def get_leverage_value(scenario: dict) -> int:
    """Получить значение leverage из сценария"""
    leverage = scenario.get("leverage", {})
    if isinstance(leverage, dict):
        lev_str = leverage.get("recommended", "5x")
        return int(lev_str.replace("x", ""))
    return int(leverage) if leverage else 5


def get_max_safe_leverage(scenario: dict) -> int:
    """Получить максимально безопасное плечо"""
    leverage = scenario.get("leverage", {})
    if isinstance(leverage, dict):
        max_str = leverage.get("max_safe", "20x")
        return int(max_str.replace("x", ""))
    return 20


async def show_edit_screen(message, scenario: dict, symbol: str):
    """Показать экран редактирования сценария"""
    bias = scenario.get("bias", "long")
    side_emoji = "🟢" if bias == "long" else "🔴"

    entry_price = get_entry_price(scenario)
    stop_price = scenario.get("stop_loss", {}).get("recommended", 0)
    targets = scenario.get("targets", [])
    leverage = get_leverage_value(scenario)

    # Формируем список TP
    tp_lines = []
    for idx, t in enumerate(targets, 1):
        mark = " ✏️" if t.get("overridden") else ""
        tp_lines.append(f"   TP{idx}: ${t['price']:.2f} ({t.get('partial_close_pct', 100)}%){mark}")
    tp_text = "\n".join(tp_lines) if tp_lines else "   Нет уровней"

    # Маркеры изменений
    entry_mark = " ✏️" if scenario.get("entry", {}).get("overridden") else ""
    sl_mark = " ✏️" if scenario.get("stop_loss", {}).get("overridden") else ""
    leverage_data = scenario.get("leverage", {})
    lev_overridden = leverage_data.get("overridden", False) if isinstance(leverage_data, dict) else False
    lev_mark = " ✏️" if lev_overridden else ""

    card = f"""
✏️ <b>Редактирование сценария</b>

{side_emoji} <b>{symbol}</b> {bias.upper()}

<b>Текущие параметры:</b>

⚡ <b>Entry:</b> ${entry_price:.2f}{entry_mark}
🛑 <b>Stop Loss:</b> ${stop_price:.2f}{sl_mark}
🎯 <b>Take Profit:</b>
{tp_text}
📊 <b>Leverage:</b> {leverage}x{lev_mark}

<i>Выбери параметр для редактирования:</i>
"""

    await message.edit_text(
        card,
        reply_markup=ai_scenarios_kb.get_edit_scenario_keyboard(scenario)
    )


# ===== Главный экран редактирования =====

@router.callback_query(AIScenarioStates.confirmation, F.data.startswith("ai:edit_scenario:"))
async def open_edit_screen(callback: CallbackQuery, state: FSMContext):
    """Открыть экран редактирования сценария"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "BTCUSDT")

    # Сохраняем оригинал для возможности сброса
    if "original_scenario" not in data:
        await state.update_data(original_scenario=deepcopy(scenario))

    await state.set_state(AIScenarioStates.editing_scenario)
    await show_edit_screen(callback.message, scenario, symbol)
    await callback.answer()


@router.callback_query(AIScenarioStates.editing_scenario, F.data == "ai:noop")
async def noop_handler(callback: CallbackQuery):
    """Игнорируем нажатие на разделитель"""
    await callback.answer()


@router.callback_query(AIScenarioStates.editing_scenario, F.data == "ai:edit:done")
async def edit_done(callback: CallbackQuery, state: FSMContext, settings_storage):
    """Завершить редактирование и вернуться к подтверждению"""
    # Импортируем здесь чтобы избежать циклических импортов
    from bot.handlers.ai_scenarios import show_trade_confirmation

    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "BTCUSDT")

    user_id = callback.from_user.id
    settings = await settings_storage.get_settings(user_id)

    risk_usd = data.get("risk_usd", 10)
    leverage = data.get("leverage", get_leverage_value(scenario))
    base_risk = data.get("base_risk_usd", risk_usd)
    multiplier = data.get("risk_multiplier", 1.0)

    # Обновляем leverage в state если был изменён
    await state.update_data(leverage=leverage)
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
    await callback.answer()


@router.callback_query(AIScenarioStates.editing_scenario, F.data == "ai:edit:reset")
async def edit_reset(callback: CallbackQuery, state: FSMContext):
    """Сбросить все изменения к оригиналу"""
    data = await state.get_data()
    original = data.get("original_scenario")

    if original:
        scenarios = data.get("scenarios", [])
        scenario_index = data.get("selected_scenario_index", 0)
        scenarios[scenario_index] = deepcopy(original)
        await state.update_data(scenarios=scenarios)

        symbol = data.get("symbol", "BTCUSDT")
        await show_edit_screen(callback.message, scenarios[scenario_index], symbol)
        await callback.answer("Изменения сброшены")
    else:
        await callback.answer("Нет сохранённого оригинала")


# ===== Редактирование Entry =====

@router.callback_query(AIScenarioStates.editing_scenario, F.data == "ai:edit:entry")
async def edit_entry_start(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование Entry Price"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]

    current_entry = get_entry_price(scenario)
    bias = scenario.get("bias", "long")

    await state.set_state(AIScenarioStates.editing_entry)

    await callback.message.edit_text(
        f"⚡ <b>Редактирование Entry Price</b>\n\n"
        f"Текущий Entry: ${current_entry:.2f}\n"
        f"Направление: {bias.upper()}\n\n"
        f"Введи новую цену входа (только число):\n"
        f"Например: <code>{current_entry:.2f}</code>",
        reply_markup=ai_scenarios_kb.get_edit_entry_cancel_keyboard()
    )
    await callback.answer()


@router.message(AIScenarioStates.editing_entry)
async def edit_entry_process(message: Message, state: FSMContext):
    """Обработать введённую цену Entry"""
    try:
        new_entry = float(message.text.strip().replace(",", ".").replace("$", ""))

        if new_entry <= 0:
            raise ValueError("Entry must be positive")

        data = await state.get_data()
        scenarios = data.get("scenarios", [])
        scenario_index = data.get("selected_scenario_index", 0)
        scenario = scenarios[scenario_index]
        symbol = data.get("symbol", "BTCUSDT")

        # Обновляем entry (устанавливаем одинаковые min/max для точной цены)
        scenario["entry"]["price_min"] = new_entry
        scenario["entry"]["price_max"] = new_entry
        scenario["entry"]["overridden"] = True

        await state.update_data(scenarios=scenarios)
        await state.set_state(AIScenarioStates.editing_scenario)

        try:
            await message.delete()
        except Exception:
            pass

        # Отправляем новое сообщение с экраном редактирования
        await message.answer(
            "✅ Entry обновлён",
            reply_markup=None
        )

        # Показываем экран редактирования
        msg = await message.answer("Загрузка...")
        await show_edit_screen(msg, scenario, symbol)

        logger.info(f"User {message.from_user.id} changed entry to ${new_entry:.2f}")

    except ValueError:
        await message.answer(
            "⚠️ Неверный формат цены!\n\n"
            "Введи число, например: <code>95000.50</code>"
        )


@router.callback_query(AIScenarioStates.editing_entry, F.data == "ai:edit:cancel")
async def edit_entry_cancel(callback: CallbackQuery, state: FSMContext):
    """Отменить редактирование Entry"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "BTCUSDT")

    await state.set_state(AIScenarioStates.editing_scenario)
    await show_edit_screen(callback.message, scenario, symbol)
    await callback.answer("Отменено")


# ===== Редактирование Stop Loss =====

@router.callback_query(AIScenarioStates.editing_scenario, F.data == "ai:edit:sl")
async def edit_sl_start(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование Stop Loss"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]

    stop_loss = scenario.get("stop_loss", {})
    current_sl = stop_loss.get("recommended", 0)
    bias = scenario.get("bias", "long")
    entry_price = get_entry_price(scenario)

    await state.set_state(AIScenarioStates.editing_sl)

    sl_direction = "ниже entry" if bias == "long" else "выше entry"

    await callback.message.edit_text(
        f"🛑 <b>Редактирование Stop Loss</b>\n\n"
        f"Текущий SL: ${current_sl:.2f}\n"
        f"Entry: ${entry_price:.2f}\n"
        f"Направление: {bias.upper()}\n\n"
        f"<i>Для {bias.upper()} позиции SL должен быть {sl_direction}</i>\n\n"
        f"Введи новую цену Stop Loss (только число):\n"
        f"Например: <code>{current_sl:.2f}</code>",
        reply_markup=ai_scenarios_kb.get_edit_entry_cancel_keyboard()
    )
    await callback.answer()


@router.message(AIScenarioStates.editing_sl)
async def edit_sl_process(message: Message, state: FSMContext):
    """Обработать введённый SL (из экрана редактирования)"""
    try:
        new_sl = float(message.text.strip().replace(",", ".").replace("$", ""))

        if new_sl <= 0:
            raise ValueError("SL must be positive")

        data = await state.get_data()
        scenarios = data.get("scenarios", [])
        scenario_index = data.get("selected_scenario_index", 0)
        scenario = scenarios[scenario_index]
        symbol = data.get("symbol", "BTCUSDT")

        entry_price = get_entry_price(scenario)
        bias = scenario.get("bias", "long")

        # Валидация направления
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

        # Обновляем SL
        scenario["stop_loss"]["recommended"] = new_sl
        scenario["stop_loss"]["overridden"] = True

        await state.update_data(scenarios=scenarios)
        await state.set_state(AIScenarioStates.editing_scenario)

        try:
            await message.delete()
        except Exception:
            pass

        msg = await message.answer("✅ Stop Loss обновлён")
        await show_edit_screen(msg, scenario, symbol)

        logger.info(f"User {message.from_user.id} changed SL to ${new_sl:.2f}")

    except ValueError:
        await message.answer(
            "⚠️ Неверный формат цены!\n\n"
            "Введи число, например: <code>95000.50</code>"
        )


# ===== Редактирование Take Profit =====

@router.callback_query(AIScenarioStates.editing_scenario, F.data == "ai:edit:tp")
async def edit_tp_list(callback: CallbackQuery, state: FSMContext):
    """Показать список TP уровней для редактирования"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]

    targets = scenario.get("targets", [])
    entry_price = get_entry_price(scenario)

    await state.set_state(AIScenarioStates.editing_tp)

    await callback.message.edit_text(
        f"🎯 <b>Редактирование Take Profit</b>\n\n"
        f"Entry: ${entry_price:.2f}\n\n"
        f"Выбери уровень для редактирования:",
        reply_markup=ai_scenarios_kb.get_edit_tp_keyboard(targets)
    )
    await callback.answer()


@router.callback_query(AIScenarioStates.editing_tp, F.data == "ai:edit:back")
async def edit_tp_back(callback: CallbackQuery, state: FSMContext):
    """Вернуться к главному экрану редактирования"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "BTCUSDT")

    await state.set_state(AIScenarioStates.editing_scenario)
    await show_edit_screen(callback.message, scenario, symbol)
    await callback.answer()


@router.callback_query(AIScenarioStates.editing_tp, F.data.startswith("ai:edit:tp:"))
async def edit_tp_select(callback: CallbackQuery, state: FSMContext):
    """Выбрать TP уровень для редактирования"""
    action = callback.data.split(":")[-1]

    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]
    targets = scenario.get("targets", [])
    entry_price = get_entry_price(scenario)
    bias = scenario.get("bias", "long")

    if action == "add":
        # Добавить новый TP
        if len(targets) >= 5:
            await callback.answer("Максимум 5 уровней TP")
            return

        # Рассчитываем примерную цену для нового TP
        if targets:
            last_tp = targets[-1]["price"]
            diff = abs(last_tp - entry_price) * 0.5
            new_price = last_tp + diff if bias == "long" else last_tp - diff
        else:
            stop_price = scenario.get("stop_loss", {}).get("recommended", entry_price)
            risk = abs(entry_price - stop_price)
            new_price = entry_price + risk * 2 if bias == "long" else entry_price - risk * 2

        await state.update_data(editing_tp_index=-1, suggested_tp_price=new_price)
        await state.set_state(AIScenarioStates.editing_tp_level)

        await callback.message.edit_text(
            f"➕ <b>Добавить новый TP</b>\n\n"
            f"Entry: ${entry_price:.2f}\n\n"
            f"Введи цену и % закрытия через пробел:\n"
            f"Например: <code>{new_price:.2f} 25</code>\n\n"
            f"<i>(цена и процент позиции для закрытия)</i>",
            reply_markup=ai_scenarios_kb.get_edit_tp_level_cancel_keyboard()
        )
    else:
        # Редактировать существующий TP
        tp_index = int(action)
        if tp_index >= len(targets):
            await callback.answer("TP не найден")
            return

        target = targets[tp_index]
        await state.update_data(editing_tp_index=tp_index)
        await state.set_state(AIScenarioStates.editing_tp_level)

        await callback.message.edit_text(
            f"✏️ <b>Редактирование TP{tp_index + 1}</b>\n\n"
            f"Текущая цена: ${target['price']:.2f}\n"
            f"Текущий %: {target.get('partial_close_pct', 100)}%\n"
            f"Entry: ${entry_price:.2f}\n\n"
            f"Введи новую цену и % закрытия через пробел:\n"
            f"Например: <code>{target['price']:.2f} {target.get('partial_close_pct', 100)}</code>\n\n"
            f"<i>(цена и процент позиции для закрытия)</i>",
            reply_markup=ai_scenarios_kb.get_edit_tp_level_cancel_keyboard()
        )

    await callback.answer()


@router.message(AIScenarioStates.editing_tp_level)
async def edit_tp_level_process(message: Message, state: FSMContext):
    """Обработать введённые данные TP уровня"""
    try:
        parts = message.text.strip().replace(",", ".").split()

        if len(parts) < 1:
            raise ValueError("Need at least price")

        new_price = float(parts[0].replace("$", ""))
        new_pct = float(parts[1]) if len(parts) > 1 else 100

        if new_price <= 0:
            raise ValueError("Price must be positive")
        if not 1 <= new_pct <= 100:
            raise ValueError("Percent must be 1-100")

        data = await state.get_data()
        scenarios = data.get("scenarios", [])
        scenario_index = data.get("selected_scenario_index", 0)
        scenario = scenarios[scenario_index]
        targets = scenario.get("targets", [])
        symbol = data.get("symbol", "BTCUSDT")

        entry_price = get_entry_price(scenario)
        stop_price = scenario.get("stop_loss", {}).get("recommended", entry_price)
        bias = scenario.get("bias", "long")

        # Валидация направления TP
        if bias == "long" and new_price <= entry_price:
            await message.answer(
                f"⚠️ <b>Неверный TP для LONG!</b>\n\n"
                f"TP (${new_price:.2f}) должен быть выше entry (${entry_price:.2f})"
            )
            return

        if bias == "short" and new_price >= entry_price:
            await message.answer(
                f"⚠️ <b>Неверный TP для SHORT!</b>\n\n"
                f"TP (${new_price:.2f}) должен быть ниже entry (${entry_price:.2f})"
            )
            return

        # Рассчитываем RR
        risk = abs(entry_price - stop_price)
        reward = abs(new_price - entry_price)
        rr = reward / risk if risk > 0 else 0

        tp_index = data.get("editing_tp_index", -1)

        if tp_index == -1:
            # Добавляем новый TP
            new_tp = {
                "level": len(targets) + 1,
                "price": new_price,
                "partial_close_pct": new_pct,
                "rr": round(rr, 2),
                "overridden": True
            }
            targets.append(new_tp)
        else:
            # Обновляем существующий
            targets[tp_index]["price"] = new_price
            targets[tp_index]["partial_close_pct"] = new_pct
            targets[tp_index]["rr"] = round(rr, 2)
            targets[tp_index]["overridden"] = True

        scenario["targets"] = targets
        await state.update_data(scenarios=scenarios)
        await state.set_state(AIScenarioStates.editing_tp)

        try:
            await message.delete()
        except Exception:
            pass

        # Показываем список TP
        msg = await message.answer("✅ TP обновлён")
        await msg.edit_text(
            f"🎯 <b>Редактирование Take Profit</b>\n\n"
            f"Entry: ${entry_price:.2f}\n\n"
            f"Выбери уровень для редактирования:",
            reply_markup=ai_scenarios_kb.get_edit_tp_keyboard(targets)
        )

        logger.info(f"User {message.from_user.id} updated TP to ${new_price:.2f} ({new_pct}%)")

    except ValueError as e:
        await message.answer(
            "⚠️ Неверный формат!\n\n"
            "Введи цену и процент через пробел:\n"
            "<code>97000 50</code>"
        )


@router.callback_query(AIScenarioStates.editing_tp_level, F.data == "ai:edit:tp:cancel")
async def edit_tp_level_cancel(callback: CallbackQuery, state: FSMContext):
    """Отменить редактирование TP уровня"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]
    targets = scenario.get("targets", [])
    entry_price = get_entry_price(scenario)

    await state.set_state(AIScenarioStates.editing_tp)

    await callback.message.edit_text(
        f"🎯 <b>Редактирование Take Profit</b>\n\n"
        f"Entry: ${entry_price:.2f}\n\n"
        f"Выбери уровень для редактирования:",
        reply_markup=ai_scenarios_kb.get_edit_tp_keyboard(targets)
    )
    await callback.answer("Отменено")


@router.callback_query(AIScenarioStates.editing_tp_level, F.data == "ai:edit:tp:delete")
async def edit_tp_level_delete(callback: CallbackQuery, state: FSMContext):
    """Удалить TP уровень"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]
    targets = scenario.get("targets", [])

    tp_index = data.get("editing_tp_index", -1)

    if tp_index == -1 or tp_index >= len(targets):
        await callback.answer("Нельзя удалить")
        return

    if len(targets) <= 1:
        await callback.answer("Нужен хотя бы один TP")
        return

    # Удаляем TP
    targets.pop(tp_index)

    # Перенумеровываем
    for i, t in enumerate(targets):
        t["level"] = i + 1

    scenario["targets"] = targets
    await state.update_data(scenarios=scenarios)
    await state.set_state(AIScenarioStates.editing_tp)

    entry_price = get_entry_price(scenario)

    await callback.message.edit_text(
        f"🎯 <b>Редактирование Take Profit</b>\n\n"
        f"Entry: ${entry_price:.2f}\n\n"
        f"Выбери уровень для редактирования:",
        reply_markup=ai_scenarios_kb.get_edit_tp_keyboard(targets)
    )
    await callback.answer("TP удалён")


# ===== Редактирование Leverage =====

@router.callback_query(AIScenarioStates.editing_scenario, F.data == "ai:edit:leverage")
async def edit_leverage_start(callback: CallbackQuery, state: FSMContext):
    """Показать выбор Leverage"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]

    current_lev = data.get("leverage", get_leverage_value(scenario))
    max_safe = get_max_safe_leverage(scenario)

    await state.set_state(AIScenarioStates.editing_leverage)

    await callback.message.edit_text(
        f"📊 <b>Редактирование Leverage</b>\n\n"
        f"Текущее плечо: {current_lev}x\n"
        f"Макс. безопасное: {max_safe}x\n\n"
        f"Выбери плечо:",
        reply_markup=ai_scenarios_kb.get_edit_leverage_keyboard(current_lev, max_safe)
    )
    await callback.answer()


@router.callback_query(AIScenarioStates.editing_leverage, F.data == "ai:edit:back")
async def edit_leverage_back(callback: CallbackQuery, state: FSMContext):
    """Вернуться к главному экрану редактирования"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "BTCUSDT")

    await state.set_state(AIScenarioStates.editing_scenario)
    await show_edit_screen(callback.message, scenario, symbol)
    await callback.answer()


@router.callback_query(AIScenarioStates.editing_leverage, F.data.startswith("ai:edit:lev:"))
async def edit_leverage_select(callback: CallbackQuery, state: FSMContext):
    """Выбрать значение Leverage"""
    action = callback.data.split(":")[-1]

    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "BTCUSDT")

    if action == "custom":
        # Ввод custom leverage
        max_safe = get_max_safe_leverage(scenario)
        await callback.message.edit_text(
            f"📊 <b>Custom Leverage</b>\n\n"
            f"Макс. безопасное: {max_safe}x\n\n"
            f"Введи значение плеча (число от 1 до {max_safe}):",
            reply_markup=ai_scenarios_kb.get_edit_entry_cancel_keyboard()
        )
        await callback.answer()
        return

    # Выбрано конкретное значение
    new_lev = int(action)

    # Обновляем leverage в сценарии
    if isinstance(scenario.get("leverage"), dict):
        scenario["leverage"]["recommended"] = f"{new_lev}x"
        scenario["leverage"]["overridden"] = True
    else:
        scenario["leverage"] = {
            "recommended": f"{new_lev}x",
            "max_safe": f"{get_max_safe_leverage(scenario)}x",
            "overridden": True
        }

    await state.update_data(scenarios=scenarios, leverage=new_lev)
    await state.set_state(AIScenarioStates.editing_scenario)

    await show_edit_screen(callback.message, scenario, symbol)
    await callback.answer(f"Leverage: {new_lev}x")


@router.message(AIScenarioStates.editing_leverage)
async def edit_leverage_custom_process(message: Message, state: FSMContext):
    """Обработать введённое custom значение leverage"""
    try:
        new_lev = int(message.text.strip().replace("x", ""))

        data = await state.get_data()
        scenarios = data.get("scenarios", [])
        scenario_index = data.get("selected_scenario_index", 0)
        scenario = scenarios[scenario_index]
        symbol = data.get("symbol", "BTCUSDT")

        max_safe = get_max_safe_leverage(scenario)

        if not 1 <= new_lev <= max_safe:
            await message.answer(
                f"⚠️ Плечо должно быть от 1 до {max_safe}!\n\n"
                f"Введи корректное значение:"
            )
            return

        # Обновляем leverage
        if isinstance(scenario.get("leverage"), dict):
            scenario["leverage"]["recommended"] = f"{new_lev}x"
            scenario["leverage"]["overridden"] = True
        else:
            scenario["leverage"] = {
                "recommended": f"{new_lev}x",
                "max_safe": f"{max_safe}x",
                "overridden": True
            }

        await state.update_data(scenarios=scenarios, leverage=new_lev)
        await state.set_state(AIScenarioStates.editing_scenario)

        try:
            await message.delete()
        except Exception:
            pass

        msg = await message.answer(f"✅ Leverage: {new_lev}x")
        await show_edit_screen(msg, scenario, symbol)

        logger.info(f"User {message.from_user.id} changed leverage to {new_lev}x")

    except ValueError:
        await message.answer(
            "⚠️ Неверный формат!\n\n"
            "Введи число, например: <code>10</code>"
        )


@router.callback_query(AIScenarioStates.editing_leverage, F.data == "ai:edit:cancel")
async def edit_leverage_cancel(callback: CallbackQuery, state: FSMContext):
    """Отменить редактирование Leverage"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "BTCUSDT")

    await state.set_state(AIScenarioStates.editing_scenario)
    await show_edit_screen(callback.message, scenario, symbol)
    await callback.answer("Отменено")


# Обработчик отмены для editing_sl (когда пришли из экрана редактирования)
@router.callback_query(AIScenarioStates.editing_sl, F.data == "ai:edit:cancel")
async def edit_sl_cancel(callback: CallbackQuery, state: FSMContext):
    """Отменить редактирование SL"""
    data = await state.get_data()
    scenarios = data.get("scenarios", [])
    scenario_index = data.get("selected_scenario_index", 0)
    scenario = scenarios[scenario_index]
    symbol = data.get("symbol", "BTCUSDT")

    await state.set_state(AIScenarioStates.editing_scenario)
    await show_edit_screen(callback.message, scenario, symbol)
    await callback.answer("Отменено")
