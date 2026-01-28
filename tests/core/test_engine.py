from unittest.mock import patch

import pytest
from tiebameow.models.dto import ThreadDTO
from tiebameow.schemas.rules import (
    Actions,
    Condition,
    FieldType,
    FunctionCall,
    LogicType,
    OperatorType,
    ReviewRule,
    RuleGroup,
    TargetType,
)

from src.core.engine import RuleMatcher
from src.core.provider import LocalFunctionProvider
from src.core.registry import rule_functions


@pytest.fixture
def matcher():
    return RuleMatcher()


@pytest.fixture
def mock_rule():
    def _create(
        id=1,  # noqa: A002
        name="Test",
        block=False,
        priority=10,
        field=FieldType.TITLE,
        op=OperatorType.EQ,
        val="test",
        func_name=None,
    ):
        if func_name:
            trigger = Condition(
                field=FunctionCall(name=func_name, args=[], kwargs={}),
                operator=op,
                value=val,
            )
        else:
            trigger = Condition(field=field, operator=op, value=val)

        return ReviewRule(
            id=id,
            name=name,
            enabled=True,
            trigger=trigger,
            actions=Actions(),
            block=block,
            priority=priority,
            fid=1,
            forum_rule_id=101,
            uploader_id=0,
            target_type=TargetType.THREAD,
        )

    return _create


@pytest.mark.asyncio
async def test_regex_caching(matcher):
    condition = Condition(field=FieldType.TITLE, operator=OperatorType.REGEX, value="test_pattern")
    dto = ThreadDTO.from_incomplete_data({"title": "some test_pattern here"})

    # Initial call should cache
    assert await matcher._evaluate_condition(dto, condition) is True
    assert "test_pattern" in matcher._regex_cache

    # Check pre-compiled pattern matches
    pattern = matcher._regex_cache["test_pattern"]
    assert pattern.search("test_pattern")


@pytest.mark.asyncio
async def test_match_all(matcher, mock_rule):
    rule1 = mock_rule(id=1, name="Rule 1", val="foo", block=False)
    rule2 = mock_rule(id=2, name="Rule 2", val="bar", block=True)

    data = ThreadDTO.from_incomplete_data({"title": "foo"})
    matched, _ = await matcher.match_all(data, [rule1, rule2])

    assert len(matched) == 1
    assert matched[0].id == 1


@pytest.mark.asyncio
async def test_regex_exceptions(matcher):
    # Test valid regex but non-matching
    dto = ThreadDTO.from_incomplete_data({"text": "def"})
    condition = Condition(field=FieldType.TEXT, operator=OperatorType.REGEX, value="abc")
    assert await matcher._evaluate_condition(dto, condition) is False

    # Test invalid regex (should raise re.error internally and return False)
    condition.value = "["
    dto.text = "abc"
    assert await matcher._evaluate_condition(dto, condition) is False

    # Not regex bad regex (error -> True for safety)
    condition.operator = OperatorType.NOT_REGEX
    assert await matcher._evaluate_condition(dto, condition) is True

    # Valid NOT_REGEX matching (should be False)
    condition.value = "abc"
    assert await matcher._evaluate_condition(dto, condition) is False

    # Valid NOT_REGEX not matching (should be True)
    dto.text = "def"
    assert await matcher._evaluate_condition(dto, condition) is True


@pytest.mark.asyncio
async def test_type_error_handling(matcher):
    dto = ThreadDTO.from_incomplete_data({"reply_num": 10})

    # GT TypeError: str > int
    condition_gt = Condition(field=FieldType.REPLY_NUM, operator=OperatorType.GT, value=10)
    # Mock finding field value to return a string

    with patch.object(matcher, "_get_field_value", return_value="string"):
        assert await matcher._evaluate_condition(dto, condition_gt) is False

    # LT TypeError: None < int
    condition_lt = Condition(field=FieldType.REPLY_NUM, operator=OperatorType.LT, value=10)
    with patch.object(matcher, "_get_field_value", return_value=None):
        assert await matcher._evaluate_condition(dto, condition_lt) is False


@pytest.mark.asyncio
async def test_function_call_local():
    # Setup registry
    @rule_functions.register("test_local_func_call")
    def local_func(data, x):
        return x > 10

    provider = LocalFunctionProvider()
    matcher = RuleMatcher(provider=provider)
    dto = ThreadDTO.from_incomplete_data({})

    # Condition: test_local_func_call(15) is True
    fc = FunctionCall(name="test_local_func_call", args=[15])
    assert await matcher._execute_function_call(dto, fc) is True


