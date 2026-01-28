from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from tiebameow.utils.logger import logger

from src.config import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from tiebameow.schemas.rules import ReviewRule


class ReviewResultPayload(BaseModel):
    fid: int
    matched_rule_ids: list[int]
    object_type: str
    object_data: dict[str, Any]
    function_call_results: dict[str, Any] = Field(default_factory=dict)
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
        fid: int,
        object_type: str,
        object_data: dict[str, Any],
        function_call_results: dict[str, Any] | None = None,
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
            matched_rule_ids = [rule.id for rule in rules]

            payload = ReviewResultPayload(
                fid=fid,
                matched_rule_ids=matched_rule_ids,
                object_type=object_type,
                object_data=object_data,
                function_call_results=function_call_results or {},
            )

            stream_entry = {"data": payload.model_dump_json()}

            await self._redis.xadd(settings.REDIS_ACTION_STREAM_KEY, stream_entry)  # type: ignore[arg-type]
            logger.info("Dispatched result with {} matched rules to stream.", len(matched_rule_ids))
        except Exception as e:
            logger.error("Failed to dispatch result: {}", e)
