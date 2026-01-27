from __future__ import annotations

import asyncio
import signal
import sys

from tiebameow.utils.logger import init_logger, logger

from src.config import settings
from src.core.engine import RuleMatcher
from src.core.provider import (
    FunctionProvider,
    HybridFunctionProvider,
    LocalFunctionProvider,
)
from src.infra.db import dispose_db, init_db
from src.infra.dispatcher import ReviewResultDispatcher
from src.infra.redis_client import get_redis_client
from src.infra.repository import RuleRepository
from src.worker.manager import WorkerManager


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

    # 根据配置初始化函数提供者
    provider: FunctionProvider
    if settings.RPC_ENABLED:
        target = settings.RPC_URL.replace("http://", "").replace("https://", "")
        logger.info("Initializing Hybrid Function Provider (RPC Target: {})", target)
        provider = HybridFunctionProvider(rpc_target=target, rpc_timeout=settings.RPC_TIMEOUT)
    else:
        logger.info("Initializing Local Function Provider")
        provider = LocalFunctionProvider()

    matcher = RuleMatcher(provider=provider)

    # 3. 加载规则并启动同步
    try:
        await repo.load_initial_rules()
        repo.start_sync()
    except Exception as e:
        logger.critical("Failed to load rules: {}", e)
        sys.exit(1)

    # 4. 初始化 Worker Manager
    stream_key = settings.REDIS_STREAM_KEY
    manager = WorkerManager(repo, dispatcher, matcher, redis_client, stream_key)

    # 5. 信号处理
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Shutdown signal received.")
        asyncio.create_task(manager.stop())
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # 6. 运行 Manager
    await manager.start()

    # 等待停止信号
    await stop_event.wait()

    # 优雅关闭
    logger.info("Stopping services...")
    await repo.stop_sync()
    await manager.stop()
    await dispose_db()
    await redis_client.close()

    logger.info("Exiting...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
