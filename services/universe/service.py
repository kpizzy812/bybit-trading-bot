"""
Universe Service - Main API

Главный сервис для получения динамического Universe монет.
"""
import logging
from datetime import datetime
from typing import List, Optional

from services.bybit import BybitClient
from .models import (
    SymbolMetrics, UniverseResult,
    MAJOR_SYMBOLS, MEME_SYMBOLS, MEME_TAG_MAP, UNIVERSE_LIMITS
)
from .fetcher import get_universe_fetcher, UniverseFetcher
from .scorer import calculate_metrics_from_tickers, calculate_scores, sort_by_category
from .cache import get_universe_cache

logger = logging.getLogger(__name__)


class UniverseService:
    """
    Главный сервис Universe.

    Предоставляет:
    - get_universe(mode) -> UniverseResult с категориями
    - get_symbols(mode, category, limit) -> List[str]
    """

    def __init__(self, bybit_client: Optional[BybitClient] = None):
        self.fetcher = get_universe_fetcher(bybit_client)
        self.cache = get_universe_cache()

    def set_bybit_client(self, client: BybitClient):
        """Set Bybit client."""
        self.fetcher.set_bybit_client(client)

    async def get_universe(
        self,
        mode: str = "standard",
        limits_per_category: int = 10
    ) -> UniverseResult:
        """
        Получить Universe для режима торговли.

        Args:
            mode: Trading mode (conservative, standard, high_risk, meme)
            limits_per_category: Количество символов в каждой категории

        Returns:
            UniverseResult с категориями Popular, Gainers, Losers, Volatile, Trending
        """
        mode_config = UNIVERSE_LIMITS.get(mode, UNIVERSE_LIMITS["standard"])

        # Special handling for MEME mode
        if mode == "meme":
            return await self._get_meme_universe(mode_config, limits_per_category)

        # Get filtered tickers
        tickers = await self.fetcher.get_filtered_tickers(
            mode=mode,
            min_turnover=mode_config.get("min_turnover")
        )

        if not tickers:
            logger.warning(f"No tickers available for mode={mode}, using fallback")
            return self._fallback_universe(mode)

        # Calculate metrics
        metrics = calculate_metrics_from_tickers(tickers)

        # Apply mode-specific filters
        metrics = self._apply_mode_filters(metrics, mode, mode_config)

        # Calculate scores
        top_n = mode_config.get("top_n", 100)
        metrics = calculate_scores(metrics, top_n_for_scoring=top_n)

        # Build result with sorted categories
        result = UniverseResult(
            popular=sort_by_category(metrics, "popular", limits_per_category),
            gainers=sort_by_category(metrics, "gainers", limits_per_category),
            losers=sort_by_category(metrics, "losers", limits_per_category),
            volatile=sort_by_category(metrics, "volatile", limits_per_category),
            trending=sort_by_category(metrics, "trending", limits_per_category),
            as_of=datetime.utcnow(),
            mode=mode,
            universe_size=len(metrics),
        )

        logger.info(
            f"Universe built for {mode}: {result.universe_size} symbols, "
            f"top trending: {[m.symbol for m in result.trending[:3]]}"
        )
        return result

    async def _get_meme_universe(
        self,
        mode_config: dict,
        limits_per_category: int
    ) -> UniverseResult:
        """Get Universe for MEME mode (whitelist based)."""
        whitelist = set(mode_config.get("whitelist", MEME_SYMBOLS))
        use_dynamic = mode_config.get("use_dynamic_memes", True)

        # Get tickers
        all_tickers = await self.fetcher.get_tickers()
        if not all_tickers:
            return self._fallback_universe("meme")

        # Build metrics for whitelist symbols
        metrics = []
        for ticker in all_tickers:
            symbol = ticker.get('symbol', '')

            # Include if in whitelist OR (dynamic and in meme_tag_map)
            is_whitelist = symbol in whitelist
            is_dynamic_meme = use_dynamic and symbol in MEME_TAG_MAP

            if not (is_whitelist or is_dynamic_meme):
                continue

            m = calculate_metrics_from_tickers([ticker])
            if m:
                metrics.extend(m)

        # Calculate scores
        metrics = calculate_scores(metrics, top_n_for_scoring=50)

        result = UniverseResult(
            popular=sort_by_category(metrics, "popular", limits_per_category),
            gainers=sort_by_category(metrics, "gainers", limits_per_category),
            losers=sort_by_category(metrics, "losers", limits_per_category),
            volatile=sort_by_category(metrics, "volatile", limits_per_category),
            trending=sort_by_category(metrics, "trending", limits_per_category),
            as_of=datetime.utcnow(),
            mode="meme",
            universe_size=len(metrics),
        )

        logger.info(f"MEME Universe: {result.universe_size} symbols")
        return result

    def _apply_mode_filters(
        self,
        metrics: List[SymbolMetrics],
        mode: str,
        mode_config: dict
    ) -> List[SymbolMetrics]:
        """Apply mode-specific filters."""
        if not metrics:
            return metrics

        # Conservative: filter out wild movers
        max_change = mode_config.get("max_change_pct")
        if max_change:
            before = len(metrics)
            metrics = [m for m in metrics if abs(m.price_change_pct) < max_change]
            logger.debug(
                f"Conservative filter: {before} -> {len(metrics)} "
                f"(removed |chg| >= {max_change}%)"
            )

        # Limit to top N by volume
        top_n = mode_config.get("top_n", 100)
        if len(metrics) > top_n:
            metrics = sorted(metrics, key=lambda m: m.turnover_24h, reverse=True)[:top_n]

        return metrics

    def _fallback_universe(self, mode: str) -> UniverseResult:
        """Fallback Universe with major symbols only."""
        symbols = MEME_SYMBOLS if mode == "meme" else MAJOR_SYMBOLS
        metrics = [
            SymbolMetrics(
                symbol=s,
                last_price=0.0,
                turnover_24h=0.0,
                price_change_pct=0.0,
                range_pct=0.0,
            )
            for s in symbols
        ]
        return UniverseResult(
            popular=metrics,
            gainers=metrics,
            losers=metrics,
            volatile=metrics,
            trending=metrics,
            as_of=datetime.utcnow(),
            mode=mode,
            universe_size=len(metrics),
            source="fallback",
        )

    async def get_symbols(
        self,
        mode: str = "standard",
        category: str = "trending",
        limit: int = 5
    ) -> List[str]:
        """
        Получить список символов для категории.

        Args:
            mode: Trading mode
            category: Category (popular, gainers, losers, volatile, trending)
            limit: Max symbols to return

        Returns:
            List of symbol strings (e.g., ["BTCUSDT", "ETHUSDT"])
        """
        universe = await self.get_universe(mode, limits_per_category=limit)
        return universe.get_symbols(category, limit)

    async def get_symbols_with_metrics(
        self,
        mode: str = "standard",
        category: str = "trending",
        limit: int = 5
    ) -> List[SymbolMetrics]:
        """
        Получить символы с метриками для UI.

        Args:
            mode: Trading mode
            category: Category
            limit: Max symbols

        Returns:
            List of SymbolMetrics
        """
        universe = await self.get_universe(mode, limits_per_category=limit)
        return universe.get_category(category, limit)

    @staticmethod
    def get_major_symbols() -> List[str]:
        """Get major/anchor symbols (always available)."""
        return list(MAJOR_SYMBOLS)

    @staticmethod
    def get_meme_symbols() -> List[str]:
        """Get meme whitelist symbols."""
        return list(MEME_SYMBOLS)


# Global singleton
_service: Optional[UniverseService] = None


def get_universe_service(bybit_client: Optional[BybitClient] = None) -> UniverseService:
    """Get global Universe service instance."""
    global _service
    if _service is None:
        _service = UniverseService(bybit_client)
    elif bybit_client:
        _service.set_bybit_client(bybit_client)
    return _service
