#!/usr/bin/env python3
"""拉取2026年9月云端批量执行 + 数据沉淀表格，区分PC/线上分别去重，生成HTML报告数据"""
import sys, os, csv, json, re
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.clients import feishu_client
from src.web.server import load_config, _parse_markdown_batch_table, _bitable_text, _flatten_bitable_record_all

# ──── 步骤1: 拉取云端批量执行记录（区分PC/线上） ────
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

def classify_exec_mode(doc_name):
    """根据文档名判断执行模式: PC / 线上"""
    if doc_name.startswith("线上"):
        return "线上"
    if "_online_" in doc_name or "_prod_" in doc_name:
        return "线上"
    return "PC"

# 收集记录：按执行模式分开
pc_execs = defaultdict(list)      # jira -> [exec_info]
online_execs = defaultdict(list)  # jira -> [exec_info]
total_raw = 0

for i, doc in enumerate(sorted(sep_files, key=lambda x: x.get("folder", "") + x.get("name", ""))):
    doc_token = doc.get("token", "")
    doc_name = doc.get("name", "")
    folder = doc.get("folder", "")
    mode = classify_exec_mode(doc_name)
    if not doc_token:
        continue
    try:
        md = feishu_client.fetch_docx_as_markdown(doc_token)
        batch_rows = _parse_markdown_batch_table(md)
        if not batch_rows:
            continue
        for r in batch_rows:
            jira = (r.get("jira号") or r.get("Jira号") or "").strip()
            if not jira:
                continue
            total_raw += 1
            exec_info = {
                "exec_time": (r.get("执行时间") or "").strip(),
                "trigger_time": (r.get("触发时间") or "").strip(),
                "exec_result": (r.get("执行结果") or "").strip(),
                "model": (r.get("模型") or "").strip(),
                "batch": f"{folder}/{doc_name}",
                "mode": mode,
            }
            if mode == "PC":
                pc_execs[jira].append(exec_info)
            else:
                online_execs[jira].append(exec_info)
        if (i + 1) % 50 == 0 or i == len(sep_files) - 1:
            print(f"  [{i+1}/{len(sep_files)}] PC:{sum(len(v) for v in pc_execs.values())} 线上:{sum(len(v) for v in online_execs.values())}")
    except Exception:
        pass

print(f"\n拉取完成: 原始 {total_raw} 条")
print(f"  PC: {sum(len(v) for v in pc_execs.values())} 条, {len(pc_execs)} 个Jira")
print(f"  线上: {sum(len(v) for v in online_execs.values())} 条, {len(online_execs)} 个Jira")

# ──── 步骤2: 分别去重 ────
def dedup_execs(jira_execs):
    """对每个Jira保留最新执行时间的记录"""
    latest = {}
    dup = 0
    for jira, execs in jira_execs.items():
        execs.sort(key=lambda x: x["exec_time"])
        latest[jira] = execs[-1]
        latest[jira]["exec_count"] = len(execs)
        if len(execs) > 1:
            dup += len(execs) - 1
    return latest, dup

pc_latest, pc_dup = dedup_execs(pc_execs)
online_latest, online_dup = dedup_execs(online_execs)

# 全局去重（合并PC+线上，同一Jira取最新）
all_latest = {}
all_dup = 0
for jira in set(pc_execs.keys()) | set(online_execs.keys()):
    all_e = pc_execs.get(jira, []) + online_execs.get(jira, [])
    all_e.sort(key=lambda x: x["exec_time"])
    all_latest[jira] = all_e[-1]
    all_latest[jira]["exec_count"] = len(all_e)
    if len(all_e) > 1:
        all_dup += len(all_e) - 1

print(f"\n去重结果:")
print(f"  PC: {len(pc_latest)} 个Jira (去重 {pc_dup})")
print(f"  线上: {len(online_latest)} 个Jira (去重 {online_dup})")
print(f"  全局: {len(all_latest)} 个Jira (去重 {all_dup})")

# ──── 步骤3: 查询数据沉淀表格 ────
print("\n" + "=" * 60)
print("步骤2: 查询数据沉淀表格")
print("=" * 60)

bitable_records = feishu_client.list_bitable_records(app_token, table_id)
print(f"数据沉淀: {len(bitable_records)} 条")

bt_map = {}
for rec in bitable_records:
    fields = rec.get("fields", {})
    jira_key = _bitable_text(fields.get(bugid_field, ""))
    if jira_key:
        bt_map.setdefault(jira_key, []).append(
            _flatten_bitable_record_all(fields, report_field))

# ──── 步骤4: 分析结果 ────
print("\n" + "=" * 60)
print("步骤3: 分析结果")
print("=" * 60)

def normalize_error_cat(raw_error, analysis_result):
    if analysis_result == "成功":
        return "成功", ""
    if analysis_result in ("未找到", ""):
        return "未匹配数据沉淀", "执行问题"
    error = raw_error[:200]
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

