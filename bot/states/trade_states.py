from aiogram.fsm.state import State, StatesGroup


class AIScenarioStates(StatesGroup):
    """
    FSM States для AI Scenarios (быстрое открытие на основе AI анализа)

    Шаги:
    1. Выбор символа и таймфрейма
    2. Просмотр сценариев от Syntra AI
    3. Выбор сценария
    4. Выбор риска ($5, $10, $20, $50, custom)
    5. Опциональное редактирование параметров
    6. Подтверждение и execute
    """

    choosing_symbol = State()       # Шаг 1: Выбор символа
    choosing_timeframe = State()    # Шаг 2: Выбор таймфрейма
    viewing_scenarios = State()     # Шаг 3: Просмотр сценариев
    viewing_detail = State()        # Шаг 4: Детальный просмотр сценария
    entering_custom_risk = State()  # Шаг 5: Ввод custom риска
    editing_sl = State()            # Шаг 5b: Override SL (кастомный стоп)
    confirmation = State()          # Шаг 6: Подтверждение

    # Редактирование сценария
    editing_scenario = State()      # Экран выбора параметра для редактирования
    editing_entry = State()         # Редактирование Entry Price
    editing_tp = State()            # Редактирование Take Profit
    editing_tp_level = State()      # Редактирование конкретного TP уровня
    editing_leverage = State()      # Редактирование Leverage


class TradeStates(StatesGroup):
    """
    FSM States для Trade Wizard (пошаговое открытие сделки)

    Шаги:
    1. Выбор символа (BTCUSDT, ETHUSDT, etc.)
    2. Выбор направления (Long/Short)
    3. Выбор типа входа (Market/Limit)
    4. Ввод цены входа (если Limit)
    5. Выбор режима стопа (%, цена, AI)
    6. Ввод Stop Loss (в зависимости от режима)
    7. Выбор риска и плеча
    8. Выбор Take Profit режима
    9. Подтверждение сделки
    """

    choosing_symbol = State()       # Шаг 1: Выбор инструмента
    choosing_side = State()         # Шаг 2: Long/Short
    choosing_entry_type = State()   # Шаг 3: Market/Limit
    entering_entry_price = State()  # Шаг 4: Ввод цены (если Limit)
    choosing_stop_mode = State()    # Шаг 5: Режим стопа (%, цена, AI)
    choosing_stop_percent = State() # Шаг 5a: Выбор % (если режим %)
    entering_stop = State()         # Шаг 5b: Ввод стопа вручную (если режим цена)
    choosing_risk_lev = State()     # Шаг 6: Риск и плечо
    choosing_tp = State()           # Шаг 7: Тейк-профит
    confirmation = State()          # Шаг 8: Подтверждение
