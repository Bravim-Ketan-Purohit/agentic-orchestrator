"""SQLAlchemy async engine and session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from orchestrator.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=60,
    max_overflow=40,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async session."""
    async with async_session_factory() as session:
        yield session
