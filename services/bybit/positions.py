import logging
from typing import Optional, List, Dict
import config
from .client import BybitError

logger = logging.getLogger(__name__)


class PositionsMixin:
    """Миксин для работы с позициями"""

    async def set_leverage(self, symbol: str, leverage: int):
        """Установить плечо для символа"""
        try:
            response = self.client.set_leverage(
                category=config.BYBIT_CATEGORY,
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage)
            )
            self._handle_response(response)
            logger.info(f"Leverage set to {leverage}x for {symbol}")

        except Exception as e:
            logger.error(f"Error setting leverage for {symbol}: {e}")
            raise BybitError(f"Failed to set leverage: {str(e)}")

    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        Получить открытые позиции

        Returns:
            List of positions with info (size, unrealizedPnl, liqPrice, etc.)
        """
        try:
            params = {
                'category': config.BYBIT_CATEGORY,
                'settleCoin': 'USDT'
            }

            if symbol:
                params['symbol'] = symbol

            response = self.client.get_positions(**params)
            result = self._handle_response(response)

            # Фильтруем только активные позиции (size > 0)
            positions = []
            for pos in result.get('list', []):
                size = float(pos.get('size', 0))
                if size > 0:
                    positions.append(pos)

            return positions

        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            raise BybitError(f"Failed to get positions: {str(e)}")

    async def close_position(self, symbol: str):
        """Закрыть позицию Market ордером"""
        try:
            # Получаем позицию
            positions = await self.get_positions(symbol=symbol)

            if not positions:
                raise BybitError(f"No open position for {symbol}")

            position = positions[0]
            size = position.get('size')
            side = position.get('side')  # "Buy" or "Sell"

            # Противоположная сторона для закрытия
            close_side = "Sell" if side == "Buy" else "Buy"

            # Закрываем Market ордером
            await self.place_order(
                symbol=symbol,
                side=close_side,
                order_type="Market",
                qty=size,
                reduce_only=True
            )

            logger.info(f"Position closed for {symbol}")

        except Exception as e:
            logger.error(f"Error closing position: {e}")
            raise BybitError(f"Failed to close position: {str(e)}")
