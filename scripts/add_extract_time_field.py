"""给触发时间_2表补上提取时间字段并回填"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.clients import feishu_client
from src.web.server import _get_trigger_time_table_cfg
from datetime import datetime
import httpx

app_token, table_ids = _get_trigger_time_table_cfg()
headers = feishu_client._bitable_headers()
tid2 = table_ids[1]
print(f"目标表: {tid2}")

# 1. 添加提取时间字段
url = f"{feishu_client._FEISHU_API}/bitable/v1/apps/{app_token}/tables/{tid2}/fields"
resp = httpx.post(url, headers=headers, json={"field_name": "提取时间", "type": 1}, timeout=15, verify=False)
data = resp.json()
print(f"添加字段: code={data.get('code')} msg={data.get('msg', '')}")

# 2. 为已有记录回填提取时间
records = feishu_client.list_bitable_records(app_token, tid2)
now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
update_batch = [{"record_id": r["record_id"], "fields": {"提取时间": now_str}} for r in records]
for i in range(0, len(update_batch), 500):
    batch = update_batch[i:i + 500]
    feishu_client.update_bitable_records(app_token, tid2, batch)
print(f"已回填 {len(update_batch)} 条记录的提取时间: {now_str}")
