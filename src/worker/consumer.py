from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import orjson
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
        fid: int,
        stream_key: str,
    ) -> None:
        self._repo = repository
        self._dispatcher = dispatcher
        self._matcher = matcher
        self._redis = redis_client
        self._stream_key = stream_key
        self._fid = fid
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
            logger.info("Stream recovery task started for {}.", self._stream_key)

        logger.info("Worker started. Listening on {}", self._stream_key)

        active_tasks: set[asyncio.Task[None]] = set()

        while self._running:
            try:
                # 清理已完成的任务
                done_tasks = {t for t in active_tasks if t.done()}
                for task in done_tasks:
                    try:
                        task.result()
                    except Exception as e:
                        logger.error("Task failed: {}", e)
                    active_tasks.discard(task)

                # 计算可用配额
                quota = settings.WORKER_CONCURRENCY - len(active_tasks)

                if quota <= 0:
                    await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED)
                    continue

                # XREADGROUP
                # count=quota, block=1000ms
                streams = {self._stream_key: ">"}
                messages = await self._redis.xreadgroup(
                    settings.REDIS_CONSUMER_GROUP,
                    settings.REDIS_CONSUMER_NAME,
                    streams,  # type: ignore
                    count=quota,
                    block=1000,
                )

                if not messages:
                    continue

                for _stream_name, entries in messages:
                    for message_id, fields in entries:
                        task = asyncio.create_task(self._process_message(message_id, fields))
                        active_tasks.add(task)

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
                self._stream_key,
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

            data = orjson.loads(raw_data)
            object_type = data.get("object_type")
            object_id = data.get("object_id")
            payload = data.get("payload")

            if not object_type or not payload:
                logger.warning("Invalid message format: {}", object_id)
                await self._ack(message_id)
                return

            if not isinstance(payload, dict) or object_type not in ("thread", "post", "comment"):
                logger.warning("Invalid message format: {}", object_id)
                await self._ack(message_id)
                return

            # 反序列化
            try:
                obj = deserialize(object_type, payload)
            except Exception as e:
                logger.error("Deserialization failed for {}: {}", object_id, e)
                await self._ack(message_id)
                return

            # 获取当前规则 (按 FID 和 ObjectType 过滤)
            rules = self._repo.get_match_rules(self._fid, object_type)

            try:
                matched_rules, context = await self._matcher.match_all(obj, rules)
                if matched_rules:
                    for rule in matched_rules:
                        logger.info("Rule matched: {} (ID: {})", rule.name, rule.id)
            except Exception as e:
                logger.error("Error matching rules for message {}: {}", message_id, e)
                await self._ack(message_id)
                return

            # 分发结果
            obj_dict = obj.model_dump()
            if matched_rules:
                await self._dispatcher.dispatch(matched_rules, self._fid, object_type, obj_dict, context)

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
        await self._redis.xack(self._stream_key, settings.REDIS_CONSUMER_GROUP, message_id)

    async def _recovery_loop(self) -> None:
        """消息恢复循环。

        定期扫描并认领长时间未处理的消息 (PEL)，防止消息丢失。
        """
        last_id = "0-0"
        while self._running:
            try:
                await asyncio.sleep(settings.STREAM_RECOVERY_INTERVAL)

                # XAUTOCLAIM
                # 尝试认领闲置超过 STREAM_MIN_IDLE_TIME 的消息
                messages = await self._redis.xautoclaim(
                    self._stream_key,
                    settings.REDIS_CONSUMER_GROUP,
                    settings.REDIS_CONSUMER_NAME,
                    min_idle_time=settings.STREAM_MIN_IDLE_TIME,
                    start_id=last_id,
                    count=settings.BATCH_SIZE,
                )

                # messages 结构: (next_start_id, entries, [deleted_ids])
                # entries 是列表 [(message_id, fields), ...]
                if messages:
                    # 更新游标
                    last_id = messages[0]
                    entries = messages[1]

                    if entries:
                        logger.info("Recovered {} messages.", len(entries))
                        for message_id, fields in entries:
                            await self._process_message(message_id, fields)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in recovery loop: {}", e)
                # 出错时重置 last_id 以防卡死
                last_id = "0-0"
                await asyncio.sleep(60)
