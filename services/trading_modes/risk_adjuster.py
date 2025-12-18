"""
Trading Modes - Risk Adjuster

Адаптация risk, leverage, position size под режим торговли.
"""
from typing import Tuple, Optional
from loguru import logger

from services.trading_modes.models import ModeConfig
from services.trading_modes.registry import get_mode_or_default


class RiskAdjuster:
    """
    Адаптер риска под режим торговли.

    Применяет mode-specific ограничения:
    - Risk multiplier range
    - Leverage cap
    - Position size multiplier
    - SL ATR range
    """

    def __init__(self, mode: Optional[ModeConfig] = None):
        """
        Args:
            mode: Конфигурация режима или None для default
        """
        self.mode = mode or get_mode_or_default(None)

    def adjust_risk(
        self,
        base_risk_usd: float,
        confidence: float = 0.5
    ) -> float:
        """
        Скорректировать риск на основе confidence и режима.

        Args:
            base_risk_usd: Базовый риск в USD
            confidence: Confidence от AI (0.0 - 1.0)

        Returns:
            Скорректированный риск в USD
        """
        # Маппим confidence [0, 1] на risk_multiplier_range
        mult_min = self.mode.risk_multiplier_min
        mult_max = self.mode.risk_multiplier_max

        # Linear interpolation
        multiplier = mult_min + (mult_max - mult_min) * confidence

        adjusted_risk = base_risk_usd * multiplier

        logger.debug(
            f"Risk adjusted: ${base_risk_usd:.2f} × {multiplier:.2f} "
            f"(conf={confidence:.2f}) = ${adjusted_risk:.2f} "
            f"[mode={self.mode.mode_id}]"
        )

        return adjusted_risk

    def adjust_position_size(
        self,
        base_size_usd: float
    ) -> float:
        """
        Скорректировать размер позиции под режим.

        Для MEME режима автоматически уменьшаем size.

        Args:
            base_size_usd: Базовый размер позиции в USD

        Returns:
            Скорректированный размер
        """
        mult = self.mode.position_size_mult
        adjusted = base_size_usd * mult

        if mult != 1.0:
            logger.debug(
                f"Position size adjusted: ${base_size_usd:.2f} × {mult} "
                f"= ${adjusted:.2f} [mode={self.mode.mode_id}]"
            )

        return adjusted

    def get_leverage(
        self,
        requested_leverage: int,
        confidence: Optional[float] = None
    ) -> int:
        """
        Получить leverage с учётом mode cap.

        Args:
            requested_leverage: Запрошенное плечо
            confidence: Опционально - снизить leverage при низком confidence

        Returns:
            Итоговое плечо (не выше mode.max_leverage)
        """
        # Cap по режиму
        max_lev = self.mode.max_leverage
        leverage = min(requested_leverage, max_lev)

        # Опционально снижаем при низком confidence
        if confidence is not None and confidence < 0.4:
            # При confidence < 0.4 используем default leverage
            leverage = min(leverage, self.mode.default_leverage)
            logger.debug(
                f"Leverage reduced due to low confidence ({confidence:.2f}): "
                f"{requested_leverage}x → {leverage}x"
            )

        if leverage != requested_leverage:
            logger.debug(
                f"Leverage capped: {requested_leverage}x → {leverage}x "
                f"[mode={self.mode.mode_id}, max={max_lev}x]"
            )

        return leverage

    def get_sl_atr_range(self) -> Tuple[float, float]:
        """
        Получить диапазон SL в ATR для режима.

        Returns:
            (min_atr, max_atr) - диапазон множителей ATR для SL
        """
        return (self.mode.sl_atr_min, self.mode.sl_atr_max)

    def validate_sl_distance(
        self,
        sl_distance_pct: float,
        atr_pct: float
    ) -> Tuple[bool, str]:
        """
        Валидация расстояния до SL относительно ATR.

        Args:
            sl_distance_pct: Расстояние до SL в %
            atr_pct: ATR в % от цены

        Returns:
            (valid, reason) - результат валидации
        """
        if atr_pct <= 0:
            return True, "ATR not available"

        sl_atr_mult = sl_distance_pct / atr_pct
        min_atr, max_atr = self.get_sl_atr_range()

        if sl_atr_mult < min_atr:
            return False, (
                f"SL too tight: {sl_atr_mult:.2f}x ATR "
                f"(min {min_atr}x for {self.mode.name})"
            )

        if sl_atr_mult > max_atr:
            return False, (
                f"SL too wide: {sl_atr_mult:.2f}x ATR "
                f"(max {max_atr}x for {self.mode.name})"
            )

        return True, f"SL OK: {sl_atr_mult:.2f}x ATR"

    def get_risk_multiplier_for_confidence(
        self,
        confidence: float
    ) -> float:
        """
        Получить risk multiplier для заданного confidence.

        Args:
            confidence: Confidence от AI (0.0 - 1.0)

        Returns:
            Risk multiplier
        """
        mult_min = self.mode.risk_multiplier_min
        mult_max = self.mode.risk_multiplier_max
        return mult_min + (mult_max - mult_min) * confidence

    def calculate_position_params(
        self,
        risk_usd: float,
        entry_price: float,
        sl_price: float,
        requested_leverage: int,
        confidence: float = 0.5
    ) -> dict:
        """
        Рассчитать все параметры позиции с учётом режима.

        Args:
            risk_usd: Базовый риск в USD
            entry_price: Цена входа
            sl_price: Цена стопа
            requested_leverage: Запрошенное плечо
            confidence: Confidence от AI

        Returns:
            Dict с параметрами: adjusted_risk, leverage, qty, margin, notional
        """
        # 1. Корректируем риск
        adjusted_risk = self.adjust_risk(risk_usd, confidence)

        # 2. Корректируем leverage
        leverage = self.get_leverage(requested_leverage, confidence)

        # 3. Расстояние до SL
        sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100

        # 4. Рассчитываем qty из риска
        # risk = qty * entry * sl_distance%
        # qty = risk / (entry * sl_distance%)
        if sl_distance_pct > 0:
            qty_usd = adjusted_risk / (sl_distance_pct / 100)
        else:
            qty_usd = adjusted_risk * leverage  # fallback

        # 5. Применяем position_size_mult
        qty_usd = self.adjust_position_size(qty_usd)

        # 6. Рассчитываем margin и notional
        qty = qty_usd / entry_price
        notional = qty * entry_price
        margin = notional / leverage

        return {
            "adjusted_risk_usd": adjusted_risk,
            "leverage": leverage,
            "qty": qty,
            "qty_usd": qty_usd,
            "margin_usd": margin,
            "notional_usd": notional,
            "sl_distance_pct": sl_distance_pct,
            "mode_id": self.mode.mode_id,
            "position_size_mult": self.mode.position_size_mult,
        }


def get_risk_adjuster(mode_id: Optional[str] = None) -> RiskAdjuster:
    """Создать RiskAdjuster для указанного режима."""
    mode = get_mode_or_default(mode_id)
    return RiskAdjuster(mode)


def adjust_risk_for_mode(
    base_risk_usd: float,
    confidence: float,
    mode_id: Optional[str] = None
) -> float:
    """Shortcut для корректировки риска."""
    adjuster = get_risk_adjuster(mode_id)
    return adjuster.adjust_risk(base_risk_usd, confidence)


def get_leverage_for_mode(
    requested_leverage: int,
    mode_id: Optional[str] = None,
    confidence: Optional[float] = None
) -> int:
    """Shortcut для получения leverage."""
    adjuster = get_risk_adjuster(mode_id)
    return adjuster.get_leverage(requested_leverage, confidence)
