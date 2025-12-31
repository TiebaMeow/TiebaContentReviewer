from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from redis.exceptions import ResponseError
from tiebameow.serializer import deserialize
from tiebameow.utils.logger import logger

from src.config import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.core.engine import RuleMatcher
    from src.infra.dispatcher import ReviewResultDispatcher
    from src.infra.repository import RuleRepository


class ReviewWorker:
    """Worker类。

    负责从 Redis Stream 消费数据，调用规则引擎进行匹配，并分发匹配结果。
    支持批量消费和消息恢复机制。
    """

    def __init__(
        self,
        repository: RuleRepository,
        dispatcher: ReviewResultDispatcher,
        matcher: RuleMatcher,
        redis_client: Redis,
    ) -> None:
        self._repo = repository
        self._dispatcher = dispatcher
        self._matcher = matcher
        self._redis = redis_client
        self._running = False
        self._recovery_task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        """启动Worker。

        初始化消费者组，启动恢复任务，并进入主消费循环。
        """
        self._running = True
        await self._ensure_consumer_group()

        if settings.ENABLE_STREAM_RECOVERY:
            self._recovery_task = asyncio.create_task(self._recovery_loop())
            logger.info("Stream recovery task started.")

        logger.info("Worker started. Listening on {}", settings.REDIS_STREAM_KEY)

        while self._running:
            try:
                # XREADGROUP
                # count=BATCH_SIZE, block=2000ms
                streams = {settings.REDIS_STREAM_KEY: ">"}
                messages = await self._redis.xreadgroup(
                    settings.REDIS_CONSUMER_GROUP,
                    settings.REDIS_CONSUMER_NAME,
                    streams,  # type: ignore
                    count=settings.BATCH_SIZE,
                    block=2000,
                )

                if not messages:
                    continue

                for _stream_name, entries in messages:
                    for message_id, fields in entries:
                        await self._process_message(message_id, fields)

            except Exception as e:
                logger.error("Error in worker loop: {}", e)
                await asyncio.sleep(1)

    def stop(self) -> None:
        """停止Worker。

        设置停止标志并取消后台任务。
        """
        self._running = False
        if self._recovery_task:
            self._recovery_task.cancel()

    async def _ensure_consumer_group(self) -> None:
        """确保消费者组存在。

        如果不存在则创建，如果已存在则忽略。
        """
        try:
            await self._redis.xgroup_create(
                settings.REDIS_STREAM_KEY,
                settings.REDIS_CONSUMER_GROUP,
                id="0",
                mkstream=True,
            )
            logger.info("Created consumer group: {}", settings.REDIS_CONSUMER_GROUP)
        except ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.info("Consumer group already exists.")
            else:
                raise e

    async def _process_message(self, message_id: str, fields: dict[str, Any]) -> None:
        """处理单条消息。

        反序列化数据，匹配规则，分发匹配结果，并确认消息。

        Args:
            message_id: 消息 ID。
            fields: 消息字段字典。
        """
        try:
            raw_data = fields.get("data")
            if not raw_data:
                logger.warning("Message {} missing data field.", message_id)
                await self._ack(message_id)
                return

            data = json.loads(raw_data)
            object_type = data.get("object_type")
            payload = data.get("payload")

            if not object_type or not payload:
                logger.warning("Invalid message format: {}", message_id)
                await self._ack(message_id)
                return

            assert isinstance(payload, dict)
            assert object_type in ("thread", "post", "comment")

            # 反序列化
            try:
                obj = deserialize(object_type, payload)
            except Exception as e:
                logger.error("Deserialization failed for {}: {}", message_id, e)
                await self._ack(message_id)
                return

            # 转换为字典供规则引擎使用
            # 假设 obj 是 Pydantic model
            if hasattr(obj, "model_dump"):
                obj_dict = obj.model_dump()
            else:
                obj_dict = payload  # Fallback

            # 获取当前规则
            rules = self._repo.get_active_rules()

            matched_rules = []
            try:
                for rule in rules:
                    if self._matcher.match(obj_dict, rule):
                        logger.info("Rule matched: {} (ID: {})", rule.name, rule.id)
                        matched_rules.append(rule)
            except Exception as e:
                logger.error("Error matching rules for message {}: {}", message_id, e)
                await self._ack(message_id)
                return

            # 分发结果
            if matched_rules:
                await self._dispatcher.dispatch(matched_rules, object_type, obj_dict)

            # ACK
            await self._ack(message_id)

        except Exception as e:
            logger.error("Failed to process message {}: {}", message_id, e)
            # 未启用 XAUTOCLAIM 机制时，死信最终将被 ACK
            if not settings.ENABLE_STREAM_RECOVERY:
                await self._ack(message_id)

    async def _ack(self, message_id: str) -> None:
        """确认消息已处理。

        Args:
            message_id: 消息 ID。
        """
        await self._redis.xack(settings.REDIS_STREAM_KEY, settings.REDIS_CONSUMER_GROUP, message_id)

    async def _recovery_loop(self) -> None:
        """消息恢复循环。

        定期扫描并认领长时间未处理的消息 (PEL)，防止消息丢失。
        """
        while self._running:
            try:
                await asyncio.sleep(settings.STREAM_RECOVERY_INTERVAL)

                # XAUTOCLAIM
                # 尝试认领闲置超过 STREAM_MIN_IDLE_TIME 的消息
                # start_id="0-0", count=BATCH_SIZE
                messages = await self._redis.xautoclaim(
                    settings.REDIS_STREAM_KEY,
                    settings.REDIS_CONSUMER_GROUP,
                    settings.REDIS_CONSUMER_NAME,
                    min_idle_time=settings.STREAM_MIN_IDLE_TIME,
                    start_id="0-0",
                    count=settings.BATCH_SIZE,
                )

                # messages 结构: (next_start_id, entries, [deleted_ids])
                # entries 是列表 [(message_id, fields), ...]
                if messages and len(messages) > 1:
                    entries = messages[1]
                    if entries:
                        logger.info("Recovered {} messages.", len(entries))
                        for message_id, fields in entries:
                            await self._process_message(message_id, fields)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in recovery loop: {}", e)
                await asyncio.sleep(60)
