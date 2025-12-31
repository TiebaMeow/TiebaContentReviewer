import pytest

from src.core.engine import RuleMatcher
from src.core.rules import Action, Condition, ReviewRule, RuleGroup


@pytest.fixture
def matcher():
    return RuleMatcher()


def test_basic_operators(matcher):
    data = {"age": 20, "name": "test", "tags": ["a", "b"]}

    # eq
    assert matcher._evaluate_node(data, Condition(field="age", operator="eq", value=20)) is True
    assert matcher._evaluate_node(data, Condition(field="age", operator="eq", value=21)) is False

    # gt/lt
    assert matcher._evaluate_node(data, Condition(field="age", operator="gt", value=10)) is True
    assert matcher._evaluate_node(data, Condition(field="age", operator="lt", value=30)) is True

    # contains
    assert matcher._evaluate_node(data, Condition(field="name", operator="contains", value="es")) is True

    # in
    assert matcher._evaluate_node(data, Condition(field="name", operator="in", value=["test", "demo"])) is True
    assert matcher._evaluate_node(data, Condition(field="age", operator="in", value=[20, 30])) is True


def test_operators_gte_lte(matcher):
    data = {"age": 18, "score": 95.5}

    # Test gte
    c1 = Condition(field="age", operator="gte", value=18)
    assert matcher._evaluate_node(data, c1) is True

    c2 = Condition(field="age", operator="gte", value=19)
    assert matcher._evaluate_node(data, c2) is False

    # Test lte
    c3 = Condition(field="score", operator="lte", value=95.5)
    assert matcher._evaluate_node(data, c3) is True

    c4 = Condition(field="score", operator="lte", value=90)
    assert matcher._evaluate_node(data, c4) is False


def test_logic_not(matcher):
    data = {"content": "hello world"}
    # NOT (content contains "bad") -> True
    c = Condition(field="content", operator="contains", value="bad")
    rule = RuleGroup(logic="NOT", conditions=[c])
    assert matcher._evaluate_node(data, rule) is True

    # NOT (content contains "hello") -> False
    c2 = Condition(field="content", operator="contains", value="hello")
    rule2 = RuleGroup(logic="NOT", conditions=[c2])
    assert matcher._evaluate_node(data, rule2) is False


def test_logic_not_multiple_conditions(matcher):
    # Verify that NOT only considers the first condition
    data = {"a": 1, "b": 2}
    c1 = Condition(field="a", operator="eq", value=1)  # True
    c2 = Condition(field="b", operator="eq", value=3)  # False

    # NOT (True, False) -> NOT True -> False (ignores second condition)
    rule = RuleGroup(logic="NOT", conditions=[c1, c2])
    assert matcher._evaluate_node(data, rule) is False

    # NOT (False, True) -> NOT False -> True
    rule2 = RuleGroup(logic="NOT", conditions=[c2, c1])
    assert matcher._evaluate_node(data, rule2) is True


def test_logic_xor(matcher):
    data = {"a": 1, "b": 2}
    c1 = Condition(field="a", operator="eq", value=1)  # True
    c2 = Condition(field="b", operator="eq", value=2)  # True
    c3 = Condition(field="b", operator="eq", value=3)  # False

    # True XOR True -> False
    rule1 = RuleGroup(logic="XOR", conditions=[c1, c2])
    assert matcher._evaluate_node(data, rule1) is False

    # True XOR False -> True
    rule2 = RuleGroup(logic="XOR", conditions=[c1, c3])
    assert matcher._evaluate_node(data, rule2) is True

    # False XOR False -> False
    rule3 = RuleGroup(logic="XOR", conditions=[c3, c3])
    assert matcher._evaluate_node(data, rule3) is False


def test_logic_nand(matcher):
    data = {"a": 1, "b": 2}
    c1 = Condition(field="a", operator="eq", value=1)  # True
    c2 = Condition(field="b", operator="eq", value=2)  # True
    c3 = Condition(field="b", operator="eq", value=3)  # False

    # NAND (True, True) -> False
    rule1 = RuleGroup(logic="NAND", conditions=[c1, c2])
    assert matcher._evaluate_node(data, rule1) is False

    # NAND (True, False) -> True
    rule2 = RuleGroup(logic="NAND", conditions=[c1, c3])
    assert matcher._evaluate_node(data, rule2) is True


def test_logic_nor(matcher):
    data = {"a": 1, "b": 2}
    c1 = Condition(field="a", operator="eq", value=1)  # True
    c2 = Condition(field="b", operator="eq", value=2)  # True
    c3 = Condition(field="b", operator="eq", value=3)  # False

    # NOR (True, True) -> False
    rule1 = RuleGroup(logic="NOR", conditions=[c1, c2])
    assert matcher._evaluate_node(data, rule1) is False

    # NOR (False, False) -> True
    rule2 = RuleGroup(logic="NOR", conditions=[c3, c3])
    assert matcher._evaluate_node(data, rule2) is True

    # NOR (True, False) -> False
    rule3 = RuleGroup(logic="NOR", conditions=[c1, c3])
    assert matcher._evaluate_node(data, rule3) is False


def test_logic_xnor(matcher):
    data = {"a": 1, "b": 2}
    c1 = Condition(field="a", operator="eq", value=1)  # True
    c2 = Condition(field="b", operator="eq", value=2)  # True
    c3 = Condition(field="b", operator="eq", value=3)  # False

    # XNOR (True, True) -> True
    rule1 = RuleGroup(logic="XNOR", conditions=[c1, c2])
    assert matcher._evaluate_node(data, rule1) is True

    # XNOR (True, False) -> False
    rule2 = RuleGroup(logic="XNOR", conditions=[c1, c3])
    assert matcher._evaluate_node(data, rule2) is False

    # XNOR (False, False) -> True
    rule3 = RuleGroup(logic="XNOR", conditions=[c3, c3])
    assert matcher._evaluate_node(data, rule3) is True


def test_match_rule(matcher):
    data = {"content": "spam message"}
    trigger = Condition(field="content", operator="contains", value="spam")
    rule = ReviewRule(
        id=1, name="test", enabled=True, priority=10, trigger=trigger, actions=[Action(type="delete", params={})]
    )

    assert matcher.match(data, rule) is True

    rule.enabled = False
    assert matcher.match(data, rule) is False
