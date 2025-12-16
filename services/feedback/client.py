"""
Feedback Client

HTTP клиент для отправки feedback в Syntra API.
Поддерживает retry и idempotency.
"""
import logging
import aiohttp
from typing import Optional, Dict, Any
from datetime import datetime

import config
from services.feedback.models import TradeFeedback

logger = logging.getLogger(__name__)


class FeedbackClient:
    """
    HTTP клиент для Syntra Feedback API.

    Endpoints:
    - POST /api/feedback/submit - отправка feedback
    - GET /api/feedback/stats/confidence - статистика confidence buckets
    - GET /api/feedback/stats/archetypes - статистика архетипов
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.base_url = base_url or getattr(config, "SYNTRA_API_URL", "http://localhost:8003")
        self.api_key = api_key or getattr(config, "SYNTRA_API_KEY", "")
        self.timeout = timeout
        self.max_retries = max_retries

        # Remove trailing slash
        self.base_url = self.base_url.rstrip("/")

    async def submit(self, feedback: TradeFeedback) -> Dict[str, Any]:
        """
        Отправить feedback в Syntra API.

        Args:
            feedback: TradeFeedback объект

        Returns:
            Response dict с success, trade_id, duplicate, learning_triggered

        Raises:
            FeedbackSubmitError: При ошибке отправки
        """
        url = f"{self.base_url}/api/feedback/submit"

        # Конвертируем в dict
        payload = feedback.model_dump(mode="json", exclude_none=True)

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as response:
                        response_data = await response.json()

                        if response.status == 200:
                            logger.info(
                                f"Feedback submitted successfully: "
                                f"trade_id={feedback.trade_id}, "
                                f"duplicate={response_data.get('duplicate', False)}"
                            )
                            return response_data

                        elif response.status == 409:
                            # Duplicate - это не ошибка
                            logger.info(
                                f"Feedback duplicate detected: trade_id={feedback.trade_id}"
                            )
                            return {
                                "success": True,
                                "trade_id": feedback.trade_id,
                                "duplicate": True,
                            }

                        else:
                            error_msg = response_data.get("detail", f"HTTP {response.status}")
                            logger.warning(
                                f"Feedback submit failed (attempt {attempt}): {error_msg}"
                            )
                            last_error = FeedbackSubmitError(error_msg, response.status)

            except aiohttp.ClientError as e:
                logger.warning(f"Feedback submit network error (attempt {attempt}): {e}")
                last_error = FeedbackSubmitError(str(e), 0)

            except Exception as e:
                logger.error(f"Feedback submit unexpected error: {e}")
                last_error = FeedbackSubmitError(str(e), 0)

        # Все попытки исчерпаны
        raise last_error or FeedbackSubmitError("Unknown error", 0)

    async def submit_partial(
        self,
        trade_id: str,
        analysis_id: str,
        scenario_local_id: int,
        scenario_hash: str,
        event_type: str,
        data: Dict[str, Any],
        is_testnet: bool = False,
    ) -> Dict[str, Any]:
        """
        Отправить partial feedback (один из слоёв).

        Args:
            trade_id: UUID сделки
            analysis_id: UUID анализа
            scenario_local_id: ID сценария в рамках анализа
            scenario_hash: Hash сценария
            event_type: Тип события (execution, outcome, attribution)
            data: Данные слоя
            is_testnet: Флаг testnet

        Returns:
            Response dict
        """
        url = f"{self.base_url}/api/feedback/submit"

        idempotency_key = f"{trade_id}:{event_type}"

        payload = {
            "trade_id": trade_id,
            "analysis_id": analysis_id,
            "scenario_local_id": scenario_local_id,
            "scenario_hash": scenario_hash,
            "idempotency_key": idempotency_key,
            "is_testnet": is_testnet,
            event_type: data,
        }

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                response_data = await response.json()

                if response.status in (200, 409):
                    return response_data

                raise FeedbackSubmitError(
                    response_data.get("detail", f"HTTP {response.status}"),
                    response.status
                )

    async def get_confidence_stats(self) -> Dict[str, Any]:
        """Получить статистику confidence buckets."""
        url = f"{self.base_url}/api/feedback/stats/confidence"

        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status == 200:
                    return await response.json()
                raise FeedbackSubmitError(f"HTTP {response.status}", response.status)

    async def get_archetype_stats(self, min_trades: int = 10) -> Dict[str, Any]:
        """Получить статистику архетипов."""
        url = f"{self.base_url}/api/feedback/stats/archetypes"
        params = {"min_trades": min_trades}

        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status == 200:
                    return await response.json()
                raise FeedbackSubmitError(f"HTTP {response.status}", response.status)

    async def health_check(self) -> bool:
        """Проверка доступности Syntra API."""
        url = f"{self.base_url}/api/feedback/health"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    return response.status == 200
        except Exception:
            return False


class FeedbackSubmitError(Exception):
    """Ошибка отправки feedback."""

    def __init__(self, message: str, status_code: int):
        self.message = message
        self.status_code = status_code
        super().__init__(f"Feedback submit failed: {message} (status={status_code})")


# Singleton instance
feedback_client = FeedbackClient()
