"""报表查询路由：日报/周报/抽查/批量执行等报表端点"""
import os
import sys
import time
import threading
from datetime import datetime

from fastapi import APIRouter, Request, Query

from src.config import get_path, load_config, setup_logger, PROJECT_ROOT
from src.schemas.common import ApiResponse
from src.schemas.report import ClassifyDocsRequest

logger = setup_logger("web.report")
router = APIRouter()

# ── 云端看板缓存（按日期，今天 30 分钟 / 历史 24 小时）──
_dashboard_cloud_cache = {}  # {date_str: {"ts": float, "batches": list}}
_dashboard_cache_lock = threading.Lock()
_DASHBOARD_CLOUD_TTL = 120  # 今天: 2 分钟（手动刷新时更新）
_DASHBOARD_HISTORY_TTL = 10 * 365 * 86400  # 历史日期: 永久（数据不会变，除非 force 或云端 JSON 被删）
_DASHBOARD_CACHE_FOLDER = "JXbNfpdzJlJELNdv10Pc5ElVnAc"  # 看板缓存 JSON 文件夹（批次文件夹下的 dashboard_cache 子文件夹，user_access_token 创建）
_dashboard_cloud_index = {}  # {date_str: file_token} 缓存云端 JSON 文件索引
_cloud_json_enabled = True  # 云端 JSON 缓存开关，权限错误后自动关闭
_dashboard_index_loaded = False  # 是否已尝试加载过索引
_cloud_dates_cache = {"ts": 0, "data": None}  # 云端日期列表缓存，5 分钟 TTL
_CLOUD_DATES_TTL = 300  # 5 分钟
_cloud_data_hash = {}  # {key: hash} 记录上次保存的数据哈希，未变化时跳过上传

# ── 主表全量记录缓存（避免 5 处重复拉取 6000+ 条）──
_main_table_cache = {}  # {"ts": float, "data": list, "app_table": str}
_main_table_lock = threading.Lock()
_MAIN_TABLE_TTL = 120  # 2 分钟


def _get_main_table_records(force: bool = False) -> list:
    """获取主表全量记录（共享缓存 + 请求合并，防止并发重复拉取）

    :param force: 强制刷新缓存
    :return: 记录列表，失败返回 []
    """
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    if not app_token or not table_id:
        return []
    cache_key = f"{app_token}:{table_id}"
    # 快速路径：缓存命中且未过期
    if not force:
        cached = _main_table_cache.get(cache_key)
        if cached and time.time() - cached["ts"] < _MAIN_TABLE_TTL:
            return cached["data"]
    # 慢路径：加锁，防止并发请求同时拉取
    with _main_table_lock:
        # 双重检查：可能在等锁期间已被其他线程刷新
        if not force:
            cached = _main_table_cache.get(cache_key)
            if cached and time.time() - cached["ts"] < _MAIN_TABLE_TTL:
                return cached["data"]
        try:
            records = feishu_client.list_bitable_records(app_token, table_id, timeout=60)
            _main_table_cache[cache_key] = {
                "ts": time.time(), "data": records, "app_table": cache_key,
            }
            logger.info("主表全量缓存已刷新: %d 条", len(records))
            return records
        except Exception as e:
            logger.warning("主表全量拉取失败: %s，尝试使用过期缓存", e)
            # 回退到过期缓存（有总比没有好）
            stale = _main_table_cache.get(cache_key)
            if stale:
                logger.info("使用过期缓存: %d 条（%ds 前）",
                            len(stale["data"]), int(time.time() - stale["ts"]))
                return stale["data"]
            return []


# ── 批次详情缓存（内存 + 云端 JSON）──
_batch_detail_cache = {}  # {(date, batch): {"ts": float, "data": dict}}
_BATCH_DETAIL_TTL_TODAY = 300  # 今天: 5 分钟
_BATCH_DETAIL_TTL_HISTORY = 86400  # 历史: 24 小时


# ── 云端批次文件列表缓存（列表本身很贵，5 分钟内复用）──
_cloud_docs_cache = {"ts": 0.0, "data": None}
_cloud_docs_lock = threading.Lock()
_CLOUD_DOCS_TTL = 300


def _list_cloud_docs_all() -> list:
    """列出云端批次文件夹下所有 docx（递归），5 分钟缓存"""
    global _cloud_docs_cache
    now = time.time()
    with _cloud_docs_lock:
        if _cloud_docs_cache["data"] is not None and now - _cloud_docs_cache["ts"] < _CLOUD_DOCS_TTL:
            return _cloud_docs_cache["data"]
    try:
        from src.clients import feishu_client
        from src.api.routes.data import _get_batch_folder_token
        folder_token = _get_batch_folder_token()
        if not folder_token:
            return []
        files = feishu_client.list_folder_files(folder_token, recursive=True) or []
    except Exception as e:
        logger.warning("云端批次列表获取失败: %s", e)
        return _cloud_docs_cache["data"] or []
    with _cloud_docs_lock:
        _cloud_docs_cache = {"ts": now, "data": files}
    return files


