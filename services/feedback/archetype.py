"""
Archetype Classifier

Rule-based классификация торговых сетапов.
НЕ использует LLM - полностью детерминированная логика.

Архетипы:
- pullback_to_ema20/50: Откат к EMA в тренде
- breakout_retest: Пробой с ретестом
- range_bounce_support/resistance: Отскок от границ рейнджа
- momentum_continuation: Продолжение импульса
- reversal_oversold/overbought: Разворот от экстремумов RSI
- liquidation_sweep: Вход после ликвидаций
"""
import logging
from typing import Tuple, List, Dict, Any, Optional

from services.trade_logger import TradeRecord
from services.feedback.models import ScenarioFactors

logger = logging.getLogger(__name__)


# Определения архетипов
ARCHETYPES = {
    "pullback_to_ema20": {
        "description": "Откат к EMA20 в тренде",
        "priority": 1,
    },
    "pullback_to_ema50": {
        "description": "Откат к EMA50 в тренде",
        "priority": 2,
    },
    "breakout_retest": {
        "description": "Пробой уровня с ретестом",
        "priority": 3,
    },
    "range_bounce_support": {
        "description": "Отскок от поддержки рейнджа",
        "priority": 4,
    },
    "range_bounce_resistance": {
        "description": "Отскок от сопротивления рейнджа",
        "priority": 5,
    },
    "momentum_continuation": {
        "description": "Продолжение импульса в сильном тренде",
        "priority": 6,
    },
    "reversal_oversold": {
        "description": "Разворот от перепроданности (RSI < 30)",
        "priority": 7,
    },
    "reversal_overbought": {
        "description": "Разворот от перекупленности (RSI > 70)",
        "priority": 8,
    },
    "liquidation_sweep": {
        "description": "Вход после ликвидационного свипа",
        "priority": 9,
    },
    "unknown": {
        "description": "Неклассифицированный сетап",
        "priority": 100,
    },
}


