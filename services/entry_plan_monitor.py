"""
Entry Plan Monitor

Мониторинг Entry Plans с несколькими ордерами (ladder entry).
Отслеживает активацию, fills, cancel условия и устанавливает SL/TP.
"""
import asyncio
import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone
from aiogram import Bot

from services.bybit import BybitClient
from services.entry_plan import EntryPlan, EntryOrder
from services.trade_logger import TradeLogger, TradeRecord, calculate_fee, calculate_margin
from utils.validators import round_qty, round_price

logger = logging.getLogger(__name__)


class EntryPlanMonitor:
    """
    Мониторинг Entry Plans с несколькими ордерами.

    Ответственности:
    1. Хранение активных планов (in-memory, TODO: Redis)
    2. Проверка activation gate
    3. Размещение entry ордеров при активации
    4. Мониторинг fills всех entry ордеров
    5. Обработка cancel_if условий
    6. Установка SL/TP после набора позиции (полного или частичного)
    """

    def __init__(
        self,
        bot: Bot,
        trade_logger: TradeLogger,
        check_interval: int = 10,
        testnet: bool = False
    ):
        self.bot = bot
        self.trade_logger = trade_logger
        self.check_interval = check_interval
        self.testnet = testnet

        # Bybit client
        self.client = BybitClient(testnet=testnet)

        # Хранение планов: {plan_id: EntryPlan}
        self.active_plans: Dict[str, EntryPlan] = {}

        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ==================== Public API ====================

    async def register_plan(self, plan: EntryPlan):
        """
        Зарегистрировать новый план для мониторинга.

        Args:
            plan: EntryPlan объект
        """
        self.active_plans[plan.plan_id] = plan
        logger.info(
            f"Plan {plan.plan_id} registered: {plan.symbol} {plan.side}, "
            f"{len(plan.orders)} orders, mode={plan.mode}"
        )

        # Если activation_type = immediate, сразу активируем
        if plan.activation_type == "immediate":
            await self._activate_plan(plan)

    def unregister_plan(self, plan_id: str):
        """Убрать план из мониторинга"""
        if plan_id in self.active_plans:
            del self.active_plans[plan_id]
            logger.info(f"Plan {plan_id} unregistered")

    async def start(self):
        """Запустить мониторинг в фоновом режиме"""
        if self._running:
            logger.warning("Entry plan monitor already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Entry plan monitor started (interval: {self.check_interval}s)")

    async def stop(self):
        """Остановить мониторинг"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Entry plan monitor stopped")

    # ==================== Main Loop ====================

    async def _monitor_loop(self):
        """Основной цикл мониторинга"""
        while self._running:
            try:
                await self._check_all_plans()
            except Exception as e:
                logger.error(f"Error in entry plan monitor loop: {e}", exc_info=True)

            await asyncio.sleep(self.check_interval)

    async def _check_all_plans(self):
        """Проверить все активные планы"""
        for plan_id in list(self.active_plans.keys()):
            plan = self.active_plans.get(plan_id)
            if not plan:
                continue

            try:
                # 1. Проверка activation gate (если ещё не активирован)
                if not plan.is_activated:
                    await self._check_activation(plan)
                    continue  # Ждём активации

                # 2. Проверка cancel conditions
                should_cancel, reason = await self._check_cancel_conditions(plan)
                if should_cancel:
                    await self._cancel_plan(plan, reason)
                    continue

                # 3. Проверка fills
                await self._check_order_fills(plan)

                # 4. Если план завершён - финализируем
                if plan.status == "filled":
                    await self._handle_plan_completed(plan)

            except Exception as e:
                logger.error(f"Error checking plan {plan_id}: {e}", exc_info=True)

    # ==================== Activation ====================

    async def _check_activation(self, plan: EntryPlan):
        """Проверить условия активации плана"""
        try:
            ticker = await self.client.get_tickers(plan.symbol)
            current_price = float(ticker.get('markPrice', 0))

            if not current_price:
                return

            should_activate = self._evaluate_activation(
                activation_type=plan.activation_type,
                activation_level=plan.activation_level,
                current_price=current_price,
                max_distance_pct=plan.max_distance_pct
            )

            if should_activate:
                await self._activate_plan(plan)

        except Exception as e:
            logger.error(f"Error checking activation for plan {plan.plan_id}: {e}")

    def _evaluate_activation(
        self,
        activation_type: str,
        activation_level: Optional[float],
        current_price: float,
        max_distance_pct: float
    ) -> bool:
        """Оценить условие активации"""
        if activation_type == "immediate":
            return True

        if not activation_level:
            return True  # Нет уровня = сразу активируем

        if activation_type == "touch":
            distance_pct = abs(current_price - activation_level) / activation_level * 100
            return distance_pct <= max_distance_pct

        if activation_type == "price_above":
            return current_price >= activation_level

        if activation_type == "price_below":
            return current_price <= activation_level

        return False

    async def _activate_plan(self, plan: EntryPlan):
        """Активировать план и разместить все entry ордера"""
        logger.info(f"Activating plan {plan.plan_id} for {plan.symbol}")

        plan.is_activated = True
        plan.activated_at = datetime.now(timezone.utc).isoformat()
        plan.status = "active"

        # Получить instrument info для округления
        instrument_info = await self.client.get_instrument_info(plan.symbol)
        tick_size = instrument_info.get('tickSize', '0.01')
        qty_step = instrument_info.get('qtyStep', '0.001')

        # Размещаем все entry ордера
        order_side = "Buy" if plan.side == "Long" else "Sell"
        placed_count = 0

        for i, order_dict in enumerate(plan.orders):
            order = EntryOrder.from_dict(order_dict)

            try:
                # Округляем цену и qty
                price_str = round_price(order.price, tick_size)
                qty_str = round_qty(order.qty, qty_step)

                # Размещаем ордер
                placed_order = await self.client.place_order(
                    symbol=plan.symbol,
                    side=order_side,
                    order_type="Limit",
                    qty=qty_str,
                    price=price_str,
                    client_order_id=f"{plan.plan_id[:20]}_E{i+1}"
                )

                # Обновляем статус ордера
                order.mark_placed(placed_order['orderId'])
                plan.orders[i] = order.to_dict()
                placed_count += 1

                logger.info(
                    f"Entry order placed: {plan.symbol} {order_side} "
                    f"@ ${order.price:.2f} qty={order.qty} tag={order.tag}"
                )

            except Exception as e:
                logger.error(f"Failed to place entry order {i+1}: {e}")
                order.status = "cancelled"
                plan.orders[i] = order.to_dict()

        # Уведомляем пользователя
        if placed_count > 0:
            await self._notify_plan_activated(plan, placed_count)

    # ==================== Cancel Conditions ====================

    async def _check_cancel_conditions(self, plan: EntryPlan) -> tuple[bool, str]:
        """
        Проверить условия отмены плана.

        Returns:
            (should_cancel, reason)
        """
        if not plan.cancel_if:
            return False, ""

        try:
            ticker = await self.client.get_tickers(plan.symbol)
            current_price = float(ticker.get('markPrice', 0))

            for condition in plan.cancel_if:
                should_cancel, reason = self._evaluate_cancel_condition(
                    condition=condition,
                    current_price=current_price,
                    plan_created_at=plan.created_at,
                    time_valid_hours=plan.time_valid_hours
                )

                if should_cancel:
                    return True, reason

            return False, ""

        except Exception as e:
            logger.error(f"Error checking cancel conditions: {e}")
            return False, ""

    def _evaluate_cancel_condition(
        self,
        condition: str,
        current_price: float,
        plan_created_at: str,
        time_valid_hours: float
    ) -> tuple[bool, str]:
        """Оценить одно условие отмены"""
        parts = condition.split()

        if parts[0] == "break_below" and len(parts) >= 2:
            level = float(parts[1])
            if current_price < level:
                return True, f"break_below {level}"

        if parts[0] == "break_above" and len(parts) >= 2:
            level = float(parts[1])
            if current_price > level:
                return True, f"break_above {level}"

        if "time_valid_hours" in condition or "time_exceeded" in condition:
            try:
                created = datetime.fromisoformat(plan_created_at.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                hours_passed = (now - created).total_seconds() / 3600

                if hours_passed > time_valid_hours:
                    return True, f"time_exceeded ({hours_passed:.1f}h > {time_valid_hours}h)"
            except Exception as e:
                logger.error(f"Error parsing time condition: {e}")

        return False, ""

    async def _cancel_plan(self, plan: EntryPlan, reason: str):
        """
        Отменить план.

        - Отменяет все pending/placed ордера
        - Если есть fills — оставляет позицию с SL/TP (Вариант A)
        - Уведомляет пользователя
        """
        logger.info(f"Cancelling plan {plan.plan_id}: {reason}")

        plan.status = "cancelled"
        plan.cancel_reason = reason

        # Отменяем все открытые ордера
        cancelled = await self.client.cancel_orders_by_prefix(
            symbol=plan.symbol,
            client_order_id_prefix=plan.plan_id[:20]
        )

        logger.info(f"Cancelled {len(cancelled)} orders for plan {plan.plan_id}")

        # Если есть fills — ставим SL/TP на частичную позицию
        plan.recalculate_metrics()

        if plan.has_fills:
            logger.info(
                f"Plan has partial fills ({plan.fill_percentage:.0f}%), "
                f"setting SL/TP on partial position"
            )
            await self._setup_sl_tp_for_partial(plan)
            await self._notify_plan_cancelled_with_position(plan, reason)
        else:
            await self._notify_plan_cancelled(plan, reason)

        # Убираем из мониторинга
        self.unregister_plan(plan.plan_id)

    # ==================== Order Fills ====================

    async def _check_order_fills(self, plan: EntryPlan):
        """Проверить fills всех ордеров плана"""
        has_updates = False

        for i, order_dict in enumerate(plan.orders):
            order = EntryOrder.from_dict(order_dict)

            # Пропускаем уже заполненные или отменённые
            if order.status in ('filled', 'cancelled', 'pending'):
                continue

            if not order.order_id:
                continue

            try:
                # Получить статус ордера от Bybit
                order_info = await self.client.get_order(
                    symbol=plan.symbol,
                    order_id=order.order_id
                )

                status = order_info.get('orderStatus', '')

                if status == 'Filled':
                    # Ордер исполнен!
                    fill_price = float(order_info.get('avgPrice', order.price))
                    order.mark_filled(fill_price)
                    plan.orders[i] = order.to_dict()
                    has_updates = True

                    # Логируем entry fill в TradeRecord
                    await self._log_entry_fill(plan, order)

                    # Уведомляем пользователя
                    await self._notify_order_filled(plan, order)

                    logger.info(
                        f"Entry order filled: {plan.symbol} @ ${fill_price:.2f} "
                        f"qty={order.qty} tag={order.tag}"
                    )

                elif status in ('Cancelled', 'Rejected'):
                    order.mark_cancelled()
                    plan.orders[i] = order.to_dict()
                    has_updates = True
                    logger.info(f"Entry order {order.order_id} status: {status}")

            except Exception as e:
                logger.error(f"Error checking order {order.order_id}: {e}")

        # Пересчитать метрики если были изменения
        if has_updates:
            plan.recalculate_metrics()

            # Проверить завершение плана
            if plan.is_complete:
                plan.status = "filled"

    async def _log_entry_fill(self, plan: EntryPlan, order: EntryOrder):
        """Залогировать entry fill в TradeRecord"""
        try:
            await self.trade_logger.add_entry_fill(
                user_id=plan.user_id,
                trade_id=plan.trade_id,
                fill_price=order.fill_price,
                fill_qty=order.qty,
                order_tag=order.tag,
                is_taker=False,  # Limit = maker
                testnet=plan.testnet
            )
        except Exception as e:
            logger.error(f"Failed to log entry fill: {e}")

    # ==================== Plan Completion ====================

    async def _handle_plan_completed(self, plan: EntryPlan):
        """Обработка полностью заполненного плана"""
        logger.info(
            f"Plan {plan.plan_id} completed: "
            f"avg_entry=${plan.avg_entry_price:.2f}, filled_qty={plan.filled_qty}"
        )

        # Устанавливаем SL/TP
        await self._setup_sl_tp(plan)

        # Уведомляем пользователя
        await self._notify_plan_completed(plan)

        # Убираем из мониторинга
        self.unregister_plan(plan.plan_id)

    async def _setup_sl_tp(self, plan: EntryPlan):
        """Установить SL и ladder TP для позиции"""
        try:
            # Установить SL
            await self.client.set_trading_stop(
                symbol=plan.symbol,
                stop_loss=str(plan.stop_price),
                sl_trigger_by="MarkPrice" if not plan.testnet else "LastPrice"
            )
            logger.info(f"SL set at ${plan.stop_price:.2f} for {plan.symbol}")

            # Установить ladder TP
            if plan.targets:
                await self._setup_ladder_tp(plan)

        except Exception as e:
            logger.error(f"Error setting SL/TP: {e}", exc_info=True)

    async def _setup_sl_tp_for_partial(self, plan: EntryPlan):
        """Установить SL/TP для частичной позиции (при отмене плана)"""
        if plan.filled_qty <= 0:
            return

        try:
            # Установить SL
            await self.client.set_trading_stop(
                symbol=plan.symbol,
                stop_loss=str(plan.stop_price),
                sl_trigger_by="MarkPrice" if not plan.testnet else "LastPrice"
            )
            logger.info(f"SL set at ${plan.stop_price:.2f} for partial position")

            # Установить ladder TP (пропорционально filled_qty)
            if plan.targets:
                await self._setup_ladder_tp(plan, use_filled_qty=True)

        except Exception as e:
            logger.error(f"Error setting SL/TP for partial: {e}", exc_info=True)

    async def _setup_ladder_tp(self, plan: EntryPlan, use_filled_qty: bool = False):
        """Установить ladder TP ордера"""
        try:
            instrument_info = await self.client.get_instrument_info(plan.symbol)
            tick_size = instrument_info.get('tickSize', '0.01')
            qty_step = instrument_info.get('qtyStep', '0.001')

            base_qty = plan.filled_qty if use_filled_qty else plan.total_qty
            order_side = "Buy" if plan.side == "Long" else "Sell"

            tp_levels = []
            for target in plan.targets:
                partial_pct = target.get('partial_close_pct', 100)
                tp_qty_raw = (base_qty * partial_pct) / 100
                tp_qty = round_qty(tp_qty_raw, qty_step, round_down=True)

                if tp_qty > 0:
                    tp_levels.append({
                        'price': round_price(target['price'], tick_size),
                        'qty': tp_qty
                    })

            if tp_levels:
                await self.client.place_ladder_tp(
                    symbol=plan.symbol,
                    position_side=order_side,
                    tp_levels=tp_levels,
                    client_order_id_prefix=f"{plan.plan_id[:15]}_tp"
                )
                logger.info(f"Ladder TP set: {len(tp_levels)} levels for {plan.symbol}")

        except Exception as e:
            logger.error(f"Error setting ladder TP: {e}", exc_info=True)

    # ==================== Notifications ====================

    async def _notify_plan_activated(self, plan: EntryPlan, placed_count: int):
        """Уведомление об активации плана"""
        try:
            side_emoji = "🟢" if plan.side == "Long" else "🔴"
            orders = plan.get_orders()

            message = f"""
