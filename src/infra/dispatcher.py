from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from tiebameow.utils.logger import logger

from src.config import settings
from src.core.rules import Action  # noqa: TC001

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.core.rules import ReviewRule


class MatchedRule(BaseModel):
    """命中的规则信息。"""

    id: int
    name: str
    priority: int
    actions: list[Action]


class ReviewResultPayload(BaseModel):
    """审查结果载荷。"""

    matched_rules: list[MatchedRule]
    object_type: str
    target_data: dict[str, Any]
    timestamp: float = Field(default_factory=time.time)


class ReviewResultDispatcher:
    """审查结果分发器。

    负责将规则匹配结果（包含触发的规则和动作）分发到 Redis Stream 中，供下游服务执行。
    """

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def dispatch(
        self,
        rules: list[ReviewRule],
        object_type: str,
        target_data: dict[str, Any],
    ) -> None:
        """分发审查结果到 Redis Stream。

        将匹配的规则和目标数据封装成 payload，推送到配置的 Redis Stream 中。

        Args:
            rules: 匹配的规则列表。
            object_type: 数据对象类型 (thread, post, comment)。
            target_data: 触发动作的原始数据。
        """
        if not rules:
            return

        try:
            matched_rules = [
                MatchedRule(
                    id=rule.id,
                    name=rule.name,
                    priority=rule.priority,
                    actions=rule.actions,
                )
                for rule in rules
            ]

            payload = ReviewResultPayload(
                matched_rules=matched_rules,
                object_type=object_type,
                target_data=target_data,
            )

            stream_entry = {"data": payload.model_dump_json()}

            await self._redis.xadd(settings.REDIS_ACTION_STREAM_KEY, stream_entry)  # type: ignore[arg-type]
            logger.info("Dispatched result with {} matched rules to stream.", len(matched_rules))
        except Exception as e:
            logger.error("Failed to dispatch result: {}", e)
