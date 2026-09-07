"""查询知识库 wiki space 的节点结构"""
import httpx
import re
import json
import sys
sys.path.insert(0, ".")
from src.clients import feishu_client

wiki_token = "VSWFwwkLTiZC6QkeZY4csbwUnjd"

# 方式1: user_access_token
print("=== 方式1: user_access_token ===")
token = feishu_client._get_doc_token()
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
url = f"{feishu_client._FEISHU_API}/wiki/v2/spaces/get_node?token={wiki_token}"
resp = httpx.get(url, headers=headers, timeout=15, verify=False)
print(f"Status: {resp.status_code}, code: {resp.json().get('code')}")

# 方式2: cookie 访问 wiki 页面提取 space_id
print("\n=== 方式2: Cookie 访问 Wiki 页面 ===")
cfg = feishu_client._get_bitable_cfg()
domain = cfg.get("domain", "feishu.cn")
page_url = f"https://{domain}/wiki/{wiki_token}"
headers2 = feishu_client._cookie_headers()
resp2 = httpx.get(page_url, headers=headers2, timeout=30, follow_redirects=True, verify=False)
print(f"Status: {resp2.status_code}, Final URL: {resp2.url}")
text = resp2.text
print(f"HTML length: {len(text)}")

# 提取 space_id
patterns = [
    (r'"space_id"\s*:\s*"(\d+)"', "space_id json"),
    (r'"spaceId"\s*:\s*"?(\d+)"?', "spaceId json"),
    (r'space_id=(\d+)', "space_id param"),
    (r'spaceId=(\d+)', "spaceId param"),
    (r'/spaces/(\d+)', "spaces path"),
]
found = False
for pat, name in patterns:
    m = re.search(pat, text)
    if m:
        print(f"Found [{name}]: {m.group(1)}")
        found = True

if not found:
    # 搜索包含 space 或 wiki 的 script
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', text, re.S)
    for i, s in enumerate(scripts):
        if len(s) > 100 and ("space" in s.lower() or "wiki" in s.lower()):
            print(f"\nScript {i} (len={len(s)}):")
            print(s[:1000])
            print("...")
            break

# 方式3: 尝试用 tenant_access_token 列出 spaces
print("\n=== 方式3: tenant_access_token 列出 spaces ===")
tenant_token = feishu_client.get_tenant_access_token()
headers3 = {"Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}
url3 = f"{feishu_client._FEISHU_API}/wiki/v2/spaces"
resp3 = httpx.get(url3, headers=headers3, timeout=15, verify=False)
data3 = resp3.json()
print(json.dumps(data3, indent=2, ensure_ascii=False))
