"""
Хендлеры для истории сделок
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from datetime import datetime
import logging

from bot.keyboards.history_kb import (
    get_history_main_kb,
    get_history_list_kb,
    get_history_filters_kb,
    get_stats_kb
)

logger = logging.getLogger(__name__)
router = Router()


# ============================================================
# CALLBACK: Главное меню истории
# ============================================================

@router.callback_query(F.data == "hist_main")
async def show_history_main(callback: CallbackQuery):
    """Главное меню истории"""
    await callback.answer()

    text = """
🧾 <b>История сделок</b>

Здесь ты можешь:
• Просмотреть закрытые сделки
• Проанализировать статистику
• Отфильтровать по символам

Выбери действие ниже:
"""

    await callback.message.edit_text(
        text.strip(),
        reply_markup=get_history_main_kb()
    )


# ============================================================
# CALLBACK: Последние сделки
# ============================================================

@router.callback_query(F.data == "hist_recent")
async def show_recent_trades(callback: CallbackQuery, trade_logger, settings_storage):
    """Показать последние сделки"""
    await callback.answer("📋 Загружаю историю...")

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet_mode = user_settings.testnet_mode

    try:
        # Получаем последние 20 сделок для текущего режима
        trades = await trade_logger.get_trades(user_id, limit=20, offset=0, testnet=testnet_mode)

        if not trades:
            await callback.message.edit_text(
                "🧾 <b>История сделок пуста</b>\n\n"
                "Здесь будут отображаться твои закрытые позиции.\n\n"
                "💡 Открой первую сделку через <b>➕ Открыть сделку</b>",
                reply_markup=get_history_main_kb()
            )
            return

        # Формируем текст со списком сделок
        text = "📋 <b>Последние сделки:</b>\n\n"

        for trade in trades:
            # Парсим данные
            symbol = trade.symbol
            side = trade.side
            outcome = trade.outcome or "open"
            pnl = trade.pnl_usd or 0
            roe = trade.roe_percent or 0
            timestamp = datetime.fromisoformat(trade.timestamp).strftime("%d.%m %H:%M")

            # Эмодзи
            side_emoji = "🟢" if side in ("Buy", "Long") else "🔴"
            if outcome == "win":
                outcome_emoji = "✅"
            elif outcome == "loss":
                outcome_emoji = "❌"
            elif outcome == "open":
                outcome_emoji = "⏳"
            else:
                outcome_emoji = "➖"

            # Exit price может быть None для открытых позиций
            exit_str = f"${trade.exit_price:.4f}" if trade.exit_price else "открыта"

            # Индикатор режима (testnet/live)
            mode_indicator = "🧪" if getattr(trade, 'testnet', False) else "💰"

            text += (
                f"{outcome_emoji} {side_emoji} <b>{symbol}</b> {mode_indicator} | {timestamp}\n"
                f"  PnL: ${pnl:+.2f} ({roe:+.2f}%)\n"
                f"  Entry: ${trade.entry_price:.4f} → Exit: {exit_str}\n\n"
            )

        # Проверяем, есть ли ещё сделки
        has_next = len(trades) == 20

        await callback.message.edit_text(
            text,
            reply_markup=get_history_list_kb(has_next=has_next, offset=0)
        )

    except Exception as e:
        logger.error(f"Error showing recent trades: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при загрузке истории:\n{str(e)}",
            reply_markup=get_history_main_kb()
        )


# ============================================================
# CALLBACK: Пагинация
# ============================================================

@router.callback_query(F.data.startswith("hist_page:"))
async def show_trades_page(callback: CallbackQuery, trade_logger, settings_storage):
    """Показать страницу истории с пагинацией"""
    # Парсим offset
    offset = int(callback.data.split(":")[1])

    await callback.answer("📋 Загружаю...")

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet_mode = user_settings.testnet_mode

    try:
        trades = await trade_logger.get_trades(user_id, limit=20, offset=offset, testnet=testnet_mode)

        if not trades:
            await callback.answer("📋 Больше сделок нет", show_alert=True)
            return

        # Формируем текст
        text = f"📋 <b>История сделок (стр. {offset // 20 + 1}):</b>\n\n"

        for trade in trades:
            symbol = trade.symbol
            side = trade.side
            outcome = trade.outcome or "open"
            pnl = trade.pnl_usd or 0
            roe = trade.roe_percent or 0
            timestamp = datetime.fromisoformat(trade.timestamp).strftime("%d.%m %H:%M")

            side_emoji = "🟢" if side in ("Buy", "Long") else "🔴"
            if outcome == "win":
                outcome_emoji = "✅"
            elif outcome == "loss":
                outcome_emoji = "❌"
            elif outcome == "open":
                outcome_emoji = "⏳"
            else:
                outcome_emoji = "➖"

            exit_str = f"${trade.exit_price:.4f}" if trade.exit_price else "открыта"

            # Индикатор режима (testnet/live)
            mode_indicator = "🧪" if getattr(trade, 'testnet', False) else "💰"

            text += (
                f"{outcome_emoji} {side_emoji} <b>{symbol}</b> {mode_indicator} | {timestamp}\n"
                f"  PnL: ${pnl:+.2f} ({roe:+.2f}%)\n"
                f"  Entry: ${trade.entry_price:.4f} → Exit: {exit_str}\n\n"
            )

        has_next = len(trades) == 20

        await callback.message.edit_text(
            text,
            reply_markup=get_history_list_kb(has_next=has_next, offset=offset)
        )

    except Exception as e:
        logger.error(f"Error showing trades page: {e}")
        await callback.answer("❌ Ошибка при загрузке", show_alert=True)


# ============================================================
# CALLBACK: Статистика
# ============================================================

@router.callback_query(F.data == "hist_stats")
async def show_statistics(callback: CallbackQuery, trade_logger, settings_storage):
    """Показать статистику по сделкам"""
    await callback.answer("📊 Загружаю статистику...")

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet_mode = user_settings.testnet_mode

    try:
        # Получаем статистику по последним 100 сделкам для текущего режима
        stats = await trade_logger.get_statistics(user_id, limit=100, testnet=testnet_mode)

        if stats['total_trades'] == 0:
            await callback.message.edit_text(
                "📊 <b>Статистика недоступна</b>\n\n"
                "Здесь будет отображаться твоя статистика после первых сделок.",
                reply_markup=get_stats_kb()
            )
            return

        # Формируем текст статистики
        total = stats['total_trades']
        winrate = stats['winrate']
        total_pnl = stats['total_pnl']
        avg_win = stats['avg_win']
        avg_loss = stats['avg_loss']
        best = stats['best_trade']
        worst = stats['worst_trade']
        avg_rr = stats['avg_rr']
        long_trades = stats['long_trades']
        short_trades = stats['short_trades']

        # New metrics
        expectancy = stats.get('expectancy', 0)
        expectancy_r = stats.get('expectancy_r', 0)
        profit_factor = stats.get('profit_factor', 0)
        win_count = stats.get('win_count', 0)
        loss_count = stats.get('loss_count', 0)
        max_win_streak = stats.get('max_win_streak', 0)
        max_loss_streak = stats.get('max_loss_streak', 0)

        # Форматируем profit factor
        pf_str = f"{profit_factor:.2f}" if profit_factor != float('inf') else "∞"

        # Эмодзи для expectancy
        exp_emoji = "📈" if expectancy > 0 else "📉" if expectancy < 0 else "➖"

        text = f"""
