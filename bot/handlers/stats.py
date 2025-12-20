"""
Stats Handler

Inline UI для Trading Statistics из Syntra Stats API.
Согласно плану Phase 6.
"""
import html
from datetime import datetime
from typing import Optional, Dict, Any

from aiogram import Router, F
from aiogram.types import CallbackQuery
from loguru import logger

from bot.keyboards.stats_kb import (
    get_stats_menu_kb,
    get_overview_kb,
    get_outcomes_kb,
    get_archetypes_list_kb,
    get_archetype_detail_kb,
    get_funnel_kb,
    get_gates_kb,
    get_period_menu_kb,
    get_error_kb,
    DEFAULT_PERIOD,
    ARCHETYPES_PER_PAGE,
)
from services.stats_client import get_stats_client, StatsServiceUnavailable, StatsClientError

router = Router()


# =============================================================================
# State (simple in-memory period per user)
# =============================================================================

_user_periods: Dict[int, str] = {}


def get_user_period(user_id: int) -> str:
    """Get current period for user."""
    return _user_periods.get(user_id, DEFAULT_PERIOD)


def set_user_period(user_id: int, period: str):
    """Set period for user."""
    _user_periods[user_id] = period


# =============================================================================
# Formatting Helpers
# =============================================================================

def format_date_range(from_ts: Optional[int], to_ts: Optional[int]) -> str:
    """Format date range from timestamps."""
    if not from_ts or not to_ts:
        return ""
    from_dt = datetime.fromtimestamp(from_ts)
    to_dt = datetime.fromtimestamp(to_ts)
    return f"{from_dt.strftime('%b %d, %Y')} - {to_dt.strftime('%b %d, %Y')}"


def format_ci(ci: Optional[Dict], is_percent: bool = True) -> str:
    """Format confidence interval."""
    if not ci:
        return ""
    lower = ci.get("lower") or 0
    upper = ci.get("upper") or 0
    if is_percent:
        return f"({lower*100:.0f}-{upper*100:.0f}%)"
    return f"({lower:.2f}-{upper:.2f})"


def format_winrate_emoji(winrate: float) -> str:
    """Get emoji for winrate."""
    if winrate >= 0.6:
        return "✅"
    elif winrate >= 0.5:
        return "🟡"
    else:
        return "🔴"


def format_ev_emoji(ev: float) -> str:
    """Get emoji for expectancy."""
    if ev >= 0.2:
        return "✅"
    elif ev >= 0:
        return "🟢"
    elif ev >= -0.1:
        return "🟡"
    else:
        return "🔴"


def format_gate_status(status: str) -> str:
    """Format gate status with emoji."""
    status_map = {
        "enabled": "✅ ENABLED",
        "warning": "🟡 WARNING",
        "disabled": "🔴 DISABLED",
        "no_data": "🔘 NO DATA",
    }
    return status_map.get(status, status)


# =============================================================================
# HANDLERS: Menu
# =============================================================================

@router.callback_query(F.data == "show_stats_menu")
async def show_stats_menu(callback: CallbackQuery):
    """Показать меню Stats из настроек."""
    await callback.answer()

    user_id = callback.from_user.id
    period = get_user_period(user_id)

    text = """
📊 <b>Trading Statistics</b>

Статистика торговли из Syntra AI.

<b>Sections:</b>
• <b>Overview</b> - ключевые метрики (WR, EV, PF)
• <b>Outcomes</b> - распределение выходов
• <b>Archetypes</b> - статистика по паттернам
• <b>Funnel</b> - воронка конверсии
• <b>EV Gates</b> - статус EV гейтов

Выбери раздел:
"""

    await callback.message.edit_text(
        text.strip(),
        parse_mode="HTML",
        reply_markup=get_stats_menu_kb(period)
    )


@router.callback_query(F.data == "stats:menu")
async def stats_menu(callback: CallbackQuery):
    """Вернуться в меню Stats."""
    await show_stats_menu(callback)


# =============================================================================
# HANDLERS: Period
# =============================================================================

@router.callback_query(F.data.startswith("stats:period:"))
async def set_period(callback: CallbackQuery):
    """Установить период."""
    period = callback.data.replace("stats:period:", "")

    if period not in ["7d", "30d", "90d", "180d"]:
        await callback.answer("Invalid period", show_alert=True)
        return

    user_id = callback.from_user.id
    set_user_period(user_id, period)

    await callback.answer(f"Period: {period}")
    await show_stats_menu(callback)


