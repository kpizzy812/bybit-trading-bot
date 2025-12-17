"""
EV Stats Handler

Telegram UI для Real EV статистики и управления.
- /ev_stats - общая статистика
- /ev_check - debug какой уровень сработал
- /ev_enable - включить группу
- /ev_disable - выключить группу
"""
import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from services.real_ev import (
    get_calculator,
    get_gate_checker,
    get_state_manager,
    GateStatus,
)

router = Router()


@router.message(Command("ev_stats"))
async def cmd_ev_stats(message: Message):
    """Показать общую Real EV статистику."""
    await message.answer("📊 Загружаю Real EV статистику...")

    try:
        calculator = get_calculator()
        state_manager = get_state_manager()

        # Получить L1 stats для всех архетипов
        all_stats = await calculator.calculate_all_l1_stats()

        if not all_stats:
            await message.answer(
                "📊 <b>Real EV Stats</b>\n\n"
                "Нет данных о закрытых сделках.\n"
                "Статистика появится после закрытия первых сделок.",
                parse_mode="HTML"
            )
            return

        # Сортируем по real_ev
        sorted_stats = sorted(all_stats, key=lambda s: s.real_ev, reverse=True)

        # Формируем текст
        text = "📊 <b>Real EV Stats (90d)</b>\n\n"
        text += "🎯 <b>By Archetype (L1):</b>\n"

        for stats in sorted_stats:
            # Emoji по EV
            if stats.real_ev >= 0.1:
                emoji = "✅"
            elif stats.real_ev >= 0:
                emoji = "🟢"
            elif stats.real_ev >= -0.1:
                emoji = "🟡"
            else:
                emoji = "🔴"

            # Проверяем disabled
            is_disabled = await state_manager.is_disabled(stats.group_key)
            disabled_mark = " 🚫 DISABLED" if is_disabled else ""

            arch_name = stats.group_key.split(":")[0]
            text += f"├ {emoji} {html.escape(arch_name)}: {stats.real_ev:+.2f}R (n={stats.sample_size})"
            text += f" WR:{stats.winrate*100:.0f}%{disabled_mark}\n"

        # Paper vs Real Gap
        text += "\n📈 <b>Paper vs Real Gap:</b>\n"
        for stats in sorted_stats[:5]:  # Top 5
            if stats.paper_ev_avg is not None and stats.ev_gap is not None:
                arch_name = stats.group_key.split(":")[0]
                gap_emoji = "⚠️" if abs(stats.ev_gap) > 0.3 else ""
                text += f"├ {html.escape(arch_name)}: "
                text += f"{stats.paper_ev_avg:+.2f} → {stats.real_ev:+.2f} "
                text += f"(gap {stats.ev_gap:+.2f}R) {gap_emoji}\n"

        # Disabled groups
        disabled_groups = await state_manager.get_all_disabled()
        if disabled_groups:
            text += f"\n🚫 <b>Disabled ({len(disabled_groups)}):</b>\n"
            for group in disabled_groups[:5]:
                text += f"└ {html.escape(group.group_key)}"
                if group.disable_reason:
                    text += f" ({html.escape(group.disable_reason)})"
                text += "\n"

        await message.answer(text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in /ev_stats: {e}")
        await message.answer(f"❌ Ошибка: {html.escape(str(e))}")


@router.message(Command("ev_check"))
async def cmd_ev_check(message: Message):
    """
    Debug: проверить какой уровень сработает.
    Usage: /ev_check <archetype> [timeframe] [regime]
    """
    parts = message.text.split()[1:]  # Убираем /ev_check

    if not parts:
        await message.answer(
            "📝 <b>Usage:</b>\n"
            "<code>/ev_check archetype [timeframe] [regime]</code>\n\n"
            "<b>Examples:</b>\n"
            "<code>/ev_check pullback_to_ema</code>\n"
            "<code>/ev_check pullback_to_ema 4h</code>\n"
            "<code>/ev_check pullback_to_ema 4h bullish_accumulation</code>",
            parse_mode="HTML"
        )
        return

    archetype = parts[0]
    timeframe = parts[1] if len(parts) > 1 else "4h"
    regime = parts[2] if len(parts) > 2 else None

    try:
        gate_checker = get_gate_checker()
        result = await gate_checker.check(
            archetype=archetype,
            timeframe=timeframe,
            market_regime=regime,
            user_id=message.from_user.id,
        )

        # Формируем текст
        text = f"🔍 <b>EV Check:</b> {html.escape(archetype)}"
        if timeframe:
            text += f" / {html.escape(timeframe)}"
        if regime:
            text += f" / {html.escape(regime)}"
        text += "\n\n"

        # Fallback chain
        text += "<b>Fallback chain:</b>\n"
        for item in result.fallback_chain:
            selected = " ✅ SELECTED" if item.meets_threshold else " ❌"
            ev_str = f"{item.real_ev:+.2f}R" if item.real_ev is not None else "N/A"
            text += f"├ {item.level}: {html.escape(item.key)}\n"
            text += f"│  n={item.sample_size}, EV={ev_str} {item.reason}{selected}\n"

        # Selected level
        text += f"\n<b>Selected:</b> {result.selected_level or 'NO_DATA'}\n"

        # Stats
        if result.stats:
            s = result.stats
            text += f"<b>Real EV:</b> {s.real_ev:+.2f}R | "
            text += f"<b>Rolling:</b> {s.rolling_ev:+.2f}R | " if s.rolling_ev else ""
            text += f"<b>WR:</b> {s.winrate*100:.0f}%\n"

        # Status
        status_emoji = {
            GateStatus.ALLOWED: "✅",
            GateStatus.WARN: "🟡",
            GateStatus.SOFT_BLOCK: "🟠",
            GateStatus.BLOCK: "🔴",
            GateStatus.NO_DATA: "🔘",
            GateStatus.OVERRIDE: "🟣",
        }
        emoji = status_emoji.get(result.status, "❓")
        text += f"\n<b>Status:</b> {emoji} {result.status.value}"
        if result.message:
            text += f"\n{html.escape(result.message)}"

        # Keyboard для действий
        builder = InlineKeyboardBuilder()
        if result.selected_key:
            if result.status in (GateStatus.BLOCK, GateStatus.SOFT_BLOCK):
                builder.button(
                    text="🔓 Enable 24h",
                    callback_data=f"ev:enable:{result.selected_key}"
                )
            else:
                builder.button(
                    text="🔒 Disable",
                    callback_data=f"ev:disable:{result.selected_key}"
                )
            builder.adjust(1)

        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=builder.as_markup() if result.selected_key else None
        )

    except Exception as e:
        logger.error(f"Error in /ev_check: {e}")
        await message.answer(f"❌ Ошибка: {html.escape(str(e))}")


