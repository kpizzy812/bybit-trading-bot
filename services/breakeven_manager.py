"""
Breakeven Manager - автоматический перенос SL на entry после TP1

После срабатывания первого Take Profit переносит Stop Loss на цену входа,
чтобы защитить позицию от убытка.
"""
import logging
from typing import Optional, Dict, Set
from datetime import datetime
from aiogram import Bot
from services.bybit import BybitClient
from services.trade_logger import TradeLogger
import config

logger = logging.getLogger(__name__)


class BreakevenManager:
    """
    Управляет автоматическим переносом SL на breakeven после TP1.

    Интегрируется с PositionMonitor - при обнаружении partial close
    автоматически перемещает SL на entry price.
    """

    def __init__(
        self,
        bot: Bot,
        trade_logger: TradeLogger,
        testnet: bool = False
    ):
        self.bot = bot
        self.trade_logger = trade_logger
        self.testnet = testnet
        self.client = BybitClient(testnet=testnet)

        # Позиции которые уже были переведены в breakeven
        # {position_key: True}
        self.breakeven_applied: Dict[str, bool] = {}

    def _position_key(self, symbol: str, side: str) -> str:
        """Уникальный ключ позиции"""
        return f"{symbol}:{side}"

    def is_breakeven_applied(self, symbol: str, side: str) -> bool:
        """Проверить применён ли breakeven к позиции"""
        key = self._position_key(symbol, side)
        return self.breakeven_applied.get(key, False)

    def mark_breakeven_applied(self, symbol: str, side: str):
        """Отметить что breakeven применён"""
        key = self._position_key(symbol, side)
        self.breakeven_applied[key] = True
        logger.info(f"Breakeven marked as applied for {key}")

    def clear_breakeven_status(self, symbol: str, side: str):
        """Очистить статус breakeven (при закрытии позиции)"""
        key = self._position_key(symbol, side)
        if key in self.breakeven_applied:
            del self.breakeven_applied[key]
            logger.info(f"Breakeven status cleared for {key}")

    async def move_to_breakeven(
        self,
        user_id: int,
        symbol: str,
        side: str,
        entry_price: float,
        current_tp: Optional[str] = None
    ) -> bool:
        """
        Переместить SL на breakeven (entry price + буфер)

        Args:
            user_id: ID пользователя для уведомления
            symbol: Торговая пара
            side: "Buy" или "Sell"
            entry_price: Цена входа
            current_tp: Текущий TP (для сохранения)

        Returns:
            True если успешно, False если ошибка
        """
        try:
            # Проверяем включён ли auto breakeven
            if not config.AUTO_BREAKEVEN_ENABLED:
                logger.debug("Auto breakeven disabled in config")
                return False

            # Проверяем не применён ли уже
            if self.is_breakeven_applied(symbol, side):
                logger.debug(f"Breakeven already applied for {symbol} {side}")
                return False

            # Рассчитываем breakeven price с буфером
            buffer_pct = config.BREAKEVEN_BUFFER_PCT

            if side == "Buy":
                # Long: SL немного выше entry чтобы закрыть в небольшой плюс
                breakeven_price = entry_price * (1 + buffer_pct)
            else:
                # Short: SL немного ниже entry
                breakeven_price = entry_price * (1 - buffer_pct)

            # Проверяем текущий SL - не ухудшаем позицию!
            positions = await self.client.get_positions(symbol=symbol)
            if positions:
                current_sl_str = positions[0].get('stopLoss', '')
                if current_sl_str:
                    current_sl = float(current_sl_str)
                    if side == "Buy" and current_sl > breakeven_price:
                        logger.info(f"Current SL {current_sl} already better than BE {breakeven_price}, skipping")
                        return False
                    elif side == "Sell" and current_sl < breakeven_price:
                        logger.info(f"Current SL {current_sl} already better than BE {breakeven_price}, skipping")
                        return False

            # Получаем instrument info для округления
            instrument_info = await self.client.get_instrument_info(symbol)
            tick_size = instrument_info.get('tickSize', '0.01')

            # Округляем цену
            from utils.validators import round_price
            breakeven_price_str = round_price(breakeven_price, tick_size)

            # Используем update_trading_stop чтобы сохранить TP
            await self.client.update_trading_stop(
                symbol=symbol,
                stop_loss=breakeven_price_str,
                sl_trigger_by="MarkPrice"
            )

            # Отмечаем как применённый
            self.mark_breakeven_applied(symbol, side)

            # Отправляем уведомление пользователю
            await self._send_breakeven_notification(
                user_id=user_id,
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                breakeven_price=float(breakeven_price_str)
            )

            logger.info(
                f"Breakeven applied: {symbol} {side}, "
                f"entry=${entry_price:.4f} → SL=${breakeven_price_str}"
            )
            return True

        except Exception as e:
            logger.error(f"Error moving to breakeven: {e}", exc_info=True)
            return False

    async def _send_breakeven_notification(
        self,
        user_id: int,
        symbol: str,
        side: str,
        entry_price: float,
        breakeven_price: float
    ):
        """Отправить уведомление о переносе SL на breakeven"""
        try:
            side_emoji = "🟢" if side == "Buy" else "🔴"
            side_text = "Long" if side == "Buy" else "Short"

            message = f"""
🛡️ <b>Auto Breakeven Activated!</b>

📊 <b>{symbol}</b> {side_emoji} {side_text}

✅ <b>TP1 исполнен!</b>
🔒 <b>SL перенесён на breakeven</b>

Entry: ${entry_price:.4f}
New SL: ${breakeven_price:.4f}

<i>Позиция защищена от убытка</i>

⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC
"""

            await self.bot.send_message(
                chat_id=user_id,
                text=message.strip(),
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Failed to send breakeven notification: {e}")

    async def handle_partial_close(
        self,
        user_id: int,
        symbol: str,
        side: str,
        entry_price: float,
        old_size: float,
        new_size: float,
        closed_pct: float
    ) -> bool:
        """
        Обработать partial close и применить breakeven если это TP1

        Вызывается из PositionMonitor при обнаружении частичного закрытия.

        Args:
            user_id: ID пользователя
            symbol: Торговая пара
            side: "Buy" или "Sell"
            entry_price: Цена входа
            old_size: Размер до закрытия
            new_size: Размер после закрытия
            closed_pct: Процент закрытия (0-100)

        Returns:
            True если breakeven применён
        """
        # Применяем breakeven только при первом partial close
        # (т.е. если ещё не применяли для этой позиции)
        if self.is_breakeven_applied(symbol, side):
            logger.debug(f"Breakeven already applied for {symbol}, skipping")
            return False

        # Проверяем что закрыто минимум 20% позиции
        # (чтобы не триггерить на случайные флуктуации)
        if closed_pct < 20:
            logger.debug(f"Closed only {closed_pct}%, minimum 20% for breakeven")
            return False

        logger.info(
            f"Partial close detected: {symbol} {side}, "
            f"closed {closed_pct:.1f}% ({old_size} → {new_size}), "
            f"applying breakeven..."
        )

        return await self.move_to_breakeven(
            user_id=user_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price
        )


def create_breakeven_manager(
    bot: Bot,
    trade_logger: TradeLogger,
    testnet: bool = False
) -> BreakevenManager:
    """Создать экземпляр BreakevenManager"""
    return BreakevenManager(
        bot=bot,
        trade_logger=trade_logger,
        testnet=testnet
    )
