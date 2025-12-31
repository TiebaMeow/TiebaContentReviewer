import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.rules import Action, Condition, ReviewRule
from src.worker.consumer import ReviewWorker


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get_active_rules.return_value = []
    return repo


@pytest.fixture
def mock_dispatcher():
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
    return dispatcher


@pytest.fixture
def mock_matcher():
    matcher = MagicMock()
    matcher.match.return_value = False
    return matcher


@pytest.mark.asyncio
async def test_ensure_consumer_group(mock_redis, mock_repo, mock_dispatcher, mock_matcher):
    worker = ReviewWorker(mock_repo, mock_dispatcher, mock_matcher, mock_redis)

    await worker._ensure_consumer_group()

    mock_redis.xgroup_create.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_success(mock_redis, mock_repo, mock_dispatcher, mock_matcher):
    worker = ReviewWorker(mock_repo, mock_dispatcher, mock_matcher, mock_redis)

    # Setup rule match
    rule = ReviewRule(
        id=1,
        name="test",
        enabled=True,
        priority=10,
        trigger=Condition(field="content", operator="contains", value="bad"),
        actions=[Action(type="delete", params={})],
    )
    mock_repo.get_active_rules.return_value = [rule]
    mock_matcher.match.return_value = True

    # Message data
    payload = {"content": "this is bad content"}
    message_data = {"object_type": "post", "payload": payload}
    fields = {"data": json.dumps(message_data)}

    # Mock deserialize to return a dict or object
    with patch("src.worker.consumer.deserialize") as mock_deserialize:
        mock_deserialize.return_value = payload  # Simple dict for now

        await worker._process_message("msg-id-1", fields)

        # Verify matching called
        mock_matcher.match.assert_called_with(payload, rule)

        # Verify dispatch called
        mock_dispatcher.dispatch.assert_called_once()
        args = mock_dispatcher.dispatch.call_args[0]
        # args[0] should be list of ReviewRule
        assert len(args[0]) == 1
        assert args[0][0] == rule
        assert args[1] == "post"
        assert args[2] == payload

        # Verify ACK
        mock_redis.xack.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_invalid_format(mock_redis, mock_repo, mock_dispatcher, mock_matcher):
    worker = ReviewWorker(mock_repo, mock_dispatcher, mock_matcher, mock_redis)

    # Missing data field
    await worker._process_message("msg-id-1", {})
    mock_redis.xack.assert_called_once()  # Should ack to skip bad message
    mock_dispatcher.dispatch.assert_not_called()

    mock_redis.xack.reset_mock()

    # Invalid JSON
    await worker._process_message("msg-id-2", {"data": "invalid-json"})
    # Should ack to skip bad message
    mock_redis.xack.assert_called_once()


@pytest.mark.asyncio
async def test_run_loop(mock_redis, mock_repo, mock_dispatcher, mock_matcher):
    worker = ReviewWorker(mock_repo, mock_dispatcher, mock_matcher, mock_redis)

    # Mock xreadgroup to return one message then empty
    # We need to stop the loop, so we can raise an exception or set _running to False

    async def side_effect(*args, **kwargs):
        worker.stop()  # Stop after first call
        return [["stream_key", [("msg-id-1", {"data": json.dumps({"object_type": "t", "payload": {}})})]]]

    mock_redis.xreadgroup.side_effect = side_effect

    # Mock _process_message to avoid complex setup
    worker._process_message = AsyncMock()

    # Mock _ensure_consumer_group
    worker._ensure_consumer_group = AsyncMock()

    await worker.run()

    worker._process_message.assert_called_once()
