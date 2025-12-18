"""
Состояния FSM для управления позициями
"""
from aiogram.fsm.state import State, StatesGroup


class PositionStates(StatesGroup):
    """Состояния для управления позициями"""
    entering_new_sl = State()  # Ввод новой цены SL
    entering_tp_price = State()  # Ввод цены TP
    entering_tp_percent = State()  # Ввод кастомного % объёма
