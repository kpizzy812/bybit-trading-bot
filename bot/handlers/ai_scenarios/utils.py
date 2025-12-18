"""
AI Scenarios Utils

Утилитарные функции для работы с AI сценариями.
Вынесены из ai_scenarios.py для модульности.
"""
import math
import uuid
from typing import Optional

from loguru import logger

import config
from services.entry_plan import EntryPlan, EntryOrder


def parse_leverage(leverage_info, default: int = 5) -> int:
    """
    Парсит leverage из разных форматов.

    Args:
        leverage_info: Может быть:
            - dict: {"recommended": 3, "max_safe": 10}
            - int/float: 3
            - str: "3x" или "3"
        default: Значение по умолчанию

    Returns:
        int: Значение leverage
    """
    if leverage_info is None:
        return default

    if isinstance(leverage_info, dict):
        raw = leverage_info.get("recommended", default)
    else:
        raw = leverage_info

    # Парсим значение
    if isinstance(raw, (int, float)):
        return int(raw)

    if isinstance(raw, str):
        # Убираем "x" если есть: "3x" -> "3"
        cleaned = raw.lower().replace("x", "").strip()
        try:
            return int(float(cleaned))
        except (ValueError, TypeError):
            return default

    return default


def calculate_confidence_adjusted_risk(
    base_risk: float,
    confidence: float,
    scaling_enabled: bool = True
) -> tuple[float, float]:
    """
    Масштабировать риск на основе confidence AI сценария.

    Логика:
    - Высокий confidence (0.9+) → увеличиваем риск до 130%
    - Средний confidence (0.6-0.8) → риск около базового
    - Низкий confidence (<0.6) → уменьшаем риск до 70%

    Args:
        base_risk: Базовый риск в USD
        confidence: Confidence от 0 до 1
        scaling_enabled: Включено ли масштабирование

    Returns:
        (adjusted_risk, multiplier)
    """
    if not scaling_enabled:
        return base_risk, 1.0

    # Проверка минимального confidence
    if confidence < config.MIN_CONFIDENCE_THRESHOLD:
        logger.warning(f"Confidence {confidence:.2f} below threshold {config.MIN_CONFIDENCE_THRESHOLD}")

    # Линейная интерполяция между MIN и MAX multiplier
    # confidence=0 → MIN_MULTIPLIER, confidence=1 → MAX_MULTIPLIER
    min_mult = config.MIN_CONFIDENCE_MULTIPLIER
    max_mult = config.MAX_CONFIDENCE_MULTIPLIER

    multiplier = min_mult + (confidence * (max_mult - min_mult))

    # Ограничиваем в пределах [MIN, MAX]
    multiplier = max(min_mult, min(max_mult, multiplier))

    adjusted_risk = base_risk * multiplier

    # Не превышаем max_risk_per_trade
    adjusted_risk = min(adjusted_risk, config.MAX_RISK_PER_TRADE)

    logger.info(
        f"Risk scaling: base=${base_risk:.2f}, confidence={confidence:.2f}, "
        f"multiplier={multiplier:.2f}, adjusted=${adjusted_risk:.2f}"
    )

    return adjusted_risk, multiplier


