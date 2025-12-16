"""
Entry Plan Models

Модели данных для работы с планами входа (ladder entry).
Поддерживает размещение 1-5 entry ордеров как единого плана.
"""
from dataclasses import dataclass, asdict, fields, field
from typing import Optional, List, Dict
from datetime import datetime


@dataclass
class EntryOrder:
    """
    Один entry ордер в плане.

    Attributes:
        order_id: Bybit order_id (заполняется после размещения)
        price: Целевая цена ордера
        size_pct: Процент от total_qty (1-100, сумма всех = 100%)
        qty: Рассчитанный qty для этого ордера
        order_type: Тип ордера ("limit" | "stop_limit")
        tag: Метка для логирования ("E1_ema20", "E2_support")
        source_level: Источник цены ("ema_20", "support_1", "swing_low_1")
        status: Статус ордера
        placed_at: Время размещения (ISO)
        filled_at: Время исполнения (ISO)
        fill_price: Фактическая цена исполнения
    """
    price: float
    size_pct: float
    qty: float
    order_type: str = "limit"
    tag: str = ""
    source_level: str = ""

    # Заполняется после размещения
    order_id: str = ""
    status: str = "pending"  # "pending" | "placed" | "filled" | "cancelled"
    placed_at: Optional[str] = None
    filled_at: Optional[str] = None
    fill_price: Optional[float] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'EntryOrder':
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def mark_placed(self, order_id: str):
        """Отметить ордер как размещённый"""
        self.order_id = order_id
        self.status = "placed"
        self.placed_at = datetime.utcnow().isoformat()

    def mark_filled(self, fill_price: float):
        """Отметить ордер как исполненный"""
        self.status = "filled"
        self.fill_price = fill_price
        self.filled_at = datetime.utcnow().isoformat()

    def mark_cancelled(self):
        """Отметить ордер как отменённый"""
        self.status = "cancelled"


@dataclass
class EntryFill:
    """
    Запись о частичном entry fill.
    Используется для логирования в TradeRecord.entry_fills
    """
    fill_id: str
    order_tag: str          # Связь с EntryOrder.tag ("E1_ema20")
    timestamp: str          # ISO format
    price: float
    qty: float
    fee_usd: float

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'EntryFill':
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class EntryPlan:
    """
    План входа с несколькими ордерами.

    Modes:
        - "ladder": Лестница из нескольких лимиток на разных уровнях
        - "single": Один ордер (совместимость со старой логикой)
        - "dca": DCA режим (добавление к позиции)

    Activation types:
        - "immediate": Сразу активировать и разместить ордера
        - "touch": Когда цена касается activation_level (в пределах max_distance_pct)
        - "price_above": Когда цена выше activation_level
        - "price_below": Когда цена ниже activation_level

    Cancel conditions:
        - "break_below PRICE": Отменить если цена упадёт ниже PRICE
        - "break_above PRICE": Отменить если цена вырастет выше PRICE
        - "time_valid_hours exceeded": Отменить по истечении времени
    """
    # Идентификация
    plan_id: str
    trade_id: str
    user_id: int
    symbol: str
    side: str  # "Long" | "Short"

    # Mode
    mode: str  # "ladder" | "single" | "dca"

    # Orders
    orders: List[Dict] = field(default_factory=list)  # List[EntryOrder.to_dict()]
    total_qty: float = 0.0

    # Activation gate
    activation_type: str = "immediate"
    activation_level: Optional[float] = None
    max_distance_pct: float = 0.5
    is_activated: bool = False
    activated_at: Optional[str] = None

    # Cancel conditions
    cancel_if: List[str] = field(default_factory=list)
    time_valid_hours: float = 48

    # Trade params
    stop_price: float = 0.0
    targets: List[Dict] = field(default_factory=list)
    leverage: int = 5
    risk_usd: float = 0.0
    testnet: bool = False

    # Status
    status: str = "pending"  # "pending" | "active" | "partial" | "filled" | "cancelled"
    created_at: str = ""
    updated_at: str = ""
    cancel_reason: Optional[str] = None

    # Metrics
    filled_qty: float = 0.0
    filled_orders_count: int = 0
    avg_entry_price: float = 0.0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()
        self.updated_at = self.created_at

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'EntryPlan':
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def get_orders(self) -> List[EntryOrder]:
        """Получить список EntryOrder объектов"""
        return [EntryOrder.from_dict(o) for o in self.orders]

    def update_order(self, index: int, order: EntryOrder):
        """Обновить ордер по индексу"""
        if 0 <= index < len(self.orders):
            self.orders[index] = order.to_dict()
            self.updated_at = datetime.utcnow().isoformat()

    def calculate_avg_entry(self) -> float:
        """Рассчитать средневзвешенную цену входа"""
        if self.filled_qty <= 0:
            return 0.0

        total_value = 0.0
        for order_dict in self.orders:
            order = EntryOrder.from_dict(order_dict)
            if order.status == "filled" and order.fill_price:
                total_value += order.fill_price * order.qty

        return total_value / self.filled_qty if self.filled_qty > 0 else 0.0

    def recalculate_metrics(self):
        """Пересчитать метрики плана"""
        filled_qty = 0.0
        filled_count = 0

        for order_dict in self.orders:
            order = EntryOrder.from_dict(order_dict)
            if order.status == "filled":
                filled_qty += order.qty
                filled_count += 1

        self.filled_qty = filled_qty
        self.filled_orders_count = filled_count
        self.avg_entry_price = self.calculate_avg_entry()
        self.updated_at = datetime.utcnow().isoformat()

        # Update status
        total_orders = len(self.orders)
        if filled_count == 0:
            if self.is_activated:
                self.status = "active"
            else:
                self.status = "pending"
        elif filled_count < total_orders:
            self.status = "partial"
        else:
            self.status = "filled"

    def get_pending_orders(self) -> List[EntryOrder]:
        """Получить незаполненные ордера"""
        return [
            EntryOrder.from_dict(o) for o in self.orders
            if o.get('status') in ('pending', 'placed')
        ]

    def get_filled_orders(self) -> List[EntryOrder]:
        """Получить исполненные ордера"""
        return [
            EntryOrder.from_dict(o) for o in self.orders
            if o.get('status') == 'filled'
        ]

    @property
    def is_complete(self) -> bool:
        """Все ордера исполнены"""
        return self.status == "filled"

    @property
    def has_fills(self) -> bool:
        """Есть хотя бы один fill"""
        return self.filled_orders_count > 0

    @property
    def fill_percentage(self) -> float:
        """Процент заполнения плана"""
        if self.total_qty <= 0:
            return 0.0
        return (self.filled_qty / self.total_qty) * 100
