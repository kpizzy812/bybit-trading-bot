import os
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def require_env(name: str) -> str:
    """
    Получить обязательную переменную окружения с валидацией.
    Fail fast - бот не запустится без необходимых ключей.

    Args:
        name: Имя переменной окружения

    Returns:
        Значение переменной

    Raises:
        RuntimeError: Если переменная не установлена
    """
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"❌ Missing required env var: {name}. Check your .env file!")
    return val


# ============================================================
# TELEGRAM
# ============================================================

# Bot token - обязателен, fail fast если не установлен
TELEGRAM_BOT_TOKEN = require_env('TELEGRAM_BOT_TOKEN')

# Owner Telegram ID для дополнительной безопасности
# Если установлен (не 0), то только owner сможет использовать бота
OWNER_TELEGRAM_ID = int(os.getenv('OWNER_TELEGRAM_ID', '0'))


# ============================================================
# BYBIT API
# ============================================================

# Live API keys (опционально, нужны только для live режима)
BYBIT_API_KEY = os.getenv('BYBIT_API_KEY')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET')

# Testnet API keys (опционально, нужны только для testnet режима)
BYBIT_TESTNET_API_KEY = os.getenv('BYBIT_TESTNET_API_KEY')
BYBIT_TESTNET_API_SECRET = os.getenv('BYBIT_TESTNET_API_SECRET')


def get_bybit_keys(testnet: bool) -> tuple[str, str]:
    """
    Получить активные Bybit API ключи в зависимости от режима.
    Fail fast - бросит RuntimeError если ключи не установлены.

    Args:
        testnet: True для testnet, False для live

    Returns:
        (api_key, api_secret)

    Raises:
        RuntimeError: Если ключи не установлены в .env
    """
    if testnet:
        return (
            require_env('BYBIT_TESTNET_API_KEY'),
            require_env('BYBIT_TESTNET_API_SECRET')
        )
    return (
        require_env('BYBIT_API_KEY'),
        require_env('BYBIT_API_SECRET')
    )


# ============================================================
# SYNTRA AI API
# ============================================================

# Syntra AI API URL (аналитическая система)
SYNTRA_API_URL = os.getenv('SYNTRA_API_URL', 'http://localhost:8000')

# API Key для Syntra AI (опционально, если требуется аутентификация)
SYNTRA_API_KEY = os.getenv('SYNTRA_API_KEY')

# Таймаут для запросов к Syntra AI (секунды)
SYNTRA_API_TIMEOUT = int(os.getenv('SYNTRA_API_TIMEOUT', 30))

# Включить AI сценарии в боте
AI_SCENARIOS_ENABLED = os.getenv('AI_SCENARIOS_ENABLED', 'true').lower() == 'true'


# ============================================================
# REDIS
# ============================================================

# Redis
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')  # None if not set

# Bot Settings
DEFAULT_TESTNET_MODE = os.getenv('DEFAULT_TESTNET_MODE', 'true').lower() == 'true'

# Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
VALID_LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
if LOG_LEVEL not in VALID_LOG_LEVELS:
    LOG_LEVEL = 'INFO'

# ============================================================
# SUPPORTED SYMBOLS
# ============================================================

SUPPORTED_SYMBOLS = [
    'BTCUSDT',
    'ETHUSDT',
    'SOLUSDT',
    'BNBUSDT',
    'HYPEUSDT'
]

# Set для быстрой проверки: if symbol in SUPPORTED_SYMBOLS_SET
SUPPORTED_SYMBOLS_SET = set(SUPPORTED_SYMBOLS)

# Строка для отображения пользователю
SUPPORTED_SYMBOLS_DISPLAY = ", ".join(SUPPORTED_SYMBOLS)


# ============================================================
# TRADING CAPITAL SETTINGS
# ============================================================

# Trading Capital Mode: manual (fixed amount) или auto (from balance)
_capital_mode = os.getenv('TRADING_CAPITAL_MODE', 'manual').lower()
TRADING_CAPITAL_MODE = _capital_mode if _capital_mode in ('manual', 'auto') else 'manual'

# Fixed trading capital (для manual mode)
# Рекомендуется для безопасности - бот не будет использовать весь баланс
TRADING_CAPITAL_USD = float(os.getenv('TRADING_CAPITAL_USD', 500))


# ============================================================
# DEFAULT TRADING SETTINGS
# ============================================================

