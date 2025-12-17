"""
Database module for Futures Bot

PostgreSQL storage for:
- Scenarios (from Syntra API with full metadata)
- Trades (linked to scenarios)
- No-trade signals history
- Market contexts
"""

from database.engine import (
    init_db,
    close_db,
    get_session,
    AsyncSessionLocal
)
from database.models import (
    Base,
    Scenario,
    Trade,
    NoTradeSignal,
    MarketContext,
    UserSettingsDB,
)
from database.repository import ScenarioRepository, UserSettingsRepository

__all__ = [
    # Engine
    'init_db',
    'close_db',
    'get_session',
    'AsyncSessionLocal',
    # Models
    'Base',
    'Scenario',
    'Trade',
    'NoTradeSignal',
    'MarketContext',
    'UserSettingsDB',
    # Repository
    'ScenarioRepository',
    'UserSettingsRepository',
]
