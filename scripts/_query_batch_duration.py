"""查询飞书数据沉淀中 11/11-11/12 的功能测试批量执行记录，统计耗时"""
import os
import sys
import json
from collections import defaultdict

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ_ROOT)


def _bt(val):
    """扁平化飞书字段值"""
    if val is None:
        return ""
    if isinstance(val, list):
        if not val:
            return ""
        first = val[0]
        if isinstance(first, dict) and "text" in first:
            return "".join(seg.get("text", "") for seg in val)
        if isinstance(first, str):
            return ", ".join(val)
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, dict):
        return val.get("value", json.dumps(val, ensure_ascii=False))
    return str(val)


def _parse_duration_sec(dur_str):
    """解析耗时字符串为秒数，如 '25分30秒' -> 1530, '1时5分20秒' -> 3920"""
    if not dur_str:
        return 0
    import re
    h = re.search(r'(\d+)\s*[时小时hH]', dur_str)
    m = re.search(r'(\d+)\s*[分分钟mM]', dur_str)
    s = re.search(r'(\d+)\s*[秒sS]', dur_str)
    total = 0
    if h:
        total += int(h.group(1)) * 3600
    if m:
        total += int(m.group(1)) * 60
    if s:
        total += int(s.group(1))
    # 纯数字（秒）
    if total == 0:
        try:
            total = int(float(dur_str))
        except (ValueError, TypeError):
            pass
    return total