@router.callback_query(F.data == "stats:period_menu")
async def show_period_menu(callback: CallbackQuery):
    """Показать меню выбора периода."""
    await callback.answer()

    user_id = callback.from_user.id
    period = get_user_period(user_id)

    text = "⏰ <b>Select Period</b>\n\nВыбери период для статистики:"

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_period_menu_kb(period)
    )


# =============================================================================
# HANDLERS: Overview
# =============================================================================

@router.callback_query(F.data == "stats:overview")
async def show_overview(callback: CallbackQuery):
    """Показать Trading Overview."""
    await callback.answer("📊 Loading...")

    user_id = callback.from_user.id
    period = get_user_period(user_id)

    try:
        client = get_stats_client()
        data = await client.get_trading_overview(period=period)

        if not data:
            await callback.message.edit_text(
                "📊 <b>Trading Statistics</b>\n\n"
                "Нет данных за выбранный период.",
                parse_mode="HTML",
                reply_markup=get_overview_kb(period)
            )
            return

        # Extract data (с защитой от None)
        sample_size = data.get("sample_size") or 0
        winrate = data.get("winrate") or 0
        winrate_ci = data.get("winrate_ci")
        expectancy_r = data.get("expectancy_r") or 0
        profit_factor = data.get("profit_factor")
        net_pnl = data.get("net_pnl_usd") or 0
        fees = data.get("fees_usd") or 0
        avg_mae = data.get("avg_mae_r") or 0
        avg_mfe = data.get("avg_mfe_r") or 0
        max_dd = data.get("max_drawdown_r") or 0
        streaks = data.get("streaks") or {}
        by_origin = data.get("by_origin") or {}
        from_ts = data.get("from_ts")
        to_ts = data.get("to_ts")

        # Format
        date_range = format_date_range(from_ts, to_ts)
        wr_emoji = format_winrate_emoji(winrate)
        wr_ci_str = format_ci(winrate_ci)
        pf_str = f"{profit_factor:.2f}" if profit_factor else "-"

        # AI vs Manual
        ai_stats = by_origin.get("ai_scenario", {})
        manual_stats = by_origin.get("manual", {})

        text = f"""
📊 <b>Trading Statistics ({period})</b>
📅 {date_range}

🎯 <b>Key Metrics</b> (n={sample_size}):
├ WR: {winrate*100:.0f}% {wr_ci_str} {wr_emoji}
├ Expectancy: {expectancy_r:+.2f}R/trade
├ Profit Factor: {pf_str}
└ Net PnL: ${net_pnl:+,.0f}

📉 <b>Risk:</b>
├ Avg MAE: {avg_mae:.2f}R
├ Avg MFE: {avg_mfe:.2f}R
└ Max DD: {max_dd:.1f}R

🔥 <b>Streaks:</b> {streaks.get('max_win', 0)}W / {streaks.get('max_loss', 0)}L (current: {streaks.get('current', 0):+d})
"""

        if ai_stats or manual_stats:
            ai_count = ai_stats.get("count") or 0
            ai_wr = ai_stats.get("winrate") or 0
            ai_ev = ai_stats.get("expectancy_r") or 0
            manual_count = manual_stats.get("count") or 0
            manual_wr = manual_stats.get("winrate") or 0
            manual_ev = manual_stats.get("expectancy_r") or 0

            ai_emoji = "✅" if ai_ev > manual_ev else ""
            manual_emoji = "✅" if manual_ev > ai_ev else ""

            text += f"""
🤖 <b>AI vs Manual:</b>
├ AI: {ai_count} trades, {ai_wr*100:.0f}% WR, {ai_ev:+.2f}R {ai_emoji}
└ Manual: {manual_count} trades, {manual_wr*100:.0f}% WR, {manual_ev:+.2f}R {manual_emoji}
"""

        # Warnings
        warnings = data.get("warnings", [])
        if warnings:
            text += f"\n⚠️ {', '.join(warnings)}"

        await callback.message.edit_text(
            text.strip(),
            parse_mode="HTML",
            reply_markup=get_overview_kb(period)
        )

    except StatsServiceUnavailable as e:
        logger.warning(f"Stats service unavailable: {e}")
        await callback.message.edit_text(
            "📊 <b>Trading Statistics</b>\n\n"
            "⚠️ Stats service temporarily unavailable.\n"
            "Try again later.",
            parse_mode="HTML",
            reply_markup=get_error_kb("stats:overview")
        )
    except Exception as e:
        logger.error(f"Error in show_overview: {e}")
        await callback.message.edit_text(
            f"❌ Error: {html.escape(str(e)[:100])}",
            parse_mode="HTML",
            reply_markup=get_error_kb("stats:overview")
        )


