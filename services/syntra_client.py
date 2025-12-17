"""
Syntra AI Client

Клиент для интеграции с аналитической системой Syntra AI.
Получает торговые сценарии с конкретными уровнями входа, стопа и целей.
"""
import asyncio
import aiohttp
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from loguru import logger

import config


class SyntraAPIError(Exception):
    """Ошибка при работе с Syntra AI API"""
    pass


@dataclass
class NoTradeSignal:
    """No-trade signal from API"""
    should_not_trade: bool = False
    confidence: float = 0.0
    category: str = ""
    reasons: List[str] = field(default_factory=list)
    wait_for: Optional[List[str]] = None
    estimated_wait_hours: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional['NoTradeSignal']:
        if not data:
            return None
        return cls(
            should_not_trade=data.get("should_not_trade", False),
            confidence=data.get("confidence", 0.0),
            category=data.get("category", ""),
            reasons=data.get("reasons", []),
            wait_for=data.get("wait_for"),
            estimated_wait_hours=data.get("estimated_wait_hours"),
        )


@dataclass
class MarketContext:
    """Market context from API"""
    trend: str = "neutral"
    phase: str = "unknown"
    sentiment: str = "neutral"
    volatility: str = "medium"
    bias: str = "neutral"
    strength: float = 0.5
    rsi: Optional[float] = None
    funding_rate_pct: Optional[float] = None
    long_short_ratio: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> 'MarketContext':
        if not data:
            return cls()
        return cls(
            trend=data.get("trend", "neutral"),
            phase=data.get("phase", "unknown"),
            sentiment=data.get("sentiment", "neutral"),
            volatility=data.get("volatility", "medium"),
            bias=data.get("bias", "neutral"),
            strength=data.get("strength", 0.5),
            rsi=data.get("rsi"),
            funding_rate_pct=data.get("funding_rate_pct"),
            long_short_ratio=data.get("long_short_ratio"),
        )


@dataclass
class SyntraAnalysisResponse:
    """Full response from Syntra API"""
    success: bool
    symbol: str
    timeframe: str
    analysis_id: str
    current_price: float
    market_context: MarketContext
    scenarios: List[Dict[str, Any]]
    no_trade: Optional[NoTradeSignal] = None
    key_levels: Optional[Dict[str, Any]] = None
    data_quality: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'SyntraAnalysisResponse':
        return cls(
            success=data.get("success", False),
            symbol=data.get("symbol", ""),
            timeframe=data.get("timeframe", "4h"),
            analysis_id=data.get("analysis_id", ""),
            current_price=data.get("current_price", 0.0),
            market_context=MarketContext.from_dict(data.get("market_context")),
            scenarios=data.get("scenarios", []),
            no_trade=NoTradeSignal.from_dict(data.get("no_trade")),
            key_levels=data.get("key_levels"),
            data_quality=data.get("data_quality"),
            metadata=data.get("metadata"),
        )


def _clean_error_response(status_code: int, error_text: str) -> str:
    """Очистить HTML из ответа сервера для читаемости"""
    if "<html" in error_text.lower():
        if status_code == 504:
            return "Gateway Timeout (nginx таймаут на сервере, нужно увеличить proxy_read_timeout)"
        elif status_code == 502:
            return "Bad Gateway (сервер недоступен)"
        elif status_code == 503:
            return "Service Unavailable"
        else:
            return f"HTTP {status_code}"
    return error_text[:200]  # Ограничить длину


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

    async def get_analysis(
        self,
        symbol: str,
        timeframe: str = "4h",
        max_scenarios: int = 3,
        user_params: Optional[Dict[str, Any]] = None
    ) -> SyntraAnalysisResponse:
        """
        Получить полный анализ от Syntra AI (включая market_context, no_trade, etc.)

        Args:
            symbol: Торговая пара (BTCUSDT, ETHUSDT, etc.)
            timeframe: Таймфрейм (1h, 4h, 1d)
            max_scenarios: Максимум сценариев (1-5)
            user_params: Опциональные параметры пользователя

        Returns:
            SyntraAnalysisResponse: Полный ответ API

        Example:
            >>> analysis = await syntra.get_analysis("BTCUSDT")
            >>> if analysis.no_trade and analysis.no_trade.should_not_trade:
            >>>     print("Don't trade:", analysis.no_trade.reasons)
        """
        url = f"{self.api_url}/api/futures-scenarios"

        payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "max_scenarios": max_scenarios
        }

        if user_params:
            payload["user_params"] = user_params

        logger.info(f"Requesting analysis: {symbol} {timeframe}")

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
                        clean_error = _clean_error_response(response.status, error_text)
                        raise SyntraAPIError(f"API error {response.status}: {clean_error}")

                    data = await response.json()

                    if not data.get("success"):
                        raise SyntraAPIError(
                            f"API returned error: {data.get('error', 'Unknown error')}"
                        )

                    analysis = SyntraAnalysisResponse.from_dict(data)

                    # Log summary
                    no_trade_info = ""
                    if analysis.no_trade and analysis.no_trade.should_not_trade:
                        no_trade_info = f", NO_TRADE: {analysis.no_trade.category}"

                    logger.info(
                        f"Received analysis for {symbol}: "
                        f"{len(analysis.scenarios)} scenarios, "
                        f"ctx={analysis.market_context.trend}/{analysis.market_context.sentiment}"
                        f"{no_trade_info}"
                    )

                    # Save to DB if enabled
                    try:
                        from database.repository import ScenarioRepository
                        await ScenarioRepository.save_analysis_response(
                            analysis_id=analysis.analysis_id,
                            symbol=analysis.symbol,
                            timeframe=analysis.timeframe,
                            current_price=analysis.current_price,
                            market_context=data.get("market_context", {}),
                            scenarios=analysis.scenarios,
                            no_trade=data.get("no_trade"),
                            key_levels=analysis.key_levels,
                            data_quality=analysis.data_quality,
                        )
                    except Exception as db_err:
                        logger.debug(f"DB save skipped: {db_err}")

                    return analysis

        except SyntraAPIError:
            raise

        except asyncio.TimeoutError:
            logger.error(f"Timeout after {self.timeout}s waiting for Syntra AI response")
            raise SyntraAPIError(f"Request timeout ({self.timeout}s) - Syntra AI is too slow")

        except aiohttp.ClientError as e:
            logger.error(f"Network error: {e}")
            raise SyntraAPIError(f"Failed to connect to Syntra AI: {e}")

        except Exception as e:
            logger.error(f"Unexpected error ({type(e).__name__}): {e}", exc_info=True)
            raise SyntraAPIError(f"Unexpected error ({type(e).__name__}): {e}")

    async def get_scenarios(
        self,
        symbol: str,
        timeframe: str = "4h",
        max_scenarios: int = 3,
        user_params: Optional[Dict[str, Any]] = None
    ) -> List[Dict]:
        """
        Получить торговые сценарии от Syntra AI (legacy метод для совместимости)

        Returns:
            List[Dict]: Список торговых сценариев
        """
        analysis = await self.get_analysis(symbol, timeframe, max_scenarios, user_params)
        return analysis.scenarios

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
                        clean_error = _clean_error_response(response.status, error_text)
                        raise SyntraAPIError(f"API error {response.status}: {clean_error}")

                    data = await response.json()

                    if not data.get("success"):
                        raise SyntraAPIError(
                            f"API returned error: {data.get('error', 'Unknown error')}"
                        )

                    return data

        except SyntraAPIError:
            raise  # Не оборачивать повторно

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
