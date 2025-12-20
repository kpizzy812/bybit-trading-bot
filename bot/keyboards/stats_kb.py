"""
Stats Inline Keyboards

Клавиатуры для Stats API интерфейса.
Согласно плану: main menu, period switcher, archetype pagination.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Optional


# =============================================================================
# Constants
# =============================================================================

PERIODS = ["7d", "30d", "90d", "180d"]
DEFAULT_PERIOD = "90d"
ARCHETYPES_PER_PAGE = 5


# =============================================================================
# Main Menu
# =============================================================================

def get_stats_menu_kb(current_period: str = DEFAULT_PERIOD) -> InlineKeyboardMarkup:
    """
    Главное меню статистики.

    📊 Stats Menu
    ├── [📈 Overview]  [📉 Outcomes]
    ├── [🎯 Archetypes] [📊 Funnel]
    ├── [🔬 EV Gates]
    ├── [⏰ 7d] [30d] [90d] [180d]
    └── [◀️ Назад]
    """
    builder = InlineKeyboardBuilder()

    # Row 1: Main actions
    builder.row(
        InlineKeyboardButton(text="📈 Overview", callback_data="stats:overview"),
        InlineKeyboardButton(text="📉 Outcomes", callback_data="stats:outcomes")
    )

    # Row 2: Learning stats
    builder.row(
        InlineKeyboardButton(text="🎯 Archetypes", callback_data="stats:arch:page:0"),
        InlineKeyboardButton(text="📊 Funnel", callback_data="stats:funnel")
    )

    # Row 3: Gates
    builder.row(
        InlineKeyboardButton(text="🔬 EV Gates", callback_data="stats:gates")
    )

    # Row 4: Period switcher
    period_buttons = []
    for period in PERIODS:
        text = f"[{period}]" if period == current_period else period
        period_buttons.append(
            InlineKeyboardButton(text=text, callback_data=f"stats:period:{period}")
        )
    builder.row(*period_buttons)

    # Row 5: Back
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="show_settings_menu")
    )

    return builder.as_markup()


# =============================================================================
# Overview Screen
# =============================================================================

def get_overview_kb(current_period: str = DEFAULT_PERIOD) -> InlineKeyboardMarkup:
    """
    Клавиатура для Overview screen.

    [🔄 Refresh] [⏰ Period]
    [◀️ Menu]
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="🔄 Refresh", callback_data="stats:overview"),
        InlineKeyboardButton(text=f"⏰ {current_period}", callback_data="stats:period_menu")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Menu", callback_data="stats:menu")
    )

    return builder.as_markup()


# =============================================================================
# Outcomes Screen
# =============================================================================

def get_outcomes_kb(current_period: str = DEFAULT_PERIOD) -> InlineKeyboardMarkup:
    """
    Клавиатура для Outcomes screen.
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="🔄 Refresh", callback_data="stats:outcomes"),
        InlineKeyboardButton(text=f"⏰ {current_period}", callback_data="stats:period_menu")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Menu", callback_data="stats:menu")
    )

    return builder.as_markup()


# =============================================================================
# Archetypes List (Paginated)
# =============================================================================

def get_archetypes_list_kb(
    archetypes: List[str],
    page: int,
    total_pages: int,
    current_period: str = DEFAULT_PERIOD
) -> InlineKeyboardMarkup:
    """
    Клавиатура для списка архетипов с пагинацией.

    [◀️ Prev] [1] [2] [3] [Next ▶️]
    [🔍 archetype1] [🔍 archetype2]
    [🔄 Refresh] [◀️ Menu]
    """
    builder = InlineKeyboardBuilder()

    # Archetype detail buttons (max 5)
    for arch in archetypes[:ARCHETYPES_PER_PAGE]:
        short_name = arch[:18] if len(arch) > 18 else arch
        builder.button(
            text=f"🔍 {short_name}",
            callback_data=f"stats:arch:detail:{arch[:40]}"
        )
    builder.adjust(2)  # 2 per row

    # Pagination row
    pagination_buttons = []

    if page > 0:
        pagination_buttons.append(
            InlineKeyboardButton(text="◀️", callback_data=f"stats:arch:page:{page - 1}")
        )

    # Page numbers (show max 5)
    start_page = max(0, page - 2)
    end_page = min(total_pages, start_page + 5)

    for i in range(start_page, end_page):
        text = f"[{i + 1}]" if i == page else str(i + 1)
        pagination_buttons.append(
            InlineKeyboardButton(text=text, callback_data=f"stats:arch:page:{i}")
        )

    if page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(text="▶️", callback_data=f"stats:arch:page:{page + 1}")
        )

    if pagination_buttons:
        builder.row(*pagination_buttons[:7])  # Max 7 buttons

    # Control buttons
    builder.row(
        InlineKeyboardButton(text="🔄 Refresh", callback_data=f"stats:arch:page:{page}"),
        InlineKeyboardButton(text="◀️ Menu", callback_data="stats:menu")
    )

    return builder.as_markup()


# =============================================================================
# Archetype Detail
# =============================================================================

def get_archetype_detail_kb(
    archetype: str,
    current_period: str = DEFAULT_PERIOD
) -> InlineKeyboardMarkup:
    """
    Клавиатура для детального просмотра архетипа.

    [◀️ Back] [🔄 Refresh]
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="◀️ Back", callback_data="stats:arch:page:0"),
        InlineKeyboardButton(text="🔄 Refresh", callback_data=f"stats:arch:detail:{archetype[:40]}")
    )

    return builder.as_markup()


# =============================================================================
# Funnel Screen
# =============================================================================

def get_funnel_kb(current_period: str = DEFAULT_PERIOD) -> InlineKeyboardMarkup:
    """
    Клавиатура для Conversion Funnel screen.
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="🔄 Refresh", callback_data="stats:funnel"),
        InlineKeyboardButton(text=f"⏰ {current_period}", callback_data="stats:period_menu")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Menu", callback_data="stats:menu")
    )

    return builder.as_markup()


# =============================================================================
# Gates Screen
# =============================================================================

def get_gates_kb() -> InlineKeyboardMarkup:
    """
    Клавиатура для EV Gates screen.
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="🔄 Refresh", callback_data="stats:gates")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Menu", callback_data="stats:menu")
    )

    return builder.as_markup()


# =============================================================================
# Period Selector
# =============================================================================

def get_period_menu_kb(current_period: str, return_to: str = "stats:menu") -> InlineKeyboardMarkup:
    """
    Меню выбора периода.

    [7d] [30d] [90d] [180d]
    [◀️ Back]
    """
    builder = InlineKeyboardBuilder()

    # Period buttons
    period_buttons = []
    for period in PERIODS:
        text = f"✅ {period}" if period == current_period else period
        period_buttons.append(
            InlineKeyboardButton(text=text, callback_data=f"stats:period:{period}")
        )
    builder.row(*period_buttons)

    # Back
    builder.row(
        InlineKeyboardButton(text="◀️ Back", callback_data=return_to)
    )

    return builder.as_markup()


# =============================================================================
# Error / Loading
# =============================================================================

def get_error_kb(retry_callback: str = "stats:menu") -> InlineKeyboardMarkup:
    """
    Клавиатура при ошибке.
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="🔄 Retry", callback_data=retry_callback),
        InlineKeyboardButton(text="◀️ Menu", callback_data="stats:menu")
    )

    return builder.as_markup()
