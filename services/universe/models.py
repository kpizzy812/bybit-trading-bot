"""
Universe Service - Models

Модели данных для динамического Universe монет.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class SymbolMetrics:
    """Метрики символа для ранжирования."""
    symbol: str
    last_price: float
    turnover_24h: float         # Volume в USD
    price_change_pct: float     # Изменение в % (уже * 100)
    range_pct: float            # (high-low)/low * 100
    # Scores (заполняются после z-score нормализации)
    trending_score: float = 0.0
    bull_score: float = 0.0     # Для "🔥 Pumping"
    bear_score: float = 0.0     # Для "🧊 Dumping"


@dataclass
class UniverseResult:
    """Результат Universe с категориями и метаданными."""
    # Категории (топы по разным критериям)
    popular: List[SymbolMetrics] = field(default_factory=list)    # По volume
    gainers: List[SymbolMetrics] = field(default_factory=list)    # По bull_score
    losers: List[SymbolMetrics] = field(default_factory=list)     # По bear_score
    volatile: List[SymbolMetrics] = field(default_factory=list)   # По range_pct
    trending: List[SymbolMetrics] = field(default_factory=list)   # По trending_score
    # Метаданные
    as_of: datetime = field(default_factory=datetime.utcnow)
    mode: str = "standard"
    universe_size: int = 0
    source: str = "bybit"

    def get_category(self, category: str, limit: int = 5) -> List[SymbolMetrics]:
        """Получить символы по категории."""
        categories = {
            "popular": self.popular,
            "gainers": self.gainers,
            "pumping": self.gainers,   # alias
            "losers": self.losers,
            "dumping": self.losers,    # alias
            "volatile": self.volatile,
            "trending": self.trending,
        }
        return categories.get(category, self.trending)[:limit]

    def get_symbols(self, category: str, limit: int = 5) -> List[str]:
        """Получить список символов по категории."""
        return [m.symbol for m in self.get_category(category, limit)]


# Константы
MAJOR_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

MEME_SYMBOLS = [
    "DOGEUSDT", "SHIBUSDT", "PEPEUSDT",
    "WIFUSDT", "BONKUSDT", "FLOKIUSDT"
]

# Расширенный meme-tag map (пополняется вручную)
MEME_TAG_MAP = {
    "DOGEUSDT": True, "SHIBUSDT": True, "PEPEUSDT": True,
    "WIFUSDT": True, "BONKUSDT": True, "FLOKIUSDT": True,
    "MEMEUSDT": True, "PEOPLEUSDT": True, "TRUMPUSDT": True,
    "NEIROUSDT": True, "ACTUSDT": True, "PNUTUSDT": True,
}

# Лимиты по режимам торговли
UNIVERSE_LIMITS = {
    "conservative": {
        "top_n": 50,
        "max_change_pct": 25.0,
        "min_turnover": 5_000_000,
    },
    "standard": {
        "top_n": 100,
        "min_turnover": 3_000_000,
    },
    "high_risk": {
        "top_n": 200,
        "min_turnover": 1_000_000,
    },
    "meme": {
        "whitelist": MEME_SYMBOLS,
        "use_dynamic_memes": True,
        "min_turnover": 1_000_000,
    },
}

# Категории для UI
CATEGORY_LABELS = {
    "trending": "🌊 Trending",
    "popular": "📊 Popular",
    "pumping": "🔥 Pumping",
    "dumping": "🧊 Dumping",
    "volatile": "⚡ Volatile",
}
