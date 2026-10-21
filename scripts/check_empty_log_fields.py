"""查看时间过滤后日志为空的记录的详细字段"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.clients import feishu_client
from src.config import load_config

cfg = load_config().get("feishu_bitable", {})
recs = feishu_client.list_bitable_records(cfg["app_token"], cfg["table_id"])

def _t(v):
    if isinstance(v, list):
        return "".join(i.get("text", "") if isinstance(i, dict) else str(i) for i in v)
    if isinstance(v, dict):
        return v.get("text", str(v))
    return str(v)

# 找匹配记录
count = 0
for r in recs:
    f = r.get("fields", {})
    res = _t(f.get("分析结果", ""))
    if res != "失败":
        continue
    err = _t(f.get("错误信息", ""))
    if "时间过滤后日志为空" not in err:
        continue
    count += 1
    if count == 1:
        print("=== 第一条匹配记录的所有字段 ===")
        for k in sorted(f.keys()):
            val = _t(f[k])
            display = val[:100] if val else "(empty)"
            print(f"  [{k}]: {display}")

print(f"\n总匹配: {count} 条")

# 也看看这些记录的触发时间字段是否有值
has_time = 0
no_time = 0
for r in recs:
    f = r.get("fields", {})
    res = _t(f.get("分析结果", ""))
    if res != "失败":
        continue
    err = _t(f.get("错误信息", ""))
    if "时间过滤后日志为空" not in err:
        continue
    tt = _t(f.get("触发时间", ""))
    if tt:
        has_time += 1
    else:
        no_time += 1

print(f"\n有触发时间: {has_time}, 无触发时间: {no_time}")
