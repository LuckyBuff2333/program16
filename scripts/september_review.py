#!/usr/bin/env python3
"""拉取2026年9月云端批量执行记录 + 数据沉淀表格，生成错误类型复盘报告"""
import sys, os, csv
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.clients import feishu_client
from src.web.server import load_config, _parse_markdown_batch_table, _bitable_text, _flatten_bitable_record_all

# ──── 步骤1: 从云端文件夹拉取9月所有批量执行记录 ────
print("=" * 60)
print("步骤1: 拉取云端批量执行记录 (2026-09)")
print("=" * 60)

cfg = load_config().get("feishu_bitable", {})
app_token = cfg.get("app_token", "")
table_id = cfg.get("table_id", "")
bugid_field = cfg.get("bugid_field", "jira号")
report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
folder_token = cfg.get("batch_folder_token", "")

if not folder_token:
    print("ERROR: 未配置 batch_folder_token")
    sys.exit(1)

# 列出所有文件
print(f"云端文件夹: {folder_token}")
all_files = feishu_client.list_folder_files(folder_token, recursive=True)
print(f"总文件数: {len(all_files)}")

# 过滤9月的文件
sep_files = [f for f in all_files
             if f.get("type") == "docx"
             and f.get("folder", "").startswith("2026-09")
             and (f.get("name", "").startswith("批量执行")
                  or f.get("name", "").startswith("线上批量执行"))]
print(f"9月批量执行文档: {len(sep_files)} 个")

# 读取每个文档
all_batch_records = {}  # jira -> record (保留最新执行时间)
dup_count = 0
daily_stats = defaultdict(lambda: {"total": 0, "success": 0, "fail": 0})

def process_batch_rows(rows):
    """处理批次CSV行，返回成功记录"""
    global dup_count
    has_success = any((r.get("执行结果") or "").strip() == "成功" for r in rows)
    if not has_success:
        return {}
    result = {}
    for r in rows:
        jira = (r.get("jira号") or r.get("Jira号") or "").strip()
        if not jira:
            continue
        exec_result = (r.get("执行结果") or "").strip()
        if exec_result != "成功":
            continue
        exec_time = (r.get("执行时间") or "").strip()
        trigger_time = (r.get("触发时间") or "").strip()
        if jira in all_batch_records:
            dup_count += 1
            if exec_time > all_batch_records[jira].get("执行时间", ""):
                all_batch_records[jira] = r
        else:
            all_batch_records[jira] = r
        if jira in result:
            if exec_time > result[jira].get("执行时间", ""):
                result[jira] = r
        else:
            result[jira] = r
    return result

for i, doc in enumerate(sorted(sep_files, key=lambda x: x.get("folder", "") + x.get("name", ""))):
    doc_token = doc.get("token", "")
    doc_name = doc.get("name", "")
    folder = doc.get("folder", "")
    if not doc_token:
        continue
    try:
        md = feishu_client.fetch_docx_as_markdown(doc_token)
        batch_rows = _parse_markdown_batch_table(md)
        if batch_rows:
            result = process_batch_rows(batch_rows)
            daily_stats[folder]["total"] += len(batch_rows)
            daily_stats[folder]["success"] += len(result)
            daily_stats[folder]["fail"] += (len(batch_rows) - len(result))
            print(f"  [{i+1}/{len(sep_files)}] {folder}/{doc_name}: {len(batch_rows)}条, 成功{len(result)}")
        else:
            print(f"  [{i+1}/{len(sep_files)}] {folder}/{doc_name}: 无数据")
    except Exception as e:
        print(f"  [{i+1}/{len(sep_files)}] {folder}/{doc_name}: 读取失败 - {e}")

print(f"\n云端拉取完成:")
print(f"  总记录: {sum(s['total'] for s in daily_stats.values())}")
print(f"  去重后: {len(all_batch_records)} 条 (去重 {dup_count} 条)")
print(f"  按日分布:")
for d in sorted(daily_stats.keys()):
    s = daily_stats[d]
    print(f"    {d}: 总{s['total']}, 成功{s['success']}, 失败{s['fail']}")

# ──── 步骤2: 查询数据沉淀表格 ────
print("\n" + "=" * 60)
print("步骤2: 查询数据沉淀表格")
print("=" * 60)

print(f"多维表格: {app_token}/{table_id}")
bitable_records = feishu_client.list_bitable_records(app_token, table_id)
print(f"数据沉淀总记录数: {len(bitable_records)}")

# 构建 jira -> bitable record 映射
bt_map = {}
for rec in bitable_records:
    fields = rec.get("fields", {})
    jira_key = _bitable_text(fields.get(bugid_field, ""))
    if jira_key and jira_key in all_batch_records:
        bt_map.setdefault(jira_key, []).append(
            _flatten_bitable_record_all(fields, report_field))

matched_count = len(bt_map)
unmatched_count = len(all_batch_records) - matched_count
print(f"匹配: {matched_count} 条, 未匹配: {unmatched_count} 条")

# ──── 步骤3: 生成复盘报告 ────
print("\n" + "=" * 60)
print("步骤3: 生成错误类型复盘报告")
print("=" * 60)

# 分析结果分类
result_cats = Counter()  # 分析结果分类
fail_cats = Counter()    # 失败原因分类
error_details = defaultdict(list)  # 错误类型 -> [(jira, 错误信息, 触发时间)]
success_count = 0
pending_count = 0

