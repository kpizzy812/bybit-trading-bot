import asyncio
import time
import logging
from typing import Optional, Dict, List
from pybit.unified_trading import HTTP
import config

logger = logging.getLogger(__name__)


class BybitError(Exception):
    """Custom exception for Bybit API errors"""
    pass


class BybitClient:
    """
    Wrapper для Bybit API V5 (Unified Trading)
    Поддерживает testnet/live режимы
    """

    def __init__(self, testnet: bool = True):
        self.testnet = testnet

        # Используем функцию get_bybit_keys для получения ключей
        api_key, api_secret = config.get_bybit_keys(testnet)

        if not api_key or not api_secret:
            raise ValueError(
                f"Bybit API credentials not found for {'testnet' if testnet else 'live'} mode. "
                "Please set them in .env file."
            )

        self.client = HTTP(
            testnet=testnet,
            api_key=api_key,
            api_secret=api_secret
        )

        logger.info(f"Bybit client initialized ({'testnet' if testnet else 'live'} mode)")

    def _handle_response(self, response: Dict) -> Dict:
        """Обработка ответа от Bybit API"""
        ret_code = response.get('retCode', -1)
        ret_msg = response.get('retMsg', 'Unknown error')

        if ret_code != 0:
            # Типичные ошибки
            error_lower = ret_msg.lower()

            if "insufficient" in error_lower or "balance" in error_lower:
                raise BybitError("💸 Insufficient balance")
            elif "duplicate" in error_lower or "exists" in error_lower:
                raise BybitError("⚠️ Order already placed")
            elif "invalid" in error_lower:
                raise BybitError(f"❌ Invalid parameters: {ret_msg}")
            else:
                raise BybitError(f"❌ Bybit API error: {ret_msg}")

        return response.get('result', {})

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

    async def get_wallet_balance(self) -> Dict:
        """
        Получить баланс кошелька

        Returns:
            {
                'totalEquity': '1000.00',
                'availableBalance': '950.00',
                'totalWalletBalance': '1000.00',
                ...
            }
        """
        try:
            response = self.client.get_wallet_balance(
                accountType="UNIFIED"  # V5 API uses UNIFIED account
            )
            result = self._handle_response(response)

            # Ищем USDT баланс
            for coin in result.get('list', [{}])[0].get('coin', []):
                if coin.get('coin') == 'USDT':
                    return coin

            raise BybitError("USDT balance not found")

        except Exception as e:
            logger.error(f"Error getting wallet balance: {e}")
            raise BybitError(f"Failed to get balance: {str(e)}")

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

    async def place_order(
        self,
        symbol: str,
        side: str,  # "Buy" or "Sell"
        order_type: str,  # "Market" or "Limit"
        qty: str,
        price: Optional[str] = None,
        client_order_id: Optional[str] = None,
        reduce_only: bool = False,
        close_on_trigger: bool = False
    ) -> Dict:
        """
        Разместить ордер

        Returns:
            {'orderId': '...', 'orderLinkId': '...', ...}
        """
        try:
            params = {
                'category': config.BYBIT_CATEGORY,
                'symbol': symbol,
                'side': side,
                'orderType': order_type,
                'qty': qty,
                'positionIdx': config.BYBIT_POSITION_IDX,
            }

            if price:
                params['price'] = price

            if client_order_id:
                params['orderLinkId'] = client_order_id[:36]  # Max 36 chars

            if reduce_only:
                params['reduceOnly'] = True

            if close_on_trigger:
                params['closeOnTrigger'] = True

            response = self.client.place_order(**params)
            result = self._handle_response(response)

            logger.info(f"Order placed: {order_type} {side} {qty} {symbol} @ {price or 'market'}")
            return result

        except Exception as e:
            logger.error(f"Error placing order: {e}")
            raise

    async def get_order(self, symbol: str, order_id: Optional[str] = None, client_order_id: Optional[str] = None) -> Dict:
        """Получить информацию об ордере"""
        try:
            params = {
                'category': config.BYBIT_CATEGORY,
                'symbol': symbol,
            }

            if order_id:
                params['orderId'] = order_id
            elif client_order_id:
                params['orderLinkId'] = client_order_id
            else:
                raise ValueError("Either order_id or client_order_id must be provided")

            response = self.client.get_open_orders(**params)
            result = self._handle_response(response)

            if not result.get('list'):
                # Попробовать в истории
                response = self.client.get_order_history(**params, limit=1)
                result = self._handle_response(response)

            if not result.get('list'):
                raise BybitError("Order not found")

            return result['list'][0]

        except Exception as e:
            logger.error(f"Error getting order: {e}")
            raise BybitError(f"Failed to get order: {str(e)}")

    async def wait_until_filled(
        self,
        symbol: str,
        order_id: str,
        timeout: int = config.MARKET_ORDER_TIMEOUT,
        poll_interval: float = config.MARKET_ORDER_POLL_INTERVAL
    ) -> Dict:
        """
        Ждёт заполнения ордера с retry

        Returns: order info with avgPrice
        Raises: TimeoutError if not filled, Exception if rejected/cancelled
        """
        start = time.time()
        attempts = 0

        while time.time() - start < timeout:
            attempts += 1

            try:
                order = await self.get_order(symbol=symbol, order_id=order_id)

                status = order.get('orderStatus')
                avg_price = float(order.get('avgPrice', 0))

                # Заполнен и avgPrice обновился
                if status == 'Filled' and avg_price > 0:
                    logger.info(f"Order {order_id} filled at avg price {avg_price} (attempt {attempts})")
                    return order

                # Отменён или отклонён
                if status in ['Cancelled', 'Rejected']:
                    reason = order.get('rejectReason', 'unknown')
                    raise BybitError(f"Order {status}: {reason}")

                # Retry
                await asyncio.sleep(poll_interval)

            except BybitError:
                raise
            except Exception as e:
                logger.warning(f"Attempt {attempts} failed: {e}")
                await asyncio.sleep(poll_interval)

        # Timeout - отменяем ордер
        logger.error(f"Order {order_id} not filled within {timeout}s, cancelling...")
        try:
            await self.cancel_order(symbol=symbol, order_id=order_id)
        except:
            pass

        raise TimeoutError(f"Order not filled within {timeout}s")

    async def cancel_order(self, symbol: str, order_id: Optional[str] = None, client_order_id: Optional[str] = None):
        """Отменить ордер"""
        try:
            params = {
                'category': config.BYBIT_CATEGORY,
                'symbol': symbol,
            }

            if order_id:
                params['orderId'] = order_id
            elif client_order_id:
                params['orderLinkId'] = client_order_id
            else:
                raise ValueError("Either order_id or client_order_id must be provided")

            response = self.client.cancel_order(**params)
            self._handle_response(response)

            logger.info(f"Order cancelled: {order_id or client_order_id}")

        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            raise BybitError(f"Failed to cancel order: {str(e)}")

    async def set_trading_stop(
        self,
        symbol: str,
        stop_loss: Optional[str] = None,
        take_profit: Optional[str] = None,
        sl_trigger_by: str = "MarkPrice",
        tp_trigger_by: str = "MarkPrice"
    ):
        """
        Установить SL/TP на позицию

        Args:
            stop_loss: Цена стоп-лосса
            take_profit: Цена тейк-профита
            sl_trigger_by: "MarkPrice" или "LastPrice"
            tp_trigger_by: "MarkPrice" или "LastPrice"
        """
        try:
            params = {
                'category': config.BYBIT_CATEGORY,
                'symbol': symbol,
                'positionIdx': config.BYBIT_POSITION_IDX,
                'tpslMode': 'Full',  # Full = SL/TP на всю позицию
            }

            if stop_loss:
                params['stopLoss'] = stop_loss
                params['slTriggerBy'] = sl_trigger_by

            if take_profit:
                params['takeProfit'] = take_profit
                params['tpTriggerBy'] = tp_trigger_by

            response = self.client.set_trading_stop(**params)
            self._handle_response(response)

            logger.info(f"Trading stop set for {symbol}: SL={stop_loss}, TP={take_profit}")

        except Exception as e:
            logger.error(f"Error setting trading stop: {e}")
            raise BybitError(f"Failed to set SL/TP: {str(e)}")

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