def analyze_mode(mode_latest, mode_execs, mode_name):
    """分析某个执行模式的数据"""
    results = []
    error_cats = Counter()
    error_type_tag = {}
    error_details = defaultdict(list)
    fixed_jiras = set()

    for jira, exec_info in mode_latest.items():
        exec_time = exec_info["exec_time"]
        bt_records = bt_map.get(jira, [])
        
        analysis_result = "未找到"
        error_msg = ""
        if bt_records:
            candidates = [r for r in bt_records
                         if r.get("分析完成时间", "") and r["分析完成时间"] >= exec_time]
            if not candidates:
                candidates = bt_records
            candidates.sort(key=lambda x: x.get("分析完成时间", ""))
            success_recs = [r for r in candidates if r.get("分析结果", "") == "成功"]
            bf = success_recs[0] if success_recs else candidates[-1]
            analysis_result = bf.get("分析结果", "失败")
            error_msg = _bitable_text(bf.get("错误信息", ""))

        cat, tag = normalize_error_cat(error_msg, analysis_result)
        
        # 已修复检测：该Jira在本模式内有多次执行，且后续执行成功
        all_e = mode_execs.get(jira, [])
        is_fixed = False
        if len(all_e) > 1 and analysis_result != "成功":
            for later in reversed(all_e):
                if later["exec_time"] > exec_time:
                    later_bt = [r for r in bt_map.get(jira, [])
                              if r.get("分析结果", "") == "成功"
                              and r.get("分析完成时间", "") >= later["exec_time"]]
                    if later_bt:
                        is_fixed = True
                        fixed_jiras.add(jira)
                        break
        elif analysis_result == "成功" and len(all_e) > 1:
            for earlier in all_e[:-1]:
                if earlier["exec_time"] < exec_time:
                    earlier_bt = [r for r in bt_map.get(jira, [])
                                if r.get("分析完成时间", "") and
                                earlier["exec_time"] <= r.get("分析完成时间", "") <= exec_time
                                and r.get("分析结果", "") != "成功"]
                    if earlier_bt:
                        is_fixed = True
                        fixed_jiras.add(jira)
                        break

        record = {
            "jira": jira, "mode": mode_name,
            "exec_time": exec_time, "trigger_time": exec_info["trigger_time"],
            "model": exec_info.get("model", ""),
            "analysis_result": analysis_result, "error_msg": error_msg[:200],
            "error_cat": cat, "error_tag": tag,
            "is_fixed": is_fixed, "exec_count": exec_info.get("exec_count", 1),
        }
        results.append(record)
        if analysis_result != "成功":
            error_cats[cat] += 1
            error_type_tag[cat] = tag
            error_details[cat].append(record)

    success = sum(1 for r in results if r["analysis_result"] == "成功")
    fail = sum(1 for r in results if r["analysis_result"] not in ("成功", "未找到", ""))
    unmatched = sum(1 for r in results if r["analysis_result"] in ("未找到", ""))
    exec_issue = sum(c for cat, c in error_cats.items() if error_type_tag.get(cat) == "执行问题")
    analysis_issue = sum(c for cat, c in error_cats.items() if error_type_tag.get(cat) == "分析问题")

    # 每日统计
    daily = defaultdict(lambda: {"total": 0, "success": 0, "fail": 0})
    for r in results:
        day = r["exec_time"][:10]
        if day and day.startswith("2026-09"):
            daily[day]["total"] += 1
            if r["analysis_result"] == "成功":
                daily[day]["success"] += 1
            else:
                daily[day]["fail"] += 1

    return {
        "results": results,
        "total": len(results),
        "success": success, "fail": fail, "unmatched": unmatched,
        "fixed": len(fixed_jiras),
        "exec_issue": exec_issue, "analysis_issue": analysis_issue,
        "error_cats": [(cat, cnt, error_type_tag.get(cat, "")) for cat, cnt in error_cats.most_common()],
        "error_details": {cat: [{"jira": r["jira"], "error": r["error_msg"][:100],
                                 "trigger_time": r["trigger_time"], "exec_time": r["exec_time"],
                                 "is_fixed": r["is_fixed"]}
                                for r in items[:10]]
                         for cat, items in error_details.items()},
        "daily": {d: dict(v) for d, v in sorted(daily.items())},
    }

pc_data = analyze_mode(pc_latest, pc_execs, "PC")
online_data = analyze_mode(online_latest, online_execs, "线上")
all_data = analyze_mode(all_latest, {j: pc_execs.get(j, []) + online_execs.get(j, []) for j in all_latest}, "全部")

# 打印汇总
for label, d in [("PC", pc_data), ("线上", online_data), ("全部", all_data)]:
    print(f"\n【{label}】")
    print(f"  总数: {d['total']}, 成功: {d['success']} ({d['success']/d['total']*100:.1f}%), 失败: {d['fail']}, 未匹配: {d['unmatched']}")
    print(f"  已修复: {d['fixed']}, 执行问题: {d['exec_issue']}, 分析问题: {d['analysis_issue']}")
    print(f"  错误TOP5: {d['error_cats'][:5]}")

# ──── 步骤5: 保存JSON ────
report_dir = os.path.join(os.path.dirname(__file__), "..", "reports")
os.makedirs(report_dir, exist_ok=True)

report_json = {
    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "doc_count": len(sep_files),
    "total_raw": total_raw,
    "pc_doc": sum(1 for f in sep_files if classify_exec_mode(f["name"]) == "PC"),
    "online_doc": sum(1 for f in sep_files if classify_exec_mode(f["name"]) == "线上"),
    "pc": {k: v for k, v in pc_data.items() if k != "results"},
    "online": {k: v for k, v in online_data.items() if k != "results"},
    "all": {k: v for k, v in all_data.items() if k != "results"},
    "pc_dup": pc_dup,
    "online_dup": online_dup,
    "all_dup": all_dup,
    # 已修复详情
    "fixed_details": [],
}

# 收集所有已修复记录
for d in [pc_data, online_data]:
    for r in d["results"]:
        if r["is_fixed"]:
            report_json["fixed_details"].append(r)

json_path = os.path.join(report_dir, "2026-09_report_data_v3.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(report_json, f, ensure_ascii=False, indent=2)
print(f"\nJSON已保存: {json_path}")
