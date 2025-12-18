"""
Trading Modes - Models

Dataclass для конфигурации торговых режимов.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ModeConfig:
    """
    Конфигурация торгового режима.

    Определяет параметры риска, плеча, SL/TP, безопасности и supervisor
    для каждого режима торговли.
    """
    # Идентификация
    mode_id: str                      # "conservative", "standard", "high_risk", "meme"
    mode_family: str                  # "cautious", "balanced", "speculative"
    name: str                         # "Conservative Mode"
    description: str                  # Описание для UI
    emoji: str                        # Emoji для UI

    # Leverage
    max_leverage: int
    default_leverage: int

    # Risk scaling
    risk_multiplier_min: float        # Минимальный множитель риска
    risk_multiplier_max: float        # Максимальный множитель риска

    # Stop Loss (ATR-based)
    sl_atr_min: float                 # Минимальный SL в ATR
    sl_atr_max: float                 # Максимальный SL в ATR

    # Position sizing
    position_size_mult: float = 1.0   # 1.0 = normal, 0.5 = reduced for meme

    # Time constraints
    max_hold_hours: int = 168         # Max время удержания (7 дней default)

    # Trading behavior
    trust_levels: bool = True         # Доверять уровням S/R (False для meme)
    aggressive_entries: bool = False  # Market vs Limit preference

    # Symbol restrictions
    allowed_symbols: Optional[list] = None  # None = all, list = whitelist

    # EV Gates
    ev_disable_threshold: float = -0.15
    ev_min_trades: int = 20

    # Safety caps (защита от убийства депо)
    max_trades_per_day: int = 5
    max_consecutive_losses: int = 3
    daily_loss_cap_usd: float = 50.0
    cooldown_after_loss_min: int = 30

    # Supervisor thresholds
    liq_proximity_warn_pct: float = 10.0
    liq_proximity_critical_pct: float = 5.0
    invalidation_threat_pct: float = 2.0
    advice_expiration_min: int = 60
    default_cooldown_min: int = 30

    # Prompt context для LLM
    prompt_context: str = ""

    @property
    def risk_multiplier_range(self) -> tuple:
        """Диапазон множителя риска."""
        return (self.risk_multiplier_min, self.risk_multiplier_max)

    @property
    def sl_atr_range(self) -> tuple:
        """Диапазон SL в ATR."""
        return (self.sl_atr_min, self.sl_atr_max)


@dataclass
class SafetyCheckResult:
    """Результат проверки безопасности перед торговлей."""
    allowed: bool
    reason: Optional[str] = None
    cooldown_remaining_min: Optional[int] = None
    trades_today: int = 0
    losses_today: int = 0
    loss_today_usd: float = 0.0
    consecutive_losses: int = 0


@dataclass
class SymbolFilterResult:
    """Результат проверки символа для режима."""
    allowed: bool
    reason: Optional[str] = None
    warnings: list = field(default_factory=list)
    volume_24h_usd: Optional[float] = None
    spread_pct: Optional[float] = None
    atr_pct: Optional[float] = None
    funding_rate_pct: Optional[float] = None
