# Bybit Trading Bot - Development Progress

## Project Overview
One-tap execution trading bot для Bybit с автоматическим расчётом риска и размера позиции.

## Core Features Target
- ✅ One-tap execution с калькулятором риска
- ✅ Обязательные SL/TP при каждом входе
- ✅ Trade Wizard (пошаговый процесс открытия сделки)
- ✅ Мониторинг позиций в реальном времени с PnL
- ✅ История сделок и статистика
- ✅ Безопасность (API только Trade, подтверждения, лимиты)
- ✅ Testnet/Live режимы

## Supported Instruments
- BTCUSDT
- ETHUSDT
- SOLUSDT
- BNBUSDT
- HYPEUSDT

---

## Development Roadmap

### Phase 1: Foundation & Core Infrastructure ⏳
**Status:** In Progress

#### 1.1 Project Setup
- [ ] Создать структуру папок проекта
- [ ] Настроить requirements.txt (без версий)
- [ ] Создать .env.example с необходимыми переменными
- [ ] Настроить базовый конфиг и логирование
- [ ] README.md с инструкциями по установке

#### 1.2 Bybit API Integration
- [ ] Создать wrapper для Bybit API (pybit)
- [ ] Реализовать безопасную загрузку API ключей из .env
- [ ] Добавить методы для futures trading:
  - [ ] Получение текущей цены (ticker)
  - [ ] Размещение Market/Limit ордеров
  - [ ] Установка SL/TP
  - [ ] Получение позиций
  - [ ] Получение баланса
  - [ ] Расчёт ликвидации
- [ ] Поддержка Testnet/Live переключения
- [ ] Обработка ошибок API

#### 1.3 Risk Calculator
- [ ] **ПРАВИЛЬНАЯ формула расчёта qty от риска:**
  - [ ] `qty = risk_$ / |entry - stop|` (leverage НЕ влияет на PnL!)
  - [ ] Margin = `(qty * entry) / leverage` (плечо влияет только на маржу)
- [ ] Получение instrument info от Bybit:
  - [ ] `qtyStep`, `minOrderQty`, `maxOrderQty`
  - [ ] `tickSize`, `minPrice`, `maxPrice`
  - [ ] `minNotional`, `maxLeverage`
- [ ] **Утилиты округления через Decimal (НЕ через %):**
  - [ ] `round_qty(qty, qtyStep)` - использовать Decimal для точности
  - [ ] `round_price(price, tickSize)` - использовать Decimal
  - [ ] Округление вниз (floor) для qty, чтобы не превысить баланс
  - [ ] ⚠️ ВАЖНО: float % даёт артефакты (0.30000004), Bybit будет отклонять
- [ ] Проверка минимального/максимального размера позиции
- [ ] Расчёт required margin и проверка баланса:
  - [ ] Использовать `availableBalance` / `availableEquity` (НЕ availableToWithdraw!)
  - [ ] Опция: настройка "manual trading capital" (например $500)
- [ ] **Расчёт цены ликвидации - ОСТОРОЖНО:**
  - [ ] Если Bybit возвращает `liqPrice` в позиции → использовать его
  - [ ] Иначе показывать: "Est. Liq: ~X (rough estimate)" с дисклеймером
  - [ ] ⚠️ Упрощённая формула часто неточна (maintenance margin, fees, symbol rules)
- [ ] Расчёт RR (Risk/Reward)
- [ ] Валидации:
  - [ ] Риск не превышает баланс
  - [ ] Риск не превышает `max_risk_per_trade` из настроек
  - [ ] Margin не превышает `max_margin_per_trade`
  - [ ] Leverage не превышает `maxLeverage` для символа
  - [ ] `minNotional`: qty * price >= minNotional

---

### Phase 2: Telegram Bot Core ⏳
**Status:** Not Started

#### 2.1 Bot Initialization
- [ ] Настроить aiogram с FSM
- [ ] Создать главное меню (ReplyKeyboard):
  - [ ] ➕ Открыть сделку
  - [ ] 📊 Позиции
  - [ ] ⚙️ Настройки
  - [ ] 🧾 История
  - [ ] 🔔 Алерты (optional)
  - [ ] 🧪 Testnet/Live
- [ ] Обработка /start команды
- [ ] Middleware для логирования

