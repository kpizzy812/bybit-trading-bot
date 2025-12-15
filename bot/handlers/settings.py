"""
Хендлеры для управления настройками
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.keyboards.settings_kb import (
    get_settings_menu_kb,
    get_default_risk_kb,
    get_default_leverage_kb,
    get_tp_mode_kb,
    get_shorts_enabled_kb,
    get_safety_limits_kb,
    get_max_risk_kb,
    get_max_margin_kb,
    get_max_leverage_kb
)
from bot.keyboards.main_menu import get_main_menu
import config
import logging

logger = logging.getLogger(__name__)
router = Router()


# ============================================================
# CALLBACK: Показать меню настроек
# ============================================================

@router.callback_query(F.data == "show_settings_menu")
async def show_settings_menu(callback: CallbackQuery, settings_storage):
    """Показать главное меню настроек"""
    await callback.answer()

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)

    # Формируем текст с текущими настройками
    testnet_mode = user_settings.testnet_mode
    default_risk = user_settings.default_risk_usd
    default_leverage = user_settings.default_leverage
    default_margin_mode = user_settings.default_margin_mode
    shorts_enabled = user_settings.shorts_enabled
    default_tp_mode = user_settings.default_tp_mode

    mode_text = "🧪 <b>Testnet</b>" if testnet_mode else "🔴 <b>Live Trading</b>"
    shorts_text = "✅ Включены" if shorts_enabled else "❌ Выключены"

    text = f"""
⚙️ <b>Настройки бота</b>

<b>Текущие параметры:</b>

🌐 Режим: {mode_text}
💰 Дефолтный риск: ${default_risk}
📊 Дефолтное плечо: {default_leverage}x
🔀 Режим маржи: {default_margin_mode}
🔴 Шорты: {shorts_text}
🎯 TP режим: {default_tp_mode}

<b>Лимиты безопасности:</b>
🛡 Макс. риск на сделку: ${user_settings.max_risk_per_trade}
🛡 Макс. маржа на сделку: ${user_settings.max_margin_per_trade}

