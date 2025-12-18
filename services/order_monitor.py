"""
Order Monitor - мониторинг pending ордеров и автоматическая установка SL/TP

Отслеживает pending Limit orders и когда они исполняются:
- Автоматически устанавливает Stop Loss
- Автоматически устанавливает ladder Take Profit
- Отправляет уведомление пользователю
"""
import asyncio
import logging
from typing import Dict, Optional, Set
from datetime import datetime
from aiogram import Bot
from services.bybit import BybitClient
from utils.validators import round_qty, round_price

logger = logging.getLogger(__name__)


class PendingOrder:
    """Информация о pending ордере"""

    def __init__(self, order_data: dict):
        self.order_id = order_data['order_id']
        self.symbol = order_data['symbol']
        self.side = order_data['side']  # "Long" or "Short"
        self.order_side = order_data['order_side']  # "Buy" or "Sell"
        self.qty = order_data['qty']
        self.entry_price = order_data['entry_price']
        self.stop_price = order_data['stop_price']
        self.targets = order_data.get('targets', [])
        self.leverage = order_data.get('leverage', 5)
        self.user_id = order_data['user_id']
        self.sl_already_set = order_data.get('sl_already_set', False)  # SL уже на ордере
        self.testnet = order_data.get('testnet', False)  # Testnet режим
        self.created_at = datetime.utcnow()


