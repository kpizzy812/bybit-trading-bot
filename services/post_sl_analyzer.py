"""
Post-SL Analyzer — анализ цены после срабатывания Stop Loss

Отслеживает движение цены после SL и определяет:
- Цена продолжила падение → SL был правильным
- Цена развернулась → SL был неправильным (слишком тесный)

Это помогает оптимизировать установку стопов.
"""
import asyncio
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import json
import redis.asyncio as aioredis

from aiogram import Bot
from services.bybit import BybitClient
from typing import TYPE_CHECKING
import config

if TYPE_CHECKING:
    from services.trade_logger import TradeLogger

logger = logging.getLogger(__name__)


@dataclass
class SLEvent:
    """Событие срабатывания Stop Loss"""
    trade_id: str
    user_id: int
    symbol: str
    side: str  # "Buy" or "Sell" (направление позиции)
    entry_price: float
    sl_price: float
    sl_time: str  # ISO format
    # Анализ после SL
    price_after_1h: Optional[float] = None
    price_after_4h: Optional[float] = None
    sl_was_correct: Optional[bool] = None  # True если цена продолжила движение против позиции
    max_adverse_move: Optional[float] = None  # Максимальное движение против позиции после SL
    max_favorable_move: Optional[float] = None  # Максимальное движение в сторону позиции после SL
    analysis_complete: bool = False

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'SLEvent':
        return cls(**data)


