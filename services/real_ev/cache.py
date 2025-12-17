"""
Redis cache for Real EV stats.
"""
import json
import logging
from typing import Optional, Dict
from datetime import datetime

import redis.asyncio as aioredis

import config
from .models import EVGroupKey, EVGroupStats

logger = logging.getLogger(__name__)


class EVCache:
    """Redis кэш для Real EV статистики."""

    TTL_SECONDS = 3600  # 60 минут

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self.lookback_days = getattr(config, 'EV_LOOKBACK_DAYS', 90)

    async def _get_redis(self) -> Optional[aioredis.Redis]:
        """Get Redis connection."""
        if self.redis is None:
            try:
                self.redis = aioredis.Redis(
                    host=config.REDIS_HOST,
                    port=config.REDIS_PORT,
                    password=config.REDIS_PASSWORD if config.REDIS_PASSWORD else None,
                    decode_responses=True,
                )
                await self.redis.ping()
            except Exception as e:
                logger.warning(f"Redis not available for EV cache: {e}")
                self.redis = None
        return self.redis

    async def get_stats(self, group_key: EVGroupKey) -> Optional[EVGroupStats]:
        """
        Получить статистику из кэша.

        Args:
            group_key: Ключ группировки
        """
        redis = await self._get_redis()
        if not redis:
            return None

        try:
            cache_key = group_key.to_cache_key(self.lookback_days)
            data = await redis.get(cache_key)
            if data:
                return EVGroupStats.from_dict(json.loads(data))
            return None
        except Exception as e:
            logger.error(f"Error getting EV stats from cache: {e}")
            return None

    async def set_stats(self, stats: EVGroupStats) -> bool:
        """
        Сохранить статистику в кэш.

        Args:
            stats: Статистика для сохранения
        """
        redis = await self._get_redis()
        if not redis:
            return False

        try:
            group_key = EVGroupKey.from_group_key_str(stats.group_key)
            cache_key = group_key.to_cache_key(self.lookback_days)

            # Serialize datetime
            data = stats.to_dict()
            if data.get('last_updated'):
                data['last_updated'] = data['last_updated'].isoformat()

            await redis.setex(
                cache_key,
                self.TTL_SECONDS,
                json.dumps(data),
            )
            return True
        except Exception as e:
            logger.error(f"Error setting EV stats to cache: {e}")
            return False

    async def get_all_stats(self, level: str = None) -> Dict[str, EVGroupStats]:
        """
        Получить все закэшированные stats.

        Args:
            level: Фильтр по уровню (L1, L2, L3) или None для всех
        """
        redis = await self._get_redis()
        if not redis:
            return {}

        try:
            pattern = f"ev:stats:{level or '*'}:*"
            keys = []
            async for key in redis.scan_iter(pattern):
                keys.append(key)

            result = {}
            if keys:
                values = await redis.mget(keys)
                for key, value in zip(keys, values):
                    if value:
                        stats = EVGroupStats.from_dict(json.loads(value))
                        result[stats.group_key] = stats

            return result
        except Exception as e:
            logger.error(f"Error getting all EV stats from cache: {e}")
            return {}

    async def invalidate(self, group_key: EVGroupKey) -> bool:
        """Инвалидировать конкретный ключ."""
        redis = await self._get_redis()
        if not redis:
            return False

        try:
            cache_key = group_key.to_cache_key(self.lookback_days)
            await redis.delete(cache_key)
            return True
        except Exception as e:
            logger.error(f"Error invalidating EV cache: {e}")
            return False

    async def invalidate_all(self) -> int:
        """Инвалидировать весь EV кэш."""
        redis = await self._get_redis()
        if not redis:
            return 0

        try:
            keys = []
            async for key in redis.scan_iter("ev:stats:*"):
                keys.append(key)

            if keys:
                deleted = await redis.delete(*keys)
                logger.info(f"Invalidated {deleted} EV cache keys")
                return deleted
            return 0
        except Exception as e:
            logger.error(f"Error invalidating all EV cache: {e}")
            return 0

    async def close(self):
        """Закрыть соединение с Redis."""
        if self.redis:
            await self.redis.close()
            self.redis = None
