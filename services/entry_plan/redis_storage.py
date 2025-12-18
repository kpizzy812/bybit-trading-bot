"""
Entry Plan Redis Storage

Персистентное хранение Entry Plans в Redis.
"""
import json
import logging
from typing import Dict, Optional, List

import redis.asyncio as aioredis

import config
from services.entry_plan.models import EntryPlan

logger = logging.getLogger(__name__)

# Redis key prefix
ENTRY_PLAN_KEY_PREFIX = "entry_plan:"
ENTRY_PLANS_INDEX_KEY = "entry_plans:active"
ENTRY_PLANS_USER_PREFIX = "entry_plans:user:"  # {user_id} -> set of plan_ids

# TTL для завершённых/отменённых планов (7 дней для истории)
COMPLETED_PLAN_TTL_SECONDS = 7 * 24 * 3600


class EntryPlanRedisStorage:
    """
    Redis хранилище для Entry Plans.

    Отвечает за:
    - Сохранение/загрузку планов
    - Индексацию активных планов
    - Индексацию планов по пользователям
    """

    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or f"redis://{config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}"
        self.redis: Optional[aioredis.Redis] = None
        self.use_redis = True

    async def connect(self) -> bool:
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
            logger.info(f"Entry plan storage connected to Redis: {self.redis_url}")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Using in-memory only.")
            self.redis = None
            self.use_redis = False
            return False

    async def close(self):
        """Закрыть соединение с Redis"""
        if self.redis:
            await self.redis.close()
            self.redis = None

    async def save_plan(self, plan: EntryPlan, with_ttl: bool = False):
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

    async def update_plan(self, plan: EntryPlan):
        """Обновить план в Redis"""
        # Если план завершён — сохраняем с TTL
        with_ttl = plan.status in ('cancelled', 'filled')
        await self.save_plan(plan, with_ttl=with_ttl)

    async def delete_plan(self, plan_id: str):
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

    async def load_active_plans(self) -> Dict[str, EntryPlan]:
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
        """Получить план по ID из Redis"""
        if not self.use_redis or not self.redis:
            return None

        try:
            key = f"{ENTRY_PLAN_KEY_PREFIX}{plan_id}"
            plan_json = await self.redis.get(key)
            if plan_json:
                plan_data = json.loads(plan_json)
                return EntryPlan.from_dict(plan_data)
        except Exception as e:
            logger.error(f"Failed to get plan {plan_id} from Redis: {e}")

        return None

    async def get_user_plan_ids(self, user_id: int) -> List[str]:
        """Получить ID всех планов пользователя"""
        if not self.use_redis or not self.redis:
            return []

        try:
            user_key = f"{ENTRY_PLANS_USER_PREFIX}{user_id}"
            return list(await self.redis.smembers(user_key))
        except Exception as e:
            logger.error(f"Failed to get user plan IDs: {e}")
            return []

    async def get_user_plans(self, user_id: int) -> List[EntryPlan]:
        """Получить все планы пользователя из Redis"""
        plans = []

        if not self.use_redis or not self.redis:
            return plans

        try:
            user_key = f"{ENTRY_PLANS_USER_PREFIX}{user_id}"
            plan_ids = await self.redis.smembers(user_key)

            for plan_id in plan_ids:
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

        return plans

    async def remove_plan_from_user_index(self, user_id: int, plan_id: str):
        """Удалить план из индекса пользователя"""
        if not self.use_redis or not self.redis:
            return

        try:
            user_key = f"{ENTRY_PLANS_USER_PREFIX}{user_id}"
            await self.redis.srem(user_key, plan_id)
        except Exception as e:
            logger.error(f"Failed to remove plan from user index: {e}")
