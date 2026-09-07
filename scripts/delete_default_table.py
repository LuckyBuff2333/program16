"""删除云端 bitable 中的默认空数据表"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from src.clients.feishu_client import _bitable_headers, _FEISHU_API

app_token = "Nj7Cb8vt3ayGXSsXjS9c3aFPnfd"
default_table_id = "tblBkxdz6ldWtG0r"

headers = _bitable_headers()
url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables/{default_table_id}"
resp = httpx.delete(url, headers=headers, timeout=15, verify=False)
print(f"HTTP {resp.status_code}: {resp.text[:300]}")
data = resp.json()
if data.get("code") == 0:
    print("默认数据表已删除")
else:
    print(f"删除失败: {data.get('msg')}")
