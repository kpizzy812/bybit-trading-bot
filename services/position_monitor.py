"""
Position Monitor - мониторинг позиций и уведомления о закрытии

Отслеживает открытые позиции и автоматически отправляет уведомления когда:
- Позиция закрывается по Stop Loss
- Позиция закрывается по Take Profit
- Позиция закрывается частично (Ladder TP)
- Позиция закрывается вручную или по ликвидации

Также интегрируется с BreakevenManager для автоматического
переноса SL на entry после первого TP.
"""
import asyncio
import logging
from typing import Dict, Optional, Set, TYPE_CHECKING
from datetime import datetime
from aiogram import Bot
from services.bybit import BybitClient
from services.trade_logger import TradeLogger

if TYPE_CHECKING:
    from services.breakeven_manager import BreakevenManager

logger = logging.getLogger(__name__)


class PositionSnapshot:
    """Снимок состояния позиции для сравнения"""

    def __init__(self, position: dict):
        self.symbol = position.get('symbol')
        self.side = position.get('side')
        self.size = float(position.get('size', 0))
        self.entry_price = float(position.get('avgPrice', 0))
        self.mark_price = float(position.get('markPrice', 0))
        self.unrealized_pnl = float(position.get('unrealisedPnl', 0))
        self.stop_loss = position.get('stopLoss', '')
        self.take_profit = position.get('takeProfit', '')
        self.leverage = position.get('leverage', '1')
        self.liq_price = position.get('liqPrice', '')

    def key(self) -> str:
        """Уникальный ключ позиции (symbol + side)"""
        return f"{self.symbol}:{self.side}"


