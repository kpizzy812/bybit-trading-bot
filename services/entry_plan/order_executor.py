"""
Entry Plan Order Executor

Размещение, активация и отмена ордеров для Entry Plans.
Установка SL/TP.
"""
import logging
from typing import Optional, List
from datetime import datetime, timezone

from services.entry_plan.models import EntryPlan, EntryOrder
from services.bybit_client_pool import client_pool
from utils.validators import round_qty, round_price

logger = logging.getLogger(__name__)


def evaluate_activation(
    activation_type: str,
    activation_level: Optional[float],
    current_price: float,
    max_distance_pct: float,
    side: str = None
) -> tuple[bool, str]:
    """
    Оценить условие активации с Direction sanity check.

    Direction sanity:
    - Long план на 95200, цена уже 96000 → reject (цена ушла вверх)
    - Short план на 95200, цена уже 94000 → reject (цена ушла вниз)

    Returns:
        (should_activate, reject_reason)
    """
    if activation_type == "immediate":
        return True, ""

    if not activation_level:
        return True, ""  # Нет уровня = сразу активируем

    # === DIRECTION SANITY CHECK ===
    # Проверяем что цена не ПРОСКОЧИЛА уровень (момент упущен)
    # Для touch планов: ждём подход цены к уровню с любой стороны
    if side and activation_type == "touch":
        distance_pct = (current_price - activation_level) / activation_level * 100

        # Используем больший порог для direction_sanity (5%) -
        # отменяем только если цена СИЛЬНО проскочила уровень
        sanity_threshold_pct = 5.0

        if side == "Long":
            # Для Long: отменяем если цена ушла НИЖЕ уровня слишком далеко
            # (цена проскочила вниз мимо точки входа)
            if distance_pct < -sanity_threshold_pct:
                return False, f"price_moved_below (current ${current_price:.2f} << level ${activation_level:.2f})"

        elif side == "Short":
            # Для Short: отменяем если цена ушла ВЫШЕ уровня слишком далеко
            # (цена проскочила вверх мимо точки входа)
            if distance_pct > sanity_threshold_pct:
                return False, f"price_moved_above (current ${current_price:.2f} >> level ${activation_level:.2f})"

    # === ACTIVATION CONDITIONS ===
    if activation_type == "touch":
        distance_pct = abs(current_price - activation_level) / activation_level * 100
        if distance_pct <= max_distance_pct:
            return True, ""
        return False, ""

    if activation_type == "price_above":
        if current_price >= activation_level:
            return True, ""
        return False, ""

    if activation_type == "price_below":
        if current_price <= activation_level:
            return True, ""
        return False, ""

    return False, ""


def evaluate_cancel_condition(
    condition: str,
    prices: dict,
    plan_created_at: str,
    time_valid_hours: float
) -> tuple[bool, str]:
    """
    Оценить одно условие отмены.

    Args:
        condition: Строка условия (break_below 95000, break_above 100000, etc.)
        prices: {'mark': float, 'last': float, 'high_24h': float, 'low_24h': float}
        plan_created_at: ISO datetime строка
        time_valid_hours: Максимальное время действия плана в часах

    Returns:
        (should_cancel, reason)
    """
    parts = condition.split()

    # === BREAK BELOW CONDITIONS ===
    if parts[0] == "break_below" and len(parts) >= 2:
        level = float(parts[1])
        if prices['mark'] < level:
            return True, f"break_below ${level:.2f} (mark=${prices['mark']:.2f})"

    if parts[0] == "break_below_close" and len(parts) >= 2:
        level = float(parts[1])
        if prices['last'] < level:
            return True, f"break_below_close ${level:.2f} (last=${prices['last']:.2f})"

    if parts[0] == "break_below_wick" and len(parts) >= 2:
        level = float(parts[1])
        if prices['low_24h'] < level:
            return True, f"break_below_wick ${level:.2f} (low24h=${prices['low_24h']:.2f})"

    # === BREAK ABOVE CONDITIONS ===
    if parts[0] == "break_above" and len(parts) >= 2:
        level = float(parts[1])
        if prices['mark'] > level:
            return True, f"break_above ${level:.2f} (mark=${prices['mark']:.2f})"

    if parts[0] == "break_above_close" and len(parts) >= 2:
        level = float(parts[1])
        if prices['last'] > level:
            return True, f"break_above_close ${level:.2f} (last=${prices['last']:.2f})"

    if parts[0] == "break_above_wick" and len(parts) >= 2:
        level = float(parts[1])
        if prices['high_24h'] > level:
            return True, f"break_above_wick ${level:.2f} (high24h=${prices['high_24h']:.2f})"

    # === TIME CONDITIONS ===
    if "time_valid_hours" in condition or "time_exceeded" in condition:
        try:
            # Парсим created_at с обработкой timezone
            created_str = plan_created_at.replace('Z', '+00:00')
            created = datetime.fromisoformat(created_str)
            # Если datetime naive - добавляем UTC timezone
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            hours_passed = (now - created).total_seconds() / 3600

            if hours_passed > time_valid_hours:
                return True, f"time_exceeded ({hours_passed:.1f}h > {time_valid_hours}h)"
        except Exception as e:
            logger.error(f"Error parsing time condition: {e}")

    return False, ""