#### 2.2 User Settings Storage
- [ ] Настроить Redis connection (или in-memory fallback)
- [ ] Модель настроек пользователя:
  - [ ] default_risk_usd (5, 10, 15)
  - [ ] default_leverage (2, 3, 5)
  - [ ] default_margin_mode (Isolated/Cross) - только для отображения, не менять API
  - [ ] shorts_enabled (True/False)
  - [ ] default_tp_mode (RR/ladder/single)
  - [ ] max_margin_per_trade
  - [ ] max_risk_per_trade
  - [ ] **trading_capital (опционально):** фиксированный капитал для расчётов (например $500)
  - [ ] confirm_always (True/False)
  - [ ] testnet_mode (True/False)
- [ ] CRUD операции для настроек
- [ ] **Trade locks для race condition:**
  - [ ] `lock:user_id:trade` с TTL
  - [ ] Acquire/Release методы

---

### Phase 3: Trade Wizard (FSM) 🎯
**Status:** Not Started

#### 3.1 FSM States Definition
```python
class TradeStates(StatesGroup):
    choosing_symbol = State()      # Шаг 1: Выбор инструмента
    choosing_side = State()        # Шаг 2: Long/Short
    choosing_entry_type = State()  # Шаг 3: Market/Limit
    entering_entry_price = State() # Если Limit - ввод цены
    entering_stop = State()        # Шаг 4: Ввод стопа
    choosing_risk_lev = State()    # Шаг 5: Риск и плечо
    choosing_tp = State()          # Шаг 6: Тейки
    confirmation = State()         # Шаг 7: Подтверждение
```

#### 3.2 Step 1: Symbol Selection
- [ ] InlineKeyboard с кнопками:
  - [ ] BTCUSDT | ETHUSDT
  - [ ] SOLUSDT | BNBUSDT
  - [ ] HYPEUSDT
  - [ ] ⭐ Избранное (optional)
  - [ ] 🔎 Поиск (optional)
- [ ] Сохранение выбора в FSM context

#### 3.3 Step 2: Side Selection
- [ ] InlineKeyboard:
  - [ ] 🟢 Long
  - [ ] 🔴 Short (если включены в настройках)
- [ ] Сохранение direction в context

#### 3.4 Step 3: Entry Type
- [ ] InlineKeyboard:
  - [ ] ⚡ Market
  - [ ] 🎯 Limit
- [ ] Если Market → переход к вводу стопа
- [ ] Если Limit → запрос цены входа

#### 3.5 Step 4: Stop Loss Entry
- [ ] Запрос цены стопа (обязательно!)
- [ ] Валидация:
  - [ ] Для Long: stop < entry
  - [ ] Для Short: stop > entry
  - [ ] Stop не слишком близко к entry (мин. 0.1%?)
- [ ] Показать расстояние в % от entry
- [ ] Нельзя продолжить без стопа

#### 3.6 Step 5: Risk & Leverage
- [ ] InlineKeyboard пресеты:
  - [ ] Risk: $5 | $10 | $15 | custom
  - [ ] Leverage: 2x | 3x | 5x | custom
  - [ ] Margin Mode: Isolated | Cross
- [ ] Использовать дефолты из настроек
- [ ] Валидация макс. риска/маржи

#### 3.7 Step 6: Take Profit
- [ ] Три режима InlineKeyboard:
  - [ ] 🎯 Single TP (ввести цену)
  - [ ] 🪜 Ladder (TP1 50% / TP2 50%)
  - [ ] 📐 By RR (выбрать RR: 1.5 / 2.0 / 3.0)
- [ ] Расчёт TP от entry+stop если RR
- [ ] Валидация:
  - [ ] Для Long: TP > entry
  - [ ] Для Short: TP < entry

#### 3.8 Step 7: Confirmation Card
- [ ] Показать карточку сделки:
  ```
  📊 Trade Summary

  Symbol: SOLUSDT
  Side: 🟢 Long
  Entry: Market (current: $135.42)
  Stop: $132.00

  Risk: $10.00
  Leverage: 5x
  Qty: 1.47 SOL
  Margin: ~$40

  TP1: $140.00 (50%)
  TP2: $145.00 (50%)

  RR: 2.1
  Est. Liq: ~$120.5
  ```
- [ ] InlineKeyboard:
  - [ ] ✅ Place Order
  - [ ] ✏️ Edit
  - [ ] ❌ Cancel
- [ ] Защита от двойного клика (idempotency)

