#!/usr/bin/env python3
"""拉取2026年9月云端批量执行 + 数据沉淀表格，分析已修复记录，生成优化HTML报告"""
import sys, os, csv, json, re
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.clients import feishu_client
from src.web.server import load_config, _parse_markdown_batch_table, _bitable_text, _flatten_bitable_record_all

# ──── 步骤1: 拉取云端批量执行记录 ────
print("=" * 60)
print("步骤1: 拉取云端批量执行记录 (2026-09)")
print("=" * 60)

cfg = load_config().get("feishu_bitable", {})
app_token = cfg.get("app_token", "")
table_id = cfg.get("table_id", "")
bugid_field = cfg.get("bugid_field", "jira号")
report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
folder_token = cfg.get("batch_folder_token", "")

all_files = feishu_client.list_folder_files(folder_token, recursive=True)
sep_files = [f for f in all_files
             if f.get("type") == "docx"
             and f.get("folder", "").startswith("2026-09")
             and (f.get("name", "").startswith("批量执行")
                  or f.get("name", "").startswith("线上批量执行"))]
print(f"9月文档: {len(sep_files)} 个")

# 收集每个Jira的所有执行记录（不去重，保留完整执行历史）
jira_all_execs = defaultdict(list)  # jira -> [(exec_time, trigger_time, trigger_source, model, batch_name)]
daily_counts = defaultdict(lambda: {"total": 0, "success": 0})

for i, doc in enumerate(sorted(sep_files, key=lambda x: x.get("folder", "") + x.get("name", ""))):
    doc_token = doc.get("token", "")
    doc_name = doc.get("name", "")
    folder = doc.get("folder", "")
    if not doc_token:
        continue
    try:
        md = feishu_client.fetch_docx_as_markdown(doc_token)
        batch_rows = _parse_markdown_batch_table(md)
        if not batch_rows:
            continue
        has_success = any((r.get("执行结果") or "").strip() == "成功" for r in batch_rows)
        daily_counts[folder]["total"] += len(batch_rows)
        for r in batch_rows:
            jira = (r.get("jira号") or r.get("Jira号") or "").strip()
            if not jira:
                continue
            exec_result = (r.get("执行结果") or "").strip()
            exec_time = (r.get("执行时间") or "").strip()
            trigger_time = (r.get("触发时间") or "").strip()
            trigger_source = (r.get("触发来源") or "").strip()
            model = (r.get("模型") or "").strip()
            if exec_result == "成功":
                daily_counts[folder]["success"] += 1
            jira_all_execs[jira].append({
                "exec_time": exec_time, "trigger_time": trigger_time,
                "trigger_source": trigger_source, "model": model,
                "exec_result": exec_result, "batch": f"{folder}/{doc_name}"
            })
        if (i + 1) % 50 == 0 or i == len(sep_files) - 1:
            print(f"  [{i+1}/{len(sep_files)}] 累计 {len(jira_all_execs)} 个Jira")
    except Exception as e:
        pass

# 去重：每个Jira保留最新执行时间的记录
jira_latest = {}
dup_count = 0
for jira, execs in jira_all_execs.items():
    execs.sort(key=lambda x: x["exec_time"])
    jira_latest[jira] = execs[-1]  # 最新执行
    if len(execs) > 1:
        dup_count += len(execs) - 1

total_execs = sum(len(v) for v in jira_all_execs.values())
print(f"\n拉取完成: {total_execs} 条执行, {len(jira_latest)} 个Jira, 去重 {dup_count} 条")

# ──── 步骤2: 查询数据沉淀表格 ────
print("\n" + "=" * 60)
print("步骤2: 查询数据沉淀表格")
print("=" * 60)

bitable_records = feishu_client.list_bitable_records(app_token, table_id)
print(f"数据沉淀: {len(bitable_records)} 条")

bt_map = {}  # jira -> [records]
for rec in bitable_records:
    fields = rec.get("fields", {})
    jira_key = _bitable_text(fields.get(bugid_field, ""))
    if jira_key:
        bt_map.setdefault(jira_key, []).append(
            _flatten_bitable_record_all(fields, report_field))

# ──── 步骤3: 分析每个Jira的最终结果 + 已修复标记 ────
print("\n" + "=" * 60)
print("步骤3: 分析结果 + 已修复标记")
print("=" * 60)

