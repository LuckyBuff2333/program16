"""检查云端 bitable 中所有数据表及其记录数"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.clients import feishu_client
import httpx

cfg = load_config().get("feishu_bitable", {})
app_token = cfg.get("trigger_time_app_token", "")
print(f"app_token: {app_token}")

# 列出所有数据表
from src.clients.feishu_client import _bitable_headers, _FEISHU_API
headers = _bitable_headers()
url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables"
resp = httpx.get(url, headers=headers, timeout=15, verify=False)
data = resp.json()
tables = data.get("data", {}).get("items", [])
print(f"\n共 {len(tables)} 张表:")

for t in tables:
    name = t.get("name", "")
    tid = t.get("table_id", "")
    # 查每张表的记录数
    rec_url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables/{tid}/records?page_size=1"
    rec_resp = httpx.get(rec_url, headers=headers, timeout=15, verify=False)
    rec_data = rec_resp.json()
    total = rec_data.get("data", {}).get("total", 0)
    print(f"  [{name}] table_id={tid}, 记录数={total}")