def _batch_settled(batch: dict) -> bool:
    """批次是否已执行且分析完成：完成的不再重新下载/重算"""
    detail = batch.get("_detail") or {}
    total = int(batch.get("total") or 0)
    if total and int(detail.get("bt_match") or 0) >= total:
        return True
    if batch.get("has_report") or batch.get("all_failed"):
        return True
    return False


def _refresh_batches_incremental(date_str: str, prev_batches: list = None, force: bool = False) -> tuple:
    """当天批次增量刷新：已完成的批次直接复用，只重新拉取未完成/新增批次

    :return: (batches, reused_names)  reused_names 用于判断详情能否沿用
    """
    from src.api.routes.shared import parse_markdown_batch_table as _parse
    from src.clients import feishu_client

    prev = {b.get("name"): b for b in (prev_batches or []) if b.get("name")}
    docs = [f for f in _list_cloud_docs_all()
            if f.get("folder") == date_str and f.get("type") == "docx" and f.get("token")]
    result = []
    reused_names = set()
    refreshed = 0
    for i, doc in enumerate(docs):
        token = doc.get("token", "")
        name = doc.get("name", "") or token
        old = prev.get(name)
        # 已完成批次永远复用（force 只代表“忽略整日缓存”，不代表要重算已完成批次）
        if old and _batch_settled(old):
            result.append(old)  # 已完成批次：不下载、不重算
            reused_names.add(name)
            continue
        try:
            md = feishu_client.fetch_docx_as_markdown(token)
            rows = _parse(md) or []
        except Exception as e:
            logger.warning("云端批次读取失败 %s/%s: %s", date_str, name, e)
            rows = (old or {}).get("rows") or []
        result.append({"name": name, "token": token, "rows": rows})
        refreshed += 1
        if i < len(docs) - 1:
            time.sleep(0.2)
    result.sort(key=lambda b: b["name"], reverse=True)
    logger.info("看板增量刷新: %s 共 %d 批，复用 %d，刷新 %d",
                date_str, len(result), len(result) - refreshed, refreshed)
    return result, reused_names


def _is_today(date_str: str) -> bool:
    return date_str == datetime.now().strftime("%Y-%m-%d")


def _cache_ttl(date_str: str) -> int:
    """根据日期返回缓存TTL：今天用短TTL，历史日期用长TTL"""
    return _DASHBOARD_CLOUD_TTL if _is_today(date_str) else _DASHBOARD_HISTORY_TTL


def _load_cloud_json_cache(date_str: str) -> list | None:
    """从云端 JSON 缓存加载看板数据，失败返回 None"""
    global _cloud_json_enabled, _dashboard_index_loaded
    if not _cloud_json_enabled:
        return None
    try:
        from src.clients import feishu_client
        import json as _json
        # 如果索引未加载，先列出文件夹构建索引
        if not _dashboard_index_loaded:
            _dashboard_index_loaded = True
            files = feishu_client.list_folder_files(_DASHBOARD_CACHE_FOLDER)
            # 空文件夹是正常的（首次使用），不禁用缓存
            for f in (files or []):
                name = f.get("name", "")
                if name.endswith(".json"):
                    d = name[:-5]  # 去掉 .json
                    _dashboard_cloud_index[d] = f.get("token", "")
        file_token = _dashboard_cloud_index.get(date_str)
        if not file_token:
            return None
        content = feishu_client.download_drive_file(file_token)
        if not content:
            return None
        batches = _json.loads(content.decode("utf-8"))
        if isinstance(batches, list):
            logger.info("看板数据从云端 JSON 缓存加载: %s (%d 个批次)", date_str, len(batches))
            return batches
        return None
    except Exception as e:
        logger.warning("加载云端 JSON 缓存失败(%s): %s", date_str, e)
        _cloud_json_enabled = False
        return None