class OrderMonitor:
    """
    Мониторинг pending ордеров в реальном времени

    Периодически проверяет статус pending Limit orders и обнаруживает fill.
    После fill автоматически устанавливает SL/TP и отправляет уведомление.
    """

    def __init__(
        self,
        bot: Bot,
        trade_logger,
        check_interval: int = 10,  # Интервал проверки в секундах
        testnet: bool = False
    ):
        self.bot = bot
        self.trade_logger = trade_logger
        self.check_interval = check_interval
        self.testnet = testnet  # Default, но каждый order имеет свой testnet флаг

        # Bybit clients (lazy init per testnet mode)
        self._clients: Dict[bool, BybitClient] = {}

        # Храним pending orders: {user_id: {order_id: PendingOrder}}
        self.pending_orders: Dict[int, Dict[str, PendingOrder]] = {}

        self._running = False
        self._task: Optional[asyncio.Task] = None

    def _get_client(self, testnet: bool) -> BybitClient:
        """Получить Bybit клиент для нужного режима (testnet/live)"""
        if testnet not in self._clients:
            self._clients[testnet] = BybitClient(testnet=testnet)
        return self._clients[testnet]

    def register_order(self, order_data: dict):
        """Зарегистрировать ордер для мониторинга"""
        user_id = order_data['user_id']
        order = PendingOrder(order_data)

        if user_id not in self.pending_orders:
            self.pending_orders[user_id] = {}

        self.pending_orders[user_id][order.order_id] = order
        logger.info(f"Order {order.order_id} registered for monitoring (user: {user_id}, symbol: {order.symbol})")

    def unregister_order(self, user_id: int, order_id: str):
        """Убрать ордер из мониторинга"""
        if user_id in self.pending_orders and order_id in self.pending_orders[user_id]:
            del self.pending_orders[user_id][order_id]
            logger.info(f"Order {order_id} unregistered (user: {user_id})")

    async def start(self):
        """Запустить мониторинг в фоновом режиме"""
        if self._running:
            logger.warning("Order monitor already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Order monitor started (interval: {self.check_interval}s, testnet: {self.testnet})")

    async def stop(self):
        """Остановить мониторинг"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Order monitor stopped")

    async def _monitor_loop(self):
        """Основной цикл мониторинга"""
        while self._running:
            try:
                await self._check_all_orders()
            except Exception as e:
                logger.error(f"Error in order monitor loop: {e}", exc_info=True)

            # Ждем до следующей проверки
            await asyncio.sleep(self.check_interval)

    async def _check_all_orders(self):
        """Проверить все pending orders"""
        for user_id in list(self.pending_orders.keys()):
            for order_id in list(self.pending_orders.get(user_id, {}).keys()):
                try:
                    await self._check_order(user_id, order_id)
                except Exception as e:
                    logger.error(f"Error checking order {order_id}: {e}")

    async def _check_order(self, user_id: int, order_id: str):
        """Проверить статус конкретного ордера"""
        order = self.pending_orders[user_id][order_id]
        client = self._get_client(order.testnet)

        try:
            # Получить статус ордера от Bybit (сначала open orders, потом history)
            order_info = await client.get_order(
                symbol=order.symbol,
                order_id=order_id
            )

            status = order_info.get('orderStatus', '')

            if status == 'Filled':
                # Ордер исполнен!
                await self._handle_order_filled(user_id, order, order_info)
                self.unregister_order(user_id, order_id)
            elif status in ['Cancelled', 'Rejected']:
                # Ордер отменен или отклонен
                logger.info(f"Order {order_id} status: {status}, removing from monitor")
                self.unregister_order(user_id, order_id)
            # Если статус New/PartiallyFilled - продолжаем мониторинг

        except Exception as e:
            logger.error(f"Error checking order {order_id}: {e}")

    async def _handle_order_filled(self, user_id: int, order: PendingOrder, order_info: dict):
        """Обработка исполненного ордера"""
        try:
            actual_entry_price = float(order_info.get('avgPrice', order.entry_price))
            actual_qty = float(order_info.get('cumExecQty', order.qty))

            logger.info(f"Order {order.order_id} filled: {order.symbol} {order.side} @ ${actual_entry_price:.2f}, qty: {actual_qty}")

            # 1. Зарегистрировать вход в позицию в trade_logger
            try:
                from datetime import datetime as dt
                from services.trade_logger import TradeRecord, calculate_fee, calculate_margin
                import uuid

                actual_risk = abs(actual_entry_price - order.stop_price) * actual_qty
                margin_usd = calculate_margin(actual_entry_price, actual_qty, order.leverage)
                # Limit order = maker fee
                entry_fee = calculate_fee(actual_entry_price, actual_qty, is_taker=False)

                # TP price для лога
                tp_price_for_log = None
                rr_planned = None
                if order.targets:
                    tp_price_for_log = order.targets[0].get("price")
                    rrs = []
                    for t in order.targets:
                        tp = t.get("price", 0)
                        if order.stop_price != actual_entry_price:
                            rr = abs(tp - actual_entry_price) / abs(actual_entry_price - order.stop_price)
                            rrs.append(rr)
                    if rrs:
                        rr_planned = sum(rrs) / len(rrs)

                # Преобразуем side в Long/Short для консистентности
                position_side = "Long" if order.side == "Buy" else "Short"

                trade_record = TradeRecord(
                    trade_id=str(uuid.uuid4()),
                    user_id=user_id,
                    symbol=order.symbol,
                    side=position_side,
                    opened_at=dt.utcnow().isoformat(),
                    entry_price=actual_entry_price,
                    qty=actual_qty,
                    leverage=order.leverage,
                    margin_mode="cross",
                    margin_usd=margin_usd,
                    stop_price=order.stop_price,
                    risk_usd=actual_risk,
                    tp_price=tp_price_for_log,
                    rr_planned=rr_planned,
                    entry_fee_usd=entry_fee,
                    total_fees_usd=entry_fee,
                    status="open",
                    testnet=order.testnet
                )
                await self.trade_logger.log_trade(trade_record)
                logger.info(f"Trade entry logged for {order.symbol} @ ${actual_entry_price:.2f}")
            except Exception as log_error:
                logger.error(f"Failed to log trade entry: {log_error}")

            # 2. Установить Stop Loss (если не был уже установлен на ордере)
            client = self._get_client(order.testnet)
            if not order.sl_already_set:
                await client.update_trading_stop(
                    symbol=order.symbol,
                    stop_loss=str(order.stop_price)
                )
                logger.info(f"SL set at ${order.stop_price:.2f} for {order.symbol}")
            else:
                logger.info(f"SL already on order for {order.symbol}, skipping")

            # 3. Установить ladder Take Profit
            tp_success = True
            if order.targets:
                tp_success = await self._set_ladder_tp(order, actual_qty)

            # 4. Отправить уведомление
            await self._send_fill_notification(user_id, order, actual_entry_price, actual_qty, tp_success)

        except Exception as e:
            logger.error(f"Error handling filled order {order.order_id}: {e}", exc_info=True)

    async def _set_ladder_tp(self, order: PendingOrder, actual_qty: float) -> bool:
        """
        Установить ladder TP для исполненного ордера

        Returns:
            True если TP установлены успешно, False если ошибка
        """
        try:
            client = self._get_client(order.testnet)
            # Получить instrument info
            instrument_info = await client.get_instrument_info(order.symbol)
            tick_size = instrument_info.get('tickSize', '0.01')
            qty_step = instrument_info.get('qtyStep', '0.001')

            # Подготовить уровни TP
            tp_levels = []
            for target in order.targets:
                tp_price = target.get("price", 0)
                partial_pct = target.get("partial_close_pct", 100)

                # Рассчитать qty для этого уровня
                tp_qty_raw = (actual_qty * partial_pct) / 100
                tp_qty = round_qty(tp_qty_raw, qty_step, round_down=True)

                # Округлить цену
                tp_price_str = round_price(tp_price, tick_size)

                tp_levels.append({
                    'price': tp_price_str,
                    'qty': tp_qty
                })

            # Разместить ladder TP ордера
            await client.place_ladder_tp(
                symbol=order.symbol,
                position_side=order.order_side,
                tp_levels=tp_levels,
                client_order_id_prefix=order.order_id[:20]  # Используем order_id как prefix
            )
            logger.info(f"Ladder TP set: {len(tp_levels)} levels for {order.symbol}")
            return True

        except Exception as e:
            logger.error(f"Error setting ladder TP: {e}", exc_info=True)
            return False

    async def _send_fill_notification(self, user_id: int, order: PendingOrder, entry_price: float, qty: float, tp_success: bool = True):
        """Отправить уведомление о fill"""
        try:
            side_emoji = "🟢" if order.side == "Long" else "🔴"
            side_text = order.side.upper()

            # Формируем сообщение
            message = f"""