results = []  # 所有记录详情
error_categories = Counter()  # 归一化后的错误分类
error_type_tag = {}  # 错误分类 -> "执行问题" / "分析问题"
fixed_in_later = set()  # 初始失败但后续修复成功的Jira
error_cat_details = defaultdict(list)

# 归一化错误分类
def normalize_error_cat(raw_error, analysis_result):
    """归一化错误分类 + 标记类型"""
    if analysis_result == "成功":
        return "成功", ""
    if analysis_result in ("未找到", ""):
        return "未匹配数据沉淀", "执行问题"
    
    error = raw_error[:200]
    # ── 执行问题 ──
    if "No space left" in error or "Errno 28" in error:
        return "磁盘空间不足", "执行问题"
    if "超时" in error or "timeout" in error.lower() or "TimeoutErr" in error:
        return "分析超时", "执行问题"
    if "Server disconnected" in error or "connection" in error.lower() or "All connection" in error:
        return "网络连接异常", "执行问题"
    if "服务有报错" in error:
        return "服务端报错", "执行问题"
    if "ProcessLookupError" in error or "未预期的错误" in error:
        return "服务进程异常", "执行问题"
    # ── 分析问题 ──
    if "时间过滤后日志为空" in error:
        return "触发时间不准确", "分析问题"
    if "处理后未找到有效的日志文件" in error:
        return "日志文件缺失", "分析问题"
    if "解压后未找到可识别的日志文件" in error:
        return "日志格式不支持", "分析问题"
    if "没有可下载的日志附件" in error:
        return "无日志附件", "分析问题"
    if "reasoning" in error or "LLM" in error or "adjudication" in error:
        return "AI模型调用失败", "分析问题"
    if "报告生成失败" in error:
        return "报告生成失败", "分析问题"
    if "视频" in error or "video" in error.lower():
        return "视频分析失败", "分析问题"
    if error and error != "失败":
        return error[:40], "分析问题"
    return "未知原因", "分析问题"

# 分析每个Jira
for jira, exec_info in jira_latest.items():
    exec_time = exec_info["exec_time"]
    trigger_time = exec_info["trigger_time"]
    trigger_source = exec_info["trigger_source"]
    model = exec_info["model"]
    
    bt_records = bt_map.get(jira, [])
    
    # 匹配分析结果
    analysis_result = "未找到"
    error_msg = ""
    analysis_time = ""
    rootcause = ""
    report_url = ""
    
    if bt_records:
        candidates = [r for r in bt_records
                     if r.get("分析完成时间", "") and r["分析完成时间"] >= exec_time]
        if not candidates:
            candidates = bt_records
        candidates.sort(key=lambda x: x.get("分析完成时间", ""))
        
        success_records = [r for r in candidates if r.get("分析结果", "") == "成功"]
        bf = success_records[0] if success_records else candidates[-1]
        
        analysis_result = bf.get("分析结果", "失败")
        error_msg = _bitable_text(bf.get("错误信息", ""))
        analysis_time = bf.get("分析完成时间", "")
        rootcause = _bitable_text(bf.get("rootcause", ""))
        report_url = bf.get("report_url", "")
    
    cat, tag = normalize_error_cat(error_msg, analysis_result)
    
    # 检查是否后续修复：同一Jira有多次执行，且最新一次分析结果为成功
    all_execs = jira_all_execs[jira]
    if len(all_execs) > 1 and analysis_result != "成功":
        # 查找该Jira是否有更晚的成功执行
        for later_exec in reversed(all_execs):
            if later_exec["exec_time"] > exec_time:
                later_bt = bt_map.get(jira, [])
                later_success = [r for r in later_bt
                              if r.get("分析结果", "") == "成功"
                              and r.get("分析完成时间", "") >= later_exec["exec_time"]]
                if later_success:
                    fixed_in_later.add(jira)
                    break
    # 如果当前记录分析成功，检查是否有更早的失败记录
    elif analysis_result == "成功" and len(all_execs) > 1:
        has_earlier_fail = False
        for earlier_exec in all_execs[:-1]:
            if earlier_exec["exec_time"] < exec_time:
                earlier_bt = [r for r in bt_map.get(jira, [])
                            if r.get("分析完成时间", "") and 
                            earlier_exec["exec_time"] <= r.get("分析完成时间", "") <= exec_time
                            and r.get("分析结果", "") != "成功"]
                if earlier_bt:
                    has_earlier_fail = True
                    break
        if has_earlier_fail:
            fixed_in_later.add(jira)
    
    record = {
        "jira": jira,
        "exec_time": exec_time,
        "trigger_time": trigger_time,
        "trigger_source": trigger_source,
        "model": model,
        "analysis_result": analysis_result,
        "error_msg": error_msg[:200],
        "error_cat": cat,
        "error_tag": tag,
        "analysis_time": analysis_time,
        "rootcause": rootcause,
        "report_url": report_url,
        "is_fixed": jira in fixed_in_later,
        "exec_count": len(all_execs),
    }
    results.append(record)
    
    if analysis_result != "成功":
        error_categories[cat] += 1
        error_type_tag[cat] = tag
        error_cat_details[cat].append(record)

