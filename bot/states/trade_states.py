from aiogram.fsm.state import State, StatesGroup


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
