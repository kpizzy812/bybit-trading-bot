"""
Syntra Supervisor Client

Client for Syntra Supervisor API.
Handles position sync, scenario registration, and action logging.
"""
import asyncio
import aiohttp
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from loguru import logger

import config


class SupervisorAPIError(Exception):
    """Error from Supervisor API"""
    pass


@dataclass
class PositionSnapshot:
    """Position state to send to supervisor"""
    trade_id: str
    symbol: str
    side: str  # "Long" / "Short"
    qty: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    pnl_pct: float
    leverage: int
    liq_price: Optional[float]
    sl_current: Optional[float]
    tp_current: Optional[List[Dict]]
    updated_at: str

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Recommendation:
    """Recommendation from supervisor"""
    action_id: str
    type: str
    params: Dict[str, Any]
    urgency: str
    confidence: int
    reason_bullets: List[str]
    guards: List[str]
    expires_at: str


@dataclass
class AdvicePack:
    """Advice pack from supervisor"""
    pack_id: str
    trade_id: str
    user_id: int
    symbol: str
    market_summary: str
    scenario_valid: bool
    time_valid_left_min: int
    risk_state: str
    recommendations: List[Dict]
    cooldown_until: Optional[str]
    price_at_creation: float
    created_at: str
    expires_at: str

    @classmethod
    def from_dict(cls, data: Dict) -> 'AdvicePack':
        return cls(
            pack_id=data.get('pack_id', ''),
            trade_id=data.get('trade_id', ''),
            user_id=data.get('user_id', 0),
            symbol=data.get('symbol', ''),
            market_summary=data.get('market_summary', ''),
            scenario_valid=data.get('scenario_valid', False),
            time_valid_left_min=data.get('time_valid_left_min', 0),
            risk_state=data.get('risk_state', 'safe'),
            recommendations=data.get('recommendations', []),
            cooldown_until=data.get('cooldown_until'),
            price_at_creation=data.get('price_at_creation', 0),
            created_at=data.get('created_at', ''),
            expires_at=data.get('expires_at', ''),
        )


