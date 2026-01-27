from unittest.mock import AsyncMock

import pytest
from tiebameow.schemas.rules import Actions, ReviewRule, TargetType

from src.config import settings
from src.infra.dispatcher import ReviewResultDispatcher


@pytest.fixture
def mock_redis():
    return AsyncMock()


@pytest.fixture
def dispatcher(mock_redis):
    return ReviewResultDispatcher(mock_redis)


@pytest.mark.asyncio
async def test_dispatch_empty_rules(dispatcher, mock_redis):
    await dispatcher.dispatch([], 1, "post", {})
    mock_redis.xadd.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_success(dispatcher, mock_redis):
    from tiebameow.schemas.rules import Condition, FieldType, OperatorType

    rule = ReviewRule(
        id=101,
        name="Test",
        enabled=True,
        trigger=Condition(field=FieldType.TITLE, operator=OperatorType.EQ, value="test"),
        actions=Actions(),
        block=True,
        priority=1,
        fid=1,
        forum_rule_id=1,
        uploader_id=1,
        target_type=TargetType.THREAD,
    )

    data = {"id": 123, "title": "foo"}

    await dispatcher.dispatch([rule], fid=1, object_type="thread", object_data=data)

    mock_redis.xadd.assert_called_once()
    args = mock_redis.xadd.call_args
    # settings.REDIS_ACTION_STREAM_KEY, stream_entry
    assert args[0][0] == settings.REDIS_ACTION_STREAM_KEY
    entry = args[0][1]
    assert "data" in entry

    payload_json = entry["data"]
    import orjson

    payload = orjson.loads(payload_json)

    assert payload["fid"] == 1
    assert payload["matched_rule_ids"] == [101]
    assert payload["object_type"] == "thread"
    assert payload["object_data"] == data
    assert "timestamp" in payload


@pytest.mark.asyncio
async def test_dispatch_exception(dispatcher, mock_redis):
    from tiebameow.schemas.rules import Condition, FieldType, OperatorType

    mock_redis.xadd.side_effect = Exception("Redis error")
    rule = ReviewRule(
        id=101,
        name="Test",
        enabled=True,
        trigger=Condition(field=FieldType.TITLE, operator=OperatorType.EQ, value="test"),
        actions=Actions(),
        block=True,
        priority=1,
        fid=1,
        forum_rule_id=1,
        uploader_id=1,
        target_type=TargetType.THREAD,
    )
    # Should log error but not raise
    await dispatcher.dispatch([rule], 1, "post", {})