🔔 <b>Лимитный ордер исполнен!</b>

{side_emoji} <b>{order.symbol}</b> {side_text}

⚡ <b>Entry:</b> ${entry_price:.2f} (filled)
🛑 <b>Stop:</b> ${order.stop_price:.2f}
"""

            # Добавляем информацию о TP
            if order.targets:
                for idx, target in enumerate(order.targets, 1):
                    tp_price = target.get("price", 0)
                    partial_pct = target.get("partial_close_pct", 100)
                    message += f"🎯 <b>TP{idx}:</b> ${tp_price:.2f} ({partial_pct}%)\n"

            message += f"""
📊 <b>Leverage:</b> {order.leverage}x
📦 <b>Qty:</b> {qty}

"""

            # Статус установки SL/TP
            sl_status = "✅ SL на ордере" if order.sl_already_set else "✅ SL установлен"
            if order.targets:
                if tp_success:
                    message += f"<i>{sl_status}, TP ордера размещены</i>\n"
                else:
                    message += f"<i>{sl_status}, но ошибка при установке TP!</i>\n<i>Проверь позицию вручную!</i>\n"
            else:
                message += f"<i>{sl_status}</i>\n"

            message += f"\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"

            await self.bot.send_message(
                chat_id=user_id,
                text=message.strip(),
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Failed to send fill notification to user {user_id}: {e}")


def create_order_monitor(
    bot: Bot,
    trade_logger,
    testnet: bool = False,
    check_interval: int = 10
) -> OrderMonitor:
    """Создать экземпляр OrderMonitor"""
    return OrderMonitor(
        bot=bot,
        trade_logger=trade_logger,
        check_interval=check_interval,
        testnet=testnet
    )