#### 3.9 Order Execution
- [ ] **Race Condition Protection (КРИТИЧНО!):**
  - [ ] Redis lock: `lock:user_id:trade` с TTL 10-20 сек
  - [ ] Если locked → "⏳ Trade in progress..."
  - [ ] Release lock после завершения/ошибки
  - [ ] Защита от дабл-клика в Telegram + сетевых повторов
- [ ] **Pre-flight checks:**
  - [ ] Проверка баланса (availableBalance >= required_margin)
  - [ ] Проверка лимитов (risk/margin не превышают макс.)
  - [ ] Получение текущей mark/last price для Market
- [ ] **Setup:**
  - [ ] Установить leverage через `set_leverage()`
  - [ ] ⚠️ Margin mode: НЕ трогать на старте (пусть будет preset руками)
  - [ ] Потом можно добавить `switch_margin_mode()`, но аккуратно:
    - [ ] Unified аккаунт имеет нюансы
    - [ ] Нельзя менять mode если есть позиция/ордер
  - [ ] Генерация `trade_id = uuid4()` для idempotency
- [ ] **Entry Order:**
  - [ ] Market: `clientOrderId = f"{trade_id}_entry"`
  - [ ] Limit: то же, но с указанием price
  - [ ] **Wait for fill (КРИТИЧНО для Market):**
    - [ ] `wait_until_filled(order_id, timeout=10s)`
    - [ ] Poll 3-10 раз с delay 0.5-1s
    - [ ] ⚠️ `avgPrice` может быть 0 сразу после place → нужен retry
    - [ ] Если timeout → отменить ордер и вернуть ошибку
  - [ ] Получить `avgPrice` (реальная цена входа)
  - [ ] Пересчитать actual_risk и RR от avgPrice
- [ ] **Stop Loss:**
  - [ ] Метод 1 (проще): `set_trading_stop()` на позицию
  - [ ] `slTriggerBy="MarkPrice"` для стабильности
  - [ ] ⚠️ Если SL НЕ установился → PANIC CLOSE позицию (на testnet минимум)
- [ ] **Take Profit:**
  - [ ] Single TP: через `set_trading_stop(takeProfit=...)`
  - [ ] Ladder TP: отдельные Limit ордера:
    - [ ] `reduceOnly=True` (обязательно!)
    - [ ] Side = противоположный позиции
    - [ ] Qty ≤ размер позиции
    - [ ] TP1: 50% qty, `clientOrderId = f"{trade_id}_tp1"`
    - [ ] TP2: 50% qty, `clientOrderId = f"{trade_id}_tp2"`
    - [ ] ⚠️ `closeOnTrigger` не обязателен для Limit (главное reduceOnly)
- [ ] **Error Handling:**
  - [ ] Ловить duplicate clientOrderId → "⚠️ Order already placed"
  - [ ] Ловить insufficient balance → "💸 Not enough USDT"
  - [ ] Ловить invalid qty/price → "❌ Invalid parameters"
  - [ ] **Rollback при частичной неудаче:**
    - [ ] Если entry заполнился, но SL не установился → закрыть позицию Market
    - [ ] Логировать все ошибки для дебага
- [ ] **Success Message:**
  - [ ] Обновить карточку с реальными данными:
    - [ ] Entry: $X.XX (filled) ← реальный avgPrice
    - [ ] Risk: $X.XX (actual)
    - [ ] RR: X.XX (actual)
    - [ ] Liq: $X.XX (from Bybit API если доступно)
  - [ ] Показать inline кнопку "📊 View Position"
- [ ] **Logging в Redis/БД:**
  - [ ] trade_id, timestamp
  - [ ] user_id, symbol, side
  - [ ] entry_price (avg), stop_price, tp_prices
  - [ ] qty, leverage, margin_mode
  - [ ] risk_usd, actual_risk
  - [ ] order_ids (entry, sl, tp1, tp2)
  - [ ] execution_status (pending/filled/error)

---

### Phase 4: Position Monitoring 📊
**Status:** Not Started

#### 4.1 Positions List View
- [ ] Получение всех открытых позиций из Bybit
- [ ] InlineKeyboard список:
  ```
  SOLUSDT Long | PnL: +12.4$ | ROE: +3.1%
  ETHUSDT Long | PnL: -4.8$ | ROE: -1.2%
  ```
- [ ] Кнопки сверху:
  - [ ] 🔄 Refresh
  - [ ] 🧯 Panic Close All (с подтверждением!)
  - [ ] ⚙️ Auto-refresh ON/OFF

