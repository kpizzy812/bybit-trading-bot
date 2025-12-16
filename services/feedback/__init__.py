"""
Feedback Loop Module

Модуль для сбора и отправки телеметрии в Syntra AI.

4 слоя телеметрии:
- A) Scenario Snapshot (из TradeRecord.scenario_snapshot)
- B) Execution Report
- C) Outcome Report
- D) Attribution

Использование:
    from services.feedback import feedback_collector, feedback_client, feedback_queue

    # При закрытии позиции
    feedback = feedback_collector.collect(trade_record)
    try:
        await feedback_client.submit(feedback)
    except Exception:
        await feedback_queue.enqueue(feedback)
"""

from services.feedback.models import (
    # Enums
    ExitReason,
    TradeLabel,
    VolatilityRegime,

    # Layer B
    OrderFill,
    ExecutionReport,

    # Layer C
    OutcomeReport,

    # Layer D
    ScenarioFactors,
    Attribution,

    # Combined
    TradeFeedback,

    # Constants
    ARCHETYPE_TAGS,
)

__all__ = [
    # Enums
    "ExitReason",
    "TradeLabel",
    "VolatilityRegime",

    # Layer B
    "OrderFill",
    "ExecutionReport",

    # Layer C
    "OutcomeReport",

    # Layer D
    "ScenarioFactors",
    "Attribution",

    # Combined
    "TradeFeedback",

    # Constants
    "ARCHETYPE_TAGS",
]
