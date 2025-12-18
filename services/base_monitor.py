"""
Base Monitor - абстрактный базовый класс для всех мониторов.

Обеспечивает общий паттерн:
- start() / stop() lifecycle
- _monitor_loop() с обработкой ошибок
- Абстрактный _check_cycle() для переопределения
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class BaseMonitor(ABC):
    """
    Абстрактный базовый класс для мониторов.

    Наследники должны реализовать:
    - _check_cycle() - основная логика проверки
    - monitor_name (property) - имя для логов
    """

    def __init__(self, check_interval: int = 10):
        self.check_interval = check_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None

    @property
    @abstractmethod
    def monitor_name(self) -> str:
        """Имя монитора для логов"""
        pass

    @abstractmethod
    async def _check_cycle(self):
        """
        Основная логика проверки.
        Вызывается каждый цикл мониторинга.
        """
        pass

    async def _on_start(self):
        """Hook: вызывается при запуске монитора"""
        pass

    async def _on_stop(self):
        """Hook: вызывается при остановке монитора"""
        pass

    async def start(self):
        """Запустить мониторинг в фоновом режиме"""
        if self._running:
            logger.warning(f"{self.monitor_name} already running")
            return

        self._running = True
        await self._on_start()
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"{self.monitor_name} started (interval: {self.check_interval}s)")

    async def stop(self):
        """Остановить мониторинг"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._on_stop()
        logger.info(f"{self.monitor_name} stopped")

    async def _monitor_loop(self):
        """Основной цикл мониторинга"""
        while self._running:
            try:
                await self._check_cycle()
            except Exception as e:
                logger.error(f"Error in {self.monitor_name} loop: {e}", exc_info=True)

            await asyncio.sleep(self.check_interval)

    @property
    def is_running(self) -> bool:
        """Проверить, запущен ли монитор"""
        return self._running
