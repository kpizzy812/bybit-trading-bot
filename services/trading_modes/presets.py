"""
Trading Modes - Presets

Предустановленные режимы торговли: CONSERVATIVE, STANDARD, HIGH_RISK, MEME.
"""
from services.trading_modes.models import ModeConfig


# ============================================================
# CONSERVATIVE MODE
# ============================================================
CONSERVATIVE_MODE = ModeConfig(
    mode_id="conservative",
    mode_family="cautious",
    name="Conservative",
    description="Низкий риск, только сильные сетапы, узкие стопы",
    emoji="🛡️",

    # Leverage
    max_leverage=5,
    default_leverage=3,

    # Risk scaling (сниженный)
    risk_multiplier_min=0.5,
    risk_multiplier_max=1.0,

    # Stop Loss (узкий)
    sl_atr_min=0.5,
    sl_atr_max=1.0,

    # Position sizing
    position_size_mult=1.0,

    # Time
    max_hold_hours=72,

    # Behavior
    trust_levels=True,
    aggressive_entries=False,

    # Symbols
    allowed_symbols=None,  # Все символы

    # EV Gates (строже)
    ev_disable_threshold=-0.08,
    ev_min_trades=30,

    # Safety caps (строже)
    max_trades_per_day=3,
    max_consecutive_losses=2,
    daily_loss_cap_usd=30.0,
    cooldown_after_loss_min=60,

    # Supervisor (консервативнее)
    liq_proximity_warn_pct=15.0,
    liq_proximity_critical_pct=8.0,
    invalidation_threat_pct=1.5,
    advice_expiration_min=120,
    default_cooldown_min=60,

    # Prompt
    prompt_context="""CONSERVATIVE MODE:
- ONLY high-probability setups with strong confluence
- Require minimum 3 confirming factors
- Tight stops (0.5-1.0x ATR)
- Skip marginal setups - better to miss than lose
- Focus on major support/resistance levels only
- Avoid entries during high volatility / news events
- Prefer limit entries with clear invalidation"""
)


# ============================================================
# STANDARD MODE (default)
# ============================================================
STANDARD_MODE = ModeConfig(
    mode_id="standard",
    mode_family="balanced",
    name="Standard",
    description="Сбалансированный режим, умеренный риск",
    emoji="📊",

    # Leverage
    max_leverage=10,
    default_leverage=5,

    # Risk scaling
    risk_multiplier_min=0.7,
    risk_multiplier_max=1.3,

    # Stop Loss
    sl_atr_min=1.0,
    sl_atr_max=1.5,

    # Position sizing
    position_size_mult=1.0,

    # Time
    max_hold_hours=168,  # 7 дней

    # Behavior
    trust_levels=True,
    aggressive_entries=False,

    # Symbols
    allowed_symbols=None,

    # EV Gates
    ev_disable_threshold=-0.15,
    ev_min_trades=20,

    # Safety caps
    max_trades_per_day=5,
    max_consecutive_losses=3,
    daily_loss_cap_usd=50.0,
    cooldown_after_loss_min=30,

    # Supervisor
    liq_proximity_warn_pct=10.0,
    liq_proximity_critical_pct=5.0,
    invalidation_threat_pct=2.0,
    advice_expiration_min=60,
    default_cooldown_min=30,

    # Prompt
    prompt_context="""STANDARD MODE:
- Balanced risk/reward approach
- Use technical levels for entry/SL/TP
- Consider both trend and counter-trend setups
- Normal stop distance (1.0-1.5x ATR)
- Follow existing market structure"""
)


# ============================================================
# HIGH RISK MODE
# ============================================================
HIGH_RISK_MODE = ModeConfig(
    mode_id="high_risk",
    mode_family="speculative",
    name="High Risk",
    description="Высокий риск, тесные стопы, высокое плечо",
    emoji="🔥",

    # Leverage (высокое!)
    max_leverage=50,
    default_leverage=20,

    # Risk scaling (повышенный)
    risk_multiplier_min=1.0,
    risk_multiplier_max=2.0,

    # Stop Loss (ТЕСНЫЙ - чтобы не словить -100% по плечу)
    sl_atr_min=0.8,
    sl_atr_max=1.5,

    # Position sizing
    position_size_mult=1.0,  # Риск выше, но не size

    # Time (короче)
    max_hold_hours=24,

    # Behavior
    trust_levels=True,
    aggressive_entries=True,  # Быстрее входим

    # Symbols
    allowed_symbols=None,

    # EV Gates (мягче для high risk)
    ev_disable_threshold=-0.25,
    ev_min_trades=15,

    # Safety caps (строже по количеству)
    max_trades_per_day=3,
    max_consecutive_losses=2,
    daily_loss_cap_usd=100.0,
    cooldown_after_loss_min=120,  # 2 часа после loss

    # Supervisor (агрессивнее)
    liq_proximity_warn_pct=8.0,
    liq_proximity_critical_pct=4.0,
    invalidation_threat_pct=1.0,
    advice_expiration_min=30,
    default_cooldown_min=15,

    # Prompt
    prompt_context="""HIGH RISK MODE:
- TIGHT stops required (0.8-1.5x ATR) to avoid liquidation cascade
- Focus on momentum entries with clear direction
- Stricter no-trade conditions - skip uncertain setups
- Leverage is high, so MUST have clear invalidation
- Quick exits if thesis breaks
- Entry on strength, not weakness
- High confidence required (>70%)"""
)


