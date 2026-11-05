"""版本号过滤工具：中文版本号不计入问题排查/每日播报/待办。"""
import re

_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")


def is_chinese_version(value) -> bool:
    """版本号中只要包含中文字符，就视为中文版本。"""
    return bool(_CHINESE_RE.search(str(value or "")))
