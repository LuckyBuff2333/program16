"""将现有触发时间表按 500 条拆分为多表（保留原表前500条，多余搬新表）"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.clients import feishu_client
from src.web.server import (
    _get_trigger_time_table_cfg, _bitable_text,
    _TRIGGER_TIME_TABLE_LIMIT, _update_config_table_ids
)
import src.config as _cfg_module

LIMIT = _TRIGGER_TIME_TABLE_LIMIT  # 500


def main():
    app_token, table_ids = _get_trigger_time_table_cfg()
    original_tid = table_ids[0]
    print(f"原始表: {original_tid}")

    # 读取所有记录
    records = feishu_client.list_bitable_records(app_token, original_tid)
    print(f"原始记录数: {len(records)}")

    if len(records) <= LIMIT:
        print(f"记录数 <= {LIMIT}，无需拆分")
        _update_config_table_ids(app_token, table_ids)
        print("已将 config 更新为 table_ids 格式")
        return

    # 提取有效数据（保持顺序）
    data = []
    for rec in records:
        fields = rec.get("fields", {})
        jira = _bitable_text(fields.get("jira号", ""))
        tt = _bitable_text(fields.get("触发时间", ""))
        if jira and tt:
            data.append({"jira号": jira, "触发时间": tt})
    print(f"有效数据: {len(data)} 条")

    new_table_ids = [original_tid]  # 第一块保留在原表（已有数据，不用重写）
    first_chunk_size = min(LIMIT, len(data))
    print(f"  触发时间（原表）: 保留前 {first_chunk_size} 条")

    # 多余的记录拆到新表
    overflow = data[LIMIT:]
    if overflow:
        chunk_count = (len(overflow) + LIMIT - 1) // LIMIT
        for i in range(chunk_count):
            chunk = overflow[i * LIMIT: (i + 1) * LIMIT]
            table_name = f"触发时间_{i + 2}"
            fields_def = [
                {"field_name": "jira号", "type": 1},
                {"field_name": "触发时间", "type": 1},
            ]
            tid = feishu_client.create_bitable_table(app_token, table_name, fields_def)
            print(f"  已创建子表: {table_name} -> {tid}")

            # 分批写入
            for batch_start in range(0, len(chunk), 500):
                batch = chunk[batch_start:batch_start + 500]
                batch_records = [{"fields": d} for d in batch]
                feishu_client.batch_create_records(app_token, tid, batch_records)
            print(f"  {table_name}: 写入 {len(chunk)} 条")
            new_table_ids.append(tid)

    # 更新 config
    _update_config_table_ids(app_token, new_table_ids)
    print(f"\n拆分完成！")
    print(f"共 {len(new_table_ids)} 个表: {new_table_ids}")

    # 验证
    _cfg_module._CONFIG = None
    total = 0
    for tid in new_table_ids:
        recs = feishu_client.list_bitable_records(app_token, tid)
        print(f"  验证 {tid}: {len(recs)} 条")
        total += len(recs)
    print(f"总记录数: {total}")


if __name__ == "__main__":
    main()
