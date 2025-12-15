"""
Bybit API Client - модульная структура

Разделен на логические модули:
- client.py: Базовый клиент и обработка ошибок
- market_data.py: Получение рыночных данных
- wallet.py: Управление балансом
- orders.py: Работа с ордерами
- positions.py: Управление позициями
- trading_stop.py: SL/TP функционал

Все методы доступны через единый класс BybitClient
"""

from .client import BybitError, BaseBybitClient
from .market_data import MarketDataMixin
from .wallet import WalletMixin
from .orders import OrdersMixin
from .positions import PositionsMixin
from .trading_stop import TradingStopMixin


class BybitClient(
    BaseBybitClient,
    MarketDataMixin,
    WalletMixin,
    OrdersMixin,
    PositionsMixin,
    TradingStopMixin
):
    """
    Полнофункциональный Bybit API клиент

    Объединяет все миксины для работы с:
    - Рыночными данными (tickers, instrument info)
    - Балансом кошелька
    - Ордерами (размещение, отслеживание, отмена)
    - Позициями (открытие, закрытие, управление плечом)
    - SL/TP (single и ladder)
    """
    pass


# Экспорт для обратной совместимости
__all__ = [
    'BybitClient',
    'BybitError',
]
