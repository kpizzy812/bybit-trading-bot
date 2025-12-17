"""
EV Gate Checker - main logic for checking if trading is allowed.
"""
import logging
from typing import Optional
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from database.engine import get_session
from database.models import EVGateLog
from .models import (
    EVGroupKey, EVGroupStats, EVGateResult,
    GateStatus, FallbackChainItem, GroupLevel
)
from .calculator import RealEVCalculator
from .cache import EVCache
from .state import EVStateManager
import config

logger = logging.getLogger(__name__)


class EVGateChecker:
    """
    Проверяет можно ли торговать сценарий на основе Real EV.

    Использует 3-уровневую иерархию с fallback:
    L3 (archetype + timeframe + regime) → L2 (archetype + timeframe) → L1 (archetype)
    """

    def __init__(self):
        self.calculator = RealEVCalculator()
        self.cache = EVCache()
        self.state_manager = EVStateManager()

        # Config
        self.warn_threshold = getattr(config, 'EV_WARN_THRESHOLD', 0.0)
        self.disable_threshold = getattr(config, 'EV_DISABLE_THRESHOLD', -0.15)
        self.min_trades_warn = getattr(config, 'EV_MIN_TRADES_WARN', 10)
        self.min_trades_disable = getattr(config, 'EV_MIN_TRADES_DISABLE', 20)
        self.min_trades_l1 = 30  # L1 требует больше данных
        self.rolling_disable_threshold = getattr(config, 'EV_ROLLING_DISABLE_THRESHOLD', -0.10)
        self.show_warning = getattr(config, 'EV_SHOW_WARNING', True)

    async def check(
        self,
        archetype: str,
        timeframe: str,
        market_regime: Optional[str] = None,
        symbol: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> EVGateResult:
        """
        Проверить можно ли торговать сценарий.

        Args:
            archetype: Архетип сценария
            timeframe: Таймфрейм
            market_regime: Режим рынка (trend_phase)
            symbol: Символ (для логирования)
            user_id: ID пользователя (для логирования)

        Returns:
            EVGateResult с решением и debug информацией
        """
        fallback_chain = []

        # Собираем stats для всех уровней
        all_stats = await self.calculator.calculate_stats_for_scenario(
            archetype=archetype,
            timeframe=timeframe,
            market_regime=market_regime,
        )

        # Проверяем L3 → L2 → L1 с fallback
        selected_stats: Optional[EVGroupStats] = None
        selected_level: Optional[str] = None
        selected_key: Optional[str] = None

        # L3: archetype + timeframe + regime
        if all_stats.get('L3'):
            stats = all_stats['L3']
            meets = stats.sample_size >= self.min_trades_disable
            fallback_chain.append(FallbackChainItem(
                level='L3',
                key=stats.group_key,
                sample_size=stats.sample_size,
                real_ev=stats.real_ev,
                meets_threshold=meets,
                reason=f"n={stats.sample_size} {'≥' if meets else '<'} {self.min_trades_disable}",
            ))
            if meets:
                selected_stats = stats
                selected_level = 'L3'
                selected_key = stats.group_key

        # L2: archetype + timeframe
        if not selected_stats and all_stats.get('L2'):
            stats = all_stats['L2']
            meets = stats.sample_size >= self.min_trades_disable
            fallback_chain.append(FallbackChainItem(
                level='L2',
                key=stats.group_key,
                sample_size=stats.sample_size,
                real_ev=stats.real_ev,
                meets_threshold=meets,
                reason=f"n={stats.sample_size} {'≥' if meets else '<'} {self.min_trades_disable}",
            ))
            if meets:
                selected_stats = stats
                selected_level = 'L2'
                selected_key = stats.group_key

        # L1: archetype only
        if not selected_stats and all_stats.get('L1'):
            stats = all_stats['L1']
            meets = stats.sample_size >= self.min_trades_l1
            fallback_chain.append(FallbackChainItem(
                level='L1',
                key=stats.group_key,
                sample_size=stats.sample_size,
                real_ev=stats.real_ev,
                meets_threshold=meets,
                reason=f"n={stats.sample_size} {'≥' if meets else '<'} {self.min_trades_l1}",
            ))
            if meets:
                selected_stats = stats
                selected_level = 'L1'
                selected_key = stats.group_key

        # Определяем статус
        result = await self._determine_status(
            selected_stats=selected_stats,
            selected_level=selected_level,
            selected_key=selected_key,
            market_regime=market_regime,
            fallback_chain=fallback_chain,
        )

        # Логируем решение
        if user_id:
            await self._log_gate_decision(
                result=result,
                archetype=archetype,
                timeframe=timeframe,
                market_regime=market_regime,
                symbol=symbol or 'UNKNOWN',
                user_id=user_id,
            )

        return result

    async def _determine_status(
        self,
        selected_stats: Optional[EVGroupStats],
        selected_level: Optional[str],
        selected_key: Optional[str],
        market_regime: Optional[str],
        fallback_chain: list,
    ) -> EVGateResult:
        """Определить статус на основе stats."""

        # NO_DATA - недостаточно данных
        if not selected_stats:
            return EVGateResult(
                status=GateStatus.NO_DATA,
                selected_level=None,
                selected_key=None,
                stats=None,
                fallback_chain=fallback_chain,
                message="Недостаточно данных для оценки Real EV",
            )

        # Проверяем disabled state в БД
        if selected_key:
            is_disabled = await self.state_manager.is_disabled(selected_key)
            if is_disabled:
                return EVGateResult(
                    status=GateStatus.BLOCK,
                    selected_level=selected_level,
                    selected_key=selected_key,
                    stats=selected_stats,
                    fallback_chain=fallback_chain,
                    message=f"Группа {selected_key} отключена",
                )

        # BLOCK - real_ev <= threshold AND rolling <= threshold
        if (
            selected_stats.real_ev <= self.disable_threshold
            and selected_stats.rolling_ev is not None
            and selected_stats.rolling_ev <= self.rolling_disable_threshold
        ):
            return EVGateResult(
                status=GateStatus.BLOCK,
                selected_level=selected_level,
                selected_key=selected_key,
                stats=selected_stats,
                fallback_chain=fallback_chain,
                message=(
                    f"Real EV {selected_stats.real_ev:+.2f}R ≤ {self.disable_threshold}R, "
                    f"Rolling EV {selected_stats.rolling_ev:+.2f}R ≤ {self.rolling_disable_threshold}R"
                ),
            )

        # SOFT_BLOCK - real_ev < 0 в chop режиме
        is_chop = market_regime and 'chop' in market_regime.lower()
        if selected_stats.real_ev < self.warn_threshold and is_chop:
            return EVGateResult(
                status=GateStatus.SOFT_BLOCK,
                selected_level=selected_level,
                selected_key=selected_key,
                stats=selected_stats,
                fallback_chain=fallback_chain,
                message=(
                    f"Real EV {selected_stats.real_ev:+.2f}R < 0 в chop режиме. "
                    f"Рекомендуем пропустить."
                ),
            )

        # WARN - real_ev < 0 при достаточном sample
        if selected_stats.real_ev < self.warn_threshold:
            return EVGateResult(
                status=GateStatus.WARN,
                selected_level=selected_level,
                selected_key=selected_key,
                stats=selected_stats,
                fallback_chain=fallback_chain,
                message=f"Real EV {selected_stats.real_ev:+.2f}R отрицательный",
            )

        # ALLOWED - всё ок
        return EVGateResult(
            status=GateStatus.ALLOWED,
            selected_level=selected_level,
            selected_key=selected_key,
            stats=selected_stats,
            fallback_chain=fallback_chain,
            message=f"Real EV {selected_stats.real_ev:+.2f}R (n={selected_stats.sample_size})",
        )

    async def _log_gate_decision(
        self,
        result: EVGateResult,
        archetype: str,
        timeframe: str,
        market_regime: Optional[str],
        symbol: str,
        user_id: int,
    ) -> None:
        """Записать решение в ev_gate_log."""
        try:
            async for session in get_session():
                log_entry = EVGateLog(
                    user_id=user_id,
                    archetype=archetype,
                    timeframe=timeframe,
                    market_regime=market_regime,
                    symbol=symbol,
                    status=result.status.value,
                    selected_level=result.selected_level,
                    selected_key=result.selected_key,
                    real_ev=result.stats.real_ev if result.stats else None,
                    rolling_ev=result.stats.rolling_ev if result.stats else None,
                    sample_size=result.stats.sample_size if result.stats else None,
                )
                session.add(log_entry)
                await session.commit()
        except Exception as e:
            logger.error(f"Error logging gate decision: {e}")

    async def update_user_action(
        self,
        log_id: str,
        action: str,
    ) -> bool:
        """
        Обновить действие пользователя в логе.

        Args:
            log_id: ID записи в ev_gate_log
            action: proceeded, skipped, force_override
        """
        try:
            from sqlalchemy import update
            async for session in get_session():
                stmt = update(EVGateLog).where(
                    EVGateLog.id == log_id
                ).values(user_action=action)
                await session.execute(stmt)
                await session.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating user action: {e}")
            return False

    async def force_override(
        self,
        group_key: str,
        user_id: int,
        duration_hours: int = 24,
    ) -> bool:
        """
        Принудительно включить группу на время.

        Args:
            group_key: Ключ группы
            user_id: ID пользователя
            duration_hours: На сколько часов включить
        """
        return await self.state_manager.set_manual_override(
            group_key=group_key,
            user_id=user_id,
            duration_hours=duration_hours,
            reason=f"Force override by user {user_id}",
        )
