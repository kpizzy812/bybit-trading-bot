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

import config

# Global engine and session factory
_engine = None
AsyncSessionLocal: async_sessionmaker[AsyncSession] = None


def get_database_url() -> str:
    """Build PostgreSQL connection URL from config"""
    user = config.POSTGRES_USER
    password = config.POSTGRES_PASSWORD
    host = config.POSTGRES_HOST
    port = config.POSTGRES_PORT
    db = config.POSTGRES_DB

    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


async def init_db() -> None:
    """
    Initialize database connection and create tables.
    Call this at bot startup.
    """
    global _engine, AsyncSessionLocal

    if not config.POSTGRES_ENABLED:
        logger.info("PostgreSQL disabled, skipping database init")
        return

    try:
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
