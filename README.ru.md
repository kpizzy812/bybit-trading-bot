<p align="center">
  <img src="assets/logo.jpeg" alt="Deep Signal" width="200"/>
</p>

<h1 align="center">Deep Signal</h1>

<p align="center">
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Proprietary-red.svg" alt="License"/></a>
  <a href="https://telegram.org"><img src="https://img.shields.io/badge/Platform-Telegram-blue.svg" alt="Telegram"/></a>
  <a href="https://bybit.com"><img src="https://img.shields.io/badge/Exchange-Bybit-orange.svg" alt="Bybit"/></a>
</p>

<p align="center">
  <b><a href="README.md">English version</a></b>
</p>

Профессиональный Telegram-бот для торговли фьючерсами Bybit USDT Perpetual с автоматическим управлением рисками, AI-аналитикой и мониторингом позиций в реальном времени.

## Ключевые возможности

### Торговое ядро
- **Trade Wizard** — 8-шаговое открытие позиции с валидацией на каждом этапе
- **Авто-расчёт размера** — Расчёт от риска: `qty = risk_usd / |entry - stop|`
- **Обязательные SL/TP** — Каждая сделка требует стоп-лосс; тейк-профит поддерживает режимы Single, Ladder, RR
- **Динамические символы** — Universe Service с авто-обнаружением топ-монет по категориям (Popular, Gainers, Losers, Volatile, Trending)

### AI-интеграция
- **AI Scenarios** — Интеграция с Syntra AI для генерации сценариев с уровнями entry/SL/TP и confidence scoring
- **Ladder Entry (Risk-on-Plan)** — Автоматизация multi-order входа со взвешенным распределением и auto-downgrade
- **Supervisor Advisory** — Рекомендации по корректировке позиций в реальном времени (SL/TP, ранний выход)
- **Feedback Loop** — Автоматический сбор обратной связи для улучшения AI-моделей

### Управление рисками
- **Real EV Tracking** — Расчёт Expected Value с авто-отключением убыточных стратегий
- **Risk Scaling по Confidence** — Автоматическая корректировка риска на основе уверенности AI (0.7x–1.3x)
- **Safety Gates** — Жёсткие лимиты: макс. риск $20, макс. маржа $150, макс. плечо 10x
- **Trading Modes** — Conservative, Standard, High Risk, Meme с соответствующими фильтрами

### Управление позициями
- **Real-time Monitor** — Фоновое отслеживание PnL каждые 15 секунд
- **Auto Breakeven** — Автоматический перенос SL на entry после срабатывания TP1
- **Post-SL Analysis** — Отслеживание цены 1h/4h после стоп-лосса для оценки качества SL
- **Partial Close** — Поддержка ladder take-profit с частичным закрытием позиции

### Аналитика
- **Trade History** — Полный журнал с фильтрацией по символу, дате, исходу
- **Statistics Dashboard** — Win rate, avg PnL, max drawdown, breakdown по архетипам
- **Funnel Analysis** — Отслеживание gate performance (Entry → TP1 → TP2 → TP3)

## Архитектура

```
┌──────────────────────────────────────────────────────────────────┐
│                    TELEGRAM BOT (aiogram 3.x)                     │
│  ├─ Trade Wizard FSM (8 шагов)                                   │
│  ├─ AI Scenarios (просмотр, редактирование, исполнение)          │
│  ├─ Position Management (мониторинг, редактирование SL/TP)       │
│  ├─ Supervisor Advice (уведомления, quick actions)               │
│  └─ Statistics Dashboard (inline UI)                             │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                      СЕРВИСНЫЙ СЛОЙ                               │
│                                                                   │
│  Торговля:                   │  AI & Аналитика:                  │
│  ├─ RiskCalculator           │  ├─ SyntraClient (сценарии)       │
│  ├─ PositionMonitor          │  ├─ SupervisorClient (advisory)   │
│  ├─ OrderMonitor             │  ├─ StatsClient (статистика)      │
│  ├─ EntryPlanMonitor         │  ├─ RealEVCalculator              │
│  ├─ BreakevenManager         │  ├─ UniverseService               │
│  ├─ PostSLAnalyzer           │  └─ FeedbackCollector             │
│  └─ TradeLogger              │                                   │
└──────────────────────────────────────────────────────────────────┘
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
deep-signal/
├── bot/
│   ├── handlers/
│   │   ├── trade_wizard/        # 8-шаговый визард (модульный)
│   │   ├── positions/           # Управление позициями
│   │   ├── ai_scenarios/        # AI сценарии
│   │   ├── supervisor.py        # Advisory уведомления
│   │   ├── stats.py             # Statistics dashboard
│   │   ├── history.py           # История сделок
│   │   ├── settings.py          # Настройки пользователя
│   │   └── ev_stats.py          # Real EV tracking
│   ├── keyboards/               # Inline/Reply клавиатуры
│   ├── states/                  # FSM состояния
│   └── middlewares/             # Проверка владельца, логи
├── services/
│   ├── bybit/                   # Bybit API V5 клиент
│   ├── entry_plan/              # Автоматизация ladder entry
│   ├── real_ev/                 # Расчёт Expected Value
│   ├── feedback/                # Сбор AI feedback
│   ├── trading_modes/           # Фильтрация по режимам
│   ├── universe/                # Динамический выбор символов
│   ├── risk_calculator.py       # Расчёт размера позиции
│   ├── position_monitor.py      # Real-time PnL (685 строк)
│   ├── syntra_client.py         # AI scenarios API
│   ├── supervisor_client.py     # Advisory API
│   ├── stats_client.py          # Statistics API
│   ├── breakeven_manager.py     # Auto breakeven
│   ├── post_sl_analyzer.py      # Post-SL анализ
│   └─ trade_logger.py          # Журнал сделок (1017 строк)
├── database/                    # SQLAlchemy модели
├── storage/                     # Redis клиент, настройки
├── utils/                       # Валидаторы, форматтеры
├── alembic/                     # DB миграции
├── config.py                    # Централизованная конфигурация
└── main.py                      # Точка входа
```

