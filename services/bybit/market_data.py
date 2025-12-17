import logging
from typing import Dict
import config
from .client import BybitError

logger = logging.getLogger(__name__)


class MarketDataMixin:
    """Миксин для работы с рыночными данными"""

    async def get_tickers(self, symbol: str) -> Dict:
        """Получить текущую цену и ticker info"""
        try:
            response = self.client.get_tickers(
                category=config.BYBIT_CATEGORY,
                symbol=symbol
            )
            result = self._handle_response(response)

            if not result.get('list'):
                raise BybitError(f"Symbol {symbol} not found")

            ticker = result['list'][0]

            # CRITICAL: Проверяем что Bybit вернул правильный символ
            returned_symbol = ticker.get('symbol', '')
            if returned_symbol != symbol:
                logger.error(
                    f"SYMBOL MISMATCH in get_tickers! "
                    f"requested={symbol}, returned={returned_symbol}"
                )
                raise BybitError(
                    f"Symbol mismatch: requested {symbol}, got {returned_symbol}"
                )

            return ticker

        except BybitError:
            raise
        except Exception as e:
            logger.error(f"Error getting tickers for {symbol}: {e}")
            raise BybitError(f"Failed to get price: {str(e)}")

    async def get_instrument_info(self, symbol: str) -> Dict:
        """
        Получить информацию об инструменте (lot size, tick size, etc.)

        Returns:
            {
                'lotSizeFilter': {'qtyStep': '0.01', 'minOrderQty': '0.01', 'maxOrderQty': '...'},
                'priceFilter': {'tickSize': '0.01', 'minPrice': '...', 'maxPrice': '...'},
                'leverageFilter': {'minLeverage': '1', 'maxLeverage': '50'},
                ...
            }
        """
        try:
            response = self.client.get_instruments_info(
                category=config.BYBIT_CATEGORY,
                symbol=symbol
            )
            result = self._handle_response(response)

            if not result.get('list'):
                raise BybitError(f"Symbol {symbol} not found")

            instrument = result['list'][0]

            # Проверяем что вернулся правильный символ
            returned_symbol = instrument.get('symbol', '')
            if returned_symbol != symbol:
                logger.error(
                    f"SYMBOL MISMATCH in get_instrument_info! "
                    f"requested={symbol}, returned={returned_symbol}"
                )
                raise BybitError(
                    f"Symbol mismatch: requested {symbol}, got {returned_symbol}"
                )

            return instrument

        except BybitError:
            raise
        except Exception as e:
            logger.error(f"Error getting instrument info for {symbol}: {e}")
            raise BybitError(f"Failed to get instrument info: {str(e)}")

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 100
    ) -> list[dict]:
        """
        Получить OHLC данные (свечи) для символа.

        Args:
            symbol: Торговая пара (BTCUSDT)
            interval: Интервал (1h, 4h, 1d)
            limit: Количество свечей (макс 1000)

        Returns:
            List[dict]: Список свечей с полями:
                - timestamp: Unix timestamp в мс
                - open, high, low, close: Цены
                - volume: Объём
        """
        try:
            # Маппинг timeframe -> pybit interval
            interval_map = {
                "1m": "1",
                "5m": "5",
                "15m": "15",
                "1h": "60",
                "4h": "240",
                "1d": "D",
            }
            pybit_interval = interval_map.get(interval, interval)

            response = self.client.get_kline(
                category=config.BYBIT_CATEGORY,
                symbol=symbol,
                interval=pybit_interval,
                limit=limit
            )
            result = self._handle_response(response)

            klines = []
            for item in result.get('list', []):
                klines.append({
                    'timestamp': int(item[0]),
                    'open': float(item[1]),
                    'high': float(item[2]),
                    'low': float(item[3]),
                    'close': float(item[4]),
                    'volume': float(item[5]),
                })

            # Сортировка по времени (старые первыми)
            klines.sort(key=lambda x: x['timestamp'])
            return klines

        except BybitError:
            raise
        except Exception as e:
            logger.error(f"Error getting klines for {symbol}: {e}")
            raise BybitError(f"Failed to get klines: {str(e)}")
