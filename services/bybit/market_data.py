import logging
from typing import Dict, List, Optional
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

    async def get_all_tickers(self) -> List[Dict]:
        """
        Получить тикеры ВСЕХ инструментов (без symbol).

        Returns:
            List[Dict]: Список тикеров с полями:
                - symbol: Символ (BTCUSDT)
                - lastPrice: Последняя цена
                - price24hPcnt: Изменение за 24h (доля, не %)
                - highPrice24h, lowPrice24h: Диапазон 24h
                - turnover24h: Объём в USD за 24h
                - volume24h: Объём в базовой валюте
                - bid1Price, ask1Price: Лучшие bid/ask
        """
        try:
            response = self.client.get_tickers(
                category=config.BYBIT_CATEGORY
                # Без symbol = все тикеры
            )
            result = self._handle_response(response)
            return result.get('list', [])

        except BybitError:
            raise
        except Exception as e:
            logger.error(f"Error getting all tickers: {e}")
            raise BybitError(f"Failed to get all tickers: {str(e)}")

    async def get_all_instruments(
        self,
        status: Optional[str] = "Trading",
        quote_coin: Optional[str] = "USDT"
    ) -> List[Dict]:
        """
        Получить все инструменты с фильтрацией.

        Args:
            status: Фильтр по статусу (Trading, Settling, Closed)
            quote_coin: Фильтр по quote валюте (USDT, USDC)

        Returns:
            List[Dict]: Список инструментов с полями:
                - symbol: Символ
                - status: Статус (Trading)
                - quoteCoin: Quote валюта (USDT)
                - baseCoin: Base валюта (BTC)
                - contractType: Тип (LinearPerpetual)
                - lotSizeFilter, priceFilter, leverageFilter
        """
        try:
            response = self.client.get_instruments_info(
                category=config.BYBIT_CATEGORY
                # Без symbol = все инструменты
            )
            result = self._handle_response(response)
            instruments = result.get('list', [])

            # Фильтрация
            if status:
                instruments = [i for i in instruments if i.get('status') == status]
            if quote_coin:
                instruments = [i for i in instruments if i.get('quoteCoin') == quote_coin]

            logger.info(f"Fetched {len(instruments)} instruments (status={status}, quote={quote_coin})")
            return instruments

        except BybitError:
            raise
        except Exception as e:
            logger.error(f"Error getting all instruments: {e}")
            raise BybitError(f"Failed to get all instruments: {str(e)}")