class ArchetypeClassifier:
    """
    Rule-based классификатор архетипов.

    Возвращает:
    - primary_archetype: str
    - confidence: float (0-1)
    - tags: List[str]
    """

    # Порог близости к EMA (в процентах)
    EMA_PROXIMITY_PCT = 0.5  # 0.5%

    # RSI пороги
    RSI_OVERSOLD = 30
    RSI_OVERBOUGHT = 70

    # ADX порог для сильного тренда
    ADX_STRONG_TREND = 25

    def classify(
        self,
        trade: TradeRecord,
        snapshot: Dict[str, Any],
        factors: ScenarioFactors
    ) -> Tuple[str, float, List[str]]:
        """
        Классифицировать сделку в архетип.

        Args:
            trade: TradeRecord
            snapshot: Scenario snapshot
            factors: Extracted factors

        Returns:
            (archetype, confidence, tags)
        """
        tags = []
        scores = {}

        # Собираем теги на основе факторов
        tags.extend(self._collect_trend_tags(trade, factors))
        tags.extend(self._collect_ema_tags(trade, snapshot, factors))
        tags.extend(self._collect_rsi_tags(factors))
        tags.extend(self._collect_funding_tags(factors))
        tags.extend(self._collect_volatility_tags(factors))
        tags.extend(self._collect_structure_tags(snapshot))

        # Оцениваем каждый архетип
        scores["pullback_to_ema20"] = self._score_pullback_ema20(trade, factors, tags)
        scores["pullback_to_ema50"] = self._score_pullback_ema50(trade, factors, tags)
        scores["breakout_retest"] = self._score_breakout_retest(trade, snapshot, tags)
        scores["range_bounce_support"] = self._score_range_bounce_support(trade, factors, tags)
        scores["range_bounce_resistance"] = self._score_range_bounce_resistance(trade, factors, tags)
        scores["momentum_continuation"] = self._score_momentum_continuation(trade, factors, tags)
        scores["reversal_oversold"] = self._score_reversal_oversold(trade, factors, tags)
        scores["reversal_overbought"] = self._score_reversal_overbought(trade, factors, tags)
        scores["liquidation_sweep"] = self._score_liquidation_sweep(trade, snapshot, tags)

        # Выбираем лучший архетип
        best_archetype = "unknown"
        best_score = 0.0

        for archetype, score in scores.items():
            if score > best_score:
                best_score = score
                best_archetype = archetype

        # Confidence = score, clamped to 0.3-0.95
        confidence = max(0.3, min(0.95, best_score))

        logger.debug(
            f"Archetype classification: {best_archetype} "
            f"(confidence={confidence:.2f}, tags={tags})"
        )

        return best_archetype, confidence, tags

    # =========================================================================
    # TAG COLLECTORS
    # =========================================================================

    def _collect_trend_tags(
        self,
        trade: TradeRecord,
        factors: ScenarioFactors
    ) -> List[str]:
        """Собрать теги тренда."""
        tags = []

        if factors.trend == "up":
            tags.append("bullish_trend")
        elif factors.trend == "down":
            tags.append("bearish_trend")
        else:
            tags.append("sideways")

        # Alignment с направлением сделки
        if factors.trend == "up" and trade.side == "Long":
            tags.append("trend_aligned")
        elif factors.trend == "down" and trade.side == "Short":
            tags.append("trend_aligned")
        elif factors.trend != "sideways":
            tags.append("counter_trend")

        return tags

    def _collect_ema_tags(
        self,
        trade: TradeRecord,
        snapshot: Dict[str, Any],
        factors: ScenarioFactors
    ) -> List[str]:
        """Собрать теги по EMA."""
        tags = []
        entry_price = trade.entry_price

        # Проверяем близость к EMA
        if factors.ema_20:
            dist_pct = abs(entry_price - factors.ema_20) / factors.ema_20 * 100
            if dist_pct < self.EMA_PROXIMITY_PCT:
                tags.append("ema20_touch")
            if entry_price > factors.ema_20:
                tags.append("above_ema20")
            else:
                tags.append("below_ema20")

        if factors.ema_50:
            dist_pct = abs(entry_price - factors.ema_50) / factors.ema_50 * 100
            if dist_pct < self.EMA_PROXIMITY_PCT:
                tags.append("ema50_touch")
            if entry_price > factors.ema_50:
                tags.append("above_ema50")
            else:
                tags.append("below_ema50")

        if factors.ema_200:
            if entry_price > factors.ema_200:
                tags.append("above_ema200")
            else:
                tags.append("below_ema200")

        return tags

    def _collect_rsi_tags(self, factors: ScenarioFactors) -> List[str]:
        """Собрать теги RSI."""
        tags = []

        if factors.rsi:
            if factors.rsi < self.RSI_OVERSOLD:
                tags.append("rsi_oversold")
            elif factors.rsi > self.RSI_OVERBOUGHT:
                tags.append("rsi_overbought")
            else:
                tags.append("rsi_neutral")

        return tags

    def _collect_funding_tags(self, factors: ScenarioFactors) -> List[str]:
        """Собрать теги funding rate."""
        tags = []

        if factors.funding_rate is not None:
            if factors.funding_rate > 0.03:
                tags.append("high_funding")
            elif factors.funding_rate < 0.01:
                tags.append("low_funding")
            if factors.funding_rate < 0:
                tags.append("negative_funding")

        return tags

    def _collect_volatility_tags(self, factors: ScenarioFactors) -> List[str]:
        """Собрать теги волатильности."""
        tags = []

        if factors.volatility_regime:
            if factors.volatility_regime.value == "high":
                tags.append("high_volatility")
            elif factors.volatility_regime.value == "low":
                tags.append("low_volatility")

        if factors.atr_pct:
            if factors.atr_pct > 3.0:
                tags.append("volatility_expansion")
            elif factors.atr_pct < 1.0:
                tags.append("volatility_contraction")

        return tags

    def _collect_structure_tags(self, snapshot: Dict[str, Any]) -> List[str]:
        """Собрать теги структуры."""
        tags = []

        # Проверяем entry_plan на наличие breakout/retest
        entry_plan = snapshot.get("entry_plan", {})
        activation = entry_plan.get("activation", {})

        if activation:
            act_type = activation.get("type", "")
            if act_type in ("break", "break_above", "break_below"):
                tags.append("breakout")
            elif act_type == "touch":
                tags.append("retest")

        # Проверяем scenario name
        scenario_name = snapshot.get("name", "").lower()
        if "breakout" in scenario_name:
            tags.append("breakout")
        if "retest" in scenario_name:
            tags.append("retest")
        if "range" in scenario_name:
            tags.append("range_setup")
        if "support" in scenario_name:
            tags.append("range_support")
        if "resistance" in scenario_name:
            tags.append("range_resistance")

        return tags

    # =========================================================================
    # ARCHETYPE SCORERS
    # =========================================================================

    def _score_pullback_ema20(
        self,
        trade: TradeRecord,
        factors: ScenarioFactors,
        tags: List[str]
    ) -> float:
        """Оценка pullback к EMA20."""
        score = 0.0

        # Требования:
        # 1. Касание EMA20
        # 2. Тренд (не sideways)
        # 3. Направление сделки совпадает с трендом

        if "ema20_touch" in tags:
            score += 0.5

        if "trend_aligned" in tags:
            score += 0.3

        if factors.trend in ("up", "down"):
            score += 0.2

        return score

    def _score_pullback_ema50(
        self,
        trade: TradeRecord,
        factors: ScenarioFactors,
        tags: List[str]
    ) -> float:
        """Оценка pullback к EMA50."""
        score = 0.0

        if "ema50_touch" in tags:
            score += 0.5

        if "trend_aligned" in tags:
            score += 0.3

        if factors.trend in ("up", "down"):
            score += 0.2

        return score

    def _score_breakout_retest(
        self,
        trade: TradeRecord,
        snapshot: Dict[str, Any],
        tags: List[str]
    ) -> float:
        """Оценка breakout с ретестом."""
        score = 0.0

        if "breakout" in tags:
            score += 0.4

        if "retest" in tags:
            score += 0.4

        # Проверяем activation type
        entry_plan = snapshot.get("entry_plan", {})
        activation = entry_plan.get("activation", {})
        if activation.get("type") in ("break", "break_above", "break_below"):
            score += 0.2

        return score

    def _score_range_bounce_support(
        self,
        trade: TradeRecord,
        factors: ScenarioFactors,
        tags: List[str]
    ) -> float:
        """Оценка отскока от поддержки рейнджа."""
        score = 0.0

        # Требования:
        # 1. Sideways тренд
        # 2. Long позиция
        # 3. Близко к поддержке

        if "sideways" in tags:
            score += 0.3

        if trade.side == "Long":
            score += 0.2

        if "range_support" in tags or "range_setup" in tags:
            score += 0.3

        # Проверяем близость к support levels
        if factors.support_levels:
            for support in factors.support_levels[:3]:  # Топ 3 уровня
                dist_pct = abs(trade.entry_price - support) / support * 100
                if dist_pct < 1.0:  # 1%
                    score += 0.2
                    break

        return score

    def _score_range_bounce_resistance(
        self,
        trade: TradeRecord,
        factors: ScenarioFactors,
        tags: List[str]
    ) -> float:
        """Оценка отскока от сопротивления рейнджа."""
        score = 0.0

        if "sideways" in tags:
            score += 0.3

        if trade.side == "Short":
            score += 0.2

        if "range_resistance" in tags or "range_setup" in tags:
            score += 0.3

        if factors.resistance_levels:
            for resistance in factors.resistance_levels[:3]:
                dist_pct = abs(trade.entry_price - resistance) / resistance * 100
                if dist_pct < 1.0:
                    score += 0.2
                    break

        return score

    def _score_momentum_continuation(
        self,
        trade: TradeRecord,
        factors: ScenarioFactors,
        tags: List[str]
    ) -> float:
        """Оценка momentum continuation."""
        score = 0.0

        # Требования:
        # 1. Сильный ADX
        # 2. Тренд
        # 3. Направление совпадает

        if factors.adx and factors.adx > self.ADX_STRONG_TREND:
            score += 0.4

        if "trend_aligned" in tags:
            score += 0.3

        if factors.trend in ("up", "down"):
            score += 0.2

        # Бонус за высокую волатильность
        if "volatility_expansion" in tags:
            score += 0.1

        return score

    def _score_reversal_oversold(
        self,
        trade: TradeRecord,
        factors: ScenarioFactors,
        tags: List[str]
    ) -> float:
        """Оценка разворота от перепроданности."""
        score = 0.0

        # Требования:
        # 1. RSI < 30
        # 2. Long позиция

        if "rsi_oversold" in tags:
            score += 0.6

        if trade.side == "Long":
            score += 0.3

        # Негативный funding = дополнительный сигнал
        if "negative_funding" in tags:
            score += 0.1

        return score

    def _score_reversal_overbought(
        self,
        trade: TradeRecord,
        factors: ScenarioFactors,
        tags: List[str]
    ) -> float:
        """Оценка разворота от перекупленности."""
        score = 0.0

        if "rsi_overbought" in tags:
            score += 0.6

        if trade.side == "Short":
            score += 0.3

        # Высокий funding = дополнительный сигнал
        if "high_funding" in tags:
            score += 0.1

        return score

    def _score_liquidation_sweep(
        self,
        trade: TradeRecord,
        snapshot: Dict[str, Any],
        tags: List[str]
    ) -> float:
        """Оценка входа после ликвидационного свипа."""
        score = 0.0

        # Проверяем liquidation данные в snapshot
        liquidation = snapshot.get("liquidation", {})

        if liquidation:
            # Проверяем liq_pressure_bias
            bias = liquidation.get("liq_pressure_bias", "")
            if bias in ("bullish", "bearish"):
                score += 0.3

            # Проверяем clusters
            clusters_above = liquidation.get("clusters_above", [])
            clusters_below = liquidation.get("clusters_below", [])

            if clusters_above or clusters_below:
                score += 0.3

        # Проверяем теги
        if "liq_sweep_above" in tags or "liq_sweep_below" in tags:
            score += 0.4

        return score
