import logging
from typing import Dict, Tuple, Optional
from utils.validators import round_qty, round_price, validate_qty, validate_price, validate_notional

logger = logging.getLogger(__name__)


class RiskCalculationError(Exception):
    """Ошибка при расчёте риска"""
    pass


class RiskCalculator:
    """
    Калькулятор размера позиции на основе риска

    КРИТИЧНО: qty = risk_$ / |entry - stop|
    Leverage НЕ влияет на PnL, только на required margin!
    """

    def __init__(self, bybit_client):
        self.bybit = bybit_client

    async def calculate_position(
        self,
        symbol: str,
        side: str,  # "Long" or "Short"
        entry_price: float,
        stop_price: float,
        risk_usd: float,
        leverage: int,
        tp_price: Optional[float] = None
    ) -> Dict:
        """
        Рассчитать параметры позиции на основе риска

        Args:
            symbol: Торговая пара (например, "SOLUSDT")
            side: "Long" или "Short"
            entry_price: Цена входа
            stop_price: Цена стоп-лосса
            risk_usd: Риск в USD
            leverage: Плечо
            tp_price: Цена тейк-профита (опционально)

        Returns:
            {
                'qty': '1.234',  # Округлённое количество
                'qty_raw': 1.234,  # Сырое количество до округления
                'entry_price': '130.50',
                'stop_price': '127.00',
                'tp_price': '138.00',
                'risk_usd': 10.0,
                'actual_risk_usd': 9.98,  # После округления qty
                'leverage': 5,
                'margin_required': 43.21,
                'liq_price_estimate': 120.5,  # Грубая оценка
                'rr': 2.1,  # Risk/Reward если TP указан
                'stop_distance_percent': 2.68,
                'instrument_info': {...}
            }

        Raises:
            RiskCalculationError: Если параметры некорректны
        """

        # 1. Валидация входных параметров
        self._validate_inputs(side, entry_price, stop_price, risk_usd, leverage, tp_price)

        # 2. Получение информации об инструменте
        try:
            instrument_info = await self.bybit.get_instrument_info(symbol)
        except Exception as e:
            raise RiskCalculationError(f"Failed to get instrument info: {e}")

        # Извлекаем параметры
        lot_size_filter = instrument_info.get('lotSizeFilter', {})
        price_filter = instrument_info.get('priceFilter', {})
        leverage_filter = instrument_info.get('leverageFilter', {})

        qty_step = float(lot_size_filter.get('qtyStep', 0.01))
        min_qty = float(lot_size_filter.get('minOrderQty', 0))
        max_qty = float(lot_size_filter.get('maxOrderQty', 1000000))

        tick_size = float(price_filter.get('tickSize', 0.01))
        min_price = float(price_filter.get('minPrice', 0))
        max_price = float(price_filter.get('maxPrice', 1000000))

        max_leverage = float(leverage_filter.get('maxLeverage', 50))

        # Проверка leverage
        if leverage > max_leverage:
            raise RiskCalculationError(f"Leverage {leverage}x exceeds maximum {max_leverage}x for {symbol}")

        # 3. ПРАВИЛЬНАЯ формула расчёта qty
        # qty = risk_usd / |entry_price - stop_price|
        # Leverage НЕ влияет на PnL!

        stop_distance = abs(entry_price - stop_price)

        # Защита от деления на ноль и слишком малых дистанций
        if stop_distance <= 0:
            raise RiskCalculationError("Stop distance is zero or negative")

        # Проверка на микродистанцию (< 0.1% от цены = шумовая зона)
        if (stop_distance / entry_price) < 0.001:
            raise RiskCalculationError(
                f"Stop too tight ({stop_distance / entry_price * 100:.3f}% < 0.1%), noise zone"
            )

        qty_raw = risk_usd / stop_distance

        logger.debug(f"Risk calculation: risk=${risk_usd}, distance={stop_distance}, qty_raw={qty_raw}")

        # 4. Округление qty до qtyStep
        qty_str = round_qty(qty_raw, qty_step, round_down=True)
        qty = float(qty_str)

        # 5. Валидация qty
        valid, error = validate_qty(qty, min_qty, max_qty, qty_step)
        if not valid:
            raise RiskCalculationError(f"Invalid qty: {error}")

        # 6. Проверка minNotional
        # Bybit V5 может хранить minNotional в разных местах
        min_notional = float(
            lot_size_filter.get("minNotionalValue")
            or lot_size_filter.get("minNotional")
            or instrument_info.get("minNotionalValue")
            or 5  # Fallback по умолчанию
        )
        valid, error = validate_notional(qty, entry_price, min_notional)
        if not valid:
            raise RiskCalculationError(f"Position too small: {error}")

        # 7. Расчёт фактического риска после округления
        actual_risk_usd = qty * stop_distance

        # 8. Расчёт required margin
        # margin = (qty * entry_price) / leverage
        margin_required = (qty * entry_price) / leverage

        # 9. Округление цен до tickSize
        entry_price_str = round_price(entry_price, tick_size)
        stop_price_str = round_price(stop_price, tick_size)

        # Валидация округленных цен
        valid, error = validate_price(float(entry_price_str), min_price, max_price, tick_size)
        if not valid:
            raise RiskCalculationError(f"Invalid entry price: {error}")

        valid, error = validate_price(float(stop_price_str), min_price, max_price, tick_size)
        if not valid:
            raise RiskCalculationError(f"Invalid stop price: {error}")

        # 10. Расчёт приблизительной ликвидации (ОСТОРОЖНО - упрощённая формула!)
        liq_price_estimate = self._estimate_liquidation_price(
            side, entry_price, qty, leverage
        )

        # 11. Расчёт RR если указан TP
        rr = None
        tp_price_str = None
        if tp_price:
            tp_price_str = round_price(tp_price, tick_size)

            # Валидация TP цены
            valid, error = validate_price(float(tp_price_str), min_price, max_price, tick_size)
            if not valid:
                raise RiskCalculationError(f"Invalid TP price: {error}")

            # Расчёт RR с явным различием Long/Short
            if side == "Long":
                # Long: reward = (tp - entry), risk = (entry - stop)
                tp_distance = tp_price - entry_price
            else:  # Short
                # Short: reward = (entry - tp), risk = (stop - entry)
                tp_distance = entry_price - tp_price

            rr = tp_distance / stop_distance

        # 12. Расчёт stop distance в %
        stop_distance_percent = (stop_distance / entry_price) * 100

        return {
            'qty': qty_str,
            'qty_raw': qty_raw,
            'entry_price': entry_price_str,
            'stop_price': stop_price_str,
            'tp_price': tp_price_str,
            'risk_usd': risk_usd,
            'actual_risk_usd': actual_risk_usd,
            'leverage': leverage,
            'margin_required': margin_required,
            'liq_price_estimate': liq_price_estimate,
            'rr': rr,
            'stop_distance_percent': stop_distance_percent,
            'instrument_info': {
                'qtyStep': qty_step,
                'minQty': min_qty,
                'maxQty': max_qty,
                'tickSize': tick_size,
                'minPrice': min_price,
                'maxPrice': max_price,
                'maxLeverage': max_leverage,
                'minNotional': min_notional,
            }
        }

    def _validate_inputs(
        self,
        side: str,
        entry_price: float,
        stop_price: float,
        risk_usd: float,
        leverage: int,
        tp_price: Optional[float]
    ):
        """Валидация входных параметров"""

        if side not in ['Long', 'Short']:
            raise RiskCalculationError(f"Invalid side: {side}. Must be 'Long' or 'Short'")

        if entry_price <= 0:
            raise RiskCalculationError(f"Invalid entry price: {entry_price}")

        if stop_price <= 0:
            raise RiskCalculationError(f"Invalid stop price: {stop_price}")

        if risk_usd <= 0:
            raise RiskCalculationError(f"Invalid risk: {risk_usd}")

        if leverage < 1:
            raise RiskCalculationError(f"Invalid leverage: {leverage}")

        # Валидация направления стопа
        if side == "Long" and stop_price >= entry_price:
            raise RiskCalculationError(
                f"For Long, stop ({stop_price}) must be below entry ({entry_price})"
            )

        if side == "Short" and stop_price <= entry_price:
            raise RiskCalculationError(
                f"For Short, stop ({stop_price}) must be above entry ({entry_price})"
            )

        # Валидация TP если указан
        if tp_price:
            if side == "Long" and tp_price <= entry_price:
                raise RiskCalculationError(
                    f"For Long, TP ({tp_price}) must be above entry ({entry_price})"
                )

            if side == "Short" and tp_price >= entry_price:
                raise RiskCalculationError(
                    f"For Short, TP ({tp_price}) must be below entry ({entry_price})"
                )

    def _estimate_liquidation_price(
        self,
        side: str,
        entry_price: float,
        qty: float,
        leverage: int
    ) -> float:
        """
        Грубая оценка цены ликвидации (для Isolated margin)

        ⚠️ ВАЖНО: Это упрощённая формула!
        Реальная ликвидация зависит от:
        - Maintenance margin
        - Fees
        - Symbol-specific rules

        Лучше использовать liqPrice из API позиции!
        """

        margin = (qty * entry_price) / leverage

        if side == "Long":
            # Long: liq = entry - (margin / qty)
            liq_price = entry_price - (margin / qty)
        else:  # Short
            # Short: liq = entry + (margin / qty)
            liq_price = entry_price + (margin / qty)

        return round(liq_price, 2)

    async def validate_balance(
        self,
        required_margin: float,
        actual_risk_usd: Optional[float] = None,
        max_risk_per_trade: Optional[float] = None,
        max_margin_per_trade: Optional[float] = None,
        trading_capital: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Проверка баланса перед сделкой

        Args:
            required_margin: Требуемая маржа для позиции
            actual_risk_usd: Фактический риск в USD (опционально)
            max_risk_per_trade: Максимальный риск на сделку (из настроек)
            max_margin_per_trade: Максимальная маржа на сделку (из настроек)
            trading_capital: Фиксированный торговый капитал (опционально)

        Returns:
            (is_valid, error_message)
        """

        try:
            balance = await self.bybit.get_wallet_balance()

            # Используем availableBalance (НЕ availableToWithdraw!)
            available = float(balance.get('availableBalance', 0))

            # Если задан trading_capital, используем его вместо баланса
            if trading_capital:
                available = min(available, trading_capital)

            # Проверка доступного баланса
            if required_margin > available:
                return False, f"💸 Insufficient balance: need ${required_margin:.2f}, available ${available:.2f}"

            # Проверка макс. риска
            if max_risk_per_trade and actual_risk_usd and actual_risk_usd > max_risk_per_trade:
                return False, f"⚠️ Risk ${actual_risk_usd:.2f} exceeds max ${max_risk_per_trade:.2f}"

            # Проверка макс. маржи
            if max_margin_per_trade and required_margin > max_margin_per_trade:
                return False, f"⚠️ Margin ${required_margin:.2f} exceeds max ${max_margin_per_trade:.2f}"

            return True, ""

        except Exception as e:
            logger.error(f"Error validating balance: {e}")
            return False, f"❌ Failed to check balance: {str(e)}"
