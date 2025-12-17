"""
Real EV Calculator - SQL aggregation logic.
"""
import logging
from typing import Optional, List, Dict
from datetime import datetime, timedelta

from sqlalchemy import select, func, text, and_, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from database.engine import get_session
from database.models import Trade
from .models import EVGroupKey, EVGroupStats, GroupLevel
import config

logger = logging.getLogger(__name__)


class RealEVCalculator:
    """Расчёт Real EV статистики из БД."""

    def __init__(self):
        self.lookback_days = getattr(config, 'EV_LOOKBACK_DAYS', 90)
        self.rolling_n = getattr(config, 'EV_ROLLING_LAST_N', 10)

    async def calculate_stats(
        self,
        archetype: str,
        timeframe: Optional[str] = None,
        market_regime: Optional[str] = None,
    ) -> Optional[EVGroupStats]:
        """
        Рассчитать статистику для конкретной группы.

        Args:
            archetype: Архетип сценария (обязательный)
            timeframe: Таймфрейм (для L2, L3)
            market_regime: Режим рынка (для L3)
        """
        group_key = EVGroupKey(archetype, timeframe, market_regime)
        cutoff_date = datetime.utcnow() - timedelta(days=self.lookback_days)

        async for session in get_session():
            try:
                # Build base conditions
                conditions = [
                    Trade.status == 'closed',
                    Trade.r_result.isnot(None),
                    Trade.closed_at >= cutoff_date,
                    Trade.scenario_archetype == archetype,
                ]

                if timeframe:
                    conditions.append(Trade.timeframe == timeframe)
                if market_regime:
                    conditions.append(Trade.market_regime == market_regime)

                # Main aggregation query
                query = select(
                    func.count(Trade.id).label('sample_size'),
                    func.avg(Trade.r_result).label('real_ev'),
                    func.avg(Trade.scenario_ev_r).label('paper_ev_avg'),
                    func.sum(func.cast(Trade.outcome == 'win', Integer)).label('win_count'),
                ).where(and_(*conditions))

                result = await session.execute(query)
                row = result.one()

                sample_size = row.sample_size or 0
                if sample_size == 0:
                    return None

                real_ev = float(row.real_ev) if row.real_ev else 0.0
                paper_ev_avg = float(row.paper_ev_avg) if row.paper_ev_avg else None
                win_count = row.win_count or 0
                winrate = (win_count / sample_size) if sample_size > 0 else 0.0

                # Calculate rolling EV
                rolling_ev, rolling_n = await self._calculate_rolling_ev(
                    session, conditions
                )

                # Calculate EV gap
                ev_gap = None
                if paper_ev_avg is not None:
                    ev_gap = paper_ev_avg - real_ev

                return EVGroupStats(
                    level=group_key.level.value,
                    group_key=group_key.to_group_key_str(),
                    sample_size=sample_size,
                    paper_ev_avg=paper_ev_avg,
                    real_ev=real_ev,
                    ev_gap=ev_gap,
                    winrate=winrate,
                    rolling_ev=rolling_ev,
                    rolling_n=rolling_n,
                    last_updated=datetime.utcnow(),
                )

            except Exception as e:
                logger.error(f"Error calculating stats for {group_key.to_group_key_str()}: {e}")
                return None

    async def _calculate_rolling_ev(
        self,
        session: AsyncSession,
        base_conditions: list,
    ) -> tuple[Optional[float], int]:
        """Рассчитать rolling EV по последним N сделкам."""
        try:
            # Subquery for last N trades
            subquery = (
                select(Trade.r_result)
                .where(and_(*base_conditions))
                .order_by(Trade.closed_at.desc())
                .limit(self.rolling_n)
            ).subquery()

            # Aggregate
            query = select(
                func.avg(subquery.c.r_result).label('rolling_ev'),
                func.count(subquery.c.r_result).label('rolling_n'),
            )

            result = await session.execute(query)
            row = result.one()

            rolling_ev = float(row.rolling_ev) if row.rolling_ev else None
            rolling_n = row.rolling_n or 0

            return rolling_ev, rolling_n

        except Exception as e:
            logger.error(f"Error calculating rolling EV: {e}")
            return None, 0

    async def calculate_all_l1_stats(self) -> List[EVGroupStats]:
        """Рассчитать L1 статистику для всех архетипов."""
        cutoff_date = datetime.utcnow() - timedelta(days=self.lookback_days)

        async for session in get_session():
            try:
                # Get all archetypes
                query = (
                    select(Trade.scenario_archetype)
                    .where(
                        Trade.status == 'closed',
                        Trade.r_result.isnot(None),
                        Trade.closed_at >= cutoff_date,
                        Trade.scenario_archetype.isnot(None),
                    )
                    .group_by(Trade.scenario_archetype)
                )

                result = await session.execute(query)
                archetypes = [row[0] for row in result.all()]

                stats_list = []
                for arch in archetypes:
                    stats = await self.calculate_stats(archetype=arch)
                    if stats:
                        stats_list.append(stats)

                return stats_list

            except Exception as e:
                logger.error(f"Error calculating all L1 stats: {e}")
                return []

    async def calculate_stats_for_scenario(
        self,
        archetype: str,
        timeframe: str,
        market_regime: Optional[str] = None,
    ) -> Dict[str, Optional[EVGroupStats]]:
        """
        Рассчитать статистику для всех уровней (L3, L2, L1).
        Используется для gate check с fallback.

        Returns:
            Dict с ключами 'L3', 'L2', 'L1' и соответствующими stats или None.
        """
        result = {'L3': None, 'L2': None, 'L1': None}

        # L1: только archetype
        result['L1'] = await self.calculate_stats(archetype=archetype)

        # L2: archetype + timeframe
        if timeframe:
            result['L2'] = await self.calculate_stats(
                archetype=archetype,
                timeframe=timeframe,
            )

        # L3: archetype + timeframe + regime
        if timeframe and market_regime:
            result['L3'] = await self.calculate_stats(
                archetype=archetype,
                timeframe=timeframe,
                market_regime=market_regime,
            )

        return result
