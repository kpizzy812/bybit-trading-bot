"""
SQLAlchemy Models for Futures Bot

Tables:
- scenarios: AI scenarios from Syntra with full metadata
- trades: Trading history linked to scenarios
- no_trade_signals: History of "don't trade" signals
- market_contexts: Market state at analysis time
"""
import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Text,
    ForeignKey, Index, JSON
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID


class Base(DeclarativeBase):
    """Base class for all models"""
    pass


class MarketContext(Base):
    """
    Market context snapshot at analysis time.
    Stored separately for historical analysis.
    """
    __tablename__ = "market_contexts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Market state
    current_price: Mapped[float] = mapped_column(Float)
    trend: Mapped[str] = mapped_column(String(20))  # bullish, bearish, neutral
    phase: Mapped[str] = mapped_column(String(30))  # accumulation, distribution, etc
    sentiment: Mapped[str] = mapped_column(String(20))  # greed, fear, neutral
    volatility: Mapped[str] = mapped_column(String(20))  # low, medium, high
    bias: Mapped[str] = mapped_column(String(10))  # long, short, neutral
    strength: Mapped[float] = mapped_column(Float)  # 0-1

    # Indicators
    rsi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    funding_rate_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    long_short_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Key levels (JSON)
    key_levels: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Data quality
    data_quality_pct: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    scenarios: Mapped[List["Scenario"]] = relationship(back_populates="market_context")
    no_trade_signal: Mapped[Optional["NoTradeSignal"]] = relationship(back_populates="market_context")

    __table_args__ = (
        Index('ix_market_contexts_symbol_created', 'symbol', 'created_at'),
    )


class NoTradeSignal(Base):
    """
    No-trade signal history.
    When AI recommends NOT to trade.
    """
    __tablename__ = "no_trade_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[str] = mapped_column(String(64), ForeignKey("market_contexts.analysis_id"), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # No-trade data
    should_not_trade: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(50))  # chop, extreme_sentiment, etc
    reasons: Mapped[List[str]] = mapped_column(JSON)  # List of reasons
    wait_for: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    estimated_wait_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationship
    market_context: Mapped["MarketContext"] = relationship(back_populates="no_trade_signal")

    __table_args__ = (
        Index('ix_no_trade_symbol_created', 'symbol', 'created_at'),
    )


