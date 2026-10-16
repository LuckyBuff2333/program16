"""报表查询路由：日报/周报/抽查/批量执行等报表端点"""
import os
import time
import threading
from datetime import datetime

from fastapi import APIRouter, Request, Query

from src.config import get_path, load_config, setup_logger, PROJECT_ROOT
from src.schemas.common import ApiResponse
from src.schemas.report import ClassifyDocsRequest

logger = setup_logger("web.report")
router = APIRouter()

# ── 云端看板缓存（按日期，60 秒 TTL）──
_dashboard_cloud_cache = {}  # {date_str: {"ts": float, "batches": list}}
_dashboard_cache_lock = threading.Lock()
_DASHBOARD_CLOUD_TTL = 60

# ── 任务总览缓存（按日期，120 秒 TTL）──
_task_overview_cache = {}  # {date_str: {"ts": float, "data": dict}}
_task_overview_lock = threading.Lock()
_TASK_OVERVIEW_TTL = 120


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


# ──────────────────────────────────────────────
# 数据看板 API
# ──────────────────────────────────────────────

@router.get("/api/dashboard/dates", response_model=ApiResponse)
def dashboard_dates():
    """列出所有有批次 CSV 数据的日期（按倒序）"""
    docs_dir = os.path.join(PROJECT_ROOT, "docs")
    reports_dir = os.path.join(PROJECT_ROOT, "reports")
    dates = []
    if os.path.isdir(docs_dir):
        for d in sorted(os.listdir(docs_dir), reverse=True):
            date_dir = os.path.join(docs_dir, d)
            if not os.path.isdir(date_dir):
                continue
            csvs = [f for f in os.listdir(date_dir)
                    if f.endswith(".csv") and (f.startswith("batch_") or f.startswith("prod_batch_"))]
            if csvs:
                # 检查日报 HTML 是否存在
                daily_html = os.path.join(reports_dir, d, f"daily_report_{d}.html")
                dates.append({
                    "date": d,
                    "batch_count": len(csvs),
                    "has_daily_report": os.path.exists(daily_html),
                })
    from src.api.routes.shared import ok as _ok
    return _ok(dates)


