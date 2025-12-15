"""
Trade Wizard - Утилиты
"""
from services.bybit import BybitClient


def calculate_stop_from_percent(entry_price: float, percent: float, side: str) -> float:
    """
    Рассчитать цену стопа от % дистанции

    Args:
        entry_price: Цена входа
        percent: % дистанции (например, 1.5 для 1.5%)
        side: "Buy" (Long) или "Sell" (Short)

    Returns:
        Цена стопа

    Example:
        Entry = 130, percent = 1.5, side = "Buy"
        stop = 130 * (1 - 0.015) = 128.05
    """
    factor = percent / 100.0

    if side == "Buy":  # Long
        stop = entry_price * (1 - factor)
    else:  # Short
        stop = entry_price * (1 + factor)

    return stop


async def get_current_price(client: BybitClient, symbol: str) -> float:
    """Получить текущую mark price для символа"""
    ticker = await client.get_tickers(symbol)
    mark_price = float(ticker.get('markPrice', 0))
    return mark_price
