import logging
from typing import Optional, Dict
import config
from .client import BybitError

logger = logging.getLogger(__name__)


class TradingStopMixin:
    """Миксин для работы с SL/TP"""

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

    async def place_ladder_tp(
        self,
        symbol: str,
        position_side: str,  # "Buy" or "Sell"
        tp_levels: list[dict],  # [{'price': '140.00', 'qty': '0.5'}, ...]
        client_order_id_prefix: str = ""
    ) -> list[Dict]:
        """
        Установить ladder TP через отдельные Limit ордера

        Args:
            symbol: Торговая пара
            position_side: Направление позиции ("Buy" для Long, "Sell" для Short)
            tp_levels: Список уровней TP [{'price': str, 'qty': str}, ...]
            client_order_id_prefix: Префикс для clientOrderId (например, trade_id)

        Returns:
            List of created orders

        Example:
            await client.place_ladder_tp(
                symbol='SOLUSDT',
                position_side='Buy',
                tp_levels=[
                    {'price': '140.00', 'qty': '0.5'},  # TP1: 50%
                    {'price': '145.00', 'qty': '0.5'}   # TP2: 50%
                ]
            )
        """
        try:
            # Противоположная сторона для закрытия
            close_side = "Sell" if position_side == "Buy" else "Buy"

            created_orders = []

            for i, level in enumerate(tp_levels, start=1):
                price = level['price']
                qty = level['qty']

                # Client order ID для каждого уровня
                client_oid = None
                if client_order_id_prefix:
                    client_oid = f"{client_order_id_prefix}_tp{i}"

                # Размещаем Limit ордер с reduceOnly
                order = await self.place_order(
                    symbol=symbol,
                    side=close_side,
                    order_type="Limit",
                    qty=qty,
                    price=price,
                    client_order_id=client_oid,
                    reduce_only=True  # КРИТИЧНО для TP!
                )

                created_orders.append(order)
                logger.info(f"TP{i} placed: {qty} @ ${price}")

            logger.info(f"Ladder TP set: {len(created_orders)} levels")
            return created_orders

        except Exception as e:
            logger.error(f"Error placing ladder TP: {e}")
            raise BybitError(f"Failed to place ladder TP: {str(e)}")
