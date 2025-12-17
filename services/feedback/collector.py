"""
Feedback Collector

Собирает данные из TradeRecord и формирует 4 слоя телеметрии:
- B) Execution Report
- C) Outcome Report
- D) Attribution

Слой A (Scenario Snapshot) берётся напрямую из TradeRecord.scenario_snapshot
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from services.trade_logger import TradeRecord, TradeFill
from services.feedback.models import (
    TradeFeedback,
    ExecutionReport,
    OutcomeReport,
    Attribution,
    ScenarioFactors,
    OrderFill,
    ExitReason,
    TradeLabel,
    VolatilityRegime,
    TerminalOutcome,
)
from services.feedback.archetype import ArchetypeClassifier

logger = logging.getLogger(__name__)


def get_terminal_outcome(
    trade: 'TradeRecord',
    snapshot: Dict[str, Any],
) -> tuple[str, List[str], int]:
    """
    Определить terminal outcome по max_price_seen.

    Terminal outcome = MAX TP HIT, НЕ exit_reason последнего fill.
    Использует min_price_seen / max_price_seen из TradeRecord.

    Args:
        trade: TradeRecord с min_price_seen / max_price_seen
        snapshot: scenario_snapshot с targets

    Returns:
        (terminal_outcome, flags, max_tp_reached)
    """
    flags = []

    # Извлекаем targets из snapshot
    targets = snapshot.get("targets", [])
    if not targets:
        # Нет targets — fallback на exit_reason
        if trade.exit_reason in ("manual", "timeout", "breakeven"):
            return TerminalOutcome.OTHER.value, ["no_targets_in_snapshot"], 0
        return TerminalOutcome.SL.value, ["no_targets_in_snapshot"], 0

    # Получаем цены TP (сортируем по порядку)
    tp_prices = []
    for t in targets:
        price = t.get("price")
        if price is not None:
            tp_prices.append(float(price))

    n_targets = len(tp_prices)
    if n_targets == 0:
        if trade.exit_reason in ("manual", "timeout", "breakeven"):
            return TerminalOutcome.OTHER.value, ["no_tp_prices"], 0
        return TerminalOutcome.SL.value, ["no_tp_prices"], 0

    if n_targets < 3:
        flags.append(f"reduced_targets_{n_targets}")

    # Получаем MFE price
    entry_price = trade.entry_price
    side = trade.side.lower() if trade.side else "long"

    if side == "long":
        mfe_price = trade.max_price_seen or entry_price
    else:  # short
        mfe_price = trade.min_price_seen or entry_price

    if mfe_price is None or mfe_price == entry_price:
        # Нет движения — SL или OTHER
        if trade.exit_reason in ("manual", "timeout", "breakeven"):
            return TerminalOutcome.OTHER.value, flags, 0
        return TerminalOutcome.SL.value, flags, 0

    # Проверяем какой TP был достигнут (с допуском)
    # Допуск = 0.1% от цены (примерный tick margin)
    tick_margin_pct = 0.001

    max_tp_reached = 0

    # Проверяем от старшего TP к младшему
    for i in range(n_targets - 1, -1, -1):
        tp_price = tp_prices[i]
        margin = tp_price * tick_margin_pct

        if side == "long":
            if mfe_price >= tp_price - margin:
                max_tp_reached = i + 1
                if mfe_price < tp_price:
                    flags.append("tp_touch_by_wick")
                break
        else:  # short
            if mfe_price <= tp_price + margin:
                max_tp_reached = i + 1
                if mfe_price > tp_price:
                    flags.append("tp_touch_by_wick")
                break

    # Маппинг max_tp_reached → terminal_outcome
    if max_tp_reached >= 3:
        return TerminalOutcome.TP3.value, flags, 3
    elif max_tp_reached == 2:
        return TerminalOutcome.TP2.value, flags, 2
    elif max_tp_reached == 1:
        return TerminalOutcome.TP1.value, flags, 1
    else:
        # Не дошли ни до одного TP
        if trade.exit_reason in ("manual", "timeout", "breakeven"):
            return TerminalOutcome.OTHER.value, flags, 0
        return TerminalOutcome.SL.value, flags, 0


class FeedbackCollector:
    """
    Собирает feedback из TradeRecord после закрытия позиции.

    Использование:
        collector = FeedbackCollector()
        feedback = collector.collect(trade_record)
    """

    def __init__(self):
        self.archetype_classifier = ArchetypeClassifier()

    def collect(self, trade: TradeRecord) -> Optional[TradeFeedback]:
        """
        Собрать полный feedback из закрытой сделки.

        Args:
            trade: Закрытая сделка (TradeRecord)

        Returns:
            TradeFeedback или None если сделка не подходит
        """
        # Проверяем что сделка подходит для feedback
        if not self._is_valid_for_feedback(trade):
            logger.debug(f"Trade {trade.trade_id} not valid for feedback")
            return None

        # Извлекаем данные из scenario_snapshot
        snapshot = trade.scenario_snapshot or {}
        analysis_id = snapshot.get("analysis_id", "")
        scenario_local_id = snapshot.get("id", 1)

        # Если нет analysis_id - генерируем из trade_id
        if not analysis_id:
            analysis_id = f"legacy_{trade.trade_id[:8]}"

        # Вычисляем scenario_hash
        scenario_hash = TradeFeedback.compute_scenario_hash(snapshot) if snapshot else ""

        # Собираем слои
        execution = self._build_execution_report(trade)
        outcome = self._build_outcome_report(trade)
        attribution = self._build_attribution(trade, snapshot)

        # Формируем idempotency_key
        idempotency_key = TradeFeedback.make_idempotency_key(trade.trade_id, "full")

        # Собираем финальный feedback
        feedback = TradeFeedback(
            trade_id=trade.trade_id,
            analysis_id=analysis_id,
            scenario_local_id=scenario_local_id,
            scenario_hash=scenario_hash,
            idempotency_key=idempotency_key,
            user_id=trade.user_id,
            symbol=trade.symbol,
            side=trade.side,
            timeframe=trade.timeframe or "4h",
            is_testnet=trade.testnet,
            confidence_raw=trade.scenario_confidence or 0.5,
            execution=execution,
            outcome=outcome,
            attribution=attribution,
            scenario_snapshot=snapshot,
        )

        logger.info(
            f"Feedback collected for trade {trade.trade_id}: "
            f"label={outcome.label.value if outcome else 'N/A'}, "
            f"pnl_r={outcome.pnl_r if outcome else 0:.2f}"
        )

        return feedback

    def _is_valid_for_feedback(self, trade: TradeRecord) -> bool:
        """Проверить что сделка подходит для feedback."""
        # Только закрытые сделки
        if trade.status not in ("closed", "liquidated"):
            return False

        # Только сделки от Syntra (или с scenario_snapshot)
        if trade.scenario_source != "syntra" and not trade.scenario_snapshot:
            return False

        # Должен быть trade_id
        if not trade.trade_id:
            return False

        return True

    def _build_execution_report(self, trade: TradeRecord) -> ExecutionReport:
        """Построить Execution Report (Layer B)."""
        # Собираем entry fills
        entry_fills = []
        if trade.entry_fills:
            for fill in trade.entry_fills:
                entry_fills.append(OrderFill(
                    order_id=fill.get("order_id", ""),
                    order_type=fill.get("type", "market"),
                    side="Buy" if trade.side == "Long" else "Sell",
                    price=fill.get("price", trade.entry_price),
                    qty=fill.get("qty", 0),
                    fee_usd=fill.get("fee_usd", 0),
                    timestamp=fill.get("timestamp", trade.opened_at),
                    is_entry=True,
                    tag=fill.get("tag"),
                ))

        # Если нет entry_fills - создаём один из entry_price
        if not entry_fills:
            entry_fills.append(OrderFill(
                order_id="",
                order_type="market",
                side="Buy" if trade.side == "Long" else "Sell",
                price=trade.entry_price,
                qty=trade.qty,
                fee_usd=trade.entry_fee_usd or 0,
                timestamp=trade.opened_at,
                is_entry=True,
            ))

        # Собираем exit fills
        exit_fills = []
        if trade.fills:
            for fill_dict in trade.fills:
                fill = TradeFill.from_dict(fill_dict) if isinstance(fill_dict, dict) else fill_dict
                exit_fills.append(OrderFill(
                    order_id=fill.fill_id,
                    order_type="market",
                    side="Sell" if trade.side == "Long" else "Buy",
                    price=fill.price,
                    qty=fill.qty,
                    fee_usd=fill.fee_usd,
                    timestamp=fill.timestamp,
                    is_entry=False,
                    tag=fill.reason,
                ))

        # Рассчитываем slippage
        planned_entry = self._get_planned_entry(trade)
        actual_entry = trade.avg_entry_price or trade.entry_price
        slippage_pct, slippage_usd = ExecutionReport.calculate_slippage(
            planned_entry, actual_entry, trade.qty, trade.side
        )

        # Время исполнения
        entry_start = trade.opened_at
        entry_complete = trade.opened_at  # Для single entry совпадает

        return ExecutionReport(
            planned_entry_price=planned_entry,
            planned_entry_qty=trade.qty,
            planned_orders_count=trade.entry_orders_count,
            actual_avg_entry=actual_entry,
            actual_total_qty=trade.qty,
            filled_orders_count=len(entry_fills),
            slippage_pct=slippage_pct,
            slippage_usd=slippage_usd,
            entry_fills=entry_fills,
            exit_fills=exit_fills,
            entry_start_ts=entry_start,
            entry_complete_ts=entry_complete,
            execution_duration_sec=0.0,
        )

    def _build_outcome_report(self, trade: TradeRecord) -> OutcomeReport:
        """Построить Outcome Report (Layer C)."""
        # Определяем exit_reason
        exit_reason = self._map_exit_reason(trade.exit_reason)

        # Определяем label
        label = self._determine_label(trade)

        # Рассчитываем pnl_r
        pnl_r = 0.0
        if trade.risk_usd and trade.risk_usd > 0:
            pnl_r = (trade.pnl_usd or 0) / trade.risk_usd

        # Рассчитываем time_in_trade
        time_in_trade_min = 0
        if trade.opened_at and trade.closed_at:
            try:
                opened = datetime.fromisoformat(trade.opened_at.replace("Z", "+00:00"))
                closed = datetime.fromisoformat(trade.closed_at.replace("Z", "+00:00"))
                time_in_trade_min = int((closed - opened).total_seconds() / 60)
            except Exception:
                pass

        # Capture efficiency
        capture_efficiency = 0.0
        mfe_r = trade.mfe_r or 0
        if mfe_r > 0 and pnl_r > 0:
            capture_efficiency = pnl_r / mfe_r

        return OutcomeReport(
            exit_reason=exit_reason,
            exit_price=trade.exit_price or trade.entry_price,
            exit_timestamp=trade.closed_at or datetime.utcnow().isoformat(),
            pnl_usd=trade.pnl_usd or 0,
            pnl_r=pnl_r,
            roe_pct=trade.roe_percent or 0,
            mae_r=trade.mae_r or 0,
            mfe_r=mfe_r,
            mae_usd=trade.mae_usd or 0,
            mfe_usd=trade.mfe_usd or 0,
            capture_efficiency=capture_efficiency,
            time_in_trade_min=time_in_trade_min,
            post_sl_mfe_r=self._calculate_post_sl_mfe(trade),
            post_sl_was_correct=trade.sl_was_correct,
            label=label,
        )

    def _build_attribution(
        self,
        trade: TradeRecord,
        snapshot: Dict[str, Any]
    ) -> Attribution:
        """Построить Attribution (Layer D)."""
        # Извлекаем факторы из snapshot
        factors = self._extract_factors(trade, snapshot)

        # Классифицируем архетип
        archetype, confidence, tags = self.archetype_classifier.classify(
            trade, snapshot, factors
        )

        # Определяем label
        label = self._determine_label(trade)

        # pnl_r
        pnl_r = 0.0
        if trade.risk_usd and trade.risk_usd > 0:
            pnl_r = (trade.pnl_usd or 0) / trade.risk_usd

        # Terminal outcome (для EV системы)
        terminal_outcome, terminal_flags, max_tp = get_terminal_outcome(trade, snapshot)

        # Factor contributions (базовый анализ)
        factor_contributions = self._analyze_factor_contributions(trade, factors, label)

        return Attribution(
            primary_archetype=archetype,
            archetype_confidence=confidence,
            tags=tags,
            factors=factors,
            label=label,
            pnl_r=pnl_r,
            terminal_outcome=terminal_outcome,
            terminal_outcome_flags=terminal_flags,
            max_tp_reached=max_tp,
            factor_contributions=factor_contributions,
        )

    def _get_planned_entry(self, trade: TradeRecord) -> float:
        """Получить планируемую цену входа из сценария."""
        snapshot = trade.scenario_snapshot or {}

        # Пробуем найти entry_plan
        entry_plan = snapshot.get("entry_plan", {})
        if entry_plan:
            orders = entry_plan.get("orders", [])
            if orders:
                # Возвращаем первую цену из ladder
                return orders[0].get("price", trade.entry_price)

        # Пробуем найти entry zone
        entry = snapshot.get("entry", {})
        if entry:
            price_min = entry.get("price_min", 0)
            price_max = entry.get("price_max", 0)
            if price_min and price_max:
                return (price_min + price_max) / 2

        return trade.entry_price

    def _map_exit_reason(self, reason: Optional[str]) -> ExitReason:
        """Маппинг exit_reason из TradeRecord в ExitReason enum."""
        if not reason:
            return ExitReason.MANUAL

        reason_lower = reason.lower()

        mapping = {
            "tp": ExitReason.TP1,
            "tp1": ExitReason.TP1,
            "tp2": ExitReason.TP2,
            "tp3": ExitReason.TP3,
            "sl": ExitReason.SL,
            "manual": ExitReason.MANUAL,
            "timeout": ExitReason.TIMEOUT,
            "time_stop": ExitReason.TIMEOUT,
            "cancel": ExitReason.CANCEL,
            "cancelled": ExitReason.CANCEL,
            "liquidated": ExitReason.LIQUIDATION,
            "liquidation": ExitReason.LIQUIDATION,
            "breakeven": ExitReason.BREAKEVEN,
        }

        return mapping.get(reason_lower, ExitReason.MANUAL)

    def _determine_label(self, trade: TradeRecord) -> TradeLabel:
        """Определить label сделки."""
        # Используем outcome если есть
        if trade.outcome:
            outcome_lower = trade.outcome.lower()
            if outcome_lower == "win":
                return TradeLabel.WIN
            elif outcome_lower == "loss":
                return TradeLabel.LOSS
            elif outcome_lower == "breakeven":
                return TradeLabel.BREAKEVEN

        # Определяем по pnl
        pnl = trade.pnl_usd or 0
        if pnl > 0:
            return TradeLabel.WIN
        elif pnl < 0:
            return TradeLabel.LOSS
        else:
            return TradeLabel.BREAKEVEN

    def _extract_factors(
        self,
        trade: TradeRecord,
        snapshot: Dict[str, Any]
    ) -> ScenarioFactors:
        """Извлечь факторы из сценария для атрибуции."""
        # Получаем market_context из snapshot
        context = snapshot.get("market_context", {})
        indicators = snapshot.get("indicators", {})
        key_levels = snapshot.get("key_levels", {})

        # Trend
        trend = context.get("trend", "sideways")
        if isinstance(trend, dict):
            trend = trend.get("direction", "sideways")

        # Bias
        bias = context.get("bias", "neutral")
        if trade.scenario_bias:
            bias = "bull" if trade.scenario_bias.lower() == "long" else "bear"

        # Volatility regime
        volatility = context.get("volatility", "normal")
        vol_regime = None
        if volatility:
            if isinstance(volatility, str):
                vol_lower = volatility.lower()
                if vol_lower in ("low", "normal", "high"):
                    vol_regime = VolatilityRegime(vol_lower)

        # EMA levels
        ema_levels = key_levels.get("ema_levels", {})

        return ScenarioFactors(
            trend=trend,
            bias=bias,
            fear_greed_index=context.get("fear_greed_index"),
            funding_rate=context.get("funding_rate"),
            long_short_ratio=context.get("long_short_ratio"),
            adx=indicators.get("adx"),
            rsi=indicators.get("rsi"),
            volatility_regime=vol_regime,
            atr_pct=indicators.get("atr_percent"),
            support_levels=key_levels.get("support", []),
            resistance_levels=key_levels.get("resistance", []),
            ema_20=ema_levels.get("ema_20"),
            ema_50=ema_levels.get("ema_50"),
            ema_200=ema_levels.get("ema_200"),
        )

    def _analyze_factor_contributions(
        self,
        trade: TradeRecord,
        factors: ScenarioFactors,
        label: TradeLabel
    ) -> Dict[str, float]:
        """
        Анализ вклада факторов в результат.
        Rule-based оценка.
        """
        contributions = {}

        # Trend alignment
        if factors.trend and factors.bias:
            is_aligned = (
                (factors.trend == "up" and factors.bias == "bull" and trade.side == "Long") or
                (factors.trend == "down" and factors.bias == "bear" and trade.side == "Short")
            )
            contributions["trend_alignment"] = 0.3 if is_aligned else -0.2

        # RSI extremes
        if factors.rsi:
            if factors.rsi < 30 and trade.side == "Long":
                contributions["rsi_oversold_long"] = 0.2 if label == TradeLabel.WIN else -0.1
            elif factors.rsi > 70 and trade.side == "Short":
                contributions["rsi_overbought_short"] = 0.2 if label == TradeLabel.WIN else -0.1

        # MAE analysis (SL placement)
        if trade.mae_r:
            if trade.mae_r > 1.5:  # Большая просадка
                contributions["sl_placement"] = -0.3
            elif trade.mae_r < 0.5:  # Маленькая просадка
                contributions["sl_placement"] = 0.1

        return contributions

    def _calculate_post_sl_mfe(self, trade: TradeRecord) -> Optional[float]:
        """
        Рассчитать MFE после SL.
        Показывает потенциальную прибыль если бы не сработал SL.
        """
        if trade.exit_reason != "sl":
            return None

        # Если есть post_sl анализ
        if trade.post_sl_price_1h or trade.post_sl_price_4h:
            post_price = trade.post_sl_price_4h or trade.post_sl_price_1h
            if post_price and trade.entry_price and trade.stop_price:
                risk = abs(trade.entry_price - trade.stop_price)
                if risk > 0:
                    if trade.side == "Long":
                        potential = post_price - trade.entry_price
                    else:
                        potential = trade.entry_price - post_price

                    return potential / risk if potential > 0 else None

        return None


# Singleton instance
feedback_collector = FeedbackCollector()
