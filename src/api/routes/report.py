"""报表查询路由：日报/周报/抽查/批量执行等报表端点"""
import os
from datetime import datetime

from fastapi import APIRouter, Request, Query

from src.config import get_path, load_config, setup_logger, PROJECT_ROOT
from src.schemas.common import ApiResponse
from src.schemas.report import ClassifyDocsRequest

logger = setup_logger("web.report")
router = APIRouter()


@router.get("/api/report/audit_failed", response_model=ApiResponse)
def report_audit_failed():
    """读取当日不达标抽查报表"""
    from src.api.routes.shared import read_csv_rows as _read_csv_rows, ok as _ok
    from src.services.report_ops import _spotcheck_csv_path
    today = datetime.now().strftime("%Y-%m-%d")
    path = _spotcheck_csv_path(f"audit_failed_{today}.csv", today)
    if not os.path.exists(path):
        return _ok([], "今日无不达标数据")
    rows = _read_csv_rows(path)
    return _ok(rows, f"不达标数据 {len(rows)} 条")


@router.post("/api/report/classify_docs", response_model=ApiResponse)
async def classify_comment_docs_api(req: ClassifyDocsRequest):
    """根据执行记录对当天评论分析文档进行分类"""
    from src.core import report as report_module
    from src.api.routes.shared import ok as _ok, fail as _fail
    date_str = (req.date or "").strip() or None
    try:
        result = report_module.classify_comment_docs(date_str)
        return _ok(result, f"分类完成: 达标{result['moved_true']}个, 不达标{result['moved_false']}个, 跳过{result['skipped']}个")
    except Exception as e:
        logger.error("文档分类失败: %s", e, exc_info=True)
        return _fail(f"文档分类失败: {e}")


@router.get("/api/report/daily", response_model=ApiResponse)
def report_daily(date: str = Query(default=None, description="日期 YYYY-MM-DD")):
    """按日期查询结论报表（读取本地 CSV）"""
    from src.api.routes.shared import read_csv_rows as _read_csv_rows, ok as _ok
    from src.services.report_ops import _daily_csv_path
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    return _ok(_read_csv_rows(_daily_csv_path(date_str)))


@router.get("/api/report/daily_refresh", response_model=ApiResponse)
def report_daily_refresh(date: str = Query(default=None, description="日期 YYYY-MM-DD")):
    """刷新今日结论报表：从批次执行记录 + 多维表格拼接报表"""
    from src.api.routes.shared import bitable_text as _bitable_text, ok as _ok
    from src.services.report_ops import (
        _get_report_date_range,
        _read_multi_day_batch_records,
        _flatten_bitable_record_all,
        _classify_failure,
        _parse_dur_sec,
        _format_dur,
        _generate_daily_report,
        _upload_daily_report_to_cloud,
        _sync_daily_stats_to_bitable,
    )
    from src.clients import feishu_client
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    report_dates = _get_report_date_range(date_str)
    jira_exec, dedup_count = _read_multi_day_batch_records(report_dates)
    if not jira_exec:
        return _ok([])
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
    jira_set = set(jira_exec.keys())
    bt_map = {}
    if app_token and table_id:
        try:
            records = feishu_client.list_bitable_records(app_token, table_id)
            for rec in records:
                fields = rec.get("fields", {})
                jira_key = _bitable_text(fields.get(bugid_field, ""))
                if jira_key and jira_key in jira_set:
                    bt_map.setdefault(jira_key, []).append(
                        _flatten_bitable_record_all(fields, report_field))
        except Exception as e:
            logger.warning("今日报表刷新：多维表格查询失败: %s", e)
    BATCH_COLS = ["jira号", "执行结果", "触发时间", "执行时间", "备注"]
    rows = []
    for jira_no, exec_info in jira_exec.items():
        bt_records = bt_map.get(jira_no, [])
        row = {"jira号": jira_no}
        row.update(exec_info)
        if bt_records:
            exec_time = exec_info.get("执行时间", "")
            candidates = [r for r in bt_records
                         if r.get("分析完成时间", "") and r["分析完成时间"] >= exec_time]
            if not candidates:
                candidates = bt_records
            candidates.sort(key=lambda x: x.get("分析完成时间", ""))
            bf = candidates[0]
            row.update(bf)
        else:
            row["分析结果"] = "分析中"
        rows.append(row)
    too_long_threshold = 900
    failed_rows, pending_rows, too_long_success_rows, normal_success_rows = [], [], [], []
    for r in rows:
        analysis_result = r.get("分析结果", "") or ""
        analysis_sec = _parse_dur_sec(r.get("分析耗时", ""))
        is_too_long = analysis_sec > too_long_threshold if analysis_sec > 0 else False
        if analysis_result == "失败":
            cat = _classify_failure(r.get("jira号", ""), r)
            failed_rows.append({**r, "_both": is_too_long, "失败分类": cat})
        elif not analysis_result or analysis_result == "分析中":
            pending_rows.append(r)
        elif is_too_long:
            too_long_success_rows.append(r)
        else:
            normal_success_rows.append(r)
    def _fail_sort_key(r):
        both = r.get("_both", False)
        cat = r.get("失败分类", "")
        is_pending = cat == "待开发排查"
        return (0 if both else 1, 1 if is_pending else 0, cat, r.get("jira号", ""))
    failed_rows.sort(key=_fail_sort_key)
    pending_rows.sort(key=lambda r: r.get("jira号", ""))
    too_long_success_rows.sort(key=lambda r: -_parse_dur_sec(r.get("分析耗时", "")))
    rows = failed_rows + pending_rows + too_long_success_rows + normal_success_rows
    all_keys = list(BATCH_COLS)
    for r in rows:
        for k in r:
            if k not in all_keys and not k.startswith("_"):
                all_keys.append(k)
    if "失败分类" in all_keys and "分析结果" in all_keys:
        all_keys.remove("失败分类")
        idx = all_keys.index("分析结果") + 1
        all_keys.insert(idx, "失败分类")
    for r in rows:
        for k in all_keys:
            r.setdefault(k, "")
    for r in rows:
        for k in list(r.keys()):
            if k.startswith("_"):
                del r[k]
    logger.info("今日结论报表刷新: %s, %d 个 Jira, 多维表格命中 %d, %d 列",
               date_str, len(jira_exec),
               len(jira_exec) - sum(1 for j in jira_exec if j not in bt_map),
               len(all_keys))
    try:
        report = _generate_daily_report(date_str)
        if report.get("total", 0) > 0:
            cloud_url = _upload_daily_report_to_cloud(report, date_str)
            if cloud_url:
                logger.info("前端刷新触发云端文档覆盖: %s", cloud_url)
            _sync_daily_stats_to_bitable(report, date_str)
    except Exception as e:
        logger.warning("前端刷新时云端文档覆盖失败: %s", e)
    return _ok(rows)