def is_invalidation_cancel(reason: str) -> bool:
    """
    Проверить, является ли причина отмены "инвалидацией" плана.

    Инвалидация = план больше не актуален:
    - break_below / break_above (цена пробила уровень)
    - direction_sanity (цена ушла от зоны)
    - time_exceeded (истекло время)
    """
    invalidation_patterns = [
        "break_below",
        "break_above",
        "direction_sanity",
        "time_exceeded",
        "price_moved_above",
        "price_moved_below"
    ]
    return any(pattern in reason.lower() for pattern in invalidation_patterns)


async def place_entry_orders(plan: EntryPlan) -> int:
    """
    Разместить все entry ордера плана.

    Returns:
        Количество успешно размещённых ордеров
    """
    client = client_pool.get_client(plan.testnet)

    # Получить instrument info для округления
    instrument_info = await client.get_instrument_info(plan.symbol)
    tick_size = instrument_info.get('tickSize', '0.01')
    qty_step = instrument_info.get('qtyStep', '0.001')

    # Размещаем все entry ордера
    order_side = "Buy" if plan.side == "Long" else "Sell"
    placed_count = 0

    # Короткий ID для prefix (Bybit limit = 36 chars)
    short_plan_id = plan.plan_id[:8]

    for i, order_dict in enumerate(plan.orders):
        order = EntryOrder.from_dict(order_dict)

        try:
            # Округляем цену и qty
            price_str = round_price(order.price, tick_size)
            qty_str = round_qty(order.qty, qty_step)

            # Формируем client_order_id: EP:{plan_id}:{tag}
            tag = order.tag or f"E{i+1}"
            client_id = f"EP:{short_plan_id}:{tag}"[:36]

            # Размещаем ордер
            placed_order = await client.place_order(
                symbol=plan.symbol,
                side=order_side,
                order_type="Limit",
                qty=qty_str,
                price=price_str,
                client_order_id=client_id
            )

            # Обновляем статус ордера
            order.mark_placed(placed_order['orderId'])
            plan.orders[i] = order.to_dict()
            placed_count += 1

            logger.info(
                f"Entry order placed: {plan.symbol} {order_side} "
                f"@ ${order.price:.2f} qty={order.qty} tag={order.tag} "
                f"client_id={client_id}"
            )

        except Exception as e:
            logger.error(f"Failed to place entry order {i+1}: {e}")
            order.status = "cancelled"
            plan.orders[i] = order.to_dict()

    return placed_count


async def cancel_plan_orders(plan: EntryPlan) -> List[str]:
    """
    Отменить все открытые ордера плана.

    Returns:
        Список ID отменённых ордеров
    """
    client = client_pool.get_client(plan.testnet)
    short_plan_id = plan.plan_id[:8]

    cancelled = await client.cancel_orders_by_prefix(
        symbol=plan.symbol,
        client_order_id_prefix=f"EP:{short_plan_id}"
    )

    logger.info(f"Cancelled {len(cancelled)} orders for plan {plan.plan_id}")
    return cancelled


async def close_partial_position(plan: EntryPlan):
    """Закрыть частичную позицию market ордером"""
    if plan.filled_qty <= 0:
        return

    try:
        # Для закрытия Long нужен Sell, для Short — Buy
        close_side = "Sell" if plan.side == "Long" else "Buy"
        client = client_pool.get_client(plan.testnet)

        # Получаем instrument_info для округления
        instrument_info = await client.get_instrument_info(plan.symbol)
        qty_step = instrument_info.get('qtyStep', '0.001')

        qty_str = round_qty(plan.filled_qty, qty_step)

        short_plan_id = plan.plan_id[:8]
        await client.place_order(
            symbol=plan.symbol,
            side=close_side,
            order_type="Market",
            qty=qty_str,
            reduce_only=True,
            client_order_id=f"EP:{short_plan_id}:close"
        )

        logger.info(
            f"Closed partial position: {plan.symbol} {close_side} "
            f"qty={plan.filled_qty:.4f} (market)"
        )

    except Exception as e:
        logger.error(f"Failed to close partial position: {e}", exc_info=True)


