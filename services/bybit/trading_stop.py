import logging
from typing import Optional, Dict
import config
from .client import BybitError
from utils.validators import round_price

logger = logging.getLogger(__name__)


class TradingStopMixin:
    """Миксин для работы с SL/TP"""

    async def update_trading_stop(
        self,
        symbol: str,
        stop_loss: Optional[str] = None,
        take_profit: Optional[str] = None,
        sl_trigger_by: Optional[str] = None,  # Auto: LastPrice on testnet, MarkPrice on mainnet
        tp_trigger_by: Optional[str] = None   # Auto: LastPrice on testnet, MarkPrice on mainnet
    ):
        """
        Атомарно обновить SL/TP на позицию с сохранением существующих значений

        ⚠️ КРИТИЧНО: Всегда используй этот метод вместо set_trading_stop()!

        Логика:
        1. Читает текущие SL/TP из позиции
        2. Мерджит с новыми значениями (новые перезаписывают старые)
        3. Один вызов API со всеми параметрами
        4. Логирует старое → новое состояние

        Это защищает от случайного стирания SL/TP при частичном апдейте.

        Args:
            symbol: Торговая пара
            stop_loss: Новая цена SL (None = оставить текущий)
            take_profit: Новая цена TP (None = оставить текущий)
            sl_trigger_by: Триггер для SL
            tp_trigger_by: Триггер для TP

        Example:
            # Обновить только TP, сохранив текущий SL
            await client.update_trading_stop(symbol='BTCUSDT', take_profit='50000')
        """
        try:
            # 1. Получаем текущую позицию
            positions = await self.get_positions(symbol=symbol)

            if not positions:
                raise BybitError(f"No position found for {symbol}")

            position = positions[0]
            current_sl = position.get('stopLoss', '')
            current_tp = position.get('takeProfit', '')
            position_side = position.get('side', '')  # "Buy" or "Sell"
            mark_price = float(position.get('markPrice', 0))

            # 1.5 Валидация SL относительно стороны позиции
            if stop_loss and mark_price > 0 and position_side:
                sl_price = float(stop_loss)
                if position_side == "Buy" and sl_price >= mark_price:
                    logger.error(
                        f"[{symbol}] Invalid SL for Buy position: SL={sl_price} >= markPrice={mark_price}. "
                        f"SL must be BELOW current price for long positions."
                    )
                    raise BybitError(
                        f"Invalid SL: {sl_price} is above mark price {mark_price} for Buy position. "
                        f"Stop Loss for long must be BELOW entry."
                    )
                elif position_side == "Sell" and sl_price <= mark_price:
                    logger.error(
                        f"[{symbol}] Invalid SL for Sell position: SL={sl_price} <= markPrice={mark_price}. "
                        f"SL must be ABOVE current price for short positions."
                    )
                    raise BybitError(
                        f"Invalid SL: {sl_price} is below mark price {mark_price} for Sell position. "
                        f"Stop Loss for short must be ABOVE entry."
                    )

            # 2. Мерджим: новые значения перезаписывают старые
            final_sl = stop_loss if stop_loss is not None else current_sl
            final_tp = take_profit if take_profit is not None else current_tp

            # 3. Логируем изменения ДО апдейта
            logger.info(
                f"[{symbol}] Updating SL/TP: "
                f"SL: {current_sl or 'None'} → {final_sl or 'None'}, "
                f"TP: {current_tp or 'None'} → {final_tp or 'None'}"
            )

            # 4. Один атомарный вызов API
            params = {
                'category': config.BYBIT_CATEGORY,
                'symbol': symbol,
                'positionIdx': config.BYBIT_POSITION_IDX,
                'tpslMode': 'Full',
            }

            # На testnet используем LastPrice (Mark Price там часто битый)
            # На mainnet используем MarkPrice (более стабильный)
            default_trigger = "LastPrice" if self.testnet else "MarkPrice"

            # Устанавливаем оба значения (или очищаем, если пустые)
            if final_sl:
                params['stopLoss'] = final_sl
                params['slTriggerBy'] = sl_trigger_by or default_trigger

            if final_tp:
                params['takeProfit'] = final_tp
                params['tpTriggerBy'] = tp_trigger_by or default_trigger

            response = self.client.set_trading_stop(**params)
            result = self._handle_response(response)

            # 5. Логируем response от API
            ret_code = response.get('retCode', -1)
            ret_msg = response.get('retMsg', 'OK')
            logger.info(f"[{symbol}] API response: retCode={ret_code}, retMsg={ret_msg}")

            # 6. Получаем финальное состояние позиции для верификации
            updated_positions = await self.get_positions(symbol=symbol)
            if updated_positions:
                updated_pos = updated_positions[0]
                verified_sl = updated_pos.get('stopLoss', '')
                verified_tp = updated_pos.get('takeProfit', '')
                logger.info(
                    f"[{symbol}] Verified position state: "
                    f"SL={verified_sl or 'None'}, TP={verified_tp or 'None'}"
                )

                # ⚠️ КРИТИЧНАЯ ПРОВЕРКА: SL должен существовать!
                if not verified_sl:
                    logger.error(f"[{symbol}] ⚠️ CRITICAL: Stop Loss is MISSING after update!")

            return result

        except Exception as e:
            logger.error(f"Error updating trading stop for {symbol}: {e}", exc_info=True)
            raise BybitError(f"Failed to update SL/TP: {str(e)}")

    async def set_trading_stop(
        self,
        symbol: str,
        stop_loss: Optional[str] = None,
        take_profit: Optional[str] = None,
        sl_trigger_by: Optional[str] = None,
        tp_trigger_by: Optional[str] = None
    ):
        """
        Установить SL/TP на позицию

        ⚠️ DEPRECATED: Используй update_trading_stop() вместо этого метода!

        Этот метод оставлен для обратной совместимости, но может случайно
        стереть существующий SL/TP при частичном апдейте.

        Args:
            stop_loss: Цена стоп-лосса
            take_profit: Цена тейк-профита
            sl_trigger_by: "MarkPrice" или "LastPrice" (auto on None)
            tp_trigger_by: "MarkPrice" или "LastPrice" (auto on None)
        """
        try:
            # На testnet используем LastPrice (Mark Price там часто битый)
            default_trigger = "LastPrice" if self.testnet else "MarkPrice"

            params = {
                'category': config.BYBIT_CATEGORY,
                'symbol': symbol,
                'positionIdx': config.BYBIT_POSITION_IDX,
                'tpslMode': 'Full',  # Full = SL/TP на всю позицию
            }

            if stop_loss:
                params['stopLoss'] = stop_loss
                params['slTriggerBy'] = sl_trigger_by or default_trigger

            if take_profit:
                params['takeProfit'] = take_profit
                params['tpTriggerBy'] = tp_trigger_by or default_trigger

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
        client_order_id_prefix: str = "",
        apply_buffer: bool = True,
        buffer_pct: float = 0.0005  # 0.05% буфер по умолчанию
    ) -> list[Dict]:
        """
        Установить ladder TP через отдельные Limit ордера с буфером для исполнения

        ✅ Оптимизации для исполнения:
        - Буфер: цены чуть "жаднее" (раньше целевой) → больше шанс fill
        - timeInForce=GTC: ордер живёт до исполнения/отмены
        - postOnly=False: может быть taker, если цена проскочила

        Args:
            symbol: Торговая пара
            position_side: Направление позиции ("Buy" для Long, "Sell" для Short)
            tp_levels: Список уровней TP [{'price': str, 'qty': str}, ...]
            client_order_id_prefix: Префикс для clientOrderId (например, trade_id)
            apply_buffer: Применять ли буфер к ценам (рекомендуется True)
            buffer_pct: Процент буфера (по умолчанию 0.05% = 0.0005)

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
                price_str = level['price']
                qty = level['qty']

                # Применяем буфер для более раннего исполнения
                if apply_buffer:
                    price_float = float(price_str)

                    if position_side == "Buy":
                        # Long: TP выше → делаем чуть ниже для раннего исполнения
                        buffered_price = price_float * (1 - buffer_pct)
                    else:
                        # Short: TP ниже → делаем чуть выше для раннего исполнения
                        buffered_price = price_float * (1 + buffer_pct)

                    # Округляем до tick size
                    instrument_info = await self.get_instrument_info(symbol)
                    tick_size = instrument_info.get('tickSize', '0.01')
                    price_str = round_price(buffered_price, tick_size)

                    logger.debug(
                        f"TP{i} buffer applied: {price_float:.4f} → {buffered_price:.4f} "
                        f"(buffered by {buffer_pct*100:.2f}%)"
                    )

                # Client order ID для каждого уровня
                client_oid = None
                if client_order_id_prefix:
                    client_oid = f"{client_order_id_prefix}_tp{i}"

                # Размещаем Limit ордер с оптимизациями для исполнения
                order = await self.place_order(
                    symbol=symbol,
                    side=close_side,
                    order_type="Limit",
                    qty=qty,
                    price=price_str,
                    client_order_id=client_oid,
                    reduce_only=True,  # КРИТИЧНО для TP!
                    time_in_force="GTC",  # Good-Till-Cancel
                    post_only=False  # Может быть taker для гарантии fill
                )

                created_orders.append(order)
                logger.info(f"TP{i} placed: {qty} @ ${price_str} (GTC, taker allowed)")

            logger.info(f"Ladder TP set: {len(created_orders)} levels with buffer")
            return created_orders

        except Exception as e:
            logger.error(f"Error placing ladder TP: {e}")
            raise BybitError(f"Failed to place ladder TP: {str(e)}")