def parse_entry_plan(
    scenario: dict,
    trade_id: str,
    user_id: int,
    symbol: str,
    side: str,
    risk_usd: float,
    leverage: int,
    testnet: bool,
    qty_step: str = "0.001",
    tick_size: str = "0.01",
    current_price: float = 0.0
) -> Optional[EntryPlan]:
    """
    Распарсить entry_plan из AI сценария с Risk-on-plan моделью.

    Risk-on-plan формула:
        P_avg = Σ(w_i * p_i)  — средневзвешенная цена входа
        Q_total = R / |P_avg - SL|  — общий размер позиции
        Q_i = Q_total * w_i  — размер каждого ордера

    Гарантирует: суммарный риск до SL ≤ risk_usd независимо от того,
    сколько entry ордеров исполнится.

    Returns:
        EntryPlan или None если сценарий использует старый формат
    """
    entry_plan_data = scenario.get('entry_plan')

    if not entry_plan_data:
        return None  # Fallback на старую логику

    # Парсим stop_loss
    stop_loss = scenario.get('stop_loss', {})
    stop_price = stop_loss.get('recommended', 0)

    if not stop_price:
        logger.error("Entry plan requires stop_loss.recommended")
        return None

    # === RISK-ON-PLAN: Расчёт P_avg ===
    orders_data = entry_plan_data.get('orders', [])
    if not orders_data:
        logger.error("Entry plan requires at least one order")
        return None

    # Считаем P_avg = Σ(w_i * p_i) где w_i = size_pct / 100
    p_avg = 0.0
    total_weight = 0.0

    for order_data in orders_data:
        price = order_data['price']
        weight = order_data['size_pct'] / 100
        p_avg += price * weight
        total_weight += weight

    # Валидация: сумма весов должна быть ~1.0 (100%)
    if abs(total_weight - 1.0) > 0.01:
        logger.warning(f"Entry plan weights sum to {total_weight*100:.1f}%, expected 100%")
        # Нормализуем если нужно
        if total_weight > 0:
            p_avg = p_avg / total_weight

    # === Валидация SL относительно стороны ===
    # Для Buy (long): SL должен быть ниже P_avg
    # Для Sell (short): SL должен быть выше P_avg
    if side.lower() == "buy" and stop_price >= p_avg:
        logger.error(
            f"Invalid SL for Buy: SL={stop_price} >= P_avg={p_avg}. "
            f"Stop Loss for long must be BELOW entry."
        )
        return None
    elif side.lower() == "sell" and stop_price <= p_avg:
        logger.error(
            f"Invalid SL for Sell: SL={stop_price} <= P_avg={p_avg}. "
            f"Stop Loss for short must be ABOVE entry."
        )
        return None

    # === RISK-ON-PLAN: Расчёт Q_total ===
    stop_distance = abs(p_avg - stop_price)

    if stop_distance <= 0:
        logger.error(f"Invalid stop distance: P_avg={p_avg}, SL={stop_price}")
        return None

    q_total_raw = risk_usd / stop_distance
    qty_step_float = float(qty_step)
    min_qty = qty_step_float  # Минимальный qty = один шаг

    # Округляем q_total вниз (floor) чтобы не превысить риск
    q_total = math.floor(q_total_raw / qty_step_float) * qty_step_float

    logger.info(
        f"Risk-on-plan: P_avg=${p_avg:.2f}, SL=${stop_price:.2f}, "
        f"distance=${stop_distance:.2f}, Q_total={q_total:.6f}"
    )

    # === Auto-downgrade: проверяем достаточно ли qty для ladder ===
    n_orders = len(orders_data)
    min_total_for_ladder = min_qty * n_orders

    effective_mode = entry_plan_data.get('mode', 'ladder')
    downgrade_reason = None

    if q_total < min_qty:
        # Даже для одного ордера не хватает
        logger.warning(f"Q_total {q_total} < min_qty {min_qty}, cannot create plan")
        return None

    if q_total < min_total_for_ladder and n_orders > 1:
        # Автоматический downgrade ladder → single или меньше ордеров
        max_possible_orders = int(q_total / min_qty)

        if max_possible_orders == 0:
            logger.warning(f"Cannot create any orders with Q_total={q_total}")
            return None
        elif max_possible_orders == 1:
            # Downgrade to single - выбираем лучший ордер (ближайший к поддержке для long)
            effective_mode = "single"
            downgrade_reason = f"min_qty_constraint: {n_orders}→1 orders"
            # Для long берём самый нижний, для short - самый верхний
            if side.lower() == "long":
                best_order = min(orders_data, key=lambda x: x['price'])
            else:
                best_order = max(orders_data, key=lambda x: x['price'])
            orders_data = [{'price': best_order['price'], 'size_pct': 100,
                          'tag': best_order.get('tag', 'E1'),
                          'source_level': best_order.get('source_level', '')}]
            n_orders = 1
            logger.info(f"Auto-downgrade: ladder→single, best price=${best_order['price']}")
        else:
            # Можем использовать несколько ордеров, но не все
            effective_mode = "ladder"
            downgrade_reason = f"min_qty_constraint: {n_orders}→{max_possible_orders} orders"
            # Оставляем лучшие ордера
            if side.lower() == "long":
                sorted_orders = sorted(orders_data, key=lambda x: x['price'])
            else:
                sorted_orders = sorted(orders_data, key=lambda x: x['price'], reverse=True)
            orders_data = sorted_orders[:max_possible_orders]
            # Перераспределяем веса равномерно
            new_pct = 100 / max_possible_orders
            for od in orders_data:
                od['size_pct'] = new_pct
            n_orders = max_possible_orders
            logger.info(f"Auto-downgrade: {len(sorted_orders)}→{max_possible_orders} orders")

    # === Создаём ордера с правильным округлением ===
    # Используем floor для каждого qty, потом добавляем остаток
    orders = []
    allocated_qty = 0.0

    for i, order_data in enumerate(orders_data):
        weight = order_data['size_pct'] / 100
        order_qty_raw = q_total * weight
        # Floor округление чтобы сумма не превысила q_total
        order_qty = math.floor(order_qty_raw / qty_step_float) * qty_step_float
        # Гарантируем минимум min_qty для каждого ордера
        order_qty = max(order_qty, min_qty)

        orders.append({
            'price': order_data['price'],
            'size_pct': order_data['size_pct'],
            'qty': order_qty,
            'order_type': order_data.get('type', 'limit'),
            'tag': order_data.get('tag', f"E{i+1}"),
            'source_level': order_data.get('source_level', '')
        })
        allocated_qty += order_qty

    # Если выделили больше чем q_total (из-за min_qty constraint), урезаем
    if allocated_qty > q_total and len(orders) > 1:
        # Пересчитываем q_total под фактическое распределение
        q_total = allocated_qty
        logger.warning(f"Q_total adjusted to {q_total} due to min_qty constraints")

    # Добавляем остаток в средний ордер (или первый если один)
    remainder = q_total - allocated_qty
    if remainder >= qty_step_float and orders:
        middle_idx = len(orders) // 2
        orders[middle_idx]['qty'] += math.floor(remainder / qty_step_float) * qty_step_float
        logger.debug(f"Added remainder {remainder:.6f} to order {middle_idx}")

    # Конвертируем в EntryOrder объекты
    entry_orders = []
    for order_dict in orders:
        entry_orders.append(EntryOrder(
            price=order_dict['price'],
            size_pct=order_dict['size_pct'],
            qty=order_dict['qty'],
            order_type=order_dict['order_type'],
            tag=order_dict['tag'],
            source_level=order_dict['source_level']
        ).to_dict())

    # Пересчитываем фактический total_qty
    actual_total_qty = sum(o['qty'] for o in entry_orders)

    if downgrade_reason:
        logger.info(f"Entry plan downgraded: {downgrade_reason}")

    # Парсим activation
    activation = entry_plan_data.get('activation', {})

    # === EXECUTION NORMALIZER: Smart Activation Override ===
    # LLM отдаёт "намерение", система решает как исполнять
    original_activation = activation.copy()
    override_reason = None

    activation_type = activation.get('type', 'immediate')
    activation_level = activation.get('level')

    # Получаем границы entry zone
    entry_prices = [o['price'] for o in orders_data]
    entry_max = max(entry_prices) if entry_prices else 0
    entry_min = min(entry_prices) if entry_prices else 0

    if activation_type == 'touch' and activation_level and current_price > 0:
        # === Правило №1: Context-aware activation ===
        # Если мы уже в зоне или ниже — ставим лимитки сразу

        if side.lower() == 'long':
            # Long ladder: если current_price < entry_max → price_below
            if current_price < activation_level:
                activation = {
                    'type': 'price_below',
                    'level': activation_level,
                    'max_distance_pct': activation.get('max_distance_pct', 0.5)
                }
                override_reason = f"dip_buy_context: price ${current_price:.2f} < level ${activation_level:.2f}"
                logger.info(
                    f"Activation override: touch→price_below @ ${activation_level:.2f} "
                    f"(current ${current_price:.2f}, reason: {override_reason})"
                )

        elif side.lower() == 'short':
            # Short ladder: если current_price > entry_min → price_above
            if current_price > activation_level:
                activation = {
                    'type': 'price_above',
                    'level': activation_level,
                    'max_distance_pct': activation.get('max_distance_pct', 0.5)
                }
                override_reason = f"rally_sell_context: price ${current_price:.2f} > level ${activation_level:.2f}"
                logger.info(
                    f"Activation override: touch→price_above @ ${activation_level:.2f} "
                    f"(current ${current_price:.2f}, reason: {override_reason})"
                )

        # === Правило №2: Safety override для парадоксов ===
        # Если все entry prices по одну сторону от activation, а цена далеко — immediate
        if not override_reason:
            if side.lower() == 'long' and all(p < activation_level for p in entry_prices):
                # Все entries ниже activation, а цена ещё ниже → нонсенс ждать touch
                if current_price < entry_min:
                    activation = {'type': 'immediate'}
                    override_reason = f"nonsensical_activation: all entries below activation, price below entries"
                    logger.info(f"Activation safety override: touch→immediate ({override_reason})")

            elif side.lower() == 'short' and all(p > activation_level for p in entry_prices):
                if current_price > entry_max:
                    activation = {'type': 'immediate'}
                    override_reason = f"nonsensical_activation: all entries above activation, price above entries"
                    logger.info(f"Activation safety override: touch→immediate ({override_reason})")

    # Логируем override для фидбека LLM
    if override_reason:
        logger.info(
            f"Activation normalized: original={original_activation}, "
            f"effective={activation}, reason={override_reason}"
        )

    # Парсим targets
    targets = scenario.get('targets', [])

    plan = EntryPlan(
        plan_id=str(uuid.uuid4()),
        trade_id=trade_id,
        user_id=user_id,
        symbol=symbol,
        side=side,
        mode=effective_mode,
        orders=entry_orders,
        total_qty=actual_total_qty,
        activation_type=activation.get('type', 'immediate'),
        activation_level=activation.get('level'),
        max_distance_pct=activation.get('max_distance_pct', 0.5),
        cancel_if=entry_plan_data.get('cancel_if', []),
        time_valid_hours=entry_plan_data.get('time_valid_hours', 48),
        stop_price=stop_price,
        targets=targets,
        leverage=leverage,
        risk_usd=risk_usd,
        testnet=testnet
    )

    downgrade_info = f" (downgraded: {downgrade_reason})" if downgrade_reason else ""
    logger.info(
        f"Parsed entry_plan: {symbol} {side}, mode={effective_mode}, "
        f"{len(entry_orders)} orders, Q_total={actual_total_qty:.6f}, P_avg=${p_avg:.2f}{downgrade_info}"
    )

    return plan


# Алиас для обратной совместимости
_parse_leverage = parse_leverage
