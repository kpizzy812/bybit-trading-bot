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

    async def partial_close(self, symbol: str, percent: float):
        """
        Частично закрыть позицию (процент от текущего размера)

        Args:
            symbol: Торговая пара
            percent: Процент для закрытия (0-100)

        Example:
            await client.partial_close('SOLUSDT', 50)  # Закрыть 50%
        """
        try:
            if not (0 < percent <= 100):
                raise BybitError(f"Percent must be between 0 and 100, got {percent}")

            # Получаем позицию
            positions = await self.get_positions(symbol=symbol)

            if not positions:
                raise BybitError(f"No open position for {symbol}")

            position = positions[0]
            size = float(position.get('size', 0))
            side = position.get('side')  # "Buy" or "Sell"

            # Рассчитываем размер для закрытия
            close_qty = size * (percent / 100)

            # Получаем instrument info для округления
            instrument = await self.get_instrument_info(symbol)
            qty_step = float(instrument.get('lotSizeFilter', {}).get('qtyStep', '0.01'))

            # Округляем qty
            from decimal import Decimal, ROUND_DOWN
            qty_dec = Decimal(str(close_qty))
            step_dec = Decimal(str(qty_step))
            rounded_qty = (qty_dec / step_dec).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_dec
            close_qty_str = str(rounded_qty)

            # Противоположная сторона для закрытия
            close_side = "Sell" if side == "Buy" else "Buy"

            # Закрываем Market ордером
            await self.place_order(
                symbol=symbol,
                side=close_side,
                order_type="Market",
                qty=close_qty_str,
                reduce_only=True
            )

            logger.info(f"Partial close {percent}% for {symbol}: {close_qty_str} / {size}")
            return {
                'closed_qty': close_qty_str,
                'total_size': size,
                'percent': percent
            }

        except Exception as e:
            logger.error(f"Error partial closing position: {e}")
            raise BybitError(f"Failed to partial close: {str(e)}")

    async def move_sl(self, symbol: str, new_sl_price: str):
        """
        Переместить Stop Loss на позиции

        Args:
            symbol: Торговая пара
            new_sl_price: Новая цена стоп-лосса (строка для точности)

        Example:
            await client.move_sl('SOLUSDT', '135.00')
        """
        try:
            # Получаем позицию для валидации
            positions = await self.get_positions(symbol=symbol)

            if not positions:
                raise BybitError(f"No open position for {symbol}")

            position = positions[0]
            side = position.get('side')  # "Buy" or "Sell"
            entry_price = float(position.get('avgPrice', 0))
            new_sl = float(new_sl_price)

            # Валидация: SL должен быть в правильном направлении
            if side == "Buy":
                # Long: SL должен быть ниже входа
                if new_sl >= entry_price:
                    raise BybitError(
                        f"For Long position, SL must be below entry price "
                        f"(entry: ${entry_price:.4f}, new SL: ${new_sl:.4f})"
                    )
            else:
                # Short: SL должен быть выше входа
                if new_sl <= entry_price:
                    raise BybitError(
                        f"For Short position, SL must be above entry price "
                        f"(entry: ${entry_price:.4f}, new SL: ${new_sl:.4f})"
                    )

            # Обновляем SL через set_trading_stop
            await self.set_trading_stop(
                symbol=symbol,
                stop_loss=new_sl_price,
                sl_trigger_by="MarkPrice"
            )

            logger.info(f"Stop Loss moved for {symbol}: ${new_sl_price}")
            return {
                'symbol': symbol,
                'new_sl': new_sl_price,
                'entry_price': entry_price
            }

        except Exception as e:
            logger.error(f"Error moving SL: {e}")
            raise BybitError(f"Failed to move SL: {str(e)}")