#### 4.2 Position Details
- [ ] По клику на позицию показать:
  ```
  📈 SOLUSDT Long

  Entry: $135.42
  Mark Price: $138.20
  Liq Price: $120.50

  Size: 1.47 SOL
  Leverage: 5x
  Margin: Isolated

  Unrealized PnL: +$12.40 (+3.1%)
  Realized PnL: $0.00

  SL: $132.00 ✅
  TP1: $140.00 (50%) ✅
  TP2: $145.00 (50%) ✅
  ```
- [ ] InlineKeyboard действия:
  - [ ] 🧷 Move SL (только в плюс для дисциплины)
  - [ ] ➕ Partial Close (25% / 50% / 75%)
  - [ ] ❌ Close Market
  - [ ] 🪜 Modify TP

#### 4.3 Auto-refresh Positions
- [ ] Фоновая задача обновления PnL (каждые 10-20 сек)
- [ ] Websocket для real-time (optional, фаза 2)
- [ ] Уведомления при достижении SL/TP

---

### Phase 5: Settings Menu ⚙️
**Status:** Not Started

#### 5.1 Settings UI
- [ ] InlineKeyboard с категориями:
  - [ ] 💰 Default Risk
  - [ ] 📊 Default Leverage
  - [ ] 🔀 Margin Mode
  - [ ] 🔴 Shorts Enabled
  - [ ] 🎯 TP Template
  - [ ] 🔒 Safety Limits
  - [ ] ✅ Confirmations
  - [ ] 🧪 Testnet/Live

#### 5.2 Individual Setting Handlers
- [ ] Каждая настройка → InlineKeyboard с опциями
- [ ] Сохранение в Redis/БД
- [ ] Подтверждение изменения
- [ ] Показать текущее значение

---

### Phase 6: Trade History & Stats 🧾
**Status:** Not Started

#### 6.1 Database Schema for Trades
- [ ] Таблица/коллекция для хранения закрытых сделок:
  - [ ] user_id, timestamp
  - [ ] symbol, side
  - [ ] entry_price, exit_price
  - [ ] stop_price, tp_price
  - [ ] qty, leverage
  - [ ] pnl_usd, pnl_percent
  - [ ] risk_usd
  - [ ] outcome (win/loss)
  - [ ] rr_actual

#### 6.2 History View
- [ ] Список последних N сделок
- [ ] Фильтры:
  - [ ] По символу (ALL / BTC / ETH / SOL...)
  - [ ] Long only / Short only / All
  - [ ] По датам (Last 7d / 30d / All)
- [ ] Pagination (если много сделок)

#### 6.3 Statistics Dashboard
- [ ] Общая статистика:
  - [ ] Total Trades
  - [ ] Winrate %
  - [ ] Avg RR
  - [ ] Max Drawdown
  - [ ] Expectancy (avg win vs avg loss)
  - [ ] Total PnL
- [ ] По символам (какая монета прибыльнее)

---

### Phase 7: Alerts (Optional) 🔔
**Status:** Not Started

#### 7.1 Price Alerts
- [ ] "Уведомить когда SOL > $150"
- [ ] "Уведомить когда ETH < $3500"
- [ ] Фоновая проверка цен

#### 7.2 Position Alerts
- [ ] PnL достиг X%
- [ ] Позиция приблизилась к ликвидации
- [ ] SL/TP сработали

---

### Phase 8: Quick Trade Buttons (UX Enhancement) ⚡
**Status:** Not Started

- [ ] Добавить в главное меню:
  - [ ] ⚡ Quick Long BTC
  - [ ] ⚡ Quick Long ETH
  - [ ] ⚡ Quick Long SOL
- [ ] При нажатии → сразу выбраны symbol + side
- [ ] Остаётся только ввести stop → всё остальное из дефолтов
- [ ] Confirm → trade

---

## Technical Stack

### Core Dependencies
- **aiogram** - Telegram Bot framework (FSM, keyboards)
- **pybit** - Bybit API wrapper (V5 API support required!)
- **redis** - State storage (опционально, fallback на in-memory dict)
- **python-dotenv** - Environment variables (.env)
- **aiohttp** - Async HTTP (уже в aiogram dependencies)
- **uuid** - Генерация clientOrderId для idempotency

### Important Notes
- **Bybit API V5** (не V3!) — у них breaking changes
- **One-Way Mode** (`positionIdx=0`) — проще для начала
- **No versions** в requirements.txt — latest stable

