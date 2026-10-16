#!/usr/bin/env python3
"""更新 online_empty_ai_jiras.csv：与多维表格交叉比对，移除已修复的 Jira

用法:
    python scripts/update_empty_jiras.py                       # 默认更新最新日期的 CSV
    python scripts/update_empty_jiras.py --date 2026-10-15     # 指定日期
    python scripts/update_empty_jiras.py --dry-run             # 仅统计不修改文件
    python scripts/update_empty_jiras.py --export-new DATE     # 从多维表格导出新的空链接列表

逻辑:
    1. 读取 docs/{date}/online_empty_ai_jiras.csv
    2. 查多维表格，匹配这些 Jira
    3. 分析结果=成功 且 AI分析结果(飞书链接)非空 → 已修复 → 从 CSV 移除
    4. 输出修复进度统计
"""
import argparse
import csv
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config, PROJECT_ROOT
from src.clients import feishu_client


def _bitable_text(val) -> str:
    """多维表格字段值归一化为纯文本"""
    if val is None:
        return ""
    if isinstance(val, list):
        return "".join(_bitable_text(item) for item in val)
    if isinstance(val, dict):
        return str(val.get("text", "") or val.get("name", "") or "").strip()
    return str(val).strip()


def _get_bitable_link(val) -> str:
    """多维表格 URL 字段取 link"""
    if isinstance(val, dict):
        return str(val.get("link", "") or "").strip()
    return str(val).strip() if val else ""


def _load_csv(date_str: str):
    """加载 CSV，返回 (文件路径, 行列表[{序号, jira号}])"""
    csv_path = os.path.join(PROJECT_ROOT, "docs", date_str, "online_empty_ai_jiras.csv")
    if not os.path.isfile(csv_path):
        return None, []
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            jira = (row.get("jira号") or "").strip()
            if jira:
                rows.append({"序号": row.get("序号", ""), "jira号": jira})
    return csv_path, rows


def _find_latest_csv_date() -> str:
    """找到 docs/ 下最新的 online_empty_ai_jiras.csv 所在日期"""
    docs_dir = os.path.join(PROJECT_ROOT, "docs")
    latest = ""
    if os.path.isdir(docs_dir):
        for d in sorted(os.listdir(docs_dir), reverse=True):
            fpath = os.path.join(docs_dir, d, "online_empty_ai_jiras.csv")
            if os.path.isfile(fpath):
                return d
    return latest


def _query_bitable(jira_set: set):
    """查多维表格，返回 {jira号: [{分析结果, 飞书链接, 分析完成时间}, ...]}"""
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")

    if not app_token or not table_id:
        print("错误：多维表格 app_token/table_id 未配置")
        sys.exit(1)

    print(f"正在查询多维表格...")
    records = feishu_client.list_bitable_records(app_token, table_id)
    print(f"多维表格总记录数: {len(records)}")

    bt_map = {}
    for rec in records:
        fields = rec.get("fields", {})
        jira_key = _bitable_text(fields.get(bugid_field, ""))
        if not jira_key or jira_key not in jira_set:
            continue
        result = _bitable_text(fields.get("分析结果", ""))
        link = _get_bitable_link(fields.get(report_field, ""))
        done_time = _bitable_text(fields.get("分析完成时间", ""))
        bt_map.setdefault(jira_key, []).append({
            "分析结果": result,
            "飞书链接": link,
            "分析完成时间": done_time,
            "record_id": rec.get("record_id", ""),
        })
    return bt_map


def _classify(jira_no: str, bt_records: list) -> str:
    """分类单个 Jira 的状态

    Returns:
        'fixed'     - 有成功记录且飞书链接非空
        'failed'    - 有记录但全部失败（或成功但无链接）
        'missing'   - 多维表格中无记录
    """
    if not bt_records:
        return "missing"
    # 有任一成功记录且链接非空 → 已修复
    for r in bt_records:
        if r["分析结果"] == "成功" and r["飞书链接"]:
            return "fixed"
    return "failed"