@router.get("/api/dashboard/data", response_model=ApiResponse)
def dashboard_data(date: str = Query(default=None, description="日期 YYYY-MM-DD，默认今天")):
    """获取指定日期的看板数据：优先云端批次，本地 CSV 作补充"""
    import re as _re
    import csv as _csv
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    reports_dir = os.path.join(PROJECT_ROOT, "reports", date_str)

    # ── 1. 云端优先：缓存命中则直接用 ──
    cloud_batches = None
    with _dashboard_cache_lock:
        cached = _dashboard_cloud_cache.get(date_str)
        if cached and time.time() - cached["ts"] < _DASHBOARD_CLOUD_TTL:
            cloud_batches = cached["batches"]
    if cloud_batches is None:
        cloud_batches = _fetch_cloud_batches_for_date(date_str)
        with _dashboard_cache_lock:
            _dashboard_cloud_cache[date_str] = {"ts": time.time(), "batches": cloud_batches}

    batches = []
    seen_names = set()  # 用于本地补充时去重（按 (执行时间+条数) 作为稳定 key）

    # ── 2. 云端批次构建 ──
    for cb in cloud_batches:
        name = cb["name"]
        token = cb["token"]
        rows = cb.get("rows") or []
        total = len(rows)
        if total == 0:
            continue
        # 解析批次名提取执行时间：线上批量执行 YYYY-MM-DD HHMMSS (n/m)
        exec_time = ""
        m = _re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{6})", name)
        if m:
            exec_time = f"{m.group(1)} {m.group(2)[:2]}:{m.group(2)[2:4]}:{m.group(2)[4:]}"
        submit_ok = sum(1 for r in rows if (r.get("执行结果") or "").strip() not in ("失败", ""))
        submit_fail = total - submit_ok
        source = (rows[0].get("触发来源") or "").strip() if rows else ""
        if not source:
            source = "线上" if "线上" in name else "PC"
        model = (rows[0].get("模型") or "").strip() if rows else ""
        all_failed = total > 0 and submit_ok == 0
        # 报告 HTML
        safe = _re.sub(r"[^\w\-.]", "_", name)
        batch_html = os.path.join(reports_dir, f"{safe}_{date_str}.html")
        batch_html_legacy = os.path.join(reports_dir, f"{safe}.html")
        has_report = os.path.exists(batch_html) or os.path.exists(batch_html_legacy)
        report_file = ""
        if os.path.exists(batch_html):
            report_file = f"{safe}_{date_str}.html"
        elif os.path.exists(batch_html_legacy):
            report_file = f"{safe}.html"
        batches.append({
            "name": name, "source": source, "total": total,
            "submit_ok": submit_ok, "submit_fail": submit_fail,
            "exec_time": exec_time, "model": model,
            "has_report": has_report, "report_file": report_file,
            "all_failed": all_failed, "is_cloud": True, "token": token,
            "rows": [{
                "jira号": (r.get("jira号") or "").strip(),
                "执行结果": (r.get("执行结果") or "").strip(),
                "触发时间": (r.get("触发时间") or "").strip(),
                "执行时间": (r.get("执行时间") or "").strip(),
                "备注": (r.get("备注") or "").strip(),
            } for r in rows],
        })
        # 生成稳定 key 供本地去重
        seen_names.add((exec_time, total))

    # ── 3. 本地 CSV 补充（仅云端为空时启用，或本地有而云端无的批次） ──
    docs_dir = os.path.join(PROJECT_ROOT, "docs", date_str)
    if os.path.isdir(docs_dir) and not cloud_batches:
        for f in sorted(os.listdir(docs_dir)):
            if not f.endswith(".csv"):
                continue
            if not (f.startswith("batch_") or f.startswith("prod_batch_")):
                continue
            batch_name = f.replace(".csv", "")
            source = "线上" if f.startswith("prod_batch_") else "PC"
            csv_path = os.path.join(docs_dir, f)
            rows = []
            try:
                with open(csv_path, encoding="utf-8-sig") as fh:
                    rows = list(_csv.DictReader(fh))
            except Exception:
                pass
            total = len(rows)
            if total == 0:
                continue
            submit_ok = sum(1 for r in rows if r.get("执行结果", "").strip() not in ("失败", ""))
            submit_fail = total - submit_ok
            exec_time = rows[0].get("执行时间", "").strip() if rows else ""
            model = rows[0].get("模型", "").strip() if rows else ""
            trigger_src = rows[0].get("触发来源", "").strip() if rows else ""
            if trigger_src:
                source = trigger_src
            if (exec_time, total) in seen_names:
                continue  # 云端已有，跳过
            seen_names.add((exec_time, total))
            batch_html = os.path.join(reports_dir, f"{batch_name}_{date_str}.html")
            batch_html_legacy = os.path.join(reports_dir, f"{batch_name}.html")
            has_report = os.path.exists(batch_html) or os.path.exists(batch_html_legacy)
            report_file = ""
            if os.path.exists(batch_html):
                report_file = f"{batch_name}_{date_str}.html"
            elif os.path.exists(batch_html_legacy):
                report_file = f"{batch_name}.html"
            batches.append({
                "name": batch_name, "source": source, "total": total,
                "submit_ok": submit_ok, "submit_fail": submit_fail,
                "exec_time": exec_time, "model": model,
                "has_report": has_report, "report_file": report_file,
                "all_failed": total > 0 and submit_ok == 0,
                "is_cloud": False, "token": "",
            })

    # ── 4. 汇总 ──
    total_submit = sum(b["total"] for b in batches)
    total_ok = sum(b["submit_ok"] for b in batches)
    total_fail = sum(b["submit_fail"] for b in batches)
    pc_batches = sum(1 for b in batches if b["source"] == "PC")
    online_batches = sum(1 for b in batches if b["source"] != "PC")
    daily_html = os.path.join(reports_dir, f"daily_report_{date_str}.html")
    has_daily_report = os.path.exists(daily_html)
    summary = {
        "total_batches": len(batches),
        "total_submit": total_submit,
        "total_ok": total_ok,
        "total_fail": total_fail,
        "pc_batches": pc_batches,
        "online_batches": online_batches,
        "submit_rate": round(total_ok / total_submit * 100, 1) if total_submit else 0,
        "has_daily_report": has_daily_report,
        "cloud_count": sum(1 for b in batches if b.get("is_cloud")),
    }
    from src.api.routes.shared import ok as _ok
    logger.info("看板数据: %s, %d 批次(云端 %d), %d 提交",
                date_str, len(batches), summary["cloud_count"], total_submit)
    return _ok({"date": date_str, "batches": batches, "summary": summary})


