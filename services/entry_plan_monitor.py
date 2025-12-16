"""
Entry Plan Monitor

Мониторинг Entry Plans с несколькими ордерами (ladder entry).
Отслеживает активацию, fills, cancel условия и устанавливает SL/TP.
Хранит планы в Redis для персистентности.
"""
import asyncio
import html
import json
import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone
from aiogram import Bot
import redis.asyncio as aioredis

import config
from services.bybit import BybitClient
from services.entry_plan import EntryPlan, EntryOrder
from services.trade_logger import TradeLogger, TradeRecord, calculate_fee, calculate_margin
from utils.validators import round_qty, round_price

logger = logging.getLogger(__name__)

# Redis key prefix
ENTRY_PLAN_KEY_PREFIX = "entry_plan:"
ENTRY_PLANS_INDEX_KEY = "entry_plans:active"
ENTRY_PLANS_USER_PREFIX = "entry_plans:user:"  # {user_id} -> set of plan_ids

# TTL для завершённых/отменённых планов (7 дней для истории)
COMPLETED_PLAN_TTL_SECONDS = 7 * 24 * 3600


class EntryPlanMonitor:
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
        self.bot = bot
        self.trade_logger = trade_logger
        self.check_interval = check_interval
        self.testnet = testnet  # Default, но каждый plan имеет свой testnet флаг

        # Bybit clients (lazy init per testnet mode)
        self._clients: Dict[bool, BybitClient] = {}

        # Redis для персистентности
        self.redis_url = redis_url or f"redis://{config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}"
        self.redis: Optional[aioredis.Redis] = None
        self.use_redis = True

        # Хранение планов: {plan_id: EntryPlan} (in-memory cache)
        self.active_plans: Dict[str, EntryPlan] = {}

        self._running = False
        self._task: Optional[asyncio.Task] = None

    def _get_client(self, testnet: bool) -> BybitClient:
        """Получить Bybit клиент для нужного режима (testnet/live)"""
        if testnet not in self._clients:
            self._clients[testnet] = BybitClient(testnet=testnet)
        return self._clients[testnet]

    # ==================== Redis Operations ====================

    async def _connect_redis(self):
        """Подключиться к Redis"""
        if self.redis:
            return True

        try:
            self.redis = await aioredis.from_url(
                self.redis_url,
                password=config.REDIS_PASSWORD,
                decode_responses=True
            )
            await self.redis.ping()
            logger.info(f"Entry plan monitor connected to Redis: {self.redis_url}")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Using in-memory only.")
            self.redis = None
            self.use_redis = False
            return False

    async def _close_redis(self):
        """Закрыть соединение с Redis"""
        if self.redis:
            await self.redis.close()
            self.redis = None

    async def _save_plan_to_redis(self, plan: EntryPlan, with_ttl: bool = False):
        """
        Сохранить план в Redis.

        Args:
            plan: EntryPlan объект
            with_ttl: Установить TTL (для завершённых/отменённых планов)
        """
        if not self.use_redis or not self.redis:
            return

        try:
            key = f"{ENTRY_PLAN_KEY_PREFIX}{plan.plan_id}"
            plan_json = json.dumps(plan.to_dict())

            if with_ttl:
                await self.redis.set(key, plan_json, ex=COMPLETED_PLAN_TTL_SECONDS)
            else:
                await self.redis.set(key, plan_json)

            # Добавить в индекс активных планов (если активен)
            if plan.status not in ('cancelled', 'filled'):
                await self.redis.sadd(ENTRY_PLANS_INDEX_KEY, plan.plan_id)
            else:
                # Удалить из активных при завершении
                await self.redis.srem(ENTRY_PLANS_INDEX_KEY, plan.plan_id)

            # Добавить в индекс планов пользователя
            user_key = f"{ENTRY_PLANS_USER_PREFIX}{plan.user_id}"
            await self.redis.sadd(user_key, plan.plan_id)

            logger.debug(f"Plan {plan.plan_id} saved to Redis (ttl={with_ttl})")
        except Exception as e:
            logger.error(f"Failed to save plan to Redis: {e}")

    async def _update_plan_in_redis(self, plan: EntryPlan):
        """Обновить план в Redis"""
        # Если план завершён — сохраняем с TTL
        with_ttl = plan.status in ('cancelled', 'filled')
        await self._save_plan_to_redis(plan, with_ttl=with_ttl)

    async def _delete_plan_from_redis(self, plan_id: str):
        """Удалить план из Redis"""
        if not self.use_redis or not self.redis:
            return

        try:
            key = f"{ENTRY_PLAN_KEY_PREFIX}{plan_id}"
            await self.redis.delete(key)
            await self.redis.srem(ENTRY_PLANS_INDEX_KEY, plan_id)
            logger.debug(f"Plan {plan_id} deleted from Redis")
        except Exception as e:
            logger.error(f"Failed to delete plan from Redis: {e}")

    async def _load_plans_from_redis(self) -> Dict[str, EntryPlan]:
        """Загрузить все активные планы из Redis"""
        plans = {}

        if not self.use_redis or not self.redis:
            return plans

        try:
            # Получить все plan_id из индекса
            plan_ids = await self.redis.smembers(ENTRY_PLANS_INDEX_KEY)

            for plan_id in plan_ids:
                key = f"{ENTRY_PLAN_KEY_PREFIX}{plan_id}"
                plan_json = await self.redis.get(key)

                if plan_json:
                    try:
                        plan_data = json.loads(plan_json)
                        plan = EntryPlan.from_dict(plan_data)
                        plans[plan_id] = plan
                    except Exception as e:
                        logger.error(f"Failed to parse plan {plan_id}: {e}")
                        # Удалить битый план из индекса
                        await self.redis.srem(ENTRY_PLANS_INDEX_KEY, plan_id)
                else:
                    # План не найден, удалить из индекса
                    await self.redis.srem(ENTRY_PLANS_INDEX_KEY, plan_id)

            logger.info(f"Loaded {len(plans)} entry plans from Redis")
        except Exception as e:
            logger.error(f"Failed to load plans from Redis: {e}")

        return plans

    async def get_plan(self, plan_id: str) -> Optional[EntryPlan]:
        """
        Получить план по ID.

        Сначала ищет в in-memory cache, затем в Redis.
        """
        # 1. Проверить in-memory cache
        if plan_id in self.active_plans:
            return self.active_plans[plan_id]

        # 2. Попробовать загрузить из Redis
        if self.use_redis and self.redis:
            try:
                key = f"{ENTRY_PLAN_KEY_PREFIX}{plan_id}"
                plan_json = await self.redis.get(key)
                if plan_json:
                    plan_data = json.loads(plan_json)
                    return EntryPlan.from_dict(plan_data)
            except Exception as e:
                logger.error(f"Failed to get plan {plan_id} from Redis: {e}")

        return None

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
        if include_completed and self.use_redis and self.redis:
            try:
                user_key = f"{ENTRY_PLANS_USER_PREFIX}{user_id}"
                plan_ids = await self.redis.smembers(user_key)

                for plan_id in plan_ids:
                    # Пропустить уже добавленные из cache
                    if any(p.plan_id == plan_id for p in plans):
                        continue

                    key = f"{ENTRY_PLAN_KEY_PREFIX}{plan_id}"
                    plan_json = await self.redis.get(key)

                    if plan_json:
                        try:
                            plan_data = json.loads(plan_json)
                            plan = EntryPlan.from_dict(plan_data)
                            plans.append(plan)
                        except Exception as e:
                            logger.error(f"Failed to parse plan {plan_id}: {e}")
                    else:
                        # План истёк — удалить из индекса пользователя
                        await self.redis.srem(user_key, plan_id)
            except Exception as e:
                logger.error(f"Failed to get user plans from Redis: {e}")

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

    # ==================== Public API ====================

    async def register_plan(self, plan: EntryPlan):
        """
        Зарегистрировать новый план для мониторинга.

        Args:
            plan: EntryPlan объект
        """
        self.active_plans[plan.plan_id] = plan
        await self._save_plan_to_redis(plan)

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
            await self._delete_plan_from_redis(plan_id)
            logger.info(f"Plan {plan_id} unregistered")

    async def start(self):
        """Запустить мониторинг в фоновом режиме"""
        if self._running:
            logger.warning("Entry plan monitor already running")
            return

        # Подключиться к Redis
        await self._connect_redis()

        # Загрузить планы из Redis
        if self.use_redis:
            loaded_plans = await self._load_plans_from_redis()
            self.active_plans.update(loaded_plans)
            if loaded_plans:
                logger.info(f"Restored {len(loaded_plans)} entry plans from Redis")

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

        await self._close_redis()
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
        """Проверить условия активации плана с Direction sanity check"""
        try:
            client = self._get_client(plan.testnet)
            ticker = await client.get_tickers(plan.symbol)
            current_price = float(ticker.get('markPrice', 0))

            # DEBUG: логируем источник цены для диагностики
            ticker_symbol = ticker.get('symbol', 'UNKNOWN')
            logger.info(
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

            should_activate, reject_reason = self._evaluate_activation(
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

    def _evaluate_activation(
        self,
        activation_type: str,
        activation_level: Optional[float],
        current_price: float,
        max_distance_pct: float,
        side: str = None
    ) -> tuple[bool, str]:
        """
        Оценить условие активации с Direction sanity check.

        Direction sanity:
        - Long план на 95200, цена уже 96000 → reject (цена ушла вверх)
        - Short план на 95200, цена уже 94000 → reject (цена ушла вниз)

        Returns:
            (should_activate, reject_reason)
        """
        if activation_type == "immediate":
            return True, ""

        if not activation_level:
            return True, ""  # Нет уровня = сразу активируем

        # === DIRECTION SANITY CHECK ===
        # Проверяем, что цена не ушла слишком далеко в "неправильном" направлении
        if side:
            distance_pct = (current_price - activation_level) / activation_level * 100

            if side == "Long":
                # Для Long: цена не должна быть выше activation_level на > max_distance_pct
                # (иначе план устарел — цена ушла вверх)
                if distance_pct > max_distance_pct:
                    return False, f"price_moved_above (current ${current_price:.2f} > level ${activation_level:.2f})"

            elif side == "Short":
                # Для Short: цена не должна быть ниже activation_level на > max_distance_pct
                # (иначе план устарел — цена ушла вниз)
                if distance_pct < -max_distance_pct:
                    return False, f"price_moved_below (current ${current_price:.2f} < level ${activation_level:.2f})"

        # === ACTIVATION CONDITIONS ===
        if activation_type == "touch":
            distance_pct = abs(current_price - activation_level) / activation_level * 100
            if distance_pct <= max_distance_pct:
                return True, ""
            return False, ""

        if activation_type == "price_above":
            if current_price >= activation_level:
                return True, ""
            return False, ""

        if activation_type == "price_below":
            if current_price <= activation_level:
                return True, ""
            return False, ""

        return False, ""

    async def _activate_plan(self, plan: EntryPlan):
        """Активировать план и разместить все entry ордера"""
        logger.info(f"Activating plan {plan.plan_id} for {plan.symbol}")

        plan.is_activated = True
        plan.activated_at = datetime.now(timezone.utc).isoformat()
        plan.status = "active"

        client = self._get_client(plan.testnet)

        # Получить instrument info для округления
        instrument_info = await client.get_instrument_info(plan.symbol)
        tick_size = instrument_info.get('tickSize', '0.01')
        qty_step = instrument_info.get('qtyStep', '0.001')

        # Размещаем все entry ордера
        order_side = "Buy" if plan.side == "Long" else "Sell"
        placed_count = 0

        # Короткий ID для prefix (Bybit limit = 36 chars)
        short_plan_id = plan.plan_id[:8]

        for i, order_dict in enumerate(plan.orders):
            order = EntryOrder.from_dict(order_dict)

            try:
                # Округляем цену и qty
                price_str = round_price(order.price, tick_size)
                qty_str = round_qty(order.qty, qty_step)

                # Формируем client_order_id: EP:{plan_id}:{tag}
                # Максимум 36 символов: "EP:" (3) + plan_id (8) + ":" (1) + tag (до 24)
                tag = order.tag or f"E{i+1}"
                client_id = f"EP:{short_plan_id}:{tag}"[:36]

                # Размещаем ордер
                placed_order = await client.place_order(
                    symbol=plan.symbol,
                    side=order_side,
                    order_type="Limit",
                    qty=qty_str,
                    price=price_str,
                    client_order_id=client_id
                )

                # Обновляем статус ордера
                order.mark_placed(placed_order['orderId'])
                plan.orders[i] = order.to_dict()
                placed_count += 1

                logger.info(
                    f"Entry order placed: {plan.symbol} {order_side} "
                    f"@ ${order.price:.2f} qty={order.qty} tag={order.tag} "
                    f"client_id={client_id}"
                )

            except Exception as e:
                logger.error(f"Failed to place entry order {i+1}: {e}")
                order.status = "cancelled"
                plan.orders[i] = order.to_dict()

        # Сохраняем обновлённый план в Redis
        await self._update_plan_in_redis(plan)

        # Уведомляем пользователя
        if placed_count > 0:
            await self._notify_plan_activated(plan, placed_count)

    # ==================== Cancel Conditions ====================

    async def _check_cancel_conditions(self, plan: EntryPlan) -> tuple[bool, str]:
        """
        Проверить условия отмены плана.

        Поддерживаемые условия:
        - break_below PRICE — markPrice ниже уровня (мгновенный)
        - break_above PRICE — markPrice выше уровня (мгновенный)
        - break_below_close PRICE — lastPrice ниже уровня (приближение к close)
        - break_above_close PRICE — lastPrice выше уровня (приближение к close)
        - break_below_wick PRICE — lowPrice24h ниже уровня (любое касание за 24h)
        - break_above_wick PRICE — highPrice24h выше уровня (любое касание за 24h)
        - time_valid_hours exceeded — истекло время действия

        Returns:
            (should_cancel, reason)
        """
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
                should_cancel, reason = self._evaluate_cancel_condition(
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

    def _evaluate_cancel_condition(
        self,
        condition: str,
        prices: dict,
        plan_created_at: str,
        time_valid_hours: float
    ) -> tuple[bool, str]:
        """
        Оценить одно условие отмены.

        Args:
            prices: {'mark': float, 'last': float, 'high_24h': float, 'low_24h': float}
        """
        parts = condition.split()

        # === BREAK BELOW CONDITIONS ===
        if parts[0] == "break_below" and len(parts) >= 2:
            level = float(parts[1])
            if prices['mark'] < level:
                return True, f"break_below ${level:.2f} (mark=${prices['mark']:.2f})"

        if parts[0] == "break_below_close" and len(parts) >= 2:
            level = float(parts[1])
            if prices['last'] < level:
                return True, f"break_below_close ${level:.2f} (last=${prices['last']:.2f})"

        if parts[0] == "break_below_wick" and len(parts) >= 2:
            level = float(parts[1])
            if prices['low_24h'] < level:
                return True, f"break_below_wick ${level:.2f} (low24h=${prices['low_24h']:.2f})"

        # === BREAK ABOVE CONDITIONS ===
        if parts[0] == "break_above" and len(parts) >= 2:
            level = float(parts[1])
            if prices['mark'] > level:
                return True, f"break_above ${level:.2f} (mark=${prices['mark']:.2f})"

        if parts[0] == "break_above_close" and len(parts) >= 2:
            level = float(parts[1])
            if prices['last'] > level:
                return True, f"break_above_close ${level:.2f} (last=${prices['last']:.2f})"

        if parts[0] == "break_above_wick" and len(parts) >= 2:
            level = float(parts[1])
            if prices['high_24h'] > level:
                return True, f"break_above_wick ${level:.2f} (high24h=${prices['high_24h']:.2f})"

        # === TIME CONDITIONS ===
        if "time_valid_hours" in condition or "time_exceeded" in condition:
            try:
                # Парсим created_at с обработкой timezone
                created_str = plan_created_at.replace('Z', '+00:00')
                created = datetime.fromisoformat(created_str)
                # Если datetime naive - добавляем UTC timezone
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)

                now = datetime.now(timezone.utc)
                hours_passed = (now - created).total_seconds() / 3600

                if hours_passed > time_valid_hours:
                    return True, f"time_exceeded ({hours_passed:.1f}h > {time_valid_hours}h)"
            except Exception as e:
                logger.error(f"Error parsing time condition: {e}")

        return False, ""

    def _is_invalidation_cancel(self, reason: str) -> bool:
        """
        Проверить, является ли причина отмены "инвалидацией" плана.

        Инвалидация = план больше не актуален:
        - break_below / break_above (цена пробила уровень)
        - direction_sanity (цена ушла от зоны)
        - time_exceeded (истекло время)

        НЕ инвалидация:
        - Ручная отмена пользователем
        - Технические ошибки
        """
        invalidation_patterns = [
            "break_below",
            "break_above",
            "direction_sanity",
            "time_exceeded",
            "price_moved_above",
            "price_moved_below"
        ]
        return any(pattern in reason.lower() for pattern in invalidation_patterns)

    async def _cancel_plan(self, plan: EntryPlan, reason: str):
        """
        Отменить план с partial fill policy.

        Policy для partial fills (<min_fill_pct_to_keep):
        - При ИНВАЛИДАЦИИ (break, timeout, direction_sanity) → закрыть позицию market
        - При других причинах → оставить с SL/TP

        Инвалидация означает что план больше не актуален и маленькая позиция
        скорее всего будет убыточной.
        """
        logger.info(f"Cancelling plan {plan.plan_id}: {reason}")

        plan.status = "cancelled"
        plan.cancel_reason = reason

        # Отменяем все открытые ордера (prefix: EP:{plan_id[:8]})
        client = self._get_client(plan.testnet)
        short_plan_id = plan.plan_id[:8]
        cancelled = await client.cancel_orders_by_prefix(
            symbol=plan.symbol,
            client_order_id_prefix=f"EP:{short_plan_id}"
        )

        logger.info(f"Cancelled {len(cancelled)} orders for plan {plan.plan_id}")

        # Пересчитываем метрики
        plan.recalculate_metrics()

        # === METRICS: filled_pct_at_cancel ===
        plan.filled_pct_at_cancel = plan.fill_percentage
        logger.info(f"Plan cancelled at {plan.filled_pct_at_cancel:.1f}% fill")

        # Сохраняем отменённый план (для истории/аналитики) перед удалением
        await self._update_plan_in_redis(plan)

        if plan.has_fills:
            fill_pct = plan.fill_percentage
            is_invalidation = self._is_invalidation_cancel(reason)

            # === PARTIAL FILL POLICY ===
            # Закрываем маленькую позицию ТОЛЬКО при инвалидации
            if fill_pct < plan.min_fill_pct_to_keep and is_invalidation:
                logger.info(
                    f"Plan fill {fill_pct:.0f}% < {plan.min_fill_pct_to_keep:.0f}% "
                    f"+ invalidation ({reason}) → closing position market"
                )
                await self._close_partial_position(plan)
                await self._notify_plan_cancelled_position_closed(plan, reason)
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
                await self._notify_plan_cancelled_with_position(plan, reason)
        else:
            # Нет fills — отменяем сделку в trade_logger
            await self._cancel_trade_no_fills(plan, reason)
            await self._notify_plan_cancelled(plan, reason)

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

    async def _close_partial_position(self, plan: EntryPlan):
        """Закрыть частичную позицию market ордером"""
        if plan.filled_qty <= 0:
            return

        try:
            # Для закрытия Long нужен Sell, для Short — Buy
            close_side = "Sell" if plan.side == "Long" else "Buy"
            client = self._get_client(plan.testnet)

            # Получаем instrument_info для округления
            instrument_info = await client.get_instrument_info(plan.symbol)
            qty_step = instrument_info.get('qtyStep', '0.001')

            qty_str = round_qty(plan.filled_qty, qty_step)

            short_plan_id = plan.plan_id[:8]
            await client.place_order(
                symbol=plan.symbol,
                side=close_side,
                order_type="Market",
                qty=qty_str,
                reduce_only=True,
                client_order_id=f"EP:{short_plan_id}:close"
            )

            logger.info(
                f"Closed partial position: {plan.symbol} {close_side} "
                f"qty={plan.filled_qty:.4f} (market)"
            )

        except Exception as e:
            logger.error(f"Failed to close partial position: {e}", exc_info=True)

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
            # Ставим SL и TP сразу после первого fill для защиты позиции
            if plan.protect_after_first_fill and plan.has_fills:
                # SL
                if not plan.sl_set:
                    await self._setup_sl_after_first_fill(plan)

                # TP (первичная установка)
                if not plan.tp_set:
                    await self._setup_tp_after_first_fill(plan)
                    # Уведомляем о SL+TP
                    await self._notify_sl_tp_set_early(plan)
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
            await self._update_plan_in_redis(plan)

        # === RECOVERY: Проверяем TP для старых планов с fills но без TP ===
        # Эта проверка нужна для планов мигрированных с tp_set=None
        if (plan.protect_after_first_fill and
            plan.has_fills and
            not plan.tp_set and
            plan.targets):
            logger.info(f"Recovery: setting TP for plan {plan.plan_id} (migration)")
            await self._setup_tp_after_first_fill(plan)
            await self._notify_sl_tp_set_early(plan)

    async def _setup_sl_after_first_fill(self, plan: EntryPlan):
        """Установить SL после первого fill для защиты позиции"""
        try:
            client = self._get_client(plan.testnet)
            trigger_type = "LastPrice" if plan.testnet else "MarkPrice"

            await client.set_trading_stop(
                symbol=plan.symbol,
                stop_loss=str(plan.stop_price),
                sl_trigger_by=trigger_type
            )

            plan.sl_set = True
            await self._update_plan_in_redis(plan)

            logger.info(
                f"SL set after first fill: {plan.symbol} @ ${plan.stop_price:.2f} "
                f"(filled {plan.fill_percentage:.0f}%)"
            )

        except Exception as e:
            logger.error(f"Failed to set SL after first fill: {e}", exc_info=True)

    async def _setup_tp_after_first_fill(self, plan: EntryPlan):
        """Установить ladder TP после первого fill"""
        if not plan.targets:
            return

        try:
            await self._setup_ladder_tp(plan, use_filled_qty=True, update_flags=True)

            logger.info(
                f"TP set after first fill: {plan.symbol}, "
                f"{len(plan.targets)} levels (filled_qty={plan.filled_qty:.4f})"
            )

        except Exception as e:
            logger.error(f"Failed to set TP after first fill: {e}", exc_info=True)

    async def _notify_sl_tp_set_early(self, plan: EntryPlan):
        """Уведомление об установке SL и TP после первого fill"""
        try:
            side_emoji = "🟢" if plan.side == "Long" else "🔴"

            message = f"""
🛡️ <b>SL/TP установлены!</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}
📊 <b>Filled:</b> {plan.fill_percentage:.0f}% ({plan.filled_orders_count}/{len(plan.orders)})
📦 <b>Qty:</b> {plan.filled_qty:.4f}

🛑 <b>Stop:</b> ${plan.stop_price:.2f}
"""
            if plan.targets:
                message += f"🎯 <b>TP:</b> {len(plan.targets)} уровней\n"
                for i, t in enumerate(plan.targets, 1):
                    message += f"   TP{i}: ${t['price']:.2f} ({t.get('partial_close_pct', 100)}%)\n"

            message += "\n<i>✅ Позиция защищена. Ожидаю остальные entry ордера...</i>"

            await self.bot.send_message(
                chat_id=plan.user_id,
                text=message.strip(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send SL/TP notification: {e}")

    async def _notify_tp_updated(self, plan: EntryPlan):
        """Уведомление об обновлении TP после добора позиции"""
        try:
            side_emoji = "🟢" if plan.side == "Long" else "🔴"

            message = f"""
🔄 <b>TP обновлены!</b>

{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}
📊 <b>Filled:</b> {plan.fill_percentage:.0f}% ({plan.filled_orders_count}/{len(plan.orders)})
📦 <b>New Qty:</b> {plan.filled_qty:.4f}

<i>TP ордера пересчитаны на новый объём позиции.</i>
"""
            await self.bot.send_message(
                chat_id=plan.user_id,
                text=message.strip(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send TP updated notification: {e}")

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
        await self.unregister_plan(plan.plan_id)

    async def _setup_sl_tp(self, plan: EntryPlan):
        """Установить SL и ladder TP для позиции (при полном завершении плана)"""
        try:
            client = self._get_client(plan.testnet)

            # SL (если ещё не установлен)
            if not plan.sl_set:
                await client.set_trading_stop(
                    symbol=plan.symbol,
                    stop_loss=str(plan.stop_price),
                    sl_trigger_by="MarkPrice" if not plan.testnet else "LastPrice"
                )
                plan.sl_set = True
                logger.info(f"SL set at ${plan.stop_price:.2f} for {plan.symbol}")

            # TP: финальное обновление на полный qty
            if plan.targets:
                # Если TP уже были и qty изменился → обновляем
                if plan.tp_set and plan.filled_qty > plan.tp_filled_qty_at_set:
                    logger.info(f"Final TP update: qty {plan.tp_filled_qty_at_set:.4f} → {plan.filled_qty:.4f}")
                    await self._cancel_existing_tp(plan)
                    await self._setup_ladder_tp(plan, use_filled_qty=True, update_flags=True)
                elif not plan.tp_set:
                    # TP ещё не было → ставим
                    await self._setup_ladder_tp(plan, use_filled_qty=True, update_flags=True)

        except Exception as e:
            logger.error(f"Error setting SL/TP: {e}", exc_info=True)

    async def _setup_sl_tp_for_partial(self, plan: EntryPlan):
        """Установить SL/TP для частичной позиции (при отмене плана)"""
        if plan.filled_qty <= 0:
            return

        try:
            client = self._get_client(plan.testnet)

            # SL (если ещё не установлен)
            if not plan.sl_set:
                await client.set_trading_stop(
                    symbol=plan.symbol,
                    stop_loss=str(plan.stop_price),
                    sl_trigger_by="MarkPrice" if not plan.testnet else "LastPrice"
                )
                plan.sl_set = True
                logger.info(f"SL set at ${plan.stop_price:.2f} for partial position")

            # TP: финальное обновление если нужно
            if plan.targets:
                if plan.tp_set and plan.filled_qty != plan.tp_filled_qty_at_set:
                    # TP были на другой qty → обновляем
                    logger.info(f"Partial cancel: updating TP qty {plan.tp_filled_qty_at_set:.4f} → {plan.filled_qty:.4f}")
                    await self._cancel_existing_tp(plan)
                    await self._setup_ladder_tp(plan, use_filled_qty=True, update_flags=True)
                elif not plan.tp_set:
                    # TP ещё не было → ставим
                    await self._setup_ladder_tp(plan, use_filled_qty=True, update_flags=True)
                # Если tp_set и qty совпадает → TP уже корректные, не трогаем

        except Exception as e:
            logger.error(f"Error setting SL/TP for partial: {e}", exc_info=True)

    async def _cancel_existing_tp(self, plan: EntryPlan):
        """Отменить существующие TP ордера плана"""
        try:
            client = self._get_client(plan.testnet)
            short_plan_id = plan.plan_id[:8]

            cancelled = await client.cancel_orders_by_prefix(
                symbol=plan.symbol,
                client_order_id_prefix=f"EP:{short_plan_id}:TP"
            )

            if cancelled:
                logger.info(f"Cancelled {len(cancelled)} existing TP orders for plan {plan.plan_id}")

            return len(cancelled)
        except Exception as e:
            logger.error(f"Error cancelling existing TP: {e}")
            return 0

    async def _setup_ladder_tp(self, plan: EntryPlan, use_filled_qty: bool = False, update_flags: bool = True):
        """
        Установить ladder TP ордера.

        Args:
            plan: EntryPlan
            use_filled_qty: Использовать filled_qty вместо total_qty
            update_flags: Обновить флаги tp_set и tp_filled_qty_at_set
        """
        if not plan.targets:
            return

        try:
            client = self._get_client(plan.testnet)
            instrument_info = await client.get_instrument_info(plan.symbol)
            lot_size = instrument_info.get('lotSizeFilter', {})
            price_filter = instrument_info.get('priceFilter', {})
            tick_size = price_filter.get('tickSize', '0.01')
            qty_step = lot_size.get('qtyStep', '0.001')
            min_order_qty = float(lot_size.get('minOrderQty', '0.001'))

            base_qty = plan.filled_qty if use_filled_qty else plan.total_qty
            position_side = "Buy" if plan.side == "Long" else "Sell"  # Сторона позиции

            logger.info(f"Setting ladder TP: base_qty={base_qty}, min_order_qty={min_order_qty}, qty_step={qty_step}")

            tp_levels = []
            skipped_qty = 0.0  # Накопленный qty от пропущенных уровней

            for target in plan.targets:
                partial_pct = target.get('partial_close_pct', 100)
                tp_qty_raw = (base_qty * partial_pct) / 100 + skipped_qty
                tp_qty = round_qty(tp_qty_raw, qty_step, round_down=True)

                if float(tp_qty) < min_order_qty:
                    # Qty слишком маленький — накапливаем для следующего уровня
                    skipped_qty = tp_qty_raw
                    logger.debug(f"TP level skipped (qty {tp_qty} < min {min_order_qty}), accumulating...")
                    continue

                skipped_qty = 0.0  # Сбрасываем после успешного добавления

                if float(tp_qty) > 0:
                    tp_levels.append({
                        'price': round_price(target['price'], tick_size),
                        'qty': tp_qty
                    })

            # Если остался skipped_qty после всех уровней — добавляем к последнему TP
            if skipped_qty > 0 and tp_levels:
                last_tp = tp_levels[-1]
                new_qty = float(last_tp['qty']) + skipped_qty
                last_tp['qty'] = round_qty(new_qty, qty_step, round_down=True)
                logger.info(f"Added remaining {skipped_qty:.4f} to last TP level")

            if tp_levels:
                short_plan_id = plan.plan_id[:8]
                await client.place_ladder_tp(
                    symbol=plan.symbol,
                    position_side=position_side,
                    tp_levels=tp_levels,
                    client_order_id_prefix=f"EP:{short_plan_id}:TP"
                )
                logger.info(
                    f"Ladder TP set: {len(tp_levels)} levels for {plan.symbol}, "
                    f"base_qty={base_qty:.4f}"
                )

                # Обновляем флаги
                if update_flags:
                    plan.tp_set = True
                    plan.tp_filled_qty_at_set = plan.filled_qty
                    await self._update_plan_in_redis(plan)

        except Exception as e:
            logger.error(f"Error setting ladder TP: {e}", exc_info=True)

    async def _update_tp_for_new_fill(self, plan: EntryPlan):
        """
        Обновить TP ордера после нового fill.

        Отменяет старые TP и ставит новые на обновлённый filled_qty.
        """
        if not plan.targets:
            return

        # Проверяем нужно ли обновлять (qty изменился)
        if plan.tp_set and plan.filled_qty > plan.tp_filled_qty_at_set:
            logger.info(
                f"Updating TP for plan {plan.plan_id}: "
                f"old_qty={plan.tp_filled_qty_at_set:.4f} → new_qty={plan.filled_qty:.4f}"
            )

            # Отменяем старые TP
            await self._cancel_existing_tp(plan)

            # Ставим новые TP на обновлённый qty
            await self._setup_ladder_tp(plan, use_filled_qty=True, update_flags=True)

            # Уведомляем пользователя
            await self._notify_tp_updated(plan)

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
            # Экранируем reason заранее чтобы избежать HTML injection
            reason_escaped = html.escape(str(reason))

            message = f"""
❌ <b>Entry Plan Cancelled</b>

<b>{html.escape(plan.symbol)}</b> {plan.side.upper()}
📋 Mode: {plan.mode}

<b>Reason:</b> {reason_escaped}

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
            reason_escaped = html.escape(str(reason))

            message = f"""
⚠️ <b>Entry Plan Cancelled (Partial Position)</b>

{side_emoji} <b>{html.escape(plan.symbol)}</b> {plan.side.upper()}

<b>Reason:</b> {reason_escaped}

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

    async def _notify_plan_cancelled_position_closed(self, plan: EntryPlan, reason: str):
        """Уведомление об отмене плана с закрытием маленькой позиции"""
        try:
            side_emoji = "🟢" if plan.side == "Long" else "🔴"
            reason_escaped = html.escape(str(reason))

            message = f"""
⚠️ <b>Entry Plan Cancelled (Position Closed)</b>

{side_emoji} <b>{html.escape(plan.symbol)}</b> {plan.side.upper()}

<b>Reason:</b> {reason_escaped}

📊 <b>Filled:</b> {plan.fill_percentage:.0f}% ({plan.filled_orders_count}/{len(plan.orders)})
⚡ <b>Avg Entry:</b> ${plan.avg_entry_price:.2f}
📦 <b>Qty:</b> {plan.filled_qty:.4f}

<i>🔄 Позиция закрыта market (fill &lt; {plan.min_fill_pct_to_keep:.0f}%)</i>
"""

            await self.bot.send_message(
                chat_id=plan.user_id,
                text=message.strip(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send position closed notification: {e}")


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