# =============================================================================
# HANDLERS: Outcomes
# =============================================================================

@router.callback_query(F.data == "stats:outcomes")
async def show_outcomes(callback: CallbackQuery):
    """Показать Outcomes Distribution."""
    await callback.answer("📉 Loading...")

    user_id = callback.from_user.id
    period = get_user_period(user_id)

    try:
        client = get_stats_client()
        data = await client.get_outcomes(period=period)

        if not data:
            await callback.message.edit_text(
                "📉 <b>Exit Distribution</b>\n\n"
                "Нет данных за выбранный период.",
                parse_mode="HTML",
                reply_markup=get_outcomes_kb(period)
            )
            return

        sample_size = data.get("sample_size") or 0
        distribution = data.get("distribution") or {}
        hit_rates = data.get("hit_rates") or {}
        from_ts = data.get("from_ts")
        to_ts = data.get("to_ts")

        date_range = format_date_range(from_ts, to_ts)

        # Outcome type formatting
        outcome_emojis = {
            "sl_early": "🔴",
            "be_after_tp1": "🟡",
            "stop_in_profit": "🟢",
            "tp1_final": "✅",
            "tp2_final": "✅",
            "tp3_final": "✅",
            "manual_close": "⚪",
            "liquidation": "💀",
            "other": "⚪",
        }

        outcome_labels = {
            "sl_early": "SL Early",
            "be_after_tp1": "BE after TP1",
            "stop_in_profit": "Stop in Profit",
            "tp1_final": "TP1 Final",
            "tp2_final": "TP2 Final",
            "tp3_final": "TP3 Final",
            "manual_close": "Manual Close",
            "liquidation": "Liquidation",
            "other": "Other",
        }

        text = f"""
📉 <b>Exit Distribution ({period})</b>
📅 {date_range} | n={sample_size}

<b>Terminal Outcomes:</b>
"""

        for outcome_type, label in outcome_labels.items():
            stats = distribution.get(outcome_type) or {}
            count = stats.get("count") or 0
            pct = stats.get("pct") or 0
            avg_r = stats.get("avg_r")

            if count > 0:
                emoji = outcome_emojis.get(outcome_type, "⚪")
                avg_r_str = f"avg {avg_r:+.1f}R" if avg_r is not None else ""
                text += f"├ {emoji} {label}: {count} ({pct*100:.0f}%) {avg_r_str}\n"

        # TP Hit Rates
        tp1_rate = hit_rates.get("tp1")
        tp2_rate = hit_rates.get("tp2")
        tp3_rate = hit_rates.get("tp3")

        if tp1_rate is not None:
            tp1_pct = (tp1_rate or 0) * 100
            tp2_pct = (tp2_rate or 0) * 100
            tp3_pct = (tp3_rate or 0) * 100
            text += f"""
<b>TP Hit Rates:</b>
├ TP1: {tp1_pct:.0f}% reached
├ TP2: {tp2_pct:.0f}%
└ TP3: {tp3_pct:.0f}%
"""

        await callback.message.edit_text(
            text.strip(),
            parse_mode="HTML",
            reply_markup=get_outcomes_kb(period)
        )

    except StatsServiceUnavailable as e:
        logger.warning(f"Stats service unavailable: {e}")
        await callback.message.edit_text(
            "📉 <b>Exit Distribution</b>\n\n"
            "⚠️ Stats service temporarily unavailable.",
            parse_mode="HTML",
            reply_markup=get_error_kb("stats:outcomes")
        )
    except Exception as e:
        logger.error(f"Error in show_outcomes: {e}")
        await callback.message.edit_text(
            f"❌ Error: {html.escape(str(e)[:100])}",
            parse_mode="HTML",
            reply_markup=get_error_kb("stats:outcomes")
        )


# =============================================================================
# HANDLERS: Archetypes List
# =============================================================================