# Дефолтный риск на сделку (USD)
DEFAULT_RISK_USD = float(os.getenv('DEFAULT_RISK_USD', 10))

# Дефолтное плечо
DEFAULT_LEVERAGE = int(os.getenv('DEFAULT_LEVERAGE', 5))

# Дефолтный режим маржи (валидируется ниже после определения констант)
# DEFAULT_MARGIN_MODE будет установлен после MARGIN_MODE_ISOLATED/CROSS

# Дефолтный режим TP с валидацией
_VALID_TP_MODES = {'single', 'ladder', 'rr'}
_default_tp = os.getenv('DEFAULT_TP_MODE', 'rr')
DEFAULT_TP_MODE = _default_tp if _default_tp in _VALID_TP_MODES else 'rr'

DEFAULT_TP_RR = float(os.getenv('DEFAULT_TP_RR', 2.0))

# Шорты включены по умолчанию
DEFAULT_SHORTS_ENABLED = os.getenv('DEFAULT_SHORTS_ENABLED', 'false').lower() == 'true'


# ============================================================
# SAFETY LIMITS (критично для безопасности!)
# ============================================================

# Максимальный риск на одну сделку (USD)
# Для депозита $500 рекомендуется $10-20
MAX_RISK_PER_TRADE = float(os.getenv('MAX_RISK_PER_TRADE', 20))

# Максимальная маржа на одну сделку (USD)
# Для депозита $500 рекомендуется $100-150
MAX_MARGIN_PER_TRADE = float(os.getenv('MAX_MARGIN_PER_TRADE', 150))

# Максимальный notional (qty * price) на одну сделку (опционально)
MAX_NOTIONAL_PER_TRADE = float(os.getenv('MAX_NOTIONAL_PER_TRADE', 1500))

# Максимальное плечо
MAX_LEVERAGE = int(os.getenv('MAX_LEVERAGE', 10))


# ============================================================
# MARGIN MODE MAPPING (для Bybit API)
# ============================================================

MARGIN_MODE_ISOLATED = "Isolated"
MARGIN_MODE_CROSS = "Cross"

# Маппинг для Bybit API (tradeMode parameter)
MARGIN_MODE_TO_TRADEMODE = {
    "Cross": 0,
    "Isolated": 1,
}

# Валидация DEFAULT_MARGIN_MODE (определяем после констант)
_default_margin = os.getenv('DEFAULT_MARGIN_MODE', 'Isolated')
DEFAULT_MARGIN_MODE = _default_margin if _default_margin in (MARGIN_MODE_ISOLATED, MARGIN_MODE_CROSS) else MARGIN_MODE_ISOLATED


# ============================================================
# SECURITY SETTINGS
# ============================================================

# Подтверждение всегда включено по умолчанию (для безопасности)
CONFIRM_ALWAYS_DEFAULT = os.getenv('CONFIRM_ALWAYS_DEFAULT', 'true').lower() == 'true'


# ============================================================
# TRADE EXECUTION SETTINGS
# ============================================================

# Таймаут для Market ордера (увеличен с 10 до 20 для надёжности)
MARKET_ORDER_TIMEOUT = float(os.getenv('MARKET_ORDER_TIMEOUT', 20))

# Интервал polling для проверки fill status
MARKET_ORDER_POLL_INTERVAL = float(os.getenv('MARKET_ORDER_POLL_INTERVAL', 0.5))

# TTL для trade lock (защита от race condition)
TRADE_LOCK_TTL = int(os.getenv('TRADE_LOCK_TTL', 20))

# Bybit API Settings
BYBIT_CATEGORY = "linear"  # USDT perpetuals
BYBIT_POSITION_IDX = 0  # One-Way Mode


# ============================================================
# CONFIG VALIDATION
# ============================================================

