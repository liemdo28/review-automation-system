from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

# Async engine (for FastAPI routes + async workers)
async_engine = create_async_engine(settings.database_url, echo=False, pool_size=10)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

# Sync engine (for rq workers + Alembic)
sync_engine = create_engine(settings.database_url_sync, echo=False, pool_size=5)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