@router.callback_query(F.data.startswith("stats:arch:page:"))
async def show_archetypes_list(callback: CallbackQuery):
    """Показать список архетипов с пагинацией."""
    page_str = callback.data.replace("stats:arch:page:", "")

    try:
        page = int(page_str)
    except ValueError:
        page = 0

    await callback.answer("🎯 Loading...")

    user_id = callback.from_user.id
    period = get_user_period(user_id)

    try:
        client = get_stats_client()
        data = await client.get_archetypes(
            period=period,
            page=page,
            page_size=ARCHETYPES_PER_PAGE
        )

        if not data:
            await callback.message.edit_text(
                "🎯 <b>Archetypes</b>\n\n"
                "Нет данных за выбранный период.",
                parse_mode="HTML",
                reply_markup=get_archetypes_list_kb([], 0, 0, period)
            )
            return

        archetypes_data = data.get("archetypes") or []
        total = data.get("total") or 0
        total_pages = (total + ARCHETYPES_PER_PAGE - 1) // ARCHETYPES_PER_PAGE

        if not archetypes_data:
            await callback.message.edit_text(
                f"🎯 <b>Archetypes ({period})</b>\n\n"
                "Нет архетипов с достаточным количеством сделок.",
                parse_mode="HTML",
                reply_markup=get_archetypes_list_kb([], 0, 0, period)
            )
            return

        text = f"🎯 <b>Archetypes ({period})</b> [{page + 1}/{total_pages}]\n\n"

        archetype_names = []
        for arch in archetypes_data:
            name = arch.get("archetype") or "unknown"
            sample_size = arch.get("sample_size") or 0
            winrate = arch.get("winrate") or 0
            expectancy = arch.get("expectancy_r") or 0
            profit_factor = arch.get("profit_factor")
            gate_status = arch.get("gate_status") or "enabled"

            archetype_names.append(name)

            # Gate status emoji
            if gate_status == "enabled":
                status_emoji = "✅"
            elif gate_status == "warning":
                status_emoji = "⚠️"
            else:
                status_emoji = "🚫"

            pf_str = f"{profit_factor:.1f}" if profit_factor else "-"

            text += f"{status_emoji} <code>{html.escape(name[:25])}</code> (n={sample_size})\n"
            text += f"   WR: {winrate*100:.0f}% | EV: {expectancy:+.2f}R | PF: {pf_str}\n\n"

        await callback.message.edit_text(
            text.strip(),
            parse_mode="HTML",
            reply_markup=get_archetypes_list_kb(archetype_names, page, total_pages, period)
        )

    except StatsServiceUnavailable as e:
        logger.warning(f"Stats service unavailable: {e}")
        await callback.message.edit_text(
            "🎯 <b>Archetypes</b>\n\n"
            "⚠️ Stats service temporarily unavailable.",
            parse_mode="HTML",
            reply_markup=get_error_kb(f"stats:arch:page:{page}")
        )
    except Exception as e:
        logger.error(f"Error in show_archetypes_list: {e}")
        await callback.message.edit_text(
            f"❌ Error: {html.escape(str(e)[:100])}",
            parse_mode="HTML",
            reply_markup=get_error_kb(f"stats:arch:page:{page}")
        )


# =============================================================================
# HANDLERS: Archetype Detail
# =============================================================================