📊 <b>Статистика (последние {total} сделок)</b>

<b>🎯 Ключевые метрики:</b>
{exp_emoji} <b>Expectancy:</b> ${expectancy:+.2f}/trade ({expectancy_r:+.2f}R)
💹 <b>Profit Factor:</b> {pf_str}
✅ <b>Winrate:</b> {winrate:.1f}% ({win_count}W/{loss_count}L)

<b>💰 PnL:</b>
Общий: ${total_pnl:+.2f}
Avg Win: ${avg_win:.2f} | Avg Loss: ${avg_loss:.2f}
Best: ${best:+.2f} | Worst: ${worst:+.2f}

<b>📈 Risk/Reward:</b>
Средний RR: {avg_rr:.2f}

<b>🔥 Streaks:</b>
Win streak: {max_win_streak} | Loss streak: {max_loss_streak}

<b>📊 Направления:</b>
🟢 Long: {long_trades} ({long_trades/total*100:.1f}%)
🔴 Short: {short_trades} ({short_trades/total*100:.1f}%)
"""

        # Статистика по символам
        if stats['symbols']:
            text += "\n<b>По символам:</b>\n"
            for symbol, symbol_stats in stats['symbols'].items():
                count = symbol_stats['count']
                pnl = symbol_stats['pnl']
                wins = symbol_stats['wins']
                winrate_symbol = (wins / count * 100) if count > 0 else 0

                text += f"• {symbol}: {count} сделок, ${pnl:+.2f} ({winrate_symbol:.0f}% WR)\n"

        await callback.message.edit_text(
            text.strip(),
            reply_markup=get_stats_kb()
        )

    except Exception as e:
        logger.error(f"Error showing statistics: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при загрузке статистики:\n{str(e)}",
            reply_markup=get_stats_kb()
        )


# ============================================================
# CALLBACK: Фильтры
# ============================================================

@router.callback_query(F.data == "hist_filters")
async def show_filters_menu(callback: CallbackQuery):
    """Меню фильтров (заглушка на будущее)"""
    await callback.answer()

    await callback.message.edit_text(
        "🔍 <b>Фильтры истории</b>\n\n"
        "⚠️ Фильтрация в разработке...\n\n"
        "В будущем здесь можно будет фильтровать по:\n"
        "• Символам\n"
        "• Направлению (Long/Short)\n"
        "• Датам\n"
        "• PnL (win/loss)",
        reply_markup=get_history_filters_kb()
    )
