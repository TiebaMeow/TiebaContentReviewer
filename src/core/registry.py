from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from tiebameow.models.dto import CommentDTO, PostDTO, ThreadDTO

type ReviewData = ThreadDTO | PostDTO | CommentDTO
type RuleFunction = Callable[..., Any | Awaitable[Any]]


class FunctionRegistry:
    """规则函数注册表。

    用于管理能够在规则引擎中调用的自定义函数。
    """

    def __init__(self) -> None:
        self._functions: dict[str, RuleFunction] = {}

    def register(self, name: str | None = None) -> Callable[[RuleFunction], RuleFunction]:
        """注册一个规则函数。

        Args:
            name: 函数名称，默认使用函数名。
        """

        def decorator(func: RuleFunction) -> RuleFunction:
            func_name = name or func.__name__
            if func_name in self._functions:
                raise ValueError(f"Function {func_name} already registered.")
            self._functions[func_name] = func
            return func

        return decorator

    def get_function(self, name: str) -> RuleFunction | None:
        """获取已注册的函数。"""
        return self._functions.get(name)

    def clear(self) -> None:
        """清空注册表。"""
        self._functions.clear()


rule_functions = FunctionRegistry()