@router.callback_query(F.data.startswith("stats:arch:detail:"))
async def show_archetype_detail(callback: CallbackQuery):
    """Показать детальную статистику архетипа."""
    archetype = callback.data.replace("stats:arch:detail:", "")

    await callback.answer("🔍 Loading...")

    user_id = callback.from_user.id
    period = get_user_period(user_id)

    try:
        client = get_stats_client()
        data = await client.get_archetype_detail(archetype=archetype, period=period)

        if not data:
            await callback.message.edit_text(
                f"🎯 <b>{html.escape(archetype)}</b>\n\n"
                "Нет данных для этого архетипа.",
                parse_mode="HTML",
                reply_markup=get_archetype_detail_kb(archetype, period)
            )
            return

        sample_size = data.get("sample_size") or 0
        winrate = data.get("winrate") or 0
        winrate_ci = data.get("winrate_ci")
        expectancy = data.get("expectancy_r") or 0
        expectancy_ci = data.get("expectancy_ci")
        profit_factor = data.get("profit_factor")
        max_dd = data.get("max_drawdown_r") or 0
        gate_status = data.get("gate_status") or "enabled"
        gate_reason = data.get("gate_reason")
        paper = data.get("paper") or {}
        conversion_rate = data.get("conversion_rate") or 0
        outcomes = data.get("outcomes") or {}

        wr_ci_str = format_ci(winrate_ci)
        ev_ci_str = format_ci(expectancy_ci, is_percent=False)
        pf_str = f"{profit_factor:.1f}" if profit_factor else "-"
        gate_str = format_gate_status(gate_status)

        text = f"""
🎯 <b>{html.escape(archetype)}</b>
📅 {period} | n={sample_size}

📊 <b>Metrics:</b>
├ WR: {winrate*100:.0f}% {wr_ci_str}
├ EV: {expectancy:+.2f}R {ev_ci_str}
├ PF: {pf_str}
└ Max DD: {max_dd:.1f}R
"""

        # Paper comparison
        if paper:
            paper_n = paper.get("sample_size") or 0
            paper_wr = paper.get("winrate") or 0
            paper_ev = paper.get("expectancy_r") or 0
            text += f"""
📈 <b>Paper Comparison:</b>
├ Paper: n={paper_n}, WR {paper_wr*100:.0f}%, EV {paper_ev:+.2f}R
└ Conversion: {conversion_rate*100:.0f}%
"""

        # Gate status
        text += f"\n🚦 <b>Gate:</b> {gate_str}"
        if gate_reason:
            text += f"\n   <i>{html.escape(gate_reason)}</i>"

        # Outcomes breakdown
        if outcomes:
            text += "\n\n📉 <b>Outcomes:</b>\n"
            for outcome, pct in outcomes.items():
                if pct and pct > 0:
                    emoji = "🔴" if outcome == "sl_early" else "✅" if outcome.startswith("tp") else "⚪"
                    text += f"├ {emoji} {outcome}: {pct*100:.0f}%\n"

        await callback.message.edit_text(
            text.strip(),
            parse_mode="HTML",
            reply_markup=get_archetype_detail_kb(archetype, period)
        )

    except StatsServiceUnavailable as e:
        logger.warning(f"Stats service unavailable: {e}")
        await callback.message.edit_text(
            f"🎯 <b>{html.escape(archetype)}</b>\n\n"
            "⚠️ Stats service temporarily unavailable.",
            parse_mode="HTML",
            reply_markup=get_error_kb(f"stats:arch:detail:{archetype}")
        )
    except Exception as e:
        logger.error(f"Error in show_archetype_detail: {e}")
        await callback.message.edit_text(
            f"❌ Error: {html.escape(str(e)[:100])}",
            parse_mode="HTML",
            reply_markup=get_error_kb(f"stats:arch:detail:{archetype}")
        )


# =============================================================================
# HANDLERS: Funnel
# =============================================================================