for jira, exec_info in all_batch_records.items():
    exec_time = exec_info.get("执行时间", "")
    trigger_time = exec_info.get("触发时间", "")
    
    bt_records = bt_map.get(jira, [])
    if not bt_records:
        result_cats["未找到分析结果"] += 1
        error_details["未找到分析结果"].append({
            "jira": jira, "error": "数据沉淀表格无匹配记录",
            "trigger_time": trigger_time, "exec_time": exec_time
        })
        continue
    
    # 匹配分析完成时间 >= 执行时间的记录
    candidates = [r for r in bt_records
                 if r.get("分析完成时间", "") and r["分析完成时间"] >= exec_time]
    if not candidates:
        candidates = bt_records
    candidates.sort(key=lambda x: x.get("分析完成时间", ""))
    
    # 智能去重：有成功则取成功，否则取最后一次
    success_records = [r for r in candidates if r.get("分析结果", "") == "成功"]
    if success_records:
        bf = success_records[0]
    else:
        bf = candidates[-1]
    
    result = bf.get("分析结果", "")
    result_cats[result] += 1
    
    if result == "成功":
        success_count += 1
    elif result in ("分析中", "待分析"):
        pending_count += 1
    else:
        # 失败分类
        error_msg = _bitable_text(bf.get("错误信息", ""))[:100]
        rootcause = _bitable_text(bf.get("rootcause", ""))[:80]
        
        # 简单分类逻辑
        if "触发时间" in error_msg or "trigger" in error_msg.lower():
            cat = "触发时间提取失败"
        elif "视频" in error_msg or "video" in error_msg.lower():
            cat = "视频分析失败"
        elif "超时" in error_msg or "timeout" in error_msg.lower():
            cat = "分析超时"
        elif "Jira" in error_msg or "jira" in error_msg.lower():
            cat = "Jira接口问题"
        elif "AI" in error_msg or "模型" in error_msg:
            cat = "AI分析接口问题"
        elif rootcause:
            cat = rootcause[:40]
        else:
            cat = error_msg[:40] if error_msg else "未知原因"
        
        fail_cats[cat] += 1
        error_details[cat].append({
            "jira": jira, "error": error_msg,
            "trigger_time": trigger_time, "exec_time": exec_time
        })

# ──── 输出报告 ────
total = len(all_batch_records)
print(f"\n{'='*60}")
print(f"  2026年9月批量执行复盘报告")
print(f"{'='*60}")
print(f"\n【总体概况】")
print(f"  执行总数: {total}")
print(f"  去重前:   {sum(s['total'] for s in daily_stats.values())}")
print(f"  去重数:   {dup_count}")
print(f"  分析成功: {success_count} ({success_count/total*100:.1f}%)")
print(f"  分析失败: {total - success_count - pending_count} ({(total-success_count-pending_count)/total*100:.1f}%)")
print(f"  待分析:   {pending_count}")
print(f"  未匹配:   {unmatched_count}")

print(f"\n【分析结果分布】")
for cat, cnt in result_cats.most_common():
    print(f"  {cat}: {cnt} 条 ({cnt/total*100:.1f}%)")

if fail_cats:
    print(f"\n【错误类型分布 TOP10】")
    for cat, cnt in fail_cats.most_common(10):
        print(f"  {cat}: {cnt} 条")

    print(f"\n【错误详情（每类最多5条）】")
    for cat, cnt in fail_cats.most_common(10):
        print(f"\n  ▸ {cat} ({cnt}条):")
        for item in error_details[cat][:5]:
            print(f"    - {item['jira']}: {item['error'][:60]}")
            print(f"      触发: {item['trigger_time']}, 执行: {item['exec_time']}")

# ──── 保存CSV报告 ────
report_dir = os.path.join(os.path.dirname(__file__), "..", "reports")
os.makedirs(report_dir, exist_ok=True)
report_path = os.path.join(report_dir, "2026-09_monthly_review.csv")

with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["jira号", "执行结果", "分析结果", "错误分类", "错误信息", "触发时间", "执行时间", "触发来源"])
    for jira, exec_info in sorted(all_batch_records.items()):
        exec_time = exec_info.get("执行时间", "")
        trigger_time = exec_info.get("触发时间", "")
        trigger_source = exec_info.get("触发来源", "")
        
        bt_records = bt_map.get(jira, [])
        if not bt_records:
            w.writerow([jira, "成功", "未找到", "未找到分析结果", "", trigger_time, exec_time, trigger_source])
            continue
        
        candidates = [r for r in bt_records
                     if r.get("分析完成时间", "") and r["分析完成时间"] >= exec_time]
        if not candidates:
            candidates = bt_records
        candidates.sort(key=lambda x: x.get("分析完成时间", ""))
        
        success_records = [r for r in candidates if r.get("分析结果", "") == "成功"]
        bf = success_records[0] if success_records else candidates[-1]
        
        result = bf.get("分析结果", "")
        error_msg = _bitable_text(bf.get("错误信息", ""))[:200] if result != "成功" else ""
        
        cat = ""
        if result not in ("成功", "分析中", "待分析"):
            if "触发时间" in error_msg:
                cat = "触发时间提取失败"
            elif "视频" in error_msg:
                cat = "视频分析失败"
            elif "超时" in error_msg:
                cat = "分析超时"
            else:
                cat = error_msg[:30] if error_msg else "未知原因"
        
        w.writerow([jira, "成功", result, cat, error_msg, trigger_time, exec_time, trigger_source])

print(f"\n报告已保存: {report_path}")
print(f"共 {total} 条记录")
