"""
Trading Modes - Prompt Builder

Генерация MODE PROFILE блока для LLM промптов.
Включает mode_notes в output schema для валидации.
"""
from typing import Optional
from loguru import logger

from services.trading_modes.models import ModeConfig
from services.trading_modes.registry import get_mode_or_default


class ModePromptBuilder:
    """
    Генератор mode-specific контекста для LLM промптов.

    Создаёт MODE PROFILE блок с:
    - Leverage bands
    - SL ATR bands
    - Mode-specific rules
    - Required mode_notes в output
    """

    def __init__(self, mode: Optional[ModeConfig] = None):
        """
        Args:
            mode: Конфигурация режима или None для default
        """
        self.mode = mode or get_mode_or_default(None)

    def build_mode_profile(self) -> str:
        """
        Сгенерировать MODE PROFILE блок для системного промпта.

        Returns:
            Строка с mode profile для вставки в промпт
        """
        mode = self.mode

        profile = f"""
=== MODE PROFILE: {mode.name} ({mode.emoji}) ===

TRADING PARAMETERS:
- Mode ID: {mode.mode_id}
- Max Leverage: {mode.max_leverage}x
- Default Leverage: {mode.default_leverage}x
- Risk Multiplier Range: {mode.risk_multiplier_min} - {mode.risk_multiplier_max}
- SL Distance (ATR): {mode.sl_atr_min}x - {mode.sl_atr_max}x ATR
- Position Size Mult: {mode.position_size_mult}x
- Max Hold Time: {mode.max_hold_hours}h

MODE RULES:
{self._build_mode_rules()}

{self._build_mode_context()}

REQUIRED OUTPUT:
You MUST include "mode_notes" array in your JSON response with 2-4 brief notes
explaining how your analysis reflects the {mode.mode_id.upper()} mode parameters.
Example: ["Using {mode.max_leverage}x max leverage", "SL at {mode.sl_atr_min}-{mode.sl_atr_max}x ATR"]
"""
        return profile.strip()

    def _build_mode_rules(self) -> str:
        """Правила специфичные для режима."""
        mode = self.mode
        rules = []

        if mode.mode_id == "conservative":
            rules = [
                "- Only enter on STRONG support/resistance levels",
                "- Require multiple confirmations (structure + momentum + volume)",
                "- Prefer counter-trend setups near key levels",
                "- Tight stops to minimize risk",
                "- NO aggressive entries on breakouts",
            ]
        elif mode.mode_id == "standard":
            rules = [
                "- Balance between risk and reward",
                "- Standard confirmation requirements",
                "- Both trend-following and counter-trend allowed",
                "- ATR-based stop placement",
            ]
        elif mode.mode_id == "high_risk":
            rules = [
                "- TIGHT stops (0.8-1.5x ATR) to avoid liquidation cascade",
                "- Momentum-first entries preferred",
                "- Higher leverage requires stricter no-trade conditions",
                "- Invalidation must be VERY clear",
                "- Prefer volatile market conditions",
                "- Quick profit-taking recommended",
            ]
        elif mode.mode_id == "meme":
            rules = [
                "- Levels are UNRELIABLE for memecoins - treat as suggestions only",
                "- Use WIDE stops (2-5x ATR) as price often overshoots",
                "- Position size is automatically REDUCED",
                "- Momentum and hype matter more than technicals",
                "- Very short holding periods recommended",
                "- High funding rate = increased risk",
            ]

        return "\n".join(rules)

    def _build_mode_context(self) -> str:
        """Дополнительный контекст режима."""
        mode = self.mode

        context_parts = []

        # Trust levels
        if not mode.trust_levels:
            context_parts.append(
                "IMPORTANT: Do NOT rely heavily on support/resistance levels. "
                "They are often broken in this asset class."
            )

        # Aggressive entries
        if mode.aggressive_entries:
            context_parts.append(
                "AGGRESSIVE ENTRIES: Prefer momentum entries over waiting for "
                "perfect level tests. Quick decisive moves recommended."
            )

        # Symbol restrictions
        if mode.allowed_symbols:
            symbols = ", ".join(mode.allowed_symbols)
            context_parts.append(
                f"SYMBOL WHITELIST: Only these symbols allowed: {symbols}"
            )

        # Hold time
        if mode.max_hold_hours < 48:
            context_parts.append(
                f"SHORT HOLD: Target exit within {mode.max_hold_hours} hours. "
                "Avoid swing trade setups."
            )

        # Custom prompt context
        if mode.prompt_context:
            context_parts.append(mode.prompt_context)

        if context_parts:
            return "MODE CONTEXT:\n" + "\n\n".join(context_parts)
        return ""

    def get_mode_notes_schema(self) -> dict:
        """
        Получить JSON schema для mode_notes в output.

        Returns:
            Dict с schema для mode_notes field
        """
        return {
            "mode_notes": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 4,
                "description": (
                    f"Brief notes explaining how analysis reflects "
                    f"{self.mode.mode_id.upper()} mode. "
                    f"Include leverage, SL placement, entry style decisions."
                )
            }
        }

    def validate_mode_notes(self, mode_notes: list) -> tuple[bool, str]:
        """
        Валидация что LLM реально применил mode rules.

        Args:
            mode_notes: Список mode_notes из response

        Returns:
            (valid, reason)
        """
        if not mode_notes or len(mode_notes) < 2:
            return False, "mode_notes must have at least 2 items"

        mode = self.mode
        notes_text = " ".join(mode_notes).lower()

        # Проверяем что notes соответствуют режиму
        if mode.mode_id == "high_risk":
            # Должны упоминать tight stops или высокий leverage
            if "tight" not in notes_text and str(mode.max_leverage) not in notes_text:
                return False, "HIGH_RISK notes should mention tight stops or high leverage"

        elif mode.mode_id == "meme":
            # Должны упоминать wide stops или reduced size
            if "wide" not in notes_text and "reduced" not in notes_text:
                return False, "MEME notes should mention wide stops or reduced position"

        elif mode.mode_id == "conservative":
            # Должны упоминать confirmation или strong levels
            if "confirm" not in notes_text and "strong" not in notes_text:
                return False, "CONSERVATIVE notes should mention confirmations or strong levels"

        return True, "OK"

    def build_full_prompt_injection(self) -> str:
        """
        Полный блок для инъекции в системный промпт.

        Returns:
            Готовый блок для вставки в prompt
        """
        return f"""
{self.build_mode_profile()}

---
Remember: You MUST follow {self.mode.name} mode parameters exactly.
Your "mode_notes" MUST reflect how you applied these parameters.
---
"""


# Shortcuts

def get_mode_prompt_builder(mode_id: Optional[str] = None) -> ModePromptBuilder:
    """Создать ModePromptBuilder для указанного режима."""
    mode = get_mode_or_default(mode_id)
    return ModePromptBuilder(mode)


def build_mode_profile(mode_id: Optional[str] = None) -> str:
    """Shortcut для генерации mode profile."""
    return get_mode_prompt_builder(mode_id).build_mode_profile()


def get_mode_notes_schema(mode_id: Optional[str] = None) -> dict:
    """Shortcut для получения schema mode_notes."""
    return get_mode_prompt_builder(mode_id).get_mode_notes_schema()
