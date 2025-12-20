"""
Stats Client для Syntra AI Stats API.

HTTP клиент с production-ready features:
- Lazy session init (connection pooling)
- Half-open circuit breaker
- Exponential backoff + jitter
- Graceful degradation (_safe методы)

Endpoints:
- GET /api/stats/trading/overview
- GET /api/stats/trading/outcomes
- GET /api/stats/trading/symbols
- GET /api/stats/learning/archetypes
- GET /api/stats/learning/archetypes/{archetype}
- GET /api/stats/learning/gates
- GET /api/stats/paper/overview
- GET /api/stats/paper/archetypes
- GET /api/stats/conversion
"""

import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import aiohttp
from loguru import logger

import config


# =============================================================================
# Exceptions
# =============================================================================


class StatsClientError(Exception):
    """Client-side error (4xx)."""
    pass


class StatsServiceError(Exception):
    """Server-side error (5xx)."""
    pass


class StatsServiceUnavailable(Exception):
    """Service unavailable (circuit open, timeout, network error)."""
    pass


# =============================================================================
# StatsClient
# =============================================================================


class StatsClient:
    """Client для Stats API с production-ready retries.

    Features:
    - Lazy session init — connection pooling, не создаём на каждый запрос
    - Half-open circuit breaker — probe request после timeout
    - Exponential backoff с jitter
    - Graceful degradation через _safe методы
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 5.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ):
        # URL priority: explicit > SYNTRA_STATS_URL > SYNTRA_API_URL
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            stats_url = getattr(config, "SYNTRA_STATS_URL", "")
            if stats_url:
                self.base_url = stats_url.rstrip("/")
            else:
                self.base_url = getattr(config, "SYNTRA_API_URL", "http://localhost:8000").rstrip("/")

        self.api_key = api_key or getattr(config, "SYNTRA_STATS_API_KEY", "")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        # Lazy session init (не создаём сразу!)
        self._session: Optional[aiohttp.ClientSession] = None

        # Circuit breaker state
        self._failures = 0
        self._circuit_state = "closed"  # closed | open | half-open
        self._circuit_open_until: Optional[datetime] = None
        self._circuit_threshold = 5     # Open after 5 failures
        self._circuit_timeout = 60      # Seconds to wait before half-open

    async def _get_session(self) -> aiohttp.ClientSession:
        """Lazy session initialization.

        НЕ создаём session на каждый запрос!
        Переиспользуем один session для connection pooling.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-API-Key": self.api_key},
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )
        return self._session

    async def close(self):
        """Закрыть session при завершении работы."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _check_circuit_breaker(self) -> bool:
        """Проверить circuit breaker. Returns True если можно делать запрос."""
        if self._circuit_state == "closed":
            return True

        if self._circuit_state == "open":
            if datetime.now() >= self._circuit_open_until:
                # Переходим в half-open — пропускаем 1 probe
                self._circuit_state = "half-open"
                logger.info("Stats circuit breaker → half-open, allowing probe request")
                return True
            else:
                # Ещё закрыт
                return False

        # half-open — пропускаем запрос (probe)
        return True

    def _on_success(self):
        """Вызывается при успешном запросе."""
        if self._circuit_state == "half-open":
            # Probe успешен → закрываем circuit
            self._circuit_state = "closed"
            self._failures = 0
            logger.info("Stats circuit breaker → closed (probe succeeded)")
        else:
            self._failures = 0

    def _on_failure(self):
        """Вызывается при неудачном запросе."""
        self._failures += 1

        if self._circuit_state == "half-open":
            # Probe неудачен → снова открываем
            self._circuit_state = "open"
            self._circuit_open_until = datetime.now() + timedelta(seconds=self._circuit_timeout)
            logger.warning(f"Stats circuit breaker → open (probe failed), wait {self._circuit_timeout}s")
            return

        if self._failures >= self._circuit_threshold:
            self._circuit_state = "open"
            self._circuit_open_until = datetime.now() + timedelta(seconds=self._circuit_timeout)
            logger.warning(f"Stats circuit breaker → open after {self._failures} failures")

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make request with retries and circuit breaker."""

        # Check circuit breaker
        if not self._check_circuit_breaker():
            raise StatsServiceUnavailable("Circuit breaker open")

        session = await self._get_session()
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                async with session.request(
                    method,
                    f"{self.base_url}{path}",
                    params=params,
                    **kwargs,
                ) as resp:
                    if resp.status == 200:
                        self._on_success()
                        return await resp.json()
                    elif resp.status >= 500:
                        raise StatsServiceError(f"Server error: {resp.status}")
                    elif resp.status == 401:
                        raise StatsClientError("Invalid API key")
                    elif resp.status == 404:
                        raise StatsClientError(f"Endpoint not found: {path}")
                    else:
                        # Client error — не ретраим
                        text = await resp.text()
                        raise StatsClientError(f"Client error {resp.status}: {text[:200]}")

            except StatsClientError:
                # Client errors — не ретраим, пробрасываем
                raise

            except (aiohttp.ClientError, asyncio.TimeoutError, StatsServiceError) as e:
                last_error = e
                self._on_failure()

                if self._circuit_state == "open":
                    raise StatsServiceUnavailable("Circuit breaker opened")

                # Exponential backoff with jitter
                if attempt < self.max_retries - 1:
                    delay = self.backoff_factor * (2 ** attempt)
                    jitter = random.uniform(0, 0.1 * delay)
                    logger.debug(f"Stats request retry {attempt + 1}, waiting {delay + jitter:.2f}s")
                    await asyncio.sleep(delay + jitter)

        raise StatsServiceUnavailable(f"Max retries exceeded: {last_error}")

    # =========================================================================
    # Trading Stats
    # =========================================================================

    async def get_trading_overview(
        self,
        period: str = "90d",
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        symbol: Optional[str] = None,
        archetype: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get trading overview statistics.

        Args:
            period: Period shorthand (7d, 30d, 90d, 180d, 365d, all)
            from_ts: Start timestamp (overrides period)
            to_ts: End timestamp (overrides period)
            symbol: Filter by symbol
            archetype: Filter by archetype
            origin: Filter by origin (ai_scenario, manual)

        Returns:
            TradingOverviewResponse dict
        """
        params = {"period": period}
        if from_ts is not None:
            params["from_ts"] = from_ts
        if to_ts is not None:
            params["to_ts"] = to_ts
        if symbol:
            params["symbol"] = symbol
        if archetype:
            params["archetype"] = archetype
        if origin:
            params["origin"] = origin

        return await self._request("GET", "/api/stats/trading/overview", params=params)

    async def get_outcomes(
        self,
        period: str = "90d",
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get outcomes distribution.

        Returns:
            OutcomesDistributionResponse dict with distribution and hit_rates
        """
        params = {"period": period}
        if from_ts is not None:
            params["from_ts"] = from_ts
        if to_ts is not None:
            params["to_ts"] = to_ts

        return await self._request("GET", "/api/stats/trading/outcomes", params=params)

    async def get_symbols_stats(
        self,
        period: str = "90d",
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get per-symbol statistics."""
        params = {"period": period}
        if from_ts is not None:
            params["from_ts"] = from_ts
        if to_ts is not None:
            params["to_ts"] = to_ts

        return await self._request("GET", "/api/stats/trading/symbols", params=params)

    # =========================================================================
    # Learning Stats
    # =========================================================================

    async def get_archetypes(
        self,
        period: str = "90d",
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        min_sample: int = 10,
        page: int = 0,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """Get archetypes list with stats.

        Args:
            period: Period shorthand
            min_sample: Minimum sample size
            page: Page number (0-indexed)
            page_size: Items per page

        Returns:
            ArchetypeListResponse dict
        """
        params = {
            "period": period,
            "min_sample": min_sample,
            "page": page,
            "page_size": page_size,
        }
        if from_ts is not None:
            params["from_ts"] = from_ts
        if to_ts is not None:
            params["to_ts"] = to_ts

        return await self._request("GET", "/api/stats/learning/archetypes", params=params)

    async def get_archetype_detail(
        self,
        archetype: str,
        period: str = "90d",
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get detailed stats for specific archetype.

        Returns:
            ArchetypeDetailResponse dict
        """
        params = {"period": period}
        if from_ts is not None:
            params["from_ts"] = from_ts
        if to_ts is not None:
            params["to_ts"] = to_ts

        return await self._request(
            "GET",
            f"/api/stats/learning/archetypes/{archetype}",
            params=params
        )

    async def get_gates(self) -> List[Dict[str, Any]]:
        """Get EV gates status.

        Returns:
            List of GateStatusResponse dicts
        """
        return await self._request("GET", "/api/stats/learning/gates")

    # =========================================================================
    # Paper Trading Stats
    # =========================================================================

    async def get_paper_overview(
        self,
        period: str = "90d",
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        archetype: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paper trading overview."""
        params = {"period": period}
        if from_ts is not None:
            params["from_ts"] = from_ts
        if to_ts is not None:
            params["to_ts"] = to_ts
        if archetype:
            params["archetype"] = archetype

        return await self._request("GET", "/api/stats/paper/overview", params=params)

    async def get_paper_archetypes(
        self,
        period: str = "90d",
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        min_sample: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get paper vs real comparison by archetype."""
        params = {"period": period, "min_sample": min_sample}
        if from_ts is not None:
            params["from_ts"] = from_ts
        if to_ts is not None:
            params["to_ts"] = to_ts

        return await self._request("GET", "/api/stats/paper/archetypes", params=params)

    # =========================================================================
    # Conversion Funnel
    # =========================================================================

    async def get_funnel(
        self,
        period: str = "90d",
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get conversion funnel statistics.

        Returns:
            ConversionFunnelResponse dict
        """
        params = {"period": period}
        if from_ts is not None:
            params["from_ts"] = from_ts
        if to_ts is not None:
            params["to_ts"] = to_ts

        return await self._request("GET", "/api/stats/conversion", params=params)

    # =========================================================================
    # Graceful Degradation (_safe methods)
    # =========================================================================

    async def get_trading_overview_safe(
        self,
        period: str = "90d",
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """Return None if stats unavailable (for graceful UI degradation)."""
        try:
            return await self.get_trading_overview(period=period, **kwargs)
        except (StatsServiceUnavailable, StatsServiceError) as e:
            logger.warning(f"Stats unavailable: {e}")
            return None

    async def get_outcomes_safe(
        self,
        period: str = "90d",
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """Return None if outcomes unavailable."""
        try:
            return await self.get_outcomes(period=period, **kwargs)
        except (StatsServiceUnavailable, StatsServiceError) as e:
            logger.warning(f"Stats outcomes unavailable: {e}")
            return None

    async def get_archetypes_safe(
        self,
        period: str = "90d",
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """Return None if archetypes unavailable."""
        try:
            return await self.get_archetypes(period=period, **kwargs)
        except (StatsServiceUnavailable, StatsServiceError) as e:
            logger.warning(f"Stats archetypes unavailable: {e}")
            return None

    async def get_gates_safe(self) -> Optional[List[Dict[str, Any]]]:
        """Return None if gates unavailable."""
        try:
            return await self.get_gates()
        except (StatsServiceUnavailable, StatsServiceError) as e:
            logger.warning(f"Stats gates unavailable: {e}")
            return None

    async def get_funnel_safe(
        self,
        period: str = "90d",
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """Return None if funnel unavailable."""
        try:
            return await self.get_funnel(period=period, **kwargs)
        except (StatsServiceUnavailable, StatsServiceError) as e:
            logger.warning(f"Stats funnel unavailable: {e}")
            return None

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# =============================================================================
# Singleton
# =============================================================================

_stats_client: Optional[StatsClient] = None


def get_stats_client() -> StatsClient:
    """Get singleton StatsClient instance."""
    global _stats_client

    if _stats_client is None:
        _stats_client = StatsClient()

    return _stats_client


async def close_stats_client():
    """Close singleton StatsClient (call on bot shutdown)."""
    global _stats_client

    if _stats_client is not None:
        await _stats_client.close()
        _stats_client = None
