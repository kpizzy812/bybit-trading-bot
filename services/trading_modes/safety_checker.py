"""
Trading Modes - Safety Checker

Проверка safety caps перед торговлей:
- max_trades_per_day
- max_consecutive_losses
- daily_loss_cap_usd
- cooldown_after_loss
"""
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

from services.trading_modes.models import ModeConfig, SafetyCheckResult
from services.trading_modes.registry import get_mode_or_default


class SafetyChecker:
    """
    Проверка safety caps для режимов торговли.

    Использует trade_logger для получения истории сделок.
    """

    def __init__(self, trade_logger=None, redis_client=None):
        """
        Args:
            trade_logger: TradeLogger для получения истории
            redis_client: Redis для кэширования cooldown
        """
        self.trade_logger = trade_logger
        self.redis = redis_client

    async def check_can_trade(
        self,
        user_id: int,
        mode_id: str,
        risk_usd: float = 0.0
    ) -> SafetyCheckResult:
        """
        Проверить можно ли открыть сделку.

        Args:
            user_id: ID пользователя
            mode_id: ID режима торговли
            risk_usd: Планируемый риск в USD

        Returns:
            SafetyCheckResult с результатом проверки
        """
        mode = get_mode_or_default(mode_id)

        # Получаем статистику за сегодня
        stats = await self._get_today_stats(user_id, mode_id)

        trades_today = stats.get('trades_today', 0)
        losses_today = stats.get('losses_today', 0)
        loss_usd_today = stats.get('loss_usd_today', 0.0)
        consecutive_losses = stats.get('consecutive_losses', 0)
        last_loss_time = stats.get('last_loss_time')

        # 1. Проверка max_trades_per_day
        if trades_today >= mode.max_trades_per_day:
            return SafetyCheckResult(
                allowed=False,
                reason=f"Daily trade limit reached ({trades_today}/{mode.max_trades_per_day})",
                trades_today=trades_today,
                losses_today=losses_today,
                loss_today_usd=loss_usd_today,
                consecutive_losses=consecutive_losses
            )

        # 2. Проверка max_consecutive_losses
        if consecutive_losses >= mode.max_consecutive_losses:
            cooldown_remaining = await self._get_cooldown_remaining(
                user_id, mode_id, last_loss_time, mode.cooldown_after_loss_min
            )
            if cooldown_remaining > 0:
                return SafetyCheckResult(
                    allowed=False,
                    reason=f"Cooldown active after {consecutive_losses} consecutive losses",
                    cooldown_remaining_min=cooldown_remaining,
                    trades_today=trades_today,
                    losses_today=losses_today,
                    loss_today_usd=loss_usd_today,
                    consecutive_losses=consecutive_losses
                )

        # 3. Проверка daily_loss_cap_usd
        projected_loss = loss_usd_today + risk_usd
        if projected_loss > mode.daily_loss_cap_usd:
            return SafetyCheckResult(
                allowed=False,
                reason=f"Daily loss cap would be exceeded "
                       f"(${loss_usd_today:.2f} + ${risk_usd:.2f} > ${mode.daily_loss_cap_usd:.2f})",
                trades_today=trades_today,
                losses_today=losses_today,
                loss_today_usd=loss_usd_today,
                consecutive_losses=consecutive_losses
            )

        # 4. Проверка cooldown после loss
        if last_loss_time:
            cooldown_remaining = await self._get_cooldown_remaining(
                user_id, mode_id, last_loss_time, mode.cooldown_after_loss_min
            )
            if cooldown_remaining > 0:
                return SafetyCheckResult(
                    allowed=False,
                    reason=f"Cooldown active after last loss",
                    cooldown_remaining_min=cooldown_remaining,
                    trades_today=trades_today,
                    losses_today=losses_today,
                    loss_today_usd=loss_usd_today,
                    consecutive_losses=consecutive_losses
                )

        # Всё ок
        return SafetyCheckResult(
            allowed=True,
            trades_today=trades_today,
            losses_today=losses_today,
            loss_today_usd=loss_usd_today,
            consecutive_losses=consecutive_losses
        )

    async def _get_today_stats(self, user_id: int, mode_id: str) -> dict:
        """
        Получить статистику сделок за сегодня.

        Returns:
            Dict с полями: trades_today, losses_today, loss_usd_today,
                          consecutive_losses, last_loss_time
        """
        if not self.trade_logger:
            logger.warning("TradeLogger not available, safety checks limited")
            return {
                'trades_today': 0,
                'losses_today': 0,
                'loss_usd_today': 0.0,
                'consecutive_losses': 0,
                'last_loss_time': None
            }

        try:
            # Начало сегодняшнего дня (UTC)
            today_start = datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            # Получаем сделки за сегодня
            trades = await self.trade_logger.get_user_trades(
                user_id=user_id,
                since=today_start,
                mode_id=mode_id  # Фильтр по режиму если поддерживается
            )

            trades_today = len(trades)
            losses_today = 0
            loss_usd_today = 0.0
            last_loss_time = None

            # Считаем losses
            for trade in trades:
                if trade.get('pnl_usd', 0) < 0:
                    losses_today += 1
                    loss_usd_today += abs(trade.get('pnl_usd', 0))
                    closed_at = trade.get('closed_at')
                    if closed_at:
                        trade_time = datetime.fromisoformat(closed_at.replace('Z', '+00:00'))
                        if last_loss_time is None or trade_time > last_loss_time:
                            last_loss_time = trade_time

            # Consecutive losses (последние N сделок)
            consecutive_losses = await self._get_consecutive_losses(user_id, mode_id)

            return {
                'trades_today': trades_today,
                'losses_today': losses_today,
                'loss_usd_today': loss_usd_today,
                'consecutive_losses': consecutive_losses,
                'last_loss_time': last_loss_time
            }

        except Exception as e:
            logger.error(f"Failed to get today stats: {e}")
            return {
                'trades_today': 0,
                'losses_today': 0,
                'loss_usd_today': 0.0,
                'consecutive_losses': 0,
                'last_loss_time': None
            }

    async def _get_consecutive_losses(self, user_id: int, mode_id: str) -> int:
        """Получить количество последовательных losses."""
        if not self.trade_logger:
            return 0

        try:
            # Получаем последние N сделок
            recent_trades = await self.trade_logger.get_user_trades(
                user_id=user_id,
                limit=10,
                mode_id=mode_id
            )

            consecutive = 0
            for trade in reversed(recent_trades):  # От новых к старым
                if trade.get('pnl_usd', 0) < 0:
                    consecutive += 1
                else:
                    break  # Первый win - прерываем

            return consecutive

        except Exception as e:
            logger.error(f"Failed to get consecutive losses: {e}")
            return 0

    async def _get_cooldown_remaining(
        self,
        user_id: int,
        mode_id: str,
        last_loss_time: Optional[datetime],
        cooldown_min: int
    ) -> int:
        """
        Получить оставшееся время cooldown в минутах.

        Returns:
            0 если cooldown не активен, иначе минуты
        """
        if not last_loss_time:
            return 0

        # Убираем timezone info если есть
        if last_loss_time.tzinfo is not None:
            last_loss_time = last_loss_time.replace(tzinfo=None)

        cooldown_end = last_loss_time + timedelta(minutes=cooldown_min)
        now = datetime.utcnow()

        if now >= cooldown_end:
            return 0

        remaining = (cooldown_end - now).total_seconds() / 60
        return int(remaining) + 1  # Round up

    async def record_trade_result(
        self,
        user_id: int,
        mode_id: str,
        is_win: bool,
        pnl_usd: float
    ):
        """
        Записать результат сделки для safety tracking.

        Используется для обновления consecutive_losses и cooldown.
        """
        if self.redis:
            try:
                key = f"safety:{user_id}:{mode_id}"

                if is_win:
                    # Reset consecutive losses
                    await self.redis.hset(key, "consecutive_losses", 0)
                else:
                    # Increment consecutive losses
                    await self.redis.hincrby(key, "consecutive_losses", 1)
                    await self.redis.hset(key, "last_loss_time", datetime.utcnow().isoformat())

                # TTL 24 часа
                await self.redis.expire(key, 86400)

            except Exception as e:
                logger.error(f"Failed to record trade result: {e}")


# Глобальный instance
_checker: Optional[SafetyChecker] = None


def get_safety_checker(trade_logger=None, redis_client=None) -> SafetyChecker:
    """Получить глобальный safety checker."""
    global _checker
    if _checker is None or trade_logger is not None:
        _checker = SafetyChecker(trade_logger, redis_client)
    return _checker