@router.message(Command("ev_enable"))
async def cmd_ev_enable(message: Message):
    """
    Включить группу вручную.
    Usage: /ev_enable <group_key> [hours]
    """
    parts = message.text.split()[1:]

    if not parts:
        await message.answer(
            "📝 <b>Usage:</b>\n"
            "<code>/ev_enable group_key [hours]</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/ev_enable pullback_to_ema:4h 24</code>",
            parse_mode="HTML"
        )
        return

    group_key = parts[0]
    hours = int(parts[1]) if len(parts) > 1 else 24

    try:
        state_manager = get_state_manager()
        success = await state_manager.set_manual_override(
            group_key=group_key,
            user_id=message.from_user.id,
            duration_hours=hours,
            reason=f"Manual enable by user {message.from_user.id}",
        )

        if success:
            await message.answer(
                f"✅ Группа <code>{html.escape(group_key)}</code> включена на {hours}ч",
                parse_mode="HTML"
            )
        else:
            await message.answer("❌ Не удалось включить группу")

    except Exception as e:
        logger.error(f"Error in /ev_enable: {e}")
        await message.answer(f"❌ Ошибка: {html.escape(str(e))}")


@router.message(Command("ev_disable"))
async def cmd_ev_disable(message: Message):
    """
    Выключить группу вручную.
    Usage: /ev_disable <group_key>
    """
    parts = message.text.split()[1:]

    if not parts:
        await message.answer(
            "📝 <b>Usage:</b>\n"
            "<code>/ev_disable group_key</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/ev_disable breakout_retest:4h</code>",
            parse_mode="HTML"
        )
        return

    group_key = parts[0]

    try:
        state_manager = get_state_manager()
        success = await state_manager.disable_group(
            group_key=group_key,
            reason=f"Manual disable by user {message.from_user.id}",
        )

        if success:
            await message.answer(
                f"🚫 Группа <code>{html.escape(group_key)}</code> отключена",
                parse_mode="HTML"
            )
        else:
            await message.answer("❌ Не удалось отключить группу")

    except Exception as e:
        logger.error(f"Error in /ev_disable: {e}")
        await message.answer(f"❌ Ошибка: {html.escape(str(e))}")


# === CALLBACK HANDLERS ===

@router.callback_query(F.data.startswith("ev:enable:"))
async def ev_enable_callback(callback: CallbackQuery):
    """Enable группу через кнопку."""
    group_key = callback.data.replace("ev:enable:", "")

    try:
        state_manager = get_state_manager()
        success = await state_manager.set_manual_override(
            group_key=group_key,
            user_id=callback.from_user.id,
            duration_hours=24,
            reason=f"Manual enable via button by user {callback.from_user.id}",
        )

        if success:
            await callback.answer(f"✅ Группа включена на 24ч", show_alert=True)
            # Обновить сообщение
            await callback.message.edit_reply_markup(reply_markup=None)
        else:
            await callback.answer("❌ Не удалось включить группу", show_alert=True)

    except Exception as e:
        logger.error(f"Error in ev_enable_callback: {e}")
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("ev:disable:"))
async def ev_disable_callback(callback: CallbackQuery):
    """Disable группу через кнопку."""
    group_key = callback.data.replace("ev:disable:", "")

    try:
        state_manager = get_state_manager()
        success = await state_manager.disable_group(
            group_key=group_key,
            reason=f"Manual disable via button by user {callback.from_user.id}",
        )

        if success:
            await callback.answer(f"🚫 Группа отключена", show_alert=True)
            # Обновить сообщение
            await callback.message.edit_reply_markup(reply_markup=None)
        else:
            await callback.answer("❌ Не удалось отключить группу", show_alert=True)

    except Exception as e:
        logger.error(f"Error in ev_disable_callback: {e}")
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)
