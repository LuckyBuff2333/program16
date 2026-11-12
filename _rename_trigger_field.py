# 一次性脚本：将云端所有触发时间子表的"触发时间"字段重命名为"问题发生时间"
import sys
sys.path.insert(0, ".")
from src.clients import feishu_client

APP_TOKEN = "Nj7Cb8vt3ayGXSsXjS9c3aFPnfd"
OLD_NAME = "触发时间"
NEW_NAME = "问题发生时间"

# 读取所有表 ID
import yaml
with open("config/config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
table_ids = cfg.get("feishu_bitable", {}).get("trigger_time_table_ids", [])
print(f"共 {len(table_ids)} 张表待处理")

for tid in table_ids:
    try:
        fields = feishu_client.list_bitable_fields(APP_TOKEN, tid)
        found = False
        for f in fields:
            fname = f.get("field_name", "")
            fid = f.get("field_id", "")
            if fname == OLD_NAME:
                print(f"  [{tid}] 发现旧字段 '{OLD_NAME}' (id={fid})，重命名中...")
                ok = feishu_client.rename_bitable_field(APP_TOKEN, tid, fid, NEW_NAME)
                print(f"  [{tid}] {'成功' if ok else '失败'}")
                found = True
            elif fname == NEW_NAME:
                print(f"  [{tid}] 已有新字段 '{NEW_NAME}'，跳过")
                found = True
        if not found:
            print(f"  [{tid}] 未找到 '{OLD_NAME}' 或 '{NEW_NAME}' 字段")
    except Exception as e:
        print(f"  [{tid}] 异常: {e}")

print("完成")
