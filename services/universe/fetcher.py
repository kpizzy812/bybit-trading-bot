"""
Universe Service - Fetcher

Получение данных из Bybit и фильтрация мусора.
"""
import logging
from typing import List, Dict, Set, Optional

from services.bybit import BybitClient
from .cache import get_universe_cache, UniverseCache
from .models import UNIVERSE_LIMITS

logger = logging.getLogger(__name__)


class UniverseFetcher:
    """
    Fetcher для Universe данных.

    Получает инструменты и тикеры из Bybit API,
    использует кэш с stale-while-revalidate.
    """

    def __init__(self, bybit_client: Optional[BybitClient] = None):
        self.bybit = bybit_client
        self.cache = get_universe_cache()

    def set_bybit_client(self, client: BybitClient):
        """Set Bybit client (for lazy initialization)."""
        self.bybit = client

    async def get_instruments(self, use_cache: bool = True) -> List[Dict]:
        """
        Получить все активные USDT perpetual инструменты.

        Args:
            use_cache: Использовать кэш (True по умолчанию)

        Returns:
            List of instrument dicts with symbol, status, quoteCoin, etc.
        """
        if use_cache:
            cached = await self.cache.get_instruments()
            if cached:
                logger.debug(f"Instruments from cache: {len(cached)} items")
                return cached

        if not self.bybit:
            logger.warning("Bybit client not available, returning empty instruments")
            return []

        try:
            instruments = await self.bybit.get_all_instruments(
                status="Trading",
                quote_coin="USDT"
            )
            logger.info(f"Fetched {len(instruments)} instruments from Bybit")

            # Cache the result
            await self.cache.set_instruments(instruments)
            return instruments

        except Exception as e:
            logger.error(f"Failed to fetch instruments: {e}")
            # Try to return stale cache
            cached = await self.cache.get_instruments()
            if cached:
                logger.warning("Using stale instruments cache as fallback")
                return cached
            return []

    async def get_tickers(self, use_cache: bool = True) -> List[Dict]:
        """
        Получить все тикеры.

        Args:
            use_cache: Использовать кэш (True по умолчанию)

        Returns:
            List of ticker dicts with lastPrice, turnover24h, etc.
        """
        if use_cache:
            cached = await self.cache.get_tickers()
            is_fresh = await self.cache.is_fresh(self.cache.TICKERS_KEY)

            if cached and is_fresh:
                logger.debug(f"Fresh tickers from cache: {len(cached)} items")
                return cached

            if cached and not is_fresh:
                # Stale-while-revalidate: return stale, refresh in background
                logger.debug("Tickers stale, returning cached + background refresh")
                await self._refresh_tickers_background()
                return cached

        if not self.bybit:
            logger.warning("Bybit client not available, returning empty tickers")
            return []

        return await self._fetch_tickers_fresh()

    async def _fetch_tickers_fresh(self) -> List[Dict]:
        """Fetch fresh tickers from Bybit."""
        try:
            tickers = await self.bybit.get_all_tickers()
            logger.info(f"Fetched {len(tickers)} tickers from Bybit")
            await self.cache.set_tickers(tickers)
            return tickers
        except Exception as e:
            logger.error(f"Failed to fetch tickers: {e}")
            cached = await self.cache.get_tickers()
            if cached:
                logger.warning("Using stale tickers cache as fallback")
                return cached
            return []

    async def _refresh_tickers_background(self):
        """Background refresh for tickers."""
        if not self.bybit:
            return

        async def fetcher():
            return await self.bybit.get_all_tickers()

        await self.cache.get_or_refresh(
            self.cache.TICKERS_KEY,
            fetcher,
            self.cache.TICKERS_TTL,
            stale_ok=True
        )

    async def get_filtered_tickers(
        self,
        mode: str = "standard",
        min_turnover: Optional[float] = None
    ) -> List[Dict]:
        """
        Получить отфильтрованные тикеры.

        Фильтрует:
        - lastPrice > 0
        - turnover24h >= min_turnover (по режиму)
        - Символ есть в instruments (не делистинг)

        Args:
            mode: Trading mode (conservative, standard, high_risk, meme)
            min_turnover: Override минимальный turnover (опционально)

        Returns:
            Filtered list of tickers
        """
        tickers = await self.get_tickers()
        instruments = await self.get_instruments()

        if not tickers:
            return []

        # Get valid symbols from instruments
        valid_symbols: Set[str] = {
            i['symbol'] for i in instruments
            if i.get('status') == 'Trading'
        }

        # Get min turnover for mode
        if min_turnover is None:
            mode_config = UNIVERSE_LIMITS.get(mode, UNIVERSE_LIMITS["standard"])
            min_turnover = mode_config.get("min_turnover", 1_000_000)

        filtered = []
        for ticker in tickers:
            symbol = ticker.get('symbol', '')

            # Filter conditions
            if symbol not in valid_symbols:
                continue

            last_price = float(ticker.get('lastPrice', 0) or 0)
            if last_price <= 0:
                continue

            turnover = float(ticker.get('turnover24h', 0) or 0)
            if turnover < min_turnover:
                continue

            filtered.append(ticker)

        logger.debug(
            f"Filtered tickers: {len(filtered)}/{len(tickers)} "
            f"(mode={mode}, min_turnover=${min_turnover:,.0f})"
        )
        return filtered

    async def get_tickers_as_dict(self) -> Dict[str, Dict]:
        """
        Получить тикеры как словарь {symbol: ticker}.

        Returns:
            Dict mapping symbol to ticker data
        """
        tickers = await self.get_tickers()
        return {t['symbol']: t for t in tickers}


# Global singleton
_fetcher: Optional[UniverseFetcher] = None


def get_universe_fetcher(bybit_client: Optional[BybitClient] = None) -> UniverseFetcher:
    """Get global Universe fetcher instance."""
    global _fetcher
    if _fetcher is None:
        _fetcher = UniverseFetcher(bybit_client)
    elif bybit_client:
        _fetcher.set_bybit_client(bybit_client)
    return _fetcher
