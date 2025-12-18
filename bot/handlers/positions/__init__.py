"""
Positions Handler Module

Обработчики для управления позициями, ордерами и Entry Plans.
"""
from aiogram import Router

from bot.handlers.positions.states import PositionStates
from bot.handlers.positions.list_handlers import router as list_router
from bot.handlers.positions.detail_handlers import router as detail_router
from bot.handlers.positions.action_handlers import router as action_router
from bot.handlers.positions.entry_plan_handlers import router as entry_plan_router

# Создаём главный роутер
router = Router()

# Включаем все суб-роутеры
router.include_router(list_router)
router.include_router(detail_router)
router.include_router(action_router)
router.include_router(entry_plan_router)

__all__ = ['router', 'PositionStates']
