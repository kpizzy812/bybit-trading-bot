import asyncio
import sys
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

import config
from bot.handlers import start
from bot.middlewares.owner_check import OwnerCheckMiddleware
from storage.user_settings import create_storage_instances


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

    # Сохраняем в workflow_data для доступа из хэндлеров
    dp.workflow_data.update({
        'settings_storage': settings_storage,
        'lock_manager': lock_manager
    })

    # Регистрация middleware
    if config.OWNER_TELEGRAM_ID > 0:
        logger.info(f"🔒 Owner-only mode enabled for user ID: {config.OWNER_TELEGRAM_ID}")
        dp.update.middleware(OwnerCheckMiddleware())

    # Регистрация роутеров
    logger.info("Registering handlers...")
    dp.include_router(start.router)

    # Запуск бота
    logger.info("Starting bot...")
    logger.info(f"Default mode: {'Testnet' if config.DEFAULT_TESTNET_MODE else 'Live'}")
    logger.info(f"Supported symbols: {', '.join(config.SUPPORTED_SYMBOLS)}")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        # Закрытие соединений
        logger.info("Shutting down...")
        await settings_storage.close()
        await lock_manager.close()
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
