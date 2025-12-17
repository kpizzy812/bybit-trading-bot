"""
Кэш AI сценариев

Хранит сценарии по ключу user_id:symbol:timeframe.
Сценарии сохраняются до явного обновления пользователем.
"""
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class CachedScenarios:
    """Закэшированные сценарии"""
    scenarios: list
    analysis_id: str
    current_price: float
    market_context: dict
    no_trade: Optional[dict]
    key_levels: list
    cached_at: datetime = field(default_factory=datetime.utcnow)


class ScenariosCache:
    """
    In-memory кэш сценариев.

    Ключ: f"{user_id}:{symbol}:{timeframe}"
    """

    def __init__(self, ttl_hours: int = 24):
        self._cache: Dict[str, CachedScenarios] = {}
        self._ttl_hours = ttl_hours

    def _make_key(self, user_id: int, symbol: str, timeframe: str) -> str:
        return f"{user_id}:{symbol}:{timeframe}"

    def get(
        self,
        user_id: int,
        symbol: str,
        timeframe: str
    ) -> Optional[CachedScenarios]:
        """Получить сценарии из кэша"""
        key = self._make_key(user_id, symbol, timeframe)
        cached = self._cache.get(key)

        if not cached:
            return None

        # Проверяем TTL
        age_hours = (datetime.utcnow() - cached.cached_at).total_seconds() / 3600
        if age_hours > self._ttl_hours:
            logger.debug(f"Cache expired for {key} (age: {age_hours:.1f}h)")
            del self._cache[key]
            return None

        logger.debug(f"Cache hit for {key} (age: {age_hours:.1f}h)")
        return cached

    def set(
        self,
        user_id: int,
        symbol: str,
        timeframe: str,
        scenarios: list,
        analysis_id: str,
        current_price: float,
        market_context: dict,
        no_trade: Optional[dict],
        key_levels: list
    ) -> None:
        """Сохранить сценарии в кэш"""
        key = self._make_key(user_id, symbol, timeframe)

        self._cache[key] = CachedScenarios(
            scenarios=scenarios,
            analysis_id=analysis_id,
            current_price=current_price,
            market_context=market_context,
            no_trade=no_trade,
            key_levels=key_levels,
            cached_at=datetime.utcnow()
        )

        logger.info(f"Cached {len(scenarios)} scenarios for {key}")

    def invalidate(self, user_id: int, symbol: str, timeframe: str) -> bool:
        """Удалить сценарии из кэша (при обновлении)"""
        key = self._make_key(user_id, symbol, timeframe)

        if key in self._cache:
            del self._cache[key]
            logger.info(f"Invalidated cache for {key}")
            return True
        return False

    def get_user_cached_pairs(self, user_id: int) -> list[tuple[str, str, datetime]]:
        """Получить список закэшированных пар для юзера"""
        pairs = []
        prefix = f"{user_id}:"

        for key, cached in self._cache.items():
            if key.startswith(prefix):
                parts = key.split(":")
                if len(parts) == 3:
                    symbol = parts[1]
                    timeframe = parts[2]
                    pairs.append((symbol, timeframe, cached.cached_at))

        return pairs


# Глобальный инстанс кэша
_scenarios_cache: Optional[ScenariosCache] = None


def get_scenarios_cache() -> ScenariosCache:
    """Получить глобальный кэш сценариев"""
    global _scenarios_cache
    if _scenarios_cache is None:
        _scenarios_cache = ScenariosCache()
    return _scenarios_cache
