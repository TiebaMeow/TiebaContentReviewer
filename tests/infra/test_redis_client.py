from unittest.mock import MagicMock, patch

import pytest

from src.infra.redis_client import get_redis_client


@pytest.mark.asyncio
async def test_get_redis_client():
    with patch("redis.asyncio.Redis.from_url") as mock_from_url:
        mock_client = MagicMock()
        mock_from_url.return_value = mock_client

        client = await get_redis_client()
        assert client is mock_client
        mock_from_url.assert_called_once()