class PositionMonitor:
    """
    Мониторинг позиций в реальном времени

    Периодически проверяет открытые позиции и обнаруживает:
    - Закрытие по SL/TP
    - Частичное закрытие
    - Полное закрытие
    """

    def __init__(
        self,
        bot: Bot,
        trade_logger: TradeLogger,
        check_interval: int = 15,  # Интервал проверки в секундах
        testnet: bool = False,
        breakeven_manager: Optional['BreakevenManager'] = None
    ):
        self.bot = bot
        self.trade_logger = trade_logger
        self.check_interval = check_interval
        self.testnet = testnet
        self.breakeven_manager = breakeven_manager

        # Создаем клиент один раз
        self.client = BybitClient(testnet=testnet)

        # Храним snapshot открытых позиций по user_id
        # {user_id: {position_key: PositionSnapshot}}
        self.positions_cache: Dict[int, Dict[str, PositionSnapshot]] = {}

        # Активные user_id для мониторинга
        self.active_users: Set[int] = set()

        self._running = False
        self._task: Optional[asyncio.Task] = None

    def set_breakeven_manager(self, breakeven_manager: 'BreakevenManager'):
        """Установить BreakevenManager после инициализации"""
        self.breakeven_manager = breakeven_manager
        logger.info("BreakevenManager connected to PositionMonitor")

    def register_user(self, user_id: int):
        """Зарегистрировать пользователя для мониторинга"""
        self.active_users.add(user_id)
        logger.info(f"User {user_id} registered for position monitoring")

    def unregister_user(self, user_id: int):
        """Убрать пользователя из мониторинга"""
        self.active_users.discard(user_id)
        if user_id in self.positions_cache:
            del self.positions_cache[user_id]
        logger.info(f"User {user_id} unregistered from monitoring")

    async def start(self):
        """Запустить мониторинг в фоновом режиме"""
        if self._running:
            logger.warning("Position monitor already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Position monitor started (interval: {self.check_interval}s, testnet: {self.testnet})")

    async def stop(self):
        """Остановить мониторинг"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Position monitor stopped")

    async def _monitor_loop(self):
        """Основной цикл мониторинга"""
        while self._running:
            try:
                await self._check_all_users()
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}", exc_info=True)

            # Ждем до следующей проверки
            await asyncio.sleep(self.check_interval)

    async def _check_all_users(self):
        """Проверить позиции всех зарегистрированных пользователей"""
        for user_id in list(self.active_users):
            try:
                await self._check_user_positions(user_id)
            except Exception as e:
                logger.error(f"Error checking positions for user {user_id}: {e}")

    async def _check_user_positions(self, user_id: int):
        """Проверить позиции конкретного пользователя"""
        try:
            # Получаем текущие позиции с Bybit
            current_positions = await self.client.get_positions()

            # Преобразуем в словарь {position_key: PositionSnapshot}
            current_dict = {}
            for pos in current_positions:
                snapshot = PositionSnapshot(pos)
                current_dict[snapshot.key()] = snapshot

            # Получаем предыдущее состояние
            previous_dict = self.positions_cache.get(user_id, {})

            # Обнаруживаем изменения
            await self._detect_changes(user_id, previous_dict, current_dict)

            # Обновляем кэш
            self.positions_cache[user_id] = current_dict

        except Exception as e:
            logger.error(f"Error checking positions for user {user_id}: {e}")

    async def _detect_changes(
        self,
        user_id: int,
        previous: Dict[str, PositionSnapshot],
        current: Dict[str, PositionSnapshot]
    ):
        """Обнаружить изменения в позициях"""

        # Найти закрытые позиции
        for key, old_snapshot in previous.items():
            if key not in current:
                # Позиция полностью закрылась
                await self._handle_position_closed(user_id, old_snapshot)
            else:
                # Позиция еще открыта, проверяем частичное закрытие
                new_snapshot = current[key]
                if new_snapshot.size < old_snapshot.size:
                    # Частичное закрытие
                    await self._handle_partial_close(user_id, old_snapshot, new_snapshot)

    async def _handle_position_closed(self, user_id: int, snapshot: PositionSnapshot):
        """Обработка полного закрытия позиции"""

        # Определяем причину закрытия
        exit_price = snapshot.mark_price
        reason = self._determine_close_reason(snapshot, exit_price)

        # Рассчитываем метрики
        pnl_usd = snapshot.unrealized_pnl

        # Рассчитываем ROE%
        position_value = snapshot.size * snapshot.entry_price
        roe_percent = 0
        if position_value > 0:
            roe_percent = (pnl_usd / position_value) * float(snapshot.leverage) * 100

        # Логируем в TradeLogger
        try:
            await self.trade_logger.update_trade_on_close(
                user_id=user_id,
                symbol=snapshot.symbol,
                exit_price=exit_price,
                pnl_usd=pnl_usd,
                is_partial=False,
                testnet=self.testnet
            )
        except Exception as e:
            logger.error(f"Failed to log closed position: {e}")

        # Очищаем статус breakeven для этой позиции
        if self.breakeven_manager:
            self.breakeven_manager.clear_breakeven_status(snapshot.symbol, snapshot.side)

        # Отправляем уведомление
        await self._send_close_notification(
            user_id=user_id,
            snapshot=snapshot,
            reason=reason,
            exit_price=exit_price,
            pnl_usd=pnl_usd,
            roe_percent=roe_percent,
            is_partial=False
        )

        logger.info(f"Position closed for user {user_id}: {snapshot.symbol} {reason} PnL: ${pnl_usd:+.2f}")

    async def _handle_partial_close(
        self,
        user_id: int,
        old_snapshot: PositionSnapshot,
        new_snapshot: PositionSnapshot
    ):
        """Обработка частичного закрытия позиции"""

        closed_size = old_snapshot.size - new_snapshot.size
        percent_closed = (closed_size / old_snapshot.size) * 100

        # PnL пропорционально закрытой части
        partial_pnl = old_snapshot.unrealized_pnl * (percent_closed / 100)

        exit_price = new_snapshot.mark_price

        # Логируем
        try:
            await self.trade_logger.update_trade_on_close(
                user_id=user_id,
                symbol=old_snapshot.symbol,
                exit_price=exit_price,
                pnl_usd=partial_pnl,
                closed_qty=closed_size,
                is_partial=True,
                testnet=self.testnet
            )
        except Exception as e:
            logger.error(f"Failed to log partial close: {e}")

        # === AUTO BREAKEVEN ===
        # Если это partial close в плюсе, переносим SL на breakeven
        if self.breakeven_manager and partial_pnl > 0:
            try:
                await self.breakeven_manager.handle_partial_close(
                    user_id=user_id,
                    symbol=old_snapshot.symbol,
                    side=old_snapshot.side,
                    entry_price=old_snapshot.entry_price,
                    old_size=old_snapshot.size,
                    new_size=new_snapshot.size,
                    closed_pct=percent_closed
                )
            except Exception as be_error:
                logger.error(f"Breakeven error: {be_error}")

        # Отправляем уведомление
        await self._send_close_notification(
            user_id=user_id,
            snapshot=old_snapshot,
            reason="Partial TP",
            exit_price=exit_price,
            pnl_usd=partial_pnl,
            roe_percent=0,
            is_partial=True,
            closed_size=closed_size,
            remaining_size=new_snapshot.size
        )

        logger.info(f"Partial close for user {user_id}: {old_snapshot.symbol} {percent_closed:.1f}% PnL: ${partial_pnl:+.2f}")

    def _determine_close_reason(self, snapshot: PositionSnapshot, exit_price: float) -> str:
        """Определить причину закрытия позиции"""

        # Проверяем близость к Stop Loss
        if snapshot.stop_loss and snapshot.stop_loss != '':
            try:
                sl_price = float(snapshot.stop_loss)
                # Если цена в пределах 1% от SL (учёт проскальзывания маркет-ордера)
                tolerance = sl_price * 0.01
                if abs(exit_price - sl_price) <= tolerance:
                    return "Stop Loss"
            except (ValueError, TypeError):
                pass

        # Проверяем близость к Take Profit
        if snapshot.take_profit and snapshot.take_profit != '':
            try:
                tp_price = float(snapshot.take_profit)
                # Если цена в пределах 1% от TP
                tolerance = tp_price * 0.01
                if abs(exit_price - tp_price) <= tolerance:
                    return "Take Profit"
            except (ValueError, TypeError):
                pass

        # Проверяем ликвидацию
        if snapshot.liq_price and snapshot.liq_price != '':
            try:
                liq = float(snapshot.liq_price)
                tolerance = liq * 0.01
                if abs(exit_price - liq) <= tolerance:
                    return "Liquidation"
            except (ValueError, TypeError):
                pass

        # Иначе - закрытие по рынку
        return "Market Close"

    async def _send_close_notification(
        self,
        user_id: int,
        snapshot: PositionSnapshot,
        reason: str,
        exit_price: float,
        pnl_usd: float,
        roe_percent: float,
        is_partial: bool = False,
        closed_size: float = 0,
        remaining_size: float = 0
    ):
        """Отправить уведомление о закрытии позиции"""

        # Определяем эмодзи в зависимости от причины и результата
        if reason == "Stop Loss":
            emoji = "🔴"
        elif reason == "Take Profit":
            emoji = "🟢"
        elif reason == "Partial TP":
            emoji = "🟡"
        elif reason == "Liquidation":
            emoji = "💀"
        else:
            emoji = "⚪"

        # Эмодзи направления
        side_emoji = "🟢" if snapshot.side == "Buy" else "🔴"
        side_text = "Long" if snapshot.side == "Buy" else "Short"

        # Эмодзи PnL
        pnl_emoji = "💰" if pnl_usd >= 0 else "📉"

        # Формируем сообщение
        if is_partial:
            title = f"{emoji} <b>Частичное закрытие</b>"
            size_info = (
                f"Закрыто: {closed_size:.4f}\n"
                f"Осталось: {remaining_size:.4f}\n"
                f"Процент: {(closed_size / (closed_size + remaining_size) * 100):.1f}%"
            )
        else:
            title = f"{emoji} <b>{reason}</b>"
            size_info = f"Size: {snapshot.size:.4f}"

        message = f"""
{title}

📊 <b>{snapshot.symbol}</b> {side_emoji} {side_text}

<b>Цены:</b>
Entry: ${snapshot.entry_price:.4f}
Exit: ${exit_price:.4f}

<b>Позиция:</b>
{size_info}
Leverage: {snapshot.leverage}x

{pnl_emoji} <b>Результат:</b>
PnL: ${pnl_usd:+.2f}
"""

        # Добавляем ROE% если это полное закрытие
        if not is_partial and roe_percent != 0:
            message += f"ROE: {roe_percent:+.2f}%\n"

        message += f"\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"

        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=message.strip(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send notification to user {user_id}: {e}")


def create_position_monitor(
    bot: Bot,
    trade_logger: TradeLogger,
    testnet: bool = False,
    check_interval: int = 15,
    breakeven_manager: Optional['BreakevenManager'] = None
) -> PositionMonitor:
    """Создать экземпляр PositionMonitor"""
    return PositionMonitor(
        bot=bot,
        trade_logger=trade_logger,
        check_interval=check_interval,
        testnet=testnet,
        breakeven_manager=breakeven_manager
    )
