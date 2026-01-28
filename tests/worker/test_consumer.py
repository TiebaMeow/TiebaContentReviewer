import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import settings
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
    matcher.match_all.return_value = ([], {})
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
    responses = [
        ("1-0", [("msg1", {"data": "{}"})], []),  # Call 1
        ("2-0", [("msg2", {"data": "{}"})], []),  # Call 2
    ]

    async def side_effect(*args, **kwargs):
        nonlocal responses
        if not responses:
            raise asyncio.CancelledError

        ret = responses.pop(0)
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
        assert mock_matcher.match_all.called
        args = mock_matcher.match_all.call_args
        assert args[0][0] == mock_obj
        assert args[0][1] == mock_repo.get_match_rules.return_value


@pytest.mark.asyncio
async def test_process_message_errors(worker):
    worker._ack = AsyncMock()
    worker._matcher.match_all = AsyncMock(return_value=([], {}))

    # 1. Missing data
    await worker._process_message("1", {})
    worker._ack.assert_awaited_with("1")

    # 2. Invalid format
    worker._ack.reset_mock()
    await worker._process_message("2", {"data": '{"payload": {}}'})
    worker._ack.assert_awaited_with("2")

    # 3. Invalid payload type
    worker._ack.reset_mock()
    await worker._process_message("3", {"data": '{"object_type": "post", "payload": "not_dict"}'})
    worker._ack.assert_awaited_with("3")

    # 4. Deserialization error
    worker._ack.reset_mock()
    with patch("src.worker.consumer.deserialize", side_effect=Exception("Data error")):
        await worker._process_message("4", {"data": '{"object_type": "post", "payload": {}}'})
    worker._ack.assert_awaited_with("4")

    # 5. Rule matching error
    worker._ack.reset_mock()
    with patch("src.worker.consumer.deserialize"):
        worker._repo.get_match_rules.return_value = [MagicMock()]
        worker._matcher.match_all = AsyncMock(side_effect=Exception("Matcher error"))
        await worker._process_message("5", {"data": '{"object_type": "post", "payload": {}}'})
    worker._ack.assert_awaited_with("5")


@pytest.mark.asyncio
async def test_ensure_consumer_group(worker):
    from redis.exceptions import ResponseError

    worker._redis.xgroup_create.side_effect = ResponseError("BUSYGROUP")
    await worker._ensure_consumer_group()

    worker._redis.xgroup_create.side_effect = ResponseError("Other Error")
    with pytest.raises(ResponseError):
        await worker._ensure_consumer_group()


@pytest.mark.asyncio
async def test_process_message_fatal_error(worker):
    worker._ack = AsyncMock()
    worker._repo.get_match_rules.side_effect = Exception("Fatal")

    with patch("src.worker.consumer.settings") as mock_settings:
        mock_settings.ENABLE_STREAM_RECOVERY = False
        with patch("src.worker.consumer.deserialize"):
            await worker._process_message("99", {"data": '{"object_type": "post", "payload": {}}'})

    worker._ack.assert_awaited_with("99")


@pytest.mark.asyncio
async def test_ack_real(worker):
    await worker._ack("123")
    worker._redis.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_run_failed_task(worker):
    iter_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal iter_count
        iter_count += 1
        if iter_count == 1:
            return [("stream", [("1", {"data": "{}"})])]
        if iter_count < 3:
            await asyncio.sleep(0.01)
            return []
        raise asyncio.CancelledError

    worker._redis.xreadgroup.side_effect = side_effect

    async def process_fail(*args):
        raise ValueError("Fail")

    worker._process_message = process_fail

    with patch("src.worker.consumer.logger") as mock_logger:
        try:
            await worker.run()
        except asyncio.CancelledError:
            pass
        assert mock_logger.error.called


@pytest.mark.asyncio
async def test_process_message_match_success(worker):
    worker._ack = AsyncMock()
    rule = MagicMock()
    rule.id = 1
    worker._matcher.match_all = AsyncMock(return_value=([rule], {}))
    worker._repo.get_match_rules.return_value = [rule]
    worker._dispatcher.dispatch = AsyncMock()

    with (
        patch(
            "src.worker.consumer.orjson.loads",
            return_value={"object_type": "post", "object_id": 1, "payload": {"active": True}},
        ),
        patch("src.worker.consumer.deserialize") as mock_deserialize,
    ):
        mock_obj = MagicMock()
        mock_obj.model_dump.return_value = {"id": 1}
        mock_deserialize.return_value = mock_obj
        await worker._process_message("100", {"data": "{}"})

    worker._dispatcher.dispatch.assert_called_once()


# Concurrency Logic Tests (Merged)


@pytest.mark.asyncio
async def test_worker_concurrency_control(worker):
    settings.WORKER_CONCURRENCY = 2
    settings.BATCH_SIZE = 5

    active_count = 0
    max_active = 0

    async def slow_process(message_id: str, fields: dict[str, Any]) -> None:
        nonlocal active_count, max_active
        active_count += 1
        max_active = max(max_active, active_count)
        await asyncio.sleep(0.01)
        active_count -= 1

    worker._process_message = slow_process

    worker._redis.xreadgroup.side_effect = [
        [[b"stream", [(b"1-0", {}), (b"2-0", {})]]],
        [[b"stream", [(b"3-0", {})]]],
        [],
        Exception("Stop Loop"),
    ]

    worker._ensure_consumer_group = AsyncMock()

    try:
        await asyncio.wait_for(worker.run(), timeout=1.0)
    except Exception:
        pass

    assert max_active <= 2
    # Ensure it fetched enough times
    assert worker._redis.xreadgroup.call_count >= 2


@pytest.mark.asyncio
async def test_worker_sliding_window_refill(worker):
    """Test that worker refills tasks when slots open up."""
    settings.WORKER_CONCURRENCY = 10

    worker._ensure_consumer_group = AsyncMock()
    msgs_batch_1 = [[b"stream", [(str(i).encode(), {}) for i in range(10)]]]
    msgs_batch_2 = [[b"stream", [(b"11-0", {})]]]

    worker._redis.xreadgroup.side_effect = [
        msgs_batch_1,
        msgs_batch_2,
        Exception("Stop"),
    ]
    worker._process_message = AsyncMock()

    try:
        await asyncio.wait_for(worker.run(), timeout=0.5)
    except Exception:
        pass

    assert worker._process_message.call_count >= 11
