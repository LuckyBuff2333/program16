"""清理原表中超出500条的多余记录"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.clients import feishu_client
from src.web.server import _get_trigger_time_table_cfg, _TRIGGER_TIME_TABLE_LIMIT

LIMIT = _TRIGGER_TIME_TABLE_LIMIT  # 500


def main():
    app_token, table_ids = _get_trigger_time_table_cfg()
    original_tid = table_ids[0]
    print(f"原表: {original_tid}")

    records = feishu_client.list_bitable_records(app_token, original_tid)
    print(f"原表记录数: {len(records)}")

    if len(records) <= LIMIT:
        print("无需清理")
        return

    # 删除超出 LIMIT 的记录
    overflow = records[LIMIT:]
    overflow_ids = [r["record_id"] for r in overflow]
    print(f"将删除 {len(overflow_ids)} 条多余记录（保留前 {LIMIT} 条）")

    feishu_client.batch_delete_records(app_token, original_tid, overflow_ids)
    print("删除完成")

    # 验证
    remaining = feishu_client.list_bitable_records(app_token, original_tid)
    print(f"验证: 原表现在有 {len(remaining)} 条记录")


if __name__ == "__main__":
    main()
