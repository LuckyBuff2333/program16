"""通过浏览器 Cookie 直接拉取飞书多维表格数据（无需 App 权限）"""
import json
import os
import sys
import httpx
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

APP_TOKEN = "HOARbsrB0aSViFs5AjNchSQ0nAf"
TABLE_ID = "tblM5keGYh2y0aSX"
VIEW_ID = "vewxmuI3le"
DOMAIN = "saic-gm.feishu.cn"
COOKIE = "passport_trace_id=7696425894004460567; _gcl_au=1.1.436211114.1791963795; landing_url=https://accounts.feishu.cn/accounts/page/login?redirect_uri=https%253A%252F%252Fsaic-gm.feishu.cn%252Fwiki%252FV48hwGZb3iEB1Akxb1Ycocolnwd%253Ffrom%253Dfrom_copylink&user_id=7696333722878037002&device_login_id=NzY5NjQyMTg4MTM0NzM2MTgwNQ%253D%253D&disposable_login_token=eu_nc%253Av2%253A1ff59e444adffe42ffa4edd59fc7e45a18559fef0eff336732f38b6fe04d6ca9&timestamp=1791963794&app_id=2&client_schema=x-feishu&pwd_less_login_auth=1; s_v_web_id=verify_mv7sz6u0_tt61DNQ7_ADAM_4hdr_BEXh_GxozMLCVdDfh; lang=zh; i18n_locale=zh; js_version=1; _csrf_token=06e32ed97ab196e674f03c354febe308e1e901b3-1791963811; __tea__ug__uid=7696425936921953826; et=45145be445674479745e574986893f9f; locale=zh-CN; ccm_cdn_host=//lf-package-cn.feishucdn.com/obj/feishu-static; _tea_utm_cache_8608=undefined; _tea_utm_cache_323044=undefined; bitable_tableId_viewId_history=%7B%22HOARbsrB0aSViFs5AjNchSQ0nAf%22%3A%7B%22tableId%22%3A%22tblM5keGYh2y0aSX%22%2C%22viewId%22%3A%22vewxmuI3le%22%7D%7D; _gid=GA1.2.1813564947.1792734724; _ga=GA1.1.842858246.1791963796; _ga_VPYRHN104D=GS2.1.s1792734724$o2$g1$t1792735120$j3$l0$h0; msToken=qPvfFS_fmS_qrYHM68t67YO_E6lmSzreCDc67W0fFluwH71ZcHVXNYK1wM8K7TK_G4nL4vWlKVfzLPVEhIZcTar0ocnCuyRBTr2Zoj4fIC8jiKBePhTvds6gOPJT0NY4yZ9J_rWlz0vD6aRSw0xpXAL_NYvvFB_-vN5tibKpBfK_; ssrLocalKey=11d4b9702606c41a4951595055384db6d7e0a14c4e079f252b2ab1158d27b208; swp_csrf_token=8319b9aa-81f9-4236-a298-e4b6ad9d50c5"


def _headers():
    return {
        "Cookie": COOKIE,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://{DOMAIN}/wiki/VSWFwwkLTiZC6QkeZY4csbwUnjd",
        "x-csrf-token": "8319b9aa-81f9-4236-a298-e4b6ad9d50c5",
        "Accept": "application/json",
    }


def _clean_field_value(val):
    if val is None:
        return ""
    if isinstance(val, list):
        if not val:
            return ""
        first = val[0]
        if isinstance(first, dict) and "text" in first:
            return "".join(seg.get("text", "") for seg in val)
        if isinstance(first, dict) and "name" in first:
            return ", ".join(p.get("name", p.get("en_name", "")) for p in val)
        if isinstance(first, dict) and "token" in first:
            return ", ".join(f.get("name", f.get("token", "")) for f in val)
        if isinstance(first, str):
            return ", ".join(val)
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, (int, float)) and val > 1000000000000:
        try:
            return datetime.fromtimestamp(val / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            pass
    if isinstance(val, dict):
        return val.get("value", json.dumps(val, ensure_ascii=False))
    return val


def fetch_all_records():
    endpoints = [
        f"https://{DOMAIN}/bitable/api/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records",
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records",
    ]
    for base_url in endpoints:
        print(f"  尝试: {base_url[:70]}...")
        all_items = []
        page_token = None
        try:
            while True:
                params = {"page_size": 500}
                if VIEW_ID:
                    params["view_id"] = VIEW_ID
                if page_token:
                    params["page_token"] = page_token
                resp = httpx.get(base_url, headers=_headers(), params=params,
                                 timeout=30, follow_redirects=True, verify=False)
                if resp.status_code != 200:
                    print(f"  HTTP {resp.status_code}")
                    break
                data = resp.json()
                if data.get("code", -1) != 0:
                    print(f"  code={data.get('code')}: {data.get('msg', '')}")
                    break
                items = data.get("data", {}).get("items", [])
                all_items.extend(items)
                print(f"  本页 {len(items)} 条, 累计 {len(all_items)} 条")
                if data.get("data", {}).get("has_more"):
                    page_token = data["data"].get("page_token")
                else:
                    return all_items
        except Exception as e:
            print(f"  异常: {e}")
    return []


def main():
    print("=" * 60)
    print(f"  app_token: {APP_TOKEN}")
    print(f"  table_id:  {TABLE_ID}")
    print("=" * 60)
    print("\n  拉取中...")
    records = fetch_all_records()
    if not records:
        print("\n  未获取到数据。Cookie 可能已过期，请重新获取。")
        return
    print(f"\n  共 {len(records)} 条")
    first = records[0].get("fields", {})
    print(f"\n  字段列表 ({len(first)} 个):")
    for i, (k, v) in enumerate(first.items()):
        t = type(v).__name__
        if isinstance(v, list) and v:
            t = f"list[{type(v[0]).__name__}]"
        print(f"  [{i+1:2d}] {k:30s} ({t})")
    cleaned = []
    for r in records:
        row = {"record_id": r.get("record_id", "")}
        for k, v in r.get("fields", {}).items():
            row[k] = _clean_field_value(v)
        cleaned.append(row)
    print(f"\n  前 3 条清洗后数据:")
    for i, rec in enumerate(cleaned[:3]):
        print(f"\n  -- 记录 {i+1} --")
        for k, v in rec.items():
            if k == "record_id":
                continue
            d = str(v)[:120]
            print(f"    {k:28s}: {d}")
    out = os.path.join(PROJECT_ROOT, "data", "bitable_export.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  已导出: {out} ({len(cleaned)} 条)")


if __name__ == "__main__":
    main()
