"""
Trading Modes - Registry

Реестр торговых режимов с валидацией.
"""
from typing import Optional

from services.trading_modes.models import ModeConfig
from services.trading_modes.presets import ALL_MODES, DEFAULT_MODE, MODE_FAMILIES


class ModeRegistry:
    """
    Реестр торговых режимов.

    Синглтон для получения конфигурации режима по ID.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._modes = ALL_MODES.copy()
        return cls._instance

    def get(self, mode_id: str) -> ModeConfig:
        """
        Получить конфигурацию режима по ID.

        Args:
            mode_id: ID режима (conservative, standard, high_risk, meme)

        Returns:
            ModeConfig для указанного режима

        Raises:
            ValueError: если режим не найден
        """
        if mode_id not in self._modes:
            raise ValueError(
                f"Unknown trading mode: {mode_id}. "
                f"Available: {list(self._modes.keys())}"
            )
        return self._modes[mode_id]

    def get_or_default(self, mode_id: Optional[str]) -> ModeConfig:
        """
        Получить режим или вернуть default.

        Args:
            mode_id: ID режима или None

        Returns:
            ModeConfig для указанного режима или STANDARD
        """
        if not mode_id or mode_id not in self._modes:
            return self._modes[DEFAULT_MODE]
        return self._modes[mode_id]

    def get_family(self, mode_id: str) -> str:
        """
        Получить family режима для Learning fallback.

        Args:
            mode_id: ID режима

        Returns:
            Family: "cautious", "balanced", "speculative"
        """
        return MODE_FAMILIES.get(mode_id, "balanced")

    def list_modes(self) -> list[ModeConfig]:
        """Получить список всех режимов."""
        return list(self._modes.values())

    def list_mode_ids(self) -> list[str]:
        """Получить список ID всех режимов."""
        return list(self._modes.keys())

    def is_valid_mode(self, mode_id: str) -> bool:
        """Проверить валидность ID режима."""
        return mode_id in self._modes

    def is_symbol_allowed(self, mode_id: str, symbol: str) -> bool:
        """
        Проверить разрешён ли символ для режима.

        Args:
            mode_id: ID режима
            symbol: Символ (например BTCUSDT)

        Returns:
            True если символ разрешён
        """
        mode = self.get_or_default(mode_id)
        if mode.allowed_symbols is None:
            return True
        return symbol in mode.allowed_symbols

    def get_allowed_symbols(self, mode_id: str) -> Optional[list]:
        """
        Получить список разрешённых символов для режима.

        Args:
            mode_id: ID режима

        Returns:
            Список символов или None (все разрешены)
        """
        mode = self.get_or_default(mode_id)
        return mode.allowed_symbols


# Глобальный instance
_registry: Optional[ModeRegistry] = None


def get_mode_registry() -> ModeRegistry:
    """Получить глобальный registry режимов."""
    global _registry
    if _registry is None:
        _registry = ModeRegistry()
    return _registry


def get_mode(mode_id: str) -> ModeConfig:
    """Shortcut для получения режима."""
    return get_mode_registry().get(mode_id)


def get_mode_or_default(mode_id: Optional[str]) -> ModeConfig:
    """Shortcut для получения режима или default."""
    return get_mode_registry().get_or_default(mode_id)
