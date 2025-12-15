# Futures Trading Scenarios API

**Документация по API для получения структурированных торговых сценариев для фьючерсов**

---

## 📋 Обзор

Futures Trading API предоставляет структурированные торговые сценарии с конкретными уровнями входа, стоп-лосса и целей для автоматизации трейдинга на Binance Futures.

### ✨ Основные возможности:

- ✅ **2-3 торговых сценария** с confidence scoring (0-1)
- ✅ **Конкретные уровни**: entry zone, stop-loss, targets (TP1, TP2, TP3)
- ✅ **RR calculation** для каждого сценария
- ✅ **Leverage recommendations** на основе ATR volatility
- ✅ **Structured reasoning** (почему этот сценарий валидный)
- ✅ **Market context** (trend, phase, sentiment, volatility)

---

## 🚀 Quick Start

### Базовый запрос:

```bash
curl -X POST "http://localhost:8000/api/futures-scenarios" \
     -H "Content-Type: application/json" \
     -d '{
       "symbol": "BTCUSDT",
       "timeframe": "4h",
       "max_scenarios": 3
     }'
```

### Пример ответа (сокращенный):

```json
{
  "success": true,
  "symbol": "BTCUSDT",
  "current_price": 95234.5,
  "market_context": {
    "trend": "bullish",
    "bias": "long",
    "confidence": 0.75
  },
  "scenarios": [
    {
      "id": 1,
      "name": "Long Breakout",
      "confidence": 0.75,
      "entry": {
        "price_min": 95000.0,
        "price_max": 95500.0
      },
      "stop_loss": {
        "recommended": 94300.0
      },
      "targets": [
        {"level": 1, "price": 96500.0, "rr": 2.1},
        {"level": 2, "price": 98000.0, "rr": 3.8},
        {"level": 3, "price": 100000.0, "rr": 6.2}
      ],
      "leverage": {
        "recommended": "5x-8x",
        "max_safe": "10x"
      }
    }
  ]
}
```

---

## 📡 API Endpoints

### 1. POST `/api/futures-scenarios`

**Получить торговые сценарии для указанного символа**

#### Request Body:

```typescript
{
  symbol: string;        // Trading pair (e.g., "BTCUSDT")
  timeframe?: string;    // "1h" | "4h" | "1d" (default: "4h")
  max_scenarios?: number; // 1-5 (default: 3)
}
```

#### Response Schema:

```typescript
{
  success: boolean;
  symbol: string;
  timeframe: string;
  analysis_timestamp: string; // ISO 8601
  current_price: number;

  market_context: {
    trend: "bullish" | "bearish" | "sideways";
    phase: "continuation" | "reversal" | "accumulation" | "distribution";
    sentiment: "extreme_greed" | "greed" | "neutral" | "fear" | "extreme_fear";
    volatility: "very_low" | "low" | "medium" | "high" | "very_high";
    bias: "long" | "short" | "neutral";
    strength: number; // 0.0 - 1.0
    rsi?: number;
    funding_rate_pct?: number;
    long_short_ratio?: number;
  };

  scenarios: TradingScenario[];
  key_levels: KeyLevels;
  data_quality: DataQuality;
  metadata: object;
}
```

---

## 🎯 Trading Scenario Schema

Каждый сценарий содержит:

```typescript
{
  id: number;
  name: string;
  bias: "long" | "short" | "neutral";
  confidence: number; // 0.0 - 1.0

  entry: {
    price_min: number;
    price_max: number;
    type: "limit_order" | "market_order";
    reason: string;
  };

  stop_loss: {
    conservative: number;
    aggressive: number;
    recommended: number;
    reason: string;
  };

  targets: [
    {
      level: 1 | 2 | 3;
      price: number;
      partial_close_pct: number; // Процент закрытия позиции
      rr: number; // Risk/Reward ratio
      reason: string;
    }
  ];

  leverage: {
    recommended: string; // "3x-5x"
    max_safe: string;    // "10x"
    volatility_adjusted: boolean;
    atr_pct?: number;
  };

  invalidation: {
    price: number;
    condition: string;
  };

  why: {
    bullish_factors?: string[];
    bearish_factors?: string[];
    risks: string[];
  };

  conditions: string[]; // Условия для входа
}
```

---

## 💡 Примеры использования

### 1. Получить сценарии для BTC с 1h таймфреймом:

```bash
curl -X POST "http://localhost:8000/api/futures-scenarios" \
     -H "Content-Type: application/json" \
     -d '{
       "symbol": "BTCUSDT",
       "timeframe": "1h",
       "max_scenarios": 2
     }'
```

### 2. Получить список поддерживаемых символов:

```bash
curl "http://localhost:8000/api/futures-scenarios/supported-symbols"
```

