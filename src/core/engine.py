from __future__ import annotations

import functools
import re
from typing import TYPE_CHECKING, Any

from tiebameow.schemas.rules import Condition, FunctionCall, LogicType, OperatorType, ReviewRule, RuleGroup, RuleNode

from src.core.provider import FunctionProvider, LocalFunctionProvider

if TYPE_CHECKING:
    from tiebameow.models.dto import CommentDTO, PostDTO, ThreadDTO


class RuleMatcher:
    """规则匹配引擎。

    负责将输入数据与审查规则进行匹配。支持复杂的逻辑组合（AND, OR, NOT 等）
    和嵌套字段访问。
    """

    def __init__(self, provider: FunctionProvider | None = None) -> None:
        self._regex_cache: dict[str, re.Pattern[str]] = {}
        self._provider = provider or LocalFunctionProvider()

    async def match_all(
        self,
        data: ThreadDTO | PostDTO | CommentDTO,
        rules: list[ReviewRule],
    ) -> tuple[list[ReviewRule], dict[str, Any]]:
        """批量匹配规则。

        按顺序执行规则。

        Args:
            data: 待审查的数据。
            rules: 规则列表。

        Returns:
            tuple[list[ReviewRule], dict[str, Any]]: 命中的规则列表和函数调用上下文。
        """
        matched: list[ReviewRule] = []
        context: dict[str, Any] = {}

        for rule in rules:
            if await self.match(data, rule, context):
                matched.append(rule)
                if rule.block:
                    break
        return matched, context

    async def match(
        self,
        data: ThreadDTO | PostDTO | CommentDTO,
        rule: ReviewRule,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """判断数据是否命中规则。

        Args:
            data: 待审查的数据字典。
            rule: 审查规则实体。
            context: 函数调用上下文字典。

        Returns:
            bool: 如果数据命中规则返回 True，否则返回 False。
        """
        if not rule.enabled:
            return False
        return await self._evaluate_node(data, rule.trigger, context)

    async def _evaluate_node(
        self,
        data: ThreadDTO | PostDTO | CommentDTO,
        node: RuleNode,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """递归评估规则节点。

        Args:
            data: 待审查的数据。
            node: 当前评估的规则节点（条件或规则组）。
            context: 函数调用上下文字典。

        Returns:
            bool: 节点评估结果。
        """
        if isinstance(node, RuleGroup):
            if not node.conditions:
                return False

            if node.logic == LogicType.AND:
                for child in node.conditions:
                    if not await self._evaluate_node(data, child, context):
                        return False
                return True
            elif node.logic == LogicType.OR:
                for child in node.conditions:
                    if await self._evaluate_node(data, child, context):
                        return True
                return False
            elif node.logic == LogicType.NOT:
                # NOT 逻辑只应用于第一个子条件
                return not await self._evaluate_node(data, node.conditions[0], context)

            return False  # type: ignore[unreachable]

        else:
            return await self._evaluate_condition(data, node, context)

    async def _evaluate_condition(
        self,
        data: ThreadDTO | PostDTO | CommentDTO,
        condition: Condition,
        context: dict[str, Any] | None = None,
    ) -> bool:
        # 支持嵌套字段访问，例如 'author.level'
        # 或者 FunctionCall 计算字段值
        if isinstance(condition.field, FunctionCall):
            field_value = await self._execute_function_call(data, condition.field, context)
        else:
            field_value = self._get_field_value(data, condition.field)

        if field_value is None:
            return False

        op = condition.operator
        val = condition.value

        # 统一转为字符串处理 contains 和 regex，避免类型错误
        str_field_value = str(field_value)
        str_val = str(val)

        match op:
            case OperatorType.CONTAINS:
                return str_val in str_field_value
            case OperatorType.NOT_CONTAINS:
                return str_val not in str_field_value
            case OperatorType.REGEX:
                try:
                    pattern = self._get_compiled_regex(str_val)
                    if pattern.search(str_field_value):
                        return True
                    return False
                except re.error:
                    # 正则错误视为不匹配
                    return False
            case OperatorType.NOT_REGEX:
                try:
                    pattern = self._get_compiled_regex(str_val)
                    if pattern.search(str_field_value):
                        return False
                    return True
                except re.error:
                    # 正则错误则视为真
                    return True
            case OperatorType.EQ:
                return bool(field_value == val)
            case OperatorType.NEQ:
                return bool(field_value != val)
            case OperatorType.GT:
                try:
                    return bool(field_value > val)
                except TypeError:
                    return False
            case OperatorType.LT:
                try:
                    return bool(field_value < val)
                except TypeError:
                    return False
            case OperatorType.GTE:
                try:
                    return bool(field_value >= val)
                except TypeError:
                    return False
            case OperatorType.LTE:
                try:
                    return bool(field_value <= val)
                except TypeError:
                    return False
            case OperatorType.IN:
                try:
                    return bool(field_value in val)
                except TypeError:
                    return False
            case OperatorType.NOT_IN:
                try:
                    return bool(field_value not in val)
                except TypeError:
                    return False
            case _:
                return False  # type: ignore[unreachable]

    async def _execute_function_call(
        self,
        data: ThreadDTO | PostDTO | CommentDTO,
        func_call: FunctionCall,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """执行 FunctionCall 获取值。"""
        result = await self._provider.execute(func_call.name, data, func_call.args, func_call.kwargs)
        if context is not None:
            context[func_call.name] = result
        return result

    def _get_compiled_regex(self, pattern: str) -> re.Pattern[str]:
        """获取编译后的正则表达式对象（带缓存）。"""
        if pattern not in self._regex_cache:
            self._regex_cache[pattern] = re.compile(pattern)
        return self._regex_cache[pattern]

    def _get_field_value(self, data: ThreadDTO | PostDTO | CommentDTO, field_path: str) -> Any:
        """获取嵌套字段的值。

        支持使用点号分隔的路径访问嵌套字典或对象属性。
        如路径为 "self" 则返回数据对象本身。

        Args:
            data: 数据源（字典或对象）。
            field_path: 字段路径，如 'author.level'。

        Returns:
            Any: 字段值，如果路径不存在或中间节点为 None 则返回 None。
        """
        if field_path == "self":
            return data
        keys = _split_path(field_path)
        val: Any = data
        for key in keys:
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
