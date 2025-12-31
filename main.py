from __future__ import annotations

import asyncio
import signal
import sys

from tiebameow.utils.logger import init_logger, logger

from src.core.engine import RuleMatcher
from src.infra.db import init_db
from src.infra.dispatcher import ReviewResultDispatcher
from src.infra.redis_client import get_redis_client
from src.infra.repository import RuleRepository
from src.worker.consumer import ReviewWorker


async def main() -> None:
    """服务入口函数。

    负责初始化各个组件（数据库、Redis、规则仓储、分发器、Worker），
    加载初始规则，启动后台同步任务，并运行 Worker 消费循环。
    同时处理系统信号以实现优雅关闭。
    """
    init_logger(service_name="TiebaContentReviewer")

    logger.info("Starting TiebaContentReviewer...")

    # 1. 初始化数据库
    try:
        await init_db()
        logger.info("Database initialized.")
    except Exception as e:
        logger.critical("Failed to initialize database: {}", e)
        sys.exit(1)

    # 2. 初始化组件
    redis_client = await get_redis_client()
    repo = RuleRepository(redis_client)
    dispatcher = ReviewResultDispatcher(redis_client)
    matcher = RuleMatcher()

    # 3. 加载规则并启动同步
    try:
        await repo.load_initial_rules()
        repo.start_sync()
    except Exception as e:
        logger.critical("Failed to load rules: {}", e)
        sys.exit(1)

    # 4. 初始化 Worker
    worker = ReviewWorker(repo, dispatcher, matcher, redis_client)

    # 5. 信号处理
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Shutdown signal received.")
        worker.stop()
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # 6. 运行 Worker
    worker_task = asyncio.create_task(worker.run())

    # 等待停止信号
    await stop_event.wait()

    # 优雅关闭
    logger.info("Stopping services...")
    await repo.stop_sync()

    # 等待 worker 结束
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Worker error during shutdown: {e}")

    logger.info("Exiting...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