💡 Выбери категорию для изменения:
"""

    await callback.message.edit_text(
        text.strip(),
        reply_markup=get_settings_menu_kb()
    )


# ============================================================
# CALLBACK: Default Risk
# ============================================================

@router.callback_query(F.data == "set_default_risk")
async def set_default_risk_menu(callback: CallbackQuery, settings_storage):
    """Меню выбора дефолтного риска"""
    await callback.answer()

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    current_risk = user_settings.default_risk_usd

    await callback.message.edit_text(
        f"💰 <b>Дефолтный риск на сделку</b>\n\n"
        f"Текущее значение: <b>${current_risk}</b>\n\n"
        f"Выбери новое значение:",
        reply_markup=get_default_risk_kb(current_risk)
    )


@router.callback_query(F.data.startswith("set_risk:"))
async def set_default_risk_value(callback: CallbackQuery, settings_storage):
    """Установить новый дефолтный риск"""
    # Парсим: set_risk:VALUE
    new_risk = float(callback.data.split(":")[1])

    user_id = callback.from_user.id

    # Валидация
    if new_risk > config.MAX_RISK_PER_TRADE:
        await callback.answer(
            f"❌ Риск не может быть больше ${config.MAX_RISK_PER_TRADE}",
            show_alert=True
        )
        return

    # Сохраняем
    await settings_storage.update_setting(user_id, 'default_risk_usd', new_risk)

    await callback.answer(f"✅ Дефолтный риск установлен: ${new_risk}")

    # Возвращаемся к меню настроек
    await show_settings_menu(callback, settings_storage)


# ============================================================
# CALLBACK: Default Leverage
# ============================================================

@router.callback_query(F.data == "set_default_leverage")
async def set_default_leverage_menu(callback: CallbackQuery, settings_storage):
    """Меню выбора дефолтного плеча"""
    await callback.answer()

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    current_leverage = user_settings.default_leverage

    await callback.message.edit_text(
        f"📊 <b>Дефолтное плечо</b>\n\n"
        f"Текущее значение: <b>{current_leverage}x</b>\n\n"
        f"Выбери новое значение:",
        reply_markup=get_default_leverage_kb(current_leverage)
    )


@router.callback_query(F.data.startswith("set_leverage:"))
async def set_default_leverage_value(callback: CallbackQuery, settings_storage):
    """Установить новое дефолтное плечо"""
    # Парсим: set_leverage:VALUE
    new_leverage = int(callback.data.split(":")[1])

    user_id = callback.from_user.id

    # Валидация
    if new_leverage > config.MAX_LEVERAGE:
        await callback.answer(
            f"❌ Плечо не может быть больше {config.MAX_LEVERAGE}x",
            show_alert=True
        )
        return

    # Сохраняем
    await settings_storage.update_setting(user_id, 'default_leverage', new_leverage)

    await callback.answer(f"✅ Дефолтное плечо установлено: {new_leverage}x")

    # Возвращаемся к меню настроек
    await show_settings_menu(callback, settings_storage)


# ============================================================
# CALLBACK: TP Mode
# ============================================================

@router.callback_query(F.data == "set_tp_mode")
async def set_tp_mode_menu(callback: CallbackQuery, settings_storage):
    """Меню выбора TP режима"""
    await callback.answer()

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    current_tp_mode = user_settings.default_tp_mode

    tp_mode_names = {
        'single': 'Single TP',
        'ladder': 'Ladder',
        'rr': 'By RR'
    }

    await callback.message.edit_text(
        f"🎯 <b>Режим Take Profit</b>\n\n"
        f"Текущий режим: <b>{tp_mode_names.get(current_tp_mode, current_tp_mode)}</b>\n\n"
        f"Выбери новый режим:\n\n"
        f"• <b>Single TP</b> - один тейк на всю позицию\n"
        f"• <b>Ladder</b> - несколько уровней (50% / 50%)\n"
        f"• <b>By RR</b> - автоматический расчёт по Risk/Reward",
        reply_markup=get_tp_mode_kb(current_tp_mode)
    )


@router.callback_query(F.data.startswith("set_tp_mode:"))
async def set_tp_mode_value(callback: CallbackQuery, settings_storage):
    """Установить новый TP режим"""
    # Парсим: set_tp_mode:MODE
    new_tp_mode = callback.data.split(":")[1]

    user_id = callback.from_user.id

    # Валидация
    valid_modes = {'single', 'ladder', 'rr'}
    if new_tp_mode not in valid_modes:
        await callback.answer("❌ Неверный режим TP", show_alert=True)
        return

    # Сохраняем
    await settings_storage.update_setting(user_id, 'default_tp_mode', new_tp_mode)

    tp_mode_names = {
        'single': 'Single TP',
        'ladder': 'Ladder',
        'rr': 'By RR'
    }

    await callback.answer(f"✅ TP режим установлен: {tp_mode_names[new_tp_mode]}")

    # Возвращаемся к меню настроек
    await show_settings_menu(callback, settings_storage)


# ============================================================
# CALLBACK: Shorts Enabled
# ============================================================

@router.callback_query(F.data == "set_shorts_enabled")
async def set_shorts_enabled_menu(callback: CallbackQuery, settings_storage):
    """Меню включения/выключения шортов"""
    await callback.answer()

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    current_shorts = user_settings.shorts_enabled

    await callback.message.edit_text(
        f"🔴 <b>Разрешить шорты</b>\n\n"
        f"Текущее состояние: <b>{'✅ Включены' if current_shorts else '❌ Выключены'}</b>\n\n"
        f"Если шорты выключены, то в Trade Wizard будет доступен только Long",
        reply_markup=get_shorts_enabled_kb(current_shorts)
    )


@router.callback_query(F.data.startswith("set_shorts:"))
async def set_shorts_enabled_value(callback: CallbackQuery, settings_storage):
    """Установить состояние шортов"""
    # Парсим: set_shorts:true/false
    new_shorts = callback.data.split(":")[1] == 'true'

    user_id = callback.from_user.id

    # Сохраняем
    await settings_storage.update_setting(user_id, 'shorts_enabled', new_shorts)

    await callback.answer(f"✅ Шорты {'включены' if new_shorts else 'выключены'}")

    # Возвращаемся к меню настроек
    await show_settings_menu(callback, settings_storage)


# ============================================================
# CALLBACK: Safety Limits
# ============================================================

@router.callback_query(F.data == "set_safety_limits")
async def set_safety_limits_menu(callback: CallbackQuery):
    """Меню лимитов безопасности"""
    await callback.answer()

    await callback.message.edit_text(
        f"🛡 <b>Лимиты безопасности</b>\n\n"
        f"Эти лимиты защищают от случайных ошибок и слишком больших позиций.\n\n"
        f"Выбери параметр для изменения:",
        reply_markup=get_safety_limits_kb()
    )


# Max Risk
@router.callback_query(F.data == "set_max_risk")
async def set_max_risk_menu(callback: CallbackQuery, settings_storage):
    """Меню выбора максимального риска"""
    await callback.answer()

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    current_max_risk = user_settings.max_risk_per_trade

    await callback.message.edit_text(
        f"🛡 <b>Максимальный риск на сделку</b>\n\n"
        f"Текущее значение: <b>${current_max_risk}</b>\n\n"
        f"Выбери новое значение:",
        reply_markup=get_max_risk_kb(current_max_risk)
    )


@router.callback_query(F.data.startswith("set_max_risk_val:"))
async def set_max_risk_value(callback: CallbackQuery, settings_storage):
    """Установить максимальный риск"""
    # Парсим: set_max_risk_val:VALUE
    new_max_risk = float(callback.data.split(":")[1])

    user_id = callback.from_user.id

    # Сохраняем
    await settings_storage.update_setting(user_id, 'max_risk_per_trade', new_max_risk)

    await callback.answer(f"✅ Макс. риск установлен: ${new_max_risk}")

    # Возвращаемся к лимитам
    await set_safety_limits_menu(callback)


# Max Margin
@router.callback_query(F.data == "set_max_margin")
async def set_max_margin_menu(callback: CallbackQuery, settings_storage):
    """Меню выбора максимальной маржи"""
    await callback.answer()

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    current_max_margin = user_settings.max_margin_per_trade

    await callback.message.edit_text(
        f"🛡 <b>Максимальная маржа на сделку</b>\n\n"
        f"Текущее значение: <b>${current_max_margin}</b>\n\n"
        f"Выбери новое значение:",
        reply_markup=get_max_margin_kb(current_max_margin)
    )


@router.callback_query(F.data.startswith("set_max_margin_val:"))
async def set_max_margin_value(callback: CallbackQuery, settings_storage):
    """Установить максимальную маржу"""
    # Парсим: set_max_margin_val:VALUE
    new_max_margin = float(callback.data.split(":")[1])

    user_id = callback.from_user.id

    # Сохраняем
    await settings_storage.update_setting(user_id, 'max_margin_per_trade', new_max_margin)

    await callback.answer(f"✅ Макс. маржа установлена: ${new_max_margin}")

    # Возвращаемся к лимитам
    await set_safety_limits_menu(callback)


# Max Leverage
@router.callback_query(F.data == "set_max_leverage")
async def set_max_leverage_menu(callback: CallbackQuery):
    """Меню выбора максимального плеча"""
    await callback.answer()

    await callback.message.edit_text(
        f"🛡 <b>Максимальное плечо</b>\n\n"
        f"⚠️ Этот параметр установлен в конфигурации бота\n\n"
        f"Текущее значение: <b>{config.MAX_LEVERAGE}x</b>\n\n"
        f"Для изменения отредактируй .env файл и перезапусти бота",
        reply_markup=get_safety_limits_kb()
    )


# ============================================================
# CALLBACK: Назад
# ============================================================

@router.callback_query(F.data == "set_back_to_menu")
async def back_to_settings_menu(callback: CallbackQuery, settings_storage):
    """Вернуться к меню настроек"""
    await callback.answer()
    await show_settings_menu(callback, settings_storage)


@router.callback_query(F.data == "set_back_to_main")
async def back_to_main(callback: CallbackQuery):
    """Вернуться к главному меню"""
    await callback.answer()

    await callback.message.edit_text(
        "◀️ Возвращаюсь в главное меню...\n\n"
        "Используй кнопки ниже для навигации",
        reply_markup=get_main_menu()
    )
