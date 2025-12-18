"""
Генерация графиков для позиций и Entry Plans.
"""
import logging

from services.charts import get_chart_generator
from services.bybit import BybitClient

logger = logging.getLogger(__name__)


async def generate_position_chart(
    client: BybitClient,
    position: dict,
    tp_orders: list = None,
    timeframe: str = "1h"
) -> bytes | None:
    """
    Генерация графика для позиции.

    Args:
        client: Bybit client
        position: Данные позиции
        tp_orders: Список TP ордеров
        timeframe: Таймфрейм для свечей

    Returns:
        PNG bytes или None при ошибке
    """
    try:
        symbol = position.get('symbol')
        entry_price = float(position.get('avgPrice', 0))
        mark_price = float(position.get('markPrice', 0))
        stop_loss_raw = position.get('stopLoss', '')
        side = position.get('side')  # Buy или Sell

        # Получаем klines
        klines = await client.get_klines(symbol=symbol, interval=timeframe, limit=100)
        if not klines:
            logger.warning(f"No klines for {symbol}")
            return None

        # Строим scenario-подобный dict для ChartGenerator
        # Entry zone (single price for position)
        scenario = {
            "entry": {
                "price_min": entry_price,
                "price_max": entry_price
            },
            "stop_loss": {},
            "targets": [],
            "bias": "long" if side == "Buy" else "short"
        }

        # Stop loss
        if stop_loss_raw:
            try:
                sl_price = float(stop_loss_raw)
                scenario["stop_loss"]["recommended"] = sl_price
            except (ValueError, TypeError):
                pass

        # Take profit levels
        if tp_orders:
            for i, tp in enumerate(tp_orders[:3]):  # Макс 3 TP
                scenario["targets"].append({
                    "price": tp['price'],
                    "partial_close_pct": 100 // len(tp_orders)  # Примерно
                })

        # Генерируем график
        chart_gen = get_chart_generator()
        chart_png = chart_gen.generate_scenario_chart(
            klines=klines,
            scenario=scenario,
            symbol=symbol,
            timeframe=timeframe,
            current_price=mark_price
        )

        return chart_png

    except Exception as e:
        logger.warning(f"Chart generation failed for position: {e}")
        return None


async def generate_entry_plan_chart(
    plan,
    testnet: bool,
    timeframe: str = "1h"
) -> bytes | None:
    """
    Генерация графика для Entry Plan.

    Args:
        plan: EntryPlan объект
        testnet: Режим testnet
        timeframe: Таймфрейм для свечей

    Returns:
        PNG bytes или None при ошибке
    """
    try:
        symbol = plan.symbol

        # Создаём клиент
        client = BybitClient(testnet=testnet)

        # Получаем текущую цену
        ticker = await client.get_tickers(symbol)
        current_price = float(ticker.get('lastPrice', 0))

        # Получаем klines
        klines = await client.get_klines(symbol=symbol, interval=timeframe, limit=100)
        if not klines:
            logger.warning(f"No klines for {symbol}")
            return None

        # Считаем entry zone из ордеров
        order_prices = [o.get('price', 0) for o in plan.orders if o.get('price', 0) > 0]
        if order_prices:
            entry_min = min(order_prices)
            entry_max = max(order_prices)
        else:
            entry_min = entry_max = plan.avg_entry_price or current_price

        # Строим scenario
        scenario = {
            "entry": {
                "price_min": entry_min,
                "price_max": entry_max
            },
            "stop_loss": {
                "recommended": plan.stop_price
            },
            "targets": [],
            "bias": "long" if plan.side == "Long" else "short"
        }

        # Take profit levels
        if plan.targets:
            for t in plan.targets[:3]:
                scenario["targets"].append({
                    "price": t.get('price', 0),
                    "partial_close_pct": t.get('partial_close_pct', 100)
                })

        # Генерируем график
        chart_gen = get_chart_generator()
        chart_png = chart_gen.generate_scenario_chart(
            klines=klines,
            scenario=scenario,
            symbol=symbol,
            timeframe=timeframe,
            current_price=current_price
        )

        return chart_png

    except Exception as e:
        logger.warning(f"Chart generation failed for entry plan: {e}")
        return None