📋 <b>Entry Plan активирован!</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}
📊 Mode: {plan.mode}

<b>Entry Orders ({placed_count}):</b>
"""
            for i, order in enumerate(orders, 1):
                status_icon = "✅" if order.status == "placed" else "❌"
                message += f"{status_icon} E{i}: ${order.price:.2f} ({order.size_pct:.0f}%)\n"

            message += f"""
🛑 <b>Stop:</b> ${plan.stop_price:.2f}
⏰ <b>Valid:</b> {plan.time_valid_hours}h

<i>Ожидаю исполнения ордеров...</i>
"""

            await self.bot.send_message(
                chat_id=plan.user_id,
                text=message.strip(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send activation notification: {e}")

    async def _notify_order_filled(self, plan: EntryPlan, order: EntryOrder):
        """Уведомление о fill одного ордера"""
        try:
            side_emoji = "🟢" if plan.side == "Long" else "🔴"

            message = f"""
🔔 <b>Entry Order Filled!</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}

⚡ <b>{order.tag}:</b> ${order.fill_price:.2f}
📦 <b>Qty:</b> {order.qty:.4f}

📊 <b>Progress:</b> {plan.fill_percentage:.0f}% ({plan.filled_orders_count}/{len(plan.orders)})
💰 <b>Avg Entry:</b> ${plan.avg_entry_price:.2f}
"""

            await self.bot.send_message(
                chat_id=plan.user_id,
                text=message.strip(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send fill notification: {e}")

    async def _notify_plan_completed(self, plan: EntryPlan):
        """Уведомление о полном завершении плана"""
        try:
            side_emoji = "🟢" if plan.side == "Long" else "🔴"

            message = f"""
