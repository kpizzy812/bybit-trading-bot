"""
Trade Logger v2 для хранения истории сделок
Использует Redis для хранения или in-memory fallback
"""
import json
import logging
import uuid
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field, fields
from datetime import datetime
import redis.asyncio as aioredis
import config

logger = logging.getLogger(__name__)

# === FEE CONSTANTS (Bybit Perpetual) ===
TAKER_FEE_RATE = 0.00055  # 0.055%
MAKER_FEE_RATE = 0.0002   # 0.02%


@dataclass
class TradeFill:
    """Запись о частичном закрытии"""
    fill_id: str
    timestamp: str  # ISO format
    price: float
    qty: float
    pnl_usd: float
    fee_usd: float
    reason: str  # "tp1", "tp2", "tp3", "sl", "manual", "liquidation", "breakeven"

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'TradeFill':
        return cls(**data)


@dataclass
class TradeRecord:
    """Запись о сделке v2"""

    # === ИДЕНТИФИКАЦИЯ (обязательные) ===
    trade_id: str
    user_id: int
    symbol: str
    side: str  # "Long" / "Short"

    # === TIMESTAMPS ===
    opened_at: str  # ISO format - время открытия

    # === ENTRY DATA (обязательные) ===
    entry_price: float
    qty: float
    leverage: int
    margin_mode: str
    margin_usd: float  # = (qty * entry) / leverage

    # === PLANNED (что планировали) ===
    stop_price: float
    risk_usd: float

    # === ОПЦИОНАЛЬНЫЕ С ДЕФОЛТАМИ ===
    closed_at: Optional[str] = None  # ISO format - время закрытия
    tp_price: Optional[float] = None
    rr_planned: Optional[float] = None

    # === ACTUAL (что получилось) ===
    exit_price: Optional[float] = None
    pnl_usd: Optional[float] = None
    pnl_percent: Optional[float] = None     # pnl / risk * 100
    roe_percent: Optional[float] = None     # pnl / margin * 100
    rr_actual: Optional[float] = None
    outcome: Optional[str] = None           # "win", "loss", "breakeven"
    exit_reason: Optional[str] = None       # "tp", "sl", "manual", "liquidated", "breakeven", "time_stop"

    # === FILLS (частичные закрытия) ===
    fills: Optional[List[Dict]] = None
    closed_qty: float = 0.0
    remaining_qty: Optional[float] = None
    avg_exit_price: Optional[float] = None

    # === FEES ===
    entry_fee_usd: Optional[float] = None
    exit_fees_usd: Optional[float] = None
    total_fees_usd: Optional[float] = None
    funding_usd: Optional[float] = None

    # === MAE/MFE (через цену) ===
    min_price_seen: Optional[float] = None
    max_price_seen: Optional[float] = None
    mae_usd: Optional[float] = None
    mae_r: Optional[float] = None
    mfe_usd: Optional[float] = None
    mfe_r: Optional[float] = None

    # === AI SCENARIO ===
    scenario_id: Optional[str] = None
    scenario_source: str = "manual"  # "syntra", "manual", "signal"
    scenario_bias: Optional[str] = None
    scenario_confidence: Optional[float] = None
    timeframe: Optional[str] = None
    entry_reason: Optional[str] = None
    validation_status: Optional[str] = None
    scenario_snapshot: Optional[Dict] = None

    # === POST-SL ANALYSIS ===
    post_sl_price_1h: Optional[float] = None
    post_sl_price_4h: Optional[float] = None
    sl_was_correct: Optional[bool] = None
    post_sl_move_pct: Optional[float] = None

    # === META ===
    status: str = "open"  # "open", "partial", "closed", "liquidated"
    testnet: bool = False

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'TradeRecord':
        """Создать TradeRecord из словаря с поддержкой старых записей"""
        # Получаем имена валидных полей
        valid_fields = {f.name for f in fields(cls)}

        # Фильтруем только известные поля
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}

        return cls(**filtered_data)


