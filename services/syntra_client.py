"""
Syntra AI Client

Клиент для интеграции с аналитической системой Syntra AI.
Получает торговые сценарии с конкретными уровнями входа, стопа и целей.
"""
import asyncio
import aiohttp
from typing import Dict, List, Optional, Any
from loguru import logger

import config


class SyntraAPIError(Exception):
    """Ошибка при работе с Syntra AI API"""
    pass


class SyntraClient:
    """
    Клиент для работы с Syntra AI API

    Endpoints:
    - GET /api/futures-scenarios - получить торговые сценарии
    - POST /api/calculate-position-size - рассчитать размер позиции (опционально)
    """

    def __init__(self, api_url: str = None, api_key: str = None, timeout: int = None):
        """
        Args:
            api_url: URL Syntra AI API (default: из config)
            api_key: API ключ для аутентификации (default: из config)
            timeout: Таймаут запросов в секундах (default: из config)
        """
        self.api_url = api_url or config.SYNTRA_API_URL
        self.api_key = api_key or config.SYNTRA_API_KEY
        self.timeout = timeout or config.SYNTRA_API_TIMEOUT

        logger.info(f"SyntraClient initialized: {self.api_url}")

    def _get_headers(self) -> Dict[str, str]:
        """Получить headers для запроса"""
        headers = {"Content-Type": "application/json"}

        # Добавить API key если есть
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        return headers

    async def get_scenarios(
        self,
        symbol: str,
        timeframe: str = "4h",
        max_scenarios: int = 3,
        user_params: Optional[Dict[str, Any]] = None
    ) -> List[Dict]:
        """
        Получить торговые сценарии от Syntra AI

        Args:
            symbol: Торговая пара (BTCUSDT, ETHUSDT, etc.)
            timeframe: Таймфрейм (1h, 4h, 1d)
            max_scenarios: Максимум сценариев (1-5)
            user_params: Опциональные параметры пользователя для фильтрации
                {
                    "risk_usd": 10,
                    "max_leverage": 5,
                    "prefer_tight_stops": True
                }

        Returns:
            List[Dict]: Список торговых сценариев

        Example:
            >>> scenarios = await syntra.get_scenarios("BTCUSDT")
            >>> best = max(scenarios, key=lambda x: x["confidence"])
        """
        url = f"{self.api_url}/api/futures-scenarios"

        payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "max_scenarios": max_scenarios
        }

        # Добавить user_params если есть
        if user_params:
            payload["user_params"] = user_params

        logger.info(f"Requesting scenarios: {symbol} {timeframe}")

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
                        raise SyntraAPIError(
                            f"API error {response.status}: {error_text}"
                        )

                    data = await response.json()

                    if not data.get("success"):
                        raise SyntraAPIError(
                            f"API returned error: {data.get('error', 'Unknown error')}"
                        )

                    scenarios = data.get("scenarios", [])
                    logger.info(f"Received {len(scenarios)} scenarios for {symbol}")

                    return scenarios

        except asyncio.TimeoutError:
            logger.error(f"Timeout after {self.timeout}s waiting for Syntra AI response")
            raise SyntraAPIError(f"Request timeout ({self.timeout}s) - Syntra AI is too slow")

        except aiohttp.ClientError as e:
            logger.error(f"Network error: {e}")
            raise SyntraAPIError(f"Failed to connect to Syntra AI: {e}")

        except Exception as e:
            logger.error(f"Unexpected error ({type(e).__name__}): {e}", exc_info=True)
            raise SyntraAPIError(f"Unexpected error ({type(e).__name__}): {e}")

    async def calculate_position_size(
        self,
        scenario_id: Optional[str] = None,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        entry_price_min: Optional[float] = None,
        entry_price_max: Optional[float] = None,
        stop_loss: Optional[float] = None,
        risk_usd: float = 10.0,
        leverage: int = 5,
        account_balance: Optional[float] = None,
        max_margin: Optional[float] = None,
        max_risk: Optional[float] = None
    ) -> Dict:
        """
        Рассчитать размер позиции (опциональный endpoint)

        ВАЖНО: Этот endpoint нужен только если Syntra AI предоставляет расчёт позиции.
        В большинстве случаев Trade Bot рассчитывает позицию сам через RiskCalculator!

        Args:
            scenario_id: ID сценария (или параметры вручную)
            symbol: Торговая пара
            side: "long" | "short"
            entry_price_min: Минимальная цена входа
            entry_price_max: Максимальная цена входа
            stop_loss: Цена стопа
            risk_usd: Риск в USD
            leverage: Плечо
            account_balance: Баланс аккаунта
            max_margin: Макс. маржа на сделку
            max_risk: Макс. риск на сделку

        Returns:
            Dict с расчётами позиции

        Raises:
            SyntraAPIError: Если endpoint не доступен или ошибка расчёта
        """
        url = f"{self.api_url}/api/calculate-position-size"

        payload = {
            "risk_usd": risk_usd,
            "leverage": leverage
        }

        # Использовать scenario_id или параметры вручную
        if scenario_id:
            payload["scenario_id"] = scenario_id
        else:
            if not all([symbol, side, entry_price_min, entry_price_max, stop_loss]):
                raise ValueError(
                    "Either scenario_id or (symbol, side, entry, stop_loss) required"
                )

            payload.update({
                "symbol": symbol,
                "side": side,
                "entry_price_min": entry_price_min,
                "entry_price_max": entry_price_max,
                "stop_loss": stop_loss
            })

        # Опциональные параметры
        if account_balance is not None:
            payload["account_balance"] = account_balance
        if max_margin is not None:
            payload["max_margin"] = max_margin
        if max_risk is not None:
            payload["max_risk"] = max_risk

        logger.info(f"Calculating position size: risk=${risk_usd}, leverage={leverage}x")

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
                        raise SyntraAPIError(
                            f"API error {response.status}: {error_text}"
                        )

                    data = await response.json()

                    if not data.get("success"):
                        raise SyntraAPIError(
                            f"API returned error: {data.get('error', 'Unknown error')}"
                        )

                    return data

        except asyncio.TimeoutError:
            logger.error(f"Timeout after {self.timeout}s waiting for Syntra AI response")
            raise SyntraAPIError(f"Request timeout ({self.timeout}s) - Syntra AI is too slow")

        except aiohttp.ClientError as e:
            logger.error(f"Network error: {e}")
            raise SyntraAPIError(f"Failed to connect to Syntra AI: {e}")

        except Exception as e:
            logger.error(f"Unexpected error ({type(e).__name__}): {e}", exc_info=True)
            raise SyntraAPIError(f"Unexpected error ({type(e).__name__}): {e}")

    async def health_check(self) -> bool:
        """
        Проверить доступность Syntra AI API

        Returns:
            bool: True если API доступен
        """
        url = f"{self.api_url}/api/futures-scenarios/health"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self._get_headers(),
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    return response.status == 200

        except Exception as e:
            logger.warning(f"Syntra AI health check failed: {e}")
            return False


# Singleton instance
_syntra_client = None


def get_syntra_client() -> SyntraClient:
    """Получить singleton instance Syntra клиента"""
    global _syntra_client

    if _syntra_client is None:
        _syntra_client = SyntraClient()

    return _syntra_client