def validate_config():
    """
    Валидация конфигурации при старте бота.
    Fail fast - бросает RuntimeError если что-то не так.

    Проверяет:
    - TELEGRAM_BOT_TOKEN установлен (уже проверено через require_env)
    - Все числовые лимиты > 0 и логичны
    - OWNER_TELEGRAM_ID валиден (если установлен)
    """

    errors = []

    # ===== Telegram =====
    # TELEGRAM_BOT_TOKEN уже проверен через require_env

    if OWNER_TELEGRAM_ID < 0:
        errors.append("OWNER_TELEGRAM_ID не может быть отрицательным")

    # ===== Trading Capital =====
    if TRADING_CAPITAL_USD <= 0:
        errors.append(f"TRADING_CAPITAL_USD должен быть > 0 (сейчас {TRADING_CAPITAL_USD})")

    # ===== Default Settings =====
    if DEFAULT_RISK_USD <= 0:
        errors.append(f"DEFAULT_RISK_USD должен быть > 0 (сейчас {DEFAULT_RISK_USD})")

    if DEFAULT_LEVERAGE < 1:
        errors.append(f"DEFAULT_LEVERAGE должен быть >= 1 (сейчас {DEFAULT_LEVERAGE})")

    if DEFAULT_TP_RR <= 0:
        errors.append(f"DEFAULT_TP_RR должен быть > 0 (сейчас {DEFAULT_TP_RR})")

    # ===== Safety Limits =====
    if MAX_RISK_PER_TRADE <= 0:
        errors.append(f"MAX_RISK_PER_TRADE должен быть > 0 (сейчас {MAX_RISK_PER_TRADE})")

    if MAX_MARGIN_PER_TRADE <= 0:
        errors.append(f"MAX_MARGIN_PER_TRADE должен быть > 0 (сейчас {MAX_MARGIN_PER_TRADE})")

    if MAX_NOTIONAL_PER_TRADE <= 0:
        errors.append(f"MAX_NOTIONAL_PER_TRADE должен быть > 0 (сейчас {MAX_NOTIONAL_PER_TRADE})")

    if MAX_LEVERAGE < 1:
        errors.append(f"MAX_LEVERAGE должен быть >= 1 (сейчас {MAX_LEVERAGE})")

    # ===== Логические проверки =====
    if DEFAULT_RISK_USD > MAX_RISK_PER_TRADE:
        errors.append(
            f"DEFAULT_RISK_USD ({DEFAULT_RISK_USD}) не может быть больше "
            f"MAX_RISK_PER_TRADE ({MAX_RISK_PER_TRADE})"
        )

    if DEFAULT_LEVERAGE > MAX_LEVERAGE:
        errors.append(
            f"DEFAULT_LEVERAGE ({DEFAULT_LEVERAGE}) не может быть больше "
            f"MAX_LEVERAGE ({MAX_LEVERAGE})"
        )

    if MAX_RISK_PER_TRADE > TRADING_CAPITAL_USD:
        errors.append(
            f"⚠️ WARNING: MAX_RISK_PER_TRADE ({MAX_RISK_PER_TRADE}) больше "
            f"TRADING_CAPITAL_USD ({TRADING_CAPITAL_USD}). Это может быть опасно!"
        )

    # ===== Execution Settings =====
    if MARKET_ORDER_TIMEOUT <= 0:
        errors.append(f"MARKET_ORDER_TIMEOUT должен быть > 0 (сейчас {MARKET_ORDER_TIMEOUT})")

    if MARKET_ORDER_POLL_INTERVAL <= 0:
        errors.append(f"MARKET_ORDER_POLL_INTERVAL должен быть > 0 (сейчас {MARKET_ORDER_POLL_INTERVAL})")

    if TRADE_LOCK_TTL <= 0:
        errors.append(f"TRADE_LOCK_TTL должен быть > 0 (сейчас {TRADE_LOCK_TTL})")

    # ===== Если есть ошибки, fail fast =====
    if errors:
        error_msg = "\n".join([f"  ❌ {err}" for err in errors])
        raise RuntimeError(
            f"\n{'='*60}\n"
            f"❌ CONFIG VALIDATION FAILED:\n"
            f"{'='*60}\n"
            f"{error_msg}\n"
            f"{'='*60}\n"
            f"Fix your .env file and restart the bot.\n"
        )

    # ===== Success =====
    print("✅ Config validation passed")
    print(f"   Mode: {'Testnet' if DEFAULT_TESTNET_MODE else 'Live'}")
    print(f"   Trading Capital: ${TRADING_CAPITAL_USD} ({TRADING_CAPITAL_MODE} mode)")
    print(f"   Default Risk: ${DEFAULT_RISK_USD} (max ${MAX_RISK_PER_TRADE})")
    print(f"   Default Leverage: {DEFAULT_LEVERAGE}x (max {MAX_LEVERAGE}x)")
    print(f"   Supported Symbols: {SUPPORTED_SYMBOLS_DISPLAY}")
    if OWNER_TELEGRAM_ID > 0:
        print(f"   🔒 Owner-only mode: ID {OWNER_TELEGRAM_ID}")
    print("")
