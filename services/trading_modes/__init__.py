"""
Trading Modes Module

Модуль для управления различными режимами торговли:
- CONSERVATIVE: низкий риск, узкие стопы
- STANDARD: сбалансированный режим
- HIGH_RISK: высокое плечо, тесные стопы
- MEME: для волатильных мемкоинов

Использование:
    from services.trading_modes import get_mode, get_mode_registry

    mode = get_mode("high_risk")
    print(mode.max_leverage)  # 50
"""
from services.trading_modes.models import (
    ModeConfig,
    SafetyCheckResult,
    SymbolFilterResult,
)
from services.trading_modes.presets import (
    CONSERVATIVE_MODE,
    STANDARD_MODE,
    HIGH_RISK_MODE,
    MEME_MODE,
    MEME_SYMBOLS,
    MEME_RUNTIME_CHECKS,
    MODE_FAMILIES,
    ALL_MODES,
    DEFAULT_MODE,
)
from services.trading_modes.registry import (
    ModeRegistry,
    get_mode_registry,
    get_mode,
    get_mode_or_default,
)
from services.trading_modes.symbol_filter import (
    SymbolFilter,
    get_symbol_filter,
)
from services.trading_modes.safety_checker import (
    SafetyChecker,
    get_safety_checker,
)

__all__ = [
    # Models
    "ModeConfig",
    "SafetyCheckResult",
    "SymbolFilterResult",
    # Presets
    "CONSERVATIVE_MODE",
    "STANDARD_MODE",
    "HIGH_RISK_MODE",
    "MEME_MODE",
    "MEME_SYMBOLS",
    "MEME_RUNTIME_CHECKS",
    "MODE_FAMILIES",
    "ALL_MODES",
    "DEFAULT_MODE",
    # Registry
    "ModeRegistry",
    "get_mode_registry",
    "get_mode",
    "get_mode_or_default",
    # Symbol Filter
    "SymbolFilter",
    "get_symbol_filter",
    # Safety Checker
    "SafetyChecker",
    "get_safety_checker",
]