### Project Structure
```
futures-bot/
├── .env.example
├── .env (ignored)
├── requirements.txt
├── README.md
├── PROGRESS.md
├── TZ.txt
├── main.py
├── config.py
├── bot/
│   ├── __init__.py
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── start.py
│   │   ├── trade_wizard.py
│   │   ├── positions.py
│   │   ├── settings.py
│   │   ├── history.py
│   │   └── alerts.py
│   ├── keyboards/
│   │   ├── __init__.py
│   │   ├── main_menu.py
│   │   ├── trade_kb.py
│   │   └── positions_kb.py
│   ├── states/
│   │   ├── __init__.py
│   │   └── trade_states.py
│   └── middlewares/
│       ├── __init__.py
│       └── logging.py
├── services/
│   ├── __init__.py
│   ├── bybit_client.py
│   ├── risk_calculator.py
│   ├── position_tracker.py
│   └── trade_logger.py
├── storage/
│   ├── __init__.py
│   ├── redis_storage.py
│   └── user_settings.py
└── utils/
    ├── __init__.py
    ├── formatters.py
    └── validators.py
```

---

## Current Session Progress

### Session 1 (2025-12-15) - MVP Core Implementation
- [x] Изучено ТЗ и создан PROGRESS.md
- [x] Создана базовая структура проекта
- [x] Изучена Bybit V5 API документация
- [x] Реализован Bybit API client с V5 поддержкой:
  - get_tickers, get_instrument_info, get_wallet_balance
  - set_leverage, place_order, get_order, wait_until_filled
  - set_trading_stop, get_positions, close_position
  - place_ladder_tp (для ladder TP через limit orders)
- [x] Реализован Risk Calculator с правильными формулами
- [x] Создана модульная архитектура Trade Wizard:
  - bot/handlers/trade_wizard/ (модульная структура)
  - 8 модулей: utils, navigation, symbol_side, entry, stop, risk_leverage, take_profit, confirmation
- [x] Реализован полный FSM wizard со Stop по % (ключевая фича!)
  - 📐 Stop % - пресеты 0.8%, 1%, 1.5%, 2%, 2.5%, custom
  - ✍️ Stop вручную - для структурных уровней
  - 🤖 AI сценарии - placeholder для будущего
- [x] Реализованы базовые хендлеры для всех Reply кнопок меню
- [x] Создан user settings storage с Redis/in-memory fallback
- [x] Добавлена race condition protection через lock_manager

### Что работает сейчас:
✅ Бот запускается и отвечает на /start
✅ Все кнопки главного меню работают
✅ Полный FSM wizard для Trade (8 шагов)
✅ Stop по % - быстрая установка стопа без расчётов
✅ Все валидации на каждом шаге
✅ Testnet/Live переключение
✅ **Trade Execution - ПОЛНОСТЬЮ РЕАЛИЗОВАН!**
  - Pre-flight checks (balance validation)
  - Risk calculation & margin validation
  - Leverage setup
  - Entry order (Market/Limit) с wait_until_filled
  - Stop Loss с panic close при ошибке
  - Take Profit (single/ladder/RR modes)
  - Real avgPrice для Market orders
  - Success message с реальными данными
  - Полный error handling (BybitError, TimeoutError, RiskCalculationError)

### Следующие шаги:
- [ ] **Тестирование Trade Execution на Testnet** (КРИТИЧНО!)
- [ ] Добавить Position Monitoring с real-time updates
- [ ] Реализовать Settings management (inline кнопки)
- [ ] Добавить Trade History и Statistics
- [ ] AI сценарии integration (опционально)

---

## Important Security Notes
- ✅ API ключ ТОЛЬКО с правами Trade (БЕЗ Withdraw) — критично!
- ✅ Все ключи в .env (НЕ в коде, добавить .env в .gitignore)
- ✅ Обязательный confirm step перед сделкой
- ✅ Защита от дабл-клика: `clientOrderId = uuid4()`
- ✅ Лимиты на макс. риск/маржу (в настройках пользователя)
- ✅ Начинать с Testnet (переключатель в боте)
- ✅ Rollback при ошибке (если SL не установился → закрыть позицию)

## Critical Implementation Details (Ultra-think Results)

