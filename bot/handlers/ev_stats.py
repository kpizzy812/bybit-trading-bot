"""
EV Stats Handler

Inline UI для Real EV статистики (раздел в настройках).
"""
import html
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from loguru import logger

from services.real_ev import (
    get_calculator,
    get_gate_checker,
    get_state_manager,
    GateStatus,
)

router = Router()


# ============================================================
# KEYBOARDS
# ============================================================

def get_ev_stats_menu_kb():
    """Главное меню EV Stats."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="ev:show_stats"),
        InlineKeyboardButton(text="🔍 Проверить", callback_data="ev:check_menu")
    )

    builder.row(
        InlineKeyboardButton(text="🚫 Disabled", callback_data="ev:show_disabled"),
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="show_settings_menu")
    )

    return builder.as_markup()


def get_ev_archetype_check_kb(archetypes: list):
    """Клавиатура выбора архетипа для проверки."""
    builder = InlineKeyboardBuilder()

    for arch in archetypes[:10]:
        builder.button(
            text=arch[:20],
            callback_data=f"ev:check:{arch}"
        )

    builder.adjust(2)

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="ev:menu")
    )

    return builder.as_markup()


def get_ev_check_result_kb(group_key: str, status: GateStatus):
    """Клавиатура после проверки."""
    builder = InlineKeyboardBuilder()

    if status in (GateStatus.BLOCK, GateStatus.SOFT_BLOCK):
        builder.row(
            InlineKeyboardButton(
                text="🔓 Enable 24h",
                callback_data=f"ev:enable:{group_key}"
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="🔒 Disable",
                callback_data=f"ev:disable:{group_key}"
            )
        )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="ev:menu")
    )

    return builder.as_markup()


# ============================================================
# HANDLERS
# ============================================================

@router.callback_query(F.data == "show_ev_stats")
async def show_ev_stats_menu(callback: CallbackQuery):
    """Показать меню EV Stats из настроек."""
    await callback.answer()

    text = """
📊 <b>Real EV Tracking</b>

Статистика реального Expected Value по закрытым сделкам.

<b>Что такое Real EV?</b>
Real EV = средний результат в R по закрытым сделкам.
Paper EV — теория, Real EV — реальность.

<b>Gate Policy:</b>
✅ ALLOWED — торговля разрешена
🟡 WARN — EV отрицательный
🟠 SOFT_BLOCK — рекомендуем skip
🔴 BLOCK — торговля запрещена
🔘 NO_DATA — недостаточно данных

