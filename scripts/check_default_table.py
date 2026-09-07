"""查看数据表中的 10 条记录内容"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.clients import feishu_client

app_token = "Nj7Cb8vt3ayGXSsXjS9c3aFPnfd"
table_id = "tblBkxdz6ldWtG0r"

records = feishu_client.list_bitable_records(app_token, table_id)
print(f"共 {len(records)} 条记录:\n")
for i, rec in enumerate(records):
    fields = rec.get("fields", {})
    print(f"--- 记录 {i+1} ---")
    for k, v in fields.items():
        # 处理飞书富文本格式
        if isinstance(v, list):
            text = "".join(seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in v)
        else:
            text = str(v)
        print(f"  {k}: {text[:100]}")
    print()
