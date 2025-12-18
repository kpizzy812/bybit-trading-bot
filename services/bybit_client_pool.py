"""
Bybit Client Pool

Единый пул клиентов Bybit для всех сервисов.
Обеспечивает lazy initialization и переиспользование клиентов.
"""
from typing import Dict
from services.bybit import BybitClient


class BybitClientPool:
    """
    Singleton-пул Bybit клиентов.

    Каждый режим (testnet/live) имеет свой клиент.
    Клиенты создаются лениво при первом запросе.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._clients: Dict[bool, BybitClient] = {}
        return cls._instance

    def get_client(self, testnet: bool = False) -> BybitClient:
        """
        Получить Bybit клиент для нужного режима.

        Args:
            testnet: True для testnet, False для live

        Returns:
            BybitClient: Клиент для указанного режима
        """
        if testnet not in self._clients:
            self._clients[testnet] = BybitClient(testnet=testnet)
        return self._clients[testnet]

    def clear(self):
        """Очистить пул (для тестов)"""
        self._clients.clear()


# Глобальный экземпляр
client_pool = BybitClientPool()
