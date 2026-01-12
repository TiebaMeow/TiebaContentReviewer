from unittest.mock import MagicMock

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