def _data_hash(obj) -> str:
    """计算数据的哈希值，用于检测数据是否变化"""
    import json as _json
    import hashlib
    return hashlib.md5(_json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _delete_cloud_file_by_name(file_name: str) -> None:
    """在云端缓存文件夹中查找并删除指定名称的文件（去重用）"""
    try:
        from src.clients import feishu_client
        # 优先用索引中的 token 删除
        key = file_name.replace(".json", "")
        old_token = _dashboard_cloud_index.get(key)
        if old_token:
            feishu_client.delete_drive_file(old_token, "file")
            _dashboard_cloud_index.pop(key, None)
            return
        # 索引中没有，列文件夹查找同名文件
        files = feishu_client.list_folder_files(_DASHBOARD_CACHE_FOLDER)
        for f in (files or []):
            if f.get("name") == file_name and f.get("token"):
                feishu_client.delete_drive_file(f["token"], "file")
                logger.info("删除云端重复文件: %s", file_name)
                return
    except Exception as e:
        logger.debug("去重删除云端文件失败(%s): %s", file_name, e)


def _save_cloud_json_cache(date_str: str, batches: list) -> None:
    """将看板数据保存到云端 JSON 缓存（仅历史日期，今天数据不缓存因为一直在变）"""
    global _cloud_json_enabled
    if not _cloud_json_enabled or _is_today(date_str):
        return
    try:
        from src.clients import feishu_client
        # 数据未变化时跳过上传，避免无意义的删除+重新上传
        cache_key = f"dashboard_{date_str}"
        new_hash = _data_hash(batches)
        if _cloud_data_hash.get(cache_key) == new_hash:
            return
        # 上传前先删除同名旧文件，避免云端出现重复文件
        _delete_cloud_file_by_name(f"{cache_key}.json")
        result = feishu_client.upload_json_to_drive(
            batches, cache_key, _DASHBOARD_CACHE_FOLDER)
        if result.get("file_token"):
            _dashboard_cloud_index[date_str] = result["file_token"]
            _cloud_data_hash[cache_key] = new_hash
            logger.info("看板数据已保存到云端 JSON: %s", date_str)
        else:
            _cloud_json_enabled = False
            logger.warning("云端 JSON 缓存上传失败，已自动禁用")
    except Exception as e:
        logger.warning("保存云端 JSON 缓存失败(%s): %s，已自动禁用", date_str, e)
        _cloud_json_enabled = False


def _load_batch_detail_cloud(date_str: str, batch: str) -> dict | None:
    """从云端 JSON 加载批次详情缓存"""
    if not _cloud_json_enabled:
        return None
    try:
        from src.clients import feishu_client
        import json as _json
        # 查找 batch_detail_{date}.json 的 file_token
        key = f"batch_detail_{date_str}"
        token = _dashboard_cloud_index.get(key)
        if not token:
            return None
        content = feishu_client.download_drive_file(token)
        if not content:
            return None
        all_details = _json.loads(content.decode("utf-8"))
        if isinstance(all_details, dict) and batch in all_details:
            logger.info("批次详情从云端缓存加载: %s/%s", date_str, batch)
            return all_details[batch]
    except Exception as e:
        logger.warning("加载批次详情云端缓存失败(%s/%s): %s", date_str, batch, e)
    return None


def _save_batch_detail_cloud(date_str: str, batch: str, data: dict) -> None:
    """将批次详情缓存保存到云端 JSON"""
    global _cloud_json_enabled
    if not _cloud_json_enabled:
        return
    try:
        from src.clients import feishu_client
        import json as _json
        key = f"batch_detail_{date_str}"
        # 读取已有缓存并合并
        all_details = {}
        old_token = _dashboard_cloud_index.get(key)
        if old_token:
            try:
                content = feishu_client.download_drive_file(old_token)
                if content:
                    all_details = _json.loads(content.decode("utf-8"))
            except Exception:
                pass
        all_details[batch] = data
        # 数据未变化时跳过上传
        new_hash = _data_hash(all_details)
        if _cloud_data_hash.get(key) == new_hash:
            return
        # 上传前先删除同名旧文件，避免云端出现重复文件
        _delete_cloud_file_by_name(f"{key}.json")
        result = feishu_client.upload_json_to_drive(
            all_details, key, _DASHBOARD_CACHE_FOLDER)
        if result.get("file_token"):
            _dashboard_cloud_index[key] = result["file_token"]
            _cloud_data_hash[key] = new_hash
            logger.info("批次详情已缓存到云端: %s/%s", date_str, batch)
        else:
            logger.warning("批次详情云端缓存上传失败: %s/%s", date_str, batch)
    except Exception as e:
        logger.warning("保存批次详情云端缓存失败(%s/%s): %s", date_str, batch, e)


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
def classify_comment_docs_api(req: ClassifyDocsRequest):
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
    records = _get_main_table_records()
    if records:
        for rec in records:
            fields = rec.get("fields", {})
            jira_key = _bitable_text(fields.get(bugid_field, ""))
            if jira_key and jira_key in jira_set:
                bt_map.setdefault(jira_key, []).append(
                    _flatten_bitable_record_all(fields, report_field))
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
    records = _get_main_table_records()
    if records:
        for rec in records:
            fields = rec.get("fields", {})
            jira_key = _bitable_text(fields.get(bugid_field, ""))
            if jira_key and jira_key in jira_set:
                bt_map.setdefault(jira_key, []).append(
                    _flatten_bitable_record_all(fields, report_field))
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
async def dashboard_dates():
    """列出所有有批次数据的日期（本地 + 云端，按倒序）"""
    import asyncio
    result = await asyncio.to_thread(_dashboard_dates_sync)
    return result


def _dashboard_dates_sync():
    """日期列表的同步实现"""
    import re as _re
    docs_dir = os.path.join(PROJECT_ROOT, "docs")
    reports_dir = os.path.join(PROJECT_ROOT, "reports")
    date_map = {}  # {date_str: {"batch_count": int, "has_daily_report": bool}}
    # ── 1. 本地 CSV 日期 ──
    if os.path.isdir(docs_dir):
        for d in os.listdir(docs_dir):
            date_dir = os.path.join(docs_dir, d)
            if not os.path.isdir(date_dir):
                continue
            csvs = [f for f in os.listdir(date_dir)
                    if f.endswith(".csv") and (f.startswith("batch_") or f.startswith("prod_batch_"))]
            if csvs:
                daily_html = os.path.join(reports_dir, d, f"daily_report_{d}.html")
                date_map[d] = {
                    "date": d,
                    "batch_count": len(csvs),
                    "has_daily_report": os.path.exists(daily_html),
                }
    # ── 2. 云端日期文件夹（递归统计每个日期的文档数，5 分钟缓存）──
    try:
        from src.clients import feishu_client
        from src.api.routes.data import _get_batch_folder_token
        folder_token = _get_batch_folder_token()
        if folder_token:
            cloud_doc_count = None
            # 使用缓存避免每次打开都做递归列出
            with _dashboard_cache_lock:
                _cd_cached, _cd_ts = _cloud_dates_cache["data"], _cloud_dates_cache["ts"]
            if _cd_cached and time.time() - _cd_ts < _CLOUD_DATES_TTL:
                cloud_doc_count = _cd_cached
            else:
                cloud_files = feishu_client.list_folder_files(folder_token, recursive=True)
                cloud_doc_count = {}
                for f in cloud_files:
                    folder_name = f.get("folder", "")
                    if folder_name and _re.match(r"\d{4}-\d{2}-\d{2}$", folder_name) and f.get("type") in ("docx", "file"):
                        cloud_doc_count[folder_name] = cloud_doc_count.get(folder_name, 0) + 1
                with _dashboard_cache_lock:
                    _cloud_dates_cache["ts"] = time.time()
                    _cloud_dates_cache["data"] = cloud_doc_count
            # 合并到日期列表
            for d, count in cloud_doc_count.items():
                if d not in date_map:
                    daily_html = os.path.join(reports_dir, d, f"daily_report_{d}.html")
                    date_map[d] = {
                        "date": d,
                        "batch_count": count,
                        "has_daily_report": os.path.exists(daily_html),
                    }
                else:
                    date_map[d]["batch_count"] = max(date_map[d]["batch_count"], count)
    except Exception as e:
        logger.warning("获取云端日期列表失败: %s", e)
    dates = sorted(date_map.values(), key=lambda x: x["date"], reverse=True)
    from src.api.routes.shared import ok as _ok
    return _ok(dates)


@router.get("/api/dashboard/data", response_model=ApiResponse)
async def dashboard_data(date: str = Query(default=None, description="日期 YYYY-MM-DD，默认今天"),
                         force: bool = Query(default=False, description="强制刷新（忽略缓存）")):
    """获取指定日期的看板数据：优先云端批次，本地 CSV 作补充"""
    import asyncio
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    result = await asyncio.to_thread(_dashboard_data_sync, date_str, force)
    return result


def _dashboard_data_sync(date_str: str, force: bool = False):
    """看板数据的同步实现（在线程池中执行，避免阻塞事件循环）"""
    import re as _re
    import csv as _csv
    reports_dir = os.path.join(PROJECT_ROOT, "reports", date_str)

    is_today = _is_today(date_str)
    # ── 1. 数据来源：历史日期永久缓存；今天按批次增量刷新 ──
    cloud_batches = None
    with _dashboard_cache_lock:
        cached = _dashboard_cloud_cache.get(date_str)
        cached_batches = (cached or {}).get("batches")
    if not force and cached_batches and time.time() - cached["ts"] < _cache_ttl(date_str):
        cloud_batches = cached_batches
    if cloud_batches is None:
        if is_today:
            # 今天：已执行且分析完的批次直接复用，只刷新未完成/新增的批次
            cloud_batches, _reused_names = _refresh_batches_incremental(date_str, cached_batches, force=force)
        elif not force and cached_batches:
            # 历史：内存里有就永久复用（数据不会变）
            cloud_batches = cached_batches
        else:
            # 历史：云端 JSON 持久缓存 → 原始文档（force 时强制重拉）
            if not force:
                cloud_batches = _load_cloud_json_cache(date_str)
            if cloud_batches is None:
                cloud_batches = _fetch_cloud_batches_for_date(date_str)
                if cloud_batches:
                    _save_cloud_json_cache(date_str, cloud_batches)
        with _dashboard_cache_lock:
            _dashboard_cloud_cache[date_str] = {"ts": time.time(), "batches": cloud_batches}
    # 已完成批次的详情直接沿用（只对本次真正复用的批次生效，刷新的批次会重算）
    _prev_detail = {cb.get("name"): cb.get("_detail")
                    for cb in (cached_batches or []) if cb.get("_detail")}
    _reused_names = locals().get("_reused_names") or set()

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
        if name in _reused_names and _prev_detail.get(name):
            batches[-1]["_detail"] = _prev_detail[name]
        # 生成稳定 key 供本地去重
        seen_names.add((exec_time, total))

    # ── 3. 汇总（仅使用云端数据，不回退本地）──
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

    # ── 4. 预加载批次详情：一次性查多维表格，为所有批次计算 _detail ──
    try:
        from src.clients import feishu_client
        from src.services.report_ops import (
            _flatten_bitable_record_all, _classify_failure, _parse_dur_sec,
        )
        from src.api.routes.shared import bitable_text as _bt
        cfg = load_config().get("feishu_bitable", {})
        app_token = cfg.get("app_token", "")
        table_id = cfg.get("table_id", "")
        bugid_field = cfg.get("bugid_field", "jira号")
        report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
        # 收集所有批次的 jira 号
        all_jira_set = set()
        for b in batches:
            for r in b.get("rows", []):
                jid = (r.get("jira号") or "").strip()
                if jid:
                    all_jira_set.add(jid)
        if all_jira_set:
            pending = [b for b in batches if not b.get("_detail")]
            if not pending:
                records = []
            else:
                records = _get_main_table_records()
            bt_all_map = {}  # {jira: [records]}
            for rec in records:
                fields = rec.get("fields", {})
                jk = _bt(fields.get(bugid_field, ""))
                if jk and jk in all_jira_set:
                    bt_all_map.setdefault(jk, []).append(
                        _flatten_bitable_record_all(fields, report_field))
            # 为每个批次计算详情（已缓存且未刷新的批次跳过）
            for b in (pending if records else []):
                row_list = b.get("rows", [])
                b_ok = b_fail = b_miss = 0
                b_fail_cats = {}
                b_durations = []
                latest_complete = ""  # 最晚分析完成时间
                for row in row_list:
                    jid = (row.get("jira号") or "").strip()
                    if not jid:
                        continue
                    bt_recs = bt_all_map.get(jid, [])
                    if not bt_recs:
                        b_miss += 1
                        continue
                    exec_t = (row.get("执行时间") or "").strip()
                    cands = [x for x in bt_recs if x.get("分析完成时间", "") and x["分析完成时间"] >= exec_t] if exec_t else []
                    if not cands:
                        cands = bt_recs
                    cands.sort(key=lambda x: x.get("分析完成时间", ""))
                    bf = cands[0] if exec_t and cands else cands[-1]  # 执行时间之后最接近的一条
                    dur = _parse_dur_sec(bf.get("分析耗时", ""))
                    if dur > 0:
                        b_durations.append(dur)
                    # 追踪最晚分析完成时间
                    ct = bf.get("分析完成时间", "")
                    if ct and ct > latest_complete:
                        latest_complete = ct
                    if bf.get("分析结果", "") == "成功":
                        b_ok += 1
                    else:
                        b_fail += 1
                        cat = _classify_failure(jid, bf)
                        b_fail_cats[cat] = b_fail_cats.get(cat, 0) + 1
                b_match = b_ok + b_fail
                # 计算批次总耗时（秒）：从执行时间到最后一条分析完成
                total_dur_sec = 0
                batch_exec_time = b.get("exec_time", "")
                if batch_exec_time and latest_complete:
                    try:
                        from datetime import datetime as _dt
                        t_start = _dt.strptime(batch_exec_time, "%Y-%m-%d %H:%M:%S")
                        t_end = _dt.strptime(latest_complete, "%Y-%m-%d %H:%M:%S")
                        diff = int((t_end - t_start).total_seconds())
                        if diff > 0:
                            total_dur_sec = diff
                    except Exception:
                        pass
                detail = {
                    "bt_ok": b_ok, "bt_fail": b_fail, "bt_miss": b_miss,
                    "bt_match": b_match,
                    "rate": round(b_ok / b_match * 100, 1) if b_match else 0,
                    "avg_dur": round(sum(b_durations) / len(b_durations)) if b_durations else 0,
                    "max_dur": max(b_durations) if b_durations else 0,
                    "total_dur": total_dur_sec,
                    "fail_cats": b_fail_cats,
                    "total": len(row_list),
                }
                b["_detail"] = detail
                # 写入缓存
                cache_key = (date_str, b["name"])
                with _dashboard_cache_lock:
                    _batch_detail_cache[cache_key] = {"ts": time.time(), "data": detail}
            logger.info("看板预加载: %s 共 %d 批，本次计算详情 %d 批",
                        date_str, len(batches), len(pending) if records else 0)
    except Exception as e:
        logger.warning("看板批次详情预加载失败: %s", e)

    # 把详情回写到云端批次缓存，供下次「增量刷新」判断哪些批次已完成
    try:
        with _dashboard_cache_lock:
            entry = _dashboard_cloud_cache.get(date_str)
            if entry:
                by_name = {cb.get("name"): cb for cb in entry.get("batches", [])}
                for b in batches:
                    cb = by_name.get(b.get("name"))
                    if cb is not None:
                        cb["_detail"] = b.get("_detail")
                        cb["total"] = b.get("total")
                        cb["has_report"] = b.get("has_report")
                        cb["all_failed"] = b.get("all_failed")
    except Exception as _e:
        logger.warning("回写看板详情缓存失败: %s", _e)

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
    # ── 1. 收集今日所有去重 Jira 号：内存缓存 → 云端 JSON → 原始文档 ──
    cloud_batches = None
    with _dashboard_cache_lock:
        cached = _dashboard_cloud_cache.get(date_str)
        if cached and time.time() - cached["ts"] < _cache_ttl(date_str):
            cloud_batches = cached["batches"]
    if cloud_batches is None:
        cloud_batches = _load_cloud_json_cache(date_str)
        if cloud_batches is None:
            cloud_batches = _fetch_cloud_batches_for_date(date_str)
            if cloud_batches:
                _save_cloud_json_cache(date_str, cloud_batches)
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
            records = _get_main_table_records()
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
    """从云端逐个拉取指定日期的所有批次（含行数据），失败返回 []"""
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
    if not cloud_docs:
        return []

    # 逐个串行拉取，避免并发触发限流
    result = []
    for i, doc in enumerate(cloud_docs):
        token = doc.get("token", "")
        name = doc.get("name", "") or token
        try:
            md = feishu_client.fetch_docx_as_markdown(token)
            rows = _parse(md) or []
        except Exception as e:
            logger.warning("云端批次读取失败 %s/%s: %s", date_str, name, e)
            rows = []
        result.append({"name": name, "token": token, "rows": rows})
        # 文档之间加小间隔，降低限流风险
        if i < len(cloud_docs) - 1:
            time.sleep(0.2)
    # 按名称（含时间）倒序：最新在前
    result.sort(key=lambda b: b["name"], reverse=True)
    return result


@router.get("/api/dashboard/prefetch_range", response_model=ApiResponse)
def dashboard_prefetch_range(
    start_date: str = Query(..., description="起始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
):
    """批量预热指定日期范围的云端看板缓存，只拉取未缓存的日期"""
    try:
        from src.clients import feishu_client
        from src.api.routes.data import _get_batch_folder_token
    except Exception as e:
        logger.warning("预热依赖加载失败: %s", e)
        return {"code": 500, "msg": str(e)}
    folder_token = _get_batch_folder_token()
    if not folder_token:
        return {"code": 200, "data": {"fetched": 0, "cached": 0, "dates": []}}
    # 一次性列出云端所有文件，按日期分组
    try:
        all_files = feishu_client.list_folder_files(folder_token, recursive=True)
    except Exception as e:
        logger.warning("预热列文件失败: %s", e)
        return {"code": 500, "msg": str(e)}
    # 筛选日期范围内的 docx 文件
    from datetime import timedelta
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    # 按日期分组
    date_docs = {}  # {date_str: [doc, ...]}
    for f in all_files:
        folder = f.get("folder", "")
        if not folder or f.get("type") != "docx" or not f.get("token"):
            continue
        try:
            d = datetime.strptime(folder, "%Y-%m-%d")
        except ValueError:
            continue
        if start_dt <= d <= end_dt:
            date_docs.setdefault(folder, []).append(f)
    # 检查哪些日期未缓存
    now = time.time()
    fetched_dates = []
    cached_dates = []
    json_loaded_dates = []
    with _dashboard_cache_lock:
        for date_str in sorted(date_docs.keys()):
            cached = _dashboard_cloud_cache.get(date_str)
            if cached and now - cached["ts"] < _cache_ttl(date_str):
                cached_dates.append(date_str)
                continue
            # 尝试云端 JSON 缓存
            json_batches = _load_cloud_json_cache(date_str)
            if json_batches is not None:
                _dashboard_cloud_cache[date_str] = {"ts": now, "batches": json_batches}
                json_loaded_dates.append(date_str)
                continue
            # 未缓存或已过期，逐个串行拉取原始文档
            docs = date_docs[date_str]
            batches = []
            for i, doc in enumerate(docs):
                token = doc.get("token", "")
                name = doc.get("name", "") or token
                try:
                    md = feishu_client.fetch_docx_as_markdown(token)
                    from src.api.routes.shared import parse_markdown_batch_table as _parse
                    rows = _parse(md) or []
                except Exception as e:
                    logger.warning("预热读取 %s/%s: %s", date_str, name, e)
                    rows = []
                batches.append({"name": name, "token": token, "rows": rows})
                # 文档之间加小间隔，降低限流风险
                if i < len(docs) - 1:
                    time.sleep(0.2)
            batches.sort(key=lambda b: b["name"], reverse=True)
            _dashboard_cloud_cache[date_str] = {"ts": now, "batches": batches}
            # 历史日期保存到云端 JSON
            if batches:
                _save_cloud_json_cache(date_str, batches)
            fetched_dates.append(date_str)
            # 日期间加间隔，避免请求过密触发限流
            time.sleep(0.5)
    logger.info("看板预热完成: 范围 %s~%s, 新拉取 %d 天, JSON缓存 %d 天, 内存缓存 %d 天",
                start_date, end_date, len(fetched_dates), len(json_loaded_dates), len(cached_dates))
    from src.api.routes.shared import ok as _ok
    return _ok({
        "fetched": len(fetched_dates),
        "cached": len(cached_dates),
        "fetched_dates": fetched_dates,
    })


@router.get("/api/dashboard/batch_detail", response_model=ApiResponse)
def dashboard_batch_detail(
    date: str = Query(..., description="日期"),
    batch: str = Query(..., description="批次名"),
    jira_ids: str = Query(default="", description="jira号列表，逗号分隔（云端批次直接传）"),
):
    """获取单个批次的详细信息（含多维表格交叉分析），支持内存+云端两级缓存"""
    import csv as _csv
    from src.api.routes.shared import ok as _ok, fail as _fail

    cache_key = (date, batch)
    ttl = _BATCH_DETAIL_TTL_TODAY if _is_today(date) else _BATCH_DETAIL_TTL_HISTORY

    # ── 1. 内存缓存 ──
    with _dashboard_cache_lock:
        cached = _batch_detail_cache.get(cache_key)
    if cached and time.time() - cached["ts"] < ttl:
        logger.info("批次详情命中内存缓存: %s/%s", date, batch)
        return _ok(cached["data"])

    # ── 2. 云端 JSON 缓存 ──
    cloud_data = _load_batch_detail_cloud(date, batch)
    if cloud_data:
        with _dashboard_cache_lock:
            _batch_detail_cache[cache_key] = {"ts": time.time(), "data": cloud_data}
        return _ok(cloud_data)

    # ── 3. 未命中，查询多维表格 ──
    ids = [x.strip() for x in jira_ids.split(",") if x.strip()]
    rows = []
    if ids:
        rows = [{"jira号": jid, "执行时间": ""} for jid in ids]
    else:
        docs_dir = os.path.join(PROJECT_ROOT, "docs", date)
        csv_path = os.path.join(docs_dir, f"{batch}.csv")
        if not os.path.exists(csv_path):
            return _fail(f"找不到批次 CSV: {batch}")
        with open(csv_path, encoding="utf-8-sig") as fh:
            rows = list(_csv.DictReader(fh))
        rows = [{k.replace("\ufeff", "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()} for r in rows]

    jira_ids_list = [r.get("jira号", "") for r in rows if r.get("jira号")]
    jira_ids_set = set(jira_ids_list)
    bt_map = {}
    bt_ok = bt_fail = bt_miss = 0
    fail_cats = {}
    durations = []
    latest_complete = ""  # 最晚分析完成时间
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
        if jira_ids_set:
            records = _get_main_table_records()
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
                cands = [x for x in bt_recs if x.get("分析完成时间", "") and x["分析完成时间"] >= exec_t] if exec_t else []
                if not cands:
                    cands = bt_recs
                cands.sort(key=lambda x: x.get("分析完成时间", ""))
                bf = cands[0] if exec_t and cands else cands[-1]  # 执行时间之后最接近的一条
                result = bf.get("分析结果", "")
                dur = _parse_dur_sec(bf.get("分析耗时", ""))
                if dur > 0:
                    durations.append(dur)
                # 追踪最晚分析完成时间
                ct = bf.get("分析完成时间", "")
                if ct and ct > latest_complete:
                    latest_complete = ct
                if result == "成功":
                    bt_ok += 1
                else:
                    bt_fail += 1
                    cat = _classify_failure(jid, bf)
                    fail_cats[cat] = fail_cats.get(cat, 0) + 1
    except Exception as e:
        logger.warning("看板批次详情-多维表格查询失败: %s", e)

    bt_match = bt_ok + bt_fail
    avg_dur = round(sum(durations) / len(durations)) if durations else 0
    max_dur = max(durations) if durations else 0
    # 计算批次总耗时（秒）
    total_dur_sec = 0
    import re as _re
    _em = _re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{6})", batch)
    batch_exec_time = ""
    if _em:
        batch_exec_time = f"{_em.group(1)} {_em.group(2)[:2]}:{_em.group(2)[2:4]}:{_em.group(2)[4:]}"
    if batch_exec_time and latest_complete:
        try:
            from datetime import datetime as _dt
            t_start = _dt.strptime(batch_exec_time, "%Y-%m-%d %H:%M:%S")
            t_end = _dt.strptime(latest_complete, "%Y-%m-%d %H:%M:%S")
            diff = int((t_end - t_start).total_seconds())
            if diff > 0:
                total_dur_sec = diff
        except Exception:
            pass

    data = {
        "name": batch, "date": date,
        "bt_ok": bt_ok, "bt_fail": bt_fail, "bt_miss": bt_miss,
        "bt_match": bt_match,
        "rate": round(bt_ok / bt_match * 100, 1) if bt_match else 0,
        "avg_dur": avg_dur, "max_dur": max_dur, "total_dur": total_dur_sec,
        "fail_cats": fail_cats,
        "total": len(rows),
    }

    # ── 4. 写入缓存 ──
    with _dashboard_cache_lock:
        _batch_detail_cache[cache_key] = {"ts": time.time(), "data": data}
    _save_batch_detail_cloud(date, batch, data)

    return _ok(data)


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


# ──────────────────────────────────────────────
# 报告生成 API
# ──────────────────────────────────────────────

@router.post("/api/report/gen_batch", response_model=ApiResponse)
def gen_batch_report(
    date: str = Query(..., description="日期 YYYY-MM-DD"),
    batch: str = Query(default=None, description="批次名，不传则生成该日所有批次"),
):
    """生成单批次 HTML 报告"""
    from src.api.routes.shared import ok as _ok, fail as _fail
    import subprocess as _sp
    cmd = [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "gen_batch_report.py"), date]
    if batch:
        cmd.append(batch)
    try:
        result = _sp.run(cmd, capture_output=True, text=True, timeout=120, cwd=PROJECT_ROOT)
        if result.returncode != 0:
            return _fail(result.stderr or result.stdout or "生成失败")
        # 解析输出获取生成的文件列表
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        return _ok({"message": "\n".join(lines[-3:]), "date": date, "batch": batch})
    except _sp.TimeoutExpired:
        return _fail("生成超时（120秒）")
    except Exception as e:
        logger.error("生成批次报告失败: %s", e, exc_info=True)
        return _fail(f"生成失败: {e}")


@router.post("/api/report/gen_daily", response_model=ApiResponse)
def gen_daily_report(date: str = Query(..., description="日期 YYYY-MM-DD")):
    """生成日报 HTML"""
    from src.api.routes.shared import ok as _ok, fail as _fail
    import subprocess as _sp
    cmd = [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "gen_daily_report.py"), date]
    try:
        result = _sp.run(cmd, capture_output=True, text=True, timeout=120, cwd=PROJECT_ROOT)
        if result.returncode != 0:
            return _fail(result.stderr or result.stdout or "生成失败")
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        return _ok({"message": "\n".join(lines[-3:]), "date": date})
    except _sp.TimeoutExpired:
        return _fail("生成超时（120秒）")
    except Exception as e:
        logger.error("生成日报失败: %s", e, exc_info=True)
        return _fail(f"生成失败: {e}")


@router.post("/api/report/gen_monthly", response_model=ApiResponse)
def gen_monthly_report(year_month: str = Query(..., description="年月，格式 YYYY-MM")):
    """生成月报 HTML"""
    from src.api.routes.shared import ok as _ok, fail as _fail
    import subprocess as _sp
    cmd = [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "generate_monthly_report.py"), year_month]
    try:
        result = _sp.run(cmd, capture_output=True, text=True, timeout=300, cwd=PROJECT_ROOT)
        if result.returncode != 0:
            return _fail(result.stderr or result.stdout or "生成失败")
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        return _ok({"message": "\n".join(lines[-3:]), "year_month": year_month})
    except _sp.TimeoutExpired:
        return _fail("生成超时（300秒）")
    except Exception as e:
        logger.error("生成月报失败: %s", e, exc_info=True)
        return _fail(f"生成失败: {e}")
