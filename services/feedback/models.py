"""
Feedback Loop Data Models

Pydantic модели для 4 слоёв телеметрии:
- A) Scenario Snapshot (ссылка, хранится в scenario_snapshot)
- B) Execution Report
- C) Outcome Report
- D) Attribution

Все модели используют 4 ключа склейки:
- analysis_id: UUID от Syntra
- scenario_local_id: int (1..N в рамках analysis)
- trade_id: UUID от бота
- scenario_hash: sha256 от snapshot JSON
"""
import hashlib
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# ENUMS
# =============================================================================

class ExitReason(str, Enum):
    """Причина закрытия позиции"""
    TP1 = "tp1"
    TP2 = "tp2"
    TP3 = "tp3"
    SL = "sl"
    MANUAL = "manual"
    TIMEOUT = "timeout"
    CANCEL = "cancel"
    LIQUIDATION = "liquidation"
    BREAKEVEN = "breakeven"


class TerminalOutcome(str, Enum):
    """
    Terminal outcome = MAX TP HIT за время сделки.

    НЕ путать с exit_reason! Если взяли 30% на TP1, а остаток
    выбило по SL — exit_reason="sl", но terminal_outcome="tp1".
    """
    SL = "sl"        # Не дошли ни до одного TP
    TP1 = "tp1"      # Дошли до TP1, но не до TP2
    TP2 = "tp2"      # Дошли до TP2, но не до TP3
    TP3 = "tp3"      # Дошли до TP3
    OTHER = "other"  # manual/timeout/breakeven ДО любого TP


class TradeLabel(str, Enum):
    """Результат сделки"""
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    TIMEOUT = "timeout"


