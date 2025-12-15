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

            return result['list'][0]

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

            return result['list'][0]

        except Exception as e:
            logger.error(f"Error getting instrument info for {symbol}: {e}")
            raise BybitError(f"Failed to get instrument info: {str(e)}")
