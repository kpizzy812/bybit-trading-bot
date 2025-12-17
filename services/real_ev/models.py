"""
Data models for Real EV Tracking.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional, List
from enum import Enum
from datetime import datetime


class GateStatus(str, Enum):
    """Gate check status."""
    NO_DATA = "NO_DATA"      # Недостаточно данных
    ALLOWED = "ALLOWED"      # Разрешено
    WARN = "WARN"            # Разрешено с предупреждением
    SOFT_BLOCK = "SOFT_BLOCK"  # Рекомендуем skip (chop regime)
    BLOCK = "BLOCK"          # Запрещено
    OVERRIDE = "OVERRIDE"    # Принудительно разрешено


class GroupLevel(str, Enum):
    """Уровень группировки."""
    L1 = "L1"  # archetype only
    L2 = "L2"  # archetype + timeframe
    L3 = "L3"  # archetype + timeframe + regime


@dataclass
class EVGroupKey:
    """Ключ группировки для Real EV."""
    archetype: str
    timeframe: Optional[str] = None
    market_regime: Optional[str] = None

    @property
    def level(self) -> GroupLevel:
        """Определить уровень по заполненным полям."""
        if self.market_regime:
            return GroupLevel.L3
        if self.timeframe:
            return GroupLevel.L2
        return GroupLevel.L1

    def to_cache_key(self, lookback_days: int = 90) -> str:
        """Строка для Redis key."""
        if self.market_regime:
            return f"ev:stats:L3:{self.archetype}:{self.timeframe}:{self.market_regime}:{lookback_days}"
        if self.timeframe:
            return f"ev:stats:L2:{self.archetype}:{self.timeframe}:{lookback_days}"
        return f"ev:stats:L1:{self.archetype}:{lookback_days}"

    def to_group_key_str(self) -> str:
        """Строка для ev_group_state.group_key."""
        parts = [self.archetype]
        if self.timeframe:
            parts.append(self.timeframe)
        if self.market_regime:
            parts.append(self.market_regime)
        return ":".join(parts)

    @classmethod
    def from_group_key_str(cls, key: str) -> 'EVGroupKey':
        """Создать из строки group_key."""
        parts = key.split(":")
        return cls(
            archetype=parts[0],
            timeframe=parts[1] if len(parts) > 1 else None,
            market_regime=parts[2] if len(parts) > 2 else None,
        )


@dataclass
class EVGroupStats:
    """Статистика Real EV для группы."""
    level: str                       # L1, L2, L3
    group_key: str                   # "pullback_to_ema50:4h:bullish_accumulation"
    sample_size: int                 # Количество сделок
    paper_ev_avg: Optional[float]    # Средний paper EV (scenario_ev_r)
    real_ev: float                   # Средний r_result
    ev_gap: Optional[float]          # paper_ev_avg - real_ev
    winrate: float                   # % побед
    rolling_ev: Optional[float]      # EV последних N сделок
    rolling_n: int                   # Фактическое кол-во в rolling
    is_disabled: bool = False
    disable_reason: Optional[str] = None
    last_updated: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'EVGroupStats':
        """Deserialize from dict."""
        if 'last_updated' in data and isinstance(data['last_updated'], str):
            data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        return cls(**data)


@dataclass
class FallbackChainItem:
    """Элемент цепочки fallback для debug."""
    level: str
    key: str
    sample_size: int
    real_ev: Optional[float]
    meets_threshold: bool
    reason: str


@dataclass
class EVGateResult:
    """Результат проверки gate."""
    status: GateStatus
    selected_level: Optional[str]    # L1, L2, L3 или None
    selected_key: Optional[str]      # group_key который выбрался
    stats: Optional[EVGroupStats]    # Статистика выбранной группы
    fallback_chain: List[FallbackChainItem] = field(default_factory=list)
    message: str = ""

    @property
    def is_allowed(self) -> bool:
        """Можно ли торговать."""
        return self.status in (GateStatus.NO_DATA, GateStatus.ALLOWED, GateStatus.WARN, GateStatus.OVERRIDE)

    @property
    def has_warning(self) -> bool:
        """Есть ли предупреждение."""
        return self.status in (GateStatus.WARN, GateStatus.SOFT_BLOCK)

    def to_dict(self) -> dict:
        """Serialize for logging."""
        return {
            'status': self.status.value,
            'selected_level': self.selected_level,
            'selected_key': self.selected_key,
            'stats': self.stats.to_dict() if self.stats else None,
            'fallback_chain': [asdict(item) for item in self.fallback_chain],
            'message': self.message,
        }
