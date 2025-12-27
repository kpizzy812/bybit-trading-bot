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
  <b><a href="README.ru.md">Русская версия</a></b>
</p>

Professional Telegram bot for Bybit USDT Perpetual futures trading with automated risk management, AI-powered trade scenarios, and real-time position monitoring.

## Key Features

### Trading Core
- **Trade Wizard** — 8-step position opening with validation at each stage
- **Auto Position Sizing** — Risk-based calculation: `qty = risk_usd / |entry - stop|`
- **Mandatory SL/TP** — Every trade requires stop-loss; take-profit supports Single, Ladder, or RR modes
- **Dynamic Symbols** — Universe Service with auto-discovery of top coins by category (Popular, Gainers, Losers, Volatile, Trending)

### AI Integration
- **AI Scenarios** — Integration with Syntra AI for trade scenario generation with entry/SL/TP levels and confidence scoring
- **Ladder Entry (Risk-on-Plan)** — Multi-order entry automation with weighted distribution and auto-downgrade
- **Supervisor Advisory** — Real-time recommendations for position adjustments (SL/TP moves, early exit)
- **Feedback Loop** — Automatic feedback collection for AI model improvement

### Risk Management
- **Real EV Tracking** — Expected Value calculation with auto-disable for losing strategies
- **Confidence-based Risk Scaling** — Automatic risk adjustment based on AI confidence (0.7x–1.3x)
- **Safety Gates** — Hard limits: max risk $20, max margin $150, max leverage 10x
- **Trading Modes** — Conservative, Standard, High Risk, Meme with appropriate filters

### Position Management
- **Real-time Monitor** — Background PnL tracking every 15 seconds
- **Auto Breakeven** — Automatic SL move to entry after TP1 hit
- **Post-SL Analysis** — Price tracking 1h/4h after stop-loss to evaluate SL quality
- **Partial Close** — Support for ladder take-profits with partial position closing

### Analytics
- **Trade History** — Complete journal with filtering by symbol, date, outcome
- **Statistics Dashboard** — Win rate, avg PnL, max drawdown, archetype breakdown
- **Funnel Analysis** — Gate performance tracking (Entry → TP1 → TP2 → TP3)

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    TELEGRAM BOT (aiogram 3.x)                     │
│  ├─ Trade Wizard FSM (8 steps)                                   │
│  ├─ AI Scenarios (view, edit, execute)                           │
│  ├─ Position Management (monitor, edit SL/TP, close)             │
│  ├─ Supervisor Advice (notifications, quick actions)             │
│  └─ Statistics Dashboard (inline UI)                             │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                      SERVICES LAYER                               │
│                                                                   │
│  Trading:                    │  AI & Analytics:                  │
│  ├─ RiskCalculator           │  ├─ SyntraClient (scenarios)      │
│  ├─ PositionMonitor          │  ├─ SupervisorClient (advisory)   │
│  ├─ OrderMonitor             │  ├─ StatsClient (statistics)      │
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

## Project Structure

```
deep-signal/
├── bot/
│   ├── handlers/
│   │   ├── trade_wizard/        # 8-step trade wizard (modular)
│   │   ├── positions/           # Position management
│   │   ├── ai_scenarios/        # AI scenario handling
│   │   ├── supervisor.py        # Advisory notifications
│   │   ├── stats.py             # Statistics dashboard
│   │   ├── history.py           # Trade history
│   │   ├── settings.py          # User preferences
│   │   └── ev_stats.py          # Real EV tracking
│   ├── keyboards/               # Inline/Reply keyboards
│   ├── states/                  # FSM states
│   └── middlewares/             # Owner check, logging
├── services/
│   ├── bybit/                   # Bybit API V5 client
│   ├── entry_plan/              # Ladder entry automation
│   ├── real_ev/                 # Expected Value calculation
│   ├── feedback/                # AI feedback collection
│   ├── trading_modes/           # Mode-based symbol filtering
│   ├── universe/                # Dynamic symbol discovery
│   ├── risk_calculator.py       # Position sizing
│   ├── position_monitor.py      # Real-time PnL (685 lines)
│   ├── syntra_client.py         # AI scenarios API
│   ├── supervisor_client.py     # Advisory API
│   ├── stats_client.py          # Statistics API
│   ├── breakeven_manager.py     # Auto breakeven
│   ├── post_sl_analyzer.py      # Post-SL analysis
│   └── trade_logger.py          # Trade journal (1017 lines)
├── database/                    # SQLAlchemy models
├── storage/                     # Redis client, settings
├── utils/                       # Validators, formatters
├── alembic/                     # DB migrations
├── config.py                    # Centralized configuration
└── main.py                      # Entry point
```

## Unique Implementation Details

### Risk-on-Plan Model for Ladder Entry

Ensures total risk to SL is **always ≤ risk_usd**, regardless of how many entry orders fill:

```python
P_avg = Σ(w_i * p_i)           # Weighted average entry price
Q_total = R / |P_avg - SL|     # Total position size
Q_i = Q_total * w_i            # Size per order
```

**Auto-downgrade**: If qty is insufficient for all orders, system automatically reduces order count while preserving best prices.

### Activation Buffer for Touch-Plans

When AI specifies `activation_type: touch`, system adds 0.5% buffer to activation_level to place orders before price reaches first entry.

### Outcome Classification V2

Framework for trade outcome classification:
- `sl_early` — SL hit before TP1 (full loss -1R)
- `be_after_tp1` — Exited at breakeven after TP1
- `stop_in_profit` — Trail SL in profit
- `tp1/tp2/tp3_final` — Final exit at targets

## Installation

### Prerequisites

- Python 3.12+
- Redis (optional, falls back to in-memory)
- PostgreSQL (for trade history and analytics)

### Setup

```bash
git clone https://github.com/yourusername/deep-signal.git
cd deep-signal

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your credentials
```

### Environment Variables

```bash
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
OWNER_TELEGRAM_ID=123456789

# Bybit API (Trade permissions ONLY, NO Withdraw!)
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

# AI Services (optional)
SYNTRA_API_URL=http://localhost:8000
SYNTRA_API_KEY=your_api_key
SUPERVISOR_API_URL=http://localhost:8001
STATS_API_URL=http://localhost:8002
```

### Running

```bash
python main.py
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Bot Framework | aiogram 3.x (async) |
| Database | PostgreSQL + SQLAlchemy 2.0 |
| Cache | Redis (hiredis) |
| Migrations | Alembic |
| Exchange | Bybit API V5 |
| Logging | Loguru |
| Precision | Decimal (no float errors) |

## Security

- **API Keys**: Trade-only permissions, **NEVER** enable Withdraw
- **Race Protection**: Redis locks prevent duplicate orders (TTL: 20s)
- **Confirmation**: Every trade requires manual confirmation
- **Idempotency**: Unique `clientOrderId` for each order
- **Rollback**: Auto-close position if SL setup fails
- **Owner-only**: Single-user mode for personal trading

## Graceful Degradation

- Redis optional → fallback to in-memory
- PostgreSQL optional → Redis-only mode
- Supervisor optional → works without advisory
- AI Scenarios optional → manual trading available

## License

This project is proprietary software. See [LICENSE](LICENSE) for details.

## Disclaimer

**This software is for educational purposes only.**

- Trading cryptocurrencies involves significant risk
- Past performance does not guarantee future results
- Never risk more than you can afford to lose
- Always start with Testnet before using real funds
- The author is not responsible for any financial losses

**Trade responsibly!**