### 1. Risk Calculation (FIXED)
```python
# ✅ ПРАВИЛЬНО
qty = risk_usd / abs(entry_price - stop_price)
margin = (qty * entry_price) / leverage

# ❌ НЕПРАВИЛЬНО (старая версия)
# qty = risk_usd / (abs(entry_price - stop_price) * leverage)  # <- leverage не влияет на PnL!
```

### 2. Bybit Lot Size & Precision (КРИТИЧНО!)
**⚠️ Использовать Decimal, НЕ float %**
```python
from decimal import Decimal, ROUND_DOWN

def round_qty(qty: float, qty_step: float) -> str:
    """Округлить qty до qtyStep через Decimal (избегать float артефактов)"""
    qty_dec = Decimal(str(qty))
    step_dec = Decimal(str(qty_step))
    rounded = (qty_dec / step_dec).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_dec
    return str(rounded)

def round_price(price: float, tick_size: float) -> str:
    """Округлить price до tickSize через Decimal"""
    price_dec = Decimal(str(price))
    tick_dec = Decimal(str(tick_size))
    rounded = (price_dec / tick_dec).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick_dec
    return str(rounded)
```
- Всегда получать `instrument_info` перед расчётом
- Округлять `qty` до `qtyStep` (ROUND_DOWN чтобы не превысить баланс)
- Округлять `price` до `tickSize`
- Проверять `minNotional = qty * price >= minNotional`
- ❌ НИКОГДА не использовать `qty % qty_step` — даёт 0.30000004 и подобное

### 3. Market Entry Flow (с wait_until_filled)
```
1. Получить mark_price
2. Рассчитать qty от mark_price
3. Разместить Market order с clientOrderId
4. ⚠️ WAIT FOR FILL (критично!):
   - Poll get_order() 3-10 раз с delay 0.5-1s
   - avgPrice может быть 0 сразу после place → retry
   - Timeout 10s → cancel order и error
5. Получить avgPrice (реальный fill)
6. Пересчитать actual_risk и RR от avgPrice
7. Обновить карточку с реальными данными
```

### 4. SL/TP Methods
**Для простого SL/TP:**
- `set_trading_stop(stopLoss=..., takeProfit=...)` на позицию
- `slTriggerBy="MarkPrice"` для стабильности

**Для ladder TP:**
- Отдельные Limit ордера:
  - `reduceOnly=True` (обязательно!)
  - Side = противоположный позиции (Long → Sell, Short → Buy)
  - Qty ≤ размер позиции
  - ⚠️ `closeOnTrigger` НЕ обязателен для Limit (главное reduceOnly)

### 5. Bybit API V5 Specifics
- `category="linear"` для USDT perpetuals
- `positionIdx=0` для One-Way Mode
- `slTriggerBy="MarkPrice"` для стабильности
- `clientOrderId` для idempotency (max 36 chars)

### 6. Error Handling Priority
1. **Race condition:** Lock занят → "⏳ Trade in progress..."
2. **Duplicate order:** clientOrderId exists → "⚠️ Already placed"
3. **Insufficient balance:** → "💸 Not enough USDT"
4. **Invalid qty/price:** → "❌ Invalid parameters"
5. **Partial fill failure:** Entry filled but SL failed → **PANIC CLOSE** position
6. **Timeout:** Market order не заполнился за 10s → Cancel + error

**Balance Check:**
- Использовать `availableBalance` или `availableEquity` (НЕ availableToWithdraw)
- Опционально: настройка "trading_capital" ($500) для ограничения капитала

### 7. Liquidation Price (ОСТОРОЖНО - упрощённая формула!)
**⚠️ ВАЖНО:** Упрощённая формула часто неточна из-за:
- Maintenance margin (зависит от размера позиции)
- Trading fees
- Symbol-specific rules
- Cross/Isolated нюансы

**Правильный подход:**
```python
# 1. Получить liqPrice из позиции (если Bybit предоставляет)
position = await bybit.get_position(symbol)
liq_price = position.get('liqPrice')  # Используй это!

# 2. Если API не даёт liqPrice → показывать с дисклеймером:
if not liq_price:
    # Грубая оценка (только для Isolated):
    margin = (qty * entry) / leverage
    if side == "Long":
        liq_estimate = entry - (margin / qty)
    else:  # Short
        liq_estimate = entry + (margin / qty)

    # В карточке:
    # "Est. Liq: ~$XXX (rough estimate)"
```

### 8. Supported Symbols
- BTCUSDT (major)
- ETHUSDT (major)
- SOLUSDT (major)
- BNBUSDT (major)
- HYPEUSDT (interesting altcoin)