def calculate_fee(price: float, qty: float, is_taker: bool = True) -> float:
    """Рассчитать комиссию за операцию"""
    rate = TAKER_FEE_RATE if is_taker else MAKER_FEE_RATE
    return price * qty * rate


def calculate_margin(entry_price: float, qty: float, leverage: int) -> float:
    """Рассчитать используемую маржу"""
    if leverage <= 0:
        leverage = 1
    return (entry_price * qty) / leverage


class TradeLogger:
    """
    Менеджер истории сделок v2
    Использует Redis List для хранения последних N сделок
    Ключи: user:{id}:trades:v2
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
            logger.info("Connected to Redis for trade history v2")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Falling back to in-memory")
            self.use_redis = False
            self.redis = None

    async def close(self):
        """Закрытие соединения"""
        if self.redis:
            await self.redis.close()

    def _trades_key(self, user_id: int) -> str:
        """Ключ для списка сделок пользователя (v2)"""
        return f"user:{user_id}:trades:v2"

    async def log_trade(self, trade_record: TradeRecord):
        """
        Логировать новую сделку

        Args:
            trade_record: Запись о сделке
        """
        user_id = trade_record.user_id

        if self.use_redis and self.redis:
            try:
                key = self._trades_key(user_id)
                trade_json = json.dumps(trade_record.to_dict())
                await self.redis.lpush(key, trade_json)
                await self.redis.ltrim(key, 0, self.max_trades_per_user - 1)
                logger.info(f"Trade logged for user {user_id}: {trade_record.trade_id}")
                return
            except Exception as e:
                logger.error(f"Error logging trade to Redis: {e}")

        # Fallback to in-memory
        if user_id not in self.in_memory_trades:
            self.in_memory_trades[user_id] = []
        self.in_memory_trades[user_id].insert(0, trade_record)
        self.in_memory_trades[user_id] = self.in_memory_trades[user_id][:self.max_trades_per_user]
        logger.info(f"Trade logged (in-memory) for user {user_id}: {trade_record.trade_id}")

    async def _replace_trade(self, user_id: int, updated_trade: TradeRecord):
        """Заменить существующую сделку на обновленную"""
        if self.use_redis and self.redis:
            try:
                key = self._trades_key(user_id)
                all_trades_json = await self.redis.lrange(key, 0, -1)

                for trade_json in all_trades_json:
                    try:
                        trade_dict = json.loads(trade_json)
                        if trade_dict.get('trade_id') == updated_trade.trade_id:
                            await self.redis.lrem(key, 1, trade_json)
                            break
                    except Exception as e:
                        logger.error(f"Error parsing trade during replace: {e}")

                updated_json = json.dumps(updated_trade.to_dict())
                await self.redis.lpush(key, updated_json)
                await self.redis.ltrim(key, 0, self.max_trades_per_user - 1)
                logger.debug(f"Trade replaced for user {user_id}: {updated_trade.trade_id}")
                return
            except Exception as e:
                logger.error(f"Error replacing trade in Redis: {e}")

        # Fallback to in-memory
        if user_id not in self.in_memory_trades:
            self.in_memory_trades[user_id] = []
        self.in_memory_trades[user_id] = [
            t for t in self.in_memory_trades[user_id]
            if t.trade_id != updated_trade.trade_id
        ]
        self.in_memory_trades[user_id].insert(0, updated_trade)
        self.in_memory_trades[user_id] = self.in_memory_trades[user_id][:self.max_trades_per_user]

    async def get_trades(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        testnet: Optional[bool] = None,
        status: Optional[str] = None
    ) -> List[TradeRecord]:
        """
        Получить историю сделок

        Args:
            user_id: ID пользователя
            limit: Количество сделок
            offset: Смещение (для пагинации)
            symbol: Фильтр по символу
            side: Фильтр по направлению
            testnet: Фильтр по режиму
            status: Фильтр по статусу ("open", "partial", "closed")
        """
        trades = []

        if self.use_redis and self.redis:
            try:
                key = self._trades_key(user_id)
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
        if status:
            trades = [t for t in trades if t.status == status]

        return trades

    async def get_trade_by_id(
        self,
        user_id: int,
        trade_id: str,
        testnet: Optional[bool] = None
    ) -> Optional[TradeRecord]:
        """Найти сделку по trade_id"""
        trades = await self.get_trades(user_id, limit=100, testnet=testnet)
        for trade in trades:
            if trade.trade_id == trade_id:
                return trade
        return None

    async def get_open_trade_by_symbol(
        self,
        user_id: int,
        symbol: str,
        testnet: Optional[bool] = None
    ) -> Optional[TradeRecord]:
        """Найти открытую сделку по символу"""
        trades = await self.get_trades(user_id, limit=100, testnet=testnet)
        for trade in trades:
            if trade.symbol == symbol and trade.status in ["open", "partial"]:
                return trade
        return None

    async def update_trade_on_close(
        self,
        user_id: int,
        trade_id: str,
        exit_price: float,
        pnl_usd: float,
        closed_qty: float,
        reason: str = "manual",
        is_final: bool = True,
        is_taker: bool = True,
        testnet: Optional[bool] = None
    ):
        """
        Обновить сделку при закрытии (полном или частичном)

        Args:
            user_id: ID пользователя
            trade_id: ID сделки (поиск по trade_id, не по symbol!)
            exit_price: Цена закрытия
            pnl_usd: PnL в USD для этого закрытия
            closed_qty: Закрытое количество
            reason: Причина ("tp1", "tp2", "sl", "manual", "liquidation")
            is_final: Финальное закрытие или частичное
            is_taker: Taker или Maker (для fees)
            testnet: Режим
        """
        # Ищем сделку по trade_id
        target_trade = await self.get_trade_by_id(user_id, trade_id, testnet)

        if not target_trade:
            logger.warning(f"Trade {trade_id} not found for update (user {user_id})")
            return

        # Рассчитываем fee для этого fill
        fill_fee = calculate_fee(exit_price, closed_qty, is_taker)

        # Создаём fill запись
        fill = TradeFill(
            fill_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            price=exit_price,
            qty=closed_qty,
            pnl_usd=pnl_usd,
            fee_usd=fill_fee,
            reason=reason
        )

        # Добавляем fill
        if target_trade.fills is None:
            target_trade.fills = []
        target_trade.fills.append(fill.to_dict())

        # Обновляем closed_qty и remaining_qty
        target_trade.closed_qty = (target_trade.closed_qty or 0) + closed_qty
        target_trade.remaining_qty = target_trade.qty - target_trade.closed_qty

        # Рассчитываем avg_exit_price (взвешенный по qty)
        total_value = sum(f['price'] * f['qty'] for f in target_trade.fills)
        total_qty = sum(f['qty'] for f in target_trade.fills)
        target_trade.avg_exit_price = total_value / total_qty if total_qty > 0 else exit_price
        target_trade.exit_price = target_trade.avg_exit_price

        # Обновляем PnL (накопительно)
        target_trade.pnl_usd = (target_trade.pnl_usd or 0) + pnl_usd

        # Обновляем exit fees (накопительно)
        target_trade.exit_fees_usd = (target_trade.exit_fees_usd or 0) + fill_fee
        target_trade.total_fees_usd = (target_trade.entry_fee_usd or 0) + (target_trade.exit_fees_usd or 0)

        # Рассчитываем ROE правильно (от margin!)
        if target_trade.margin_usd and target_trade.margin_usd > 0:
            target_trade.roe_percent = (target_trade.pnl_usd / target_trade.margin_usd) * 100

        # Рассчитываем actual RR
        if target_trade.risk_usd and target_trade.risk_usd > 0:
            target_trade.rr_actual = target_trade.pnl_usd / target_trade.risk_usd
            target_trade.pnl_percent = (target_trade.pnl_usd / target_trade.risk_usd) * 100

        # Определяем outcome
        if target_trade.pnl_usd > 0:
            target_trade.outcome = "win"
        elif target_trade.pnl_usd < 0:
            target_trade.outcome = "loss"
        else:
            target_trade.outcome = "breakeven"

        # Определяем exit_reason (итоговый)
        if reason in ["liquidation"]:
            target_trade.exit_reason = "liquidated"
        elif reason.startswith("tp"):
            target_trade.exit_reason = "tp"
        elif reason == "sl":
            target_trade.exit_reason = "sl"
        elif reason == "breakeven":
            target_trade.exit_reason = "breakeven"
        else:
            target_trade.exit_reason = "manual"

        # Обновляем статус и closed_at
        if is_final or (target_trade.remaining_qty is not None and target_trade.remaining_qty <= 0):
            target_trade.status = "liquidated" if reason == "liquidation" else "closed"
            target_trade.closed_at = datetime.utcnow().isoformat()
        else:
            target_trade.status = "partial"

        # Сохраняем
        await self._replace_trade(user_id, target_trade)
        logger.info(f"Trade {trade_id} updated: {reason}, PnL: ${pnl_usd:+.2f}, status: {target_trade.status}")

    async def update_mae_mfe(
        self,
        user_id: int,
        trade_id: str,
        current_price: float,
        testnet: Optional[bool] = None
    ):
        """
        Обновить MAE/MFE для открытой сделки
        Вызывается из position_monitor на каждом цикле
        """
        target_trade = await self.get_trade_by_id(user_id, trade_id, testnet)
        if not target_trade or target_trade.status not in ["open", "partial"]:
            return

        # Обновляем min/max price
        if target_trade.min_price_seen is None or current_price < target_trade.min_price_seen:
            target_trade.min_price_seen = current_price
        if target_trade.max_price_seen is None or current_price > target_trade.max_price_seen:
            target_trade.max_price_seen = current_price

        await self._replace_trade(user_id, target_trade)

    async def finalize_mae_mfe(
        self,
        user_id: int,
        trade_id: str,
        testnet: Optional[bool] = None
    ):
        """Финализировать расчёт MAE/MFE при закрытии сделки"""
        target_trade = await self.get_trade_by_id(user_id, trade_id, testnet)
        if not target_trade:
            return

        entry = target_trade.entry_price
        qty = target_trade.qty
        risk = target_trade.risk_usd or 1
        min_p = target_trade.min_price_seen or entry
        max_p = target_trade.max_price_seen or entry

        if target_trade.side == "Long":
            # Long: MAE когда цена падает, MFE когда растёт
            target_trade.mae_usd = (min_p - entry) * qty  # отрицательное
            target_trade.mfe_usd = (max_p - entry) * qty  # положительное
        else:
            # Short: MAE когда цена растёт, MFE когда падает
            target_trade.mae_usd = (entry - max_p) * qty  # отрицательное
            target_trade.mfe_usd = (entry - min_p) * qty  # положительное

        target_trade.mae_r = abs(target_trade.mae_usd) / risk if risk > 0 else 0
        target_trade.mfe_r = target_trade.mfe_usd / risk if risk > 0 else 0

        await self._replace_trade(user_id, target_trade)

    async def update_post_sl_analysis(
        self,
        user_id: int,
        trade_id: str,
        price_1h: Optional[float] = None,
        price_4h: Optional[float] = None,
        sl_was_correct: Optional[bool] = None,
        move_pct: Optional[float] = None,
        testnet: Optional[bool] = None
    ):
        """Обновить сделку с данными post-SL анализа"""
        target_trade = await self.get_trade_by_id(user_id, trade_id, testnet)
        if not target_trade:
            logger.warning(f"Trade {trade_id} not found for post-SL update")
            return

        if price_1h is not None:
            target_trade.post_sl_price_1h = price_1h
        if price_4h is not None:
            target_trade.post_sl_price_4h = price_4h
        if sl_was_correct is not None:
            target_trade.sl_was_correct = sl_was_correct
        if move_pct is not None:
            target_trade.post_sl_move_pct = move_pct

        await self._replace_trade(user_id, target_trade)
        logger.info(f"Post-SL analysis updated for trade {trade_id}")

    async def get_statistics(self, user_id: int, limit: int = 100, testnet: Optional[bool] = None) -> Dict:
        """Получить статистику по сделкам v2"""
        trades = await self.get_trades(user_id, limit=limit, testnet=testnet)

        # Фильтруем только закрытые сделки
        closed_trades = [t for t in trades if t.status in ["closed", "liquidated"]]

        if not closed_trades:
            return self._empty_stats()

        total_trades = len(closed_trades)
        wins = [t for t in closed_trades if t.outcome == 'win']
        losses = [t for t in closed_trades if t.outcome == 'loss']

        winrate = (len(wins) / total_trades * 100) if total_trades > 0 else 0

        # PnL (учитываем fees)
        total_pnl = sum(t.pnl_usd for t in closed_trades if t.pnl_usd is not None)
        total_fees = sum(t.total_fees_usd for t in closed_trades if t.total_fees_usd is not None)
        net_pnl = total_pnl - total_fees

        avg_win = sum(t.pnl_usd for t in wins if t.pnl_usd) / len(wins) if wins else 0
        avg_loss = sum(t.pnl_usd for t in losses if t.pnl_usd) / len(losses) if losses else 0

        # RR
        rr_values = [t.rr_actual for t in closed_trades if t.rr_actual is not None]
        avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0

        # Best/Worst
        pnl_values = [t.pnl_usd for t in closed_trades if t.pnl_usd is not None]
        best_trade = max(pnl_values) if pnl_values else 0
        worst_trade = min(pnl_values) if pnl_values else 0

        # Направления
        long_trades = len([t for t in closed_trades if t.side == 'Long'])
        short_trades = len([t for t in closed_trades if t.side == 'Short'])

        # По символам
        symbols_stats = {}
        for trade in closed_trades:
            symbol = trade.symbol
            if symbol not in symbols_stats:
                symbols_stats[symbol] = {'count': 0, 'pnl': 0, 'wins': 0}
            symbols_stats[symbol]['count'] += 1
            if trade.pnl_usd:
                symbols_stats[symbol]['pnl'] += trade.pnl_usd
            if trade.outcome == 'win':
                symbols_stats[symbol]['wins'] += 1

        # Expectancy
        win_rate_decimal = len(wins) / total_trades if total_trades > 0 else 0
        loss_rate_decimal = len(losses) / total_trades if total_trades > 0 else 0
        expectancy = (win_rate_decimal * avg_win) - (loss_rate_decimal * abs(avg_loss))
        avg_risk = sum(t.risk_usd for t in closed_trades if t.risk_usd) / total_trades if total_trades > 0 else 1
        expectancy_r = expectancy / avg_risk if avg_risk > 0 else 0

        # Profit Factor
        gross_profit = sum(t.pnl_usd for t in wins if t.pnl_usd and t.pnl_usd > 0)
        gross_loss = abs(sum(t.pnl_usd for t in losses if t.pnl_usd and t.pnl_usd < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

        # Streaks
        max_win_streak, max_loss_streak = self._calculate_streaks(closed_trades)

        # === NEW: MAE/MFE статистика ===
        mae_values = [t.mae_r for t in closed_trades if t.mae_r is not None]
        mfe_values = [t.mfe_r for t in closed_trades if t.mfe_r is not None]
        avg_mae_r = sum(mae_values) / len(mae_values) if mae_values else 0
        avg_mfe_r = sum(mfe_values) / len(mfe_values) if mfe_values else 0

        # === NEW: AI vs Manual ===
        ai_trades = [t for t in closed_trades if t.scenario_source == 'syntra']
        manual_trades = [t for t in closed_trades if t.scenario_source == 'manual']
        ai_winrate = len([t for t in ai_trades if t.outcome == 'win']) / len(ai_trades) * 100 if ai_trades else 0
        manual_winrate = len([t for t in manual_trades if t.outcome == 'win']) / len(manual_trades) * 100 if manual_trades else 0

        # === NEW: Confidence buckets ===
        confidence_stats = self._calculate_confidence_stats(closed_trades)

        return {
            'total_trades': total_trades,
            'winrate': winrate,
            'avg_rr': avg_rr,
            'total_pnl': total_pnl,
            'total_fees': total_fees,
            'net_pnl': net_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'best_trade': best_trade,
            'worst_trade': worst_trade,
            'long_trades': long_trades,
            'short_trades': short_trades,
            'symbols': symbols_stats,
            'expectancy': expectancy,
            'expectancy_r': expectancy_r,
            'profit_factor': profit_factor,
            'avg_risk': avg_risk,
            'win_count': len(wins),
            'loss_count': len(losses),
            'max_win_streak': max_win_streak,
            'max_loss_streak': max_loss_streak,
            # v2 additions
            'avg_mae_r': avg_mae_r,
            'avg_mfe_r': avg_mfe_r,
            'ai_trades_count': len(ai_trades),
            'ai_winrate': ai_winrate,
            'manual_trades_count': len(manual_trades),
            'manual_winrate': manual_winrate,
            'confidence_stats': confidence_stats
        }

    def _calculate_streaks(self, trades: List[TradeRecord]) -> tuple:
        """Рассчитать максимальные серии побед/поражений"""
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

        return max_win_streak, max_loss_streak

    def _calculate_confidence_stats(self, trades: List[TradeRecord]) -> Dict:
        """Статистика по confidence buckets"""
        buckets = {
            'low': {'range': '0-0.5', 'trades': [], 'wins': 0},
            'medium': {'range': '0.5-0.7', 'trades': [], 'wins': 0},
            'high': {'range': '0.7-1.0', 'trades': [], 'wins': 0}
        }

        for trade in trades:
            conf = trade.scenario_confidence
            if conf is None:
                continue

            if conf < 0.5:
                bucket = 'low'
            elif conf < 0.7:
                bucket = 'medium'
            else:
                bucket = 'high'

            buckets[bucket]['trades'].append(trade)
            if trade.outcome == 'win':
                buckets[bucket]['wins'] += 1

        result = {}
        for name, data in buckets.items():
            count = len(data['trades'])
            result[name] = {
                'range': data['range'],
                'count': count,
                'winrate': (data['wins'] / count * 100) if count > 0 else 0,
                'avg_pnl': sum(t.pnl_usd for t in data['trades'] if t.pnl_usd) / count if count > 0 else 0
            }

        return result

    def _empty_stats(self) -> Dict:
        """Пустая статистика"""
        return {
            'total_trades': 0,
            'winrate': 0,
            'avg_rr': 0,
            'total_pnl': 0,
            'total_fees': 0,
            'net_pnl': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'best_trade': 0,
            'worst_trade': 0,
            'long_trades': 0,
            'short_trades': 0,
            'symbols': {},
            'expectancy': 0,
            'expectancy_r': 0,
            'profit_factor': 0,
            'avg_risk': 0,
            'win_count': 0,
            'loss_count': 0,
            'max_win_streak': 0,
            'max_loss_streak': 0,
            'avg_mae_r': 0,
            'avg_mfe_r': 0,
            'ai_trades_count': 0,
            'ai_winrate': 0,
            'manual_trades_count': 0,
            'manual_winrate': 0,
            'confidence_stats': {}
        }


def create_trade_logger() -> TradeLogger:
    """Создать экземпляр TradeLogger"""
    redis_url = None
    if config.REDIS_HOST:
        redis_password_part = f":{config.REDIS_PASSWORD}@" if config.REDIS_PASSWORD else ""
        redis_url = f"redis://{redis_password_part}{config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}"
    return TradeLogger(redis_url)