# 统计
success_count = sum(1 for r in results if r["analysis_result"] == "成功")
fail_count = sum(1 for r in results if r["analysis_result"] not in ("成功", "未找到", ""))
unmatched_count = sum(1 for r in results if r["analysis_result"] in ("未找到", ""))
fixed_count = len(fixed_in_later)

# 按执行问题/分析问题汇总
exec_issue_count = sum(cnt for cat, cnt in error_categories.items() if error_type_tag.get(cat) == "执行问题")
analysis_issue_count = sum(cnt for cat, cnt in error_categories.items() if error_type_tag.get(cat) == "分析问题")

print(f"总Jira: {len(results)}")
print(f"分析成功: {success_count} ({success_count/len(results)*100:.1f}%)")
print(f"分析失败: {fail_count}")
print(f"未匹配: {unmatched_count}")
print(f"后续已修复: {fixed_count}")
print(f"执行问题: {exec_issue_count}, 分析问题: {analysis_issue_count}")

# ──── 步骤4: 按日期统计 ────
daily_stats = defaultdict(lambda: {"total": 0, "success": 0, "fail": 0, "fixed": 0})
for r in results:
    day = r["exec_time"][:10]
    if not day:
        continue
    daily_stats[day]["total"] += 1
    if r["analysis_result"] == "成功":
        daily_stats[day]["success"] += 1
    else:
        daily_stats[day]["fail"] += 1
    if r["is_fixed"]:
        daily_stats[day]["fixed"] += 1

# ──── 步骤5: 保存CSV ────
report_dir = os.path.join(os.path.dirname(__file__), "..", "reports")
os.makedirs(report_dir, exist_ok=True)
csv_path = os.path.join(report_dir, "2026-09_monthly_review.csv")
with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["jira号", "执行结果", "分析结果", "错误分类", "错误类型", "已修复", "错误信息",
                "触发时间", "执行时间", "触发来源", "模型", "执行次数"])
    for r in sorted(results, key=lambda x: x["jira"]):
        w.writerow([r["jira"], "成功", r["analysis_result"], r["error_cat"], r["error_tag"],
                    "是" if r["is_fixed"] else "", r["error_msg"],
                    r["trigger_time"], r["exec_time"], r["trigger_source"], r["model"],
                    r["exec_count"]])
print(f"\nCSV已保存: {csv_path}")

# ──── 步骤6: 生成JSON数据供HTML使用 ────
report_data = {
    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "total": len(results),
    "total_execs": total_execs,
    "dup_count": dup_count,
    "success_count": success_count,
    "fail_count": fail_count,
    "unmatched_count": unmatched_count,
    "fixed_count": fixed_count,
    "exec_issue_count": exec_issue_count,
    "analysis_issue_count": analysis_issue_count,
    "daily_stats": {d: dict(v) for d, v in sorted(daily_stats.items())},
    "error_categories": [(cat, cnt, error_type_tag.get(cat, "")) for cat, cnt in error_categories.most_common()],
    "error_details": {cat: [{"jira": r["jira"], "error": r["error_msg"][:100],
                             "trigger_time": r["trigger_time"], "exec_time": r["exec_time"],
                             "is_fixed": r["is_fixed"]}
                            for r in items[:10]]
                      for cat, items in error_cat_details.items()},
    "doc_count": len(sep_files),
}

json_path = os.path.join(report_dir, "2026-09_report_data.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(report_data, f, ensure_ascii=False, indent=2)
print(f"JSON已保存: {json_path}")
print("\n数据准备完成，可生成HTML报告")
