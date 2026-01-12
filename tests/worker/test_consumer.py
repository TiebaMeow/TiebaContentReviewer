import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.worker.consumer import ReviewWorker


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get_match_rules.return_value = []
    return repo


@pytest.fixture
def mock_dispatcher():
    return AsyncMock()


@pytest.fixture
def mock_matcher():
    matcher = MagicMock()
    matcher.match_all.return_value = []
    # match_all is run in executor, so it's a sync function mock
    return matcher


@pytest.fixture
def worker(mock_repo, mock_dispatcher, mock_matcher, mock_redis):
    return ReviewWorker(
        repository=mock_repo,
        dispatcher=mock_dispatcher,
        matcher=mock_matcher,
        redis_client=mock_redis,
        fid=123,
        stream_key="test:stream",
    )


@pytest.mark.asyncio
async def test_recovery_loop_logic(worker):
    """Test that recovery loop uses and updates cursor properly."""

    # Setup xautoclaim mock responses
    # First call returns messages with next_id "1-0"
    # Second call returns messages with next_id "2-0"
    # Third call raises CancelledError to stop loop

    responses = [
        ("1-0", [("msg1", {"data": "{}"})], []),  # Call 1
        ("2-0", [("msg2", {"data": "{}"})], []),  # Call 2
    ]

    async def side_effect(*args, **kwargs):
        nonlocal responses
        # Check start_id used
        kwargs.get("start_id")

        if not responses:
            raise asyncio.CancelledError

        ret = responses.pop(0)
        # We can assert start_id here if we want strict checking order
        return ret

    worker._redis.xautoclaim = AsyncMock(side_effect=side_effect)
    worker._process_message = AsyncMock()

    # Speed up sleep
    with patch("asyncio.sleep", AsyncMock()):
        worker._running = True
        try:
            await worker._recovery_loop()
        except asyncio.CancelledError:
            pass

    # Verify calls
    assert worker._redis.xautoclaim.call_count == 3  # 2 responses + 1 cancelled

    # Check start_id params
    calls = worker._redis.xautoclaim.call_args_list
    assert calls[0].kwargs["start_id"] == "0-0"
    assert calls[1].kwargs["start_id"] == "1-0"
    assert calls[2].kwargs["start_id"] == "2-0"


@pytest.mark.asyncio
async def test_process_message_optimizations(worker, mock_repo, mock_matcher):
    """Test standard process flow uses optimizations."""

    # Mock data
    fields = {"data": '{"object_type": "post", "object_id": 1, "payload": {"active": true}}'}

    with patch("src.worker.consumer.deserialize") as mock_deserialize:
        mock_obj = MagicMock()
        mock_obj.model_dump.return_value = {}
        mock_deserialize.return_value = mock_obj

        await worker._process_message("123-0", fields)

        # 1. Check get_match_rules called with correct fid and object_type
        mock_repo.get_match_rules.assert_called_with(worker._fid, "post")

        # 2. Check run_in_executor usage (implicit via match_all call check)
        # Should call match_all(obj, rules)
        assert mock_matcher.match_all.called
        args = mock_matcher.match_all.call_args
        assert args[0][0] == mock_obj
        # Rules arg
        assert args[0][1] == mock_repo.get_match_rules.return_value
