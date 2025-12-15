# 🤖 Syntra AI Integration

**Quick-execute торговые сценарии с AI анализом**

---

## 📋 Обзор

Syntra AI — аналитическая система, которая анализирует рынок и предоставляет торговые сценарии с конкретными уровнями входа, стопа и целей.

**Trade Bot** интегрируется с Syntra AI для получения сценариев и автоматического расчёта размера позиции на основе риска пользователя.

---

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                   SYNTRA AI (Аналитик)                      │
│  - Анализирует рынок (технический анализ, индикаторы)      │
│  - Даёт сценарии (entry/SL/TP + confidence)                │
│  - НЕ знает про Bybit                                       │
│  - НЕ открывает позиции                                     │
└─────────────────────────────────────────────────────────────┘
                            ▲  │
                            │  │
                   request  │  │  scenarios (JSON)
                            │  ▼
┌─────────────────────────────────────────────────────────────┐
│                  TRADE BOT (Исполнитель)                    │
│  - Получает сценарии от Syntra AI                           │
│  - Показывает сценарии пользователю                         │
│  - Рассчитывает qty/margin (RiskCalculator)                 │
│  - Открывает позиции через Bybit API                        │
└─────────────────────────────────────────────────────────────┘
```

**Ключевой принцип:** Syntra AI — это ТОЛЬКО аналитик. Trade Bot — исполнитель.

---

## 🚀 Быстрый старт

### 1️⃣ Установка зависимостей

```bash
pip install aiohttp
```

### 2️⃣ Настройка .env

Добавь в `.env`:

```bash
# Syntra AI API
SYNTRA_API_URL=http://localhost:8000
AI_SCENARIOS_ENABLED=true

# Опционально: API Key если требуется аутентификация
# SYNTRA_API_KEY=your_api_key_here
```

### 3️⃣ Запуск Syntra AI

В отдельном терминале:

```bash
cd /path/to/syntra-ai
source .venv/bin/activate
python api_server.py
```

Syntra AI должен быть доступен на `http://localhost:8000`.

### 4️⃣ Запуск Trade Bot

```bash
cd /path/to/futures-bot
source venv/bin/activate
python main.py
```

### 5️⃣ Использование в Telegram

1. Открой бота в Telegram
2. Нажми **"🤖 AI Сценарии"**
3. Выбери символ (BTC, ETH, SOL...)
4. Выбери таймфрейм (1h, 4h, 1d)
5. Посмотри сценарии от Syntra AI
6. Выбери сценарий → выбери риск ($10, $20, $50...)
7. Подтверди → позиция открыта!

---

## 📊 User Flow

```
1. User нажимает "🤖 AI Сценарии"
   ↓
2. Bot: "Выбери символ" (BTC/ETH/SOL...)
   ↓
3. User выбирает BTCUSDT
   ↓
4. Bot: "Выбери таймфрейм" (1h/4h/1d)
   ↓
5. User выбирает 4h
   ↓
6. Bot → Syntra AI: GET /api/futures-scenarios?symbol=BTCUSDT&timeframe=4h
   ↓
7. Syntra AI анализирует рынок (индикаторы, паттерны, свечи)
   ↓
8. Syntra AI → Bot: 3 сценария (Long Breakout 75%, Short Reversal 60%, ...)
   ↓
9. Bot показывает список:
   🟢 Long Breakout (75%)
   Entry: $95000-95500 | Stop: $94300 | TP: $96500 | RR: 2.1

   🔴 Short Reversal (60%)
   Entry: $94800-95200 | Stop: $96000 | TP: $93000 | RR: 3.0
   ↓
10. User выбирает "Long Breakout"
   ↓
11. Bot показывает детали + кнопки риска:
    [💰 Trade $10] [💰 Trade $20] [💰 Trade $50]
   ↓
12. User нажимает "Trade $10"
   ↓
13. Bot САМ рассчитывает:
    - qty = $10 / |entry - stop|
    - margin = (qty * entry) / leverage
   ↓
14. Bot показывает confirmation:
    Entry: Market @ $95250
    Stop: $94300
    TP: $96500
    Risk: $10
    Qty: 0.014 BTC
    Margin: $26.67
    [✅ Подтвердить] [❌ Отмена]
   ↓
15. User нажимает "✅ Подтвердить"
   ↓
16. Bot → Bybit API:
    - place_order(Market, qty=0.014)
    - set_trading_stop(SL=$94300, TP=$96500)
   ↓
17. Bot: "✅ Сделка открыта!"
```

---

## 🔧 Технические детали

### Syntra Client (`services/syntra_client.py`)

```python
from services.syntra_client import get_syntra_client

# Получить сценарии
syntra = get_syntra_client()

scenarios = await syntra.get_scenarios(
    symbol="BTCUSDT",
    timeframe="4h",
    max_scenarios=3,
    user_params={
        "risk_usd": 10,  # Фильтрация/приоритизация на основе риска
        "max_leverage": 5
    }
)

# Структура сценария:
scenario = {
    "id": 1,
    "name": "Long Breakout",
    "bias": "long",
    "confidence": 0.75,

    "entry": {
        "price_min": 95000,
        "price_max": 95500,
        "type": "market_order",
        "reason": "Breakout above key resistance"
    },

    "stop_loss": {
        "recommended": 94300,
        "conservative": 94000,
        "aggressive": 94500,
        "reason": "Below support level"
    },

    "targets": [
        {
            "level": 1,
            "price": 96500,
            "partial_close_pct": 50,
            "rr": 2.1,
            "reason": "Previous high"
        },
        {
            "level": 2,
            "price": 98000,
            "partial_close_pct": 50,
            "rr": 3.8,
            "reason": "Next resistance"
        }
    ],

    "leverage": {
        "recommended": "5x-8x",
        "max_safe": "10x"
    },

    "why": {
        "bullish_factors": [
            "Strong volume breakout",
            "EMA crossover on 4h"
        ],
        "risks": [
            "High funding rate",
            "Weekend low liquidity"
        ]
    }
}
```