@router.get("/api/report/daily_summary", response_model=ApiResponse)
def report_daily_summary(date: str = Query(default=None, description="日期 YYYY-MM-DD")):
    """根据今日结论报表生成汇总统计"""
    from src.api.routes.shared import bitable_text as _bitable_text, ok as _ok
    from src.services.report_ops import (
        _get_report_date_range,
        _read_multi_day_batch_records,
        _flatten_bitable_record_all,
        _classify_failure,
        _parse_dur_sec,
        _format_dur,
    )
    from src.clients import feishu_client
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    report_dates = _get_report_date_range(date_str)
    jira_exec_all, dedup_count = _read_multi_day_batch_records(report_dates)
    jira_exec = {jno: info.get("执行时间", "") for jno, info in jira_exec_all.items()}
    if not jira_exec:
        return _ok({"total": 0, "regression": 0, "success": 0, "fail": 0, "success_rate": "0%",
                     "avg_total_duration": "-", "avg_analysis_duration": "-",
                     "too_long": 0, "failures": {}, "pending": 0, "report_dates": report_dates, "dedup": 0})
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
    jira_set = set(jira_exec.keys())
    bt_map = {}
    if app_token and table_id:
        try:
            records = feishu_client.list_bitable_records(app_token, table_id)
            for rec in records:
                fields = rec.get("fields", {})
                jira_key = _bitable_text(fields.get(bugid_field, ""))
                if jira_key and jira_key in jira_set:
                    bt_map.setdefault(jira_key, []).append(
                        _flatten_bitable_record_all(fields, report_field))
        except Exception as e:
            logger.warning("今日汇总：多维表格查询失败: %s", e)
    success_count = fail_count = pending_count = 0
    durations, analysis_durations = [], []
    too_long_count = 0
    fail_cats, fail_jiras = {}, {}
    pc_count = online_count = 0
    too_long_threshold = 900
    for jira_no, exec_time in jira_exec.items():
        csv_source = jira_exec_all.get(jira_no, {}).get("触发来源", "")
        if csv_source == "jira_analyze":
            pc_count += 1
        elif csv_source == "parseFullTicket":
            online_count += 1
        bt_records = bt_map.get(jira_no, [])
        if not bt_records:
            pending_count += 1
            continue
        candidates = [r for r in bt_records
                     if r.get("分析完成时间", "") and r["分析完成时间"] >= exec_time]
        if not candidates:
            candidates = bt_records
        candidates.sort(key=lambda x: x.get("分析完成时间", ""))
        bf = candidates[0]
        result = bf.get("分析结果", "")
        if result == "成功":
            success_count += 1
        else:
            fail_count += 1
            cat = _classify_failure(jira_no, bf)
            fail_cats[cat] = fail_cats.get(cat, 0) + 1
            if cat not in fail_jiras:
                fail_jiras[cat] = []
            err_short = (bf.get("错误信息", "") or "")[:80]
            fail_jiras[cat].append({"jira号": jira_no, "错误信息": err_short})
        dur = _parse_dur_sec(bf.get("总耗时", ""))
        if dur > 0:
            durations.append(dur)
        analysis_dur = _parse_dur_sec(bf.get("分析耗时", ""))
        if analysis_dur > 0:
            analysis_durations.append(analysis_dur)
            if analysis_dur > too_long_threshold:
                too_long_count += 1
    total = success_count + fail_count + pending_count
    regression_count = total
    success_rate = f"{success_count / total * 100:.1f}%" if total else "0%"
    avg_total_duration = _format_dur(sum(durations) / total) if durations else "-"
    avg_analysis_duration = _format_dur(sum(analysis_durations) / total) if analysis_durations else "-"
    summary = {
        "total": total, "regression": regression_count,
        "success": success_count, "fail": fail_count, "pending": pending_count,
        "success_rate": success_rate,
        "avg_total_duration": avg_total_duration, "avg_analysis_duration": avg_analysis_duration,
        "too_long": too_long_count, "too_long_threshold": too_long_threshold,
        "failures": fail_cats, "failure_jiras": fail_jiras,
        "pc_count": pc_count, "online_count": online_count,
        "report_dates": report_dates, "dedup": dedup_count,
    }
    logger.info("今日汇总: %s, 总 %d, 回归 %d, 成功 %d, 失败 %d, 分析中 %d, 去重 %d",
               date_str, total, regression_count, success_count, fail_count, pending_count, dedup_count)
    return _ok(summary)


