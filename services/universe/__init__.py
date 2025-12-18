"""
Universe Service

Динамический Universe монет для AI Scenarios и Trade Wizard.
Категории: Popular, Gainers, Losers, Volatile, Trending.
"""

from .models import (
    SymbolMetrics,
    UniverseResult,
    MAJOR_SYMBOLS,
    MEME_SYMBOLS,
    MEME_TAG_MAP,
    UNIVERSE_LIMITS,
    CATEGORY_LABELS,
)

from .service import (
    UniverseService,
    get_universe_service,
)

from .cache import (
    UniverseCache,
    get_universe_cache,
)

from .fetcher import (
    UniverseFetcher,
    get_universe_fetcher,
)

from .scorer import (
    calculate_metrics_from_tickers,
    calculate_scores,
    sort_by_category,
    winsorize,
    z_score,
)

__all__ = [
    # Models
    "SymbolMetrics",
    "UniverseResult",
    "MAJOR_SYMBOLS",
    "MEME_SYMBOLS",
    "MEME_TAG_MAP",
    "UNIVERSE_LIMITS",
    "CATEGORY_LABELS",
    # Service
    "UniverseService",
    "get_universe_service",
    # Cache
    "UniverseCache",
    "get_universe_cache",
    # Fetcher
    "UniverseFetcher",
    "get_universe_fetcher",
    # Scorer
    "calculate_metrics_from_tickers",
    "calculate_scores",
    "sort_by_category",
    "winsorize",
    "z_score",
]
