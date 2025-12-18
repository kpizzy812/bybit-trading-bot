"""
Хендлеры для Entry Plans.
"""
import html
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile

from bot.keyboards.positions_kb import (
    get_entry_plan_detail_kb,
    get_entry_plan_cancel_confirm_kb
)
from bot.keyboards.main_menu import get_main_menu
from bot.handlers.positions.formatters import format_entry_plan_detail
from bot.handlers.positions.chart_generators import generate_entry_plan_chart
from bot.utils.safe_edit import safe_edit_text

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("eplan_detail:"))
async def show_entry_plan_detail(callback: CallbackQuery, entry_plan_monitor, settings_storage):
    """Показать детали Entry Plan с графиком"""
    await callback.answer()

    # Парсим plan_id (короткий, 8 символов)
    short_plan_id = callback.data.split(":")[1]

    # Ищем план по короткому ID
    plan = None
    for pid, p in entry_plan_monitor.active_plans.items():
        if pid.startswith(short_plan_id):
            plan = p
            break

    if not plan:
        await safe_edit_text(callback.message, "❌ Entry Plan не найден (возможно уже завершён)")
        return

    # Форматируем детали плана
    text = format_entry_plan_detail(plan)

    # Генерируем график
    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet = user_settings.testnet_mode

    chart_png = await generate_entry_plan_chart(plan, testnet)

    # Удаляем старое сообщение и отправляем новое
    try:
        await callback.message.delete()
    except Exception:
        pass

    if chart_png:
        photo = BufferedInputFile(chart_png, filename=f"{plan.symbol}_entryplan.png")
        await callback.message.answer_photo(
            photo=photo,
            caption=text if len(text) <= 1024 else None,
            parse_mode="HTML",
            reply_markup=get_entry_plan_detail_kb(plan.plan_id, is_activated=plan.is_activated)
        )
        if len(text) > 1024:
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=get_entry_plan_detail_kb(plan.plan_id, is_activated=plan.is_activated)
            )
    else:
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=get_entry_plan_detail_kb(plan.plan_id, is_activated=plan.is_activated)
        )


@router.callback_query(F.data.startswith("eplan_activate:"))
async def activate_entry_plan_now(callback: CallbackQuery, entry_plan_monitor):
    """Принудительно активировать Entry Plan (поставить лимитки сейчас)"""
    await callback.answer("Активирую план...")

    short_plan_id = callback.data.split(":")[1]

    # Ищем план
    plan = None
    for pid, p in entry_plan_monitor.active_plans.items():
        if pid.startswith(short_plan_id):
            plan = p
            break

    if not plan:
        await safe_edit_text(callback.message, "❌ Entry Plan не найден")
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
        return

    if plan.is_activated:
        await safe_edit_text(callback.message, "⚠️ План уже активирован")
        return

    try:
        # Принудительная активация
        await entry_plan_monitor._activate_plan(plan)

        side_emoji = "🟢" if plan.side == "Long" else "🔴"
        await safe_edit_text(
            callback.message,
            f"✅ <b>Entry Plan активирован!</b>\n\n"
            f"{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}\n"
            f"📊 Mode: {plan.mode}\n"
            f"📦 Orders: {len(plan.orders)}\n\n"
            f"🔔 Лимитки выставлены, ожидай исполнения"
        )
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except Exception as e:
        logger.error(f"Error activating entry plan: {e}")
        await safe_edit_text(callback.message, f"❌ Ошибка при активации:\n{html.escape(str(e))}")
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())


@router.callback_query(F.data.startswith("eplan_cancel:"))
async def cancel_entry_plan_confirmation(callback: CallbackQuery, entry_plan_monitor):
    """Запрос подтверждения отмены Entry Plan"""
    await callback.answer()

    short_plan_id = callback.data.split(":")[1]

    # Ищем план
    plan = None
    for pid, p in entry_plan_monitor.active_plans.items():
        if pid.startswith(short_plan_id):
            plan = p
            break

    if not plan:
        await safe_edit_text(callback.message, "❌ Entry Plan не найден")
        return

    side_emoji = "🟢" if plan.side == "Long" else "🔴"

    await safe_edit_text(
        callback.message,
        f"⚠️ <b>Подтверждение отмены Entry Plan</b>\n\n"
        f"{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}\n"
        f"📊 Mode: {plan.mode}\n"
        f"📈 Filled: {plan.fill_percentage:.0f}%\n\n"
        f"Ты уверен, что хочешь отменить этот план?\n\n"
        f"⚠️ Все pending ордера будут отменены.\n"
        f"{'✅ Частичная позиция получит SL/TP' if plan.has_fills else ''}",
        reply_markup=get_entry_plan_cancel_confirm_kb(plan.plan_id)
    )


@router.callback_query(F.data.startswith("eplan_cancel_confirm:"))
async def cancel_entry_plan_execute(callback: CallbackQuery, entry_plan_monitor):
    """Выполнить отмену Entry Plan"""
    await callback.answer("Отменяю план...")

    short_plan_id = callback.data.split(":")[1]

    # Ищем план
    plan = None
    full_plan_id = None
    for pid, p in entry_plan_monitor.active_plans.items():
        if pid.startswith(short_plan_id):
            plan = p
            full_plan_id = pid
            break

    if not plan:
        await safe_edit_text(callback.message, "❌ Entry Plan не найден")
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
        return

    try:
        # Отменяем план (это вызовет _cancel_plan в мониторе)
        await entry_plan_monitor._cancel_plan(plan, "user_cancelled")

        side_emoji = "🟢" if plan.side == "Long" else "🔴"

        result_text = (
            f"✅ <b>Entry Plan отменён</b>\n\n"
            f"{side_emoji} <b>{plan.symbol}</b> {plan.side.upper()}\n"
            f"📊 Mode: {plan.mode}\n"
        )

        if plan.has_fills:
            result_text += (
                f"\n📈 <b>Partial position:</b>\n"
                f"  Filled: {plan.fill_percentage:.0f}%\n"
                f"  Qty: {plan.filled_qty:.4f}\n"
                f"  Avg: ${plan.avg_entry_price:.2f}\n"
                f"\n✅ SL/TP установлены на позицию"
            )
        else:
            result_text += "\n<i>Все ордера отменены, позиция не открыта</i>"

        await safe_edit_text(callback.message, result_text)
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())

    except Exception as e:
        logger.error(f"Error cancelling entry plan: {e}")
        await safe_edit_text(callback.message, f"❌ Ошибка при отмене плана:\n{html.escape(str(e))}")
        await callback.message.answer("Используй главное меню 👇", reply_markup=get_main_menu())
