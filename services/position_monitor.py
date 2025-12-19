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
import logging
from typing import Dict, Optional, Set, TYPE_CHECKING
from datetime import datetime
from aiogram import Bot
from services.base_monitor import BaseMonitor
from services.bybit_client_pool import client_pool
from services.trade_logger import TradeLogger

if TYPE_CHECKING:
    from services.breakeven_manager import BreakevenManager
    from services.post_sl_analyzer import PostSLAnalyzer
    from services.supervisor_client import SupervisorClient
    from services.trade_logger import TradeRecord

# Feedback integration
from services.feedback import feedback_collector, feedback_client, feedback_queue

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


class PositionMonitor(BaseMonitor):
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
        breakeven_manager: Optional['BreakevenManager'] = None,
        post_sl_analyzer: Optional['PostSLAnalyzer'] = None,
        supervisor_client: Optional['SupervisorClient'] = None
    ):
        super().__init__(check_interval=check_interval)
        self.bot = bot
        self.trade_logger = trade_logger
        self.testnet = testnet
        self.breakeven_manager = breakeven_manager
        self.post_sl_analyzer = post_sl_analyzer
        self.supervisor_client = supervisor_client

        # Храним snapshot открытых позиций по user_id
        # {user_id: {position_key: PositionSnapshot}}
        self.positions_cache: Dict[int, Dict[str, PositionSnapshot]] = {}

        # Активные user_id для мониторинга
        self.active_users: Set[int] = set()

        # Счётчик для supervisor sync (каждые N итераций)
        self._supervisor_sync_counter = 0
        self._supervisor_sync_interval = 240  # sync каждые 240 итераций (1 час при 15 сек интервале)

    @property
    def monitor_name(self) -> str:
        return "Position monitor"

    @property
    def client(self):
        """Получить Bybit клиент для текущего режима"""
        return client_pool.get_client(self.testnet)

    def set_breakeven_manager(self, breakeven_manager: 'BreakevenManager'):
        """Установить BreakevenManager после инициализации"""
        self.breakeven_manager = breakeven_manager
        logger.info("BreakevenManager connected to PositionMonitor")

    def set_post_sl_analyzer(self, post_sl_analyzer: 'PostSLAnalyzer'):
        """Установить PostSLAnalyzer после инициализации"""
        self.post_sl_analyzer = post_sl_analyzer
        logger.info("PostSLAnalyzer connected to PositionMonitor")

    def set_supervisor_client(self, supervisor_client: 'SupervisorClient'):
        """Установить SupervisorClient после инициализации"""
        self.supervisor_client = supervisor_client
        logger.info("SupervisorClient connected to PositionMonitor")

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

    async def _check_cycle(self):
        """Основной цикл проверки позиций и supervisor sync"""
        # Проверить позиции всех пользователей
        await self._check_all_users()

        # Supervisor sync каждые N итераций
        self._supervisor_sync_counter += 1
        if self._supervisor_sync_counter >= self._supervisor_sync_interval:
            self._supervisor_sync_counter = 0
            await self._supervisor_sync_all_users()

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

    async def _supervisor_sync_all_users(self):
        """Sync positions with Supervisor API for all users"""
        import config as cfg
        if not self.supervisor_client or not cfg.SUPERVISOR_ENABLED:
            return

        from services.supervisor_client import PositionSnapshot as SupervisorSnapshot
        from services.events import event_bus, SupervisorAdviceEvent

        for user_id in list(self.active_users):
            try:
                # Get current positions from cache
                positions = self.positions_cache.get(user_id, {})
                if not positions:
                    continue

                # Convert to supervisor snapshots
                supervisor_snapshots = []
                for key, snapshot in positions.items():
                    # Get trade_id from trade logger
                    trade = await self.trade_logger.get_open_trade_by_symbol(
                        user_id=user_id,
                        symbol=snapshot.symbol,
                        testnet=self.testnet
                    )
                    trade_id = trade.trade_id if trade else f"auto_{snapshot.symbol}_{snapshot.side}"

                    # Calculate PnL %
                    pnl_pct = 0
                    if snapshot.entry_price > 0:
                        if snapshot.side == "Buy":
                            pnl_pct = ((snapshot.mark_price - snapshot.entry_price) / snapshot.entry_price) * 100
                        else:
                            pnl_pct = ((snapshot.entry_price - snapshot.mark_price) / snapshot.entry_price) * 100

                    sup_snapshot = SupervisorSnapshot(
                        trade_id=trade_id,
                        symbol=snapshot.symbol,
                        side="Long" if snapshot.side == "Buy" else "Short",
                        qty=snapshot.size,
                        entry_price=snapshot.entry_price,
                        mark_price=snapshot.mark_price,
                        unrealized_pnl=snapshot.unrealized_pnl,
                        pnl_pct=pnl_pct,
                        leverage=int(snapshot.leverage) if snapshot.leverage else 1,
                        liq_price=float(snapshot.liq_price) if snapshot.liq_price else None,
                        sl_current=float(snapshot.stop_loss) if snapshot.stop_loss else None,
                        tp_current=None,  # TODO: parse TP list if available
                        updated_at=datetime.utcnow().isoformat() + "Z"
                    )
                    supervisor_snapshots.append(sup_snapshot)

                # Sync with API
                if supervisor_snapshots:
                    advice_packs = await self.supervisor_client.sync_positions(
                        user_id=user_id,
                        positions=supervisor_snapshots
                    )

                    # Emit events for advice packs (handled by supervisor handler)
                    for advice in advice_packs:
                        # Check urgency threshold
                        urgency = advice.risk_state if hasattr(advice, 'risk_state') else 'low'
                        if self._should_notify(urgency):
                            await event_bus.emit(SupervisorAdviceEvent(
                                user_id=user_id,
                                advice=advice
                            ))

            except Exception as e:
                logger.warning(f"Supervisor sync error for user {user_id}: {e}")

    def _should_notify(self, risk_state: str) -> bool:
        """Check if notification should be sent based on urgency threshold"""
        import config as cfg
        threshold = cfg.SUPERVISOR_NOTIFICATION_THRESHOLD.lower()

        urgency_levels = {
            'low': 0,
            'med': 1,
            'medium': 1,
            'high': 2,
            'critical': 3
        }

        threshold_level = urgency_levels.get(threshold, 1)
        risk_level = urgency_levels.get(risk_state.lower(), 0)

        return risk_level >= threshold_level

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
                else:
                    # Позиция не изменилась — обновляем MAE/MFE
                    await self._update_mae_mfe_for_position(user_id, new_snapshot)

    async def _handle_position_closed(self, user_id: int, snapshot: PositionSnapshot):
        """Обработка полного закрытия позиции"""

        # Получаем реальный PnL с биржи
        closed_pnl_data = await self.client.get_closed_pnl(symbol=snapshot.symbol)

        if closed_pnl_data:
            pnl_usd = float(closed_pnl_data.get('closedPnl', snapshot.unrealized_pnl))
            exit_price = float(closed_pnl_data.get('avgExitPrice', snapshot.mark_price))
        else:
            # Fallback к snapshot данным
            pnl_usd = snapshot.unrealized_pnl
            exit_price = snapshot.mark_price
            logger.warning(f"Could not get closed PnL for {snapshot.symbol}, using snapshot")

        # Рассчитываем ROE%
        position_value = snapshot.size * snapshot.entry_price
        roe_percent = 0
        if position_value > 0:
            roe_percent = (pnl_usd / position_value) * float(snapshot.leverage) * 100

        # Находим trade по символу (нужен для определения причины закрытия)
        trade = await self.trade_logger.get_open_trade_by_symbol(
            user_id=user_id,
            symbol=snapshot.symbol,
            testnet=self.testnet
        )
        trade_id = trade.trade_id if trade else None

        # Определяем причину закрытия (с fallback к TradeRecord)
        reason = self._determine_close_reason(snapshot, exit_price, trade)

        # Логируем в TradeLogger
        if trade_id:
            try:
                # Определяем reason для fills
                fill_reason = self._map_close_reason_to_fill(reason)

                await self.trade_logger.update_trade_on_close(
                    user_id=user_id,
                    trade_id=trade_id,
                    exit_price=exit_price,
                    pnl_usd=pnl_usd,
                    closed_qty=snapshot.size,
                    reason=fill_reason,
                    is_final=True,
                    is_taker=True,  # SL/TP обычно taker
                    testnet=self.testnet
                )

                # Финализируем MAE/MFE
                await self.trade_logger.finalize_mae_mfe(user_id, trade_id, self.testnet)

            except Exception as e:
                logger.error(f"Failed to log closed position: {e}")
        else:
            logger.warning(f"No open trade found for {snapshot.symbol} to update on close")

        # Очищаем статус breakeven для этой позиции
        if self.breakeven_manager:
            self.breakeven_manager.clear_breakeven_status(snapshot.symbol, snapshot.side)

        # === POST-SL ANALYSIS ===
        # Если закрытие по Stop Loss, регистрируем для анализа
        if reason == "Stop Loss" and self.post_sl_analyzer and trade_id:
            try:
                await self.post_sl_analyzer.register_sl_hit(
                    trade_id=trade_id,
                    user_id=user_id,
                    symbol=snapshot.symbol,
                    side=snapshot.side,
                    entry_price=snapshot.entry_price,
                    sl_price=exit_price
                )
            except Exception as psl_error:
                logger.error(f"Post-SL analysis registration error: {psl_error}")

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

        # === SYNTRA FEEDBACK ===
        # Отправляем feedback в Syntra для learning системы
        if trade_id:
            # Получаем обновлённый trade record (после update_trade_on_close)
            updated_trade = await self.trade_logger.get_trade_by_id(
                user_id=user_id,
                trade_id=trade_id,
                testnet=self.testnet
            )
            if updated_trade:
                await self._send_trade_feedback(user_id, updated_trade)

    async def _handle_partial_close(
        self,
        user_id: int,
        old_snapshot: PositionSnapshot,
        new_snapshot: PositionSnapshot
    ):
        """Обработка частичного закрытия позиции"""

        closed_size = old_snapshot.size - new_snapshot.size
        percent_closed = (closed_size / old_snapshot.size) * 100

        # Получаем реальный PnL с биржи
        closed_pnl_data = await self.client.get_closed_pnl(symbol=old_snapshot.symbol)

        if closed_pnl_data:
            partial_pnl = float(closed_pnl_data.get('closedPnl', 0))
            exit_price = float(closed_pnl_data.get('avgExitPrice', new_snapshot.mark_price))
        else:
            # Fallback - пропорциональный расчёт
            partial_pnl = old_snapshot.unrealized_pnl * (percent_closed / 100)
            exit_price = new_snapshot.mark_price
            logger.warning(f"Could not get closed PnL for {old_snapshot.symbol} partial, using calculated")

        # Находим trade_id
        trade = await self.trade_logger.get_open_trade_by_symbol(
            user_id=user_id,
            symbol=old_snapshot.symbol,
            testnet=self.testnet
        )
        trade_id = trade.trade_id if trade else None

        # Логируем
        if trade_id:
            try:
                await self.trade_logger.update_trade_on_close(
                    user_id=user_id,
                    trade_id=trade_id,
                    exit_price=exit_price,
                    pnl_usd=partial_pnl,
                    closed_qty=closed_size,
                    reason="tp1",  # Partial = TP level
                    is_final=False,
                    is_taker=True,
                    testnet=self.testnet
                )
            except Exception as e:
                logger.error(f"Failed to log partial close: {e}")
        else:
            logger.warning(f"No open trade found for {old_snapshot.symbol} to update on partial close")

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

    def _determine_close_reason(
        self,
        snapshot: PositionSnapshot,
        exit_price: float,
        trade: Optional['TradeRecord'] = None
    ) -> str:
        """Определить причину закрытия позиции.

        Сначала проверяет данные из snapshot (актуальные ордера Bybit),
        затем fallback к TradeRecord (запланированные цены).
        """
        # Собираем SL цену (snapshot имеет приоритет, но может быть пустым после срабатывания)
        sl_price = None
        if snapshot.stop_loss and snapshot.stop_loss != '':
            try:
                sl_price = float(snapshot.stop_loss)
            except (ValueError, TypeError):
                pass
        # Fallback к TradeRecord если snapshot пустой
        if sl_price is None and trade and trade.stop_price:
            sl_price = trade.stop_price

        # Собираем TP цену
        tp_price = None
        if snapshot.take_profit and snapshot.take_profit != '':
            try:
                tp_price = float(snapshot.take_profit)
            except (ValueError, TypeError):
                pass
        # Fallback к TradeRecord
        if tp_price is None and trade and trade.tp_price:
            tp_price = trade.tp_price

        # Проверяем близость к Stop Loss (увеличенный tolerance для market ордеров)
        if sl_price:
            tolerance = sl_price * 0.005  # 0.5% для учёта проскальзывания маркет-ордера
            if abs(exit_price - sl_price) <= tolerance:
                return "Stop Loss"

        # Проверяем близость к Take Profit
        if tp_price:
            tolerance = tp_price * 0.005  # 0.5% tolerance
            if abs(exit_price - tp_price) <= tolerance:
                return "Take Profit"

        # Проверяем ликвидацию
        if snapshot.liq_price and snapshot.liq_price != '':
            try:
                liq = float(snapshot.liq_price)
                tolerance = liq * 0.005  # 0.5% tolerance
                if abs(exit_price - liq) <= tolerance:
                    return "Liquidation"
            except (ValueError, TypeError):
                pass

        # Иначе - закрытие по рынку
        return "Market Close"

    def _map_close_reason_to_fill(self, reason: str) -> str:
        """Преобразовать причину закрытия в reason для TradeFill"""
        mapping = {
            "Stop Loss": "sl",
            "Take Profit": "tp1",
            "Partial TP": "tp1",
            "Liquidation": "liquidation",
            "Market Close": "manual"
        }
        return mapping.get(reason, "manual")

    async def _update_mae_mfe_for_position(self, user_id: int, snapshot: PositionSnapshot):
        """Обновить MAE/MFE для открытой позиции"""
        try:
            trade = await self.trade_logger.get_open_trade_by_symbol(
                user_id=user_id,
                symbol=snapshot.symbol,
                testnet=self.testnet
            )
            if trade:
                await self.trade_logger.update_mae_mfe(
                    user_id=user_id,
                    trade_id=trade.trade_id,
                    current_price=snapshot.mark_price,
                    testnet=self.testnet
                )
        except Exception as e:
            logger.debug(f"MAE/MFE update error for {snapshot.symbol}: {e}")

    async def _send_trade_feedback(self, user_id: int, trade):
        """
        Отправить feedback в Syntra для learning системы.

        Собирает 4 слоя телеметрии и отправляет в API.
        При ошибке добавляет в Redis очередь для retry.
        """
        # Только для сделок от Syntra
        if trade.scenario_source != "syntra" and not trade.scenario_snapshot:
            logger.debug(f"Skip feedback: not syntra trade {trade.trade_id}")
            return

        try:
            # Собираем feedback из TradeRecord
            feedback = feedback_collector.collect(trade)

            if not feedback:
                logger.debug(f"Skip feedback: collector returned None for {trade.trade_id}")
                return

            # Пытаемся отправить напрямую
            try:
                response = await feedback_client.submit(feedback)
                logger.info(
                    f"Feedback sent: trade_id={trade.trade_id}, "
                    f"duplicate={response.get('duplicate', False)}"
                )
            except Exception as e:
                # Ошибка отправки — добавляем в очередь
                logger.warning(f"Feedback submit failed, queuing: {e}")
                await feedback_queue.enqueue(feedback)

        except Exception as e:
            logger.error(f"Feedback collection failed for trade {trade.trade_id}: {e}")

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
    breakeven_manager: Optional['BreakevenManager'] = None,
    post_sl_analyzer: Optional['PostSLAnalyzer'] = None,
    supervisor_client: Optional['SupervisorClient'] = None
) -> PositionMonitor:
    """Создать экземпляр PositionMonitor"""
    return PositionMonitor(
        bot=bot,
        trade_logger=trade_logger,
        check_interval=check_interval,
        testnet=testnet,
        breakeven_manager=breakeven_manager,
        post_sl_analyzer=post_sl_analyzer,
        supervisor_client=supervisor_client
    )
