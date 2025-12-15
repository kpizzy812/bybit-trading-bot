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
    # Обязательные поля (без дефолтов)
    trade_id: str
    user_id: int
    timestamp: str  # ISO format
    symbol: str
    side: str  # "Buy" or "Sell"
    entry_price: float
    qty: float
    leverage: int
    margin_mode: str
    stop_price: float
    risk_usd: float

    # Опциональные поля (с дефолтами)
    exit_price: Optional[float] = None
    tp_price: Optional[float] = None
    pnl_usd: Optional[float] = None
    pnl_percent: Optional[float] = None
    roe_percent: Optional[float] = None
    outcome: Optional[str] = None  # "win", "loss", "breakeven"
    rr_planned: Optional[float] = None
    rr_actual: Optional[float] = None
    status: str = "closed"  # "closed", "liquidated", "partial", "open"
    testnet: bool = False  # True если сделка на testnet

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

    async def _replace_trade(self, user_id: int, updated_trade: TradeRecord):
        """
        Заменить существующую сделку на обновленную (избегаем дубликатов)

        Args:
            user_id: ID пользователя
            updated_trade: Обновленная запись
        """
        if self.use_redis and self.redis:
            try:
                key = self._trades_key(user_id)

                # Получаем все сделки
                all_trades_json = await self.redis.lrange(key, 0, -1)

                # Удаляем старую запись с тем же trade_id
                for trade_json in all_trades_json:
                    try:
                        trade_dict = json.loads(trade_json)
                        if trade_dict.get('trade_id') == updated_trade.trade_id:
                            # Удаляем эту запись
                            await self.redis.lrem(key, 1, trade_json)
                            break
                    except Exception as e:
                        logger.error(f"Error parsing trade during replace: {e}")

                # Добавляем обновленную в начало
                updated_json = json.dumps(updated_trade.to_dict())
                await self.redis.lpush(key, updated_json)

                # Обрезаем список
                await self.redis.ltrim(key, 0, self.max_trades_per_user - 1)

                logger.info(f"Trade replaced for user {user_id}: {updated_trade.trade_id}")
                return

            except Exception as e:
                logger.error(f"Error replacing trade in Redis: {e}")

        # Fallback to in-memory
        if user_id not in self.in_memory_trades:
            self.in_memory_trades[user_id] = []

        # Удаляем старую запись с тем же trade_id
        self.in_memory_trades[user_id] = [
            t for t in self.in_memory_trades[user_id]
            if t.trade_id != updated_trade.trade_id
        ]

        # Добавляем обновленную в начало
        self.in_memory_trades[user_id].insert(0, updated_trade)

        # Обрезаем до max_trades
        self.in_memory_trades[user_id] = self.in_memory_trades[user_id][:self.max_trades_per_user]

        logger.info(f"Trade replaced (in-memory) for user {user_id}: {updated_trade.trade_id}")

    async def get_trades(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        testnet: Optional[bool] = None
    ) -> List[TradeRecord]:
        """
        Получить историю сделок

        Args:
            user_id: ID пользователя
            limit: Количество сделок
            offset: Смещение (для пагинации)
            symbol: Фильтр по символу (опционально)
            side: Фильтр по направлению (опционально)
            testnet: Фильтр по режиму (True=testnet, False=live, None=все)

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

        if testnet is not None:
            trades = [t for t in trades if getattr(t, 'testnet', False) == testnet]

        return trades

    async def update_trade_on_close(
        self,
        user_id: int,
        symbol: str,
        exit_price: float,
        pnl_usd: float,
        closed_qty: float = None,
        is_partial: bool = False,
        testnet: Optional[bool] = None
    ):
        """
        Обновить сделку при закрытии позиции

        Args:
            user_id: ID пользователя
            symbol: Символ закрытой позиции
            exit_price: Цена закрытия
            pnl_usd: PnL в USD
            closed_qty: Закрытое количество (для partial)
            is_partial: Частичное закрытие или полное
            testnet: Фильтр по режиму (True=testnet, False=live, None=все)
        """
        # Получаем все сделки пользователя для текущего режима
        all_trades = await self.get_trades(user_id, limit=100, testnet=testnet)

        # Ищем последнюю открытую сделку по символу
        target_trade = None
        for trade in all_trades:
            if trade.symbol == symbol and trade.status in ["open", "partial"]:
                target_trade = trade
                break

        if not target_trade:
            logger.warning(f"No open trade found for {symbol} (user {user_id})")
            return

        # Обновляем данные
        target_trade.exit_price = exit_price
        target_trade.pnl_usd = (target_trade.pnl_usd or 0) + pnl_usd

        # Рассчитываем outcome
        if target_trade.pnl_usd > 0:
            target_trade.outcome = "win"
        elif target_trade.pnl_usd < 0:
            target_trade.outcome = "loss"
        else:
            target_trade.outcome = "breakeven"

        # Рассчитываем ROE% и actual RR
        if target_trade.entry_price > 0 and target_trade.qty > 0:
            # ROE = (PnL / (qty * entry)) * leverage * 100
            position_value = target_trade.qty * target_trade.entry_price
            target_trade.roe_percent = (target_trade.pnl_usd / position_value) * target_trade.leverage * 100

            # Actual RR
            if target_trade.risk_usd > 0:
                target_trade.rr_actual = target_trade.pnl_usd / target_trade.risk_usd

        # PnL %
        if target_trade.risk_usd > 0:
            target_trade.pnl_percent = (target_trade.pnl_usd / target_trade.risk_usd) * 100

        # Обновляем статус
        if is_partial:
            target_trade.status = "partial"
        else:
            target_trade.status = "closed"

        # Обновляем timestamp закрытия
        target_trade.timestamp = datetime.utcnow().isoformat()

        # Удаляем старую запись и добавляем обновленную
        await self._replace_trade(user_id, target_trade)

        logger.info(f"Trade updated on close: {target_trade.trade_id} (PnL: ${pnl_usd:+.2f})")

    async def get_statistics(self, user_id: int, limit: int = 100, testnet: Optional[bool] = None) -> Dict:
        """
        Получить статистику по сделкам

        Args:
            user_id: ID пользователя
            limit: Количество последних сделок для анализа
            testnet: Фильтр по режиму (True=testnet, False=live, None=все)

        Returns:
            Dict со статистикой
        """
        trades = await self.get_trades(user_id, limit=limit, testnet=testnet)

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

        # === EXPECTANCY CALCULATION ===
        # Expectancy = (Win Rate * Avg Win) - (Loss Rate * Avg Loss)
        # Показывает ожидаемую прибыль на 1 сделку
        win_rate_decimal = len(wins) / total_trades if total_trades > 0 else 0
        loss_rate_decimal = len(losses) / total_trades if total_trades > 0 else 0

        expectancy = (win_rate_decimal * avg_win) - (loss_rate_decimal * abs(avg_loss))

        # Expectancy в R (относительно среднего риска)
        avg_risk = sum(t.risk_usd for t in trades if t.risk_usd) / total_trades if total_trades > 0 else 1
        expectancy_r = expectancy / avg_risk if avg_risk > 0 else 0

        # Profit Factor = Gross Profit / Gross Loss
        gross_profit = sum(t.pnl_usd for t in wins if t.pnl_usd and t.pnl_usd > 0)
        gross_loss = abs(sum(t.pnl_usd for t in losses if t.pnl_usd and t.pnl_usd < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

        # Win/Loss streaks
        current_streak = 0
        max_win_streak = 0
        max_loss_streak = 0
        for trade in trades:
            if trade.outcome == 'win':
                if current_streak >= 0:
                    current_streak += 1
                    max_win_streak = max(max_win_streak, current_streak)
                else:
                    current_streak = 1
            elif trade.outcome == 'loss':
                if current_streak <= 0:
                    current_streak -= 1
                    max_loss_streak = max(max_loss_streak, abs(current_streak))
                else:
                    current_streak = -1

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
            'symbols': symbols_stats,
            # === NEW: Advanced Analytics ===
            'expectancy': expectancy,  # $ per trade
            'expectancy_r': expectancy_r,  # R per trade
            'profit_factor': profit_factor,
            'avg_risk': avg_risk,
            'win_count': len(wins),
            'loss_count': len(losses),
            'max_win_streak': max_win_streak,
            'max_loss_streak': max_loss_streak
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