@router.callback_query(F.data == "stats:funnel")
async def show_funnel(callback: CallbackQuery):
    """Показать Conversion Funnel."""
    await callback.answer("📊 Loading...")

    user_id = callback.from_user.id
    period = get_user_period(user_id)

    try:
        client = get_stats_client()
        data = await client.get_funnel(period=period)

        if not data:
            await callback.message.edit_text(
                "📊 <b>Conversion Funnel</b>\n\n"
                "Нет данных за выбранный период.",
                parse_mode="HTML",
                reply_markup=get_funnel_kb(period)
            )
            return

        stages = data.get("stages") or {}
        dropoff = data.get("dropoff") or {}
        by_archetype = data.get("by_archetype") or []
        from_ts = data.get("from_ts")
        to_ts = data.get("to_ts")

        date_range = format_date_range(from_ts, to_ts)

        # Stage data (с защитой от None)
        generated = stages.get("generated") or {}
        viewed = stages.get("viewed") or {}
        selected = stages.get("selected") or {}
        placed = stages.get("placed") or {}
        closed = stages.get("closed") or {}

        gen_count = generated.get("count") or 0

        # Visual funnel (using block chars)
        def bar(pct: float, max_width: int = 16) -> str:
            filled = int(pct * max_width)
            return "█" * filled + "░" * (max_width - filled)

        # Extract values with None protection
        viewed_count = viewed.get('count') or 0
        viewed_pct = viewed.get('pct') or 0
        selected_count = selected.get('count') or 0
        selected_pct = selected.get('pct') or 0
        placed_count = placed.get('count') or 0
        placed_pct = placed.get('pct') or 0
        closed_count = closed.get('count') or 0
        closed_pct = closed.get('pct') or 0

        drop_gen_view = (dropoff.get('generated_to_viewed') or 0) * 100
        drop_view_sel = (dropoff.get('viewed_to_selected') or 0) * 100
        drop_sel_place = (dropoff.get('selected_to_placed') or 0) * 100
        drop_place_close = (dropoff.get('placed_to_closed') or 0) * 100

        text = f"""
📊 <b>Conversion Funnel ({period})</b>
📅 {date_range}

Generated:  {gen_count:>4} {bar(1.0)} 100%
   ↓ -{drop_gen_view:.0f}%
Viewed:     {viewed_count:>4} {bar(viewed_pct)} {viewed_pct*100:.0f}%
   ↓ -{drop_view_sel:.0f}%
Selected:   {selected_count:>4} {bar(selected_pct)} {selected_pct*100:.0f}%
   ↓ -{drop_sel_place:.0f}%
Placed:     {placed_count:>4} {bar(placed_pct)} {placed_pct*100:.0f}%
   ↓ -{drop_place_close:.0f}%
Closed:     {closed_count:>4} {bar(closed_pct)} {closed_pct*100:.0f}%
"""

        # Top converting archetypes
        if by_archetype:
            text += "\n🔝 <b>Top Converting:</b>\n"
            for arch in by_archetype[:3]:
                name = (arch.get("archetype") or "")[:15]
                rate = arch.get("conversion_rate") or 0
                text += f"├ {name}: {rate*100:.0f}%\n"

        await callback.message.edit_text(
            text.strip(),
            parse_mode="HTML",
            reply_markup=get_funnel_kb(period)
        )

    except StatsServiceUnavailable as e:
        logger.warning(f"Stats service unavailable: {e}")
        await callback.message.edit_text(
            "📊 <b>Conversion Funnel</b>\n\n"
            "⚠️ Stats service temporarily unavailable.",
            parse_mode="HTML",
            reply_markup=get_error_kb("stats:funnel")
        )
    except Exception as e:
        logger.error(f"Error in show_funnel: {e}")
        await callback.message.edit_text(
            f"❌ Error: {html.escape(str(e)[:100])}",
            parse_mode="HTML",
            reply_markup=get_error_kb("stats:funnel")
        )


# =============================================================================
# HANDLERS: Gates
# =============================================================================

@router.callback_query(F.data == "stats:gates")
async def show_gates(callback: CallbackQuery):
    """Показать EV Gates Status."""
    await callback.answer("🔬 Loading...")

    try:
        client = get_stats_client()
        data = await client.get_gates()

        if not data:
            await callback.message.edit_text(
                "🔬 <b>EV Gates</b>\n\n"
                "Нет данных о гейтах.",
                parse_mode="HTML",
                reply_markup=get_gates_kb()
            )
            return

        text = "🔬 <b>EV Gates Status</b>\n\n"

        # Group by status
        enabled = []
        warning = []
        disabled = []

        for gate in data:
            name = gate.get("archetype") or "unknown"
            status = gate.get("status") or "enabled"
            real_ev = gate.get("real_ev") or 0
            sample_size = gate.get("sample_size") or 0

            entry = f"<code>{html.escape(name[:20])}</code> EV:{real_ev:+.2f}R n={sample_size}"

            if status == "enabled":
                enabled.append(entry)
            elif status == "warning":
                warning.append(entry)
            else:
                disabled.append(entry)

        if enabled:
            text += "<b>✅ Enabled:</b>\n"
            for e in enabled[:5]:
                text += f"├ {e}\n"

        if warning:
            text += "\n<b>🟡 Warning:</b>\n"
            for w in warning[:5]:
                text += f"├ {w}\n"

        if disabled:
            text += "\n<b>🔴 Disabled:</b>\n"
            for d in disabled[:5]:
                text += f"├ {d}\n"

        if not enabled and not warning and not disabled:
            text += "Нет активных гейтов."

        await callback.message.edit_text(
            text.strip(),
            parse_mode="HTML",
            reply_markup=get_gates_kb()
        )

    except StatsServiceUnavailable as e:
        logger.warning(f"Stats service unavailable: {e}")
        await callback.message.edit_text(
            "🔬 <b>EV Gates</b>\n\n"
            "⚠️ Stats service temporarily unavailable.",
            parse_mode="HTML",
            reply_markup=get_error_kb("stats:gates")
        )
    except Exception as e:
        logger.error(f"Error in show_gates: {e}")
        await callback.message.edit_text(
            f"❌ Error: {html.escape(str(e)[:100])}",
            parse_mode="HTML",
            reply_markup=get_error_kb("stats:gates")
        )