@router.get("/api/report/weekly_summary", response_model=ApiResponse)
def report_weekly_summary(date: str = Query(default=None, description="日期 YYYY-MM-DD")):
    """每周汇总"""
    from src.api.routes.shared import ok as _ok, fail as _fail
    from src.services.report_ops import _generate_weekly_report
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    try:
        report = _generate_weekly_report(date_str)
        return _ok(report)
    except Exception as e:
        logger.error("每周汇总生成失败: %s", e, exc_info=True)
        return _fail(f"每周汇总生成失败: {e}")


@router.get("/api/report/range_summary", response_model=ApiResponse)
def report_range_summary(
    start_date: str = Query(..., description="起始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
):
    """时间段汇总"""
    from src.api.routes.shared import ok as _ok, fail as _fail
    from src.services.report_ops import _generate_range_report
    try:
        report = _generate_range_report(start_date, end_date)
        return _ok(report)
    except Exception as e:
        logger.error("时间段汇总生成失败: %s", e, exc_info=True)
        return _fail(f"时间段汇总生成失败: {e}")


@router.get("/api/report/audit", response_model=ApiResponse)
def report_audit():
    """查询抽查审核表格"""
    from src.api.routes.shared import read_csv_rows as _read_csv_rows, ok as _ok
    from src.services.report_ops import _spotcheck_csv_path
    cfg = load_config()["audit"]
    return _ok(_read_csv_rows(_spotcheck_csv_path(cfg["report_file"])))


@router.get("/api/report/audited", response_model=ApiResponse)
def report_audited():
    """查询已抽查记录"""
    from src.api.routes.shared import read_csv_rows as _read_csv_rows, ok as _ok
    cfg = load_config()["audit"]
    return _ok(_read_csv_rows(os.path.join(get_path("report_dir"), cfg["audited_file"])))


@router.get("/api/report/batch", response_model=ApiResponse)
def report_batch(date: str = Query(default=None, description="日期 YYYY-MM-DD")):
    """按日期查询批量执行记录"""
    from src.api.routes.shared import read_csv_rows as _read_csv_rows, ok as _ok
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    doc_dir = get_path("doc_dir")
    day_dir = os.path.join(doc_dir, date_str)
    if not os.path.isdir(day_dir):
        return _ok([])
    all_rows = []
    for fname in sorted(os.listdir(day_dir), reverse=True):
        if not fname.lower().startswith("batch_") or not fname.lower().endswith(".csv"):
            continue
        rows = _read_csv_rows(os.path.join(day_dir, fname))
        for r in rows:
            r["来源文件"] = fname
        all_rows.extend(rows)
    return _ok(all_rows)


@router.get("/api/report/verify", response_model=ApiResponse)
def report_verify(date: str = Query(default=None, description="日期 YYYY-MM-DD")):
    """按日期查询结果验证记录"""
    from src.api.routes.shared import read_csv_rows as _read_csv_rows, ok as _ok
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    scan_dirs = [
        os.path.join(get_path("doc_dir"), date_str),
        os.path.join(PROJECT_ROOT, "data", date_str),
    ]
    all_rows = []
    seen_files = set()
    for day_dir in scan_dirs:
        if not os.path.isdir(day_dir):
            continue
        for fname in sorted(os.listdir(day_dir), reverse=True):
            if "_compare_log" not in fname.lower() or not fname.lower().endswith(".csv"):
                continue
            if fname in seen_files:
                continue
            seen_files.add(fname)
            rows = _read_csv_rows(os.path.join(day_dir, fname))
            for r in rows:
                r["来源文件"] = fname
            all_rows.extend(rows)
    return _ok(all_rows)
