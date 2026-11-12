# 测试：向触发时间表写入一条空值更新，看是否报 FieldNameNotFound
import sys
sys.path.insert(0, ".")
from src.clients import feishu_client
import yaml

with open("config/config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

app_token = cfg.get("feishu_bitable", {}).get("trigger_time_app_token", "")
table_ids = cfg.get("feishu_bitable", {}).get("trigger_time_table_ids", [])
tid = table_ids[0]
print(f"测试表: {tid}")

# 获取第一条记录
records = feishu_client.list_bitable_records(app_token, tid, page_size=1)
if not records:
    print("表为空")
    sys.exit(0)

rec_id = records[0].get("record_id", "")
print(f"测试记录: {rec_id}")

# 测试1：只写问题发生时间（空字符串）
test_payload = [{"record_id": rec_id, "fields": {"问题发生时间": ""}}]
try:
    result = feishu_client.update_bitable_records(app_token, tid, test_payload)
    print(f"测试1（空字符串）: 成功")
except Exception as e:
    print(f"测试1（空字符串）: 失败 - {e}")

# 测试2：只写问题发生时间（有值）
test_payload2 = [{"record_id": rec_id, "fields": {"问题发生时间": "2026-11-12 10:00:00"}}]
try:
    result = feishu_client.update_bitable_records(app_token, tid, test_payload2)
    print(f"测试2（有值）: 成功")
except Exception as e:
    print(f"测试2（有值）: 失败 - {e}")

# 测试3：写扩展字段
test_payload3 = [{"record_id": rec_id, "fields": {
    "问题发生时间": "2026-11-12 10:00:00",
    "时间来源": "测试",
    "参考时间": "",
    "时间差秒": "",
    "窗口命中": "无参考",
    "时间状态": "无参考",
    "时间精度": "second"
}}]
try:
    result = feishu_client.update_bitable_records(app_token, tid, test_payload3)
    print(f"测试3（全字段）: 成功")
except Exception as e:
    print(f"测试3（全字段）: 失败 - {e}")
