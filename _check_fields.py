# 检查所有触发时间表的字段列表，看哪些字段缺失
import sys
sys.path.insert(0, ".")
from src.clients import feishu_client

APP_TOKEN = "Nj7Cb8vt3ayGXSsXjS9c3aFPnfd"
EXPECTED_FIELDS = ["问题发生时间", "时间来源", "参考时间", "时间差秒", "窗口命中", "时间状态", "时间精度", "备注", "jira号", "提取时间"]

import yaml
with open("config/config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
table_ids = cfg.get("feishu_bitable", {}).get("trigger_time_table_ids", [])

missing_report = []
for tid in table_ids[:3]:  # 先查前3张表
    try:
        fields = feishu_client.list_bitable_fields(APP_TOKEN, tid)
        existing = {f.get("field_name", "") for f in fields}
        missing = [f for f in EXPECTED_FIELDS if f not in existing]
        print(f"[{tid}] 现有字段: {sorted(existing)}")
        if missing:
            print(f"[{tid}] 缺失字段: {missing}")
            missing_report.append((tid, missing))
        else:
            print(f"[{tid}] 字段完整")
    except Exception as e:
        print(f"[{tid}] 异常: {e}")
