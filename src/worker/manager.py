from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tiebameow.utils.logger import logger

from src.worker.consumer import ReviewWorker

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.core.engine import RuleMatcher
    from src.infra.dispatcher import ReviewResultDispatcher
    from src.infra.repository import RuleRepository


class WorkerManager:
    """Worker 管理器。

    根据活跃规则中的 fid 动态启动或停止 ReviewWorker 实例。
    """

    def __init__(
        self,
        repository: RuleRepository,
        dispatcher: ReviewResultDispatcher,
        matcher: RuleMatcher,
        redis_client: Redis,
        stream_key: str,
    ) -> None:
        self._repo = repository
        self._dispatcher = dispatcher
        self._matcher = matcher
        self._redis = redis_client
        self._stream_key = stream_key

        # 存储活跃的 worker: fid -> (worker_instance, task)
        self._active_workers: dict[int, tuple[ReviewWorker, asyncio.Task[None]]] = {}
        self._running = False
        self._manage_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """启动管理器。"""
        self._running = True
        self._manage_task = asyncio.create_task(self._loop())
        logger.info("WorkerManager started.")

    async def stop(self) -> None:
        """停止管理器及所有 Worker。"""
        self._running = False
        if self._manage_task:
            self._manage_task.cancel()

        # 停止所有子 worker
        for fid, (worker, task) in self._active_workers.items():
            logger.info(f"Stopping worker for fid {fid}...")
            worker.stop()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._active_workers.clear()

    async def _loop(self) -> None:
        """定期检查规则变更并调整 Worker。"""
        while self._running:
            try:
                await self._reconcile_workers()
                # 每隔一段时间检查一次，或者可以结合 Repository 的事件通知机制优化
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in WorkerManager loop: {e}")
                await asyncio.sleep(5)

    async def _reconcile_workers(self) -> None:
        """协调 Worker 状态与规则状态一致。"""
        rules = self._repo.get_active_rules()

        # 提取所有需要监听的 fid
        # 假设 RuleDBModel 中的 fid 字段对应规则适用的贴吧
        # 如果有全局规则 (fid=0 或特定标识)，可能需要特殊处理
        active_fids = {rule.fid for rule in rules if hasattr(rule, "fid")}

        # 1. 停止不再需要的 Worker
        current_fids = set(self._active_workers.keys())
        to_remove = current_fids - active_fids

        for fid in to_remove:
            logger.info(f"No active rules for fid {fid}, stopping worker.")
            worker, task = self._active_workers.pop(fid)
            worker.stop()
            # 不等待 task 结束，让它在后台取消，避免阻塞主循环
            task.cancel()

        # 2. 启动新的 Worker
        to_add = active_fids - current_fids

        for fid in to_add:
            logger.info(f"New active rules for fid {fid}, starting worker.")
            # 构造特定 fid 的 stream key
            stream_key = f"{self._stream_key}:{fid}"

            worker = ReviewWorker(
                self._repo,
                self._dispatcher,
                self._matcher,
                self._redis,
                stream_key=stream_key,
                fid=fid,
            )
            task = asyncio.create_task(worker.run())
            self._active_workers[fid] = (worker, task)
