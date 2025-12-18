"""
Утилиты для работы с процентным риском от баланса.

Используется когда trading_capital_mode == 'auto'.
"""
import time
import logging
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

# ============================================================
# КОНСТАНТЫ
# ============================================================

EQUITY_CACHE_TTL = 30  # секунд - не дёргать Bybit на каждый клик

MIN_RISK_USD = 2.0  # минимум чтобы не упасть на min-notional
MIN_RISK_PCT = 0.1
MAX_RISK_PCT = 3.0

# Пресеты процентов для UI
ALLOWED_RISK_PCTS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0]


# ============================================================
# EQUITY CACHING
# ============================================================

async def get_equity_cached(
    state_data: Dict[str, Any],
    user_settings,
    force_refresh: bool = False
) -> Tuple[float, Dict[str, Any]]:
    """
    Получить equity с кэшированием в FSM state.

    Args:
        state_data: Данные из FSM state
        user_settings: UserSettings пользователя
        force_refresh: Принудительно обновить кэш

    Returns:
        (equity, updated_state_data)

    Raises:
        ValueError: Если не удалось получить equity
    """
    from services.bybit import BybitClient

    now = time.time()
    cached_equity = state_data.get('cached_equity')
    cached_ts = state_data.get('cached_equity_ts', 0)

    # Проверяем кэш
    if not force_refresh and cached_equity and cached_equity > 0:
        if (now - cached_ts) < EQUITY_CACHE_TTL:
            logger.debug(f"Using cached equity: ${cached_equity:.2f}")
            return cached_equity, state_data

    # Fetch from Bybit
    try:
        bybit = BybitClient(testnet=user_settings.testnet_mode)
        balance = await bybit.get_wallet_balance()

        # Safe parse - Bybit возвращает строки
        equity_raw = balance.get('equity', '0')
        equity = float(equity_raw) if equity_raw else 0.0

        if equity <= 0:
            raise ValueError(
                "Не удалось получить equity.\n"
                "Проверь:\n"
                "• API ключи\n"
                "• Unified аккаунт включён\n"
                "• Есть баланс на аккаунте"
            )

        # Update cache
        state_data['cached_equity'] = equity
        state_data['cached_equity_ts'] = now

        logger.info(f"Fetched equity: ${equity:.2f}")
        return equity, state_data

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error fetching equity: {e}")
        raise ValueError(f"Ошибка получения баланса: {e}")


# ============================================================
# РАСЧЁТЫ
# ============================================================

def calc_risk_usd_from_pct(equity: float, pct: float) -> float:
    """
    Рассчитать risk_usd из процента, с округлением.

    Args:
        equity: Баланс в USD
        pct: Процент риска (например, 0.5 для 0.5%)

    Returns:
        risk_usd округлённый до 2 знаков
    """
    return round(equity * (pct / 100.0), 2)


# ============================================================
# ВАЛИДАЦИЯ
# ============================================================

def validate_risk_pct(pct: float) -> Tuple[bool, Optional[str]]:
    """
    Валидация процента риска.

    Args:
        pct: Процент (например, 0.5)

    Returns:
        (is_valid, error_message)
    """
    if pct < MIN_RISK_PCT:
        return False, f"Минимум {MIN_RISK_PCT}%"
    if pct > MAX_RISK_PCT:
        return False, f"Максимум {MAX_RISK_PCT}%. Рекомендуется 0.5–1%"
    return True, None


def validate_risk_usd(risk_usd: float, max_risk: float) -> Tuple[bool, Optional[str]]:
    """
    Валидация итогового риска в USD.

    Args:
        risk_usd: Рассчитанный риск
        max_risk: Максимальный риск из настроек пользователя

    Returns:
        (is_valid, error_message)
    """
    if risk_usd < MIN_RISK_USD:
        return False, (
            f"Риск ${risk_usd:.2f} слишком мал.\n"
            f"Минимум ${MIN_RISK_USD}.\n"
            f"Увеличь % или пополни депозит."
        )
    if risk_usd > max_risk:
        return False, f"Риск ${risk_usd:.2f} превышает макс ${max_risk:.2f}"
    return True, None


def is_pct_in_whitelist(pct: float) -> bool:
    """Проверить что процент из разрешённого списка."""
    return pct in ALLOWED_RISK_PCTS
