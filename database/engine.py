"""
Database Engine - async PostgreSQL connection
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker
)
from sqlalchemy.pool import NullPool
from loguru import logger
import asyncpg

import config

# Global engine and session factory
_engine = None
AsyncSessionLocal: async_sessionmaker[AsyncSession] = None


def get_database_url(db_name: str = None) -> str:
    """Build PostgreSQL connection URL from config"""
    user = config.POSTGRES_USER
    password = config.POSTGRES_PASSWORD
    host = config.POSTGRES_HOST
    port = config.POSTGRES_PORT
    db = db_name or config.POSTGRES_DB

    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


async def _ensure_database_exists() -> None:
    """
    Check if database exists and create it if not.
    Connects to 'postgres' system database to perform this operation.
    """
    try:
        # Подключаемся к системной БД postgres
        conn = await asyncpg.connect(
            host=config.POSTGRES_HOST,
            port=config.POSTGRES_PORT,
            user=config.POSTGRES_USER,
            password=config.POSTGRES_PASSWORD,
            database='postgres'
        )

        try:
            # Проверяем существует ли наша БД
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1",
                config.POSTGRES_DB
            )

            if not exists:
                # Создаём БД (нельзя внутри транзакции)
                # asyncpg по умолчанию в autocommit для DDL
                await conn.execute(
                    f'CREATE DATABASE "{config.POSTGRES_DB}" '
                    f'OWNER "{config.POSTGRES_USER}" '
                    f'ENCODING "UTF8"'
                )
                logger.info(f"✅ Database '{config.POSTGRES_DB}' created")
            else:
                logger.debug(f"Database '{config.POSTGRES_DB}' already exists")

        finally:
            await conn.close()

    except asyncpg.InvalidCatalogNameError:
        # БД postgres не существует - попробуем template1
        logger.warning("'postgres' database not found, trying 'template1'")
        conn = await asyncpg.connect(
            host=config.POSTGRES_HOST,
            port=config.POSTGRES_PORT,
            user=config.POSTGRES_USER,
            password=config.POSTGRES_PASSWORD,
            database='template1'
        )
        try:
            await conn.execute(
                f'CREATE DATABASE "{config.POSTGRES_DB}" '
                f'OWNER "{config.POSTGRES_USER}" '
                f'ENCODING "UTF8"'
            )
            logger.info(f"✅ Database '{config.POSTGRES_DB}' created")
        finally:
            await conn.close()


async def init_db() -> None:
    """
    Initialize database connection and create tables.
    Call this at bot startup.

    Automatically creates database if it doesn't exist.
    """
    global _engine, AsyncSessionLocal

    if not config.POSTGRES_ENABLED:
        logger.info("PostgreSQL disabled, skipping database init")
        return

    try:
        # Сначала убедимся что БД существует
        await _ensure_database_exists()

        database_url = get_database_url()

        _engine = create_async_engine(
            database_url,
            echo=config.POSTGRES_ECHO,
            poolclass=NullPool,  # Для asyncio лучше без пула
        )

        AsyncSessionLocal = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        # Create tables
        from database.models import Base
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info(f"PostgreSQL connected: {config.POSTGRES_HOST}:{config.POSTGRES_PORT}/{config.POSTGRES_DB}")

    except Exception as e:
        logger.error(f"Failed to initialize PostgreSQL: {e}")
        raise


async def close_db() -> None:
    """
    Close database connection.
    Call this at bot shutdown.
    """
    global _engine, AsyncSessionLocal

    if _engine:
        await _engine.dispose()
        _engine = None
        AsyncSessionLocal = None
        logger.info("PostgreSQL connection closed")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get async session for database operations.
    Usage:
        async with get_session() as session:
            result = await session.execute(...)
    """
    if AsyncSessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
