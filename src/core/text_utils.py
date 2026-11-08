"""文本处理公共工具函数

集中管理跨模块复用的文本归一化逻辑，避免在 jira_client（文本提取路径）
与 server_legacy（OCR 提取路径）中重复实现，保证两条路径行为一致。
"""
import re


def normalize_datetime_text(text: str) -> str:
    """标准化非标准日期时间文本，提升提取兼容性

    处理三类常见异常格式：
    1. 破折号分隔符：YYYY/MM/DD——HH:MM → YYYY/MM/DD HH:MM（全角/半角破折号替换为空格）
    2. 冒号空格：HH: MM → HH:MM（去除时间冒号旁的空格）
    3. 分号冒号化：8；44 / 8;44 → 8:44（中文/半角分号在数字间替换为冒号）

    同时统一全角冒号（：→:）等中文输入法常见字符，供 OCR 与文本两条路径共享。
    """
    # 破折号/全角横线替换为空格（U+2013 en-dash, U+2014 em-dash, U+2015 horizontal bar, U+FF0D fullwidth hyphen-minus）
    text = re.sub(r'[\u2013\u2014\u2015\uFF0D]+', ' ', text)
    # 数字间的中文分号/半角分号替换为冒号（8；44 → 8:44, 8;44 → 8:44）
    text = re.sub(r'(\d)\s*[;；]\s*(\d)', r'\1:\2', text)
    # 全角冒号替换为半角冒号（支持中文输入法场景）
    # 中文标签后全角冒号 + 数字：加空格避免与独立时间正则冲突（测试时间：11：30 → 测试时间: 11:30）
    text = re.sub(r'([^\d])\s*[\uFF1A]\s*(\d)', r'\1: \2', text)
    # 数字间全角冒号（11：30 → 11:30）
    text = re.sub(r'(\d)\s*[\uFF1A]\s*(\d)', r'\1:\2', text)
    # 时间冒号旁空格去除（14: 57 → 14:57，不影响日期部分）
    text = re.sub(r'(\d)\s*:\s*(\d)', r'\1:\2', text)
    return text