@router.get("/api/dashboard/task_overview", response_model=ApiResponse)
def dashboard_task_overview(
    date: str = Query(default=None, description="日期 YYYY-MM-DD，默认今天"),
    force: bool = Query(default=False, description="强制刷新缓存"),
):
    """任务总览：5 维度统计（执行总数/成功/分析中/待排查/待重试）"""
    from src.api.routes.shared import bitable_text as _bt, ok as _ok
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    # ── 缓存检查 ──
    if not force:
        with _task_overview_lock:
            cached = _task_overview_cache.get(date_str)
            if cached and time.time() - cached["ts"] < _TASK_OVERVIEW_TTL:
                return _ok(cached["data"])
    # ── 1. 收集今日所有去重 Jira 号 ──
    cloud_batches = None
    with _dashboard_cache_lock:
        cached = _dashboard_cloud_cache.get(date_str)
        if cached and time.time() - cached["ts"] < _DASHBOARD_CLOUD_TTL:
            cloud_batches = cached["batches"]
    if cloud_batches is None:
        cloud_batches = _fetch_cloud_batches_for_date(date_str)
        with _dashboard_cache_lock:
            _dashboard_cloud_cache[date_str] = {"ts": time.time(), "batches": cloud_batches}
    jira_exec = {}  # {jira_id: {"exec_ok": bool, "exec_time": str, "trigger_time": str}}
    for cb in cloud_batches:
        for row in (cb.get("rows") or []):
            jid = (row.get("jira号") or "").strip()
            if not jid or jid in jira_exec:
                continue
            result = (row.get("执行结果") or "").strip()
            jira_exec[jid] = {
                "exec_ok": result not in ("失败", ""),
                "exec_time": (row.get("执行时间") or "").strip(),
                "trigger_time": (row.get("触发时间") or "").strip(),
            }
    all_ids = sorted(jira_exec.keys())
    # ── 2. 查多维表格建立分析结果映射（含完成时间/耗时/错误/人工审核） ──
    bt_map = {}  # {jira_id: [{result, done_time, duration, error_info, human_review}, ...]}
    if all_ids:
        try:
            from src.clients import feishu_client
            cfg = load_config().get("feishu_bitable", {})
            app_token = cfg.get("app_token", "")
            table_id = cfg.get("table_id", "")
            bugid_field = cfg.get("bugid_field", "jira号")
            if app_token and table_id:
                records = feishu_client.list_bitable_records(app_token, table_id)
                id_set = set(all_ids)
                for rec in records:
                    fields = rec.get("fields", {})
                    jk = _bt(fields.get(bugid_field, ""))
                    if jk and jk in id_set:
                        bt_map.setdefault(jk, []).append({
                            "result": _bt(fields.get("分析结果", "")).strip(),
                            "done_time": _bt(fields.get("分析完成时间", "")).strip(),
                            "duration": _bt(fields.get("分析耗时", "")).strip(),
                            "error_info": (_bt(fields.get("错误信息", "")) or "")[:120],
                            "human_review": _bt(fields.get("人工审核结果", "")).strip(),
                        })
        except Exception as e:
            logger.warning("任务总览-多维表格查询失败: %s", e)
    # ── 3. 分类统计（时间匹配：只取本次执行后的分析记录） ──
    total_rows, success_rows, analyzing_rows, investigate_rows, retry_rows = [], [], [], [], []
    for jid in all_ids:
        exec_info = jira_exec[jid]
        exec_time = exec_info["exec_time"]
        recs = bt_map.get(jid, [])
        # 按分析完成时间筛选：只取执行时间之后的记录
        matched = [r for r in recs if r["done_time"] and r["done_time"] >= exec_time] if exec_time else recs
        if not matched:
            matched = recs  # 回退到全部记录
        # 取最新一条
        latest = None
        if matched:
            matched.sort(key=lambda r: r["done_time"] or "")
            latest = matched[-1]
        # 构建行数据
        base = {"jira": jid}
        if latest and latest["result"] == "成功":
            success_rows.append({**base, "duration": latest["duration"]})
            total_rows.append({**base, "status": "分析完成"})
        elif not recs:
            total_rows.append({**base, "status": "分析中"})
            analyzing_rows.append({**base, "exec_time": exec_info["exec_time"], "trigger_time": exec_info["trigger_time"]})
        elif exec_info["exec_ok"]:
            total_rows.append({**base, "status": "分析完成" if recs else "分析中"})
            retry_rows.append({**base, "done_time": latest["done_time"] if latest else "", "human_review": latest["human_review"] if latest else ""})
        else:
            total_rows.append({**base, "status": "分析完成" if recs else "分析中"})
            investigate_rows.append({**base, "done_time": latest["done_time"] if latest else "", "error_info": latest["error_info"] if latest else ""})
    result = {
        "total": len(all_ids),
        "all_rows": total_rows,
        "success": {"count": len(success_rows), "rows": success_rows},
        "analyzing": {"count": len(analyzing_rows), "rows": analyzing_rows},
        "investigate": {"count": len(investigate_rows), "rows": investigate_rows},
        "retry": {"count": len(retry_rows), "rows": retry_rows},
    }
    with _task_overview_lock:
        _task_overview_cache[date_str] = {"ts": time.time(), "data": result}
    logger.info("任务总览: %s, 总数=%d 成功=%d 分析中=%d 待排查=%d 待重试=%d",
                date_str, len(all_ids), len(success_rows),
                len(analyzing_rows), len(investigate_rows), len(retry_rows))
    return _ok(result)


