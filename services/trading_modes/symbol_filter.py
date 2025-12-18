"""
Trading Modes - Symbol Filter

Runtime-проверки символов для MEME режима.
"""
from loguru import logger
from typing import Optional

from services.trading_modes.models import ModeConfig, SymbolFilterResult
from services.trading_modes.presets import MEME_RUNTIME_CHECKS


class SymbolFilter:
    """
    Фильтр символов для режимов торговли.

    Проверяет whitelist и runtime conditions (volume, spread, ATR, funding).
    """

    def __init__(self, bybit_client=None):
        """
        Args:
            bybit_client: Клиент Bybit для получения market data
        """
        self.bybit = bybit_client
        self.checks = MEME_RUNTIME_CHECKS

    async def check_symbol(
        self,
        symbol: str,
        mode: ModeConfig,
        skip_runtime_checks: bool = False
    ) -> SymbolFilterResult:
        """
        Проверить разрешён ли символ для режима.

        Args:
            symbol: Символ (например DOGEUSDT)
            mode: Конфигурация режима
            skip_runtime_checks: Пропустить runtime проверки

        Returns:
            SymbolFilterResult с результатом и причиной
        """
        warnings = []

        # 1. Проверка whitelist
        if mode.allowed_symbols is not None:
            if symbol not in mode.allowed_symbols:
                return SymbolFilterResult(
                    allowed=False,
                    reason=f"Symbol {symbol} not in {mode.name} whitelist. "
                           f"Allowed: {', '.join(mode.allowed_symbols)}",
                    warnings=warnings
                )

        # 2. Runtime checks (только для MEME режима)
        if mode.mode_id == "meme" and not skip_runtime_checks:
            return await self._check_meme_runtime(symbol, warnings)

        return SymbolFilterResult(
            allowed=True,
            warnings=warnings
        )

    async def _check_meme_runtime(
        self,
        symbol: str,
        warnings: list
    ) -> SymbolFilterResult:
        """
        Runtime проверки для MEME режима.

        Проверяет: volume, spread, ATR, notional, funding.
        """
        if not self.bybit:
            warnings.append("Bybit client not available, skipping runtime checks")
            return SymbolFilterResult(allowed=True, warnings=warnings)

        try:
            # Получаем ticker
            ticker = await self.bybit.get_tickers(symbol)
            if not ticker:
                return SymbolFilterResult(
                    allowed=False,
                    reason=f"Failed to get ticker for {symbol}",
                    warnings=warnings
                )

            # Volume 24h
            volume_24h = float(ticker.get('turnover24h', 0))
            min_volume = self.checks['min_24h_volume_usd']
            if volume_24h < min_volume:
                return SymbolFilterResult(
                    allowed=False,
                    reason=f"24h volume ${volume_24h:,.0f} below minimum ${min_volume:,.0f}",
                    warnings=warnings,
                    volume_24h_usd=volume_24h
                )

            # Spread (bid1 - ask1)
            bid1 = float(ticker.get('bid1Price', 0))
            ask1 = float(ticker.get('ask1Price', 0))
            if bid1 > 0 and ask1 > 0:
                spread_pct = (ask1 - bid1) / bid1 * 100
                max_spread = self.checks['max_spread_pct']
                if spread_pct > max_spread:
                    return SymbolFilterResult(
                        allowed=False,
                        reason=f"Spread {spread_pct:.2f}% exceeds maximum {max_spread}%",
                        warnings=warnings,
                        spread_pct=spread_pct,
                        volume_24h_usd=volume_24h
                    )
            else:
                spread_pct = None
                warnings.append("Could not calculate spread")

            # ATR check требует klines - делаем отдельно если нужно
            # Пока просто warning
            warnings.append("ATR check requires klines, skipped in quick check")

            # Funding rate
            funding_rate = None
            try:
                funding_info = await self.bybit.get_funding_rate(symbol)
                if funding_info:
                    funding_rate = float(funding_info.get('fundingRate', 0)) * 100
                    max_funding = self.checks['max_funding_abs_pct']
                    if abs(funding_rate) > max_funding:
                        warnings.append(
                            f"Funding rate {funding_rate:+.3f}% is extreme "
                            f"(>{max_funding}%), increased risk"
                        )
            except Exception as e:
                logger.warning(f"Failed to get funding rate for {symbol}: {e}")

            return SymbolFilterResult(
                allowed=True,
                warnings=warnings,
                volume_24h_usd=volume_24h,
                spread_pct=spread_pct,
                funding_rate_pct=funding_rate
            )

        except Exception as e:
            logger.error(f"Runtime check failed for {symbol}: {e}")
            warnings.append(f"Runtime check error: {e}")
            # При ошибке - разрешаем с warning
            return SymbolFilterResult(
                allowed=True,
                warnings=warnings
            )

    async def check_atr_volatility(
        self,
        symbol: str,
        klines: list,
        timeframe: str = "4h"
    ) -> Optional[float]:
        """
        Проверить ATR volatility для MEME режима.

        Args:
            symbol: Символ
            klines: OHLCV данные
            timeframe: Таймфрейм

        Returns:
            ATR в процентах от цены или None
        """
        if not klines or len(klines) < 14:
            return None

        try:
            # Простой расчёт ATR
            tr_values = []
            for i in range(1, min(15, len(klines))):
                high = float(klines[i]['high'])
                low = float(klines[i]['low'])
                prev_close = float(klines[i-1]['close'])

                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )
                tr_values.append(tr)

            atr = sum(tr_values) / len(tr_values)
            current_price = float(klines[-1]['close'])
            atr_pct = (atr / current_price) * 100

            return atr_pct

        except Exception as e:
            logger.error(f"ATR calculation failed: {e}")
            return None


# Глобальный instance
_filter: Optional[SymbolFilter] = None


def get_symbol_filter(bybit_client=None) -> SymbolFilter:
    """Получить глобальный symbol filter."""
    global _filter
    if _filter is None or bybit_client is not None:
        _filter = SymbolFilter(bybit_client)
    return _filter