class SupervisorClient:
    """
    Client for Syntra Supervisor API

    Endpoints:
        POST /api/supervisor/sync           - Sync positions
        POST /api/supervisor/register       - Register trade
        POST /api/supervisor/action-result  - Log action result
        POST /api/supervisor/deactivate     - Deactivate scenario
        GET  /api/supervisor/health         - Health check
    """

    def __init__(
        self,
        api_url: str = None,
        api_key: str = None,
        timeout: int = None
    ):
        self.api_url = api_url or config.SYNTRA_API_URL
        self.api_key = api_key or config.SYNTRA_API_KEY
        self.timeout = timeout or config.SYNTRA_API_TIMEOUT

        logger.info(f"SupervisorClient initialized: {self.api_url}")

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def sync_positions(
        self,
        user_id: int,
        positions: List[PositionSnapshot]
    ) -> List[AdvicePack]:
        """
        Sync positions with supervisor and get advice.

        Args:
            user_id: Telegram user ID
            positions: List of current position snapshots

        Returns:
            List of AdvicePack for positions needing attention
        """
        url = f"{self.api_url}/api/supervisor/sync"

        payload = {
            "user_id": user_id,
            "positions": [p.to_dict() for p in positions]
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=self._get_headers(),
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:

                    if response.status != 200:
                        error_text = await response.text()
                        raise SupervisorAPIError(
                            f"Sync failed ({response.status}): {error_text[:200]}"
                        )

                    data = await response.json()

                    if not data.get("success"):
                        raise SupervisorAPIError(
                            f"Sync error: {data.get('detail', 'Unknown')}"
                        )

                    # Parse advice packs
                    advices = []
                    for advice_data in data.get("advices", []):
                        advices.append(AdvicePack.from_dict(advice_data))

                    # Only log when we have advice (avoid spam)
                    if advices:
                        logger.info(
                            f"Supervisor: {len(advices)} advice packs for {len(positions)} positions"
                        )

                    return advices

        except SupervisorAPIError:
            raise
        except asyncio.TimeoutError:
            logger.error(f"Supervisor sync timeout ({self.timeout}s)")
            raise SupervisorAPIError(f"Request timeout ({self.timeout}s)")
        except aiohttp.ClientError as e:
            logger.error(f"Supervisor network error: {e}")
            raise SupervisorAPIError(f"Network error: {e}")
        except Exception as e:
            logger.error(f"Supervisor sync error: {e}")
            raise SupervisorAPIError(f"Unexpected error: {e}")

    async def register_trade(
        self,
        trade_id: str,
        user_id: int,
        symbol: str,
        timeframe: str,
        side: str,
        scenario_data: Dict[str, Any]
    ) -> Dict:
        """
        Register new trade with scenario snapshot.

        Args:
            trade_id: Unique trade ID
            user_id: Telegram user ID
            symbol: Trading pair
            timeframe: Timeframe (1h, 4h, 1d)
            side: Position side (Long/Short)
            scenario_data: Full scenario from AI analysis

        Returns:
            Registration result with scenario_id
        """
        url = f"{self.api_url}/api/supervisor/register"

        payload = {
            "trade_id": trade_id,
            "user_id": user_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "scenario_data": scenario_data
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=self._get_headers(),
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:

                    if response.status != 200:
                        error_text = await response.text()
                        raise SupervisorAPIError(
                            f"Registration failed ({response.status}): {error_text[:200]}"
                        )

                    data = await response.json()

                    if not data.get("success"):
                        raise SupervisorAPIError(
                            f"Registration error: {data.get('detail', 'Unknown')}"
                        )

                    logger.info(
                        f"Registered trade {trade_id} with supervisor, "
                        f"scenario_id={data.get('scenario_id')}"
                    )

                    return data

        except SupervisorAPIError:
            raise
        except Exception as e:
            logger.error(f"Trade registration error: {e}")
            raise SupervisorAPIError(f"Registration failed: {e}")

    async def log_action_result(
        self,
        trade_id: str,
        action_id: str,
        status: str,
        details: Optional[Dict] = None
    ) -> bool:
        """
        Log action execution result.

        Args:
            trade_id: Trade ID
            action_id: Action ID from recommendation
            status: Result (applied/rejected/failed)
            details: Execution details (order_id, error, etc.)

        Returns:
            Success flag
        """
        url = f"{self.api_url}/api/supervisor/action-result"

        payload = {
            "trade_id": trade_id,
            "action_id": action_id,
            "status": status,
            "details": details
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=self._get_headers(),
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:

                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Action log failed: {error_text[:200]}")
                        return False

                    data = await response.json()
                    return data.get("success", False)

        except Exception as e:
            logger.error(f"Action log error: {e}")
            return False

    async def deactivate_scenario(
        self,
        trade_id: str,
        reason: str = "position_closed"
    ) -> bool:
        """
        Deactivate scenario when position is closed.

        Args:
            trade_id: Trade ID
            reason: Deactivation reason

        Returns:
            Success flag
        """
        url = f"{self.api_url}/api/supervisor/deactivate"

        payload = {
            "trade_id": trade_id,
            "reason": reason
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=self._get_headers(),
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:

                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Deactivation failed: {error_text[:200]}")
                        return False

                    data = await response.json()
                    return data.get("success", False)

        except Exception as e:
            logger.error(f"Deactivation error: {e}")
            return False

    async def health_check(self) -> bool:
        """Check supervisor API health"""
        url = f"{self.api_url}/api/supervisor/health"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self._get_headers(),
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    return response.status == 200

        except Exception as e:
            logger.warning(f"Supervisor health check failed: {e}")
            return False


# Singleton instance
_supervisor_client = None


def get_supervisor_client() -> SupervisorClient:
    """Get singleton instance of SupervisorClient"""
    global _supervisor_client

    if _supervisor_client is None:
        _supervisor_client = SupervisorClient()

    return _supervisor_client