### 9. Race Condition Protection (АРХИТЕКТУРНО КРИТИЧНО!)
**Проблема:** Дабл-клик, сетевой повтор, Telegram callback дубль → 2 одинаковых ордера

**Решение - многоуровневая защита:**
```python
# 1. Redis Lock (ОСНОВНАЯ защита)
async def acquire_trade_lock(user_id: int, ttl: int = 20) -> bool:
    """Взять лок на пользователя для выполнения сделки"""
    lock_key = f"lock:user:{user_id}:trade"
    acquired = await redis.set(lock_key, "1", ex=ttl, nx=True)
    return bool(acquired)

async def release_trade_lock(user_id: int):
    """Освободить лок"""
    lock_key = f"lock:user:{user_id}:trade"
    await redis.delete(lock_key)

# 2. clientOrderId (вторая линия защиты)
trade_id = str(uuid4())
client_order_id = f"{trade_id}_entry"[:36]  # max 36 chars

# 3. В хендлере "Place Order":
if not await acquire_trade_lock(user_id):
    await message.answer("⏳ Trade in progress, please wait...")
    return

try:
    # ... выполнение сделки ...
finally:
    await release_trade_lock(user_id)
```

### 10. Margin Mode - Начальная рекомендация
**⚠️ НЕ трогать switch_margin_mode на старте!**

**Причины:**
- Unified аккаунт имеет нюансы
- Нельзя менять mode если есть позиция/ордер
- Разные версии API имеют разные параметры

**Рекомендация для MVP:**
1. Один раз **руками** в Bybit UI установить:
   - One-Way Mode (не Hedge)
   - Isolated или Cross (что предпочитаешь)
2. Бот только:
   - `set_leverage()`
   - Размещает ордера
3. После стабилизации можно добавить `switch_margin_mode()` как опцию

### 11. wait_until_filled() - Критичная функция
```python
async def wait_until_filled(
    bybit_client,
    order_id: str,
    symbol: str,
    timeout: int = 10,
    poll_interval: float = 0.5
) -> dict:
    """
    Ждёт заполнения ордера с retry

    Returns: order info with avgPrice
    Raises: TimeoutError if not filled
    """
    start = time.time()
    attempts = 0

    while time.time() - start < timeout:
        attempts += 1
        order = await bybit_client.get_order(
            category="linear",
            symbol=symbol,
            orderId=order_id
        )

        status = order.get('orderStatus')
        avg_price = float(order.get('avgPrice', 0))

        # Заполнен и avgPrice обновился
        if status == 'Filled' and avg_price > 0:
            return order

        # Отменён или отклонён
        if status in ['Cancelled', 'Rejected']:
            raise Exception(f"Order {status}: {order.get('rejectReason', 'unknown')}")

        # Retry
        await asyncio.sleep(poll_interval)

    # Timeout - отменяем ордер
    await bybit_client.cancel_order(
        category="linear",
        symbol=symbol,
        orderId=order_id
    )
    raise TimeoutError(f"Order not filled within {timeout}s")
```

---

## Testing Checklist (Before Live)
- [ ] Testnet: Открытие Market Long
- [ ] Testnet: Открытие Limit Long
- [ ] Testnet: Открытие Short (если включено)
- [ ] Testnet: SL срабатывает корректно
- [ ] Testnet: TP срабатывает корректно
- [ ] Testnet: Partial close работает
- [ ] Testnet: Move SL работает
- [ ] Testnet: Panic close all
- [ ] Проверка всех лимитов безопасности
- [ ] Проверка защиты от дабл-клика
- [ ] Статистика считается правильно

---

## Known Limitations & Future Ideas
- WebSocket для real-time PnL (сейчас polling)
- Trailing Stop (умный стоп, следующий за ценой)
- Условные ордера (OCO - One Cancels Other)
- AI сигналы интеграция (если у тебя есть источник)
- Multi-user support (сейчас одиночный пользователь)
- Бэктестинг на исторических данных

---

## Quick Start (After Setup)
1. Установить Redis (или использовать in-memory)
2. Создать .env файл с токенами
3. `pip install -r requirements.txt`
4. `python main.py`
5. Открыть бота в Telegram
6. /start → настроить Testnet режим
7. Попробовать открыть тестовую сделку

---

**Last Updated:** 2025-12-15
**Status:** Phase 1 - Foundation in Progress
