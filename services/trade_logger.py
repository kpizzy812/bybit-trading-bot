"""
Trade Logger для хранения истории сделок
Использует Redis для хранения или in-memory fallback
"""
import json
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass, asdict
from datetime import datetime
import redis.asyncio as aioredis
import config

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """Запись о закрытой сделке"""
    trade_id: str
    user_id: int
    timestamp: str  # ISO format

    # Trade params
    symbol: str
    side: str  # "Buy" or "Sell"
    entry_price: float
    exit_price: Optional[float] = None

    # Position details
    qty: float
    leverage: int
    margin_mode: str

    # Risk management
    stop_price: float
    tp_price: Optional[float] = None
    risk_usd: float

    # Results
    pnl_usd: Optional[float] = None
    pnl_percent: Optional[float] = None
    roe_percent: Optional[float] = None
    outcome: Optional[str] = None  # "win", "loss", "breakeven"

    # RR
    rr_planned: Optional[float] = None
    rr_actual: Optional[float] = None

    # Status
    status: str = "closed"  # "closed", "liquidated", "partial"

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'TradeRecord':
        return cls(**data)


class TradeLogger:
    """
    Менеджер истории сделок
    Использует Redis List для хранения последних N сделок
    """

    def __init__(self, redis_url: Optional[str] = None, max_trades_per_user: int = 100):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self.in_memory_trades: Dict[int, List[TradeRecord]] = {}
        self.use_redis = redis_url is not None
        self.max_trades_per_user = max_trades_per_user

    async def connect(self):
        """Подключение к Redis"""
        if not self.use_redis:
            logger.info("Using in-memory storage for trade history")
            return

        try:
            self.redis = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis.ping()
            logger.info("Connected to Redis for trade history")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Falling back to in-memory")
            self.use_redis = False
            self.redis = None

    async def close(self):
        """Закрытие соединения"""
        if self.redis:
            await self.redis.close()

    def _trades_key(self, user_id: int) -> str:
        """Ключ для списка сделок пользователя"""
        return f"user:{user_id}:trades"

    async def log_trade(self, trade_record: TradeRecord):
        """
        Логировать сделку

        Args:
            trade_record: Запись о сделке
        """
        user_id = trade_record.user_id

        if self.use_redis and self.redis:
            try:
                key = self._trades_key(user_id)

                # Добавляем в начало списка (LPUSH)
                trade_json = json.dumps(trade_record.to_dict())
                await self.redis.lpush(key, trade_json)

                # Обрезаем список до max_trades_per_user
                await self.redis.ltrim(key, 0, self.max_trades_per_user - 1)

                logger.info(f"Trade logged for user {user_id}: {trade_record.trade_id}")
                return

            except Exception as e:
                logger.error(f"Error logging trade to Redis: {e}")

        # Fallback to in-memory
        if user_id not in self.in_memory_trades:
            self.in_memory_trades[user_id] = []

        # Добавляем в начало
        self.in_memory_trades[user_id].insert(0, trade_record)

        # Обрезаем до max_trades
        self.in_memory_trades[user_id] = self.in_memory_trades[user_id][:self.max_trades_per_user]

        logger.info(f"Trade logged (in-memory) for user {user_id}: {trade_record.trade_id}")

    async def get_trades(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
        symbol: Optional[str] = None,
        side: Optional[str] = None
    ) -> List[TradeRecord]:
        """
        Получить историю сделок

        Args:
            user_id: ID пользователя
            limit: Количество сделок
            offset: Смещение (для пагинации)
            symbol: Фильтр по символу (опционально)
            side: Фильтр по направлению (опционально)

        Returns:
            Список TradeRecord
        """
        trades = []

        if self.use_redis and self.redis:
            try:
                key = self._trades_key(user_id)

                # Получаем сделки из Redis (LRANGE)
                end_index = offset + limit - 1
                trade_jsons = await self.redis.lrange(key, offset, end_index)

                for trade_json in trade_jsons:
                    try:
                        trade_dict = json.loads(trade_json)
                        trade = TradeRecord.from_dict(trade_dict)
                        trades.append(trade)
                    except Exception as e:
                        logger.error(f"Error parsing trade JSON: {e}")

            except Exception as e:
                logger.error(f"Error getting trades from Redis: {e}")
        else:
            # Fallback to in-memory
            if user_id in self.in_memory_trades:
                all_trades = self.in_memory_trades[user_id]
                trades = all_trades[offset:offset + limit]

        # Фильтрация
        if symbol:
            trades = [t for t in trades if t.symbol == symbol]

        if side:
            trades = [t for t in trades if t.side == side]

        return trades

    async def get_statistics(self, user_id: int, limit: int = 100) -> Dict:
        """
        Получить статистику по сделкам

        Args:
            user_id: ID пользователя
            limit: Количество последних сделок для анализа

        Returns:
            Dict со статистикой
        """
        trades = await self.get_trades(user_id, limit=limit)

        if not trades:
            return {
                'total_trades': 0,
                'winrate': 0,
                'avg_rr': 0,
                'total_pnl': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'best_trade': 0,
                'worst_trade': 0,
                'long_trades': 0,
                'short_trades': 0,
                'symbols': {}
            }

        # Подсчёт статистики
        total_trades = len(trades)
        wins = [t for t in trades if t.outcome == 'win']
        losses = [t for t in trades if t.outcome == 'loss']

        winrate = (len(wins) / total_trades * 100) if total_trades > 0 else 0

        # PnL
        total_pnl = sum(t.pnl_usd for t in trades if t.pnl_usd is not None)
        avg_win = sum(t.pnl_usd for t in wins if t.pnl_usd is not None) / len(wins) if wins else 0
        avg_loss = sum(t.pnl_usd for t in losses if t.pnl_usd is not None) / len(losses) if losses else 0

        # RR
        rr_values = [t.rr_actual for t in trades if t.rr_actual is not None]
        avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0

        # Best/Worst
        pnl_values = [t.pnl_usd for t in trades if t.pnl_usd is not None]
        best_trade = max(pnl_values) if pnl_values else 0
        worst_trade = min(pnl_values) if pnl_values else 0

        # Направления
        long_trades = len([t for t in trades if t.side == 'Buy'])
        short_trades = len([t for t in trades if t.side == 'Sell'])

        # По символам
        symbols_stats = {}
        for trade in trades:
            symbol = trade.symbol
            if symbol not in symbols_stats:
                symbols_stats[symbol] = {
                    'count': 0,
                    'pnl': 0,
                    'wins': 0
                }
            symbols_stats[symbol]['count'] += 1
            if trade.pnl_usd:
                symbols_stats[symbol]['pnl'] += trade.pnl_usd
            if trade.outcome == 'win':
                symbols_stats[symbol]['wins'] += 1

        return {
            'total_trades': total_trades,
            'winrate': winrate,
            'avg_rr': avg_rr,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'best_trade': best_trade,
            'worst_trade': worst_trade,
            'long_trades': long_trades,
            'short_trades': short_trades,
            'symbols': symbols_stats
        }


# Глобальный экземпляр
def create_trade_logger() -> TradeLogger:
    """Создать экземпляр TradeLogger"""
    # Redis URL
    redis_url = None
    if config.REDIS_HOST:
        redis_password_part = f":{config.REDIS_PASSWORD}@" if config.REDIS_PASSWORD else ""
        redis_url = f"redis://{redis_password_part}{config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}"

    return TradeLogger(redis_url)
