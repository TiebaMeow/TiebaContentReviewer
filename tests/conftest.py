import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def mock_redis():
    redis = MagicMock(spec=Redis)
    # Mock async methods
    redis.get = AsyncMock()
    redis.set = AsyncMock()
    redis.publish = AsyncMock()
    redis.subscribe = AsyncMock()
    redis.unsubscribe = AsyncMock()
    redis.rpush = AsyncMock()
    redis.xreadgroup = AsyncMock()
    redis.xgroup_create = AsyncMock()
    redis.xack = AsyncMock()

    # Mock pubsub
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    # Mock listen to return an async iterator

    async def mock_listen():
        yield {"type": "subscribe", "channel": "test", "data": 1}

    pubsub.listen = mock_listen

    redis.pubsub.return_value = pubsub
    return redis


@pytest.fixture
def mock_db_session():
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session
