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

            # Используем opened_at или closed_at для timestamp
            trade_time = getattr(trade, 'opened_at', None) or getattr(trade, 'closed_at', None)
            timestamp = datetime.fromisoformat(trade_time).strftime("%d.%m %H:%M") if trade_time else "?"

            # Эмодзи
            side_emoji = "🟢" if side in ("Buy", "Long") else "🔴"
            if outcome == "win":
                outcome_emoji = "✅"
            elif outcome == "loss":
                outcome_emoji = "❌"
            elif trade.status == "open":
                outcome_emoji = "⏳"
            elif trade.status == "partial":
                outcome_emoji = "🔄"
            else:
                outcome_emoji = "➖"

            # Exit price может быть None для открытых позиций
            exit_str = f"${trade.exit_price:.4f}" if trade.exit_price else "открыта"

            # Индикатор режима (testnet/live)
            mode_indicator = "🧪" if getattr(trade, 'testnet', False) else "💰"

            # AI scenario индикатор
            ai_indicator = ""
            scenario_source = getattr(trade, 'scenario_source', 'manual')
            if scenario_source == 'syntra':
                conf = getattr(trade, 'scenario_confidence', 0) or 0
                ai_indicator = f"🤖{conf*100:.0f}% "

            # Entry mode info
            entry_mode = getattr(trade, 'entry_mode', 'single')
            entry_fills = getattr(trade, 'entry_fills', None)
            entry_info = ""
            if entry_mode == "ladder":
                fills_count = len(entry_fills) if entry_fills else 0
                entry_info = f"📋 {fills_count} entries"
            elif entry_fills and len(entry_fills) > 1:
                entry_info = f"({len(entry_fills)} fills)"

            # Exit fills info
            fills_info = ""
            fills = getattr(trade, 'fills', None)
            if fills and len(fills) > 1:
                fills_info = f" ({len(fills)} fills)"

            # Post-SL Analysis индикатор
            post_sl_info = ""
            if hasattr(trade, 'sl_was_correct') and trade.sl_was_correct is not None:
                sl_emoji = "🛡️" if trade.sl_was_correct else "⚠️"
                move = getattr(trade, 'post_sl_move_pct', 0) or 0
                post_sl_info = f"\n  {sl_emoji} Post-SL: {move:+.1f}%"

            # MAE/MFE info
            mae_mfe_info = ""
            mae_r = getattr(trade, 'mae_r', None)
            mfe_r = getattr(trade, 'mfe_r', None)
            if mae_r is not None and mfe_r is not None:
                mae_mfe_info = f"\n  MAE: {mae_r:.2f}R | MFE: {mfe_r:.2f}R"

            # Формируем строку entry
            entry_str = f"${trade.entry_price:.4f}"
            avg_entry = getattr(trade, 'avg_entry_price', None)
            if entry_mode == "ladder" and avg_entry and avg_entry > 0:
                entry_str = f"${avg_entry:.4f} (avg)"

            text += (
                f"{outcome_emoji} {side_emoji} {ai_indicator}<b>{symbol}</b> {mode_indicator} | {timestamp}\n"
                f"  PnL: ${pnl:+.2f} ({roe:+.2f}%){fills_info} {entry_info}\n"
                f"  Entry: {entry_str} → Exit: {exit_str}{post_sl_info}{mae_mfe_info}\n\n"
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

            # Используем opened_at или closed_at
            trade_time = getattr(trade, 'opened_at', None) or getattr(trade, 'closed_at', None)
            timestamp = datetime.fromisoformat(trade_time).strftime("%d.%m %H:%M") if trade_time else "?"

            side_emoji = "🟢" if side in ("Buy", "Long") else "🔴"
            if outcome == "win":
                outcome_emoji = "✅"
            elif outcome == "loss":
                outcome_emoji = "❌"
            elif trade.status == "open":
                outcome_emoji = "⏳"
            elif trade.status == "partial":
                outcome_emoji = "🔄"
            else:
                outcome_emoji = "➖"

            exit_str = f"${trade.exit_price:.4f}" if trade.exit_price else "открыта"

            # Индикатор режима (testnet/live)
            mode_indicator = "🧪" if getattr(trade, 'testnet', False) else "💰"

            # AI indicator
            ai_indicator = ""
            if getattr(trade, 'scenario_source', 'manual') == 'syntra':
                conf = getattr(trade, 'scenario_confidence', 0) or 0
                ai_indicator = f"🤖{conf*100:.0f}% "

            # Entry mode info
            entry_mode = getattr(trade, 'entry_mode', 'single')
            entry_fills = getattr(trade, 'entry_fills', None)
            entry_info = ""
            if entry_mode == "ladder":
                fills_count = len(entry_fills) if entry_fills else 0
                entry_info = f"📋 {fills_count} entries"

            # Post-SL Analysis индикатор
            post_sl_info = ""
            if hasattr(trade, 'sl_was_correct') and trade.sl_was_correct is not None:
                sl_emoji = "🛡️" if trade.sl_was_correct else "⚠️"
                move = getattr(trade, 'post_sl_move_pct', 0) or 0
                post_sl_info = f"\n  {sl_emoji} Post-SL: {move:+.1f}%"

            # Формируем строку entry
            entry_str = f"${trade.entry_price:.4f}"
            avg_entry = getattr(trade, 'avg_entry_price', None)
            if entry_mode == "ladder" and avg_entry and avg_entry > 0:
                entry_str = f"${avg_entry:.4f} (avg)"

            text += (
                f"{outcome_emoji} {side_emoji} {ai_indicator}<b>{symbol}</b> {mode_indicator} | {timestamp}\n"
                f"  PnL: ${pnl:+.2f} ({roe:+.2f}%) {entry_info}\n"
                f"  Entry: {entry_str} → Exit: {exit_str}{post_sl_info}\n\n"
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
async def show_statistics(callback: CallbackQuery, trade_logger, settings_storage, post_sl_analyzer=None):
    """Показать статистику по сделкам"""
    await callback.answer("📊 Загружаю статистику...")

    user_id = callback.from_user.id
    user_settings = await settings_storage.get_settings(user_id)
    testnet_mode = user_settings.testnet_mode

    try:
        # Получаем статистику по последним 100 сделкам для текущего режима
        stats = await trade_logger.get_statistics(user_id, limit=100, testnet=testnet_mode)

        # Получаем статистику по SL (если доступна)
        sl_stats = None
        if post_sl_analyzer:
            try:
                sl_stats = await post_sl_analyzer.get_sl_statistics(user_id, limit=50)
            except Exception as sl_err:
                logger.warning(f"Could not get SL statistics: {sl_err}")

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

        # v2 metrics
        total_fees = stats.get('total_fees', 0)
        net_pnl = stats.get('net_pnl', total_pnl)
        avg_mae_r = stats.get('avg_mae_r', 0)
        avg_mfe_r = stats.get('avg_mfe_r', 0)
        ai_trades_count = stats.get('ai_trades_count', 0)
        ai_winrate = stats.get('ai_winrate', 0)
        manual_trades_count = stats.get('manual_trades_count', 0)
        manual_winrate = stats.get('manual_winrate', 0)

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
Gross: ${total_pnl:+.2f} | Fees: ${total_fees:.2f}
<b>Net PnL: ${net_pnl:+.2f}</b>
Avg Win: ${avg_win:.2f} | Avg Loss: ${avg_loss:.2f}
Best: ${best:+.2f} | Worst: ${worst:+.2f}

<b>📈 Risk/Reward:</b>
Средний RR: {avg_rr:.2f}
Avg MAE: {avg_mae_r:.2f}R | Avg MFE: {avg_mfe_r:.2f}R

<b>🔥 Streaks:</b>
Win streak: {max_win_streak} | Loss streak: {max_loss_streak}

<b>📊 Направления:</b>
🟢 Long: {long_trades} ({long_trades/total*100:.1f}%)
🔴 Short: {short_trades} ({short_trades/total*100:.1f}%)
"""

        # AI vs Manual comparison
        if ai_trades_count > 0 or manual_trades_count > 0:
            text += f"""
<b>🤖 AI vs Manual:</b>
AI: {ai_trades_count} trades ({ai_winrate:.1f}% WR)
Manual: {manual_trades_count} trades ({manual_winrate:.1f}% WR)
"""

        # Confidence buckets
        confidence_stats = stats.get('confidence_stats', {})
        if confidence_stats:
            high_stats = confidence_stats.get('high', {})
            if high_stats.get('count', 0) > 0:
                text += f"""
<b>🎯 AI Confidence Performance:</b>
High (0.7-1.0): {high_stats['count']} trades, {high_stats['winrate']:.0f}% WR
"""

        # Entry Plan статистика
        ep_stats = stats.get('entry_plan_stats', {})
        if ep_stats.get('ladder_count', 0) > 0:
            ladder_count = ep_stats['ladder_count']
            ladder_winrate = ep_stats['ladder_winrate']
            ladder_pnl = ep_stats['ladder_pnl']
            single_count = ep_stats.get('single_count', 0)
            single_winrate = ep_stats.get('single_winrate', 0)
            avg_fills = ep_stats.get('avg_entry_fills', 0)

            text += f"""
<b>📋 Entry Modes:</b>
Ladder: {ladder_count} trades, {ladder_winrate:.0f}% WR, ${ladder_pnl:+.2f}
Single: {single_count} trades, {single_winrate:.0f}% WR
Avg fills/ladder: {avg_fills:.1f}
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

        # Post-SL Analysis статистика
        if sl_stats and sl_stats.get('analyzed', 0) > 0:
            correct_rate = sl_stats.get('correct_sl_rate', 0)
            correct_count = sl_stats.get('correct_sl_count', 0)
            incorrect_count = sl_stats.get('incorrect_sl_count', 0)
            analyzed = sl_stats.get('analyzed', 0)
            avg_adverse = sl_stats.get('avg_adverse_move', 0)
            avg_favorable = sl_stats.get('avg_favorable_move', 0)

            sl_emoji = "✅" if correct_rate >= 60 else "⚠️" if correct_rate >= 40 else "❌"

            text += f"""

<b>🛡️ Post-SL Analysis:</b>
{sl_emoji} Правильных SL: {correct_rate:.0f}% ({correct_count}/{analyzed})
📊 После неверных SL: +{avg_favorable:.1f}% avg
📉 После верных SL: -{avg_adverse:.1f}% avg
"""

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
