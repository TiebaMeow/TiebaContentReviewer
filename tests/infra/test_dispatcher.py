import json
from unittest.mock import Mock

import pytest

from src.core.rules import Action, ReviewRule
from src.infra.dispatcher import ReviewResultDispatcher


@pytest.mark.asyncio
async def test_dispatch(mock_redis):
    dispatcher = ReviewResultDispatcher(mock_redis)

    rule = Mock(spec=ReviewRule)
    rule.id = 1
    rule.name = "test_rule"
    rule.priority = 10
    rule.actions = [
        Action(type="delete", params={"reason": "spam"}),
        Action(type="ban", params={"days": 1}),
    ]

    rules = [rule]
    target_data = {"id": 123, "content": "bad content"}
    object_type = "post"

    await dispatcher.dispatch(rules, object_type, target_data)

    assert mock_redis.xadd.call_count == 1

    # Verify payload of first call
    call_args = mock_redis.xadd.call_args_list[0]
    stream_key, stream_entry = call_args[0]

    assert "data" in stream_entry
    payload_json = stream_entry["data"]
    payload = json.loads(payload_json)

    assert len(payload["matched_rules"]) == 1
    matched_rule = payload["matched_rules"][0]
    assert matched_rule["id"] == 1
    assert matched_rule["name"] == "test_rule"
    assert matched_rule["priority"] == 10
    assert len(matched_rule["actions"]) == 2
    assert matched_rule["actions"][0]["type"] == "delete"
    assert payload["target_data"] == target_data
    assert payload["object_type"] == object_type
    assert "timestamp" in payload


@pytest.mark.asyncio
async def test_dispatch_empty(mock_redis):
    dispatcher = ReviewResultDispatcher(mock_redis)
    await dispatcher.dispatch([], "post", {})
    mock_redis.xadd.assert_not_called()
