# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
from src.core.doc_generator import parse_conclusion
from src.core.filter import _extract_core_summary

report = """## 根因结论
- 🔴 ASR 识别丢失"小时"时间单位：最终识别文本为"设置为3"而非"设置为3小时"([L1366395](jump://L1366395))
- 🔴 DM 意图解析未触发设置操作：DM 收到缺单位文本后未触发 SetCLEAFridge RPC([L1366422](jump://L1366422))
- 🟡 TTS 回复与用户意图不匹配：TTS 回复"现在开着呢"
- 🔵 车辆控制链路功能正常：对照组链路完整成功"""

ai = parse_conclusion(report)
print("=== parse_conclusion 输出 ===")
for line in ai.splitlines():
    print(f"  | {line}")

print("\n=== 表格字段 (_extract_core_summary) ===")
table = _extract_core_summary(ai, 60)
print(f"  {table}")
print(f"  长度: {len(table)}")

print("\n=== rootcause 展示 (通用根因注入) ===")
rootcause = "符合需求"
display = f"{rootcause}（{_extract_core_summary(ai, 60)}）"
print(f"  {display}")
