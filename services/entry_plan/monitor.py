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

from services.base_monitor import BaseMonitor
from services.bybit_client_pool import client_pool
from services.entry_plan.models import EntryPlan, EntryOrder
from services.entry_plan.redis_storage import EntryPlanRedisStorage
from services.entry_plan.order_executor import (
    evaluate_activation,
    evaluate_cancel_condition,
    is_invalidation_cancel,
    place_entry_orders,
    cancel_plan_orders,
    close_partial_position,
    setup_stop_loss,
    cancel_existing_tp,
    setup_ladder_tp,
)
from services.entry_plan.notification import (
    notify_plan_activated,
    notify_order_filled,
    notify_plan_completed,
    notify_plan_cancelled,
    notify_plan_cancelled_with_position,
    notify_plan_cancelled_position_closed,
    notify_sl_tp_set_early,
    notify_tp_updated,
    notify_tp_update_failed,
)
from services.trade_logger import TradeLogger

logger = logging.getLogger(__name__)


class EntryPlanMonitor(BaseMonitor):
    """
    Мониторинг Entry Plans с несколькими ордерами.

    Ответственности:
    1. Хранение активных планов (Redis + in-memory cache)
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
        testnet: bool = False,
        redis_url: str = None
    ):
        super().__init__(check_interval=check_interval)
        self.bot = bot
        self.trade_logger = trade_logger
        self.testnet = testnet  # Default, но каждый plan имеет свой testnet флаг

        # Redis storage
        self.storage = EntryPlanRedisStorage(redis_url)

        # Хранение планов: {plan_id: EntryPlan} (in-memory cache)
        self.active_plans: Dict[str, EntryPlan] = {}

    @property
    def monitor_name(self) -> str:
        return "Entry plan monitor"

    def _get_client(self, testnet: bool):
        """Получить Bybit клиент для нужного режима (testnet/live)"""
        return client_pool.get_client(testnet)

    # ==================== Public API ====================

    async def get_plan(self, plan_id: str) -> Optional[EntryPlan]:
        """
        Получить план по ID.
        Сначала ищет в in-memory cache, затем в Redis.
        """
        # 1. Проверить in-memory cache
        if plan_id in self.active_plans:
            return self.active_plans[plan_id]

        # 2. Попробовать загрузить из Redis
        return await self.storage.get_plan(plan_id)

    async def get_user_plans(
        self,
        user_id: int,
        include_completed: bool = False
    ) -> List[EntryPlan]:
        """
        Получить все планы пользователя.

        Args:
            user_id: ID пользователя
            include_completed: Включать завершённые/отменённые планы

        Returns:
            Список EntryPlan отсортированный по created_at (новые первые)
        """
        plans = []

        # 1. Планы из in-memory cache
        for plan in self.active_plans.values():
            if plan.user_id == user_id:
                if include_completed or plan.status not in ('cancelled', 'filled'):
                    plans.append(plan)

        # 2. Если нужны завершённые — загрузить из Redis
        if include_completed:
            redis_plans = await self.storage.get_user_plans(user_id)
            for plan in redis_plans:
                # Пропустить уже добавленные из cache
                if not any(p.plan_id == plan.plan_id for p in plans):
                    plans.append(plan)

        # Сортировка: новые первые
        plans.sort(key=lambda p: p.created_at, reverse=True)
        return plans

    async def get_active_plans_count(self, user_id: int = None) -> int:
        """Получить количество активных планов (опционально для user)"""
        if user_id:
            return sum(
                1 for p in self.active_plans.values()
                if p.user_id == user_id and p.status not in ('cancelled', 'filled')
            )
        return len(self.active_plans)

    async def register_plan(self, plan: EntryPlan):
        """Зарегистрировать новый план для мониторинга."""
        self.active_plans[plan.plan_id] = plan
        await self.storage.save_plan(plan)

        logger.info(
            f"Plan {plan.plan_id} registered: {plan.symbol} {plan.side}, "
            f"{len(plan.orders)} orders, mode={plan.mode}"
        )

        # Если activation_type = immediate, сразу активируем
        if plan.activation_type == "immediate":
            await self._activate_plan(plan)

    async def unregister_plan(self, plan_id: str):
        """Убрать план из мониторинга"""
        if plan_id in self.active_plans:
            del self.active_plans[plan_id]
            await self.storage.delete_plan(plan_id)
            logger.info(f"Plan {plan_id} unregistered")

    # ==================== Lifecycle Hooks ====================

    async def _on_start(self):
        """Hook: подключение к Redis и загрузка планов при старте"""
        await self.storage.connect()

        if self.storage.use_redis:
            loaded_plans = await self.storage.load_active_plans()
            self.active_plans.update(loaded_plans)
            if loaded_plans:
                logger.info(f"Restored {len(loaded_plans)} entry plans from Redis")

    async def _on_stop(self):
        """Hook: закрытие Redis при остановке"""
        await self.storage.close()

    # ==================== Main Loop ====================

    async def _check_cycle(self):
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
        """Проверить условия активации плана с Direction sanity check"""
        try:
            client = self._get_client(plan.testnet)
            ticker = await client.get_tickers(plan.symbol)
            current_price = float(ticker.get('markPrice', 0))

            # DEBUG: логируем источник цены для диагностики
            ticker_symbol = ticker.get('symbol', 'UNKNOWN')
            logger.debug(
                f"Activation check: plan.symbol={plan.symbol}, "
                f"ticker.symbol={ticker_symbol}, markPrice={current_price:.2f}"
            )

            # Sanity: проверяем что ticker вернул правильный символ
            if ticker_symbol != plan.symbol:
                logger.error(
                    f"SYMBOL MISMATCH! plan={plan.symbol} vs ticker={ticker_symbol}. "
                    f"Skipping activation check."
                )
                return

            if not current_price:
                return

            should_activate, reject_reason = evaluate_activation(
                activation_type=plan.activation_type,
                activation_level=plan.activation_level,
                current_price=current_price,
                max_distance_pct=plan.max_distance_pct,
                side=plan.side
            )

            if should_activate:
                await self._activate_plan(plan)
            elif reject_reason:
                # Direction sanity failed — отменяем план
                logger.warning(f"Plan {plan.plan_id} rejected: {reject_reason}")
                await self._cancel_plan(plan, f"direction_sanity: {reject_reason}")

        except Exception as e:
            logger.error(f"Error checking activation for plan {plan.plan_id}: {e}")

    async def _activate_plan(self, plan: EntryPlan):
        """Активировать план и разместить все entry ордера"""
        logger.info(f"Activating plan {plan.plan_id} for {plan.symbol}")

        plan.is_activated = True
        plan.activated_at = datetime.now(timezone.utc).isoformat()
        plan.status = "active"

        # Размещаем ордера
        placed_count = await place_entry_orders(plan)

        # Сохраняем обновлённый план в Redis
        await self.storage.update_plan(plan)

        # Уведомляем пользователя
        if placed_count > 0:
            await notify_plan_activated(self.bot, plan, placed_count)

    # ==================== Cancel Conditions ====================

    async def _check_cancel_conditions(self, plan: EntryPlan) -> tuple[bool, str]:
        """Проверить условия отмены плана."""
        if not plan.cancel_if:
            return False, ""

        try:
            client = self._get_client(plan.testnet)
            ticker = await client.get_tickers(plan.symbol)

            # DEBUG: проверяем символ
            ticker_symbol = ticker.get('symbol', 'UNKNOWN')
            if ticker_symbol != plan.symbol:
                logger.error(
                    f"SYMBOL MISMATCH in cancel check! plan={plan.symbol} vs ticker={ticker_symbol}"
                )
                return False, ""

            prices = {
                'mark': float(ticker.get('markPrice', 0)),
                'last': float(ticker.get('lastPrice', 0)),
                'high_24h': float(ticker.get('highPrice24h', 0)),
                'low_24h': float(ticker.get('lowPrice24h', 0)),
            }

            for condition in plan.cancel_if:
                should_cancel, reason = evaluate_cancel_condition(
                    condition=condition,
                    prices=prices,
                    plan_created_at=plan.created_at,
                    time_valid_hours=plan.time_valid_hours
                )

                if should_cancel:
                    return True, reason

            return False, ""

        except Exception as e:
            logger.error(f"Error checking cancel conditions: {e}")
            return False, ""

    async def _cancel_plan(self, plan: EntryPlan, reason: str):
        """Отменить план с partial fill policy."""
        logger.info(f"Cancelling plan {plan.plan_id}: {reason}")

        plan.status = "cancelled"
        plan.cancel_reason = reason

        # Отменяем все открытые ордера
        await cancel_plan_orders(plan)

        # Пересчитываем метрики
        plan.recalculate_metrics()

        # === METRICS: filled_pct_at_cancel ===
        plan.filled_pct_at_cancel = plan.fill_percentage
        logger.info(f"Plan cancelled at {plan.filled_pct_at_cancel:.1f}% fill")

        # Сохраняем отменённый план (для истории/аналитики) перед удалением
        await self.storage.update_plan(plan)

        if plan.has_fills:
            fill_pct = plan.fill_percentage
            is_invalidation = is_invalidation_cancel(reason)

            # === PARTIAL FILL POLICY ===
            # Закрываем маленькую позицию ТОЛЬКО при инвалидации
            if fill_pct < plan.min_fill_pct_to_keep and is_invalidation:
                logger.info(
                    f"Plan fill {fill_pct:.0f}% < {plan.min_fill_pct_to_keep:.0f}% "
                    f"+ invalidation ({reason}) → closing position market"
                )
                await close_partial_position(plan)
                await notify_plan_cancelled_position_closed(self.bot, plan, reason)
            else:
                # Достаточно заполнено ИЛИ не инвалидация → оставляем с SL/TP
                if fill_pct < plan.min_fill_pct_to_keep:
                    logger.info(
                        f"Plan fill {fill_pct:.0f}% < {plan.min_fill_pct_to_keep:.0f}% "
                        f"but NOT invalidation → keeping position with SL/TP"
                    )
                else:
                    logger.info(
                        f"Plan fill {fill_pct:.0f}% >= {plan.min_fill_pct_to_keep:.0f}% "
                        f"→ keeping position with SL/TP"
                    )
                await self._setup_sl_tp_for_partial(plan)
                await notify_plan_cancelled_with_position(self.bot, plan, reason)
        else:
            # Нет fills — отменяем сделку в trade_logger
            await self._cancel_trade_no_fills(plan, reason)
            await notify_plan_cancelled(self.bot, plan, reason)

        # Убираем из мониторинга
        await self.unregister_plan(plan.plan_id)

    async def _cancel_trade_no_fills(self, plan: EntryPlan, reason: str):
        """Отменить сделку в trade_logger когда Entry Plan отменён без fills"""
        try:
            await self.trade_logger.cancel_trade(
                user_id=plan.user_id,
                trade_id=plan.trade_id,
                reason=reason,
                testnet=plan.testnet
            )
            logger.info(f"Trade {plan.trade_id} cancelled in trade_logger: {reason}")
        except Exception as e:
            logger.error(f"Failed to cancel trade in trade_logger: {e}")

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
                client = self._get_client(plan.testnet)
                order_info = await client.get_order(
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
                    await notify_order_filled(self.bot, plan, order)

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

            # === METRICS: First fill ===
            if plan.has_fills and not plan.first_fill_at:
                plan.first_fill_at = datetime.now(timezone.utc).isoformat()
                # Рассчитываем время до первого fill
                if plan.activated_at:
                    try:
                        activated = datetime.fromisoformat(plan.activated_at.replace('Z', '+00:00'))
                        now = datetime.now(timezone.utc)
                        plan.time_to_first_fill_sec = (now - activated).total_seconds()
                        logger.info(f"Time to first fill: {plan.time_to_first_fill_sec:.1f}s")
                    except Exception:
                        pass

            # === PROTECT AFTER FIRST FILL ===
            if plan.protect_after_first_fill and plan.has_fills:
                # SL
                if not plan.sl_set:
                    await self._setup_sl_after_first_fill(plan)

                # TP (первичная установка)
                if not plan.tp_set:
                    await self._setup_tp_after_first_fill(plan)
                    # Уведомляем о SL+TP
                    await notify_sl_tp_set_early(self.bot, plan)
                else:
                    # TP уже есть → проверяем нужно ли обновить (qty вырос)
                    await self._update_tp_for_new_fill(plan)

            # Проверить завершение плана
            if plan.is_complete:
                plan.status = "filled"
                plan.completed_at = datetime.now(timezone.utc).isoformat()
                # Рассчитываем время до полного fill
                if plan.activated_at:
                    try:
                        activated = datetime.fromisoformat(plan.activated_at.replace('Z', '+00:00'))
                        now = datetime.now(timezone.utc)
                        plan.time_to_full_fill_sec = (now - activated).total_seconds()
                        logger.info(f"Time to full fill: {plan.time_to_full_fill_sec:.1f}s")
                    except Exception:
                        pass

            # Сохраняем обновлённый план в Redis
            await self.storage.update_plan(plan)

        # === RECOVERY: Проверяем TP для старых планов с fills но без TP ===
        if (plan.protect_after_first_fill and
            plan.has_fills and
            not plan.tp_set and
            plan.targets):
            logger.info(f"Recovery: setting TP for plan {plan.plan_id} (migration)")
            await self._setup_tp_after_first_fill(plan)
            await notify_sl_tp_set_early(self.bot, plan)

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

    # ==================== SL/TP Setup ====================

    async def _setup_sl_after_first_fill(self, plan: EntryPlan):
        """Установить SL после первого fill для защиты позиции"""
        success = await setup_stop_loss(plan)
        if success:
            plan.sl_set = True
            await self.storage.update_plan(plan)
            logger.info(
                f"SL set after first fill: {plan.symbol} @ ${plan.stop_price:.2f} "
                f"(filled {plan.fill_percentage:.0f}%)"
            )

    async def _setup_tp_after_first_fill(self, plan: EntryPlan):
        """Установить ladder TP после первого fill"""
        if not plan.targets:
            return

        success = await setup_ladder_tp(plan, use_filled_qty=True)
        if success:
            plan.tp_set = True
            plan.tp_filled_qty_at_set = plan.filled_qty
            await self.storage.update_plan(plan)
            logger.info(
                f"TP set after first fill: {plan.symbol}, "
                f"{len(plan.targets)} levels (filled_qty={plan.filled_qty:.4f})"
            )

    async def _update_tp_for_new_fill(self, plan: EntryPlan):
        """Обновить TP ордера после нового fill."""
        if not plan.targets:
            return

        # Проверяем нужно ли обновлять (qty изменился)
        if plan.tp_set and plan.filled_qty > plan.tp_filled_qty_at_set:
            logger.info(
                f"Updating TP for plan {plan.plan_id}: "
                f"old_qty={plan.tp_filled_qty_at_set:.4f} → new_qty={plan.filled_qty:.4f}"
            )

            # Отменяем старые TP
            await cancel_existing_tp(plan)

            # Ставим новые TP на обновлённый qty с retry
            success = False
            for attempt in range(3):
                success = await setup_ladder_tp(plan, use_filled_qty=True)
                if success:
                    break
                logger.warning(f"TP setup attempt {attempt + 1}/3 failed, retrying...")
                await asyncio.sleep(1)

            if success:
                plan.tp_filled_qty_at_set = plan.filled_qty
                await self.storage.update_plan(plan)
                # Уведомляем пользователя ТОЛЬКО при успешном обновлении
                await notify_tp_updated(self.bot, plan)
            else:
                # TP не удалось установить — логируем и уведомляем
                logger.error(
                    f"Failed to update TP for plan {plan.plan_id} after 3 attempts. "
                    f"Old TP cancelled, new TP not placed!"
                )
                await notify_tp_update_failed(self.bot, plan)

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
        await notify_plan_completed(self.bot, plan)

        # Убираем из мониторинга
        await self.unregister_plan(plan.plan_id)

    async def _setup_sl_tp(self, plan: EntryPlan):
        """Установить SL и ladder TP для позиции (при полном завершении плана)"""
        try:
            # SL (если ещё не установлен)
            if not plan.sl_set:
                success = await setup_stop_loss(plan)
                if success:
                    plan.sl_set = True

            # TP: финальное обновление на полный qty
            if plan.targets:
                # Если TP уже были и qty изменился → обновляем
                if plan.tp_set and plan.filled_qty > plan.tp_filled_qty_at_set:
                    logger.info(f"Final TP update: qty {plan.tp_filled_qty_at_set:.4f} → {plan.filled_qty:.4f}")
                    await cancel_existing_tp(plan)
                    # Retry логика
                    success = False
                    for attempt in range(3):
                        success = await setup_ladder_tp(plan, use_filled_qty=True)
                        if success:
                            break
                        logger.warning(f"Final TP setup attempt {attempt + 1}/3 failed")
                        await asyncio.sleep(1)
                    if success:
                        plan.tp_filled_qty_at_set = plan.filled_qty
                    else:
                        logger.error(f"Failed to set final TP for plan {plan.plan_id}")
                        await notify_tp_update_failed(self.bot, plan)
                elif not plan.tp_set:
                    # TP ещё не было → ставим с retry
                    success = False
                    for attempt in range(3):
                        success = await setup_ladder_tp(plan, use_filled_qty=True)
                        if success:
                            break
                        logger.warning(f"Initial TP setup attempt {attempt + 1}/3 failed")
                        await asyncio.sleep(1)
                    if success:
                        plan.tp_set = True
                        plan.tp_filled_qty_at_set = plan.filled_qty
                    else:
                        logger.error(f"Failed to set initial TP for plan {plan.plan_id}")
                        await notify_tp_update_failed(self.bot, plan)

            await self.storage.update_plan(plan)

        except Exception as e:
            logger.error(f"Error setting SL/TP: {e}", exc_info=True)

    async def _setup_sl_tp_for_partial(self, plan: EntryPlan):
        """Установить SL/TP для частичной позиции (при отмене плана)"""
        if plan.filled_qty <= 0:
            return

        try:
            # SL (если ещё не установлен)
            if not plan.sl_set:
                success = await setup_stop_loss(plan)
                if success:
                    plan.sl_set = True
                    logger.info(f"SL set at ${plan.stop_price:.2f} for partial position")

            # TP: финальное обновление если нужно
            if plan.targets:
                if plan.tp_set and plan.filled_qty != plan.tp_filled_qty_at_set:
                    # TP были на другой qty → обновляем с retry
                    logger.info(f"Partial cancel: updating TP qty {plan.tp_filled_qty_at_set:.4f} → {plan.filled_qty:.4f}")
                    await cancel_existing_tp(plan)
                    success = False
                    for attempt in range(3):
                        success = await setup_ladder_tp(plan, use_filled_qty=True)
                        if success:
                            break
                        logger.warning(f"Partial TP setup attempt {attempt + 1}/3 failed")
                        await asyncio.sleep(1)
                    if success:
                        plan.tp_filled_qty_at_set = plan.filled_qty
                    else:
                        logger.error(f"Failed to set TP for partial position {plan.plan_id}")
                elif not plan.tp_set:
                    # TP ещё не было → ставим с retry
                    success = False
                    for attempt in range(3):
                        success = await setup_ladder_tp(plan, use_filled_qty=True)
                        if success:
                            break
                        logger.warning(f"Partial initial TP attempt {attempt + 1}/3 failed")
                        await asyncio.sleep(1)
                    if success:
                        plan.tp_set = True
                        plan.tp_filled_qty_at_set = plan.filled_qty
                    else:
                        logger.error(f"Failed to set initial TP for partial {plan.plan_id}")

            await self.storage.update_plan(plan)

        except Exception as e:
            logger.error(f"Error setting SL/TP for partial: {e}", exc_info=True)


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
