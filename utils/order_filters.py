"""
Order Filters - общие функции фильтрации ордеров.

Используется в handlers для фильтрации списков ордеров.
"""
from typing import List


def filter_user_orders(orders: List[dict]) -> List[dict]:
    """
    Фильтрует ордера, оставляя только пользовательские.

    Исключает:
    - reduceOnly ордера (SL/TP)
    - Entry Plan ордера (orderLinkId начинается с EP:)

    Args:
        orders: Список ордеров от Bybit API

    Returns:
        Отфильтрованный список пользовательских ордеров
    """
    result = []
    for order in orders:
        # Исключаем reduceOnly (SL/TP ордера)
        if order.get('reduceOnly', False):
            continue

        # Исключаем ордера Entry Plans
        order_link_id = order.get('orderLinkId', '')
        if order_link_id.startswith('EP:'):
            continue

        result.append(order)

    return result


def filter_tp_orders(orders: List[dict]) -> List[dict]:
    """
    Фильтрует только Take Profit ордера (reduceOnly Limit с ценой > 0).

    Args:
        orders: Список ордеров от Bybit API

    Returns:
        Список TP ордеров с price и qty
    """
    result = []
    for order in orders:
        order_type = order.get('orderType', '')
        price = float(order.get('price', 0))

        if (order.get('reduceOnly', False) and
            order_type == 'Limit' and
            price > 0):
            result.append({
                'price': price,
                'qty': order.get('qty', '0')
            })

    return result
