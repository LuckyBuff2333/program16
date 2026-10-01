# -*- coding: utf-8 -*-
"""从 Excel 导入触发时间数据到云端触发时间_1 和触发时间_2"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import openpyxl
from datetime import datetime
from src.clients import feishu_client
from src.web.server import (
    _get_trigger_time_table_cfg, _load_cloud_trigger_cache,
    _create_trigger_time_subtable, _update_config_table_ids,
    _TRIGGER_TIME_TABLE_LIMIT
)

XLSX_PATH = os.path.join(os.path.dirname(__file__), "..", "触发时间修复.xlsx")
LIMIT = _TRIGGER_TIME_TABLE_LIMIT  # 500

def main():
    # 1. 读取 Excel
    print("1. 读取 Excel 数据...")
    wb = openpyxl.load_workbook(XLSX_PATH)
    ws = wb.active
    records = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        jira_no, trigger_time, extract_time = row[0], row[1], row[2]
        if not jira_no:
            continue
        # 转换 datetime 为字符串
        if isinstance(trigger_time, datetime):
            trigger_time = trigger_time.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(extract_time, datetime):
            extract_time = extract_time.strftime("%Y-%m-%d %H:%M:%S")
        records.append({
            "jira号": str(jira_no).strip(),
            "触发时间": str(trigger_time or "").strip(),
            "提取时间": str(extract_time or "").strip(),
        })
    print(f"   Excel 读取: {len(records)} 条")

    # 2. 加载云端缓存，过滤已有记录
    print("2. 加载云端缓存，过滤已有记录...")
    cloud_times, _ = _load_cloud_trigger_cache()
    to_write = []
    skipped = 0
    for rec in records:
        jira = rec["jira号"]
        if jira in cloud_times and cloud_times[jira]:
            skipped += 1
        else:
            to_write.append(rec)
    print(f"   已有跳过: {skipped} 条, 待写入: {len(to_write)} 条")

    if not to_write:
        print("无需写入")
        return

    # 3. 获取配置
    app_token, table_ids = _get_trigger_time_table_cfg()
    print(f"   当前 tables: {len(table_ids)} 个")

    # 4. 查询云端所有现有表，避免误删
    cloud_tables = feishu_client.list_bitable_tables(app_token)
    cloud_tids = {t["table_id"] for t in cloud_tables}
    cloud_tids.update(table_ids)

    # 5. 创建触发时间_1 和触发时间_2
    print("3. 创建触发时间_1 和触发时间_2...")
    new_tables = []
    for name_suffix in [1, 2]:
        tid = _create_trigger_time_subtable(app_token, name_suffix, cloud_tids)
        new_tables.append(tid)
        cloud_tids.add(tid)
        print(f"   触发时间_{name_suffix}: {tid}")

    # 6. 分批写入
    print("4. 分批写入数据...")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_written = 0
    for i, tid in enumerate(new_tables):
        batch = to_write[i * LIMIT: (i + 1) * LIMIT]
        if not batch:
            break
        create_records = [{
            "fields": {
                "jira号": r["jira号"],
                "触发时间": r["触发时间"],
                "提取时间": r["提取时间"] or now_str,
            }
        } for r in batch]
        feishu_client.batch_create_records(app_token, tid, create_records)
        total_written += len(batch)
        print(f"   触发时间_{i+1} ({tid}): 写入 {len(batch)} 条")

    # 7. 更新 config
    print("5. 更新 config.yaml...")
    all_table_ids = new_tables + list(table_ids)
    _update_config_table_ids(app_token, all_table_ids)
    print(f"   新 table_ids: {all_table_ids}")

    print(f"\n导入完成!")
    print(f"   总写入: {total_written} 条")
    print(f"   跳过已有: {skipped} 条")

if __name__ == "__main__":
    main()
