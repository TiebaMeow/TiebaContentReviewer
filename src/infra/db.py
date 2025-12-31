from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.config import settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class Base(DeclarativeBase):
    pass


class RuleDBModel(Base):
    """审查规则的数据库模型。

    对应数据库中的 review_rules 表。

    Attributes:
        id: 主键 ID。
        name: 规则名称。
        enabled: 是否启用。
        priority: 优先级。
        trigger: 触发条件 JSON。
        actions: 动作列表 JSON。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    __tablename__ = "review_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trigger: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# Database Setup
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话的异步生成器。

    Yields:
        AsyncSession: SQLAlchemy 异步会话对象。
    """
    async with AsyncSessionLocal() as db:
        yield db


async def init_db() -> None:
    """初始化数据库。

    创建所有定义的表结构。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
