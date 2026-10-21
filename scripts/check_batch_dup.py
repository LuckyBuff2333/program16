"""检查最近一次批量执行是否与多维表格有重复"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.db import get_db
from src.clients import feishu_client
from src.config import load_config

db = get_db()

# 1. 查最近一次批次执行
rows = db.execute("SELECT * FROM batch_executions ORDER BY id DESC LIMIT 1").fetchall()
if not rows:
    print("无批次执行记录")
    sys.exit(0)

r = dict(rows[0])
print(f"批次ID: {r.get('id')}")
print(f"执行时间: {r.get('created_at')}")
print(f"结果: {r.get('result_summary')}")

# 2. 获取这批执行的JIRA keys
details = db.execute("SELECT jira_key, status, result FROM batch_results WHERE batch_id=? ORDER BY id", (r['id'],)).fetchall()
executed_keys = []
for d in details:
    d = dict(d)
    executed_keys.append(d['jira_key'])
    print(f"  {d['jira_key']} - {d['status']}")

print(f"\n本次执行共 {len(executed_keys)} 条")

# 3. 拉取多维表格，检查是否有重复
print("\n--- 检查多维表格重复 ---")
cfg_bt = load_config().get("feishu_bitable", {})
app_token = cfg_bt.get("app_token", "")
table_id = cfg_bt.get("table_id", "")
bugid_field = cfg_bt.get("bugid_field", "jira号")

records = feishu_client.list_bitable_records(app_token, table_id)
print(f"多维表格总记录: {len(records)} 条")

# 构建表格中已有的key -> 记录映射
bitable_map = {}
for rec in records:
    fields = rec.get("fields", {})
    fv = fields.get(bugid_field, "")
    if isinstance(fv, list):
        fv = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in fv)
    elif isinstance(fv, dict):
        fv = fv.get("text", str(fv))
    jira_key = str(fv).strip()
    if jira_key:
        if jira_key not in bitable_map:
            bitable_map[jira_key] = []
        result_status = ""
        rs = fields.get("分析结果", "")
        if isinstance(rs, list):
            result_status = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in rs)
        elif isinstance(rs, dict):
            result_status = rs.get("text", str(rs))
        else:
            result_status = str(rs)
        review = ""
        rv = fields.get("人工审核结果", "")
        if isinstance(rv, list):
            review = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in rv)
        elif isinstance(rv, dict):
            review = rv.get("text", str(rv))
        else:
            review = str(rv)
        bitable_map[jira_key].append({"result": result_status.strip(), "review": review.strip()})

# 4. 检查重复
duplicates = []
for k in executed_keys:
    if k in bitable_map:
        duplicates.append((k, bitable_map[k]))

if duplicates:
    print(f"\n⚠️ 发现 {len(duplicates)} 条重复:")
    for k, recs in duplicates:
        for rec in recs:
            print(f"  {k}: 分析结果={rec['result']}, 人工审核={rec['review']}")
else:
    print(f"\n✅ 本次执行 {len(executed_keys)} 条与多维表格无重复")
