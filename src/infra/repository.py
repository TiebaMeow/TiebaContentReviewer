from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

import orjson
from sqlalchemy import func, select
from tiebameow.models.orm import ReviewRules
from tiebameow.schemas.rules import TargetType
from tiebameow.utils.logger import logger
from tiebameow.utils.time_utils import now_with_tz

from src.config import settings
from src.infra.db import get_session

if TYPE_CHECKING:
    from datetime import datetime

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession
    from tiebameow.schemas.rules import ReviewRule


class RuleRepository:
    """规则仓库。

    负责管理审查规则的持久化存储和内存缓存。从数据库加载规则，
    并通过 Redis Pub/Sub 和定期轮询保持与数据库同步。
    """

    def __init__(self, redis_client: Redis) -> None:
        """初始化规则仓库。

        Args:
            redis_client: Redis 客户端实例，用于订阅规则变更通知。
        """
        self._rules: list[ReviewRule] = []
        self._rule_index: dict[tuple[int, TargetType], list[ReviewRule]] = {}
        self._redis = redis_client
        self._sync_task: asyncio.Task[None] | None = None
        self._periodic_sync_task: asyncio.Task[None] | None = None
        self._last_synced_at: datetime | None = None

    async def load_initial_rules(self) -> None:
        """从数据库全量加载规则到内存。

        在服务启动时调用，确保内存中有初始规则数据。
        """
        logger.info("Loading rules from PostgreSQL...")
        async with get_session() as session:
            await self._refresh_all_rules(session)
        logger.info("Loaded {} rules.", len(self._rules))

    def start_sync(self) -> None:
        """启动后台同步任务。

        启动 Redis 订阅监听任务和定期数据库轮询任务，以保持规则与数据库同步。
        """
        if self._sync_task and not self._sync_task.done():
            return

        self._sync_task = asyncio.create_task(self._redis_listener())
        self._periodic_sync_task = asyncio.create_task(self._periodic_sync_loop())
        logger.info("Rule sync listener started.")

    async def stop_sync(self) -> None:
        """停止后台同步任务。

        取消 Redis 监听和定期轮询任务，并等待它们优雅退出。
        """
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass

        if self._periodic_sync_task:
            self._periodic_sync_task.cancel()
            try:
                await self._periodic_sync_task
            except asyncio.CancelledError:
                pass

    def get_active_rules(self) -> list[ReviewRule]:
        """获取当前内存中的所有有效规则。

        Returns:
            list[ReviewRule]: 当前生效的审查规则列表副本。
        """
        return list(self._rules)

    def get_match_rules(self, fid: int, target_type: Literal["thread", "post", "comment"]) -> list[ReviewRule]:
        """获取指定 fid 和目标类型的有效规则。

        Args:
            fid: 贴吧 ID。
            target_type: 目标类型 ('thread', 'post', 'comment')。

        Returns:
            list[ReviewRule]: 规则列表。
        """

        global_rules = self._rule_index.get((fid, TargetType.ALL), [])
        specific_rules = self._rule_index.get((fid, TargetType(target_type)), [])

        rules = specific_rules + global_rules
        rules.sort(key=lambda x: x.priority)

        return rules

    async def _redis_listener(self) -> None:
        """Redis 订阅监听器的后台任务。

        监听规则变更频道，接收到消息后触发规则更新。
        """
        while True:
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(settings.REDIS_RULES_CHANNEL)

            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        await self._handle_update(message["data"])
            except asyncio.CancelledError:
                await pubsub.unsubscribe()
                raise
            except Exception as e:
                logger.error("Error in Redis listener: {}", e)
                # 重试逻辑可以在这里添加，或者让 Task 结束由外部重启
                # 简单起见，这里只是记录日志
                await asyncio.sleep(5)
            finally:
                await pubsub.close()

    async def _periodic_sync_loop(self) -> None:
        """定期轮询数据库的后台任务。

        作为 Redis 通知的兜底机制，定期检查数据库是否有更新，确保规则最终一致性。
        """
        while True:
            try:
                await asyncio.sleep(settings.RULE_SYNC_INTERVAL)
                async with get_session() as session:
                    # 检查最大 updated_at
                    result = await session.execute(select(func.max(ReviewRules.updated_at)))
                    max_updated_at = result.scalar()

                    if max_updated_at and (self._last_synced_at is None or max_updated_at > self._last_synced_at):
                        logger.info(
                            "Detected rule updates (last: {}, new: {}). Refreshing...",
                            self._last_synced_at,
                            max_updated_at,
                        )
                        await self._refresh_all_rules(session)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Error in periodic sync loop: {}", e)
                await asyncio.sleep(60)  # 出错后等待一分钟再试

    async def _handle_update(self, raw_data: str | bytes) -> None:
        """处理接收到的规则更新事件。

        Args:
            raw_data: Redis 消息中的原始数据（JSON 字符串或字节）。
        """
        try:
            event = orjson.loads(raw_data)
            rule_id = event.get("rule_id")
            event_type = event.get("type")

            logger.info("Received rule update event: {} for rule {}", event_type, rule_id)

            if event_type == "DELETE":
                self._rules = [r for r in self._rules if r.id != rule_id]
            elif event_type in ("UPDATE", "ADD"):
                async with get_session() as session:
                    await self._refresh_single_rule(session, rule_id)

        except Exception as e:
            logger.error("Error handling rule update: {}", e)

    async def _refresh_all_rules(self, session: AsyncSession) -> None:
        """从数据库重新加载所有启用的规则并更新内存缓存。

        Args:
            session: 数据库会话。
        """

        # 更新最后同步时间
        # 注意：这里取的是当前时间，也可以取 max_updated_at，但为了简单起见取当前时间
        # 如果使用 max_updated_at，需要确保所有节点时间同步
        self._last_synced_at = now_with_tz()
        result = await session.execute(
            select(ReviewRules).where(ReviewRules.enabled == True)  # noqa: E712
        )
        db_rules = result.scalars().all()

        new_rules = []
        for r in db_rules:
            try:
                rule = r.to_rule_data()
                new_rules.append(rule)
            except Exception as e:
                logger.error("Failed to parse rule {}: {}", r.id, e)

        self._rules = new_rules
        self._rebuild_index()

    async def _refresh_single_rule(self, session: AsyncSession, rule_id: int) -> None:
        """刷新单个规则的缓存。

        如果规则被禁用或删除，则从内存中移除。

        Args:
            session: 数据库会话。
            rule_id: 规则 ID。
        """
        # 先移除旧的
        self._rules = [r for r in self._rules if r.id != rule_id]

        # 查询新的
        result = await session.execute(select(ReviewRules).where(ReviewRules.id == rule_id))
        r = result.scalar_one_or_none()

        if r and r.enabled:
            try:
                rule = r.to_rule_data()
                self._rules.append(rule)
            except Exception as e:
                logger.error("Failed to parse rule {}: {}", r.id, e)

        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """重建索引。"""
        index: dict[tuple[int, TargetType], list[ReviewRule]] = {}
        for rule in self._rules:
            key = (rule.fid, rule.target_type)
            if key not in index:
                index[key] = []
            index[key].append(rule)
        self._rule_index = index
        for key in self._rule_index:
            self._rule_index[key].sort(key=lambda x: x.priority)
