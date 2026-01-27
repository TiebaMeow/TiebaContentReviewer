import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import orjson
import pytest
from tiebameow.schemas.rules import ReviewRule, TargetType

from src.infra.repository import RuleRepository


@pytest.fixture
def repo(mock_redis):
    return RuleRepository(mock_redis)


def test_rule_indexing(repo):
    # Setup rules
    # Rule 1: FID 100, Type THREAD
    rule1 = MagicMock(spec=ReviewRule)
    rule1.id = 1
    rule1.fid = 100
    rule1.target_type = TargetType.THREAD
    rule1.priority = 10

    # Rule 2: FID 200, Type POST
    rule2 = MagicMock(spec=ReviewRule)
    rule2.id = 2
    rule2.fid = 200
    rule2.target_type = TargetType.POST
    rule2.priority = 20

    # Rule 3: FID 100, Type ALL (Acts as "Global" for FID 100)
    rule3 = MagicMock(spec=ReviewRule)
    rule3.id = 3
    rule3.fid = 100
    rule3.target_type = TargetType.ALL
    rule3.priority = 5

    # Rule 4: FID 100, Type POST
    rule4 = MagicMock(spec=ReviewRule)
    rule4.id = 4
    rule4.fid = 100
    rule4.target_type = TargetType.POST
    rule4.priority = 15

    # Mock internal list
    repo._rules = [rule1, rule2, rule3, rule4]

    # Rebuild index manually
    repo._rebuild_index()

    # Case 1: Fetch for FID 100, Type THREAD
    # Expected: rule1 (FID 100 THREAD) + rule3 (FID 100 ALL)
    # Sorted by priority: rule3 (5), rule1 (10)
    rules_100_thread = repo.get_match_rules(100, "thread")
    assert len(rules_100_thread) == 2
    ids = [r.id for r in rules_100_thread]
    assert ids == [3, 1]

    # Case 2: Fetch for FID 100, Type POST
    # Expected: rule4 (FID 100 POST) + rule3 (FID 100 ALL)
    # Sorted by priority: rule3 (5), rule4 (15)
    rules_100_post = repo.get_match_rules(100, "post")
    assert len(rules_100_post) == 2
    ids = [r.id for r in rules_100_post]
    assert ids == [3, 4]

    # Case 3: Fetch for FID 200, Type POST
    # Expected: rule2 (FID 200 POST) + (No ALL rule for 200)
    # Sorted by priority: rule2 (20)
    rules_200_post = repo.get_match_rules(200, "post")
    assert len(rules_200_post) == 1
    ids = [r.id for r in rules_200_post]
    assert ids == [2]

    # Case 4: Fetch for FID 200, Type THREAD
    # Expected: Empty (No THREAD rule, No ALL rule for 200)
    rules_200_thread = repo.get_match_rules(200, "thread")
    assert len(rules_200_thread) == 0


@pytest.mark.asyncio
async def test_load_initial_rules(repo):
    # Mock DB session and result
    mock_rule = MagicMock()
    # Mock return values for to_rule_data
    mock_rule.to_rule_data.return_value = MagicMock(id=1, fid=100, target_type=TargetType.THREAD, priority=10)

    # Mock the SQLAlchemy result
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_rule]

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    # Mock get_session context manager
    mock_get_session_cm = AsyncMock()
    mock_get_session_cm.__aenter__.return_value = mock_session
    mock_get_session_cm.__aexit__.return_value = None

    with patch("src.infra.repository.get_session", return_value=mock_get_session_cm):
        await repo.load_initial_rules()

    assert len(repo._rules) == 1
    assert repo._rules[0].id == 1
    assert (100, TargetType.THREAD) in repo._rule_index


@pytest.mark.asyncio
async def test_handle_update_delete(repo):
    # Setup initial rule
    rule = MagicMock(spec=ReviewRule)
    # Be careful with MagicMock attributes being overwritten
    rule.id = 1
    rule.fid = 100
    rule.target_type = TargetType.THREAD
    rule.priority = 10

    repo._rules = [rule]
    repo._rebuild_index()
    assert len(repo._rules) == 1

    raw_data = orjson.dumps({"type": "DELETE", "rule_id": 1})

    await repo._handle_update(raw_data)

    assert len(repo._rules) == 0


@pytest.mark.asyncio
async def test_redis_listener(repo):
    # Mock redis pubsub
    # repo._redis is MagicMock
    # pubsub() returns something.
    mock_pubsub = MagicMock()
    repo._redis.pubsub.return_value = mock_pubsub

    # Simulate a message and then a cancellation
    messages = [
        {"type": "message", "data": orjson.dumps({"type": "UPDATE", "rule_id": 1})},
    ]

    async def msg_gen():
        for m in messages:
            yield m
        # Break loop by raising cancellation
        raise asyncio.CancelledError

    # Mock listen to return the async generator
    # listen() call returns an async iterator
    mock_pubsub.listen.side_effect = msg_gen

    # Mock subscribe/unsubscribe
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.close = AsyncMock()

    # Mock handle_update
    repo._handle_update = AsyncMock()

    try:
        await repo._redis_listener()
    except asyncio.CancelledError:
        pass

    repo._handle_update.assert_called_once()
    mock_pubsub.unsubscribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_periodic_sync(repo):
    # Mock sleep to stop loop after one iteration (first sleep for interval, second raises CancelledError to exit)
    with patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError]):
        # Mock DB
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1234567890  # max_updated_at set to timestamp
        mock_session.execute.return_value = mock_result

        mock_get_session_cm = AsyncMock()
        mock_get_session_cm.__aenter__.return_value = mock_session
        mock_get_session_cm.__aexit__.return_value = None

        repo._last_synced_at = 1000  # older
        repo._refresh_all_rules = AsyncMock()

        with patch("src.infra.repository.get_session", return_value=mock_get_session_cm):
            try:
                await repo._periodic_sync_loop()
            except asyncio.CancelledError:
                pass

        repo._refresh_all_rules.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_update_add(repo):
    repo._rules = []

    mock_db_rule = MagicMock()
    # Mock database rule object
    mock_db_rule.enabled = True

    # Mock the converted rule data
    converted_rule = MagicMock(spec=ReviewRule)
    converted_rule.id = 2
    converted_rule.fid = 200
    converted_rule.target_type = TargetType.POST

    mock_db_rule.to_rule_data.return_value = converted_rule

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_db_rule

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    mock_get_session_cm = AsyncMock()
    mock_get_session_cm.__aenter__.return_value = mock_session
    mock_get_session_cm.__aexit__.return_value = None

    raw_data = orjson.dumps({"type": "ADD", "rule_id": 2})

    with patch("src.infra.repository.get_session", return_value=mock_get_session_cm):
        await repo._handle_update(raw_data)

    assert len(repo._rules) == 1
    assert repo._rules[0].id == 2


@pytest.mark.asyncio
async def test_sync_lifecycle(repo):
    # Mock listener and loop to avoid blocking/infinite loops
    # We replace the methods on the instance with AsyncMocks
    repo._redis_listener = AsyncMock()
    repo._periodic_sync_loop = AsyncMock()

    repo.start_sync()
    assert repo._sync_task is not None
    assert repo._periodic_sync_task is not None

    # Check that calling start_sync again doesn't spawn new tasks if not done
    t1 = repo._sync_task
    repo.start_sync()
    assert repo._sync_task is t1

    await repo.stop_sync()