# ============================================================
# MEME MODE
# ============================================================
# Whitelist символов для MEME режима
MEME_SYMBOLS = [
    "DOGEUSDT",
    "SHIBUSDT",
    "PEPEUSDT",
    "WIFUSDT",
    "BONKUSDT",
    "FLOKIUSDT",
]

MEME_MODE = ModeConfig(
    mode_id="meme",
    mode_family="speculative",
    name="Meme/Volatile",
    description="Для мемкоинов: широкие стопы, уровни не надёжны",
    emoji="🚀",

    # Leverage
    max_leverage=20,
    default_leverage=10,

    # Risk scaling
    risk_multiplier_min=0.6,
    risk_multiplier_max=1.5,

    # Stop Loss (ШИРОКИЙ - уровни пробиваются)
    sl_atr_min=2.0,
    sl_atr_max=5.0,

    # Position sizing (REDUCED - т.к. широкий стоп)
    position_size_mult=0.5,

    # Time (короткое)
    max_hold_hours=12,

    # Behavior
    trust_levels=False,  # Уровни часто фейк
    aggressive_entries=True,

    # Symbols (whitelist)
    allowed_symbols=MEME_SYMBOLS,

    # EV Gates (мягче, мало данных)
    ev_disable_threshold=-0.35,
    ev_min_trades=10,

    # Safety caps
    max_trades_per_day=2,
    max_consecutive_losses=2,
    daily_loss_cap_usd=60.0,
    cooldown_after_loss_min=90,

    # Supervisor
    liq_proximity_warn_pct=12.0,
    liq_proximity_critical_pct=6.0,
    invalidation_threat_pct=3.0,
    advice_expiration_min=20,
    default_cooldown_min=20,

    # Prompt
    prompt_context="""MEME/VOLATILE MODE:
- LEVELS ARE WEAK - expect frequent breakouts and fakeouts
- Use MOMENTUM over structure
- WIDE stops required (2-5x ATR) because wicks are brutal
- Focus on volume spikes and liquidation cascades
- Short holding periods (< 12h typically)
- Pump/dump detection is critical
- Trust trend direction more than specific price levels
- Position size is automatically REDUCED due to wide stops
- Quick partial profits - don't wait for full target"""
)


# ============================================================
# MODE FAMILIES (для Learning fallback)
# ============================================================
MODE_FAMILIES = {
    "conservative": "cautious",
    "standard": "balanced",
    "high_risk": "speculative",
    "meme": "speculative",
}


# ============================================================
# RUNTIME CHECKS для MEME режима
# ============================================================
MEME_RUNTIME_CHECKS = {
    "min_24h_volume_usd": 10_000_000,  # $10M minimum
    "max_spread_pct": 0.3,              # 0.3% max spread
    "min_atr_pct": 2.0,                 # 2% min volatility
    "min_notional_usd": 5.0,            # Чтобы биржа не отклонила
    "max_funding_abs_pct": 0.1,         # Если funding улетел - риск выше
}


# ============================================================
# ALL MODES
# ============================================================
ALL_MODES = {
    "conservative": CONSERVATIVE_MODE,
    "standard": STANDARD_MODE,
    "high_risk": HIGH_RISK_MODE,
    "meme": MEME_MODE,
}

DEFAULT_MODE = "standard"


# ============================================================
# UNIVERSE LIMITS (для динамического выбора символов)
# Полная конфигурация в services/universe/models.py
# ============================================================
UNIVERSE_MODE_SETTINGS = {
    "conservative": {"top_n": 50, "max_change_pct": 25.0},
    "standard": {"top_n": 100},
    "high_risk": {"top_n": 200},
    "meme": {"whitelist_only": True},
}
