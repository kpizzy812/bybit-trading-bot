import json
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
import redis.asyncio as aioredis
import config

logger = logging.getLogger(__name__)


@dataclass
class UserSettings:
    """Настройки пользователя"""
    user_id: int

    # Trading Capital Settings
    trading_capital_mode: str = config.TRADING_CAPITAL_MODE  # 'manual' or 'auto'
    trading_capital_usd: Optional[float] = config.TRADING_CAPITAL_USD  # для manual mode

    # Trading defaults
    default_risk_usd: float = config.DEFAULT_RISK_USD
    default_leverage: int = config.DEFAULT_LEVERAGE
    default_margin_mode: str = config.DEFAULT_MARGIN_MODE  # 'Isolated' or 'Cross'
    default_tp_mode: str = config.DEFAULT_TP_MODE  # 'single', 'ladder', 'rr'
    default_tp_rr: float = config.DEFAULT_TP_RR

    # Feature toggles
    shorts_enabled: bool = config.DEFAULT_SHORTS_ENABLED
    confirm_always: bool = config.CONFIRM_ALWAYS_DEFAULT

    # Safety limits
    max_risk_per_trade: float = config.MAX_RISK_PER_TRADE
    max_margin_per_trade: float = config.MAX_MARGIN_PER_TRADE
    max_notional_per_trade: float = config.MAX_NOTIONAL_PER_TRADE

    # Mode
    testnet_mode: bool = config.DEFAULT_TESTNET_MODE

    # === Risk Management ===
    # Auto breakeven после первого TP
    auto_breakeven_enabled: bool = config.AUTO_BREAKEVEN_ENABLED

    # Максимум активных позиций одновременно
    max_active_positions: int = config.MAX_ACTIVE_POSITIONS

    # Масштабирование риска от confidence AI
    confidence_risk_scaling: bool = config.CONFIDENCE_RISK_SCALING_ENABLED

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'UserSettings':
        return cls(**data)


class UserSettingsStorage:
    """
    Хранилище настроек пользователей
    Поддерживает Redis или in-memory fallback
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self.in_memory_storage: Dict[int, UserSettings] = {}
        self.use_redis = redis_url is not None

    async def connect(self):
        """Подключение к Redis"""
        if not self.use_redis:
            logger.info("Using in-memory storage for user settings")
            return

        try:
            self.redis = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis.ping()
            logger.info("Connected to Redis for user settings")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Falling back to in-memory storage")
            self.use_redis = False
            self.redis = None

    async def close(self):
        """Закрытие соединения"""
        if self.redis:
            await self.redis.close()

    def _settings_key(self, user_id: int) -> str:
        """Ключ для настроек пользователя"""
        return f"user:{user_id}:settings"

    async def get_settings(self, user_id: int) -> UserSettings:
        """
        Получить настройки пользователя
        Если не существуют, создаёт дефолтные
        """
        if self.use_redis and self.redis:
            try:
                key = self._settings_key(user_id)
                data = await self.redis.get(key)

                if data:
                    settings_dict = json.loads(data)
                    return UserSettings.from_dict(settings_dict)

            except Exception as e:
                logger.error(f"Error getting settings from Redis: {e}")

        # Fallback to in-memory
        if user_id not in self.in_memory_storage:
            self.in_memory_storage[user_id] = UserSettings(user_id=user_id)

        return self.in_memory_storage[user_id]

    async def save_settings(self, settings: UserSettings):
        """Сохранить настройки пользователя"""
        user_id = settings.user_id

        if self.use_redis and self.redis:
            try:
                key = self._settings_key(user_id)
                data = json.dumps(settings.to_dict())
                await self.redis.set(key, data)
                logger.debug(f"Settings saved to Redis for user {user_id}")
                return
            except Exception as e:
                logger.error(f"Error saving settings to Redis: {e}")

        # Fallback to in-memory
        self.in_memory_storage[user_id] = settings
        logger.debug(f"Settings saved to memory for user {user_id}")

    async def update_setting(self, user_id: int, key: str, value: Any):
        """Обновить одну настройку"""
        settings = await self.get_settings(user_id)
        if hasattr(settings, key):
            setattr(settings, key, value)
            await self.save_settings(settings)
        else:
            raise ValueError(f"Unknown setting: {key}")


class TradeLockManager:
    """
    Менеджер блокировок для предотвращения race conditions
    Использует Redis для распределённых блокировок
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self.in_memory_locks: Dict[int, float] = {}
        self.use_redis = redis_url is not None

    async def connect(self):
        """Подключение к Redis"""
        if not self.use_redis:
            logger.info("Using in-memory trade locks")
            return

        try:
            self.redis = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis.ping()
            logger.info("Connected to Redis for trade locks")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Falling back to in-memory locks")
            self.use_redis = False
            self.redis = None

    async def close(self):
        """Закрытие соединения"""
        if self.redis:
            await self.redis.close()

    def _lock_key(self, user_id: int) -> str:
        """Ключ блокировки для пользователя"""
        return f"lock:user:{user_id}:trade"

    async def acquire_lock(self, user_id: int, ttl: int = config.TRADE_LOCK_TTL) -> bool:
        """
        Попытка взять блокировку

        Args:
            user_id: ID пользователя
            ttl: Время жизни блокировки в секундах

        Returns:
            True если блокировка получена, False если уже занята
        """
        import time

        if self.use_redis and self.redis:
            try:
                key = self._lock_key(user_id)
                # SET с NX (not exists) и EX (expiry)
                acquired = await self.redis.set(key, "1", ex=ttl, nx=True)
                result = bool(acquired)

                if result:
                    logger.debug(f"Trade lock acquired for user {user_id}")
                else:
                    logger.debug(f"Trade lock already held for user {user_id}")

                return result

            except Exception as e:
                logger.error(f"Error acquiring lock: {e}")
                return False

        # Fallback to in-memory
        current_time = time.time()

        # Проверяем существующую блокировку
        if user_id in self.in_memory_locks:
            lock_time = self.in_memory_locks[user_id]
            if current_time - lock_time < ttl:
                # Блокировка ещё действует
                logger.debug(f"Trade lock already held for user {user_id} (in-memory)")
                return False
            else:
                # Блокировка истекла
                del self.in_memory_locks[user_id]

        # Устанавливаем новую блокировку
        self.in_memory_locks[user_id] = current_time
        logger.debug(f"Trade lock acquired for user {user_id} (in-memory)")
        return True

    async def release_lock(self, user_id: int):
        """Освободить блокировку"""
        if self.use_redis and self.redis:
            try:
                key = self._lock_key(user_id)
                await self.redis.delete(key)
                logger.debug(f"Trade lock released for user {user_id}")
                return
            except Exception as e:
                logger.error(f"Error releasing lock: {e}")

        # Fallback to in-memory
        if user_id in self.in_memory_locks:
            del self.in_memory_locks[user_id]
            logger.debug(f"Trade lock released for user {user_id} (in-memory)")


# Глобальные экземпляры
def create_storage_instances():
    """Создать экземпляры хранилищ"""

    # Redis URL
    redis_url = None
    if config.REDIS_HOST:
        redis_password_part = f":{config.REDIS_PASSWORD}@" if config.REDIS_PASSWORD else ""
        redis_url = f"redis://{redis_password_part}{config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}"

    settings_storage = UserSettingsStorage(redis_url)
    lock_manager = TradeLockManager(redis_url)

    return settings_storage, lock_manager
