from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Union


def round_qty(qty: float, qty_step: float, round_down: bool = True) -> str:
    """
    Округляет количество до qtyStep используя Decimal для точности.

    Args:
        qty: Количество для округления
        qty_step: Шаг округления (например, 0.01)
        round_down: Округлять вниз (True) или вверх (False)

    Returns:
        Строка с округлённым значением

    ВАЖНО: Использует Decimal, чтобы избежать float артефактов (0.30000004)
    """
    if qty <= 0:
        return "0"

    qty_dec = Decimal(str(qty))
    step_dec = Decimal(str(qty_step))

    rounding = ROUND_DOWN if round_down else ROUND_UP
    rounded = (qty_dec / step_dec).quantize(Decimal('1'), rounding=rounding) * step_dec

    # Убираем trailing zeros
    result = str(rounded)
    if '.' in result:
        result = result.rstrip('0').rstrip('.')

    return result


def round_price(price: float, tick_size: float) -> str:
    """
    Округляет цену до tickSize используя Decimal для точности.

    Args:
        price: Цена для округления
        tick_size: Шаг цены (например, 0.01)

    Returns:
        Строка с округлённой ценой

    ВАЖНО: Использует Decimal, чтобы избежать float артефактов
    """
    if price <= 0:
        return "0"

    price_dec = Decimal(str(price))
    tick_dec = Decimal(str(tick_size))

    # Для цен обычно округляем вниз
    rounded = (price_dec / tick_dec).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick_dec

    # Убираем trailing zeros
    result = str(rounded)
    if '.' in result:
        result = result.rstrip('0').rstrip('.')

    return result


def validate_qty(
    qty: float,
    min_qty: float,
    max_qty: float,
    qty_step: float
) -> tuple[bool, str]:
    """
    Валидация количества по правилам Bybit.

    Returns:
        (valid, error_message)
    """
    if qty < min_qty:
        return False, f"Qty {qty} < minimum {min_qty}"

    if qty > max_qty:
        return False, f"Qty {qty} > maximum {max_qty}"

    # Проверка кратности шагу (через Decimal)
    qty_dec = Decimal(str(qty))
    step_dec = Decimal(str(qty_step))

    remainder = qty_dec % step_dec
    if remainder != 0:
        return False, f"Qty {qty} не кратно шагу {qty_step}"

    return True, ""


def validate_price(
    price: float,
    min_price: float,
    max_price: float,
    tick_size: float
) -> tuple[bool, str]:
    """
    Валидация цены по правилам Bybit.

    Returns:
        (valid, error_message)
    """
    if price < min_price:
        return False, f"Price {price} < minimum {min_price}"

    if price > max_price:
        return False, f"Price {price} > maximum {max_price}"

    # Проверка кратности tick size (через Decimal)
    price_dec = Decimal(str(price))
    tick_dec = Decimal(str(tick_size))

    remainder = price_dec % tick_dec
    if remainder != 0:
        return False, f"Price {price} не кратно tick size {tick_size}"

    return True, ""


def validate_notional(
    qty: float,
    price: float,
    min_notional: float
) -> tuple[bool, str]:
    """
    Проверка минимального notional (qty * price).

    Returns:
        (valid, error_message)
    """
    notional = qty * price

    if notional < min_notional:
        return False, f"Notional {notional:.2f} < minimum {min_notional}"

    return True, ""


def format_number(value: float, decimals: int = 2) -> str:
    """
    Форматирование числа с заданным количеством десятичных знаков.
    Убирает trailing zeros.
    """
    formatted = f"{value:.{decimals}f}"
    if '.' in formatted:
        formatted = formatted.rstrip('0').rstrip('.')
    return formatted


def format_usd(value: float) -> str:
    """Форматирование суммы в USD"""
    return f"${format_number(value, 2)}"


def format_percent(value: float) -> str:
    """Форматирование процента"""
    sign = "+" if value > 0 else ""
    return f"{sign}{format_number(value, 2)}%"