async def setup_stop_loss(plan: EntryPlan) -> bool:
    """
    Установить Stop Loss для позиции.

    Returns:
        True если SL установлен успешно
    """
    try:
        client = client_pool.get_client(plan.testnet)

        await client.update_trading_stop(
            symbol=plan.symbol,
            stop_loss=str(plan.stop_price)
        )

        logger.info(f"SL set at ${plan.stop_price:.2f} for {plan.symbol}")
        return True

    except Exception as e:
        logger.error(f"Failed to set SL: {e}", exc_info=True)
        return False


async def cancel_existing_tp(plan: EntryPlan) -> int:
    """
    Отменить существующие TP ордера плана.

    Returns:
        Количество отменённых ордеров
    """
    try:
        client = client_pool.get_client(plan.testnet)
        short_plan_id = plan.plan_id[:8]

        # Ищем TP ордера по обоим форматам prefix:
        # - старый: EP:{plan_id}:TP
        # - новый: EP:{plan_id}:T{timestamp}
        cancelled_old = await client.cancel_orders_by_prefix(
            symbol=plan.symbol,
            client_order_id_prefix=f"EP:{short_plan_id}:TP"
        )
        cancelled_new = await client.cancel_orders_by_prefix(
            symbol=plan.symbol,
            client_order_id_prefix=f"EP:{short_plan_id}:T"
        )

        total_cancelled = len(cancelled_old) + len(cancelled_new)
        if total_cancelled:
            logger.info(f"Cancelled {total_cancelled} existing TP orders for plan {plan.plan_id}")

        return total_cancelled
    except Exception as e:
        logger.error(f"Error cancelling existing TP: {e}")
        return 0


async def setup_ladder_tp(
    plan: EntryPlan,
    use_filled_qty: bool = False
) -> bool:
    """
    Установить ladder TP ордера.

    Args:
        plan: EntryPlan
        use_filled_qty: Использовать filled_qty вместо total_qty

    Returns:
        True если TP установлены успешно
    """
    if not plan.targets:
        return False

    try:
        client = client_pool.get_client(plan.testnet)
        instrument_info = await client.get_instrument_info(plan.symbol)
        lot_size = instrument_info.get('lotSizeFilter', {})
        price_filter = instrument_info.get('priceFilter', {})
        tick_size = price_filter.get('tickSize', '0.01')
        qty_step = lot_size.get('qtyStep', '0.001')
        min_order_qty = float(lot_size.get('minOrderQty', '0.001'))

        base_qty = plan.filled_qty if use_filled_qty else plan.total_qty
        position_side = "Buy" if plan.side == "Long" else "Sell"

        logger.info(f"Setting ladder TP: base_qty={base_qty}, min_order_qty={min_order_qty}, qty_step={qty_step}")

        tp_levels = []
        skipped_qty = 0.0  # Накопленный qty от пропущенных уровней

        for target in plan.targets:
            partial_pct = target.get('partial_close_pct', 100)
            tp_qty_raw = (base_qty * partial_pct) / 100 + skipped_qty
            tp_qty = round_qty(tp_qty_raw, qty_step, round_down=True)

            if float(tp_qty) < min_order_qty:
                # Qty слишком маленький — накапливаем для следующего уровня
                skipped_qty = tp_qty_raw
                logger.debug(f"TP level skipped (qty {tp_qty} < min {min_order_qty}), accumulating...")
                continue

            skipped_qty = 0.0  # Сбрасываем после успешного добавления

            if float(tp_qty) > 0:
                tp_levels.append({
                    'price': round_price(target['price'], tick_size),
                    'qty': tp_qty
                })

        # Если остался skipped_qty после всех уровней — добавляем к последнему TP
        if skipped_qty > 0 and tp_levels:
            last_tp = tp_levels[-1]
            new_qty = float(last_tp['qty']) + skipped_qty
            last_tp['qty'] = round_qty(new_qty, qty_step, round_down=True)
            logger.info(f"Added remaining {skipped_qty:.4f} to last TP level")

        if tp_levels:
            short_plan_id = plan.plan_id[:8]
            # Добавляем timestamp для уникальности client_order_id
            # (Bybit отклоняет дубликаты orderLinkId даже после отмены)
            import time
            ts = int(time.time() * 1000) % 100000  # Последние 5 цифр timestamp
            await client.place_ladder_tp(
                symbol=plan.symbol,
                position_side=position_side,
                tp_levels=tp_levels,
                client_order_id_prefix=f"EP:{short_plan_id}:T{ts}"
            )
            logger.info(
                f"Ladder TP set: {len(tp_levels)} levels for {plan.symbol}, "
                f"base_qty={base_qty:.4f}"
            )
            return True

        return False

    except Exception as e:
        logger.error(f"Error setting ladder TP: {e}", exc_info=True)
        return False
