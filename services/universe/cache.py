"""
Universe Service - Cache

Redis кэш с поддержкой stale-while-revalidate.
"""
import json
import asyncio
import logging
from typing import Optional, List, Dict, Any, Callable, Awaitable
from datetime import datetime

import redis.asyncio as aioredis

import config

logger = logging.getLogger(__name__)


class UniverseCache:
    """
    Redis кэш для Universe данных.

    Поддерживает stale-while-revalidate:
    - Если кэш есть но TTL истёк → отдать старый, фоном обновить
    - Если кэша нет → вернуть None (caller должен fetch)
    """

    # TTL в секундах
    INSTRUMENTS_TTL = 21600   # 6 часов
    TICKERS_TTL = 120         # 2 минуты
    UNIVERSE_TTL = 120        # 2 минуты

    # Ключи
    INSTRUMENTS_KEY = "universe:instruments:v1"
    TICKERS_KEY = "universe:tickers:v1"
    UNIVERSE_KEY_PATTERN = "universe:result:{mode}:v1"

    # Stale TTL (как долго хранить stale данные для fallback)
    STALE_TTL_MULTIPLIER = 3  # TTL * 3 = stale window

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self._refresh_tasks: Dict[str, asyncio.Task] = {}

    async def _get_redis(self) -> Optional[aioredis.Redis]:
        """Lazy init Redis connection."""
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
                logger.warning(f"Redis not available for Universe cache: {e}")
                self.redis = None
        return self.redis

    async def get_instruments(self) -> Optional[List[Dict]]:
        """Получить инструменты из кэша."""
        return await self._get_json(self.INSTRUMENTS_KEY)

    async def set_instruments(self, instruments: List[Dict]) -> bool:
        """Сохранить инструменты в кэш."""
        return await self._set_json(
            self.INSTRUMENTS_KEY,
            instruments,
            self.INSTRUMENTS_TTL
        )

    async def get_tickers(self) -> Optional[List[Dict]]:
        """Получить тикеры из кэша."""
        return await self._get_json(self.TICKERS_KEY)

    async def set_tickers(self, tickers: List[Dict]) -> bool:
        """Сохранить тикеры в кэш."""
        return await self._set_json(
            self.TICKERS_KEY,
            tickers,
            self.TICKERS_TTL
        )

    async def get_universe(self, mode: str) -> Optional[Dict]:
        """Получить Universe result из кэша."""
        key = self.UNIVERSE_KEY_PATTERN.format(mode=mode)
        return await self._get_json(key)

    async def set_universe(self, mode: str, data: Dict) -> bool:
        """Сохранить Universe result в кэш."""
        key = self.UNIVERSE_KEY_PATTERN.format(mode=mode)
        return await self._set_json(key, data, self.UNIVERSE_TTL)

    async def get_or_refresh(
        self,
        key: str,
        fetcher: Callable[[], Awaitable[Any]],
        ttl: int,
        stale_ok: bool = True
    ) -> Optional[Any]:
        """
        Stale-while-revalidate pattern.

        Args:
            key: Redis key
            fetcher: Async function to fetch fresh data
            ttl: TTL in seconds
            stale_ok: Return stale data while refreshing in background

        Returns:
            Data from cache or fresh fetch, None if unavailable
        """
        redis = await self._get_redis()
        if not redis:
            # Fallback: fetch without cache
            try:
                return await fetcher()
            except Exception as e:
                logger.error(f"Fetcher failed without cache: {e}")
                return None

        try:
            # Check if data exists with TTL
            data_raw = await redis.get(key)
            ttl_remaining = await redis.ttl(key)

            if data_raw:
                data = json.loads(data_raw)

                # Data is fresh
                if ttl_remaining > 0:
                    return data

                # Data is stale but exists
                if stale_ok:
                    # Return stale and refresh in background
                    self._schedule_refresh(key, fetcher, ttl)
                    logger.debug(f"Returning stale data for {key}, refreshing in background")
                    return data

            # No data or not stale_ok - fetch now
            fresh_data = await fetcher()
            if fresh_data:
                await self._set_json(key, fresh_data, ttl)
            return fresh_data

        except Exception as e:
            logger.error(f"Error in get_or_refresh for {key}: {e}")
            # Try fetch as fallback
            try:
                return await fetcher()
            except Exception:
                return None

    def _schedule_refresh(
        self,
        key: str,
        fetcher: Callable[[], Awaitable[Any]],
        ttl: int
    ):
        """Schedule background refresh if not already running."""
        if key in self._refresh_tasks:
            task = self._refresh_tasks[key]
            if not task.done():
                return  # Already refreshing

        async def refresh():
            try:
                fresh_data = await fetcher()
                if fresh_data:
                    await self._set_json(key, fresh_data, ttl)
                    logger.debug(f"Background refresh completed for {key}")
            except Exception as e:
                logger.error(f"Background refresh failed for {key}: {e}")
            finally:
                self._refresh_tasks.pop(key, None)

        self._refresh_tasks[key] = asyncio.create_task(refresh())

    async def _get_json(self, key: str) -> Optional[Any]:
        """Get and deserialize JSON from Redis."""
        redis = await self._get_redis()
        if not redis:
            return None

        try:
            data = await redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Error getting {key} from cache: {e}")
            return None

    async def _set_json(self, key: str, data: Any, ttl: int) -> bool:
        """Serialize and set JSON to Redis with TTL."""
        redis = await self._get_redis()
        if not redis:
            return False

        try:
            # Convert datetime to ISO string
            serialized = self._serialize_for_json(data)

            # Set with extended TTL for stale fallback
            stale_ttl = ttl * self.STALE_TTL_MULTIPLIER
            await redis.setex(key, stale_ttl, json.dumps(serialized))

            # Store the "fresh until" timestamp separately
            fresh_until_key = f"{key}:fresh_until"
            fresh_until = datetime.utcnow().timestamp() + ttl
            await redis.setex(fresh_until_key, stale_ttl, str(fresh_until))

            return True
        except Exception as e:
            logger.error(f"Error setting {key} to cache: {e}")
            return False

    async def is_fresh(self, key: str) -> bool:
        """Check if cached data is still fresh (not stale)."""
        redis = await self._get_redis()
        if not redis:
            return False

        try:
            fresh_until_key = f"{key}:fresh_until"
            fresh_until_raw = await redis.get(fresh_until_key)
            if fresh_until_raw:
                fresh_until = float(fresh_until_raw)
                return datetime.utcnow().timestamp() < fresh_until
            return False
        except Exception as e:
            logger.error(f"Error checking freshness for {key}: {e}")
            return False

    def _serialize_for_json(self, obj: Any) -> Any:
        """Recursively convert datetime objects to ISO strings."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {k: self._serialize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize_for_json(item) for item in obj]
        return obj

    async def invalidate_all(self) -> int:
        """Invalidate all Universe cache keys."""
        redis = await self._get_redis()
        if not redis:
            return 0

        try:
            keys = []
            async for key in redis.scan_iter("universe:*"):
                keys.append(key)

            if keys:
                deleted = await redis.delete(*keys)
                logger.info(f"Invalidated {deleted} Universe cache keys")
                return deleted
            return 0
        except Exception as e:
            logger.error(f"Error invalidating Universe cache: {e}")
            return 0

    async def close(self):
        """Close Redis connection and cancel pending tasks."""
        # Cancel all refresh tasks
        for task in self._refresh_tasks.values():
            task.cancel()
        self._refresh_tasks.clear()

        if self.redis:
            await self.redis.close()
            self.redis = None


# Global singleton
_cache: Optional[UniverseCache] = None


def get_universe_cache() -> UniverseCache:
    """Get global Universe cache instance."""
    global _cache
    if _cache is None:
        _cache = UniverseCache()
    return _cache
