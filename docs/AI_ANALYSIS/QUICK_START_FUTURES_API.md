# Quick Start: Futures Trading API

**5-минутный старт для интеграции с Trade Bot**

---

## 🚀 Запуск

```bash
cd /Users/a1/Projects/Syntra\ Trade\ Consultant
source .venv/bin/activate
python api_server.py
```

API доступен на: `http://localhost:8000`

---

## 📡 Основные endpoints

### 1. Получить торговые сценарии

```bash
POST /api/futures-scenarios
```

**Request:**
```json
{
  "symbol": "BTCUSDT",
  "timeframe": "4h"
}
```

**Response (сокращённо):**
```json
{
  "success": true,
  "current_price": 95234.5,
  "scenarios": [
    {
      "name": "Long Breakout",
      "confidence": 0.75,
      "entry": {"price_min": 95000, "price_max": 95500},
      "stop_loss": {"recommended": 94300},
      "targets": [
        {"level": 1, "price": 96500, "rr": 2.1}
      ],
      "leverage": {"recommended": "5x-8x"},
      "why": {
        "bullish_factors": ["Uptrend confirmed", "Funding negative"]
      }
    }
  ]
}
```

### 2. Рассчитать размер позиции (helper)

```bash
POST /api/calculate-position-size
```

**Request:**
```json
{
  "symbol": "BTCUSDT",
  "side": "long",
  "entry_price": 95250.0,
  "stop_loss": 94300.0,
  "risk_usd": 10.0,
  "leverage": 5
}
```

**Response:**
```json
{
  "success": true,
  "position": {
    "qty": "0.014",
    "margin_required": 26.67,
    "actual_risk_usd": 9.8
  },
  "validation": {
    "is_valid": true
  }
}
```

---

## 🤖 Интеграция с Trade Bot (минимум)

```python
import aiohttp

async def get_trade_setup(symbol: str, risk_usd: float):
    """Полный флоу: сценарии → расчёт → готово к исполнению"""

    # 1. Получить сценарии
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "http://localhost:8000/api/futures-scenarios",
            json={"symbol": symbol}
        ) as resp:
            data = await resp.json()

    # 2. Выбрать лучший сценарий
    best = max(data["scenarios"], key=lambda x: x["confidence"])

    # 3. Рассчитать позицию
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "http://localhost:8000/api/calculate-position-size",
            json={
                "symbol": symbol,
                "side": best["bias"],
                "entry_price": (best["entry"]["price_min"] + best["entry"]["price_max"]) / 2,
                "stop_loss": best["stop_loss"]["recommended"],
                "risk_usd": risk_usd,
                "leverage": 5
            }
        ) as resp:
            position = await resp.json()

    # 4. Готово к исполнению!
    return {
        "scenario": best,
        "position": position
    }


# Использование
result = await get_trade_setup("BTCUSDT", risk_usd=10.0)

print(f"Setup: {result['scenario']['name']}")
print(f"Qty: {result['position']['position']['qty']}")
print(f"Margin: ${result['position']['position']['margin_required']:.2f}")

# Теперь открывай позицию через Bybit API
# await bybit.place_order(...)
```

---

## 📊 Что возвращает API

### Market Context:
- `trend`: "bullish" | "bearish" | "sideways"
- `bias`: "long" | "short" | "neutral"
- `session`: Текущая торговая сессия (Asia/London/NY)
- `volume`: Анализ объёмов (spikes, relative volume)

### Scenarios:
- `confidence`: 0.0 - 1.0 (уверенность в сценарии)
- `entry`: price_min / price_max
- `stop_loss`: recommended / conservative / aggressive
- `targets`: TP1, TP2, TP3 с RR ratios
- `leverage`: recommended / max_safe
- `why`: bullish_factors / bearish_factors / risks

---

## 🔧 Настройки

### Поддерживаемые символы:
BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, и т.д.

Любая USDT perpetual пара на Binance Futures.

### Таймфреймы:
- `1h` — краткосрочная торговля
- `4h` — среднесрочная (рекомендуется)
- `1d` — долгосрочная

---

## ⚠️ Важно

1. **Syntra AI не открывает позиции** — это аналитический сервис
2. **Trade Bot сам открывает позиции** через Bybit/Binance API
3. **Position size calculation** — это helper, можешь использовать свой калькулятор

---

## 📚 Полная документация

- [FUTURES_TRADING_API.md](FUTURES_TRADING_API.md) — детальная документация
- [FUTURES_API_FINAL_SUMMARY.md](FUTURES_API_FINAL_SUMMARY.md) — что реализовано

---

**Готово к использованию! 🚀**