Выбери действие:
"""

    await callback.message.edit_text(
        text.strip(),
        parse_mode="HTML",
        reply_markup=get_ev_stats_menu_kb()
    )


@router.callback_query(F.data == "ev:menu")
async def ev_back_to_menu(callback: CallbackQuery):
    """Вернуться в меню EV Stats."""
    await show_ev_stats_menu(callback)


@router.callback_query(F.data == "ev:show_stats")
async def ev_show_stats(callback: CallbackQuery):
    """Показать статистику."""
    await callback.answer()

    try:
        calculator = get_calculator()
        state_manager = get_state_manager()

        all_stats = await calculator.calculate_all_l1_stats()

        if not all_stats:
            text = (
                "📊 <b>Real EV Stats</b>\n\n"
                "Нет данных о закрытых сделках.\n"
                "Статистика появится после первых сделок."
            )
        else:
            sorted_stats = sorted(all_stats, key=lambda s: s.real_ev, reverse=True)

            text = "📊 <b>Real EV Stats (90d)</b>\n\n"

            for stats in sorted_stats:
                if stats.real_ev >= 0.1:
                    emoji = "✅"
                elif stats.real_ev >= 0:
                    emoji = "🟢"
                elif stats.real_ev >= -0.1:
                    emoji = "🟡"
                else:
                    emoji = "🔴"

                is_disabled = await state_manager.is_disabled(stats.group_key)
                disabled_mark = " 🚫" if is_disabled else ""

                arch_name = stats.group_key.split(":")[0][:18]
                text += f"{emoji} <code>{html.escape(arch_name)}</code>\n"
                text += f"   EV: {stats.real_ev:+.2f}R | n={stats.sample_size} | WR:{stats.winrate*100:.0f}%{disabled_mark}\n"

            # Paper vs Real Gap
            text += "\n📈 <b>Paper vs Real:</b>\n"
            for stats in sorted_stats[:3]:
                if stats.paper_ev_avg is not None and stats.ev_gap is not None:
                    arch_name = stats.group_key.split(":")[0][:12]
                    text += f"├ {arch_name}: {stats.paper_ev_avg:+.2f}→{stats.real_ev:+.2f}R\n"

        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="🔄 Обновить", callback_data="ev:show_stats")
        )
        builder.row(
            InlineKeyboardButton(text="◀️ Назад", callback_data="ev:menu")
        )

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )

    except Exception as e:
        logger.error(f"Error in ev_show_stats: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка: {html.escape(str(e))}",
            reply_markup=get_ev_stats_menu_kb()
        )


@router.callback_query(F.data == "ev:check_menu")
async def ev_check_menu(callback: CallbackQuery):
    """Меню выбора архетипа для проверки."""
    await callback.answer()

    try:
        calculator = get_calculator()
        all_stats = await calculator.calculate_all_l1_stats()

        if not all_stats:
            text = "🔍 <b>EV Check</b>\n\nНет данных для проверки."
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(text="◀️ Назад", callback_data="ev:menu")
            )
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=builder.as_markup()
            )
            return

        archetypes = [s.group_key.split(":")[0] for s in all_stats]

        text = "🔍 <b>EV Check</b>\n\nВыбери архетип для проверки:"

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_ev_archetype_check_kb(archetypes)
        )

    except Exception as e:
        logger.error(f"Error in ev_check_menu: {e}")
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("ev:check:"))
async def ev_check_archetype(callback: CallbackQuery):
    """Проверить конкретный архетип."""
    archetype = callback.data.replace("ev:check:", "")
    await callback.answer()

    try:
        gate_checker = get_gate_checker()
        result = await gate_checker.check(
            archetype=archetype,
            timeframe="4h",
            user_id=callback.from_user.id,
        )

        text = f"🔍 <b>EV Check:</b> {html.escape(archetype)}\n\n"

        # Fallback chain
        text += "<b>Fallback:</b>\n"
        for item in result.fallback_chain:
            mark = "✅" if item.meets_threshold else "❌"
            ev_str = f"{item.real_ev:+.2f}R" if item.real_ev is not None else "N/A"
            text += f"├ {item.level}: n={item.sample_size}, EV={ev_str} {mark}\n"

        # Status
        status_emoji = {
            GateStatus.ALLOWED: "✅",
            GateStatus.WARN: "🟡",
            GateStatus.SOFT_BLOCK: "🟠",
            GateStatus.BLOCK: "🔴",
            GateStatus.NO_DATA: "🔘",
        }
        emoji = status_emoji.get(result.status, "❓")

        text += f"\n<b>Status:</b> {emoji} {result.status.value}\n"

        if result.stats:
            s = result.stats
            text += f"<b>Real EV:</b> {s.real_ev:+.2f}R\n"
            if s.rolling_ev is not None:
                text += f"<b>Rolling:</b> {s.rolling_ev:+.2f}R\n"
            text += f"<b>Winrate:</b> {s.winrate*100:.0f}%\n"

        if result.message:
            text += f"\n{html.escape(result.message)}"

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_ev_check_result_kb(
                result.selected_key or archetype,
                result.status
            )
        )

    except Exception as e:
        logger.error(f"Error in ev_check_archetype: {e}")
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data == "ev:show_disabled")
async def ev_show_disabled(callback: CallbackQuery):
    """Показать отключенные группы."""
    await callback.answer()

    try:
        state_manager = get_state_manager()
        disabled = await state_manager.get_all_disabled()

        builder = InlineKeyboardBuilder()

        if not disabled:
            text = "🚫 <b>Disabled Groups</b>\n\nНет отключенных групп."
        else:
            text = f"🚫 <b>Disabled Groups ({len(disabled)})</b>\n\n"
            for g in disabled[:10]:
                text += f"• <code>{html.escape(g.group_key)}</code>\n"
                if g.disable_reason:
                    text += f"  <i>{html.escape(g.disable_reason[:30])}</i>\n"

            for g in disabled[:5]:
                builder.button(
                    text=f"🔓 {g.group_key[:12]}",
                    callback_data=f"ev:enable:{g.group_key}"
                )
            builder.adjust(1)

        builder.row(
            InlineKeyboardButton(text="◀️ Назад", callback_data="ev:menu")
        )

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )

    except Exception as e:
        logger.error(f"Error in ev_show_disabled: {e}")
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("ev:enable:"))
async def ev_enable_group(callback: CallbackQuery):
    """Enable группу."""
    group_key = callback.data.replace("ev:enable:", "")

    try:
        state_manager = get_state_manager()
        success = await state_manager.set_manual_override(
            group_key=group_key,
            user_id=callback.from_user.id,
            duration_hours=24,
            reason=f"Manual enable by {callback.from_user.id}",
        )

        if success:
            await callback.answer(f"✅ {group_key} enabled на 24ч", show_alert=True)
        else:
            await callback.answer("❌ Не удалось включить", show_alert=True)

        await show_ev_stats_menu(callback)

    except Exception as e:
        logger.error(f"Error in ev_enable_group: {e}")
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("ev:disable:"))
async def ev_disable_group(callback: CallbackQuery):
    """Disable группу."""
    group_key = callback.data.replace("ev:disable:", "")

    try:
        state_manager = get_state_manager()
        success = await state_manager.disable_group(
            group_key=group_key,
            reason=f"Manual disable by {callback.from_user.id}",
        )

        if success:
            await callback.answer(f"🚫 {group_key} disabled", show_alert=True)
        else:
            await callback.answer("❌ Не удалось отключить", show_alert=True)

        await show_ev_stats_menu(callback)

    except Exception as e:
        logger.error(f"Error in ev_disable_group: {e}")
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)
