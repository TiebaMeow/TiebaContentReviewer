from __future__ import annotations

from urllib.parse import quote_plus

from pydantic import PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类。

    从环境变量或 .env 文件加载配置。

    Attributes:
        DB_HOST: 数据库主机地址。
        DB_PORT: 数据库端口。
        DB_USER: 数据库用户名。
        DB_PASSWORD: 数据库密码。
        DB_NAME: 数据库名称。
        REDIS_HOST: Redis 主机地址。
        REDIS_PORT: Redis 端口。
        REDIS_DB: Redis 数据库索引。
        REDIS_USER: Redis 用户名。
        REDIS_PASSWORD: Redis 密码。
        REDIS_STREAM_KEY: 输入数据流的 Key。
        REDIS_CONSUMER_GROUP: 消费者组名称。
        REDIS_CONSUMER_NAME: 消费者名称。
        REDIS_RULES_CHANNEL: 规则更新通知的 Pub/Sub 频道。
        REDIS_ACTION_STREAM_KEY: 输出动作流的 Key。
        BATCH_SIZE: 每次从 Stream 读取的消息数量。
        ENABLE_STREAM_RECOVERY: 是否启用 Stream 消息恢复机制。
        STREAM_RECOVERY_INTERVAL: Stream 恢复任务的运行间隔（秒）。
        STREAM_MIN_IDLE_TIME: 消息被视为闲置的最小时间（毫秒）。
        RULE_SYNC_INTERVAL: 规则定期同步间隔（秒）。
        LOG_LEVEL: 日志级别。
    """

    # Database
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_NAME: str = "tieba_reviewer"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_USER: str | None = None
    REDIS_PASSWORD: str | None = None

    # Redis Stream (Input)
    REDIS_STREAM_KEY: str = "scraper:tieba:events"
    REDIS_CONSUMER_GROUP: str = "reviewer_group"
    REDIS_CONSUMER_NAME: str = "reviewer_worker_1"

    # Redis Pub/Sub (Rules Sync)
    REDIS_RULES_CHANNEL: str = "reviewer:rules:update"

    # Redis Stream (Output Actions)
    REDIS_ACTION_STREAM_KEY: str = "reviewer:actions:stream"

    # Worker Settings
    BATCH_SIZE: int = 10
    ENABLE_STREAM_RECOVERY: bool = False
    STREAM_RECOVERY_INTERVAL: int = 60  # seconds
    STREAM_MIN_IDLE_TIME: int = 60000  # milliseconds (1 minute)

    # Rule Sync Settings
    RULE_SYNC_INTERVAL: int = 300  # seconds (5 minutes)

    # Logging
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def database_url(self) -> str:
        """获取 SQLAlchemy 格式的数据库连接 URL。"""
        return str(
            PostgresDsn(
                f"postgresql+asyncpg://{quote_plus(self.DB_USER)}:{quote_plus(self.DB_PASSWORD)}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )
        )

    @property
    def redis_url(self) -> str:
        """获取 Redis 连接 URL。"""
        if self.REDIS_USER and self.REDIS_PASSWORD:
            return str(
                RedisDsn(
                    f"redis://{quote_plus(self.REDIS_USER)}:{quote_plus(self.REDIS_PASSWORD)}"
                    f"@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
                )
            )
        if self.REDIS_PASSWORD:
            return str(
                RedisDsn(
                    f"redis://:{quote_plus(self.REDIS_PASSWORD)}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
                )
            )
        return str(RedisDsn(f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"))


settings = Settings()