def _fetch_cloud_batches_for_date(date_str: str) -> list:
    """从云端拉取指定日期的所有批次（含行数据），失败返回 []"""
    try:
        from src.clients import feishu_client
        from src.api.routes.shared import parse_markdown_batch_table as _parse
        from src.api.routes.data import _get_batch_folder_token
    except Exception as e:
        logger.warning("云端看板依赖加载失败: %s", e)
        return []
    folder_token = _get_batch_folder_token()
    if not folder_token:
        return []
    try:
        all_files = feishu_client.list_folder_files(folder_token, recursive=True)
    except Exception as e:
        logger.warning("云端列文件失败(%s): %s", date_str, e)
        return []
    cloud_docs = [f for f in all_files
                  if f.get("folder") == date_str
                  and f.get("type") == "docx"
                  and f.get("token")]
    result = []
    for doc in cloud_docs:
        token = doc.get("token", "")
        name = doc.get("name", "") or token
        try:
            md = feishu_client.fetch_docx_as_markdown(token)
            rows = _parse(md) or []
        except Exception as e:
            logger.warning("云端批次读取失败 %s/%s: %s", date_str, name, e)
            rows = []
        result.append({"name": name, "token": token, "rows": rows})
    # 按名称（含时间）倒序：最新在前
    result.sort(key=lambda b: b["name"], reverse=True)
    return result


