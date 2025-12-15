"""
Trade Wizard - Навигация (Cancel, Back)
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from bot.keyboards.main_menu import get_main_menu

router = Router()


@router.callback_query(F.data == "trade:cancel")
async def trade_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена создания сделки"""
    await state.clear()
    await callback.message.edit_text(
        "❌ <b>Создание сделки отменено</b>",
        reply_markup=None
    )
    await callback.message.answer(
        "Используй главное меню для навигации 👇",
        reply_markup=get_main_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "trade:back")
async def trade_back(callback: CallbackQuery, state: FSMContext):
    """Возврат на предыдущий шаг"""
    # TODO: Реализовать логику возврата назад для каждого состояния
    await callback.answer("⚠️ Навигация назад в разработке. Используй ❌ Отмена", show_alert=True)
