import pytest
from tiebameow.schemas.rules import Actions, Condition, FieldType, OperatorType, ReviewRule, TargetType

from src.core.engine import RuleMatcher


class MockDTO:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
def matcher():
    return RuleMatcher()


def test_regex_caching(matcher):
    condition = Condition(field=FieldType.TEXT, operator=OperatorType.REGEX, value="test_pattern")
    dto = MockDTO(text="some test_pattern here")

    # Initial call should cache
    assert matcher._evaluate_condition(dto, condition) is True
    assert "test_pattern" in matcher._regex_cache

    # Verify cache is used (can't easily verify use without mocking re.compile again,
    # but presence in cache is good indicator)

    # Check pre-compiled pattern matches
    pattern = matcher._regex_cache["test_pattern"]
    assert pattern.search("test_pattern")


def test_match_all(matcher):
    rule1 = ReviewRule(
        id=1,
        name="Rule 1",
        enabled=True,
        trigger=Condition(field=FieldType.TITLE, operator=OperatorType.EQ, value="foo"),
        actions=Actions(),
        priority=10,
        fid=1,
        forum_rule_id=101,
        uploader_id=0,
        target_type=TargetType.THREAD,
    )
    rule2 = ReviewRule(
        id=2,
        name="Rule 2",
        enabled=True,
        trigger=Condition(field=FieldType.TITLE, operator=OperatorType.EQ, value="bar"),
        actions=Actions(),
        priority=10,
        fid=1,
        forum_rule_id=102,
        uploader_id=0,
        target_type=TargetType.THREAD,
    )

    data = MockDTO(title="foo")
    matched = matcher.match_all(data, [rule1, rule2])

    assert len(matched) == 1
    assert matched[0].id == 1


def test_regex_exceptions(matcher):
    # Bad regex should not crash
    condition = Condition(field=FieldType.TEXT, operator=OperatorType.REGEX, value="[")
    dto = MockDTO(text="text")
    assert matcher._evaluate_condition(dto, condition) is False

    # Not regex bad regex
    condition.operator = OperatorType.NOT_REGEX
    assert matcher._evaluate_condition(dto, condition) is True