@router.get("/api/dashboard/batch_detail", response_model=ApiResponse)
def dashboard_batch_detail(
    date: str = Query(..., description="日期"),
    batch: str = Query(..., description="批次名"),
    jira_ids: str = Query(default="", description="jira号列表，逗号分隔（云端批次直接传）"),
):
    """获取单个批次的详细信息（含多维表格交叉分析）

    支持两种模式：
    - 云端模式：前端传 jira_ids，后端用其查多维表格
    - 本地模式：后端从 docs/{date}/{batch}.csv 读
    """
    import csv as _csv
    # ── 行数据：优先用前端传的 jira_ids，回退本地 CSV ──
    ids = [x.strip() for x in jira_ids.split(",") if x.strip()]
    rows = []
    if ids:
        rows = [{"jira号": jid, "执行时间": ""} for jid in ids]
    else:
        docs_dir = os.path.join(PROJECT_ROOT, "docs", date)
        csv_path = os.path.join(docs_dir, f"{batch}.csv")
        if not os.path.exists(csv_path):
            from src.api.routes.shared import fail as _fail
            return _fail(f"找不到批次 CSV: {batch}")
        with open(csv_path, encoding="utf-8-sig") as fh:
            rows = list(_csv.DictReader(fh))
        rows = [{k.replace("\ufeff", "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()} for r in rows]

    # ── 多维表格交叉 ──
    jira_ids_list = [r.get("jira号", "") for r in rows if r.get("jira号")]
    jira_ids_set = set(jira_ids_list)
    bt_map = {}
    bt_ok = bt_fail = bt_miss = 0
    fail_cats = {}
    durations = []
    try:
        from src.clients import feishu_client
        from src.services.report_ops import (
            _flatten_bitable_record_all, _classify_failure, _parse_dur_sec,
        )
        cfg = load_config().get("feishu_bitable", {})
        app_token = cfg.get("app_token", "")
        table_id = cfg.get("table_id", "")
        bugid_field = cfg.get("bugid_field", "jira号")
        report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
        if app_token and table_id and jira_ids_set:
            records = feishu_client.list_bitable_records(app_token, table_id)
            from src.api.routes.shared import bitable_text as _bt
            for rec in records:
                fields = rec.get("fields", {})
                jk = _bt(fields.get(bugid_field, ""))
                if jk and jk in jira_ids_set:
                    bt_map.setdefault(jk, []).append(
                        _flatten_bitable_record_all(fields, report_field))
            for r in rows:
                jid = r.get("jira号", "")
                if not jid:
                    continue
                bt_recs = bt_map.get(jid, [])
                if not bt_recs:
                    bt_miss += 1
                    continue
                exec_t = r.get("执行时间", "")
                cands = [x for x in bt_recs if x.get("分析完成时间", "") and x["分析完成时间"] >= exec_t]
                if not cands:
                    cands = bt_recs
                cands.sort(key=lambda x: x.get("分析完成时间", ""))
                ok_recs = [x for x in cands if x.get("分析结果", "") == "成功"]
                bf = ok_recs[0] if ok_recs else cands[-1]
                result = bf.get("分析结果", "")
                dur = _parse_dur_sec(bf.get("分析耗时", ""))
                if dur > 0:
                    durations.append(dur)
                if result == "成功":
                    bt_ok += 1
                else:
                    bt_fail += 1
                    err = (bf.get("错误信息", "") or "")[:80]
                    cat = _classify_failure(jid, bf)
                    fail_cats[cat] = fail_cats.get(cat, 0) + 1
    except Exception as e:
        logger.warning("看板批次详情-多维表格查询失败: %s", e)

    bt_match = bt_ok + bt_fail
    avg_dur = round(sum(durations) / len(durations)) if durations else 0
    max_dur = max(durations) if durations else 0

    from src.api.routes.shared import ok as _ok
    return _ok({
        "name": batch, "date": date,
        "bt_ok": bt_ok, "bt_fail": bt_fail, "bt_miss": bt_miss,
        "bt_match": bt_match,
        "rate": round(bt_ok / bt_match * 100, 1) if bt_match else 0,
        "avg_dur": avg_dur, "max_dur": max_dur,
        "fail_cats": fail_cats,
        "total": len(rows),
    })


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
