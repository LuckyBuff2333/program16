"""查询 VCU-553054 在数据沉淀表中的记录"""
from src.clients import feishu_client

app = "HOARbsrB0aSViFs5AjNchSQ0nAf"
tbl = "tblM5keGYh2y0aSX"

# 用 jira号 contains 过滤
fo = {"conjunction": "and", "conditions": [
    {"field_name": "jira号", "operator": "contains", "value": ["VCU-553054"]}
]}
recs = feishu_client.search_bitable_records(app, tbl, filter_obj=fo, timeout=15)
print(f"VCU-553054 共 {len(recs)} 条记录:")
for r in recs:
    f = r.get("fields", {})
    print(f"  record_id={r.get('record_id', '')}")
    print(f"  jira号: {f.get('jira号', '')}")
    print(f"  分析结果: {f.get('分析结果', '')}")
    print(f"  分析开始时间: {f.get('分析开始时间', '')}")
    print(f"  触发来源: {f.get('触发来源', '')}")
    print(f"  错误分类: {f.get('错误分类', '')}")
    print(f"  错误信息: {(f.get('错误信息', '') or '')[:100]}")
    print(f"  人工审核结果: {f.get('人工审核结果', '')}")
    print()