✅ <b>Entry Plan Complete!</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}

⚡ <b>Avg Entry:</b> ${plan.avg_entry_price:.2f}
📦 <b>Total Qty:</b> {plan.filled_qty:.4f}
🛑 <b>Stop:</b> ${plan.stop_price:.2f}

<b>Entry Fills:</b>
"""
            for order in plan.get_filled_orders():
                message += f"   • {order.tag}: ${order.fill_price:.2f} x {order.qty:.4f}\n"

            if plan.targets:
                message += "\n<b>TP Levels:</b>\n"
                for i, target in enumerate(plan.targets, 1):
                    message += f"   🎯 TP{i}: ${target['price']:.2f} ({target.get('partial_close_pct', 100)}%)\n"

            message += "\n<i>✅ SL/TP установлены автоматически</i>"

            await self.bot.send_message(
                chat_id=plan.user_id,
                text=message.strip(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send completion notification: {e}")

    async def _notify_plan_cancelled(self, plan: EntryPlan, reason: str):
        """Уведомление об отмене плана (без позиции)"""
        try:
            message = f"""
❌ <b>Entry Plan Cancelled</b>

<b>{plan.symbol}</b> {plan.side.upper()}
📋 Mode: {plan.mode}

<b>Reason:</b> {reason}

<i>Все ордера отменены. Позиция не открыта.</i>
"""

            await self.bot.send_message(
                chat_id=plan.user_id,
                text=message.strip(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send cancel notification: {e}")

    async def _notify_plan_cancelled_with_position(self, plan: EntryPlan, reason: str):
        """Уведомление об отмене плана с частичной позицией"""
        try:
            side_emoji = "🟢" if plan.side == "Long" else "🔴"

            message = f"""
⚠️ <b>Entry Plan Cancelled (Partial Position)</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}

<b>Reason:</b> {reason}

📊 <b>Filled:</b> {plan.fill_percentage:.0f}% ({plan.filled_orders_count}/{len(plan.orders)})
⚡ <b>Avg Entry:</b> ${plan.avg_entry_price:.2f}
📦 <b>Qty:</b> {plan.filled_qty:.4f}

🛑 <b>Stop:</b> ${plan.stop_price:.2f}

<i>✅ SL/TP установлены на частичную позицию</i>
"""

            await self.bot.send_message(
                chat_id=plan.user_id,
                text=message.strip(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send partial cancel notification: {e}")


def create_entry_plan_monitor(
    bot: Bot,
    trade_logger: TradeLogger,
    testnet: bool = False,
    check_interval: int = 10
) -> EntryPlanMonitor:
    """Создать экземпляр EntryPlanMonitor"""
    return EntryPlanMonitor(
        bot=bot,
        trade_logger=trade_logger,
        check_interval=check_interval,
        testnet=testnet
    )