def main():
    import warnings
    warnings.filterwarnings("ignore")

    from src.config import load_config
    from src.clients import feishu_client

    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    print(f"查询飞书多维表格: app={app_token}, table={table_id}")

    # 用过滤条件只拉 11/11-11/12 的数据
    filter_expr = 'CurrentValue.[分析开始时间] > "2026-11-10 23:59:59"'
    records = feishu_client.list_bitable_records(
        app_token, table_id, filter_expr=filter_expr, timeout=60)
    print(f"获取 {len(records)} 条记录（分析开始时间 >= 11/11）")

    # 按连续时间分组批次（间隔 > 30 分钟视为新批次）
    from datetime import datetime, timedelta
    all_items = []
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bt(fields.get("jira号", "")).strip()
        if not jira_no:
            continue
        version = _bt(fields.get("版本号", "")).strip()
        if version and any('\u4e00' <= c <= '\u9fff' for c in version):
            continue
        result = _bt(fields.get("分析结果", "")).strip()
        start_time = _bt(fields.get("分析开始时间", "")).strip()
        duration = _bt(fields.get("分析耗时", "")).strip()
        source = _bt(fields.get("触发来源", "")).strip()
        error = _bt(fields.get("错误信息", "")).strip()[:80]
        if not start_time:
            continue
        if not (start_time.startswith("2026-11-11") or start_time.startswith("2026-11-12")):
            continue
        dur_sec = _parse_duration_sec(duration)
        all_items.append({
            "jira": jira_no, "result": result, "start_time": start_time,
            "duration": duration, "dur_sec": dur_sec, "source": source, "error": error,
        })

    # 按开始时间排序后分组
    all_items.sort(key=lambda x: x["start_time"])
    GAP = 30 * 60  # 30 分钟间隔
    batches_list = []  # [{"key": str, "items": [...]}]
    current_batch = []
    last_end = None
    for item in all_items:
        try:
            st = datetime.strptime(item["start_time"][:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        item_end = st + timedelta(seconds=item["dur_sec"]) if item["dur_sec"] > 0 else st
        if last_end and (st - last_end).total_seconds() > GAP:
            # 间隔超过 30 分钟，开新批次
            if current_batch:
                batches_list.append(current_batch)
            current_batch = [item]
        else:
            current_batch.append(item)
        if last_end is None or item_end > last_end:
            last_end = item_end
    if current_batch:
        batches_list.append(current_batch)

    # 输出每个批次的统计
    print(f"\n{'='*100}")
    print(f"  11/11-11/12 功能测试批量执行耗时分析（批次总时长 = 首条开始 → 末条结束）")
    print(f"{'='*100}")

    all_durations = []
    batch_summaries = []

    for idx, batch_items in enumerate(batches_list):
        items = batch_items
        n = len(items)
        ok = sum(1 for i in items if i["result"] == "成功")
        fail = n - ok

        durs = [i["dur_sec"] for i in items if i["dur_sec"] > 0]
        avg_dur = sum(durs) / len(durs) if durs else 0

        sources = set(i["source"] for i in items if i["source"])
        source_str = "/".join(sources) if sources else "-"

        # 计算批次 wall-clock 总时长：最早开始 → 最晚（开始+耗时）
        earliest_start = None
        latest_end = None
        for i in items:
            try:
                st = datetime.strptime(i["start_time"][:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            if earliest_start is None or st < earliest_start:
                earliest_start = st
            end = st + timedelta(seconds=i["dur_sec"]) if i["dur_sec"] > 0 else st
            if latest_end is None or end > latest_end:
                latest_end = end

        wall_sec = int((latest_end - earliest_start).total_seconds()) if earliest_start and latest_end else 0
        wall_h = wall_sec // 3600
        wall_m = (wall_sec % 3600) // 60
        wall_s = wall_sec % 60
        wall_str = f"{wall_h}时{wall_m}分{wall_s}秒" if wall_h else f"{wall_m}分{wall_s}秒"

        # 平均每条（按批次总时长 / 条数，反映真实吞吐）
        avg_per_item = wall_sec / n / 60 if n else 0

        # 批次标签：日期 + 起始时间
        batch_label = f"{earliest_start.strftime('%m/%d %H:%M')}"

        print(f"\n── 批次 {idx+1}: {batch_label} ──")
        print(f"  总数: {n} | 成功: {ok} | 失败: {fail} | 成功率: {ok/n*100:.1f}%")
        print(f"  来源: {source_str}")
        print(f"  批次总时长: {wall_str}（{earliest_start.strftime('%m/%d %H:%M:%S')} → {latest_end.strftime('%m/%d %H:%M:%S')}）")
        print(f"  折算平均每条: {avg_per_item:.1f} 分钟（含并行）")
        if durs:
            print(f"  单条分析耗时: 平均 {avg_dur/60:.1f}分 | 最长 {max(durs)/60:.1f}分")
            all_durations.extend(durs)

        batch_summaries.append({
            "batch": batch_label, "n": n, "ok": ok, "fail": fail,
            "wall_sec": wall_sec, "avg_per_item": avg_per_item,
        })

    # 全局汇总
    print(f"\n\n{'='*100}")
    print(f"  全局汇总")
    print(f"{'='*100}")
    total = sum(b["n"] for b in batch_summaries)
    total_ok = sum(b["ok"] for b in batch_summaries)
    print(f"  总记录数: {total} | 成功: {total_ok} | 失败: {total - total_ok}")
    if all_durations:
        avg = sum(all_durations) / len(all_durations)
        print(f"  单条分析耗时均值: {avg/60:.1f} 分钟")
    print(f"\n  各批次 wall-clock 总时长 & 折算平均:")
    print(f"  {'批次':<20} {'条数':>6} {'总时长':>12} {'折算平均/条':>12} {'成功率':>8}")
    print(f"  {'-'*60}")
    for b in batch_summaries:
        w = b["wall_sec"]
        wh, wm = w // 3600, (w % 3600) // 60
        w_str = f"{wh}时{wm}分" if wh else f"{wm}分"
        rate = b["ok"] / b["n"] * 100 if b["n"] else 0
        print(f"  {b['batch']:<20} {b['n']:>6} {w_str:>12} {b['avg_per_item']:>10.1f}分 {rate:>7.1f}%")


if __name__ == "__main__":
    main()