class Scenario(Base):
    """
    AI Trading Scenario from Syntra.
    Full metadata for analytics.
    """
    __tablename__ = "scenarios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[str] = mapped_column(String(64), ForeignKey("market_contexts.analysis_id"), index=True)
    scenario_idx: Mapped[int] = mapped_column(Integer)  # Position in response (0, 1, 2)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Basic info
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(100))
    bias: Mapped[str] = mapped_column(String(10))  # long, short

    # Confidence
    confidence: Mapped[float] = mapped_column(Float)  # Calibrated
    confidence_raw: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Original

    # Archetype
    primary_archetype: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Entry (legacy zone)
    entry_price_min: Mapped[float] = mapped_column(Float)
    entry_price_max: Mapped[float] = mapped_column(Float)
    entry_type: Mapped[str] = mapped_column(String(30))

    # Entry Plan (JSON - full ladder)
    entry_plan: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Stop Loss
    stop_loss_conservative: Mapped[float] = mapped_column(Float)
    stop_loss_aggressive: Mapped[float] = mapped_column(Float)
    stop_loss_recommended: Mapped[float] = mapped_column(Float)
    stop_loss_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stop_pct_of_entry: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atr_multiple_stop: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Targets (JSON - array of targets)
    targets: Mapped[List[dict]] = mapped_column(JSON)

    # Leverage
    leverage_recommended: Mapped[str] = mapped_column(String(20))
    leverage_max_safe: Mapped[str] = mapped_column(String(20))
    leverage_volatility_adjusted: Mapped[bool] = mapped_column(Boolean, default=False)
    atr_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Invalidation
    invalidation_price: Mapped[float] = mapped_column(Float)
    invalidation_condition: Mapped[str] = mapped_column(String(200))

    # Why (JSON)
    why_bullish: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    why_bearish: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    why_risks: Mapped[List[str]] = mapped_column(JSON)

    # Conditions
    conditions: Mapped[List[str]] = mapped_column(JSON)
    no_trade_conditions: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Validity
    time_valid_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entry_trigger: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    validation_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # === EV METRICS ===
    ev_r: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ev_r_gross: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ev_fees_r: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ev_grade: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # A, B, C, D
    scenario_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # === OUTCOME PROBS ===
    prob_sl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prob_tp1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prob_tp2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prob_tp3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prob_other: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    probs_source: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # learning, llm, default
    probs_sample_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # === CLASS STATS ===
    class_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    class_level: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # L1, L2
    class_sample_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    class_winrate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    class_avg_pnl_r: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    class_avg_ev_r: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    class_is_enabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    class_warning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # === LEARNING SUGGESTIONS ===
    learning_sl_atr_mult: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    learning_tp1_r: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    learning_tp2_r: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    learning_based_on_trades: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    learning_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Full snapshot (JSON backup)
    raw_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationship
    market_context: Mapped["MarketContext"] = relationship(back_populates="scenarios")
    trades: Mapped[List["Trade"]] = relationship(back_populates="scenario")

    __table_args__ = (
        Index('ix_scenarios_symbol_created', 'symbol', 'created_at'),
        Index('ix_scenarios_archetype', 'primary_archetype'),
        Index('ix_scenarios_ev_grade', 'ev_grade'),
    )


class Trade(Base):
    """
    Trade record linked to scenario.
    Full persistence of TradeRecord from Redis.
    """
    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trade_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # From TradeRecord
    scenario_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # Actual open time
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Basic
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))  # Long, Short
    timeframe: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Entry
    entry_price: Mapped[float] = mapped_column(Float)
    qty: Mapped[float] = mapped_column(Float)
    leverage: Mapped[int] = mapped_column(Integer)
    margin_mode: Mapped[str] = mapped_column(String(20), default="Isolated")  # Isolated, Cross
    margin_usd: Mapped[float] = mapped_column(Float)
    entry_mode: Mapped[str] = mapped_column(String(20), default="single")  # ladder, single, dca

    # Risk / Planned
    stop_price: Mapped[float] = mapped_column(Float)
    risk_usd: Mapped[float] = mapped_column(Float)
    tp_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rr_planned: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Result
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # For partial closes
    pnl_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    roe_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rr_actual: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # win, loss, breakeven
    exit_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # Fills (partial closes) - JSON array
    fills: Mapped[Optional[List[dict]]] = mapped_column(JSON, nullable=True)
    closed_qty: Mapped[float] = mapped_column(Float, default=0.0)
    remaining_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Fees (detailed)
    entry_fee_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_fees_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    funding_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_fees_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # MAE/MFE (via price tracking)
    min_price_seen: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_price_seen: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mae_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mae_r: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mfe_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mfe_r: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # === REAL EV TRACKING ===
    r_result: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # NET PnL в R
    market_regime: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # "{trend}_{phase}"

    # Status
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, partial, closed
    testnet: Mapped[bool] = mapped_column(Boolean, default=False)

    # === SCENARIO SOURCE ===
    scenario_source: Mapped[str] = mapped_column(String(20), default="manual")  # syntra, manual, signal
    entry_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    validation_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    analysis_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # Denormalized for queries

    # === SCENARIO METADATA (denormalized for fast queries) ===
    scenario_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scenario_bias: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # long, short
    scenario_archetype: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    scenario_ev_r: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scenario_ev_grade: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    scenario_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scenario_class_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    scenario_class_winrate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scenario_class_warning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # === OUTCOME PROBS (denormalized) ===
    prob_sl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prob_tp1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    probs_source: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # === FULL SCENARIO SNAPSHOT (JSON backup) ===
    scenario_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationship
    scenario: Mapped[Optional["Scenario"]] = relationship(back_populates="trades")

    __table_args__ = (
        Index('ix_trades_user_created', 'user_id', 'created_at'),
        Index('ix_trades_symbol_outcome', 'symbol', 'outcome'),
        Index('ix_trades_archetype_outcome', 'scenario_archetype', 'outcome'),
        Index('ix_trades_analysis_id', 'analysis_id'),
        # Real EV aggregation indexes
        Index('ix_trades_status_closed_at', 'status', 'closed_at'),
        Index('ix_trades_archetype_tf_closed', 'scenario_archetype', 'timeframe', 'closed_at'),
        Index('ix_trades_regime_closed', 'market_regime', 'closed_at'),
    )


