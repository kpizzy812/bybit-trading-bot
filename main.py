import asyncio
import sys
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

import config
from bot.handlers import start, menu, positions, settings, history
from bot.handlers import trade_wizard, ai_scenarios
from bot.middlewares.owner_check import OwnerCheckMiddleware
from storage.user_settings import create_storage_instances
from services.trade_logger import create_trade_logger
from services.position_monitor import create_position_monitor


class InterceptHandler(logging.Handler):
    """Перехватчик для интеграции стандартного logging с loguru"""
    def emit(self, record):
        # Получаем соответствующий уровень loguru
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Находим caller frame
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


# Настройка логирования с loguru
logger.remove()  # Удаляем стандартный хендлер
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    level=config.LOG_LEVEL
)
logger.add(
    "bot.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
    level=config.LOG_LEVEL,
    rotation="10 MB",
    retention="7 days",
    compression="zip"
)

# Перехватываем логи из aiogram и других библиотек
logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


async def main():
    """Главная функция запуска бота"""

    # ===== КРИТИЧНО: Валидация конфигурации перед запуском =====
    try:
        config.validate_config()
    except RuntimeError as e:
        logger.error(str(e))
        return

    # Инициализация бота
    bot = Bot(
        token=config.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Инициализация диспетчера с FSM storage
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Инициализация хранилищ
    logger.info("Initializing storage...")
    settings_storage, lock_manager = create_storage_instances()

    # Подключение к Redis (если доступен)
    await settings_storage.connect()
    await lock_manager.connect()

    # Инициализация trade logger
    logger.info("Initializing trade logger...")
    trade_logger = create_trade_logger()
    await trade_logger.connect()

    # Инициализация position monitor
    logger.info("Initializing position monitor...")
    position_monitor = create_position_monitor(
        bot=bot,
        trade_logger=trade_logger,
        testnet=config.DEFAULT_TESTNET_MODE,
        check_interval=config.POSITION_MONITOR_INTERVAL
    )

    # Автоматически регистрируем owner для мониторинга
    if config.OWNER_TELEGRAM_ID > 0:
        position_monitor.register_user(config.OWNER_TELEGRAM_ID)
        logger.info(f"Owner {config.OWNER_TELEGRAM_ID} registered for position monitoring")

    # Запускаем мониторинг
    await position_monitor.start()

    # Сохраняем в workflow_data для доступа из хэндлеров
    dp.workflow_data.update({
        'settings_storage': settings_storage,
        'lock_manager': lock_manager,
        'trade_logger': trade_logger,
        'position_monitor': position_monitor
    })

    # Регистрация middleware
    if config.OWNER_TELEGRAM_ID > 0:
        logger.info(f"🔒 Owner-only mode enabled for user ID: {config.OWNER_TELEGRAM_ID}")
        dp.update.middleware(OwnerCheckMiddleware())

    # Регистрация роутеров
    logger.info("Registering handlers...")
    dp.include_router(start.router)
    dp.include_router(menu.router)
    dp.include_router(positions.router)
    dp.include_router(settings.router)
    dp.include_router(history.router)

    # AI Scenarios (если включено)
    if config.AI_SCENARIOS_ENABLED:
        dp.include_router(ai_scenarios.router)
        logger.info("🤖 AI Scenarios enabled")

    dp.include_router(trade_wizard.router)

    # Запуск бота
    logger.info("Starting bot...")
    logger.info(f"Default mode: {'Testnet' if config.DEFAULT_TESTNET_MODE else 'Live'}")
    logger.info(f"Supported symbols: {', '.join(config.SUPPORTED_SYMBOLS)}")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        # Закрытие соединений
        logger.info("Shutting down...")
        await position_monitor.stop()
        await settings_storage.close()
        await lock_manager.close()
        await trade_logger.close()
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
