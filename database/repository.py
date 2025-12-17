"""
Repository for database operations.
Provides high-level methods for storing and querying data.
"""
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from database.models import Scenario, Trade, NoTradeSignal, MarketContext
from database.engine import AsyncSessionLocal
import config


class ScenarioRepository:
    """
    Repository for scenario-related database operations.
    """

    @staticmethod
    async def save_analysis_response(
        analysis_id: str,
        symbol: str,
        timeframe: str,
        current_price: float,
        market_context: Dict[str, Any],
        scenarios: List[Dict[str, Any]],
        no_trade: Optional[Dict[str, Any]] = None,
        key_levels: Optional[Dict[str, Any]] = None,
        data_quality: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Save full API response to database.

        Args:
            analysis_id: Unique analysis ID from API
            symbol: Trading symbol
            timeframe: Timeframe
            current_price: Current price at analysis time
            market_context: Market context dict
            scenarios: List of scenario dicts
            no_trade: Optional no-trade signal
            key_levels: Optional key levels
            data_quality: Optional data quality info
        """
        if not config.POSTGRES_ENABLED or AsyncSessionLocal is None:
            return

        try:
            async with AsyncSessionLocal() as session:
                # 1. Save MarketContext
                mc = MarketContext(
                    analysis_id=analysis_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    current_price=current_price,
                    trend=market_context.get("trend", "neutral"),
                    phase=market_context.get("phase", "unknown"),
                    sentiment=market_context.get("sentiment", "neutral"),
                    volatility=market_context.get("volatility", "medium"),
                    bias=market_context.get("bias", "neutral"),
                    strength=market_context.get("strength", 0.5),
                    rsi=market_context.get("rsi"),
                    funding_rate_pct=market_context.get("funding_rate_pct"),
                    long_short_ratio=market_context.get("long_short_ratio"),
                    key_levels=key_levels,
                    data_quality_pct=data_quality.get("completeness", 0) if data_quality else 0,
                )
                session.add(mc)

                # 2. Save NoTradeSignal if present
                if no_trade and no_trade.get("should_not_trade"):
                    nts = NoTradeSignal(
                        analysis_id=analysis_id,
                        symbol=symbol,
                        timeframe=timeframe,
                        should_not_trade=True,
                        confidence=no_trade.get("confidence", 0),
                        category=no_trade.get("category", "unknown"),
                        reasons=no_trade.get("reasons", []),
                        wait_for=no_trade.get("wait_for"),
                        estimated_wait_hours=no_trade.get("estimated_wait_hours"),
                    )
                    session.add(nts)

                # 3. Save Scenarios
                for idx, sc in enumerate(scenarios):
                    entry = sc.get("entry", {})
                    stop_loss = sc.get("stop_loss", {})
                    leverage = sc.get("leverage", {})
                    invalidation = sc.get("invalidation", {})
                    why = sc.get("why", {})
                    ev_metrics = sc.get("ev_metrics", {})
                    outcome_probs = sc.get("outcome_probs", {})
                    class_stats = sc.get("class_stats", {})
                    learning = sc.get("learning_suggestions", {})

                    scenario = Scenario(
                        analysis_id=analysis_id,
                        scenario_idx=idx,
                        symbol=symbol,
                        timeframe=timeframe,
                        name=sc.get("name", f"Scenario {idx + 1}"),
                        bias=sc.get("bias", "neutral"),
                        confidence=sc.get("confidence", 0),
                        confidence_raw=sc.get("confidence_raw"),
                        primary_archetype=sc.get("primary_archetype"),
                        # Entry
                        entry_price_min=entry.get("price_min", 0),
                        entry_price_max=entry.get("price_max", 0),
                        entry_type=entry.get("type", "market"),
                        entry_plan=sc.get("entry_plan"),
                        # Stop Loss
                        stop_loss_conservative=stop_loss.get("conservative", 0),
                        stop_loss_aggressive=stop_loss.get("aggressive", 0),
                        stop_loss_recommended=stop_loss.get("recommended", 0),
                        stop_loss_reason=stop_loss.get("reason"),
                        stop_pct_of_entry=sc.get("stop_pct_of_entry"),
                        atr_multiple_stop=sc.get("atr_multiple_stop"),
                        # Targets
                        targets=sc.get("targets", []),
                        # Leverage
                        leverage_recommended=leverage.get("recommended", "5x") if isinstance(leverage, dict) else str(leverage),
                        leverage_max_safe=leverage.get("max_safe", "10x") if isinstance(leverage, dict) else str(leverage),
                        leverage_volatility_adjusted=leverage.get("volatility_adjusted", False) if isinstance(leverage, dict) else False,
                        atr_pct=leverage.get("atr_pct") if isinstance(leverage, dict) else None,
                        # Invalidation
                        invalidation_price=invalidation.get("price", 0),
                        invalidation_condition=invalidation.get("condition", ""),
                        # Why
                        why_bullish=why.get("bullish_factors"),
                        why_bearish=why.get("bearish_factors"),
                        why_risks=why.get("risks", []),
                        # Conditions
                        conditions=sc.get("conditions", []),
                        no_trade_conditions=sc.get("no_trade_conditions"),
                        time_valid_hours=sc.get("time_valid_hours"),
                        entry_trigger=sc.get("entry_trigger"),
                        validation_status=sc.get("validation_status"),
                        # EV Metrics
                        ev_r=ev_metrics.get("ev_r"),
                        ev_r_gross=ev_metrics.get("ev_r_gross"),
                        ev_fees_r=ev_metrics.get("fees_r"),
                        ev_grade=ev_metrics.get("ev_grade"),
                        scenario_score=ev_metrics.get("scenario_score"),
                        # Outcome Probs
                        prob_sl=outcome_probs.get("sl"),
                        prob_tp1=outcome_probs.get("tp1"),
                        prob_tp2=outcome_probs.get("tp2"),
                        prob_tp3=outcome_probs.get("tp3"),
                        prob_other=outcome_probs.get("other"),
                        probs_source=outcome_probs.get("source"),
                        probs_sample_size=outcome_probs.get("sample_size"),
                        # Class Stats
                        class_key=class_stats.get("class_key"),
                        class_level=class_stats.get("class_level"),
                        class_sample_size=class_stats.get("sample_size"),
                        class_winrate=class_stats.get("winrate"),
                        class_avg_pnl_r=class_stats.get("avg_pnl_r"),
                        class_avg_ev_r=class_stats.get("avg_ev_r"),
                        class_is_enabled=class_stats.get("is_enabled"),
                        class_warning=sc.get("class_warning"),
                        # Learning
                        learning_sl_atr_mult=learning.get("sl_atr_mult") if learning else None,
                        learning_tp1_r=learning.get("tp1_r") if learning else None,
                        learning_tp2_r=learning.get("tp2_r") if learning else None,
                        learning_based_on_trades=learning.get("based_on_trades") if learning else None,
                        learning_confidence=learning.get("confidence") if learning else None,
                        # Raw snapshot
                        raw_snapshot=sc,
                    )
                    session.add(scenario)

                await session.commit()
                logger.debug(f"Saved analysis {analysis_id}: {len(scenarios)} scenarios")

        except Exception as e:
            logger.error(f"Failed to save analysis to DB: {e}")

    @staticmethod
    async def save_trade(
        trade_id: str,
        user_id: int,
        symbol: str,
        side: str,
        entry_price: float,
        qty: float,
        leverage: int,
        margin_usd: float,
        stop_price: float,
        risk_usd: float,
        scenario_data: Optional[Dict[str, Any]] = None,
        analysis_id: Optional[str] = None,
        timeframe: Optional[str] = None,
        entry_mode: str = "single",
        testnet: bool = False,
    ) -> None:
        """
        Save trade to database with scenario metadata.
        """
        if not config.POSTGRES_ENABLED or AsyncSessionLocal is None:
            return

        try:
            async with AsyncSessionLocal() as session:
                # Find scenario if analysis_id provided
                scenario_db_id = None
                if analysis_id and scenario_data:
                    # Find by analysis_id and scenario index (or name)
                    scenario_idx = scenario_data.get("id", 0) - 1  # API uses 1-indexed
                    result = await session.execute(
                        select(Scenario).where(
                            and_(
                                Scenario.analysis_id == analysis_id,
                                Scenario.scenario_idx == scenario_idx
                            )
                        )
                    )
                    scenario_row = result.scalar_one_or_none()
                    if scenario_row:
                        scenario_db_id = scenario_row.id

                # Extract scenario metadata
                ev_metrics = scenario_data.get("ev_metrics", {}) if scenario_data else {}
                class_stats = scenario_data.get("class_stats", {}) if scenario_data else {}

                trade = Trade(
                    trade_id=trade_id,
                    scenario_id=scenario_db_id,
                    user_id=user_id,
                    symbol=symbol,
                    side=side,
                    timeframe=timeframe,
                    entry_price=entry_price,
                    qty=qty,
                    leverage=leverage,
                    margin_usd=margin_usd,
                    entry_mode=entry_mode,
                    stop_price=stop_price,
                    risk_usd=risk_usd,
                    testnet=testnet,
                    # Scenario metadata (denormalized)
                    scenario_confidence=scenario_data.get("confidence") if scenario_data else None,
                    scenario_archetype=scenario_data.get("primary_archetype") if scenario_data else None,
                    scenario_ev_r=ev_metrics.get("ev_r"),
                    scenario_ev_grade=ev_metrics.get("ev_grade"),
                    scenario_class_key=class_stats.get("class_key"),
                )
                session.add(trade)
                await session.commit()
                logger.debug(f"Saved trade {trade_id} to DB")

        except Exception as e:
            logger.error(f"Failed to save trade to DB: {e}")

    @staticmethod
    async def update_trade_result(
        trade_id: str,
        exit_price: float,
        pnl_usd: float,
        pnl_percent: float,
        roe_percent: Optional[float],
        rr_actual: Optional[float],
        outcome: str,
        exit_reason: str,
        total_fees_usd: Optional[float] = None,
        mae_r: Optional[float] = None,
        mfe_r: Optional[float] = None,
    ) -> None:
        """
        Update trade with exit results.
        """
        if not config.POSTGRES_ENABLED or AsyncSessionLocal is None:
            return

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Trade).where(Trade.trade_id == trade_id)
                )
                trade = result.scalar_one_or_none()

                if trade:
                    trade.exit_price = exit_price
                    trade.pnl_usd = pnl_usd
                    trade.pnl_percent = pnl_percent
                    trade.roe_percent = roe_percent
                    trade.rr_actual = rr_actual
                    trade.outcome = outcome
                    trade.exit_reason = exit_reason
                    trade.total_fees_usd = total_fees_usd
                    trade.mae_r = mae_r
                    trade.mfe_r = mfe_r
                    trade.status = "closed"
                    trade.closed_at = datetime.utcnow()
                    await session.commit()
                    logger.debug(f"Updated trade {trade_id} result in DB")

        except Exception as e:
            logger.error(f"Failed to update trade in DB: {e}")

    @staticmethod
    async def get_archetype_stats(
        user_id: Optional[int] = None,
        symbol: Optional[str] = None,
        days: int = 90
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get performance statistics by archetype.

        Returns:
            Dict[archetype, {count, winrate, avg_pnl_r, avg_ev_r}]
        """
        if not config.POSTGRES_ENABLED or AsyncSessionLocal is None:
            return {}

        try:
            async with AsyncSessionLocal() as session:
                cutoff = datetime.utcnow() - timedelta(days=days)

                query = select(
                    Trade.scenario_archetype,
                    func.count(Trade.id).label("count"),
                    func.avg(Trade.pnl_usd).label("avg_pnl"),
                    func.avg(Trade.rr_actual).label("avg_rr"),
                ).where(
                    and_(
                        Trade.status == "closed",
                        Trade.created_at >= cutoff,
                        Trade.scenario_archetype.isnot(None),
                    )
                ).group_by(Trade.scenario_archetype)

                if user_id:
                    query = query.where(Trade.user_id == user_id)
                if symbol:
                    query = query.where(Trade.symbol == symbol)

                result = await session.execute(query)
                rows = result.all()

                stats = {}
                for row in rows:
                    archetype = row.scenario_archetype
                    # Calculate winrate
                    wins_query = select(func.count(Trade.id)).where(
                        and_(
                            Trade.scenario_archetype == archetype,
                            Trade.outcome == "win",
                            Trade.status == "closed",
                            Trade.created_at >= cutoff,
                        )
                    )
                    if user_id:
                        wins_query = wins_query.where(Trade.user_id == user_id)

                    wins_result = await session.execute(wins_query)
                    wins = wins_result.scalar() or 0

                    stats[archetype] = {
                        "count": row.count,
                        "winrate": (wins / row.count * 100) if row.count > 0 else 0,
                        "avg_pnl": row.avg_pnl or 0,
                        "avg_rr": row.avg_rr or 0,
                    }

                return stats

        except Exception as e:
            logger.error(f"Failed to get archetype stats: {e}")
            return {}

    @staticmethod
    async def get_ev_grade_stats(
        user_id: Optional[int] = None,
        days: int = 90
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get performance by EV grade (A, B, C, D).
        Validates if predicted EV correlates with actual results.
        """
        if not config.POSTGRES_ENABLED or AsyncSessionLocal is None:
            return {}

        try:
            async with AsyncSessionLocal() as session:
                cutoff = datetime.utcnow() - timedelta(days=days)

                query = select(
                    Trade.scenario_ev_grade,
                    func.count(Trade.id).label("count"),
                    func.avg(Trade.pnl_usd).label("avg_pnl"),
                    func.avg(Trade.rr_actual).label("avg_rr"),
                    func.avg(Trade.scenario_ev_r).label("predicted_ev"),
                ).where(
                    and_(
                        Trade.status == "closed",
                        Trade.created_at >= cutoff,
                        Trade.scenario_ev_grade.isnot(None),
                    )
                ).group_by(Trade.scenario_ev_grade)

                if user_id:
                    query = query.where(Trade.user_id == user_id)

                result = await session.execute(query)
                rows = result.all()

                stats = {}
                for row in rows:
                    grade = row.scenario_ev_grade
                    stats[grade] = {
                        "count": row.count,
                        "avg_pnl": row.avg_pnl or 0,
                        "avg_rr": row.avg_rr or 0,
                        "predicted_ev": row.predicted_ev or 0,
                    }

                return stats

        except Exception as e:
            logger.error(f"Failed to get EV grade stats: {e}")
            return {}


from datetime import timedelta
