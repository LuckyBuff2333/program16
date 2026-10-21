"""统计最近两天多维表格中分析失败且包含"时间过滤后日志为空"的记录，分析其触发时间来源"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.clients import feishu_client
from src.config import load_config
from collections import Counter

cfg_bt = load_config().get("feishu_bitable", {})
app_token = cfg_bt.get("app_token", "")
table_id = cfg_bt.get("table_id", "")
bugid_field = cfg_bt.get("bugid_field", "jira号")

def _text(val):
    """提取文本字段的纯文本"""
    if isinstance(val, list):
        return "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in val)
    elif isinstance(val, dict):
        return val.get("text", str(val))
    return str(val).strip()

print("正在拉取多维表格记录...")
records = feishu_client.list_bitable_records(app_token, table_id)
print(f"总记录: {len(records)} 条")

# 筛选：分析失败 + 人工审核包含"时间过滤后日志为空"
from datetime import datetime, timedelta
now = datetime.now()
two_days_ago = now - timedelta(days=2)

matched = []
for rec in records:
    fields = rec.get("fields", {})
    result = _text(fields.get("分析结果", ""))
    review = _text(fields.get("人工审核结果", ""))
    if result != "失败":
        continue
    if "时间过滤后日志为空" not in review:
        continue
    jira_key = _text(fields.get(bugid_field, ""))
    trigger_time = _text(fields.get("触发时间", ""))
    trigger_source = _text(fields.get("触发来源", ""))
    # 尝试获取创建时间来判断是否是最近两天的
    created = _text(fields.get("创建时间", "")) or _text(fields.get("执行时间", ""))
    matched.append({
        "jira_key": jira_key,
        "trigger_time": trigger_time,
        "trigger_source": trigger_source,
        "review": review,
        "created": created,
        "fields": fields,
    })

print(f"\n匹配记录（分析失败 + 时间过滤后日志为空）: {len(matched)} 条")
print(f"{'='*80}")

# 统计触发时间来源
source_counter = Counter()
for m in matched:
    src = m["trigger_source"] or "(未记录)"
    source_counter[src] += 1

print(f"\n--- 触发来源分布 ---")
for src, cnt in source_counter.most_common():
    print(f"  {src}: {cnt} 条")

# 展示每条记录的详细信息
print(f"\n--- 详细记录（前30条）---")
for i, m in enumerate(matched[:30]):
    print(f"\n[{i+1}] {m['jira_key']}")
    print(f"    触发时间: {m['trigger_time']}")
    print(f"    触发来源: {m['trigger_source']}")
    print(f"    人工审核: {m['review'][:80]}")

# 查看所有可用字段名
if matched:
    print(f"\n--- 可用字段列表 ---")
    sample_fields = matched[0]["fields"]
    for fname in sorted(sample_fields.keys()):
        val = sample_fields[fname]
        print(f"  {fname}: {_text(val)[:60]}")
