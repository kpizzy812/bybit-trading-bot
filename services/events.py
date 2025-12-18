"""
Event Bus

Простая реализация паттерна Observer для асинхронных событий.
Позволяет избежать циркулярных зависимостей между слоями.

Использование:
    # В services (публикация события)
    from services.events import event_bus, SupervisorAdviceEvent
    await event_bus.emit(SupervisorAdviceEvent(user_id=123, advice=advice_pack))

    # В handlers (подписка на события)
    from services.events import event_bus, SupervisorAdviceEvent

    @event_bus.on(SupervisorAdviceEvent)
    async def handle_advice(event: SupervisorAdviceEvent):
        await send_notification(event.user_id, event.advice)
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict, List, Type, TypeVar

logger = logging.getLogger(__name__)

# Type variable for events
E = TypeVar('E', bound='Event')


@dataclass
class Event:
    """Базовый класс для событий"""
    pass


@dataclass
class SupervisorAdviceEvent(Event):
    """
    Событие: получен совет от Supervisor API.

    Публикуется position_monitor при получении advice_pack.
    Обрабатывается в bot/handlers/supervisor.py для отправки уведомления.
    """
    user_id: int
    advice: Any  # AdvicePack dict


@dataclass
class PositionClosedEvent(Event):
    """
    Событие: позиция закрыта.

    Публикуется position_monitor при обнаружении закрытия позиции.
    Может использоваться для:
    - Отправки feedback в Syntra
    - Обновления статистики
    - Уведомлений
    """
    user_id: int
    symbol: str
    side: str
    pnl: float
    exit_type: str  # 'sl', 'tp', 'manual', 'liquidation'


class EventBus:
    """
    Асинхронный Event Bus.

    Thread-safe реализация паттерна Observer.
    Поддерживает async handlers и graceful error handling.
    """

    def __init__(self):
        self._handlers: Dict[Type[Event], List[Callable]] = {}
        self._lock = asyncio.Lock()

    def on(self, event_type: Type[E]):
        """
        Декоратор для подписки на события.

        Usage:
            @event_bus.on(SupervisorAdviceEvent)
            async def handle_advice(event: SupervisorAdviceEvent):
                ...
        """
        def decorator(handler: Callable[[E], Coroutine]):
            # Регистрируем handler синхронно (декоратор вызывается при импорте)
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)
            logger.debug(f"Handler {handler.__name__} subscribed to {event_type.__name__}")
            return handler
        return decorator

    def subscribe(self, event_type: Type[E], handler: Callable[[E], Coroutine]):
        """
        Подписаться на событие программно (без декоратора).

        Usage:
            event_bus.subscribe(SupervisorAdviceEvent, my_handler)
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)
            logger.debug(f"Handler {handler.__name__} subscribed to {event_type.__name__}")

    def unsubscribe(self, event_type: Type[E], handler: Callable[[E], Coroutine]):
        """Отписаться от события"""
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
                logger.debug(f"Handler {handler.__name__} unsubscribed from {event_type.__name__}")
            except ValueError:
                pass

    async def emit(self, event: Event):
        """
        Опубликовать событие.

        Все подписанные handlers будут вызваны асинхронно.
        Ошибки в handlers логируются, но не прерывают выполнение.
        """
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])

        if not handlers:
            logger.debug(f"No handlers for event {event_type.__name__}")
            return

        logger.debug(f"Emitting {event_type.__name__} to {len(handlers)} handlers")

        # Вызываем все handlers параллельно
        tasks = []
        for handler in handlers:
            tasks.append(self._safe_call(handler, event))

        await asyncio.gather(*tasks)

    async def _safe_call(self, handler: Callable, event: Event):
        """Безопасный вызов handler с логированием ошибок"""
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                f"Error in event handler {handler.__name__} "
                f"for {type(event).__name__}: {e}",
                exc_info=True
            )

    def clear(self):
        """Очистить все подписки (для тестирования)"""
        self._handlers.clear()


# Глобальный singleton
event_bus = EventBus()

__all__ = [
    'Event',
    'SupervisorAdviceEvent',
    'PositionClosedEvent',
    'EventBus',
    'event_bus',
]
