"""对比云端和本地触发时间数据，找出本地多余条目并分析一致性"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import csv
import yaml
from datetime import datetime

# 1. 加载本地 CSV 全量数据
data_dir = os.path.join(os.path.dirname(__file__), "data")
local_all = {}  # {jira号: 触发时间}（包含空值）
local_by_file = {}  # {filepath: [{jira号, 触发时间, 提取时间}]}
for root, _dirs, files in os.walk(data_dir):
    for f in sorted(files):
        if not f.startswith("trigger_times_") or not f.endswith(".csv"):
            continue
        path = os.path.join(root, f)
        rows = []
        with open(path, "r", encoding="utf-8-sig") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                jira = (row.get("jira号") or "").strip()
                tt = (row.get("触发时间") or "").strip()
                et = (row.get("提取时间") or "").strip()
                if jira:
                    local_all[jira] = tt
                    rows.append({"jira号": jira, "触发时间": tt, "提取时间": et})
        local_by_file[path] = rows

# 2. 加载云端数据（通过 app 模块）
from src.clients import feishu_client
with open("config/config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
feishu_cfg = cfg.get("feishu_bitable", {})
app_token = feishu_cfg.get("trigger_time_app_token", "")
table_ids = feishu_cfg.get("trigger_time_table_ids", [])

# 设置 feishu_client 的 token
feishu_cfg_full = cfg.get("feishu_bitable", {})
user_token = feishu_cfg_full.get("user_access_token", "")
if user_token:
    feishu_client._doc_token_cache = user_token

cloud_all = {}  # {jira号: 触发时间}
cloud_keys = set()
for tid in table_ids:
    try:
        records = feishu_client.list_bitable_records(app_token, tid)
        for rec in records:
            fields = rec.get("fields", {})
            # bitable text 字段可能是 list 或 str
            def _bt(val):
                if isinstance(val, list):
                    return "".join(seg.get("text", "") for seg in val if isinstance(seg, dict)).strip()
                return str(val).strip() if val else ""
            jira_no = _bt(fields.get("jira号", ""))
            tt = _bt(fields.get("触发时间", ""))
            if jira_no:
                cloud_keys.add(jira_no)
                if tt:
                    cloud_all[jira_no] = tt
    except Exception as e:
        print(f"[ERROR] 加载表 {tid} 失败: {e}")

# 3. 对比分析
local_with_time = {k: v for k, v in local_all.items() if v}
local_without_time = {k: v for k, v in local_all.items() if not v}
cloud_with_time = cloud_all

# 本地有但云端没有的
local_only_with_time = {k: v for k, v in local_with_time.items() if k not in cloud_keys}
local_only_without_time = {k for k in local_without_time if k not in cloud_keys}

# 两者都有的
both_keys = set(local_all.keys()) & cloud_keys

# 两者都有且都有触发时间的 -> 比较值
both_with_time = {k for k in both_keys if k in local_with_time and k in cloud_with_time}
time_match = 0
time_mismatch = 0
mismatches = []
for k in both_with_time:
    lt = local_with_time[k]
    ct = cloud_with_time[k]
    if lt == ct:
        time_match += 1
    else:
        time_mismatch += 1
        mismatches.append((k, lt, ct))

# 4. 打印报告
print("=" * 60)
print("触发时间数据对比报告")
print("=" * 60)
print(f"\n【云端】: {len(cloud_keys)} 条记录, {len(cloud_with_time)} 条有触发时间")
print(f"【本地】: {len(local_all)} 条记录, {len(local_with_time)} 条有触发时间, {len(local_without_time)} 条空标记")
print(f"\n差异 = {len(local_all) - len(cloud_keys)} 条")

print(f"\n--- 本地有但云端没有 ---")
print(f"  有触发时间: {len(local_only_with_time)} 条")
print(f"  空标记:     {len(local_only_without_time)} 条")
print(f"  合计需删除: {len(local_only_with_time) + len(local_only_without_time)} 条")

print(f"\n--- 两者共有: {len(both_keys)} 条 ---")
print(f"  两者都有触发时间: {len(both_with_time)} 条")
print(f"    时间一致: {time_match} 条")
print(f"    时间不一致: {time_mismatch} 条")
if mismatches:
    print(f"\n  不一致明细 (最多显示20条):")
    for k, lt, ct in sorted(mismatches)[:20]:
        print(f"    {k}: 本地={lt} | 云端={ct}")

# 云端有但本地没有
cloud_only = cloud_keys - set(local_all.keys())
print(f"\n--- 云端有但本地没有: {len(cloud_only)} 条 ---")

# 5. 按文件统计需删除的行
print(f"\n--- 各 CSV 文件统计 ---")
for path, rows in sorted(local_by_file.items()):
    fname = os.path.relpath(path, os.path.dirname(__file__))
    total = len(rows)
    to_delete = sum(1 for r in rows if r["jira号"] not in cloud_keys)
    keep = total - to_delete
    print(f"  {fname}: 总 {total} 条, 需删除 {to_delete} 条, 保留 {keep} 条")

print(f"\n{'=' * 60}")
print("总结:")
print(f"  本地比云端多 {len(local_only_with_time) + len(local_only_without_time)} 条")
print(f"  时间不一致 {time_mismatch} 条（本地旧提取方式可能不准确）")
print(f"{'=' * 60}")

