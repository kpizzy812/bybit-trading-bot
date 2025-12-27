# Bybit Futures Trading Bot

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)
[![Telegram](https://img.shields.io/badge/Platform-Telegram-blue.svg)](https://telegram.org)
[![Bybit](https://img.shields.io/badge/Exchange-Bybit-orange.svg)](https://bybit.com)

**[English version](README.md)**

Профессиональный Telegram-бот для торговли фьючерсами Bybit USDT Perpetual с автоматическим управлением рисками и AI-аналитикой.

## Возможности

- **Trade Wizard** — Пошаговое открытие позиции с валидацией на каждом этапе
- **Авто-расчёт размера** — Расчёт количества от риска: `qty = risk_$ / |entry - stop|`
- **Обязательные SL/TP** — Каждая сделка требует стоп-лосс и тейк-профит
- **Мониторинг позиций** — Отслеживание PnL в реальном времени с уведомлениями
- **AI Scenarios** — Интеграция с внешним AI API для торговых сценариев
- **Auto Breakeven** — Автоматический перенос SL на entry после TP1
- **История сделок** — Полный журнал со статистикой и винрейтом
- **Testnet/Live** — Переключение между тестовым и реальным режимом
- **Защита от race conditions** — Redis locks предотвращают дублирование ордеров

## Поддерживаемые инструменты

| Символ | Описание |
|--------|----------|
| BTCUSDT | Bitcoin Perpetual |
| ETHUSDT | Ethereum Perpetual |
| SOLUSDT | Solana Perpetual |
| BNBUSDT | BNB Perpetual |
| HYPEUSDT | Hyperliquid Perpetual |

## Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                     TELEGRAM BOT (aiogram)                       │
│  - Trade Wizard FSM                                              │
│  - Управление позициями                                          │
│  - Настройки и история                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      СЕРВИСНЫЙ СЛОЙ                              │
│  - Risk Calculator (точность Decimal)                           │
│  - Position Monitor (фоновые задачи)                            │
│  - Trade Logger (статистика)                                    │
│  - Syntra Client (AI scenarios API)                             │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────────┐
        │  Bybit   │   │  Redis   │   │  PostgreSQL  │
        │  API V5  │   │  Cache   │   │   Database   │
        └──────────┘   └──────────┘   └──────────────┘
```

## Структура проекта

```
futures-bot/
├── bot/
│   ├── handlers/
│   │   ├── trade_wizard/     # 8-шаговый визард
│   │   ├── positions.py      # Управление позициями
│   │   ├── settings.py       # Настройки пользователя
│   │   ├── history.py        # История сделок
│   │   └── ai_scenarios.py   # Интеграция AI сценариев
│   ├── keyboards/            # Inline/Reply клавиатуры
│   ├── states/               # FSM состояния
│   └── middlewares/          # Проверка владельца, логи
├── services/
│   ├── bybit/                # Bybit API V5 клиент
│   │   ├── client.py         # Базовый клиент
│   │   ├── orders.py         # Управление ордерами
│   │   ├── positions.py      # Запросы позиций
│   │   └── market_data.py    # Тикеры, инструменты
│   ├── risk_calculator.py    # Расчёт размера позиции
│   ├── position_monitor.py   # Фоновый мониторинг
│   ├── trade_logger.py       # Журнал сделок
│   └── syntra_client.py      # Клиент AI API
├── database/                 # SQLAlchemy модели
├── storage/                  # Redis/хранилище настроек
├── utils/                    # Валидаторы, форматтеры
├── alembic/                  # Миграции БД
├── main.py                   # Точка входа
├── config.py                 # Конфигурация
└── requirements.txt
```

## Установка

### Требования

- Python 3.12+
- Redis (опционально, fallback на in-memory)
- PostgreSQL (для истории сделок)

### Настройка

```bash
# Клонирование репозитория
git clone https://github.com/yourusername/bybit-trading-bot.git
cd bybit-trading-bot

# Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Установка зависимостей
pip install -r requirements.txt

# Настройка окружения
cp .env.example .env
# Отредактируйте .env с вашими данными
```

### Переменные окружения

```bash
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
OWNER_TELEGRAM_ID=123456789

# Bybit API (ТОЛЬКО права Trade, БЕЗ Withdraw!)
BYBIT_API_KEY=your_api_key
BYBIT_API_SECRET=your_api_secret

# Bybit Testnet (рекомендуется для тестирования)
BYBIT_TESTNET_API_KEY=your_testnet_key
BYBIT_TESTNET_API_SECRET=your_testnet_secret

# Redis (опционально)
REDIS_HOST=localhost
REDIS_PORT=6379

# AI Scenarios API (опционально)
SYNTRA_API_URL=http://localhost:8000
SYNTRA_API_KEY=your_api_key
```

### Запуск

```bash
python main.py
```

## Использование

### Главное меню

```
┌─────────────────────────────────────┐
│  [➕] Открыть сделку  [📊] Позиции  │
│  [⚙️] Настройки      [🧾] История   │
│  [🧪] Testnet/Live                  │
└─────────────────────────────────────┘
```

### Trade Wizard

1. **Символ** — Выбор торговой пары (BTC, ETH, SOL...)
2. **Направление** — Long или Short
3. **Тип входа** — Market или Limit
4. **Стоп-лосс** — Обязателен! По цене или проценту
5. **Риск и плечо** — $5/$10/$15, 2x/3x/5x
6. **Тейк-профит** — Single TP, Лесенка, или по RR
7. **Подтверждение** — Проверка и исполнение

### Управление позициями

- Просмотр открытых позиций с PnL
- Частичное закрытие (25%, 50%, 75%)
- Передвижение стоп-лосса (breakeven, trail)
- Panic close всех позиций

## Интеграция AI Scenarios

Бот интегрируется с внешним AI API (Syntra AI), который предоставляет:

- **Торговые сценарии** с уровнями входа, стоп-лосса и тейк-профита
- **Оценка уверенности** на основе анализа рынка
- **One-tap execution** — применение сценария с автоматическим расчётом размера

```
┌─────────────────────────────────────────────┐
│           SYNTRA AI (Аналитик)              │
│  - Анализ рынка и технические индикаторы   │
│  - Торговые сценарии (entry/SL/TP)         │
│  - Оценка уверенности                       │
└─────────────────────────────────────────────┘
                     │ JSON API
                     ▼
┌─────────────────────────────────────────────┐
│           TRADE BOT (Исполнитель)           │
│  - Получает сценарии от AI                 │
│  - Рассчитывает размер от риска            │
│  - Исполняет через Bybit API               │
└─────────────────────────────────────────────┘
```

## Безопасность

- **API ключи**: Только права Trade, **НИКОГДА** не включайте Withdraw
- **Подтверждение**: Каждая сделка требует ручного подтверждения
- **Race Protection**: Redis locks предотвращают дубликаты
- **Idempotency**: Уникальный `clientOrderId` для каждого ордера
- **Rollback**: Авто-закрытие позиции если SL не установился
- **Лимиты**: Настраиваемый макс. риск/маржа на сделку

## Технологии

| Компонент | Технология |
|-----------|------------|
| Bot Framework | aiogram 3.x |
| Async HTTP | aiohttp |
| Database | PostgreSQL + SQLAlchemy |
| Cache | Redis |
| Migrations | Alembic |
| Exchange | Bybit API V5 |

## Расчёт риска

Бот использует **правильную** формулу риска:

```python
# Размер позиции от фиксированного риска
qty = risk_usd / abs(entry_price - stop_price)

# Требуемая маржа
margin = (qty * entry_price) / leverage

# Плечо НЕ влияет на PnL, только на требование маржи
```

Все расчёты используют `Decimal` для точности и избежания ошибок float.

## Лицензия

Проприетарное ПО. См. файл [LICENSE](LICENSE).

## Дисклеймер

**Данное ПО предназначено только для образовательных целей.**

- Торговля криптовалютами сопряжена со значительным риском
- Прошлые результаты не гарантируют будущих
- Никогда не рискуйте больше, чем можете позволить себе потерять
- Всегда начинайте с Testnet перед использованием реальных средств
- Автор не несёт ответственности за финансовые потери

**Торгуйте ответственно!**