**Response:**
```json
{
  "success": true,
  "symbols": [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    ...
  ],
  "count": 25
}
```

### 3. Health check:

```bash
curl "http://localhost:8000/api/futures-scenarios/health"
```

**Response:**
```json
{
  "success": true,
  "status": "healthy",
  "binance_api": "connected",
  "has_api_keys": true,
  "available_features": {
    "basic_analysis": true,
    "funding_rates": true,
    "open_interest": true,
    "liquidation_data": true
  }
}
```

---

## 🤖 Интеграция с трейдинг-ботом

### Пример: Python трейдинг-бот

```python
import requests
import asyncio
from binance.client import Client

class FuturesTradingBot:
    def __init__(self, api_url, binance_api_key, binance_secret):
        self.api_url = api_url
        self.binance = Client(binance_api_key, binance_secret)

    async def get_trading_scenarios(self, symbol: str, timeframe: str = "4h"):
        """Получить торговые сценарии от Syntra API"""
        response = requests.post(
            f"{self.api_url}/api/futures-scenarios",
            json={
                "symbol": symbol,
                "timeframe": timeframe,
                "max_scenarios": 3
            }
        )
        return response.json()

    async def execute_scenario(self, scenario: dict, symbol: str):
        """Выполнить торговый сценарий автоматически"""

        # 1. Получить параметры сценария
        bias = scenario["bias"]
        entry_min = scenario["entry"]["price_min"]
        entry_max = scenario["entry"]["price_max"]
        stop_loss = scenario["stop_loss"]["recommended"]
        targets = scenario["targets"]
        leverage = scenario["leverage"]["recommended"]

        # 2. Установить плечо
        leverage_value = int(leverage.split("-")[0].replace("x", ""))
        self.binance.futures_change_leverage(
            symbol=symbol,
            leverage=leverage_value
        )

        # 3. Разместить лимитный ордер на вход
        side = "BUY" if bias == "long" else "SELL"
        entry_price = (entry_min + entry_max) / 2

        order = self.binance.futures_create_order(
            symbol=symbol,
            side=side,
            type="LIMIT",
            timeInForce="GTC",
            quantity=calculate_position_size(entry_price, stop_loss),
            price=entry_price
        )

        print(f"✅ Order placed: {side} {symbol} @ {entry_price}")

        # 4. Установить stop-loss
        sl_side = "SELL" if bias == "long" else "BUY"
        self.binance.futures_create_order(
            symbol=symbol,
            side=sl_side,
            type="STOP_MARKET",
            stopPrice=stop_loss,
            closePosition=True
        )

        # 5. Установить take-profit ордера
        for target in targets:
            tp_quantity = order["executedQty"] * (target["partial_close_pct"] / 100)
            self.binance.futures_create_order(
                symbol=symbol,
                side=sl_side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=target["price"],
                quantity=tp_quantity
            )

        return order

    async def run(self, symbol: str):
        """Главный цикл бота"""
        while True:
            # Получить сценарии
            result = await self.get_trading_scenarios(symbol)

            if not result["success"]:
                print(f"❌ Error: {result.get('error')}")
                await asyncio.sleep(300)
                continue

            # Показать сценарии пользователю
            scenarios = result["scenarios"]
            print(f"\n📊 {len(scenarios)} сценариев для {symbol}:")

            for i, scenario in enumerate(scenarios, 1):
                print(f"\n{i}. {scenario['name']} ({scenario['bias'].upper()})")
                print(f"   Confidence: {scenario['confidence']:.0%}")
                print(f"   Entry: ${scenario['entry']['price_min']:.2f} - ${scenario['entry']['price_max']:.2f}")
                print(f"   Stop: ${scenario['stop_loss']['recommended']:.2f}")
                print(f"   Targets: ", end="")
                for t in scenario['targets']:
                    print(f"TP{t['level']}=${t['price']:.2f} (RR:{t['rr']}x) ", end="")
                print(f"\n   Leverage: {scenario['leverage']['recommended']}")

            # Автоматически выбрать сценарий с highest confidence
            best_scenario = max(scenarios, key=lambda x: x["confidence"])

            if best_scenario["confidence"] >= 0.7:
                print(f"\n🚀 Executing best scenario: {best_scenario['name']}")
                await self.execute_scenario(best_scenario, symbol)
            else:
                print(f"\n⏳ Waiting for higher confidence signal...")

            # Проверка каждые 5 минут
            await asyncio.sleep(300)


# Запуск бота
if __name__ == "__main__":
    bot = FuturesTradingBot(
        api_url="http://localhost:8000",
        binance_api_key="YOUR_API_KEY",
        binance_secret="YOUR_SECRET"
    )

    asyncio.run(bot.run("BTCUSDT"))
```

---

## 📊 Data Sources

API использует следующие источники данных:

### 1. **Binance Futures**
- OHLCV данные (200 свечей)
- Funding rates
- Open Interest
- Long/Short ratio
- Liquidation history (требует API keys)

### 2. **Technical Analysis**
- RSI, MACD, EMA (20, 50, 200)
- ATR (Average True Range)
- Bollinger Bands
- VWAP, OBV
- Candlestick patterns

### 3. **Market Sentiment**
- Fear & Greed Index
- BTC dominance
- Multi-timeframe analysis

---

## ⚙️ Configuration

### Environment Variables:

```bash
# Binance API (опционально, для liquidation data)
BINANCE_API_KEY=your_api_key
BINANCE_SECRET=your_secret

# Syntra API
API_HOST=0.0.0.0
API_PORT=8000
```

### Rate Limits:

- **Без auth**: 10 requests / hour
- **С auth**: зависит от subscription tier
- **Binance API**: 1200 requests / minute (weight-based)

---

## 🛠️ Error Handling

### Возможные ошибки:

```json
// 400 Bad Request - Невалидный символ
{
  "detail": "Invalid symbol. Must be a USDT perpetual pair"
}

// 500 Internal Server Error
{
  "detail": "Failed to analyze BTCUSDT: Insufficient candlestick data"
}
```

### Обработка ошибок в боте:

```python
try:
    result = await bot.get_trading_scenarios("BTCUSDT")

    if not result["success"]:
        error = result.get("error")

        if "Insufficient" in error:
            print("⏳ Waiting for more data...")
            await asyncio.sleep(60)
        else:
            print(f"❌ Critical error: {error}")

except requests.exceptions.RequestException as e:
    print(f"🌐 Network error: {e}")
    await asyncio.sleep(30)
```

---

## 📈 Data Quality Assessment

Каждый ответ содержит `data_quality` объект:

```json
{
  "completeness": 95,  // 0-100%
  "sources": [
    "candlestick_data",
    "technical_indicators",
    "funding_rates",
    "open_interest",
    "liquidation_history"
  ],
  "warnings": null  // или ["Liquidation data unavailable"]
}
```

### Интерпретация:

- **95-100%**: Excellent quality, все источники доступны
- **80-94%**: Good quality, minor data missing
- **60-79%**: Fair quality, некоторые данные отсутствуют
- **< 60%**: Poor quality, рекомендуется не торговать

---

## 🎓 Best Practices

### 1. **Always check confidence score**

```python
if scenario["confidence"] >= 0.75:
    # High confidence - можно торговать
    execute_trade(scenario)
elif scenario["confidence"] >= 0.60:
    # Medium confidence - меньше risk
    execute_trade_conservative(scenario)
else:
    # Low confidence - skip
    print("⏳ Waiting for better setup")
```

### 2. **Use leverage recommendations**

```python
# Не превышай max_safe leverage
recommended = scenario["leverage"]["recommended"]  # "5x-8x"
max_safe = scenario["leverage"]["max_safe"]        # "10x"

# Extract numeric value
leverage = int(recommended.split("-")[0].replace("x", ""))
```

### 3. **Implement partial take-profits**

```python
for target in scenario["targets"]:
    # Закрывай позицию частями
    close_percent = target["partial_close_pct"]  # 30%, 40%, 30%
    tp_price = target["price"]

    place_take_profit_order(tp_price, close_percent)
```

### 4. **Monitor invalidation conditions**

```python
invalidation_price = scenario["invalidation"]["price"]

# Если цена пробила invalidation level
if current_price < invalidation_price and position_side == "long":
    close_position()
    print("❌ Scenario invalidated - closing position")
```

---

## 🔐 Security

### Authentication (опционально):

```bash
curl -X POST "http://localhost:8000/api/futures-scenarios" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_TOKEN" \
     -d '{
       "symbol": "BTCUSDT"
     }'
```

---

## 📞 Support

- **GitHub Issues**: [https://github.com/your-repo/issues](https://github.com/your-repo/issues)
- **Telegram**: @syntra_support
- **Email**: support@syntra.com

---

## 📜 License

MIT License - see [LICENSE](../LICENSE) file

---

## 🚧 Roadmap

### Планируемые фичи:

- [ ] **Volume Delta** - buy vs sell pressure в реальном времени
- [ ] **OI Change tracking** - динамика открытого интереса
- [ ] **Market Structure** - HH/HL/LH/LL, BOS, CHoCH автоопределение
- [ ] **Liquidation Heatmap** - clusters выше/ниже цены
- [ ] **Session Detection** - Asia/London/NY sessions
- [ ] **Macro Events** - календарь важных событий
- [ ] **Multi-symbol correlation** - BTC vs ALTs correlation matrix
- [ ] **WebSocket support** - real-time сценарии

---

**Happy Trading! 🚀📈**
