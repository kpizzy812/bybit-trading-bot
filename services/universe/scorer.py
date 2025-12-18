"""
Universe Service - Scorer

Расчёт метрик и скоринг символов.
Включает z-score нормализацию и winsorize для защиты от выбросов.
"""
import logging
from math import log
from typing import List, Dict, Tuple
import statistics

from .models import SymbolMetrics

logger = logging.getLogger(__name__)


def winsorize(values: List[float], percentile: float = 1.0) -> List[float]:
    """
    Clip values at percentile boundaries to remove outliers.

    Args:
        values: List of values
        percentile: Percentile to clip at (1.0 = 1st and 99th percentile)

    Returns:
        List with outliers clipped
    """
    if not values or len(values) < 3:
        return values

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    # Calculate percentile indices
    lower_idx = int(n * percentile / 100)
    upper_idx = int(n * (100 - percentile) / 100)

    lower_bound = sorted_vals[lower_idx]
    upper_bound = sorted_vals[min(upper_idx, n - 1)]

    return [max(lower_bound, min(upper_bound, v)) for v in values]


def z_score(values: List[float]) -> List[float]:
    """
    Calculate z-scores for values.

    Z-score = (value - mean) / std

    Args:
        values: List of values

    Returns:
        List of z-scores
    """
    if not values or len(values) < 2:
        return [0.0] * len(values) if values else []

    mean = statistics.mean(values)
    try:
        std = statistics.stdev(values)
    except statistics.StatisticsError:
        std = 0.0

    if std == 0:
        return [0.0] * len(values)

    return [(v - mean) / std for v in values]


def calculate_metrics_from_tickers(tickers: List[Dict]) -> List[SymbolMetrics]:
    """
    Calculate basic metrics from raw tickers.

    Args:
        tickers: List of raw ticker dicts from Bybit

    Returns:
        List of SymbolMetrics (without scores yet)
    """
    metrics = []

    for ticker in tickers:
        try:
            symbol = ticker.get('symbol', '')
            if not symbol:
                continue

            last_price = float(ticker.get('lastPrice', 0) or 0)
            if last_price <= 0:
                continue

            turnover = float(ticker.get('turnover24h', 0) or 0)

            # price24hPcnt comes as fraction (0.1234 = +12.34%)
            price_change_raw = ticker.get('price24hPcnt', '0')
            price_change_pct = float(price_change_raw or 0) * 100

            # Range calculation: (high - low) / low * 100
            high = float(ticker.get('highPrice24h', 0) or 0)
            low = float(ticker.get('lowPrice24h', 0) or 0)

            if low > 0:
                range_pct = (high - low) / low * 100
            else:
                range_pct = 0.0

            metrics.append(SymbolMetrics(
                symbol=symbol,
                last_price=last_price,
                turnover_24h=turnover,
                price_change_pct=price_change_pct,
                range_pct=range_pct,
            ))

        except Exception as e:
            logger.debug(f"Error parsing ticker {ticker.get('symbol', '?')}: {e}")
            continue

    logger.debug(f"Calculated metrics for {len(metrics)} symbols")
    return metrics


def calculate_scores(
    metrics: List[SymbolMetrics],
    top_n_for_scoring: int = 200,
    weights: Tuple[float, float, float] = (0.5, 0.3, 0.2)
) -> List[SymbolMetrics]:
    """
    Calculate trending, bull, and bear scores.

    Algorithm:
    1. Take top N by volume (filters out low-volume garbage)
    2. Winsorize metrics to remove outliers
    3. Z-score normalize
    4. Calculate composite scores

    Args:
        metrics: List of SymbolMetrics with basic metrics
        top_n_for_scoring: Limit to top N by volume before scoring
        weights: (volume_weight, change_weight, range_weight) for trending

    Returns:
        Same list with scores filled in
    """
    if not metrics:
        return metrics

    # Sort by volume, take top N
    sorted_by_vol = sorted(metrics, key=lambda m: m.turnover_24h, reverse=True)
    top_metrics = sorted_by_vol[:top_n_for_scoring]

    if len(top_metrics) < 3:
        # Not enough data for meaningful scoring
        return metrics

    # Extract values for scoring
    vols = [log(m.turnover_24h + 1) for m in top_metrics]  # log(v+1) for safety
    chgs = [m.price_change_pct for m in top_metrics]
    ranges = [m.range_pct for m in top_metrics]

    # Winsorize to remove outliers (1st and 99th percentile)
    vols_w = winsorize(vols, percentile=1.0)
    chgs_w = winsorize(chgs, percentile=1.0)
    ranges_w = winsorize(ranges, percentile=1.0)

    # Z-score normalize
    z_vol = z_score(vols_w)
    z_chg = z_score(chgs_w)
    z_range = z_score(ranges_w)

    # Calculate abs change for "hot" detection (any direction)
    abs_chgs = [abs(c) for c in chgs_w]
    z_chg_abs = z_score(abs_chgs)

    # Bear score = z(-chg)
    neg_chgs = [-c for c in chgs_w]
    z_chg_bear = z_score(neg_chgs)

    # Unpack weights
    w_vol, w_chg, w_range = weights

    # Calculate scores
    for i, m in enumerate(top_metrics):
        m.trending_score = z_vol[i] * w_vol + z_chg_abs[i] * w_chg + z_range[i] * w_range
        m.bull_score = z_chg[i]
        m.bear_score = z_chg_bear[i]

    # Symbols not in top_n keep default scores (0.0)
    # They're still in the original list

    logger.debug(f"Calculated scores for {len(top_metrics)} top symbols")
    return metrics


def sort_by_category(
    metrics: List[SymbolMetrics],
    category: str,
    limit: int = 10
) -> List[SymbolMetrics]:
    """
    Sort metrics by category.

    Args:
        metrics: List of SymbolMetrics
        category: One of: popular, gainers/pumping, losers/dumping, volatile, trending
        limit: Max items to return

    Returns:
        Sorted and limited list
    """
    if not metrics:
        return []

    sort_keys = {
        "popular": lambda m: m.turnover_24h,
        "gainers": lambda m: m.bull_score,
        "pumping": lambda m: m.bull_score,
        "losers": lambda m: m.bear_score,
        "dumping": lambda m: m.bear_score,
        "volatile": lambda m: m.range_pct,
        "trending": lambda m: m.trending_score,
    }

    key_fn = sort_keys.get(category, sort_keys["trending"])
    sorted_metrics = sorted(metrics, key=key_fn, reverse=True)

    return sorted_metrics[:limit]
