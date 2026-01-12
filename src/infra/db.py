from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from tiebameow.models.orm import RuleBase

from src.config import settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话的异步生成器。

    Yields:
        AsyncSession: SQLAlchemy 异步会话对象。
    """
    if _sessionmaker is None:
        raise RuntimeError("Database is not initialized. Call init_db first.")
    async with _sessionmaker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """初始化数据库。

    创建所有定义的表结构。
    """
    global _engine, _sessionmaker

    if _engine is None:
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(RuleBase.metadata.create_all)


async def dispose_db() -> None:
    """释放数据库连接。"""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _sessionmaker = None
