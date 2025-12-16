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
        close_on_trigger: bool = False,
        stop_loss: Optional[str] = None,
        take_profit: Optional[str] = None,
        sl_trigger_by: Optional[str] = None,  # Auto: LastPrice on testnet, MarkPrice on mainnet
        tp_trigger_by: Optional[str] = None,  # Auto: LastPrice on testnet, MarkPrice on mainnet
        time_in_force: Optional[str] = None,
        post_only: Optional[bool] = None
    ) -> Dict:
        """
        Разместить ордер

        Args:
            stop_loss: Цена стоп-лосса (опционально)
            take_profit: Цена тейк-профита (опционально)
            sl_trigger_by: Тип триггера SL (MarkPrice, LastPrice, IndexPrice)
            tp_trigger_by: Тип триггера TP (MarkPrice, LastPrice, IndexPrice)
            time_in_force: GTC (по умолчанию), IOC, FOK
            post_only: True = только maker, False = может быть taker (для ladder TP рекомендуется False)

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
                # Max 36 chars, но сохраняем конец (суффикс _tp1, _tp2 важен)
                if len(client_order_id) > 36:
                    # Обрезаем UUID часть, сохраняя суффикс
                    params['orderLinkId'] = client_order_id[:30] + client_order_id[-6:]
                else:
                    params['orderLinkId'] = client_order_id

            if reduce_only:
                params['reduceOnly'] = True

            if close_on_trigger:
                params['closeOnTrigger'] = True

            # Time in force (для limit ордеров)
            if time_in_force:
                params['timeInForce'] = time_in_force

            # Post-only (для maker-only ордеров)
            if post_only is not None:
                params['postOnlyOrder'] = post_only

            # SL/TP для ордера (будет активирован при исполнении)
            # На testnet используем LastPrice (Mark Price там часто битый)
            # На mainnet используем MarkPrice (более стабильный)
            default_trigger = "LastPrice" if self.testnet else "MarkPrice"

            if stop_loss:
                params['stopLoss'] = stop_loss
                params['slTriggerBy'] = sl_trigger_by or default_trigger

            if take_profit:
                params['takeProfit'] = take_profit
                params['tpTriggerBy'] = tp_trigger_by or default_trigger

            response = self.client.place_order(**params)
            result = self._handle_response(response)

            sl_tp_info = ""
            if stop_loss:
                sl_tp_info += f" SL={stop_loss}"
            if take_profit:
                sl_tp_info += f" TP={take_profit}"

            logger.info(f"Order placed: {order_type} {side} {qty} {symbol} @ {price or 'market'}{sl_tp_info}")
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

    async def get_open_orders(self, symbol: Optional[str] = None) -> list:
        """
        Получить все открытые ордера (лимитные ордера ожидающие исполнения)

        Args:
            symbol: Опционально - фильтр по символу

        Returns:
            List of open orders
        """
        try:
            params = {
                'category': config.BYBIT_CATEGORY,
                'settleCoin': 'USDT'
            }

            if symbol:
                params['symbol'] = symbol

            response = self.client.get_open_orders(**params)
            result = self._handle_response(response)

            return result.get('list', [])

        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            raise BybitError(f"Failed to get open orders: {str(e)}")

    async def get_order_history(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        limit: int = 1
    ) -> Optional[Dict]:
        """
        Получить информацию об ордере из истории

        Returns:
            Order info dict или None если не найден
        """
        try:
            params = {
                'category': config.BYBIT_CATEGORY,
                'symbol': symbol,
                'limit': limit
            }

            if order_id:
                params['orderId'] = order_id
            elif client_order_id:
                params['orderLinkId'] = client_order_id

            response = self.client.get_order_history(**params)
            result = self._handle_response(response)

            if not result.get('list'):
                return None

            return result['list'][0]

        except Exception as e:
            logger.error(f"Error getting order history: {e}")
            return None

    async def cancel_orders_by_prefix(
        self,
        symbol: str,
        client_order_id_prefix: str
    ) -> list:
        """
        Отменить все ордера с указанным префиксом client_order_id.

        Используется для отмены всех entry ордеров плана при cancel условии.

        Args:
            symbol: Торговая пара
            client_order_id_prefix: Префикс orderLinkId (напр. "plan_abc123")

        Returns:
            List of cancelled order_ids
        """
        cancelled = []

        try:
            open_orders = await self.get_open_orders(symbol=symbol)

            for order in open_orders:
                order_link_id = order.get('orderLinkId', '')
                if order_link_id.startswith(client_order_id_prefix):
                    try:
                        await self.cancel_order(
                            symbol=symbol,
                            order_id=order['orderId']
                        )
                        cancelled.append(order['orderId'])
                        logger.debug(f"Cancelled order {order['orderId']} (prefix: {client_order_id_prefix})")
                    except Exception as e:
                        logger.error(f"Failed to cancel order {order['orderId']}: {e}")

            if cancelled:
                logger.info(f"Cancelled {len(cancelled)} orders with prefix '{client_order_id_prefix}'")

            return cancelled

        except Exception as e:
            logger.error(f"Error in cancel_orders_by_prefix: {e}")
            return cancelled

    async def get_orders_by_prefix(
        self,
        symbol: str,
        client_order_id_prefix: str,
        include_history: bool = True
    ) -> list:
        """
        Получить все ордера с указанным префиксом client_order_id.

        Args:
            symbol: Торговая пара
            client_order_id_prefix: Префикс orderLinkId
            include_history: Искать также в истории ордеров

        Returns:
            List of orders matching the prefix
        """
        result = []

        try:
            # Открытые ордера
            open_orders = await self.get_open_orders(symbol=symbol)
            for order in open_orders:
                if order.get('orderLinkId', '').startswith(client_order_id_prefix):
                    result.append(order)

            # История ордеров (если нужно)
            if include_history:
                params = {
                    'category': config.BYBIT_CATEGORY,
                    'symbol': symbol,
                    'limit': 50
                }
                response = self.client.get_order_history(**params)
                history = self._handle_response(response)

                for order in history.get('list', []):
                    if order.get('orderLinkId', '').startswith(client_order_id_prefix):
                        # Избегаем дубликатов
                        if not any(o['orderId'] == order['orderId'] for o in result):
                            result.append(order)

            return result

        except Exception as e:
            logger.error(f"Error in get_orders_by_prefix: {e}")
            return result