def update_csv(date_str: str, dry_run: bool = False):
    """核心：更新指定日期的 online_empty_ai_jiras.csv"""
    csv_path, rows = _load_csv(date_str)
    if not csv_path:
        print(f"错误：未找到 docs/{date_str}/online_empty_ai_jiras.csv")
        sys.exit(1)

    total = len(rows)
    jira_set = set(r["jira号"] for r in rows)
    print(f"CSV 文件: {csv_path}")
    print(f"CSV Jira 总数: {total}")

    # 查多维表格
    bt_map = _query_bitable(jira_set)

    # 分类
    fixed_list = []     # 已修复（链接已填充）
    failed_list = []    # 仅失败（有记录但无成功链接）
    missing_list = []   # 未入沉淀
    remaining = []      # 保留在 CSV 中的

    for row in rows:
        jira = row["jira号"]
        bt_recs = bt_map.get(jira, [])
        status = _classify(jira, bt_recs)
        if status == "fixed":
            fixed_list.append(jira)
        elif status == "failed":
            failed_list.append(jira)
            remaining.append(row)
        else:
            missing_list.append(jira)
            remaining.append(row)

    # 输出统计
    print(f"\n{'='*50}")
    print(f"  修复进度统计")
    print(f"{'='*50}")
    print(f"  初始空链接总数:    {total}")
    print(f"  已修复(链接已填充): {len(fixed_list)}")
    print(f"  仍为空(有记录):    {len(failed_list)}")
    print(f"  未入沉淀:          {len(missing_list)}")
    print(f"  修复率:            {len(fixed_list)}/{total} ({len(fixed_list)*100/total:.1f}%)" if total else "  修复率: N/A")
    print(f"  剩余待处理:        {len(remaining)}")
    print(f"{'='*50}")

    if fixed_list:
        print(f"\n已修复的 Jira ({len(fixed_list)} 个):")
        for j in fixed_list[:20]:
            # 找到最新的成功记录
            recs = bt_map.get(j, [])
            success_recs = [r for r in recs if r["分析结果"] == "成功" and r["飞书链接"]]
            latest = max(success_recs, key=lambda r: r.get("分析完成时间", ""))
            print(f"  {j} → {latest['飞书链接'][:60]}... (完成: {latest['分析完成时间']})")
        if len(fixed_list) > 20:
            print(f"  ... 还有 {len(fixed_list) - 20} 个")

    if failed_list:
        print(f"\n仍为空(分析成功但链接为空) 的 Jira ({len(failed_list)} 个):")
        for j in failed_list[:10]:
            print(f"  {j}")
        if len(failed_list) > 10:
            print(f"  ... 还有 {len(failed_list) - 10} 个")

    if missing_list:
        print(f"\n未入沉淀的 Jira ({len(missing_list)} 个):")
        for j in missing_list[:10]:
            print(f"  {j}")
        if len(missing_list) > 10:
            print(f"  ... 还有 {len(missing_list) - 10} 个")

    # 更新 CSV
    if dry_run:
        print(f"\n[DRY RUN] 不修改文件，原 CSV 保持不变")
        return

    if not fixed_list:
        print(f"\n无需更新，CSV 保持不变")
        return

    # 重写序号
    for i, row in enumerate(remaining, 1):
        row["序号"] = str(i)

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["序号", "jira号"])
        writer.writeheader()
        writer.writerows(remaining)

    print(f"\nCSV 已更新：移除 {len(fixed_list)} 个已修复 Jira，剩余 {len(remaining)} 个")
    print(f"文件: {csv_path}")


def export_new(date_str: str):
    """从多维表格导出当前所有「分析成功但飞书链接为空」的 Jira 到新 CSV"""
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")

    if not app_token or not table_id:
        print("错误：多维表格 app_token/table_id 未配置")
        sys.exit(1)

    print("正在查询多维表格...")
    records = feishu_client.list_bitable_records(app_token, table_id)
    print(f"多维表格总记录数: {len(records)}")

    # 找分析成功但飞书链接为空的 Jira（去重）
    empty_jiras = set()
    for rec in records:
        fields = rec.get("fields", {})
        jira = _bitable_text(fields.get(bugid_field, ""))
        result = _bitable_text(fields.get("分析结果", ""))
        link = _get_bitable_link(fields.get(report_field, ""))
        if jira and result == "成功" and not link:
            empty_jiras.add(jira)

    if not empty_jiras:
        print("当前多维表格中无「分析成功但飞书链接为空」的 Jira")
        return

    # 写入
    out_dir = os.path.join(PROJECT_ROOT, "docs", date_str)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "online_empty_ai_jiras.csv")

    sorted_jiras = sorted(empty_jiras)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["序号", "jira号"])
        writer.writeheader()
        for i, j in enumerate(sorted_jiras, 1):
            writer.writerow({"序号": str(i), "jira号": j})

    print(f"\n导出完成：{len(empty_jiras)} 个空链接 Jira")
    print(f"文件: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="更新 online_empty_ai_jiras.csv：移除已修复的 Jira")
    parser.add_argument("--date", type=str, default="", help="CSV 所在日期目录（默认最新）")
    parser.add_argument("--dry-run", action="store_true", help="仅统计，不修改文件")
    parser.add_argument("--export-new", type=str, metavar="DATE", help="从多维表格导出新的空链接列表到指定日期目录")
    args = parser.parse_args()

    if args.export_new:
        export_new(args.export_new)
        return

    date_str = args.date or _find_latest_csv_date()
    if not date_str:
        print("错误：未找到任何 online_empty_ai_jiras.csv，请用 --export-new DATE 先导出")
        sys.exit(1)

    update_csv(date_str, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