class PostSLAnalyzer:
    """
    Анализатор движения цены после Stop Loss

    Запускает отложенные проверки цены через 1h и 4h после SL
    и определяет, был ли SL правильным решением.
    """

    def __init__(
        self,
        bot: Bot,
        trade_logger: Optional['TradeLogger'] = None,
        redis_url: Optional[str] = None,
        testnet: bool = False
    ):
        self.bot = bot
        self.trade_logger = trade_logger  # Для сохранения в TradeRecord
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self.use_redis = redis_url is not None
        self.testnet = testnet

        # In-memory fallback
        self.pending_events: Dict[str, SLEvent] = {}  # trade_id -> SLEvent

        # Scheduled checks: {trade_id: [asyncio.Task]}
        self._scheduled_tasks: Dict[str, List[asyncio.Task]] = {}

        # Bybit client для получения текущей цены
        self.client = BybitClient(testnet=testnet)

    async def connect(self):
        """Подключение к Redis"""
        if not self.use_redis:
            logger.info("PostSLAnalyzer: Using in-memory storage")
            return

        try:
            self.redis = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis.ping()
            logger.info("PostSLAnalyzer: Connected to Redis")
        except Exception as e:
            logger.warning(f"PostSLAnalyzer: Failed to connect to Redis: {e}")
            self.use_redis = False
            self.redis = None

    async def close(self):
        """Закрытие соединений и отмена задач"""
        # Отменяем все scheduled tasks
        for trade_id, tasks in self._scheduled_tasks.items():
            for task in tasks:
                task.cancel()
        self._scheduled_tasks.clear()

        if self.redis:
            await self.redis.close()

    def _sl_events_key(self, user_id: int) -> str:
        """Redis key для хранения SL событий пользователя"""
        return f"user:{user_id}:sl_events"

    async def register_sl_hit(
        self,
        trade_id: str,
        user_id: int,
        symbol: str,
        side: str,
        entry_price: float,
        sl_price: float
    ):
        """
        Зарегистрировать срабатывание Stop Loss для последующего анализа

        Args:
            trade_id: ID сделки
            user_id: ID пользователя
            symbol: Торговый символ (BTCUSDT)
            side: Направление позиции (Buy/Sell)
            entry_price: Цена входа
            sl_price: Цена стопа (цена выхода)
        """
        event = SLEvent(
            trade_id=trade_id,
            user_id=user_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            sl_price=sl_price,
            sl_time=datetime.utcnow().isoformat()
        )

        # Сохраняем событие
        await self._save_event(event)

        # Планируем проверки через 1h и 4h
        await self._schedule_checks(event)

        logger.info(f"PostSLAnalyzer: Registered SL hit for {symbol} (trade {trade_id})")

    async def _save_event(self, event: SLEvent):
        """Сохранить событие в хранилище"""
        if self.use_redis and self.redis:
            try:
                key = self._sl_events_key(event.user_id)
                event_json = json.dumps(event.to_dict())
                await self.redis.hset(key, event.trade_id, event_json)
                # TTL 7 дней
                await self.redis.expire(key, 7 * 24 * 60 * 60)
            except Exception as e:
                logger.error(f"Error saving SL event to Redis: {e}")
                self.pending_events[event.trade_id] = event
        else:
            self.pending_events[event.trade_id] = event

    async def _get_event(self, user_id: int, trade_id: str) -> Optional[SLEvent]:
        """Получить событие из хранилища"""
        if self.use_redis and self.redis:
            try:
                key = self._sl_events_key(user_id)
                event_json = await self.redis.hget(key, trade_id)
                if event_json:
                    return SLEvent.from_dict(json.loads(event_json))
            except Exception as e:
                logger.error(f"Error getting SL event from Redis: {e}")

        return self.pending_events.get(trade_id)

    async def _schedule_checks(self, event: SLEvent):
        """Запланировать проверки цены"""
        trade_id = event.trade_id

        # Отменяем предыдущие задачи если есть
        if trade_id in self._scheduled_tasks:
            for task in self._scheduled_tasks[trade_id]:
                task.cancel()

        # Создаем новые задачи
        tasks = []

        # Проверка через 1 час
        task_1h = asyncio.create_task(
            self._delayed_price_check(event, delay_hours=1)
        )
        tasks.append(task_1h)

        # Проверка через 4 часа (финальная)
        task_4h = asyncio.create_task(
            self._delayed_price_check(event, delay_hours=4, is_final=True)
        )
        tasks.append(task_4h)

        self._scheduled_tasks[trade_id] = tasks

        logger.debug(f"Scheduled price checks for trade {trade_id}")

    async def _delayed_price_check(
        self,
        event: SLEvent,
        delay_hours: int,
        is_final: bool = False
    ):
        """Отложенная проверка цены"""
        try:
            # Ждём указанное время
            await asyncio.sleep(delay_hours * 60 * 60)

            # Получаем текущую цену
            current_price = await self._get_current_price(event.symbol)
            if current_price is None:
                logger.warning(f"Could not get price for {event.symbol}")
                return

            # Получаем актуальное событие из хранилища
            updated_event = await self._get_event(event.user_id, event.trade_id)
            if not updated_event:
                logger.warning(f"SL event {event.trade_id} not found")
                return

            # Обновляем данные
            if delay_hours == 1:
                updated_event.price_after_1h = current_price
            elif delay_hours == 4:
                updated_event.price_after_4h = current_price

            # Анализируем движение
            self._analyze_price_movement(updated_event, current_price)

            if is_final:
                updated_event.analysis_complete = True

                # === СОХРАНЯЕМ В TRADERECORD ДЛЯ ИСТОРИИ ===
                if self.trade_logger:
                    try:
                        # Рассчитываем % движения для TradeRecord
                        move_pct = ((current_price - updated_event.sl_price) / updated_event.sl_price) * 100
                        # Для Long: + = хорошо (цена выросла), - = плохо
                        # Для Short: - = хорошо (цена упала), + = плохо
                        if updated_event.side == "Sell":
                            move_pct = -move_pct  # Инвертируем для Short

                        await self.trade_logger.update_post_sl_analysis(
                            user_id=updated_event.user_id,
                            trade_id=updated_event.trade_id,
                            price_1h=updated_event.price_after_1h,
                            price_4h=updated_event.price_after_4h,
                            sl_was_correct=updated_event.sl_was_correct,
                            move_pct=move_pct,
                            testnet=self.testnet
                        )
                        logger.info(f"Post-SL data saved to TradeRecord: {updated_event.trade_id}")
                    except Exception as tr_err:
                        logger.error(f"Failed to save post-SL to TradeRecord: {tr_err}")

                # Отправляем уведомление с результатами
                await self._send_analysis_notification(updated_event)
                # Удаляем из scheduled tasks
                if event.trade_id in self._scheduled_tasks:
                    del self._scheduled_tasks[event.trade_id]

            # Сохраняем обновлённое событие
            await self._save_event(updated_event)

            logger.info(
                f"Price check {delay_hours}h for {event.symbol}: "
                f"SL={event.sl_price:.4f} → Now={current_price:.4f}"
            )

        except asyncio.CancelledError:
            logger.debug(f"Price check task cancelled for {event.trade_id}")
        except Exception as e:
            logger.error(f"Error in delayed price check: {e}")

    def _analyze_price_movement(self, event: SLEvent, current_price: float):
        """
        Анализировать движение цены после SL

        Для Long: SL правильный если цена упала ещё ниже
        Для Short: SL правильный если цена выросла ещё выше
        """
        sl_price = event.sl_price

        if event.side == "Buy":  # Long позиция
            # Long: убыток если цена падает
            # SL правильный если текущая цена < sl_price
            move_pct = ((current_price - sl_price) / sl_price) * 100
            event.sl_was_correct = current_price < sl_price

            # Adverse move для Long = падение
            if current_price < sl_price:
                event.max_adverse_move = max(
                    event.max_adverse_move or 0,
                    abs(move_pct)
                )
            else:
                event.max_favorable_move = max(
                    event.max_favorable_move or 0,
                    move_pct
                )
        else:  # Short позиция
            # Short: убыток если цена растёт
            # SL правильный если текущая цена > sl_price
            move_pct = ((current_price - sl_price) / sl_price) * 100
            event.sl_was_correct = current_price > sl_price

            # Adverse move для Short = рост
            if current_price > sl_price:
                event.max_adverse_move = max(
                    event.max_adverse_move or 0,
                    move_pct
                )
            else:
                event.max_favorable_move = max(
                    event.max_favorable_move or 0,
                    abs(move_pct)
                )

    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """Получить текущую цену символа"""
        try:
            ticker = await self.client.get_ticker(symbol)
            if ticker:
                return float(ticker.get('lastPrice', 0))
        except Exception as e:
            logger.error(f"Error getting price for {symbol}: {e}")
        return None

    async def _send_analysis_notification(self, event: SLEvent):
        """Отправить уведомление с результатами анализа"""
        try:
            side_emoji = "🟢" if event.side == "Buy" else "🔴"
            side_text = "Long" if event.side == "Buy" else "Short"

            # Результат анализа
            if event.sl_was_correct:
                result_emoji = "✅"
                result_text = "SL был правильным"
                explanation = (
                    "Цена продолжила движение против позиции.\n"
                    "Стоп-лосс защитил от большего убытка."
                )
            else:
                result_emoji = "❌"
                result_text = "SL был слишком тесным"
                explanation = (
                    "Цена развернулась после SL.\n"
                    "Возможно, стоп был установлен слишком близко."
                )

            # Движения
            price_1h = event.price_after_1h
            price_4h = event.price_after_4h
            sl = event.sl_price

            move_1h = ((price_1h - sl) / sl * 100) if price_1h else 0
            move_4h = ((price_4h - sl) / sl * 100) if price_4h else 0

            message = f"""
📊 <b>Post-SL Analysis</b>

{side_emoji} {event.symbol} {side_text}

<b>Цена при SL:</b> ${event.sl_price:.4f}

<b>Движение после SL:</b>
• 1h: ${price_1h:.4f} ({move_1h:+.2f}%)
• 4h: ${price_4h:.4f} ({move_4h:+.2f}%)

{result_emoji} <b>{result_text}</b>
{explanation}

💡 Это помогает улучшить размещение стопов.
"""

            await self.bot.send_message(
                chat_id=event.user_id,
                text=message.strip(),
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Failed to send analysis notification: {e}")

    async def get_sl_statistics(self, user_id: int, limit: int = 50) -> Dict:
        """
        Получить статистику по SL

        Returns:
            Dict с метриками качества стопов
        """
        events = await self._get_all_events(user_id, limit)

        if not events:
            return {
                'total_sl_hits': 0,
                'analyzed': 0,
                'correct_sl_count': 0,
                'incorrect_sl_count': 0,
                'correct_sl_rate': 0,
                'avg_adverse_move': 0,
                'avg_favorable_move': 0
            }

        analyzed = [e for e in events if e.analysis_complete]
        correct = [e for e in analyzed if e.sl_was_correct]
        incorrect = [e for e in analyzed if not e.sl_was_correct]

        correct_rate = (len(correct) / len(analyzed) * 100) if analyzed else 0

        adverse_moves = [e.max_adverse_move for e in analyzed if e.max_adverse_move]
        favorable_moves = [e.max_favorable_move for e in analyzed if e.max_favorable_move]

        avg_adverse = sum(adverse_moves) / len(adverse_moves) if adverse_moves else 0
        avg_favorable = sum(favorable_moves) / len(favorable_moves) if favorable_moves else 0

        return {
            'total_sl_hits': len(events),
            'analyzed': len(analyzed),
            'correct_sl_count': len(correct),
            'incorrect_sl_count': len(incorrect),
            'correct_sl_rate': correct_rate,
            'avg_adverse_move': avg_adverse,
            'avg_favorable_move': avg_favorable
        }

    async def _get_all_events(self, user_id: int, limit: int = 50) -> List[SLEvent]:
        """Получить все SL события пользователя"""
        events = []

        if self.use_redis and self.redis:
            try:
                key = self._sl_events_key(user_id)
                all_events = await self.redis.hgetall(key)
                for trade_id, event_json in all_events.items():
                    try:
                        event = SLEvent.from_dict(json.loads(event_json))
                        events.append(event)
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Error getting SL events from Redis: {e}")

        # Добавляем in-memory события
        for event in self.pending_events.values():
            if event.user_id == user_id:
                events.append(event)

        # Сортируем по времени (новые первые) и ограничиваем
        events.sort(key=lambda e: e.sl_time, reverse=True)
        return events[:limit]


def create_post_sl_analyzer(
    bot: Bot,
    trade_logger: Optional['TradeLogger'] = None,
    testnet: bool = False
) -> PostSLAnalyzer:
    """Создать экземпляр PostSLAnalyzer"""
    redis_url = None
    if config.REDIS_HOST:
        redis_password_part = f":{config.REDIS_PASSWORD}@" if config.REDIS_PASSWORD else ""
        redis_url = f"redis://{redis_password_part}{config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}"

    return PostSLAnalyzer(
        bot=bot,
        trade_logger=trade_logger,
        redis_url=redis_url,
        testnet=testnet
    )
