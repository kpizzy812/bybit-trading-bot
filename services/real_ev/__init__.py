"""
Real EV Tracking Service

Трекинг реального Expected Value по закрытым сделкам.
Группировка по archetype + timeframe + market_regime.
"""
from .models import EVGroupKey, EVGroupStats, EVGateResult, GateStatus
from .calculator import RealEVCalculator
from .cache import EVCache
from .gates import EVGateChecker
from .state import EVStateManager

__all__ = [
    'EVGroupKey',
    'EVGroupStats',
    'EVGateResult',
    'GateStatus',
    'RealEVCalculator',
    'EVCache',
    'EVGateChecker',
    'EVStateManager',
]

# Singleton instances
_calculator: RealEVCalculator = None
_cache: EVCache = None
_gate_checker: EVGateChecker = None
_state_manager: EVStateManager = None


def get_calculator() -> RealEVCalculator:
    global _calculator
    if _calculator is None:
        _calculator = RealEVCalculator()
    return _calculator


def get_cache() -> EVCache:
    global _cache
    if _cache is None:
        _cache = EVCache()
    return _cache


def get_gate_checker() -> EVGateChecker:
    global _gate_checker
    if _gate_checker is None:
        _gate_checker = EVGateChecker()
    return _gate_checker


def get_state_manager() -> EVStateManager:
    global _state_manager
    if _state_manager is None:
        _state_manager = EVStateManager()
    return _state_manager