@pytest.mark.asyncio
async def test_logic_operators(matcher):
    data = ThreadDTO.from_incomplete_data({"title": "test"})

    def mk_cond(val, result):
        return Condition(field=FieldType.TITLE, operator=OperatorType.EQ, value=val)

    # AND
    g_and = RuleGroup(logic=LogicType.AND, conditions=[mk_cond("test", True), mk_cond("test", True)])
    assert await matcher._evaluate_node(data, g_and) is True

    g_and_fail = RuleGroup(logic=LogicType.AND, conditions=[mk_cond("test", True), mk_cond("fail", False)])
    assert await matcher._evaluate_node(data, g_and_fail) is False

    # OR
    g_or = RuleGroup(logic=LogicType.OR, conditions=[mk_cond("fail", False), mk_cond("test", True)])
    assert await matcher._evaluate_node(data, g_or) is True

    # NOT
    g_not = RuleGroup(logic=LogicType.NOT, conditions=[mk_cond("fail", False)])
    assert await matcher._evaluate_node(data, g_not) is True


@pytest.mark.asyncio
async def test_operators(matcher):
    data = ThreadDTO.from_incomplete_data({"title": "hello world"})

    assert await matcher._evaluate_condition(
        data, Condition(field=FieldType.TITLE, operator=OperatorType.GT, value="a")
    )
    assert not await matcher._evaluate_condition(
        data, Condition(field=FieldType.TITLE, operator=OperatorType.GT, value="z")
    )
    assert await matcher._evaluate_condition(
        data, Condition(field=FieldType.TITLE, operator=OperatorType.CONTAINS, value="world")
    )
    assert not await matcher._evaluate_condition(
        data, Condition(field=FieldType.TITLE, operator=OperatorType.NOT_CONTAINS, value="world")
    )
    assert await matcher._evaluate_condition(
        data, Condition(field=FieldType.TITLE, operator=OperatorType.IN, value=["hello world", "foo"])
    )


@pytest.mark.asyncio
async def test_match_all_mixed(matcher, mock_rule):
    # Register a local function
    @rule_functions.register("is_local_fs")
    def is_local(data):
        return True

    # Fast Rule (uses local function)
    r1 = mock_rule(id=1, name="Fast", func_name="is_local_fs", op=OperatorType.EQ, val=True, block=False)

    # Slow Rule (uses remote/unknown function)
    r2 = mock_rule(id=2, name="Slow", func_name="remote_func", op=OperatorType.EQ, val=True, block=False)

    data = ThreadDTO.from_incomplete_data({})

    # Patch match to simulate rule passing without actual function execution
    async def side_effect_match(d, r, ctx=None):
        # We want both to match
        return True

    with patch.object(matcher, "match", side_effect=side_effect_match):
        matched, _ = await matcher.match_all(data, [r1, r2])

    assert len(matched) == 2
    ids = {r.id for r in matched}
    assert {1, 2} == ids


@pytest.mark.asyncio
async def test_match_all_blocking_priority(matcher, mock_rule):
    @rule_functions.register("is_local_bp")
    def is_local(data):
        return True

    # Fast Rule, Blocking
    fast_block = mock_rule(
        id=1, name="Fast Block", func_name="is_local_bp", op=OperatorType.EQ, val=True, block=True, priority=10
    )
    # Slow Rule
    slow = mock_rule(id=2, name="Slow", func_name="remote_func", op=OperatorType.EQ, val=True, block=False, priority=10)

    data = ThreadDTO.from_incomplete_data({})

    with patch.object(matcher, "match", return_value=True) as mock_match:
        # Pass in sorted order (fast_block first)
        matched, _ = await matcher.match_all(data, [fast_block, slow])

        assert len(matched) == 1
        assert matched[0].id == 1

        # Verify slow rule wasn't checked because fast_block blocked it
        assert mock_match.call_count == 1
        assert mock_match.call_args[0][1] == fast_block


@pytest.mark.asyncio
async def test_registry_duplicate_error():
    name = "unique_func_dup"

    @rule_functions.register(name)
    def func1(d):
        return True

    with pytest.raises(ValueError, match="already registered"):

        @rule_functions.register(name)
        def func2(d):
            return False
