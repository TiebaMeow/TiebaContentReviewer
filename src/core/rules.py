from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Condition(BaseModel):
    """单个条件单元。

    定义了规则中的最小匹配单元，包含字段、操作符和目标值。

    Attributes:
        field: 匹配字段路径，支持点号分隔的嵌套字段，如 'content', 'author.level'。
        operator: 匹配操作符，支持 'contains', 'regex', 'eq', 'gt', 'lt', 'gte', 'lte', 'in'。
        value: 匹配的目标值，类型取决于操作符。
    """

    field: str
    operator: Literal["contains", "regex", "eq", "gt", "lt", "gte", "lte", "in"]
    value: Any


class RuleGroup(BaseModel):
    """规则组，支持逻辑组合。

    用于组合多个条件或子规则组，支持 AND, OR, NOT 等逻辑运算。

    Attributes:
        logic: 逻辑关系，如 'AND', 'OR', 'NOT' 等。
        conditions: 子条件列表，可以是 Condition 或嵌套的 RuleGroup。
    """

    logic: Literal["AND", "OR", "NOT", "XOR", "XNOR", "NAND", "NOR"]
    conditions: list[RuleNode]


# 递归类型
RuleNode = Condition | RuleGroup


class Action(BaseModel):
    """匹配命中后的动作。

    定义了当规则匹配成功时应执行的操作。

    Attributes:
        type: 动作类型，如 'delete', 'ban', 'notify'。
        params: 动作参数字典，具体内容取决于动作类型。
    """

    type: Literal["delete", "ban", "notify"]
    params: dict[str, Any] = Field(default_factory=dict)


class ReviewRule(BaseModel):
    """完整的审查规则实体。

    包含规则的元数据、触发条件逻辑树以及命中后的执行动作。

    Attributes:
        id: 规则唯一标识 ID。
        name: 规则名称。
        enabled: 是否启用该规则。
        priority: 规则优先级，数字越大越先执行。
        trigger: 规则触发条件的逻辑树根节点。
        actions: 规则命中后执行的动作列表。
    """

    id: int
    name: str
    enabled: bool
    priority: int
    trigger: RuleNode
    actions: list[Action]
