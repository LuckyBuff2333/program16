# -*- coding: utf-8 -*-
import re

# 新正则
_OCR_TIME_FULL_RE = re.compile(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2}[\s.]?\d{1,2}[.:]\d{2}(?:[.:]\d{2})?)')

# 新的 normalize 函数
def _normalize_ocr_time(text):
    text = re.sub(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})\.(\d{1,2}[.:]\d{2})', r'\1 \2', text)
    text = re.sub(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})(\d{1,2}[.:]\d{2})', r'\1 \2', text)
    return re.sub(r'(\d{1,2})\.(\d{2})(?:\.(\d{2}))?', lambda m: f"{m.group(1)}:{m.group(2)}" + (f":{m.group(3)}" if m.group(3) else ""), text)

# 测试用例
tests = [
    "2026-01-09 14:02",      # 标准格式
    "2026-01-0914:02",       # 无分隔符
    "2026-01-09.14:02",      # 点号分隔
    "2026/01/09 14:02:30",   # 斜杠+秒
    "2026-1-9 14:02",        # 单位数日月
    "10.26.39",              # 仅时间点号
]

print("正则匹配测试:")
for t in tests:
    m = _OCR_TIME_FULL_RE.search(t)
    result = m.group(1) if m else "NO MATCH"
    print(f"  {t!r:30s} -> {result!r}")

print("\n规范化测试:")
for t in tests:
    normalized = _normalize_ocr_time(t)
    print(f"  {t!r:30s} -> {normalized!r}")