class UserSettingsDB(Base):
    """
    User settings persisted in PostgreSQL.
    Redis serves as cache, PG as source of truth.
    """
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Telegram user ID
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Trading Capital Settings
    trading_capital_mode: Mapped[str] = mapped_column(String(20), default="manual")  # manual, auto
    trading_capital_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Trading defaults
    default_risk_usd: Mapped[float] = mapped_column(Float, default=5.0)
    default_leverage: Mapped[int] = mapped_column(Integer, default=10)
    default_margin_mode: Mapped[str] = mapped_column(String(20), default="Isolated")  # Isolated, Cross
    default_tp_mode: Mapped[str] = mapped_column(String(20), default="rr")  # single, ladder, rr
    default_tp_rr: Mapped[float] = mapped_column(Float, default=2.0)

    # Feature toggles
    shorts_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    confirm_always: Mapped[bool] = mapped_column(Boolean, default=True)

    # Safety limits
    max_risk_per_trade: Mapped[float] = mapped_column(Float, default=50.0)
    max_margin_per_trade: Mapped[float] = mapped_column(Float, default=500.0)
    max_notional_per_trade: Mapped[float] = mapped_column(Float, default=10000.0)

    # Mode
    testnet_mode: Mapped[bool] = mapped_column(Boolean, default=False)

    # Risk Management
    auto_breakeven_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_active_positions: Mapped[int] = mapped_column(Integer, default=5)
    confidence_risk_scaling: Mapped[bool] = mapped_column(Boolean, default=True)


# =============================================================================
# REAL EV TRACKING MODELS
# =============================================================================

class EVGroupState(Base):
    """
    Персистентное состояние группы для auto/manual disable.
    Хранит текущий статус группировки сценариев по Real EV.
    """
    __tablename__ = "ev_group_state"

    group_key: Mapped[str] = mapped_column(String(200), primary_key=True)  # pullback_to_ema50:4h:bullish_accumulation
    level: Mapped[str] = mapped_column(String(10))  # L1, L2, L3

    # Disable state
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # для временных банов
    disable_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # auto_disabled, manual_disabled

    # Last evaluation
    last_eval_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_real_ev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_rolling_ev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_sample_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_winrate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Manual override
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False)
    override_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # user_id
    override_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EVGateLog(Base):
    """
    Лог всех gate решений для аудита.
    Записывается каждый раз когда проверяется возможность торговли.
    """
    __tablename__ = "ev_gate_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)

    # Контекст запроса
    archetype: Mapped[str] = mapped_column(String(50))
    timeframe: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    market_regime: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20))

    # Результат проверки
    status: Mapped[str] = mapped_column(String(20))  # NO_DATA, WARN, SOFT_BLOCK, BLOCK, OVERRIDE
    selected_level: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # L1, L2, L3
    selected_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    real_ev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rolling_ev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sample_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Действие пользователя
    user_action: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # proceeded, skipped, force_override

    __table_args__ = (
        Index('ix_ev_gate_log_user_created', 'user_id', 'created_at'),
        Index('ix_ev_gate_log_status', 'status'),
    )
