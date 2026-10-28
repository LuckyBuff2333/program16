"""从 attached TSV 数据生成 CSV 并导入 case_info"""
import csv
import json
import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src import db
from src.config import setup_logger

logger = setup_logger("import_tsv")


def _safe_float(val):
    if val is None or val == "" or val == "-":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val):
    if val is None or val == "" or val == "-":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _safe_str(val):
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s not in ("-", "None", "nan", "") else None


def _seconds_to_duration(seconds):
    if seconds is None:
        return None
    try:
        s = float(seconds)
        if s < 60:
            return f"{s:.1f}s"
        elif s < 3600:
            return f"{s/60:.1f}min"
        else:
            h, rem = divmod(s, 3600)
            m = rem / 60
            return f"{h:.0f}h{m:.0f}min"
    except (ValueError, TypeError):
        return str(seconds)


def import_from_tsv(tsv_path: str, update_existing: bool = True) -> dict:
    """从 TSV（飞书导出的 tab 分隔文件）导入"""
    if not os.path.isfile(tsv_path):
        return {"error": f"文件不存在: {tsv_path}"}

    print(f"[1/4] 读取 TSV: {tsv_path}")
    rows = []
    with open(tsv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        headers = reader.fieldnames or []
        for row in reader:
            jira = _safe_str(row.get("jira号"))
            if jira:
                rows.append(row)
    print(f"  表头 ({len(headers)} 列)")
    print(f"  数据行: {len(rows)} 条")

    # ── 字段映射 ──
    print(f"\n[2/4] 字段映射...")
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    CORE_FIELDS = {
        "jira号": "case_id",
        "分析结果": "analysis_result",
        "触发来源": "trigger_source",
        "版本号": "version",
        "分析问题时间": "problem_time",
        "分析完成时间": "finish_time",
        "分析重试次数": "retry_count",
        "总耗时": "total_seconds",
        "分析耗时": "analysis_seconds",
        "错误类型": "error_type",
        "错误信息": "error_message",
        "AI分析问题所在模块": "ai_module",
        "问题所在实际模块": "actual_module",
        "分析日期": "analysis_date",
    }
    FLOAT_COLS = {"总耗时", "分析耗时", "access耗时", "reasoning耗时",
                  "adjudication耗时", "reporting耗时", "结果置信度", "ADP置信度"}
    INT_COLS = {"分析重试次数"}
    EXTRA_FIELDS = {
        "版本变动": "version_change", "Jira链接": "jira_link",
        "人工审核结果": "audit_result",
        "access耗时": "access_duration", "reasoning耗时": "reasoning_duration",
        "adjudication耗时": "adjudication_duration", "reporting耗时": "reporting_duration",
        "AI评论总结": "ai_comment_summary", "置信度区间": "conf_interval",
        "分析时长区间": "duration_interval", "错误分类": "error_category",
        "bug状态": "bug_status", "ADP平台报告": "adp_report",
        "问题发生时间": "problem_occur_time", "ADP平台运行时间": "adp_runtime",
        "ADP现象级归因": "adp_attribution", "ADP置信度": "adp_confidence",
        "问题模块": "problem_module", "AI分析问题根因": "ai_root_cause_detail",
        "AI分析结果(飞书链接)": "ai_result_link",
    }

    records = []
    for row in rows:
        jira = _safe_str(row.get("jira号"))
        if not jira:
            continue

        rec = {
            "case_id": jira, "vcu_number": jira,
            "created_at": now, "updated_at": now,
            "is_deleted": False, "converged": False,
            "decision_chain": "[]", "hypothesis_table": "[]",
        }

        for excel_col, db_field in CORE_FIELDS.items():
            val = row.get(excel_col)
            if excel_col in FLOAT_COLS:
                rec[db_field] = _safe_float(val)
            elif excel_col in INT_COLS:
                rec[db_field] = _safe_int(val)
            else:
                rec[db_field] = _safe_str(val)

        # analysis_result → case_status
        result = _safe_str(row.get("分析结果"))
        if result == "成功":
            rec["case_status"] = "已分析"
        elif result == "失败":
            rec["case_status"] = "分析失败"
        else:
            rec["case_status"] = "历史导入"

        # 置信度
        conf_val = _safe_float(row.get("结果置信度"))
        if conf_val is not None:
            rec["conf"] = conf_val / 100 if conf_val > 1 else conf_val

        # duration
        total_sec = rec.get("total_seconds")
        rec["duration"] = _seconds_to_duration(total_sec) if total_sec else _safe_str(row.get("总耗时"))

        # rootcause
        rootcause_val = _safe_str(row.get("rootcause"))
        if rootcause_val:
            rec["rootcause"] = rootcause_val
            rec["root_cause_summary"] = rootcause_val
        else:
            ai_root = _safe_str(row.get("AI分析问题根因"))
            if ai_root:
                rec["root_cause_summary"] = ai_root[:500]

        # problem_desc
        err_type = _safe_str(row.get("错误类型"))
        err_msg = _safe_str(row.get("错误信息"))
        if err_type or err_msg:
            parts = []
            if err_type:
                parts.append(f"[{err_type}]")
            if err_msg:
                parts.append(err_msg)
            rec["problem_desc"] = " ".join(parts)

        # extra_data
        extra = {}
        for excel_col, extra_key in EXTRA_FIELDS.items():
            val = row.get(excel_col)
            str_val = _safe_str(val)
            if str_val:
                if excel_col in FLOAT_COLS:
                    extra[extra_key] = _safe_float(val)
                else:
                    extra[extra_key] = str_val
        if extra:
            rec["extra_data"] = json.dumps(extra, ensure_ascii=False)

        # decision_chain + hypothesis_table（结构化字段）
        from src.services.observability_service import build_decision_chain, build_hypothesis_table
        rec["decision_chain"] = build_decision_chain(
            total_seconds=rec.get("total_seconds"),
            analysis_seconds=rec.get("analysis_seconds"),
            problem_time=rec.get("problem_time"),
            analysis_date=rec.get("analysis_date"),
            analysis_result=rec.get("analysis_result"),
            trigger_source=rec.get("trigger_source"),
            error_type=rec.get("error_type"),
            rootcause=rec.get("rootcause"),
            error_message=rec.get("error_message"),
        )
        rec["hypothesis_table"] = build_hypothesis_table(
            rootcause=rec.get("rootcause"),
            error_type=rec.get("error_type"),
            error_message=rec.get("error_message"),
            ai_module=rec.get("ai_module"),
            actual_module=rec.get("actual_module"),
            analysis_result=rec.get("analysis_result"),
            conf=rec.get("conf"),
        )

        records.append(rec)

    print(f"  有效记录: {len(records)} 条")

    # ── 写入数据库 ──
    print(f"\n[3/4] 写入数据库...")
    session = db._get_session()
    try:
        existing = {r.case_id: r for r in session.query(db.CaseInfo).filter(
            db.CaseInfo.is_deleted == False).all()}
        existing_ids = set(existing.keys())

        new_records = []
        updated_count = 0

        for rec in records:
            cid = rec["case_id"]
            if cid not in existing_ids:
                new_records.append(rec)
            elif update_existing:
                obj = existing[cid]
                for key, val in rec.items():
                    if key in ("id", "case_id", "created_at"):
                        continue
                    if val is not None:
                        setattr(obj, key, val)
                obj.updated_at = now
                updated_count += 1

        for rec in new_records:
            session.add(db.CaseInfo(**rec))
        session.commit()

        print(f"  新增: {len(new_records)} 条")
        print(f"  更新: {updated_count} 条")

        # ── 统计 ──
        print(f"\n[4/4] 导入统计")
        total_in_db = session.query(db.CaseInfo).filter(
            db.CaseInfo.is_deleted == False).count()
        success_count = session.query(db.CaseInfo).filter(
            db.CaseInfo.is_deleted == False,
            db.CaseInfo.analysis_result == "成功").count()
        fail_count = session.query(db.CaseInfo).filter(
            db.CaseInfo.is_deleted == False,
            db.CaseInfo.analysis_result == "失败").count()
        print(f"  数据库总计: {total_in_db} 条")
        print(f"  分析成功: {success_count} 条")
        print(f"  分析失败: {fail_count} 条")

        return {
            "total": len(records),
            "inserted": len(new_records),
            "updated": updated_count,
            "db_total": total_in_db,
        }
    except Exception as e:
        session.rollback()
        logger.error("TSV 导入失败: %s", e)
        print(f"  错误: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}
    finally:
        session.close()


if __name__ == "__main__":
    default_path = os.path.join(PROJECT_ROOT, "data", "bitable_export.tsv")
    tsv_path = sys.argv[1] if len(sys.argv) > 1 else default_path
    print("=" * 60)
    print("  飞书数据沉淀表 → 本地数据库导入")
    print("=" * 60)
    result = import_from_tsv(tsv_path)
    print(f"\n完成: {json.dumps(result, ensure_ascii=False)}")
