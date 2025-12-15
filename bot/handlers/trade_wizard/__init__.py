"""
Trade Wizard - Модульный FSM для открытия сделки

Архитектура:
- utils.py - утилиты (расчёты)
- navigation.py - Cancel/Back
- symbol_side.py - шаги 1-2
- entry.py - шаги 3-4
- stop.py - шаг 5 (режим стопа, %, вручную)
- risk_leverage.py - шаг 6
- take_profit.py - шаг 7
- confirmation.py - шаг 8

Все модули имеют свои роутеры, которые собираются здесь в main_router
"""
from aiogram import Router

# Импортируем все роутеры из модулей
from . import navigation
from . import symbol_side
from . import entry
from . import stop
from . import risk_leverage
from . import take_profit
from . import confirmation

# Создаём главный router для Trade Wizard
router = Router(name="trade_wizard")

# Включаем все sub-роутеры в порядке приоритета
# Navigation должен быть первым (обрабатывает cancel/back)
router.include_router(navigation.router)

# Затем все шаги в логическом порядке
router.include_router(symbol_side.router)
router.include_router(entry.router)
router.include_router(stop.router)
router.include_router(risk_leverage.router)
router.include_router(take_profit.router)
router.include_router(confirmation.router)

# Экспортируем главный router
__all__ = ['router']
