"""
Feedback Queue

Redis очередь для отложенной отправки feedback.
Включает dead-letter queue и метрики.
"""
import json
import logging
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime
import redis.asyncio as aioredis

import config
from services.feedback.models import TradeFeedback
from services.feedback.client import FeedbackClient, FeedbackSubmitError

logger = logging.getLogger(__name__)


class FeedbackQueue:
    """
    Redis очередь для feedback с retry и dead-letter.

    Keys:
    - feedback:queue - основная очередь
    - feedback:dead_letter - неудачные сообщения после всех retry
    - feedback:metrics - счётчики метрик
    - feedback:processing - сообщения в обработке (для защиты от дублей)
    """

    QUEUE_KEY = "feedback:queue"
    DEAD_LETTER_KEY = "feedback:dead_letter"
    METRICS_KEY = "feedback:metrics"
    PROCESSING_KEY = "feedback:processing"

    MAX_RETRIES = 3
    RETRY_DELAYS = [60, 300, 900]  # 1min, 5min, 15min

    def __init__(
        self,
        redis_url: Optional[str] = None,
        client: Optional[FeedbackClient] = None,
    ):
        self.redis_url = redis_url or getattr(config, "REDIS_URL", None)
        self.redis: Optional[aioredis.Redis] = None
        self.client = client or FeedbackClient()
        self._processing = False
        self._task: Optional[asyncio.Task] = None

    async def connect(self):
        """Подключение к Redis."""
        if not self.redis_url:
            logger.warning("Redis URL not configured, feedback queue disabled")
            return

        try:
            self.redis = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis.ping()
            logger.info("Feedback queue connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis for feedback queue: {e}")
            self.redis = None

    async def close(self):
        """Закрытие соединения."""
        self._processing = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self.redis:
            await self.redis.close()

    async def enqueue(self, feedback: TradeFeedback) -> bool:
        """
        Добавить feedback в очередь.

        Args:
            feedback: TradeFeedback для отправки

        Returns:
            True если успешно добавлено
        """
        if not self.redis:
            logger.warning("Redis not available, feedback will be lost")
            return False

        try:
            item = {
                "payload": feedback.model_dump(mode="json", exclude_none=True),
                "retries": 0,
                "created_at": datetime.utcnow().isoformat(),
                "trade_id": feedback.trade_id,
            }

            await self.redis.lpush(self.QUEUE_KEY, json.dumps(item))
            await self._inc_metric("enqueued")

            logger.info(f"Feedback queued: trade_id={feedback.trade_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to enqueue feedback: {e}")
            return False

    async def enqueue_dict(self, payload: Dict[str, Any], trade_id: str) -> bool:
        """
        Добавить feedback dict в очередь.

        Args:
            payload: Feedback payload dict
            trade_id: ID сделки

        Returns:
            True если успешно добавлено
        """
        if not self.redis:
            return False

        try:
            item = {
                "payload": payload,
                "retries": 0,
                "created_at": datetime.utcnow().isoformat(),
                "trade_id": trade_id,
            }

            await self.redis.lpush(self.QUEUE_KEY, json.dumps(item))
            await self._inc_metric("enqueued")
            return True

        except Exception as e:
            logger.error(f"Failed to enqueue feedback dict: {e}")
            return False

    async def start_processing(self, interval: int = 60):
        """
        Запустить фоновую обработку очереди.

        Args:
            interval: Интервал между проверками (секунды)
        """
        if self._processing:
            logger.warning("Queue processing already running")
            return

        self._processing = True
        self._task = asyncio.create_task(self._process_loop(interval))
        logger.info(f"Feedback queue processing started (interval={interval}s)")

    async def stop_processing(self):
        """Остановить обработку очереди."""
        self._processing = False
        if self._task:
            self._task.cancel()

    async def _process_loop(self, interval: int):
        """Цикл обработки очереди."""
        while self._processing:
            try:
                await self.process_queue()
            except Exception as e:
                logger.error(f"Error in queue processing loop: {e}")

            await asyncio.sleep(interval)

    async def process_queue(self) -> int:
        """
        Обработать все сообщения в очереди.

        Returns:
            Количество обработанных сообщений
        """
        if not self.redis:
            return 0

        processed = 0

        while True:
            # Получаем сообщение из конца очереди (FIFO)
            item_json = await self.redis.rpop(self.QUEUE_KEY)
            if not item_json:
                break

            try:
                item = json.loads(item_json)
                success = await self._process_item(item)

                if success:
                    await self._inc_metric("success")
                    processed += 1
                else:
                    # Retry или dead letter
                    item["retries"] = item.get("retries", 0) + 1

                    if item["retries"] >= self.MAX_RETRIES:
                        # Dead letter
                        item["dead_letter_at"] = datetime.utcnow().isoformat()
                        await self.redis.lpush(self.DEAD_LETTER_KEY, json.dumps(item))
                        await self._inc_metric("dead_letter")

                        logger.warning(
                            f"Feedback moved to dead letter: "
                            f"trade_id={item.get('trade_id')}"
                        )
                    else:
                        # Re-queue для retry
                        await self._schedule_retry(item)
                        await self._inc_metric("retried")

            except Exception as e:
                logger.error(f"Error processing queue item: {e}")
                await self._inc_metric("errors")

        return processed

    async def _process_item(self, item: Dict[str, Any]) -> bool:
        """
        Обработать один элемент очереди.

        Returns:
            True если успешно отправлено
        """
        payload = item.get("payload", {})
        trade_id = item.get("trade_id", "unknown")

        try:
            # Создаём TradeFeedback из payload
            feedback = TradeFeedback(**payload)

            # Отправляем
            response = await self.client.submit(feedback)

            if response.get("success"):
                logger.info(f"Queued feedback sent: trade_id={trade_id}")
                return True

            return False

        except FeedbackSubmitError as e:
            logger.warning(
                f"Queued feedback submit failed: trade_id={trade_id}, error={e.message}"
            )
            return False

        except Exception as e:
            logger.error(f"Queued feedback processing error: {e}")
            return False

    async def _schedule_retry(self, item: Dict[str, Any]):
        """Запланировать retry с задержкой."""
        retries = item.get("retries", 0)
        delay_index = min(retries, len(self.RETRY_DELAYS) - 1)
        delay = self.RETRY_DELAYS[delay_index]

        item["next_retry_at"] = (
            datetime.utcnow().timestamp() + delay
        )

        # Добавляем в начало очереди (будет обработано позже)
        await self.redis.lpush(self.QUEUE_KEY, json.dumps(item))

        logger.debug(
            f"Feedback retry scheduled: trade_id={item.get('trade_id')}, "
            f"attempt={retries + 1}, delay={delay}s"
        )

    async def _inc_metric(self, metric: str):
        """Инкрементировать метрику."""
        if self.redis:
            await self.redis.hincrby(self.METRICS_KEY, metric, 1)

    async def get_metrics(self) -> Dict[str, Any]:
        """
        Получить метрики очереди.

        Returns:
            Dict с queue_size, dead_letter_size, success_count, etc.
        """
        if not self.redis:
            return {
                "queue_size": 0,
                "dead_letter_size": 0,
                "success_count": 0,
                "fail_count": 0,
                "retry_count": 0,
                "available": False,
            }

        try:
            queue_size = await self.redis.llen(self.QUEUE_KEY)
            dead_letter_size = await self.redis.llen(self.DEAD_LETTER_KEY)
            metrics = await self.redis.hgetall(self.METRICS_KEY)

            return {
                "queue_size": queue_size,
                "dead_letter_size": dead_letter_size,
                "success_count": int(metrics.get("success", 0)),
                "fail_count": int(metrics.get("dead_letter", 0)),
                "retry_count": int(metrics.get("retried", 0)),
                "enqueued_count": int(metrics.get("enqueued", 0)),
                "error_count": int(metrics.get("errors", 0)),
                "available": True,
            }

        except Exception as e:
            logger.error(f"Failed to get queue metrics: {e}")
            return {"available": False, "error": str(e)}

    async def get_dead_letters(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Получить сообщения из dead letter queue.

        Args:
            limit: Максимальное количество

        Returns:
            Список dead letter items
        """
        if not self.redis:
            return []

        try:
            items = await self.redis.lrange(self.DEAD_LETTER_KEY, 0, limit - 1)
            return [json.loads(item) for item in items]
        except Exception as e:
            logger.error(f"Failed to get dead letters: {e}")
            return []

    async def retry_dead_letter(self, trade_id: str) -> bool:
        """
        Переместить dead letter обратно в очередь для retry.

        Args:
            trade_id: ID сделки

        Returns:
            True если найдено и перемещено
        """
        if not self.redis:
            return False

        try:
            # Получаем все dead letters
            items = await self.redis.lrange(self.DEAD_LETTER_KEY, 0, -1)

            for i, item_json in enumerate(items):
                item = json.loads(item_json)
                if item.get("trade_id") == trade_id:
                    # Удаляем из dead letter
                    await self.redis.lrem(self.DEAD_LETTER_KEY, 1, item_json)

                    # Сбрасываем retries и добавляем в очередь
                    item["retries"] = 0
                    item["retried_from_dead_letter"] = True
                    await self.redis.lpush(self.QUEUE_KEY, json.dumps(item))

                    logger.info(f"Dead letter retried: trade_id={trade_id}")
                    return True

            return False

        except Exception as e:
            logger.error(f"Failed to retry dead letter: {e}")
            return False

    async def clear_dead_letters(self) -> int:
        """
        Очистить dead letter queue.

        Returns:
            Количество удалённых сообщений
        """
        if not self.redis:
            return 0

        try:
            count = await self.redis.llen(self.DEAD_LETTER_KEY)
            await self.redis.delete(self.DEAD_LETTER_KEY)
            logger.info(f"Dead letter queue cleared: {count} items")
            return count
        except Exception as e:
            logger.error(f"Failed to clear dead letters: {e}")
            return 0


# Singleton instance
feedback_queue = FeedbackQueue()
