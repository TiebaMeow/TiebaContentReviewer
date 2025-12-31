import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.rules import Condition, ReviewRule
from src.infra.repository import RuleRepository


@pytest.fixture
def mock_db_rules():
    # Create mock DB objects
    rule1 = MagicMock()
    rule1.id = 1
    rule1.name = "rule1"
    rule1.enabled = True
    rule1.priority = 10
    rule1.trigger = {"field": "content", "operator": "contains", "value": "bad"}
    rule1.actions = [{"type": "delete", "params": {}}]
    return [rule1]


@pytest.mark.asyncio
async def test_load_initial_rules(mock_redis, mock_db_session, mock_db_rules):
    # Setup mock DB result
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_db_rules
    mock_db_session.execute.return_value = mock_result

    # Patch AsyncSessionLocal to return our mock session
    with patch("src.infra.repository.AsyncSessionLocal") as mock_session_cls:
        mock_session_cls.return_value.__aenter__.return_value = mock_db_session

        repo = RuleRepository(mock_redis)
        await repo.load_initial_rules()

        assert len(repo.get_active_rules()) == 1
        assert repo.get_active_rules()[0].id == 1
        mock_db_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_handle_update_delete(mock_redis):
    repo = RuleRepository(mock_redis)
    # Manually add a rule
    rule = ReviewRule(
        id=1, name="test", enabled=True, priority=10, trigger=Condition(field="a", operator="eq", value=1), actions=[]
    )
    repo._rules = [rule]

    # Simulate DELETE event
    event = json.dumps({"type": "DELETE", "rule_id": 1})
    await repo._handle_update(event)

    assert len(repo.get_active_rules()) == 0


@pytest.mark.asyncio
async def test_handle_update_add(mock_redis, mock_db_session, mock_db_rules):
    repo = RuleRepository(mock_redis)

    # Setup mock DB for single rule fetch
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_db_rules[0]
    mock_db_session.execute.return_value = mock_result

    with patch("src.infra.repository.AsyncSessionLocal") as mock_session_cls:
        mock_session_cls.return_value.__aenter__.return_value = mock_db_session

        # Simulate ADD event
        event = json.dumps({"type": "ADD", "rule_id": 1})
        await repo._handle_update(event)

        assert len(repo.get_active_rules()) == 1
        assert repo.get_active_rules()[0].id == 1


@pytest.mark.asyncio
async def test_redis_listener(mock_redis):
    repo = RuleRepository(mock_redis)

    # Mock handle_update to avoid DB calls
    repo._handle_update = AsyncMock()

    # Mock listen to block so we don't spin in the while True loop
    async def blocking_listen():
        # Simulate waiting for a message
        await asyncio.sleep(1)
        yield {"type": "ping", "data": "pong"}

    mock_redis.pubsub.return_value.listen = blocking_listen

    # Start sync
    repo.start_sync()

    # Wait a bit for the task to run
    await asyncio.sleep(0.1)

    # Stop sync
    await repo.stop_sync()

    mock_redis.pubsub.assert_called_once()
    # Verify subscribe was called
    mock_redis.pubsub.return_value.subscribe.assert_called()