class VolatilityRegime(str, Enum):
    """Режим волатильности"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


# =============================================================================
# LAYER B: EXECUTION REPORT
# =============================================================================

class OrderFill(BaseModel):
    """Информация о заполнении ордера"""
    order_id: str
    order_type: str                    # "limit" | "market"
    side: str                          # "Buy" | "Sell"
    price: float
    qty: float
    fee_usd: float
    timestamp: str                     # ISO format
    is_entry: bool
    tag: Optional[str] = None          # "E1_ema20", "TP1", "SL"


class ExecutionReport(BaseModel):
    """
    Layer B: Execution Report

    Что реально произошло при исполнении сделки:
    - Проскальзывание
    - Частичные филлы
    - Ручные вмешательства
    """
    # Planned
    planned_entry_price: float
    planned_entry_qty: float
    planned_orders_count: int = 1

    # Actual
    actual_avg_entry: float
    actual_total_qty: float
    filled_orders_count: int

    # Slippage
    slippage_pct: float = 0.0          # (actual - planned) / planned * 100
    slippage_usd: float = 0.0

    # Fills
    entry_fills: List[OrderFill] = Field(default_factory=list)
    exit_fills: List[OrderFill] = Field(default_factory=list)

    # Manual interventions
    manual_interventions: List[Dict[str, Any]] = Field(default_factory=list)
    # e.g., [{"action": "move_sl", "old": 100, "new": 105, "timestamp": "..."}]

    # Timing
    entry_start_ts: str                # ISO format
    entry_complete_ts: Optional[str] = None
    time_to_first_fill_sec: Optional[float] = None
    execution_duration_sec: float = 0.0

    @classmethod
    def calculate_slippage(
        cls,
        planned_price: float,
        actual_price: float,
        qty: float,
        side: str
    ) -> tuple[float, float]:
        """Рассчитать проскальзывание"""
        if planned_price == 0:
            return 0.0, 0.0

        diff = actual_price - planned_price
        # Для лонга: если actual > planned = negative slippage
        # Для шорта: если actual < planned = negative slippage
        if side.lower() == "short":
            diff = -diff

        slippage_pct = (diff / planned_price) * 100
        slippage_usd = diff * qty

        return slippage_pct, slippage_usd


# =============================================================================
# LAYER C: OUTCOME REPORT
# =============================================================================

class OutcomeReport(BaseModel):
    """
    Layer C: Outcome Report

    Чем закончилась сделка:
    - PnL в USD и R
    - MAE/MFE
    - Время в сделке
    - Эффективность захвата прибыли
    """
    # Exit info
    exit_reason: ExitReason
    exit_price: float
    exit_timestamp: str                # ISO format

    # PnL metrics
    pnl_usd: float
    pnl_r: float                       # PnL / risk
    roe_pct: float                     # PnL / margin * 100

    # MAE/MFE (Maximum Adverse/Favorable Excursion)
    mae_r: float                       # Max drawdown in R
    mfe_r: float                       # Max profit in R
    mae_usd: float = 0.0
    mfe_usd: float = 0.0

    # Efficiency
    capture_efficiency: float = 0.0    # pnl / mfe (how much of max profit captured)

    # Time metrics
    time_in_trade_min: int
    time_to_mfe_min: Optional[int] = None    # Когда достигли макс profit
    time_to_mae_min: Optional[int] = None    # Когда достигли макс drawdown

    # Post-SL analysis (если был SL)
    post_sl_mfe_r: Optional[float] = None    # MFE после SL
    post_sl_was_correct: Optional[bool] = None

    # Label
    label: TradeLabel

    @field_validator('capture_efficiency', mode='before')
    @classmethod
    def calculate_capture(cls, v, info):
        """Рассчитать эффективность захвата"""
        if v != 0:
            return v
        values = info.data
        mfe = values.get('mfe_r', 0)
        pnl = values.get('pnl_r', 0)
        if mfe > 0 and pnl > 0:
            return pnl / mfe
        return 0.0


# =============================================================================
# LAYER D: ATTRIBUTION
# =============================================================================

class ScenarioFactors(BaseModel):
    """Факторы из сценария для атрибуции"""
    trend: str                         # "up" | "down" | "sideways"
    bias: str                          # "bull" | "bear" | "neutral"
    fear_greed_index: Optional[int] = None
    funding_rate: Optional[float] = None
    long_short_ratio: Optional[float] = None
    adx: Optional[float] = None
    rsi: Optional[float] = None
    volatility_regime: Optional[VolatilityRegime] = None
    atr_pct: Optional[float] = None
    support_levels: Optional[List[float]] = None
    resistance_levels: Optional[List[float]] = None
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None


class Attribution(BaseModel):
    """
    Layer D: Attribution

    Почему сделка закончилась так, как закончилась.
    Rule-based архетипы и факторы.
    """
    # Archetype (rule-based, НЕ LLM!)
    primary_archetype: str             # e.g., "pullback_to_ema50"
    archetype_confidence: float = 0.5  # 0-1, насколько уверены в классификации
    tags: List[str] = Field(default_factory=list)
    # e.g., ["ema50_touch", "bullish_trend", "low_funding"]

    # Factors
    factors: ScenarioFactors

    # Outcome
    label: TradeLabel
    pnl_r: float

    # Terminal Outcome (для EV расчёта)
    terminal_outcome: Optional[str] = None  # "sl" | "tp1" | "tp2" | "tp3" | "other"
    terminal_outcome_flags: List[str] = Field(default_factory=list)
    # e.g., ["tp_touch_by_wick", "reduced_targets"]
    max_tp_reached: int = 0  # 0, 1, 2, или 3

    # Factor contributions (rule-based analysis)
    factor_contributions: Dict[str, float] = Field(default_factory=dict)
    # e.g., {"trend_alignment": 0.3, "sl_placement": -0.2, "timing": 0.1}

    # Notes
    analysis_notes: Optional[str] = None


# =============================================================================
# COMBINED FEEDBACK PAYLOAD
# =============================================================================

class TradeFeedback(BaseModel):
    """
    Полный payload для отправки feedback в Syntra API.

    Включает все 4 слоя телеметрии и 4 ключа склейки.
    Поддерживает partial updates (можно отправлять не все слои).
    """
    # === 4 КЛЮЧА СКЛЕЙКИ (обязательно) ===
    trade_id: str                      # UUID от бота
    analysis_id: str                   # UUID от Syntra
    scenario_local_id: int             # 1..N в рамках analysis
    scenario_hash: str                 # sha256 от snapshot JSON

    # === Idempotency ===
    idempotency_key: str               # "{trade_id}:{event_type}"

    # === Context ===
    user_id: int
    symbol: str
    side: str                          # "Long" | "Short"
    timeframe: str                     # "1h", "4h", "1d"
    is_testnet: bool = False

    # === Confidence (из сценария) ===
    confidence_raw: float              # Оригинальный confidence от AI

    # === Partial data (можно отправлять по частям) ===
    execution: Optional[ExecutionReport] = None
    outcome: Optional[OutcomeReport] = None
    attribution: Optional[Attribution] = None

    # === Scenario snapshot (полный) ===
    scenario_snapshot: Optional[Dict[str, Any]] = None

    # === Meta ===
    bot_version: str = "2.0.0"
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    @staticmethod
    def compute_scenario_hash(scenario_snapshot: Dict[str, Any]) -> str:
        """
        Вычислить sha256 hash от scenario snapshot.
        Гарантирует что сценарий не был изменён.
        """
        # Сортируем ключи для детерминированности
        json_str = json.dumps(scenario_snapshot, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(json_str.encode()).hexdigest()

    @staticmethod
    def make_idempotency_key(trade_id: str, event_type: str) -> str:
        """
        Создать idempotency key для защиты от дублей.

        event_type: "execution" | "outcome" | "attribution" | "full"
        """
        return f"{trade_id}:{event_type}"


# =============================================================================
# HELPER: ARCHETYPE TAGS
# =============================================================================

# Стандартные теги для архетипов
ARCHETYPE_TAGS = {
    # Trend tags
    "bullish_trend": "Бычий тренд",
    "bearish_trend": "Медвежий тренд",
    "sideways": "Боковик",

    # EMA tags
    "ema20_touch": "Касание EMA20",
    "ema50_touch": "Касание EMA50",
    "ema200_touch": "Касание EMA200",
    "above_ema20": "Выше EMA20",
    "below_ema20": "Ниже EMA20",

    # RSI tags
    "rsi_oversold": "RSI перепродан (<30)",
    "rsi_overbought": "RSI перекуплен (>70)",
    "rsi_neutral": "RSI нейтральный",

    # Funding tags
    "high_funding": "Высокий funding (>0.03%)",
    "low_funding": "Низкий funding (<0.01%)",
    "negative_funding": "Отрицательный funding",

    # Volatility tags
    "high_volatility": "Высокая волатильность",
    "low_volatility": "Низкая волатильность",
    "volatility_expansion": "Расширение волатильности",
    "volatility_contraction": "Сжатие волатильности",

    # Structure tags
    "breakout": "Пробой",
    "retest": "Ретест",
    "range_support": "Поддержка рейнджа",
    "range_resistance": "Сопротивление рейнджа",

    # Liquidity tags
    "liq_sweep_above": "Ликвидации сверху",
    "liq_sweep_below": "Ликвидации снизу",
    "liq_cluster_nearby": "Кластер ликвидаций рядом",
}