### Position Sizing (локально в Trade Bot)

```python
from services.risk_calculator import RiskCalculator
from services.bybit import BybitClient

# Извлечь параметры из сценария
entry_price = (scenario["entry"]["price_min"] + scenario["entry"]["price_max"]) / 2
stop_price = scenario["stop_loss"]["recommended"]
risk_usd = 10  # выбрано пользователем
leverage = 5    # из settings

# Рассчитать позицию (Trade Bot делает сам!)
bybit = BybitClient(testnet=True)
risk_calc = RiskCalculator(bybit)

position = await risk_calc.calculate_position(
    symbol="BTCUSDT",
    side="Buy",
    entry_price=entry_price,
    stop_price=stop_price,
    risk_usd=risk_usd,
    leverage=leverage
)

# position = {
#     "qty": "0.014",
#     "actual_risk_usd": 9.8,
#     "margin_required": 26.67,
#     ...
# }
```

---

## ⚙️ Настройки

### В config.py:

```python
# Syntra AI API
SYNTRA_API_URL = os.getenv('SYNTRA_API_URL', 'http://localhost:8000')
SYNTRA_API_KEY = os.getenv('SYNTRA_API_KEY')
SYNTRA_API_TIMEOUT = int(os.getenv('SYNTRA_API_TIMEOUT', 30))
AI_SCENARIOS_ENABLED = os.getenv('AI_SCENARIOS_ENABLED', 'true').lower() == 'true'
```

### В .env:

```bash
SYNTRA_API_URL=http://localhost:8000
AI_SCENARIOS_ENABLED=true
SYNTRA_API_TIMEOUT=30
```

---

## 🧪 Тестирование

### 1. Проверить доступность Syntra AI:

```bash
curl http://localhost:8000/api/futures-scenarios/health
```

**Ответ:**
```json
{
  "success": true,
  "status": "healthy"
}
```

### 2. Получить сценарии вручную:

```bash
curl -X POST "http://localhost:8000/api/futures-scenarios" \
     -H "Content-Type: application/json" \
     -d '{"symbol": "BTCUSDT", "timeframe": "4h"}'
```

### 3. В боте:

1. Нажми "🤖 AI Сценарии"
2. Выбери BTC → 4h
3. Должны появиться сценарии

---

## 🔐 Безопасность

### ✅ ЧТО БЕЗОПАСНО:

- Syntra AI НЕ имеет доступа к Bybit API
- Syntra AI НЕ может открывать позиции
- Syntra AI НЕ знает баланс пользователя (если не передашь)
- Trade Bot рассчитывает qty локально
- Trade Bot открывает позиции через свой Bybit API

### ⚠️ ЧТО ПЕРЕДАЁТСЯ В SYNTRA AI:

- Symbol (BTCUSDT, ETHUSDT...)
- Timeframe (1h, 4h, 1d)
- Опционально: risk_usd, max_leverage (только для фильтрации сценариев)

**НЕ передаётся:** API keys, баланс, позиции, история сделок.

---

## 📝 Структура файлов

```
futures-bot/
├── services/
│   ├── syntra_client.py        # Клиент для Syntra AI API
│   ├── risk_calculator.py      # Расчёт qty локально
│   └── bybit/                  # Bybit API client
│
├── bot/
│   ├── handlers/
│   │   └── ai_scenarios.py     # Handler для AI сценариев
│   ├── keyboards/
│   │   └── ai_scenarios_kb.py  # Клавиатуры для AI
│   └── states/
│       └── trade_states.py     # FSM states (AIScenarioStates)
│
├── config.py                   # Настройки (SYNTRA_API_URL)
├── .env                        # Переменные окружения
└── main.py                     # Регистрация ai_scenarios router
```

---

## 🐛 Troubleshooting

### ❌ "Failed to connect to Syntra AI"

**Причина:** Syntra AI не запущен или недоступен.

**Решение:**
1. Проверь что Syntra AI запущен:
   ```bash
   curl http://localhost:8000/api/futures-scenarios/health
   ```

2. Проверь `SYNTRA_API_URL` в `.env`

3. Проверь логи Syntra AI

### ❌ "API returned error: Invalid symbol"

**Причина:** Символ не поддерживается Syntra AI.

**Решение:** Используй только `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `HYPEUSDT`.

### ❌ "No scenarios found"

**Причина:** Syntra AI не нашёл подходящих сценариев для данного символа/таймфрейма.

**Решение:**
- Попробуй другой timeframe
- Попробуй другой символ
- Проверь логи Syntra AI для деталей

---

## 🎓 Best Practices

### 1. Всегда проверяй confidence

```python
if scenario["confidence"] >= 0.75:
    # High confidence - можно торговать
elif scenario["confidence"] >= 0.60:
    # Medium confidence - меньше risk
else:
    # Low confidence - skip
```

### 2. Используй recommended leverage

```python
leverage_recommended = scenario["leverage"]["recommended"]  # "5x-8x"
leverage = int(leverage_recommended.split("-")[0].replace("x", ""))  # 5
```

### 3. Мониторь invalidation

```python
invalidation = scenario.get("invalidation", {})
invalidation_price = invalidation.get("price")

# Если цена пробила invalidation level → закрыть позицию
```

---

## 📞 Поддержка

- **Issues:** [GitHub Issues](https://github.com/your-repo/issues)
- **Docs:** `/docs/AI_ANALYSIS` (Syntra AI)
- **Telegram:** @your_support_bot

---

**Happy Trading! 🚀**
