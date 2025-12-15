import asyncio
import time
import logging
from typing import Optional, Dict
import config
from .client import BybitError

logger = logging.getLogger(__name__)


class OrdersMixin:
    """Миксин для работы с ордерами"""

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
