from __future__ import annotations

import functools
import re
from typing import Any

from src.core.rules import Condition, ReviewRule, RuleGroup, RuleNode


class RuleMatcher:
    """规则匹配引擎。

    负责将输入数据与审查规则进行匹配。支持复杂的逻辑组合（AND, OR, NOT 等）
    和嵌套字段访问。
    """

    def match(self, data: dict[str, Any], rule: ReviewRule) -> bool:
        """判断数据是否命中规则。

        Args:
            data: 待审查的数据字典。
            rule: 审查规则实体。

        Returns:
            bool: 如果数据命中规则返回 True，否则返回 False。
        """
        if not rule.enabled:
            return False
        return self._evaluate_node(data, rule.trigger)

    def _evaluate_node(self, data: dict[str, Any], node: RuleNode) -> bool:
        """递归评估规则节点。

        Args:
            data: 待审查的数据。
            node: 当前评估的规则节点（条件或规则组）。

        Returns:
            bool: 节点评估结果。
        """
        if isinstance(node, RuleGroup):
            if not node.conditions:
                return False

            if node.logic == "AND":
                return all(self._evaluate_node(data, child) for child in node.conditions)
            elif node.logic == "OR":
                return any(self._evaluate_node(data, child) for child in node.conditions)
            elif node.logic == "NOT":
                # NOT 逻辑只应用于第一个子条件
                return not self._evaluate_node(data, node.conditions[0])
            elif node.logic == "XOR":
                # 异或：奇数个真为真
                return sum(self._evaluate_node(data, child) for child in node.conditions) % 2 == 1
            elif node.logic == "XNOR":
                # 同或：偶数个真为真 (即 XOR 取反)
                return sum(self._evaluate_node(data, child) for child in node.conditions) % 2 == 0
            elif node.logic == "NAND":
                # 与非：NOT (AND)
                return not all(self._evaluate_node(data, child) for child in node.conditions)
            elif node.logic == "NOR":
                # 或非：NOT (OR)
                return not any(self._evaluate_node(data, child) for child in node.conditions)

            return False  # type: ignore[unreachable]

        else:
            return self._evaluate_condition(data, node)

    def _evaluate_condition(self, data: dict[str, Any], condition: Condition) -> bool:
        # 支持嵌套字段访问，例如 'author.level'
        field_value = self._get_field_value(data, condition.field)

        if field_value is None:
            return False

        op = condition.operator
        val = condition.value

        # 统一转为字符串处理 contains 和 regex，避免类型错误
        str_field_value = str(field_value)
        str_val = str(val)

        if op == "contains":
            return str_val in str_field_value
        elif op == "regex":
            try:
                if re.search(str_val, str_field_value):
                    return True
                return False
            except re.error:
                # 正则错误视为不匹配
                return False
        elif op == "eq":
            return bool(field_value == val)
        elif op == "gt":
            try:
                return float(field_value) > float(val)
            except (ValueError, TypeError):
                return False
        elif op == "lt":
            try:
                return float(field_value) < float(val)
            except (ValueError, TypeError):
                return False
        elif op == "gte":
            try:
                return float(field_value) >= float(val)
            except (ValueError, TypeError):
                return False
        elif op == "lte":
            try:
                return float(field_value) <= float(val)
            except (ValueError, TypeError):
                return False
        elif op == "in":
            return bool(field_value in val) if isinstance(val, list | tuple) else False

        return False  # type: ignore[unreachable]

    def _get_field_value(self, data: dict[str, Any] | Any, field_path: str) -> Any:
        """获取嵌套字段的值。

        支持使用点号分隔的路径访问嵌套字典或对象属性。

        Args:
            data: 数据源（字典或对象）。
            field_path: 字段路径，如 'author.level'。

        Returns:
            Any: 字段值，如果路径不存在或中间节点为 None 则返回 None。
        """
        keys = _split_path(field_path)
        val: Any = data
        for key in keys:
            if isinstance(val, dict):
                val = val.get(key)
            else:
                # 尝试作为对象属性访问
                val = getattr(val, key, None)

            if val is None:
                return None
        return val


@functools.lru_cache(maxsize=1024)
def _split_path(path: str) -> list[str]:
    """分割字段路径并缓存结果。

    Args:
        path: 点号分隔的字段路径字符串。

    Returns:
        list[str]: 分割后的路径部分列表。
    """
    return path.split(".")
