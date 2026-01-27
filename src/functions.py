from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.core.registry import rule_functions

if TYPE_CHECKING:
    from tiebameow.models.dto import CommentDTO, PostDTO, ThreadDTO

url_pattern = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")


@rule_functions.register("text_length")
def text_length(data: CommentDTO | PostDTO | ThreadDTO) -> int:
    """
    计算文本长度。

    Args:
        data: 待审查的数据对象。

    Returns:
        int: 文本长度。
    """
    return len(data.text)


@rule_functions.register("keyword_count")
def keyword_count(data: CommentDTO | PostDTO | ThreadDTO, keywords: list[str]) -> int:
    """
    计算文本中包含指定关键词及其出现的总次数。

    Args:
        data: 待审查的数据对象。
        keywords: 关键词列表。

    Returns:
        int: 关键词出现的总次数。
    """
    text = data.full_text
    count = 0
    for keyword in keywords:
        count += text.count(keyword)
    return count


@rule_functions.register("has_url")
def has_url(data: CommentDTO | PostDTO | ThreadDTO) -> bool:
    """
    检查文本中是否包含 URL 链接。

    Args:
        data: 待审查的数据对象。

    Returns:
        bool: 如果包含 URL 返回 True，否则返回 False。
    """

    return bool(url_pattern.search(data.full_text))
