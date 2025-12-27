# Bybit Futures Trading Bot

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)
[![Telegram](https://img.shields.io/badge/Platform-Telegram-blue.svg)](https://telegram.org)
[![Bybit](https://img.shields.io/badge/Exchange-Bybit-orange.svg)](https://bybit.com)

**[Русская версия](README.ru.md)**

Professional Telegram bot for Bybit USDT Perpetual futures trading with automated risk management and AI-powered trade scenarios.

## Features

- **Trade Wizard** — Step-by-step position opening with validation at each stage
- **Auto Position Sizing** — Calculates quantity from risk: `qty = risk_$ / |entry - stop|`
- **Mandatory SL/TP** — Every trade requires stop-loss and take-profit levels
- **Position Monitor** — Real-time PnL tracking with notifications
- **AI Scenarios** — Integration with external AI analytics API for trade scenarios
- **Auto Breakeven** — Automatically moves SL to entry after TP1 hit
- **Trade History** — Complete journal with statistics and winrate
- **Testnet/Live** — Seamless switching between paper trading and live
- **Race Condition Protection** — Redis locks prevent duplicate orders

## Supported Instruments

| Symbol | Description |
|--------|-------------|
| BTCUSDT | Bitcoin Perpetual |
| ETHUSDT | Ethereum Perpetual |
| SOLUSDT | Solana Perpetual |
| BNBUSDT | BNB Perpetual |
| HYPEUSDT | Hyperliquid Perpetual |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     TELEGRAM BOT (aiogram)                       │
│  - Trade Wizard FSM                                              │
│  - Position Management                                           │
│  - Settings & History                                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SERVICES LAYER                              │
│  - Risk Calculator (Decimal precision)                          │
│  - Position Monitor (background tasks)                          │
│  - Trade Logger (statistics)                                    │
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

## Project Structure

```
futures-bot/
├── bot/
│   ├── handlers/
│   │   ├── trade_wizard/     # 8-step trade wizard
│   │   ├── positions.py      # Position management
│   │   ├── settings.py       # User settings
│   │   ├── history.py        # Trade history
│   │   └── ai_scenarios.py   # AI scenarios integration
│   ├── keyboards/            # Inline/Reply keyboards
│   ├── states/               # FSM states
│   └── middlewares/          # Owner check, logging
├── services/
│   ├── bybit/                # Bybit API V5 client
│   │   ├── client.py         # Base client
│   │   ├── orders.py         # Order management
│   │   ├── positions.py      # Position queries
│   │   └── market_data.py    # Tickers, instruments
│   ├── risk_calculator.py    # Position sizing
│   ├── position_monitor.py   # Background monitoring
│   ├── trade_logger.py       # Trade journal
│   └── syntra_client.py      # AI API client
├── database/                 # SQLAlchemy models
├── storage/                  # Redis/settings storage
├── utils/                    # Validators, formatters
├── alembic/                  # DB migrations
├── main.py                   # Entry point
├── config.py                 # Configuration
└── requirements.txt
```

## Installation

### Prerequisites

- Python 3.12+
- Redis (optional, falls back to in-memory)
- PostgreSQL (for trade history)

### Setup

```bash
# Clone repository
git clone https://github.com/yourusername/bybit-trading-bot.git
cd bybit-trading-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
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

# Bybit Testnet (recommended for testing)
BYBIT_TESTNET_API_KEY=your_testnet_key
BYBIT_TESTNET_API_SECRET=your_testnet_secret

# Redis (optional)
REDIS_HOST=localhost
REDIS_PORT=6379

# AI Scenarios API (optional)
SYNTRA_API_URL=http://localhost:8000
SYNTRA_API_KEY=your_api_key
```

### Running

```bash
python main.py
```

## Usage

### Main Menu

```
┌─────────────────────────────────────┐
│  [+] Open Trade    [Chart] Positions│
│  [Gear] Settings   [Doc] History    │
│  [Test] Testnet/Live                │
└─────────────────────────────────────┘
```

### Trade Wizard Flow

1. **Symbol** — Select trading pair (BTC, ETH, SOL...)
2. **Direction** — Long or Short
3. **Entry Type** — Market or Limit
4. **Stop Loss** — Required! By price or percentage
5. **Risk & Leverage** — $5/$10/$15, 2x/3x/5x
6. **Take Profit** — Single TP, Ladder, or by RR
7. **Confirmation** — Review and execute

### Position Management

- View open positions with live PnL
- Partial close (25%, 50%, 75%)
- Move stop-loss (breakeven, trail)
- Panic close all positions

## AI Scenarios Integration

The bot integrates with an external AI analytics API (Syntra AI) that provides:

- **Trade scenarios** with entry, stop-loss, and take-profit levels
- **Confidence scoring** based on market analysis
- **One-tap execution** — apply scenario with automatic position sizing

```
┌─────────────────────────────────────────────┐
│           SYNTRA AI (Analytics)             │
│  - Market analysis & technical indicators   │
│  - Trade scenarios (entry/SL/TP)            │
│  - Confidence scoring                       │
└─────────────────────────────────────────────┘
                     │ JSON API
                     ▼
┌─────────────────────────────────────────────┐
│           TRADE BOT (Executor)              │
│  - Receives scenarios from AI              │
│  - Calculates position size from risk      │
│  - Executes via Bybit API                   │
└─────────────────────────────────────────────┘
```

## Security

- **API Keys**: Trade-only permissions, **NEVER** enable Withdraw
- **Confirmation**: Every trade requires manual confirmation
- **Race Protection**: Redis locks prevent duplicate orders
- **Idempotency**: Unique `clientOrderId` for each order
- **Rollback**: Auto-close position if SL setup fails
- **Limits**: Configurable max risk/margin per trade

## Tech Stack

| Component | Technology |
|-----------|------------|
| Bot Framework | aiogram 3.x |
| Async HTTP | aiohttp |
| Database | PostgreSQL + SQLAlchemy |
| Cache | Redis |
| Migrations | Alembic |
| Exchange | Bybit API V5 |

## Risk Calculation

The bot uses the **correct** risk formula:

```python
# Position size from fixed risk
qty = risk_usd / abs(entry_price - stop_price)

# Required margin
margin = (qty * entry_price) / leverage

# Leverage does NOT affect PnL, only margin requirement
```

All calculations use `Decimal` for precision to avoid floating-point errors.

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