## Уникальные детали реализации

### Risk-on-Plan Model для Ladder Entry

Гарантирует, что суммарный риск до SL **всегда ≤ risk_usd**, независимо от того, сколько entry ордеров исполнится:

```python
P_avg = Σ(w_i * p_i)           # Средневзвешенная цена входа
Q_total = R / |P_avg - SL|     # Общий размер позиции
Q_i = Q_total * w_i            # Размер каждого ордера
```

**Auto-downgrade**: Если qty недостаточно для всех ордеров, система автоматически сокращает количество ордеров, сохраняя лучшие цены.

### Activation Buffer для Touch-Plans

Когда AI указывает `activation_type: touch`, система добавляет 0.5% буфер к activation_level чтобы успеть выставить ордера до достижения первого entry.

### Outcome Classification V2

Фреймворк классификации исходов сделок:
- `sl_early` — SL сработал до TP1 (полный лосс -1R)
- `be_after_tp1` — Выход на breakeven после TP1
- `stop_in_profit` — Трейл SL в профит
- `tp1/tp2/tp3_final` — Финальный выход на целях

## Установка

### Требования

- Python 3.12+
- Redis (опционально, fallback на in-memory)
- PostgreSQL (для истории и аналитики)

### Настройка

```bash
git clone https://github.com/yourusername/deep-signal.git
cd deep-signal

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Отредактируйте .env
```

### Переменные окружения

```bash
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
OWNER_TELEGRAM_ID=123456789

# Bybit API (ТОЛЬКО права Trade, БЕЗ Withdraw!)
BYBIT_API_KEY=your_api_key
BYBIT_API_SECRET=your_api_secret

# Bybit Testnet
BYBIT_TESTNET_API_KEY=your_testnet_key
BYBIT_TESTNET_API_SECRET=your_testnet_secret

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/deep_signal

# AI Services (опционально)
SYNTRA_API_URL=http://localhost:8000
SYNTRA_API_KEY=your_api_key
SUPERVISOR_API_URL=http://localhost:8001
STATS_API_URL=http://localhost:8002
```

### Запуск

```bash
python main.py
```

## Технологии

| Компонент | Технология |
|-----------|------------|
| Bot Framework | aiogram 3.x (async) |
| Database | PostgreSQL + SQLAlchemy 2.0 |
| Cache | Redis (hiredis) |
| Migrations | Alembic |
| Exchange | Bybit API V5 |
| Logging | Loguru |
| Precision | Decimal (без float ошибок) |

## Безопасность

- **API ключи**: Только права Trade, **НИКОГДА** не включайте Withdraw
- **Race Protection**: Redis locks предотвращают дубликаты (TTL: 20s)
- **Подтверждение**: Каждая сделка требует ручного подтверждения
- **Idempotency**: Уникальный `clientOrderId` для каждого ордера
- **Rollback**: Авто-закрытие позиции если SL не установился
- **Owner-only**: Single-user режим для персональной торговли

## Graceful Degradation

- Redis опционален → fallback на in-memory
- PostgreSQL опционален → Redis-only режим
- Supervisor опционален → работает без advisory
- AI Scenarios опционален → доступна ручная торговля

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
