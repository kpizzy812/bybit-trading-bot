import logging
from typing import Optional, List, Dict
import config
from .client import BybitError

logger = logging.getLogger(__name__)


class PositionsMixin:
    """Миксин для работы с позициями"""

    async def set_margin_mode(self, symbol: str, margin_mode: str, leverage: int):
        """
        Установить режим маржи (Isolated/Cross) и плечо для символа

        Args:
            symbol: Торговая пара (например, ETHUSDT)
            margin_mode: "Isolated" или "Cross"
            leverage: Кредитное плечо
        """
        try:
            # Маппинг margin mode в tradeMode для Bybit API
            trade_mode = config.MARGIN_MODE_TO_TRADEMODE.get(margin_mode, 1)  # По умолчанию Isolated

            response = self.client.switch_margin_mode(
                category=config.BYBIT_CATEGORY,
                symbol=symbol,
                tradeMode=trade_mode,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage)
            )
            self._handle_response(response)
            logger.info(f"Margin mode set to {margin_mode} (tradeMode={trade_mode}) with {leverage}x leverage for {symbol}")

        except Exception as e:
            error_str = str(e)
            # Игнорируем ошибки, если режим уже установлен
            if "110025" in error_str or "110043" in error_str or "not modified" in error_str.lower():
                logger.info(f"Margin mode {margin_mode} and leverage {leverage}x already set for {symbol}")
                return

            logger.error(f"Error setting margin mode for {symbol}: {e}")
            raise BybitError(f"Failed to set margin mode: {error_str}")

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
            error_str = str(e)
            # Игнорируем ошибку "leverage not modified" - это не ошибка, leverage уже установлен
            if "110043" in error_str or "leverage not modified" in error_str.lower():
                logger.info(f"Leverage already set to {leverage}x for {symbol}")
                return

            logger.error(f"Error setting leverage for {symbol}: {e}")
            raise BybitError(f"Failed to set leverage: {error_str}")

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

    async def close_position(self, symbol: str, verify: bool = True, max_retries: int = 2):
        """
        Закрыть позицию Market ордером с верификацией

        Args:
            symbol: Торговая пара
            verify: Проверять ли что позиция действительно закрылась
            max_retries: Максимальное количество попыток при неудаче
        """
        import asyncio

        for attempt in range(max_retries + 1):
            try:
                # Получаем позицию
                positions = await self.get_positions(symbol=symbol)

                if not positions:
                    if attempt > 0:
                        # Позиция закрылась после предыдущей попытки
                        logger.info(f"Position for {symbol} confirmed closed")
                        return
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

                # Верификация: проверяем что позиция действительно закрылась
                if verify:
                    await asyncio.sleep(1)  # Даём время на обработку
                    updated_positions = await self.get_positions(symbol=symbol)

                    if updated_positions and float(updated_positions[0].get('size', 0)) > 0:
                        remaining_size = updated_positions[0].get('size')
                        if attempt < max_retries:
                            logger.warning(
                                f"Position still open after close attempt {attempt + 1}: "
                                f"{symbol} size={remaining_size}, retrying..."
                            )
                            continue  # Retry
                        else:
                            raise BybitError(
                                f"Position still open after {max_retries + 1} attempts: "
                                f"{symbol} size={remaining_size}"
                            )

                logger.info(f"Position closed for {symbol}")
                return

            except BybitError:
                raise
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"Close attempt {attempt + 1} failed: {e}, retrying...")
                    await asyncio.sleep(1)
                    continue
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

            # Обновляем SL через update_trading_stop (сохраняет существующий TP)
            await self.update_trading_stop(
                symbol=symbol,
                stop_loss=new_sl_price
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

    async def get_closed_pnl(
        self,
        symbol: str,
        limit: int = 1,
        start_time: Optional[int] = None
    ) -> Optional[Dict]:
        """
        Получить реализованный PnL по закрытым позициям

        Args:
            symbol: Торговая пара
            limit: Количество записей
            start_time: Время начала в мс (опционально)

        Returns:
            Dict с closedPnl или None
        """
        try:
            params = {
                'category': config.BYBIT_CATEGORY,
                'symbol': symbol,
                'limit': limit
            }

            if start_time:
                params['startTime'] = start_time

            response = self.client.get_closed_pnl(**params)
            result = self._handle_response(response)

            records = result.get('list', [])
            if not records:
                return None

            return records[0] if limit == 1 else records

        except Exception as e:
            logger.error(f"Error getting closed PnL for {symbol}: {e}")
            return None
