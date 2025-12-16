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
from bot.handlers import trade_wizard, ai_scenarios, scenario_editor
from bot.handlers import supervisor as supervisor_handler
from bot.middlewares.owner_check import OwnerCheckMiddleware
from storage.user_settings import create_storage_instances
from services.trade_logger import create_trade_logger
from services.position_monitor import create_position_monitor
from services.order_monitor import create_order_monitor
from services.entry_plan_monitor import create_entry_plan_monitor
from services.breakeven_manager import create_breakeven_manager
from services.post_sl_analyzer import create_post_sl_analyzer
from services.supervisor_client import get_supervisor_client


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
logger.add(
    "errors.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="ERROR",
    rotation="5 MB",
    retention="30 days",
    compression="zip",
    backtrace=True,
    diagnose=True
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

    # Инициализация breakeven manager
    logger.info("Initializing breakeven manager...")
    breakeven_manager = create_breakeven_manager(
        bot=bot,
        trade_logger=trade_logger,
        testnet=config.DEFAULT_TESTNET_MODE
    )
    if config.AUTO_BREAKEVEN_ENABLED:
        logger.info("🛡️ Auto Breakeven enabled")

    # Инициализация post-SL analyzer
    logger.info("Initializing post-SL analyzer...")
    post_sl_analyzer = create_post_sl_analyzer(
        bot=bot,
        trade_logger=trade_logger,
        testnet=config.DEFAULT_TESTNET_MODE
    )
    await post_sl_analyzer.connect()
    logger.info("📊 Post-SL Analysis enabled")

    # Инициализация supervisor client
    supervisor_client = None
    if config.SUPERVISOR_ENABLED:
        logger.info("Initializing supervisor client...")
        supervisor_client = get_supervisor_client()
        # Health check
        if await supervisor_client.health_check():
            logger.info("🧠 Supervisor API connected")
        else:
            logger.warning("⚠️ Supervisor API not available")

    # Инициализация position monitor
    logger.info("Initializing position monitor...")
    position_monitor = create_position_monitor(
        bot=bot,
        trade_logger=trade_logger,
        testnet=config.DEFAULT_TESTNET_MODE,
        check_interval=config.POSITION_MONITOR_INTERVAL,
        breakeven_manager=breakeven_manager,
        post_sl_analyzer=post_sl_analyzer,
        supervisor_client=supervisor_client
    )

    # Автоматически регистрируем owner для мониторинга
    if config.OWNER_TELEGRAM_ID > 0:
        position_monitor.register_user(config.OWNER_TELEGRAM_ID)
        logger.info(f"Owner {config.OWNER_TELEGRAM_ID} registered for position monitoring")

    # Запускаем мониторинг
    await position_monitor.start()

    # Инициализация order monitor
    logger.info("Initializing order monitor...")
    order_monitor = create_order_monitor(
        bot=bot,
        trade_logger=trade_logger,
        testnet=config.DEFAULT_TESTNET_MODE,
        check_interval=10  # Проверяем ордера каждые 10 секунд
    )

    # Запускаем order monitor
    await order_monitor.start()

    # Инициализация entry plan monitor (для ladder entry)
    logger.info("Initializing entry plan monitor...")
    entry_plan_monitor = create_entry_plan_monitor(
        bot=bot,
        trade_logger=trade_logger,
        testnet=config.DEFAULT_TESTNET_MODE,
        check_interval=10
    )

    # Запускаем entry plan monitor
    await entry_plan_monitor.start()
    logger.info("📋 Entry Plan Monitor enabled")

    # Сохраняем в workflow_data для доступа из хэндлеров
    dp.workflow_data.update({
        'settings_storage': settings_storage,
        'lock_manager': lock_manager,
        'trade_logger': trade_logger,
        'position_monitor': position_monitor,
        'order_monitor': order_monitor,
        'entry_plan_monitor': entry_plan_monitor,
        'breakeven_manager': breakeven_manager,
        'post_sl_analyzer': post_sl_analyzer,
        'supervisor_client': supervisor_client
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
        dp.include_router(scenario_editor.router)
        logger.info("🤖 AI Scenarios enabled")

    dp.include_router(trade_wizard.router)

    # Supervisor handlers (если включено)
    if config.SUPERVISOR_ENABLED:
        dp.include_router(supervisor_handler.router)
        logger.info("🧠 Supervisor handlers registered")

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
        await order_monitor.stop()
        await entry_plan_monitor.stop()
        await post_sl_analyzer.close()
        await settings_storage.close()
        await lock_manager.close()
        await trade_logger.close()
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
