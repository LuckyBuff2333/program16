"""Testing routes - test endpoints"""
from fastapi import APIRouter, Request, Body, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from datetime import datetime, timedelta
import io
import random
import threading

from src import pipeline
from src.config import PROJECT_ROOT, get_path, load_config, setup_logger
from src.core.attachment_guard import begin_batch as _begin_attach_batch
from src.core import doc_generator
from src.schemas.common import ApiResponse
from src.api.routes.shared import (
    _AI_INIT_FIELD_ID,
    _EXCLUDE_REASONS,
    _GMLOGGER_REVIEW_KEYWORDS,
    _STUDY_DIR,
    _UNANALYZED_DIR,
    _bitable_text,
    _build_prod_ai_payload,
    _calc_smoke_duration,
    _compare_single_bug,
    _flatten_bitable_record,
    _get_prod_ai_cfg,
    _get_prod_ai_url,
    _is_bitable_excluded,
    _parse_bugids,
    _parse_reasoning_rounds,
    _scan_study_folders,
    _ts_parse_datetime,
    MAX_EXPAND_BYTES as _MAX_EXPAND_BYTES,
    ExpandBudget as _ExpandBudget,
    check_archive_entries as _check_archive_entries,
    read_upload_limited as _read_upload_limited,
    run_blocking as _run_blocking,
    ok as _ok,
)
from fastapi.responses import JSONResponse as _JSONResponse


# 上传文件解析结果在内存中的保留上限（避免长时间运行内存无限增长）
_MAX_UPLOADED_FILES = 20
_upload_seq = 0

# 错误统计缓存：多维表格全量拉取较慢，60 秒内复用，避免连续查询重复拉全表
_ERROR_STATS_CACHE = {"ts": 0.0, "records": None}
_ERROR_STATS_TTL = 60.0
_ERROR_STATS_LOCK = threading.Lock()


def _adp_text_payload(result: dict) -> dict:
    """ADP 结果回传给前端的文本字段：只给「预览 + 总长度 + 报告路径」

    完整文本（可能几 MB~几十 MB）已经落盘到 docs/adp_results/<key>/，前端按需打开，
    避免把整段文本塞进 SSE 帧/JSON 响应导致页面卡顿与内存暴涨。
    """
    result = result or {}
    full = result.get("full_text") or ""
    return {
        "text_len": result.get("text_len") or len(full),
        "text_preview": result.get("text_preview") or full[:2000],
        "report_path": result.get("report_path", ""),
    }


def _adp_fail_type(result: dict) -> str:
    """ADP 结果的失败类型（失败归因）；成功时为空字符串"""
    result = result or {}
    return result.get("fail_type") or (result.get("results") or {}).get("分析失败归因", "")


def _fail(message: str, extra: dict = None):
    data = {"ok": False, "message": message}
    if extra:
        data.update(extra)
    return _JSONResponse(content=data, status_code=200)


# 上传/解压限额工具统一放在 shared.py，见本文件顶部 import 的
# _read_upload_limited / _check_archive_entries / _ExpandBudget / _MAX_EXPAND_BYTES


logger = setup_logger("web.testing")
router = APIRouter()

# —— 内存级跨批次去重：记录最近执行的 JIRA 号，防止多维表格未及时更新导致重复 ——
import time as _time_mod
_recently_executed = {}  # jira_key -> timestamp
_EXECUTED_TTL = 2 * 3600  # 2小时过期

def _mark_executed(keys: list):
    """ 标记一批 JIRA 号为已执行 """
    now = _time_mod.time()
    for k in keys:
        _recently_executed[k] = now

def _filter_recently_executed(keys: list) -> tuple:
    """ 过滤掉最近已执行的 JIRA 号，返回 (过滤后列表, 排除数量) """
    now = _time_mod.time()
    # 清理过期记录
    expired = [k for k, t in _recently_executed.items() if now - t > _EXECUTED_TTL]
    for k in expired:
        del _recently_executed[k]
    # 过滤
    filtered = [k for k in keys if k not in _recently_executed]
    return filtered, len(keys) - len(filtered)


def _get_same_source_executed_keys(source: str = "parseFullTicket") -> set:
    """读取本地+云端批量执行记录，返回指定来源的已执行Jira号集合

    用于同来源去重：线上执行时只排除线上已执行的，PC执行时只排除PC已执行的。
    PC和线上允许重复（不同来源）。
    同时检查今天和昨天的记录，支持跨天持续执行场景。
    """
    import os, csv
    from src.config import load_config, get_path
    from src.services.report_ops import _read_csv_rows
    executed = set()
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    check_dates = [today.strftime("%Y-%m-%d"), yesterday.strftime("%Y-%m-%d")]
    # 路径1：本地 PC 批量执行记录 docs/日期/batch_*.csv
    doc_dir = get_path("doc_dir")
    for date_str in check_dates:
        day_dir = os.path.join(doc_dir, date_str)
        if os.path.isdir(day_dir):
            for fname in sorted(os.listdir(day_dir)):
                if fname.lower().startswith("batch_") and fname.lower().endswith(".csv"):
                    for row in _read_csv_rows(os.path.join(day_dir, fname)):
                        jira = (row.get("jira号") or row.get("Jira号") or "").strip()
                        src = (row.get("触发来源") or "").strip()
                        if jira and (not source or src == source):
                            executed.add(jira)
    # 路径2：本地上线批量执行记录 data/unanalyzed/prod_batch_{日期}_*.csv
    unanalyzed_dir = os.path.join(PROJECT_ROOT, "data", "unanalyzed")
    if os.path.isdir(unanalyzed_dir):
        for date_str in check_dates:
            prefix = f"prod_batch_{date_str}_"
            for fname in sorted(os.listdir(unanalyzed_dir)):
                if fname.startswith(prefix) and fname.endswith(".csv"):
                    for row in _read_csv_rows(os.path.join(unanalyzed_dir, fname)):
                        jira = (row.get("jira号") or row.get("Jira号") or "").strip()
                        if jira:
                            executed.add(jira)
    # 路径3：云端批次执行记录
    try:
        from src.clients import feishu_client
        folder_token = load_config().get("feishu_bitable", {}).get("batch_folder_token", "")
        if folder_token:
            all_files = feishu_client.list_folder_files(folder_token, recursive=True)
            cloud_docs = [f for f in all_files
                         if f.get("folder", "") in check_dates and f.get("type") == "docx"
                         and (f.get("name", "").startswith("批量执行")
                              or f.get("name", "").startswith("线上批量执行"))]
            for doc in cloud_docs:
                doc_token = doc.get("token", "")
                doc_name = doc.get("name", "")
                if not doc_token:
                    continue
                try:
                    md = feishu_client.fetch_docx_as_markdown(doc_token)
                    # 解析 markdown 表格中的 Jira 号
                    from src.services.report_ops import _parse_markdown_batch_table
                    batch_rows = _parse_markdown_batch_table(md)
                    inferred_source = "parseFullTicket" if doc_name.startswith("线上批量执行") else "jira_analyze"
                    for r in batch_rows:
                        jira = (r.get("jira号") or "").strip()
                        if jira and (not source or inferred_source == source):
                            executed.add(jira)
                except Exception as e:
                    logger.warning("云端批次记录读取失败 %s: %s", doc_name, e)
    except Exception as e:
        logger.warning("读取云端批量执行记录失败: %s", e)
    return executed


@router.post("/api/test/ai_analyze", response_model=ApiResponse)
async def test_ai_analyze(request: Request):
    """AI 日志分析功能测试：阶段1-调接口验证字段（15s）；阶段2-异步监听飞书通知下载文档"""
    import os, re, json
    import asyncio
    import time
    import httpx as _httpx
    from src.clients import feishu_client
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("bugid 不能为空")
    try:
        cfg = load_config()["ai_log_api"]
        # mock 模式：不发真实请求，返回固定的成功响应供联调/测试使用
        if cfg.get("mock", False):
            return _ok({
                "api_response": {"code": 200, "msg": "分析任务已启动(mock)",
                                 "data": {"issue_key": bugid}},
                "api_elapsed": 0.0, "api_success": True, "mock": True,
            }, "mock 模式：AI 分析接口字段校验通过")
        # ── 阶段 1：调用 AI 接口，验证返回字段（15s 内完成）──
        payload = {cfg.get("bugid_field") or "issue_key": bugid}
        trigger_time = body.get("trigger_time") or None
        if trigger_time and cfg.get("trigger_time_field"):
            payload[cfg["trigger_time_field"]] = trigger_time
        api_timeout = int(cfg.get("timeout", 15))
        call_time = time.time()
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, lambda: _httpx.post(cfg["url"], json=payload,
                                      timeout=_httpx.Timeout(api_timeout, connect=8),
                                      headers={"Content-Type": "application/json"},
                                      verify=False)
        )
        api_elapsed = round(time.time() - call_time, 2)
        api_response = resp.json()
        # 验证字段：code=200 + issue_key 一致 + msg 含"已启动"
        resp_code = api_response.get("code")
        resp_msg = str(api_response.get("msg", ""))
        resp_key = (api_response.get("data") or {}).get("issue_key", "")
        api_success = (resp_code == 200 and resp_key == bugid and "已启动" in resp_msg)
        result = {"api_response": api_response, "api_elapsed": api_elapsed, "api_success": api_success}
        if not api_success:
            return _ok(result, f"接口返回不符合预期: code={resp_code}, key={resp_key}")
        # ── 阶段 2：异步监听与“王源泉”的对话，获取「分析完成通知」卡片 ──
        chat_name = cfg.get("chat_name") or "王源泉"
        chat_id = await loop.run_in_executor(None, feishu_client.find_chat_by_name, chat_name)
        if not chat_id:
            return _ok(result, f"接口调用成功，但未找到与 '{chat_name}' 的对话，无法监听完成通知")
        after_ts = str(int(call_time))
        report_link = await loop.run_in_executor(
            None, lambda: feishu_client.poll_message_for_report(
                chat_id, after_ts, poll_interval=15, max_wait=180)
        )
        result["report_link"] = report_link
        if not report_link:
            return _ok(result, "接口调用成功，但未在 180s 内收到飞书完成通知")
        # 下载报告文档
        doc_id = feishu_client.extract_doc_id_from_url(report_link)
        feishu_domain = feishu_client.extract_domain_from_url(report_link)
        if doc_id:
            try:
                md_content = await loop.run_in_executor(
                    None, lambda: feishu_client.fetch_docx_as_markdown(
                        doc_id, bugid=bugid, feishu_domain=feishu_domain)
                )
                doc_path = doc_generator.save_document(bugid, md_content)
                result.update(doc_path=doc_path, content_length=len(md_content),
                              conclusion=doc_generator.parse_conclusion(md_content))
                return _ok(result, f"全流程完成，文档已生成（{len(md_content)} 字）")
            except Exception as e:
                logger.error("飞书文档下载失败: %s", e)
                result["doc_error"] = str(e)
                return _ok(result, f"接口成功+通知已收到，但文档下载失败: {e}")
        return _ok(result, "接口成功+通知已收到，但无法提取文档 ID")
    except Exception as e:
        err_name = type(e).__name__
        if "Connect" in err_name or "10060" in str(e):
            msg = "AI 分析服务连接超时（目标地址不可达），请检查网络或服务状态"
        elif "Timeout" in err_name:
            msg = "AI 分析接口响应超时，请稍后重试或增大超时时间"
        else:
            msg = str(e)
        logger.error("AI 分析功能测试失败: [%s] %s", err_name, e)
        return _fail(msg)


@router.get("/api/test/batch_ai_csv_files", response_model=ApiResponse)
def test_batch_ai_csv_files():
    """列出 data/unanalyzed/ 下可用于功能7批量执行的 CSV 文件"""
    import os, re, json
    import csv as _csv
    files = []
    if os.path.isdir(_UNANALYZED_DIR):
        for fname in sorted(os.listdir(_UNANALYZED_DIR), reverse=True):
            if not fname.endswith(".csv"):
                continue
            fpath = os.path.join(_UNANALYZED_DIR, fname)
            count = 0
            try:
                with open(fpath, "r", encoding="utf-8-sig") as f:
                    reader = _csv.reader(f)
                    next(reader, None)
                    count = sum(1 for _ in reader)
            except Exception:
                pass
            files.append({"name": fname, "path": fpath, "count": count})
    return _ok(files, f"找到 {len(files)} 个 CSV 文件")


@router.post("/api/test/batch_ai_csv_import", response_model=ApiResponse)
async def test_batch_ai_csv_import(request: Request):
    """从 CSV 文件导入 Jira 号及触发时间，去重后返回"""
    import os, re, json
    import csv as _csv
    body = await request.json() or {}
    csv_path = body.get("path", "").strip()
    if not csv_path or not os.path.isfile(csv_path):
        return _fail("CSV 文件不存在")
    rows = []
    csv_trigger_times = {}  # {jira号: 触发时间}，CSV 中已有的触发时间
    seen = set()
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                # 支持多种 Jira 号列名
                jira = (row.get("Jira号") or row.get("jira号") or row.get("JIRA号") or "").strip()
                if not jira or jira in seen:
                    continue
                seen.add(jira)
                # 读取触发时间列（多种列名兼容）
                tt = (row.get("触发时间") or row.get("创建时间") or row.get("执行时间") or row.get("分析执行时间") or "").strip()
                if tt:
                    csv_trigger_times[jira] = tt
                rows.append({"key": jira, "summary": "", "status": "", "created": ""})
    except Exception as e:
        return _fail(f"读取 CSV 失败: {e}")
    if not rows:
        return _fail("CSV 文件中无 Jira 号")
    dup_count = sum(1 for _ in open(csv_path, encoding="utf-8-sig").readlines()) - 1 - len(rows)
    msg = f"导入 {len(rows)} 条 Jira 号（去重后）"
    if csv_trigger_times:
        msg += f"，其中 {len(csv_trigger_times)} 条有触发时间"
    if dup_count > 0:
        msg += f"，去除重复 {dup_count} 条"
    return _ok({"rows": rows, "csv_trigger_times": csv_trigger_times}, msg)


@router.post("/api/test/batch_ai_search", response_model=ApiResponse)
async def test_batch_ai_search(request: Request):
    """步骤1：搜索 Jira JQL 候选 bug，仅保留 key 含 VCU 的，展示完整表格"""
    import os, re, json
    body = await request.json() or {}
    jql = str(body.get("jql", "")).strip()
    if not jql:
        return _fail("JQL 查询语句不能为空")
    try:
        from src.clients import jira_client
        issues = await _run_blocking(jira_client.search_issues, jql, max_results=5000)
        vcu_issues = [i for i in issues if "VCU" in (i.get("key") or "").upper()]
        rows = []
        for i in vcu_issues:
            fields = i.get("fields") or {}
            rows.append({
                "key": (i.get("key") or "").strip(),
                "summary": (fields.get("summary") or "")[:120],
                "status": ((fields.get("status") or {}).get("name") or ""),
                "created": (fields.get("created") or "")[:10],
            })
        return _ok({"total": len(issues), "vcu_count": len(rows), "rows": rows},
                    f"搜索到 {len(issues)} 条，其中 VCU {len(rows)} 条")
    except Exception as e:
        logger.error("批量搜索失败: %s", e)
        return _fail(str(e))


@router.post("/api/test/jira_lookup", response_model=ApiResponse)
async def test_jira_lookup(request: Request):
    """Jira 概要查询：输入支持两种形态
    - 纯 Jira 号（多个用逗号/空格/换行分隔）
    - JQL 查询（如 summary ~ \"关键词\"、key = VCU-123 等）
    返回 key + 概要 + 状态 + 根因
    """
    body = await request.json() or {}
    raw = str(body.get("query", "") or body.get("keys", "") or body.get("bugid", "")).strip()
    if not raw:
        return _fail("请输入 Jira 号或 JQL 查询语句")
    # 判断输入类型：JQL 或纯 Jira 号列表
    jql_keywords = ("summary", "status", "project", "assignee", "reporter", "created",
                    "updated", "resolution", "priority", "issuetype", "type", "labels",
                    "text", "description", "comment", "key", "id", "ORDER BY")
    is_jql = any(kw in raw.lower() for kw in [k.lower() for k in jql_keywords]) \
             or any(op in raw for op in ("~", "!=", ">=", "<=", "~")) \
             or raw.count("=") > 0 and not raw.replace(",", "").replace(" ", "").isalnum()
    try:
        from src.clients import jira_client
        import concurrent.futures as _cf
        rows = []; failed = []

        def _fetch_one(bugid):
            """并发拉取单个 Jira 详情，返回 (row_dict, error_dict)"""
            try:
                detail = jira_client.fetch_issue(bugid)
                fields = detail.get("fields") or {}
                _ai_f = fields.get("customfield_13714")
                _has_ai = bool(_ai_f and str(_ai_f).strip() and str(_ai_f).strip().lower() not in ("none", "null"))
                return {
                    "key": (detail.get("key") or bugid).strip(),
                    "summary": (fields.get("summary") or "")[:200] or "（无概要）",
                    "status": ((fields.get("status") or {}).get("name") or "") or "-",
                    "created": (fields.get("created") or "")[:10] or "-",
                    "root_cause": jira_client.extract_rootcause(detail) or "（未填写）",
                    "has_ai_preliminary": _has_ai,
                }, None
            except Exception as e:
                return None, {"key": bugid, "error": str(e)[:120]}

        if is_jql:
            try:
                issues = await _run_blocking(jira_client.search_issues, raw, max_results=500)
                bugids = [(i.get("key") or "").strip() for i in issues if i.get("key")]
                bugids = [b for b in bugids if b]
                # 并行拉取详情（15路并发）
                with _cf.ThreadPoolExecutor(max_workers=15) as pool:
                    for row, err in pool.map(_fetch_one, bugids):
                        if row:
                            rows.append(row)
                        if err:
                            failed.append(err)
            except Exception as e:
                return _fail(f"JQL 查询失败: {e}")
        else:
            import re
            keys = [k.upper().strip() for k in re.split(r"[,，;；\s]+", raw) if k.strip()]
            seen = set(); dedup = []
            for k in keys:
                if k not in seen:
                    seen.add(k); dedup.append(k)
            # 并行拉取详情（15路并发）
            with _cf.ThreadPoolExecutor(max_workers=15) as pool:
                for row, err in pool.map(_fetch_one, dedup):
                    if row:
                        rows.append(row)
                    if err:
                        failed.append(err)
        msg = f"查询成功 {len(rows)} 条" + (f"，失败 {len(failed)} 条" if failed else "")
        return _ok({"total": len(rows) + len(failed), "success": len(rows),
                    "failed": len(failed), "mode": "jql" if is_jql else "keys",
                    "rows": rows, "errors": failed}, msg)
    except Exception as e:
        logger.error("Jira 查询失败: %s", e)
        return _fail(str(e))


@router.post("/api/test/batch_ai_extract_times/stop", response_model=ApiResponse)
def stop_batch_ai_extract_times():
    """触发批量提取停止信号（优雅停止：当前条目完成后停止后续）"""
    import os, re, json
    from src.api.routes.shared import batch_extract_stop_event as _batch_extract_stop_event
    _batch_extract_stop_event.set()
    logger.info("收到批量提取停止信号，当前条目完成后将停止后续处理")
    return _ok(None, "停止信号已发送，当前条目完成后停止")


@router.post("/api/test/filter_success_jiras", response_model=ApiResponse)
async def filter_success_jiras(request: Request):
    """查询多维表格中已分析成功的 Jira 号（分PC/线上），用于前端过滤"""
    import os, re, json
    import asyncio
    body = await request.json() or {}
    bugids = body.get("bugids") or []
    if not bugids:
        return _ok({"pc_success": [], "online_success": []})
    loop = asyncio.get_event_loop()
    try:
        from src.clients import feishu_client
        cfg = load_config().get("feishu_bitable", {})
        app_token = cfg.get("app_token", "")
        table_id = cfg.get("table_id", "")
        bugid_field = cfg.get("bugid_field", "jira号")
        if not app_token or not table_id:
            return _ok({"pc_success": [], "online_success": []})
        records = await loop.run_in_executor(
            None, feishu_client.list_bitable_records, app_token, table_id)
        bugid_set = set(bugids)
        pc_success, online_success = set(), set()
        for rec in records:
            fields = rec.get("fields", {})
            jk = _bitable_text(fields.get(bugid_field, ""))
            if not jk or jk not in bugid_set:
                continue
            result = _bitable_text(fields.get("分析结果", ""))
            if result != "成功":
                continue
            source = _bitable_text(fields.get("触发来源", ""))
            if source == "jira_analyze":
                pc_success.add(jk)
            else:
                online_success.add(jk)
        logger.info("过滤已成功: PC %d, 线上 %d (查询 %d 个 Jira)",
                   len(pc_success), len(online_success), len(bugids))
        return _ok({"pc_success": list(pc_success), "online_success": list(online_success)})
    except Exception as e:
        logger.warning("查询已成功 Jira 失败: %s", e)
        return _ok({"pc_success": [], "online_success": []})


@router.post("/api/test/batch_ai_extract_times", response_model=ApiResponse)
async def test_batch_ai_extract_times(request: Request):
    """步骤2：批量提取所有候选的触发时间，SSE 实时推送进度"""
    import os, re, json
    import asyncio
    import json as _json
    from src.api.routes.shared import batch_extract_stop_event as _batch_extract_stop_event
    from src.services.trigger_ops import (
        _load_cloud_trigger_cache, _ensure_trigger_time_bugid_cache,
        _batch_save_trigger_times_to_cloud, _save_trigger_time_to_csv, remember_ref_time,
    _timestudy_record,
    )
    from src.services.report_ops import _load_bitable_success_jiras
    from src.services.server_legacy import _diag_extract_time_from_video_simple, _has_gmlogger_logs, _diag_extract_time_from_images, _diag_gmlogger_times
    body = await request.json() or {}
    keys = body.get("keys") or []
    filter_existing = body.get("filter_existing", False)  # 过滤多维表格中已有数据
    video_fallback = body.get("video_fallback", False)    # 用视频提取兜底
    refresh_cache = body.get("refresh_cache", False)      # 云端缓存更新：有缓存也重新提取
    re_extract_empty = body.get("re_extract_empty", False) # 空标记重新提取
    parallel = body.get("parallel", False)                   # 并行提取（3路并发）
    if not keys:
        return _fail("候选列表为空，请先执行步骤1")

    async def event_generator():
        import signal
        import threading
        import concurrent.futures
        loop = asyncio.get_event_loop()
        stop_event = threading.Event()
        _prev_handler = signal.getsignal(signal.SIGINT)

        def _on_sigint(sig, frame):
            logger.info("收到 Ctrl+C，正在停止时间提取...")
            stop_event.set()

        signal.signal(signal.SIGINT, _on_sigint)
        try:
            _batch_extract_stop_event.clear()  # 新批次开始时清除停止标志
            _begin_attach_batch()              # 新批次：重置附件下载预算
            # 加载云端已有时间 + 所有已处理的 jira 号 + 成功分析记录（用于缓存过期判断，合并加载避免两次全量拉取）
            (cloud_times, cloud_keys), success_jiras = await asyncio.gather(
                loop.run_in_executor(None, _load_cloud_trigger_cache),
                loop.run_in_executor(None, _load_bitable_success_jiras),
            )
            # 过滤多维表格中已有数据（不论成功/失败，只要出现过就排除）
            bitable_exclude = set()
            if filter_existing:
                try:
                    from src.clients import feishu_client
                    bitable_records = await loop.run_in_executor(
                        None, feishu_client.list_bitable_records,
                        load_config().get("feishu_bitable", {}).get("app_token", ""),
                        load_config().get("feishu_bitable", {}).get("table_id", ""))
                    bf = load_config().get("feishu_bitable", {}).get("bugid_field", "jira号")
                    for rec in bitable_records:
                        fields = rec.get("fields", {})
                        fv = fields.get(bf, "")
                        if isinstance(fv, list):
                            fv = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in fv)
                        elif isinstance(fv, dict):
                            fv = fv.get("text", str(fv))
                        jk = str(fv).strip()
                        if jk:
                            bitable_exclude.add(jk)
                    logger.info("多维表格过滤: 排除 %d 个已有Jira号", len(bitable_exclude))
                except Exception as e:
                    logger.warning("多维表格过滤查询失败（跳过）: %s", e)
            # 加载已修正/已确认的诊断缓存记录（缓存更新时跳过这些）
            corrected_jiras = set()
            _cache_dir = os.path.join(PROJECT_ROOT, "data", "troubleshoot")
            if os.path.isdir(_cache_dir):
                for _fname in os.listdir(_cache_dir):
                    if not _fname.endswith(".json"):
                        continue
                    try:
                        with open(os.path.join(_cache_dir, _fname), "r", encoding="utf-8") as _f:
                            _c = _json.load(_f)
                        if _c.get("verify_status") in ("corrected", "success"):
                            corrected_jiras.add(_c.get("bugid", _fname[:-5]))
                    except Exception:
                        pass
            trigger_times = {}
            sources = {}
            need_fetch = []
            skip_empty = 0
            skip_bitable = 0
            skip_corrected = 0
            old_cache = {}  # refresh_cache 时保存旧缓存，提取失败时回退
            for key in keys:
                if key in bitable_exclude:
                    # 多维表格中已有，直接跳过
                    sources[key] = "已存在(多维表)"
                    skip_bitable += 1
                    continue
                if refresh_cache:
                    # 已修正/已确认的记录跳过重新提取
                    if key in corrected_jiras:
                        trigger_times[key] = cloud_times.get(key, "")
                        sources[key] = "已修正(跳过)"
                        skip_corrected += 1
                        continue
                    # 强制重新提取：记录旧缓存值，放入 need_fetch
                    if key in cloud_times:
                        old_cache[key] = cloud_times[key]
                    need_fetch.append(key)
                elif key in cloud_times:
                    # 云端有触发时间，直接使用（包含用户手动修正的值）
                    trigger_times[key] = cloud_times[key]
                    sources[key] = "云端缓存"
                elif key in cloud_keys and not re_extract_empty:
                    # 云端已记录但无触发时间（之前提取为空），跳过
                    sources[key] = "已标记空"
                    skip_empty += 1
                else:
                    need_fetch.append(key)
            cloud_hit = len(trigger_times)
            total = len(keys)
            yield f"data: {_json.dumps({'type': 'start', 'total': total, 'local_hit': cloud_hit, 'need_fetch': len(need_fetch), 'skip_empty': skip_empty, 'skip_bitable': skip_bitable, 'skip_corrected': skip_corrected, 'refresh_cache': refresh_cache, 're_extract_empty': re_extract_empty, 'parallel': parallel}, ensure_ascii=False)}\n\n"
            # 对未处理过的走接口提取
            done_count = cloud_hit + skip_empty
            empty_count = 0
            skip_no_gmlogger = 0
            interrupted = False
            # 预加载 bugid 缓存 + 初始化批量写入缓冲区（避免逐条写入和重复加载云端表）
            await loop.run_in_executor(None, _ensure_trigger_time_bugid_cache)
            _write_buffer = []  # [(bugid, trigger_time)] 缓冲 20 条批量写入
            _WRITE_BATCH_SIZE = 20
            if need_fetch:
                from src.clients import jira_client as _jc
                _ocr_sem = asyncio.Semaphore(2)  # OCR 并发限制：最多 2 路同时 GPU 推理，避免显存争抢

                def _lookup_ref_local(bid):
                    from src.services.trigger_ops import _lookup_ref as _lr
                    return _lr(bid)

                def _self_check_local(tt, ref):
                    from src.services.trigger_ops import self_check_trigger_time as _sc
                    return _sc(tt, ref)

                async def _process_one(key):
                    """处理单条触发时间提取，返回 (key, status, tt_val)"""
                    def _should_stop():
                        return _batch_extract_stop_event.is_set() or stop_event.is_set()
                    status = "success"
                    tt_val = ""
                    try:
                        if _should_stop():
                            return key, "stopped", ""
                        issue = await asyncio.wait_for(
                            loop.run_in_executor(None, _jc.fetch_issue, key),
                            timeout=30)
                        if _should_stop():
                            return key, "stopped", ""
                        attachments = (issue.get("fields") or {}).get("attachment") or []
                        # 登记日志包参考时间，供写表时做自检（时间差秒/窗口命中）
                        try:
                            _gm_times = _diag_gmlogger_times(attachments) or []
                            if _gm_times:
                                _g0 = _gm_times[0][0] if isinstance(_gm_times[0], tuple) else _gm_times[0]
                                remember_ref_time(key, _g0.strftime("%Y-%m-%d %H:%M:%S") if hasattr(_g0, "strftime") else str(_g0)[:19])
                        except Exception as _e:
                            logger.debug("登记参考时间失败 %s: %s", key, _e)
                        _has_log = await loop.run_in_executor(None, _has_gmlogger_logs, attachments, key)
                        if not _has_log:
                            # 无gmlogger且包内无main → 不写空标记，下次仍可重新检查
                            return key, "no_gmlogger", ""
                        if _should_stop():
                            return key, "stopped", ""
                        tt = ""
                        if video_fallback:
                            # 勾选"视频提取优先"：视频 → 评论 → 图片
                            async with _ocr_sem:
                                if _should_stop():
                                    return key, "stopped", ""
                                video_tt = await loop.run_in_executor(
                                    None, _diag_extract_time_from_video_simple, issue)
                            if video_tt:
                                tt = video_tt
                                sources[key] = "视频提取"
                            if not tt:
                                tt = await _run_blocking(_jc.extract_trigger_time_from_issue, issue, skip_attachment=True)
                                if tt:
                                    sources[key] = "新提取"
                        else:
                            # 默认不勾选：评论 → 视频 → 图片
                            tt = await _run_blocking(_jc.extract_trigger_time_from_issue, issue, skip_attachment=True)
                            if tt:
                                sources[key] = "新提取"
                            if not tt:
                                async with _ocr_sem:
                                    if _should_stop():
                                        return key, "stopped", ""
                                    video_tt = await loop.run_in_executor(
                                        None, _diag_extract_time_from_video_simple, issue)
                                if video_tt:
                                    tt = video_tt
                                    sources[key] = "视频提取"
                        # 图片OCR最终兜底（两种模式都走）
                        if not tt:
                            if _should_stop():
                                return key, "stopped", ""
                            cfg_api = load_config().get("jira_api", {})
                            img_h = {}
                            img_tok = cfg_api.get("token", "")
                            if img_tok:
                                img_h["Authorization"] = f"Bearer {img_tok}"
                            img_to = max(int(cfg_api.get("timeout", 30)), 120)
                            img_tt, _ = _diag_extract_time_from_images(issue, img_h, img_to, key)
                            if img_tt:
                                tt = img_tt
                                sources[key] = "图片提取"
                        # 附件文件名最终兑底
                        if not tt:
                            att_tt = _jc.extract_attachment_time(issue)
                            if att_tt:
                                tt = att_tt
                                sources[key] = "附件名"
                        if tt:
                            trigger_times[key] = tt
                            tt_val = tt
                            _write_buffer.append((key, tt))
                            # P0-1：把本次提取写入自学习记录（来源/参考时间/时间差）
                            try:
                                _ref = _lookup_ref_local(key)
                                _chk = _self_check_local(tt, _ref)
                                _vids = sum(1 for a in attachments if (a.get("mimeType", "") or "").startswith("video"))
                                _gms = len(_diag_gmlogger_times(attachments) or [])
                                _timestudy_record(
                                    key, tt, sources.get(key, ""),
                                    ctx={"ref_times": _ref,
                                         "match_diff": "" if _chk.get("diff_sec") is None else str(_chk["diff_sec"]),
                                         "video_count": _vids, "gm_count": _gms})
                            except Exception as _e:
                                logger.debug("写自学习记录失败 %s: %s", key, _e)
                        else:
                            if key in old_cache:
                                trigger_times[key] = old_cache[key]
                                sources[key] = "旧缓存"
                                tt_val = old_cache[key]
                            else:
                                status = "empty"
                                sources[key] = "空标记"
                                _write_buffer.append((key, ""))
                    except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
                        status = "error"
                        logger.warning("提取触发时间超时 %s", key)
                    except Exception as e:
                        status = "error"
                        logger.warning("提取触发时间失败 %s: %s", key, e)
                    return key, status, tt_val

                if parallel and len(need_fetch) > 1:
                    # ── 并行模式：从配置读取并发数 ──
                    _trigger_parallel = load_config().get("params", {}).get("trigger_parallel", 8)
                    sem = asyncio.Semaphore(_trigger_parallel)
                    _active_tasks = set()  # 正在执行 _process_one 的任务（不可取消）
                    async def _sem_process(key):
                        async with sem:
                            if interrupted or _batch_extract_stop_event.is_set() or stop_event.is_set():
                                return key, "skipped", ""
                            # 已进入执行区，加入 active 集合（不会被 cancel）
                            task = asyncio.current_task()
                            _active_tasks.add(task)
                            try:
                                return await _process_one(key)
                            except asyncio.CancelledError:
                                return key, "cancelled", ""
                            finally:
                                _active_tasks.discard(task)
                    tasks = [asyncio.ensure_future(_sem_process(k)) for k in need_fetch]
                    for coro in asyncio.as_completed(tasks):
                        if await request.is_disconnected():
                            interrupted = True
                            for t in tasks:
                                if not t.done():
                                    t.cancel()
                            break
                        key, status, tt_val = await coro
                        if status in ("skipped", "stopped", "cancelled"):
                            continue
                        # Ctrl+C 后：cancel 队列中的任务，让正在执行的跑完
                        if not interrupted and (stop_event.is_set() or _batch_extract_stop_event.is_set()):
                            interrupted = True
                            for t in tasks:
                                if not t.done() and t not in _active_tasks:
                                    t.cancel()  # 只 cancel 队列中未开始的
                        if status == "no_gmlogger":
                            sources[key] = "无gmlogger"
                            skip_no_gmlogger += 1
                        elif status == "empty":
                            empty_count += 1
                        elif status == "error":
                            pass
                        done_count += 1
                        yield f"data: {_json.dumps({'type': 'progress', 'index': done_count, 'total': total, 'key': key, 'status': status, 'time': tt_val}, ensure_ascii=False)}\n\n"
                        if len(_write_buffer) >= _WRITE_BATCH_SIZE:
                            # 云端写入（失败不影响本地）
                            try:
                                batch_items = dict(_write_buffer)
                                await loop.run_in_executor(None, _batch_save_trigger_times_to_cloud, batch_items)
                            except Exception as e:
                                logger.warning("并行批量写入触发时间(云端)失败: %s", e)
                            # 本地 CSV 写入（独立保护，绝不跳过）
                            try:
                                for bid, btt in _write_buffer:
                                    _save_trigger_time_to_csv(bid, btt)
                                logger.info("并行批量写入触发时间: %d 条", len(_write_buffer))
                            except Exception as e:
                                logger.warning("并行批量写入触发时间(本地CSV)失败: %s", e)
                            _write_buffer.clear()
                else:
                    # ── 串行模式：逐条处理 ──
                    for i, key in enumerate(need_fetch):
                        if _batch_extract_stop_event.is_set():
                            logger.info("前端停止信号触发，优雅中断（已完成 %d/%d）", i, len(need_fetch))
                            interrupted = True
                            break
                        if stop_event.is_set():
                            logger.info("Ctrl+C 中断提取（已完成 %d/%d）", i, len(need_fetch))
                            interrupted = True
                            break
                        if await request.is_disconnected():
                            logger.info("客户端已断开，提取中断（已完成 %d/%d）", i, len(need_fetch))
                            interrupted = True
                            break
                        key, status, tt_val = await _process_one(key)
                        if status == "stopped":
                            logger.info("前端停止信号触发（_process_one内部检测），优雅中断（已完成 %d/%d）", i, len(need_fetch))
                            interrupted = True
                            break
                        if status == "no_gmlogger":
                            sources[key] = "无gmlogger"
                            skip_no_gmlogger += 1
                        elif status == "empty":
                            empty_count += 1
                        done_count += 1
                        yield f"data: {_json.dumps({'type': 'progress', 'index': done_count, 'total': total, 'key': key, 'status': status, 'time': tt_val}, ensure_ascii=False)}\n\n"
                        if len(_write_buffer) >= _WRITE_BATCH_SIZE:
                            # 云端写入（失败不影响本地）
                            try:
                                batch_items = dict(_write_buffer)
                                await loop.run_in_executor(None, _batch_save_trigger_times_to_cloud, batch_items)
                            except Exception as e:
                                logger.warning("批量写入触发时间(云端)失败: %s", e)
                            # 本地 CSV 写入（独立保护，绝不跳过）
                            try:
                                for bid, btt in _write_buffer:
                                    _save_trigger_time_to_csv(bid, btt)
                                logger.info("批量写入触发时间: %d 条", len(_write_buffer))
                            except Exception as e:
                                logger.warning("批量写入触发时间(本地CSV)失败: %s", e)
                            _write_buffer.clear()
            # 最终批量写入缓冲区剩余数据
            if _write_buffer:
                # 云端写入（失败不影响本地）
                try:
                    batch_items = dict(_write_buffer)
                    await loop.run_in_executor(None, _batch_save_trigger_times_to_cloud, batch_items)
                except Exception as e:
                    logger.warning("最终批量写入触发时间(云端)失败: %s", e)
                # 本地 CSV 写入（独立保护，绝不跳过）
                try:
                    for bid, btt in _write_buffer:
                        _save_trigger_time_to_csv(bid, btt)
                    logger.info("最终批量写入触发时间: %d 条", len(_write_buffer))
                except Exception as e:
                    logger.warning("最终批量写入触发时间(本地CSV)失败: %s", e)
                _write_buffer.clear()
            new_count = len(trigger_times) - cloud_hit
            if interrupted:
                logger.info("提取被 Ctrl+C 中断: 已完成 %d 条（云端命中 %d, 新提取 %d, 无gmlogger %d）",
                            done_count, cloud_hit, new_count, skip_no_gmlogger)
            else:
                logger.info("批量提取触发时间: 云端命中 %d, 跳过空 %d, 无gmlogger %d, 新提取 %d, 本次空 %d, 共 %d/%d",
                            cloud_hit, skip_empty, skip_no_gmlogger, new_count, empty_count, len(trigger_times), total)
            yield f"data: {_json.dumps({'type': 'done', 'time_count': len(trigger_times), 'total': total, 'local_hit': cloud_hit, 'new_count': new_count, 'empty_count': empty_count, 'skip_empty': skip_empty, 'skip_bitable': skip_bitable, 'skip_corrected': skip_corrected, 'skip_no_gmlogger': skip_no_gmlogger, 'interrupted': interrupted, 'trigger_times': trigger_times, 'sources': sources}, ensure_ascii=False)}\n\n"
        finally:
            signal.signal(signal.SIGINT, _prev_handler)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/test/video_ocr_stats", response_model=ApiResponse)
def video_ocr_stats():
    """视频 OCR 统计（进程内累计）：整帧/ROI/跳帧/投票命中

    用于观察几天真实数据后，判断 ROI 兜底是否值得保留。
    """
    from src.services.server_legacy import _VIDEO_OCR_STATS
    return _ok(dict(_VIDEO_OCR_STATS), "视频 OCR 统计（服务重启后清零）")


@router.post("/api/test/batch_ai_filter", response_model=ApiResponse)
async def test_batch_ai_filter(request: Request):
    """步骤3：过滤候选记录。顺序：多维表格去重 → AI初步分析过滤"""
    import os, re, json
    body = await request.json() or {}
    keys = body.get("keys") or []
    filter_all = body.get("filter_all", False)
    filter_pc_only = body.get("filter_pc_only", False)
    filter_online_only = body.get("filter_online_only", False)
    filter_ai_preliminary = body.get("filter_ai_preliminary", False)
    filter_existing_success = body.get("filter_existing_success", False)
    if not keys:
        return _fail("候选列表为空，请先执行步骤1")
    # —— 第1步：多维表格去重（filter_all / 指定来源 / 过滤已成功 时启用）——
    exclude_keys = set()
    use_bitable = filter_all or filter_pc_only or filter_online_only or filter_existing_success
    records = []
    if use_bitable:
        try:
            import asyncio
            from src.clients import feishu_client
            loop = asyncio.get_event_loop()
            records = await loop.run_in_executor(None, feishu_client.list_bitable_records,
                                                 load_config().get("feishu_bitable", {}).get("app_token", ""),
                                                 load_config().get("feishu_bitable", {}).get("table_id", ""))
            bugid_field = load_config().get("feishu_bitable", {}).get("bugid_field", "jira号")
            key_set = set(keys)  # 候选集合，用于快速匹配
            for rec in records:
                fields = rec.get("fields", {})
                fv = fields.get(bugid_field, "")
                if isinstance(fv, list):
                    fv = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in fv)
                elif isinstance(fv, dict):
                    fv = fv.get("text", str(fv))
                jira_key = str(fv).strip()
                if not jira_key or jira_key not in key_set:
                    continue  # 不在候选列表中，跳过
                trigger_source = _bitable_text(fields.get("触发来源", ""))
                is_pc = trigger_source == "jira_analyze"
                is_excluded = _is_bitable_excluded(fields, bugid_field)
                # 排除逻辑
                if filter_all:
                    exclude_keys.add(jira_key)  # 过滤所有已存在
                elif filter_existing_success and is_excluded:
                    # 区分来源：线上模式只排除线上成功的，PC模式只排除PC成功的
                    # is_pc=True表示PC来源(jira_analyze)，is_pc=False表示线上来源(parseFullTicket)
                    is_online_record = not is_pc
                    if filter_online_only and is_online_record:
                        exclude_keys.add(jira_key)  # 线上模式：只排除线上分析成功的
                    elif filter_pc_only and is_pc:
                        exclude_keys.add(jira_key)  # PC模式：只排除PC分析成功的
                    elif not filter_online_only and not filter_pc_only:
                        exclude_keys.add(jira_key)  # 未指定来源时：排除所有成功的
                elif filter_pc_only and filter_online_only:
                    if is_excluded:
                        exclude_keys.add(jira_key)
                elif filter_pc_only:
                    if is_pc and is_excluded:
                        exclude_keys.add(jira_key)
                elif filter_online_only:
                    if not is_pc and is_excluded:
                        exclude_keys.add(jira_key)
                elif is_excluded:
                    exclude_keys.add(jira_key)  # 默认：分析成功的排除
        except Exception as e:
            logger.warning("多维表格重复过滤查询失败（跳过此检查）: %s", e)
    bitable_removed = len(exclude_keys)  # ① 多维表格去重条数（后续云端去重会在此基础上累加）
    # —— 第1.5步：同来源云端批量记录去重（默认模式 + 指定来源时使用）——
    if not filter_all:
        if filter_pc_only:
            cloud_sources = ["jira_analyze"]
        elif filter_online_only:
            cloud_sources = ["parseFullTicket"]
        else:
            cloud_sources = ["jira_analyze", "parseFullTicket"]
        for cs in cloud_sources:
            cloud_executed = _get_same_source_executed_keys(cs)
            if cloud_executed:
                before_cloud = len(exclude_keys)
                exclude_keys |= (cloud_executed & set(keys))
                added_cloud = len(exclude_keys) - before_cloud
                if added_cloud:
                    logger.debug("云端同来源去重(%s): 额外排除 %d 条", cs, added_cloud)
    cloud_removed = len(exclude_keys) - bitable_removed
    # 日志记录过滤模式
    mode_parts = []
    if filter_all:
        mode_parts.append("所有已存在")
    if filter_existing_success:
        mode_parts.append("已存在成功")
    if not filter_pc_only and not filter_online_only and not filter_all and not filter_existing_success:
        mode_parts.append("云端去重")
    if filter_pc_only and filter_online_only:
        mode_parts.append("PC+线上正确和通用失败")
    else:
        if filter_pc_only:
            mode_parts.append("PC正确+通用失败")
        if filter_online_only:
            mode_parts.append("线上正确+通用失败")
    mode_desc = "+".join(mode_parts) if mode_parts else "无过滤"
    filtered = [k for k in keys if k not in exclude_keys]
    # —— 内存级跨批次去重：排除最近已提交但多维表格可能尚未更新的 JIRA ——
    mem_skipped = 0
    if filtered:
        filtered, mem_skipped = _filter_recently_executed(filtered)
        if mem_skipped:
            logger.info("内存去重: 排除最近已执行的 %d 条", mem_skipped)
    # —— 第2步：AI初步分析过滤（逐个 fetch，并行执行）——
    ai_exclude = set()
    if filter_ai_preliminary and filtered:
        import concurrent.futures as _cf
        from src.clients import jira_client as _jc
        _AI_FIELD_ID = "customfield_13714"

        def _check_ai_field(bid):
            try:
                iss = _jc.fetch_issue(bid)
                f = (iss.get("fields") or {}).get(_AI_FIELD_ID)
                if f and str(f).strip() and str(f).strip().lower() not in ("none", "null"):
                    return bid
            except Exception:
                pass
            return None

        with _cf.ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(_check_ai_field, filtered))
        for r in results:
            if r:
                ai_exclude.add(r)
        if ai_exclude:
            filtered = [k for k in filtered if k not in ai_exclude]
    # —— 汇总返回 ——
    removed = len(keys) - len(filtered)
    ai_removed = len(ai_exclude)
    logger.info("过滤汇总(%s): 候选 %d → 表格去重 %d / 云端去重 %d / 内存去重 %d / AI初步分析 %d → 剩余 %d",
                mode_desc, len(keys), bitable_removed, cloud_removed, mem_skipped, ai_removed, len(filtered))
    if not filtered:
        return _fail(f"所有候选均已被过滤（候选 {len(keys)} 条，共过滤 {removed} 条）")
    filter_desc = f"候选 {len(keys)} 条，多维表格过滤 {bitable_removed} 条"
    if mem_skipped:
        filter_desc += f"，内存去重 {mem_skipped} 条"
    if ai_exclude:
        filter_desc += f"，AI字段过滤 {len(ai_exclude)} 条"
    filter_desc += f"，剩余 {len(filtered)} 条"
    return _ok({"filtered": filtered, "removed": removed, "total": len(keys),
                 "counts": {"total": len(keys), "bitable": bitable_removed, "cloud": cloud_removed,
                            "memory": mem_skipped, "ai": ai_removed, "remaining": len(filtered)},
                 "exclude_keys": list(exclude_keys)[:20]},
                filter_desc)


@router.post("/api/test/batch_ai_sample", response_model=ApiResponse)
async def test_batch_ai_sample(request: Request):
    """步骤4：从候选列表中随机抽取，优先云端已有时间，不够则逐批提取，提取失败跳过继续补充

    去重规则：docs/ 全量 CSV 已测试 排除，候选 keys 已由步骤3过滤
    """
    import os, re, json
    from src.services.trigger_ops import (
        _load_cloud_trigger_cache, _save_trigger_time_to_csv,
        _batch_save_trigger_times_to_cloud,
    )
    from src.services.report_ops import _load_all_doc_jira_keys
    from src.services.server_legacy import _diag_extract_time_from_video_simple, _has_gmlogger_logs, _diag_extract_time_from_images
    body = await request.json() or {}
    keys = body.get("keys") or []
    count = int(body.get("count", 0))
    csv_trigger_times = body.get("csv_trigger_times") or {}  # CSV 导入时携带的触发时间
    if not keys:
        return _fail("候选列表为空，请先执行步骤1")
    if count <= 0:
        return _fail("抽取数量必须大于 0")
    # 去重 keys（CSV 可能包含重复）
    seen_keys = set()
    unique_keys = []
    for k in keys:
        if k not in seen_keys:
            seen_keys.add(k)
            unique_keys.append(k)
    keys = unique_keys
    # 跨批次去重：本地 CSV + 云端批量执行记录（只要执行过就排除，不论分析结果）
    tested = _load_all_doc_jira_keys()
    cloud_executed = _get_same_source_executed_keys("")  # 空=不限来源，全部排除
    before_cloud = len(tested)
    tested |= cloud_executed
    cloud_added = len(tested) - before_cloud
    if cloud_added:
        logger.info("云端批量执行记录去重: 额外排除 %d 条", cloud_added)
    # 排除已执行记录
    available = [k for k in keys if k not in tested]
    if not available:
        return _fail(f"所有候选 bug 均已执行过（已执行 {len(tested)} 条）")
    # 从云端加载触发时间 + 空标记（支持多表，合并加载避免两次全量拉取）
    local_times, cloud_keys = _load_cloud_trigger_cache()
    # 始终信任云端缓存，无缓存的才重新提取
    trigger_times = {}
    for k in available:
        if k in local_times and local_times[k]:
            trigger_times[k] = local_times[k]
    # 合并 CSV 携带的触发时间（云端优先，CSV 补充）
    csv_hit = 0
    for k in available:
        if k not in trigger_times and k in csv_trigger_times and csv_trigger_times[k]:
            trigger_times[k] = csv_trigger_times[k]
            csv_hit += 1
    # 分类：有时间的 / 待提取池（云端已记录的空标记也跳过，不重复提取）
    with_time = [k for k in available if k in trigger_times]
    pending_pool = [k for k in available if k not in trigger_times and k not in cloud_keys]
    random.shuffle(pending_pool)
    # 先从有时间的中抽取
    sample_size = min(count, len(available))
    selected = []
    cloud_picked = 0
    new_extracted = 0
    extract_failed = 0
    new_to_cloud = {}  # 循环内收集待上传云端的数据，循环后批量上传
    new_sources = {}   # {jira号: 来源}
    new_refs = {}      # {jira号: 日志包抓包时间}
    if with_time:
        pick_with = min(sample_size, len(with_time))
        selected.extend(random.sample(with_time, pick_with))
        cloud_picked = pick_with
    # 云端已足够，不再提取
    if len(selected) >= sample_size:
        selected = selected[:sample_size]
    else:
        # 云端不够，从待提取池逐批提取，提取失败跳过继续下一个，直到凑够或池子耗尽
        extract_batch = 20
        _cloud_flush_interval = 2  # 每提取 2 个增量保存一次云端，防止请求超时丢失
        _cloud_flush_counter = 0
        while len(selected) < sample_size and pending_pool:
            batch = pending_pool[:extract_batch]
            pending_pool = pending_pool[extract_batch:]
            for k in batch:
                if len(selected) >= sample_size:
                    break
                try:
                    from src.clients import jira_client as _jc
                    issue = await _run_blocking(_jc.fetch_issue, k)
                    # gmlogger 前置检查：无 gmlogger 附件直接跳过（与批量提取保持一致）
                    attachments = (issue.get("fields") or {}).get("attachment") or []
                    if not _has_gmlogger_logs(attachments, k):
                        logger.info("抽样提取: %s 无gmlogger附件，跳过", k)
                        extract_failed += 1
                        continue
                    # 评论/字段提取优先（文本提取准确率最高且速度最快）
                    tt = await _run_blocking(_jc.extract_trigger_time_from_issue, issue, skip_attachment=True)
                    if not tt:
                        # 文本未命中，视频OCR兑底
                        tt = _diag_extract_time_from_video_simple(issue)
                    if not tt:
                        # 视频也未命中，图片OCR再兑底
                        cfg_api = load_config().get("jira_api", {})
                        img_h = {}
                        img_tok = cfg_api.get("token", "")
                        if img_tok:
                            img_h["Authorization"] = f"Bearer {img_tok}"
                        img_to = max(int(cfg_api.get("timeout", 30)), 120)
                        img_tt, _ = _diag_extract_time_from_images(issue, img_h, img_to, k)
                        if img_tt:
                            tt = img_tt
                    # 所有方法均失败，附件文件名最终兑底
                    if not tt:
                        tt = _jc.extract_attachment_time(issue)
                    # 防御性处理：确保 tt 是字符串
                    if tt and not isinstance(tt, str):
                        if hasattr(tt, 'strftime'):
                            tt = tt.strftime("%Y-%m-%d %H:%M:%S")
                        elif isinstance(tt, (tuple, list)) and len(tt) >= 1:
                            tt = str(tt[0])
                        else:
                            tt = str(tt)
                    if tt:
                        trigger_times[k] = tt
                        _save_trigger_time_to_csv(k, tt)
                        new_to_cloud[k] = tt
                        new_sources[k] = "抽样提取"
                        try:
                            _gm = _diag_gmlogger_times(attachments) or []
                            if _gm:
                                _d = _gm[0][1]
                                new_refs[k] = (_d.strftime("%Y-%m-%d %H:%M:%S")
                                               if hasattr(_d, "strftime") else str(_d)[:19])
                        except Exception:
                            pass
                        selected.append(k)
                        new_extracted += 1
                    else:
                        _save_trigger_time_to_csv(k, "")
                        new_to_cloud[k] = ""
                        extract_failed += 1
                except Exception as e:
                    logger.warning("抽样按需提取触发时间失败 %s: %s", k, e)
                    # 失败也保存空标记，防止下次重复提取
                    _save_trigger_time_to_csv(k, "")
                    new_to_cloud[k] = ""
                    extract_failed += 1
                # 增量保存云端：每 N 个刷新一次，防止请求超时导致已提取数据全部丢失
                _cloud_flush_counter += 1
                if _cloud_flush_counter >= _cloud_flush_interval and new_to_cloud:
                    _batch_save_trigger_times_to_cloud(new_to_cloud, dict(new_sources), dict(new_refs))
                    new_to_cloud.clear()
                    new_sources.clear()
                    new_refs.clear()
                    _cloud_flush_counter = 0
    # 循环结束后保存剩余未上传的到云端
    if new_to_cloud:
        _batch_save_trigger_times_to_cloud(new_to_cloud, dict(new_sources), dict(new_refs))
    # 统计
    with_time_count = len([k for k in selected if k in trigger_times])
    time_info = f"，{with_time_count} 条有触发时间（云端 {cloud_picked} + CSV {csv_hit} + 新提取 {new_extracted}）"
    if extract_failed:
        time_info += f"，提取失败跳过 {extract_failed} 条"
    return _ok({"available_count": len(available), "tested_count": len(tested),
                 "selected": selected, "selected_count": len(selected),
                 "trigger_times": trigger_times, "time_count": len(trigger_times),
                 "cloud_picked": cloud_picked, "csv_hit": csv_hit,
                 "new_extracted": new_extracted,
                 "extract_failed": extract_failed, "pending_scanned": len(pending_pool)},
                f"可用 {len(available)} 条，抽取 {len(selected)} 条{time_info}")


@router.post("/api/test/batch_ai_run")
async def test_batch_ai_run(request: Request):
    """步骤5：并行批量执行 AI 日志分析，SSE 实时推送每个完成结果，完成后写入本次批量执行表格"""
    import os, re, json
    import asyncio
    import json as _json
    import csv as _csv
    import queue
    from src.clients import ai_log_client
    from src.services.report_ops import _upload_batch_to_cloud
    from src.services.trigger_ops import _load_trigger_times_from_cloud
    body = await request.json() or {}
    bugids = body.get("bugids") or []
    trigger_times = body.get("trigger_times") or {}
    # 批量执行元数据（分析并发数、下载并发数、模型、触发来源）
    _batch_meta = {
        "分析并发数": str(body.get("analysis_concurrency", "10")),
        "下载并发数": str(body.get("download_concurrency", "4")),
        "模型": str(body.get("model", "deepseek-v-pro")),
        "触发来源": str(body.get("trigger_source", "PC")),
    }
    if not bugids:
        return _fail("待执行列表为空，请先执行步骤2")
    # 从云端补全缺失的触发时间（用户可能跳过步骤2直接执行）
    missing = [b for b in bugids if b not in trigger_times]
    if missing:
        try:
            cloud_times = await asyncio.get_event_loop().run_in_executor(None, _load_trigger_times_from_cloud)
            filled = 0
            for b in missing:
                if b in cloud_times and cloud_times[b]:
                    trigger_times[b] = cloud_times[b]
                    filled += 1
            if filled:
                logger.info("从云端补全 %d/%d 个缺失触发时间", filled, len(missing))
        except Exception as e:
            logger.warning("云端触发时间加载失败: %s", e)
    # 步骤3已过滤多维表格成功记录，此处不再重复去重
    skipped_jiras = []
    
    async def event_generator():
        import threading
        stop_event = threading.Event()
        batch_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        yield f"data: {_json.dumps({'type': 'start', 'total': len(bugids)}, ensure_ascii=False)}\n\n"
        result_queue = queue.Queue()
        loop = asyncio.get_event_loop()

        def _run_one(bugid):
            """在线程池中执行单个 AI 分析：支持 stop_event 中断"""
            if stop_event.is_set():
                return
            from src.clients.base import http_post
            # 无触发时间的 Jira 号跳过
            exec_time = trigger_times.get(bugid, "")
            if not exec_time:
                result_queue.put({"jira号": bugid, "执行结果": "失败",
                                  "报告长度": 0, "备注": "无触发时间", "触发时间": "", "执行时间": batch_start_time,
                                  "分析执行时间": batch_start_time,
                                  "status": "fail", "report_len": 0, "msg": "无触发时间"})
                return
            try:
                cfg = load_config()["ai_log_api"]
                payload = {cfg["bugid_field"]: bugid}
                if cfg.get("trigger_time_field"):
                    payload[cfg["trigger_time_field"]] = exec_time
                resp = http_post(cfg["url"], payload, timeout=min(int(cfg.get("timeout", 60)), 30))
                if stop_event.is_set():
                    return
                # 判断是否异步启动成功：code=200 且 msg 包含异步关键词
                resp_code = resp.get("code") if isinstance(resp, dict) else None
                resp_msg = str(resp.get("msg", "")) if isinstance(resp, dict) else ""
                is_async_ok = (resp_code == 200 or resp_code == 0) and any(
                    kw in resp_msg for kw in ["分析任务已启动", "后台处理", "正在分析"])
                if is_async_ok:
                    result_queue.put({"jira号": bugid, "执行结果": "成功",
                                      "报告长度": 0, "备注": resp_msg[:200], "触发时间": exec_time, "执行时间": batch_start_time,
                                      "分析执行时间": batch_start_time,
                                      "status": "success", "report_len": 0, "msg": resp_msg[:100]})
                else:
                    result_queue.put({"jira号": bugid, "执行结果": "失败",
                                      "报告长度": 0, "备注": f"返回异常: {resp_msg[:150]}", "触发时间": exec_time, "执行时间": batch_start_time,
                                      "分析执行时间": batch_start_time,
                                      "status": "fail", "report_len": 0, "msg": resp_msg[:100]})
            except Exception as e:
                result_queue.put({"jira号": bugid, "执行结果": "失败", "报告长度": 0,
                                  "备注": str(e)[:200], "status": "fail",
                                  "report_len": 0, "msg": str(e)[:100],
                                  "触发时间": exec_time,
                                  "执行时间": batch_start_time,
                                  "分析执行时间": batch_start_time})

        # 并行启动所有任务
        for bugid in bugids:
            loop.run_in_executor(None, _run_one, bugid)

        # 轮询队列，实时推送完成事件
        results = []
        while len(results) < len(bugids):
            if await request.is_disconnected():
                stop_event.set()
                logger.info("客户端已断开，停止批量执行（已完成 %d/%d）", len(results), len(bugids))
                break
            try:
                item = result_queue.get_nowait()
                results.append(item)
                yield f"data: {_json.dumps({'type': 'progress', 'index': len(results), 'total': len(bugids), 'bugid': item['jira号'], 'status': item['status'], 'report_len': item.get('report_len', 0), 'msg': item.get('msg', ''), 'exec_time': item.get('触发时间', ''), 'analysis_time': item.get('执行时间', '')}, ensure_ascii=False)}\n\n"
            except queue.Empty:
                await asyncio.sleep(1)

        # 写入本次批量执行表格：docs/日期/batch_HHMMSS.csv
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        batch_csv = os.path.join(get_path("doc_dir"), date_str, f"batch_{time_str}.csv")
        os.makedirs(os.path.dirname(batch_csv), exist_ok=True)
        fieldnames = ["jira号", "执行结果", "报告长度", "备注", "触发时间", "执行时间",
                      "分析并发数", "下载并发数", "模型", "触发来源"]
        with open(batch_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow({"jira号": r["jira号"], "执行结果": r["执行结果"],
                                 "报告长度": r["报告长度"], "备注": r["备注"],
                                 "触发时间": r.get("触发时间", ""),
                                 "执行时间": r.get("执行时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                                 **_batch_meta})
        success_count = sum(1 for r in results if r["执行结果"] == "成功")
        fail_count = len(results) - success_count
        # 将结果写入每日结论报表（仅含已知字段，后续单Jira流程会补全其余字段）
        try:
            from src.core import report as report_module
            daily_rows = [{"jira号": r["jira号"],
                           "分析问题时间": r.get("触发时间", ""),
                           "AI分析结果(飞书链接)": "", "AI评论总结": "",
                           "rootcause": "", "结果置信度": ""} for r in results]
            report_module.generate_daily_csv(daily_rows, date_str=date_str)
        except Exception as e:
            logger.warning("批量执行写入每日报表失败（不影响主流程）: %s", e)
        # 上传到飞书云端文件夹
        cloud_url = ""
        try:
            doc_title = f"批量执行 {date_str}_{time_str} ({success_count}/{len(results)})"
            cloud_url = _upload_batch_to_cloud(batch_csv, doc_title)
        except Exception as e:
            logger.warning("批量执行上传云端失败（不影响主流程）: %s", e)
        done_msg = f"执行完成：成功 {success_count} 条，失败 {fail_count} 条"
        if skipped_jiras:
            done_msg += f"，已跳过 {len(skipped_jiras)} 条（多维表格已成功）"
        yield f"data: {_json.dumps({'type': 'done', 'total': len(results), 'success': success_count, 'fail': fail_count, 'skipped': len(skipped_jiras), 'message': done_msg, 'csv_path': batch_csv, 'cloud_url': cloud_url}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/test/batch_quality_assess", response_model=ApiResponse)
async def test_batch_quality_assess(request: Request):
    """本批次质量评估：统计成功率/耗时，扫描多维表格补写缺失的执行时间"""
    import os, re, json
    from src.clients import feishu_client
    body = await request.json() or {}
    bugids = body.get("bugids") or []
    doc_created_time = str(body.get("doc_created_time", "")).strip()
    if not bugids:
        return _fail("请先执行批量分析")
    cfg = load_config().get("feishu_bitable", {})
    app_token, table_id = cfg.get("app_token", ""), cfg.get("table_id", "")
    if not app_token or not table_id:
        return _fail("多维表格未配置")
    bitable = await _run_blocking(feishu_client.list_bitable_records, app_token, table_id)
    jira_set = set(bugids)
    latest_done, missing_exec = "", []
    for rec in bitable:
        fields = rec.get("fields", {})
        jid = _bitable_text(fields.get("jira号", ""))
        if jid not in jira_set:
            continue
        dt = _bitable_text(fields.get("分析完成时间", ""))
        if dt > latest_done:
            latest_done = dt
        if not _bitable_text(fields.get("分析问题时间", "")).strip():
            missing_exec.append({"record_id": rec["record_id"], "jira_no": jid})
    # 优先使用云端文档创建时间，否则回退到本地 CSV 创建时间
    csv_ctime = doc_created_time if doc_created_time else ""
    if not csv_ctime:
        doc_dir = get_path("doc_dir")
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_dir = os.path.join(doc_dir, today_str)
        if os.path.isdir(today_dir):
            csvs = sorted([f for f in os.listdir(today_dir) if f.startswith("batch_") and f.endswith(".csv")], reverse=True)
            if csvs:
                csv_ctime = datetime.fromtimestamp(
                    os.path.getctime(os.path.join(today_dir, csvs[0]))).strftime("%Y-%m-%d %H:%M:%S")
    # 批量补写缺失的执行时间
    backfilled = 0
    if missing_exec and csv_ctime:
        updates = [{"record_id": m["record_id"], "fields": {"分析问题时间": csv_ctime}} for m in missing_exec]
        for i in range(0, len(updates), 100):
            await _run_blocking(feishu_client.update_bitable_records, app_token, table_id, updates[i:i + 100])
        backfilled = len(missing_exec)
    return _ok({"assessment": {
        "total": len(bugids), "backfilled": backfilled,
        "missing_count": len(missing_exec), "latest_done": latest_done, "backfill_time": csv_ctime,
    }}, "质量评估完成")


@router.post("/api/test/bitable_write", response_model=ApiResponse)
async def test_bitable_write(request: Request):
    """测试接口：多维表格模拟写入（支持dry-run预览），不传bugid时返回全量记录"""
    import os, re, json
    from src.clients import feishu_client
    from src.core import filter as comment_filter
    from src.api.routes.shared import _find_comment_doc
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    dry_run = bool(body.get("dry_run", False))

    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")

    try:
        # 获取字段定义
        field_defs = await _run_blocking(feishu_client.list_bitable_fields, app_token, table_id)
        field_name_map = {fd.get("field_name", ""): fd.get("field_name", "") for fd in field_defs}
        field_type_map = {fd.get("field_name", ""): fd.get("type", 0) for fd in field_defs}

        # 无 bugid 时：返回全量记录（供数据看板展示）
        if not bugid:
            records = await _run_blocking(feishu_client.list_bitable_records, app_token, table_id)
            result_rows = []
            for rec in records:
                fields = rec.get("fields", {})
                flat = {"record_id": rec.get("record_id", "")}
                for key, val in fields.items():
                    if isinstance(val, dict) and "link" in val:
                        flat[key] = val.get("text", "")
                    elif isinstance(val, list):
                        flat[key] = " ".join(str(v) for v in val)
                    else:
                        flat[key] = str(val) if val is not None else ""
                result_rows.append(flat)
            field_names = [fd.get("field_name", "") for fd in field_defs]
            return _ok({
                "records": result_rows,
                "field_names": field_names,
                "field_types": field_type_map,
                "count": len(result_rows)
            })

        rc_field = field_name_map.get("rootcause") or field_name_map.get("Rootcause") or ""
        cs_field = field_name_map.get("AI评论总结") or field_name_map.get("评论总结") or ""
        cf_field = field_name_map.get("结果置信度") or field_name_map.get("置信度") or ""

        # 获取记录
        records = await _run_blocking(feishu_client.list_bitable_records, app_token, table_id)
        bugid_to_record = {}
        for rec in records:
            fields = rec.get("fields", {})
            field_value = fields.get(bugid_field, "")
            if isinstance(field_value, list):
                field_value = "".join(str(v) for v in field_value)
            field_value = str(field_value).strip()
            if field_value:
                bugid_to_record[field_value] = rec.get("record_id", "")

        record_id = bugid_to_record.get(bugid)
        if not record_id:
            return _fail(f"未找到 bugid={bugid} 对应的记录")

        # 构建写入值
        rootcause = str(body.get("rootcause", ""))
        comment_summary = str(body.get("comment_summary", ""))
        confidence = body.get("confidence", "")
        doc_url = str(body.get("doc_url", ""))

        cleaned_comment = comment_filter._clean_table_text(comment_summary)
        cleaned_comment = re.sub(r'\s*\[详情:\s*[^\]]+\]', '', cleaned_comment).strip()

        fields_to_write = {}
        field_types = {}
        if rc_field:
            fields_to_write[rc_field] = comment_filter._clean_table_text(rootcause)
            field_types[rc_field] = field_type_map.get(rc_field, 0)
        if cs_field:
            cs_field_type = field_type_map.get(cs_field, 0)
            field_types[cs_field] = cs_field_type
            if cs_field_type == 15:
                # URL字段：无doc_url时自动创建飞书在线文档并获取链接
                if not doc_url and cleaned_comment:
                    try:
                        doc_title = f"{bugid} AI评论总结"
                        doc_content = _find_comment_doc(bugid) or cleaned_comment
                        doc_result = await _run_blocking(feishu_client.create_docx_document, doc_title, doc_content)
                        doc_url = doc_result.get("url", "")
                    except Exception as e:
                        logger.warning("创建在线文档失败: %s", e)
                if doc_url:
                    fields_to_write[cs_field] = {"link": doc_url, "text": cleaned_comment}
                # 无链接时跳过该字段，避免 URLFieldConvFail
            elif doc_url:
                fields_to_write[cs_field] = f"{cleaned_comment} {doc_url}" if cleaned_comment else doc_url
            else:
                fields_to_write[cs_field] = cleaned_comment
        if cf_field:
            cf_field_type = field_type_map.get(cf_field, 0)
            field_types[cf_field] = cf_field_type
            if cf_field_type == 2:
                try:
                    fields_to_write[cf_field] = float(confidence) if confidence else 0
                except (ValueError, TypeError):
                    fields_to_write[cf_field] = 0
            else:
                fields_to_write[cf_field] = str(confidence)

        update_records = [{"record_id": record_id, "fields": fields_to_write}]

        if dry_run:
            return _ok({
                "record_id": record_id,
                "fields": fields_to_write,
                "field_types": field_types,
                "dry_run": True
            }, "模拟写入成功，未实际发送")

        await _run_blocking(feishu_client.update_bitable_records, app_token, table_id, update_records)
        return _ok({
            "record_id": record_id,
            "fields": fields_to_write,
            "field_types": field_types,
            "dry_run": False
        }, f"写入成功: bugid={bugid}")
    except Exception as e:
        logger.error("多维表格模拟写入失败: %s", e, exc_info=True)
        return _fail(f"写入失败: {e}")


@router.post("/api/test/jira_raw", response_model=ApiResponse)
async def test_jira_raw(request: Request):
    """功能测试5：Jira 接口原始返回字段验证，调用 Jira API 并返回完整响应内容"""
    import os, re, json
    from src.clients import jira_client
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("请输入 bugid")
    try:
        cfg = load_config()["jira_api"]
        is_mock = cfg.get("mock", False)
        # 调用 Jira 接口获取完整响应
        raw_response = await _run_blocking(jira_client.fetch_issue, bugid)
        # 提取当前已使用的字段值，便于对比
        extracted = {
            "description": jira_client.extract_error_cause(raw_response),
            "rootcause": jira_client.extract_rootcause(raw_response),
            "comments": jira_client.extract_comments(raw_response),
        }
        # 列出 fields 下所有可用字段名及其值类型，帮助判断哪些字段有用
        fields_keys = []
        fields = raw_response.get("fields") or {}
        for k, v in fields.items():
            val_type = type(v).__name__
            preview = str(v)[:100] if v is not None else "null"
            fields_keys.append({"key": k, "type": val_type, "preview": preview})
        return _ok({
            "raw_response": raw_response,
            "extracted": extracted,
            "fields_keys": fields_keys,
            "is_mock": is_mock,
            "api_url": cfg.get("url", ""),
        }, f"Jira 接口返回成功（{'mock' if is_mock else '真实'}模式），fields 共 {len(fields_keys)} 个字段")
    except Exception as e:
        logger.error("Jira 接口测试失败: %s", e)
        return _fail(str(e))


@router.post("/api/test/trigger_time", response_model=ApiResponse)
async def test_trigger_time(request: Request):
    """功能测试：触发时间提取，优先读云端已有数据，无记录再从 Jira 提取"""
    import os, re, json
    from src.clients import jira_client
    from src.services.trigger_ops import (
        _load_trigger_times_from_cloud,
        _save_trigger_time_to_cloud,
    )
    from src.services.server_legacy import _diag_extract_time_from_video_simple, _has_gmlogger_logs, _diag_extract_time_from_images
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("请输入 bugid")
    try:
        # 优先从云端读取已有触发时间
        cloud_times = _load_trigger_times_from_cloud()
        cached_time = cloud_times.get(bugid, "")
        if cached_time:
            return _ok({
                "trigger_time": cached_time,
                "comment_count": 0,
                "source": "cloud",
            }, f"云端已有触发时间: {cached_time}")
        # 云端无记录，从 Jira 提取
        issue = await _run_blocking(jira_client.fetch_issue, bugid)
        # gmlogger 前置检查
        attachments = (issue.get("fields") or {}).get("attachment") or []
        if not _has_gmlogger_logs(attachments, bugid):
            return _fail("无gmlogger附件，跳过提取")
        # 评论/字段提取优先（文本提取准确率最高且速度最快）
        trigger_time = await _run_blocking(jira_client.extract_trigger_time_from_issue, issue, skip_attachment=True)
        source = "jira_comment"
        if not trigger_time:
            # 文本未命中，视频OCR兑底
            trigger_time = _diag_extract_time_from_video_simple(issue)
            if trigger_time:
                source = "video_ocr"
        if not trigger_time:
            # 视频也未命中，图片OCR再兑底
            cfg_api = load_config().get("jira_api", {})
            img_h = {}
            img_tok = cfg_api.get("token", "")
            if img_tok:
                img_h["Authorization"] = f"Bearer {img_tok}"
            img_to = max(int(cfg_api.get("timeout", 30)), 120)
            img_tt, _ = _diag_extract_time_from_images(issue, img_h, img_to, bugid)
            if img_tt:
                trigger_time = img_tt
                source = "image_ocr"
        # 所有方法均失败，附件文件名最终兑底
        if not trigger_time:
            trigger_time = jira_client.extract_attachment_time(issue)
            if trigger_time:
                source = "attachment_name"
        if not trigger_time:
            return _fail("提取失败，评论/视频/图片/附件名均未获取到时间内容")
        # 防御性处理：确保 tt 是字符串
        if not isinstance(trigger_time, str):
            trigger_time = trigger_time.strftime("%Y-%m-%d %H:%M:%S") if hasattr(trigger_time, 'strftime') else str(trigger_time)
        # 提取成功后保存到云端+本地（带来源与日志包参考时间）
        _save_trigger_time_to_cloud(bugid, trigger_time, source=f"单条提取:{source}")
        comments = jira_client.extract_comments(issue)
        return _ok({
            "trigger_time": trigger_time,
            "comment_count": len(comments),
            "source": source,
        }, f"Jira提取成功({source})，从 {len(comments)} 条评论中提取到触发时间")
    except Exception as e:
        logger.error("触发时间提取失败: %s", e)
        return _fail(str(e))


# [已拆分到 routes/trigger.py] trigger_time/cache_batch_extract/stop 已移至 trigger_router


# 云端缓存批量提取本地进度文件路径


@router.post("/api/test/create_docx", response_model=ApiResponse)
async def test_create_docx(request: Request):
    """测试接口：创建飞书在线文档，返回文档 URL 和详细调试信息"""
    import os, re, json
    from src.clients import feishu_client
    body = await request.json() or {}
    title = str(body.get("title", "测试文档")).strip()
    content = str(body.get("content", "# 测试文档\n\n这是一段测试内容。")).strip()

    # 获取当前 token 信息
    cfg = load_config().get("feishu_bitable", {})
    user_token = cfg.get("user_access_token", "")
    token_type = "user" if user_token else "tenant"
    token_preview = (user_token or "")[:30] + "..." if (user_token or "") else "empty"

    try:
        doc_result = await _run_blocking(feishu_client.create_docx_document, title, content)
        return _ok({
            "document_id": doc_result.get("document_id"),
            "url": doc_result.get("url"),
            "token_type": token_type,
            "token_preview": token_preview,
        }, f"文档创建成功: {doc_result.get('url', '')}")
    except Exception as e:
        logger.error("测试创建文档失败: %s", e)
        return _fail(f"创建失败: {e}", extra={
            "token_type": token_type,
            "token_preview": token_preview,
            "error": str(e),
        })


@router.post("/api/test/bitable_failed_jiras", response_model=ApiResponse)
async def test_bitable_failed_jiras(request: Request):
    """从多维表格提取分析失败的 jira 号，支持时间/通用失败/已成功过滤"""
    import os, re, json
    body = await request.json() or {}
    after_time = str(body.get("after_time", "") or "").strip()  # 分析完成时间起点过滤
    exclude_common = body.get("exclude_common", False)  # 是否排除通用失败原因
    exclude_success = body.get("exclude_success", False)  # 是否排除已成功的 Jira
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = await _run_blocking(feishu_client.list_bitable_records, app_token, table_id)
        # 第一遍：收集所有已成功的 Jira 号
        success_jiras = set()
        if exclude_success:
            for rec in records:
                fields = rec.get("fields", {})
                if _bitable_text(fields.get("分析结果", "")) == "成功":
                    fv = fields.get(bugid_field, "")
                    if isinstance(fv, list):
                        fv = " ".join(str(v) for v in fv)
                    fv = str(fv).strip()
                    if fv:
                        success_jiras.add(fv)
        # 第二遍：提取失败记录
        failed_jiras = set()
        skipped_common = 0
        skipped_time = 0
        skipped_success = 0
        for rec in records:
            fields = rec.get("fields", {})
            result_status = _bitable_text(fields.get("分析结果", ""))
            if result_status != "失败":
                continue
            # 排除人工审核确认无需重试的记录
            human_review = _bitable_text(fields.get("人工审核结果", ""))
            if human_review in _EXCLUDE_REASONS or any(
                    human_review.lower() == r.lower() for r in _EXCLUDE_REASONS):
                skipped_common += 1
                continue
            # 通用失败原因过滤
            if exclude_common:
                err_info = _bitable_text(fields.get("错误信息", ""))
                rootcause = _bitable_text(fields.get("rootcause", ""))
                combined = f"{err_info} {rootcause} {human_review}".strip()
                if any(reason in combined for reason in _EXCLUDE_REASONS):
                    skipped_common += 1
                    continue
            # 分析完成时间过滤
            if after_time:
                done_time = _bitable_text(fields.get("分析完成时间", ""))
                if done_time and done_time < after_time:
                    skipped_time += 1
                    continue
            field_value = fields.get(bugid_field, "")
            if isinstance(field_value, list):
                field_value = " ".join(str(v) for v in field_value)
            field_value = str(field_value).strip()
            if field_value:
                # 已成功过滤
                if exclude_success and field_value in success_jiras:
                    skipped_success += 1
                    continue
                failed_jiras.add(field_value)
        jira_list = sorted(failed_jiras)
        msg = f"提取到 {len(jira_list)} 个分析失败的 Jira 号（已去重）"
        if skipped_common:
            msg += f"，跳过通用原因 {skipped_common} 条"
        if skipped_time:
            msg += f"，跳过时间过滤 {skipped_time} 条"
        if skipped_success:
            msg += f"，跳过已成功 {skipped_success} 条"
        return _ok({"jiras": jira_list, "count": len(jira_list)}, msg)
    except Exception as e:
        logger.error("提取失败Jira号失败: %s", e, exc_info=True)
        return _fail(f"提取失败: {e}")


# ==================== 无gmlogger重新排查 ====================

# 需要重新排查的人工审核关键词


@router.post("/api/test/gmlogger_rescan", response_model=ApiResponse)
def test_gmlogger_rescan(request: Request):
    """扫描多维表格中人工审核为'无gmlogger'的失败记录，重新检查Jira附件是否已有gmlogger/main文件"""
    import os, re, json
    from src.clients import feishu_client, jira_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
        # 筛选：分析结果=失败 且 人工审核结果包含无gmlogger相关关键词
        candidates = []
        for rec in records:
            fields = rec.get("fields", {})
            result_status = _bitable_text(fields.get("分析结果", ""))
            if result_status != "失败":
                continue
            human_review = _bitable_text(fields.get("人工审核结果", ""))
            if not human_review:
                continue
            # 检查是否匹配无gmlogger相关关键词
            review_lower = human_review.lower()
            is_match = any(kw.lower() in review_lower for kw in _GMLOGGER_REVIEW_KEYWORDS)
            if not is_match:
                continue
            # 提取 bugid
            fv = fields.get(bugid_field, "")
            if isinstance(fv, list):
                fv = " ".join(str(v) for v in fv)
            bugid = str(fv).strip()
            if not bugid:
                continue
            candidates.append({
                "record_id": rec.get("record_id", ""),
                "bugid": bugid,
                "human_review": human_review,
            })
        # 逐个查询Jira附件
        results = []
        has_file_count = 0
        for c in candidates:
            bugid = c["bugid"]
            try:
                issue = jira_client.fetch_issue(bugid)
                attachments = (issue.get("fields") or {}).get("attachment") or []
                matched = [att.get("filename", "") for att in attachments
                           if "gmlogger" in (att.get("filename", "") or "").lower()
                           or "main" in (att.get("filename", "") or "").lower()]
                has_gmlogger = any("gmlogger" in f.lower() for f in matched)
                has_main = any("main" in f.lower() and "gmlogger" not in f.lower() for f in matched)
                if matched:
                    has_file_count += 1
                results.append({
                    "record_id": c["record_id"],
                    "bugid": bugid,
                    "human_review": c["human_review"],
                    "attachment_count": len(attachments),
                    "matched_files": matched,
                    "has_gmlogger": has_gmlogger,
                    "has_main": has_main,
                    "has_file": len(matched) > 0,
                })
            except Exception as e:
                results.append({
                    "record_id": c["record_id"],
                    "bugid": bugid,
                    "human_review": c["human_review"],
                    "attachment_count": 0,
                    "matched_files": [],
                    "has_gmlogger": False,
                    "has_main": False,
                    "has_file": False,
                    "error": str(e)[:100],
                })
        msg = f"扫描完成: {len(candidates)} 条无gmlogger记录，{has_file_count} 条已新增日志文件"
        return _ok({"candidates": results, "total": len(candidates), "has_file_count": has_file_count}, msg)
    except Exception as e:
        logger.error("无gmlogger重新扫描失败: %s", e, exc_info=True)
        return _fail(f"扫描失败: {e}")


@router.post("/api/test/gmlogger_clear_review", response_model=ApiResponse)
async def test_gmlogger_clear_review(request: Request):
    """批量清空选中记录的人工审核结果字段"""
    import os, re, json
    from src.clients import feishu_client
    body = await request.json() or {}
    record_ids = body.get("record_ids") or []
    if not record_ids:
        return _fail("请选择要清空的记录")
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        updates = [{"record_id": rid, "fields": {"人工审核结果": ""}} for rid in record_ids]
        # 批量更新，每次最多100条
        success = 0
        errors = []
        for i in range(0, len(updates), 100):
            batch = updates[i:i + 100]
            try:
                await _run_blocking(feishu_client.update_bitable_records, app_token, table_id, batch)
                success += len(batch)
            except Exception as e:
                errors.append(f"批次 {i // 100 + 1}: {str(e)[:80]}")
        msg = f"已清空 {success} 条人工审核结果"
        if errors:
            msg += f"，{len(errors)} 批次失败"
        return _ok({"success": success, "errors": errors}, msg)
    except Exception as e:
        logger.error("清空人工审核结果失败: %s", e, exc_info=True)
        return _fail(f"清空失败: {e}")


# ========== AI日志分析失败问题排查工具 ==========


@router.get("/api/test/confidence_batch_write", response_model=ApiResponse)
async def test_confidence_batch_write(request: Request, after_time: str = "", only_empty: str = "", jira_ids: str = ""):
    """置信度批量写入（**只读分析**）：计算 rootcause + AI问题分析根因，对比语义相似度得出置信度

    本端点不写多维表格：只把每条待写字段（write_fields）通过 SSE 推给页面，
    真正写入由用户确认后调用 POST /api/test/confidence_batch_commit 完成。

    :param after_time: 可选时间筛选，仅处理分析完成时间在此时间之后的记录
    :param jira_ids: 可选 Jira 号列表（逗号分隔），指定时仅处理这些记录，忽略 after_time 和 only_empty
    """
    import os, re, json, asyncio
    from src.core import semantic as semantic_module
    from src.clients import feishu_client, jira_client
    import json as _json

    async def generate():
        cfg = load_config().get("feishu_bitable", {})
        app_token = cfg.get("app_token", "")
        table_id = cfg.get("table_id", "")
        bugid_field = cfg.get("bugid_field", "jira号")
        conf_field_name = cfg.get("confidence_field", "结果置信度")
        threshold = float(load_config().get("similarity", {}).get("threshold", 0.7))
        if not app_token or not table_id:
            yield f"data: {_json.dumps({'type': 'error', 'msg': '多维表格 app_token/table_id 未配置'}, ensure_ascii=False)}\n\n"
            return

        # 加载字段定义，确定字段名和类型
        try:
            field_defs = await _run_blocking(feishu_client.list_bitable_fields, app_token, table_id)
            field_type_map = {fd.get("field_name", ""): fd.get("type", 0) for fd in field_defs}
            field_names = list(field_type_map.keys())
            # 置信度字段
            cf_field = conf_field_name if conf_field_name in field_type_map else ""
            if not cf_field:
                for fn in field_names:
                    if "置信度" in fn:
                        cf_field = fn
                        break
            # rootcause 字段
            rc_field = next((fn for fn in field_names if fn.lower() == "rootcause"), "")
            # AI问题分析根因字段
            ai_rc_field = next((fn for fn in field_names if "AI问题分析根因" in fn or "问题分析根因" in fn), "")
            if not ai_rc_field:
                ai_rc_field = next((fn for fn in field_names if "AI" in fn and "根因" in fn), "")
            logger.info("置信度批量写入字段映射: cf=%s, rc=%s, ai_rc=%s", cf_field, rc_field, ai_rc_field)
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'msg': f'获取字段定义失败: {e}'}, ensure_ascii=False)}\n\n"
            return

        # 加载多维表格记录，筛选分析结果=成功 且 置信度为空/0
        try:
            records = await _run_blocking(feishu_client.list_bitable_records, app_token, table_id)
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'msg': f'加载多维表格记录失败: {e}'}, ensure_ascii=False)}\n\n"
            return

        # 当指定 jira_ids 时，仅处理这些 Jira 号，忽略 after_time 和 only_empty
        _jira_id_set = set(x.strip().upper() for x in jira_ids.split(",") if x.strip()) if jira_ids else None
        targets = []
        for rec in records:
            fields = rec.get("fields", {})
            if str(fields.get("分析结果", "")).strip() != "成功":
                continue
            if _jira_id_set:
                # 按指定 Jira ID 过滤（大小写不敏感）
                fv_check = fields.get(bugid_field, "")
                if isinstance(fv_check, list):
                    fv_check = " ".join(str(v) for v in fv_check)
                if str(fv_check).strip().upper() not in _jira_id_set:
                    continue
            if not _jira_id_set and after_time:
                done_str = _bitable_text(fields.get("分析完成时间", ""))
                if not done_str or done_str < after_time:
                    continue
            conf_val = fields.get(conf_field_name, "")
            if isinstance(conf_val, list):
                conf_val = " ".join(str(v) for v in conf_val)
            conf_str = str(conf_val).strip()
            # only_empty=True 时仅处理置信度为空的记录，jira_ids 模式忽略此筛选
            if not _jira_id_set and only_empty and conf_str and conf_str not in ("0", "0.0"):
                continue
            fv = fields.get(bugid_field, "")
            if isinstance(fv, list):
                fv = " ".join(str(v) for v in fv)
            fv = str(fv).strip()
            if not fv:
                continue
            # 提取已有字段值
            existing_rc = _bitable_text(fields.get(rc_field, "")) if rc_field else ""
            existing_ai_rc = _bitable_text(fields.get(ai_rc_field, "")) if ai_rc_field else ""
            feishu_link = fields.get("AI分析结果(飞书链接)", "")
            if isinstance(feishu_link, dict):
                feishu_link = feishu_link.get("link", "") or feishu_link.get("text", "")
            feishu_link = str(feishu_link).strip() if feishu_link else ""
            targets.append({
                "jira号": fv, "record_id": rec["record_id"],
                "rootcause": existing_rc, "ai_rootcause": existing_ai_rc,
                "feishu_link": feishu_link,
                "conf_empty": not conf_str or conf_str in ("0", "0.0"),
            })

        total = len(targets)
        yield f"data: {_json.dumps({'type': 'start', 'total': total, 'threshold': threshold, 'after_time': after_time or ''}, ensure_ascii=False)}\n\n"
        if not total:
            yield f"data: {_json.dumps({'type': 'done', 'updated': 0, 'total': 0, 'msg': '无需处理的记录'}, ensure_ascii=False)}\n\n"
            return

        # 逐条处理：填充字段 + 对比 + 立即写回
        loop = asyncio.get_event_loop()
        success_count = 0
        fail_count = 0
        written = 0

        def _extract_core_rootcause(text: str) -> str:
            """从根因文本中提取核心语义用于 Diana LLM 对比

            支持两种格式：
            1. 结构化标记：【根本原因】/【直接原因】 段落
            2. 自然语言：提取结论句+前文上下文，拼成完整因果链
            无标记时返回全文。
            """
            if not text:
                return ""
            import re as _re
            # 1. 结构化标记：【根本原因】/【直接原因】
            m = _re.search(r'[\[\u3010\(（]\s*(?:根本原因|直接原因)\s*[\]\u3011\)）]\s*(.*?)(?=[\[\u3010\(（]|$)', text, _re.DOTALL)
            if m:
                return m.group(1).strip()
            # 2. 自然语言结论句提取
            # 优先匹配结论句（“因此”），带上前一句上下文拼成完整因果链
            for pattern in [
                r'(?:因此[，,]?\s*)([\u4e00-\u9fff].{10,})',
                r'(?:核心原因[是为]|直接原因[是为]|根因[是为])([\u4e00-\u9fff].{10,})',
            ]:
                m = _re.search(pattern, text)
                if m:
                    conclusion = m.group(1).strip()
                    # 取到第一个句号/感叹号为止的核心句
                    end = _re.search(r'[。！]', conclusion)
                    if end and end.start() > 6:
                        conclusion = conclusion[:end.end()]
                    else:
                        conclusion = conclusion[:200]
                    # 去除尾部噪声从句：“由于…”“这是…”“但无法…”
                    conclusion = _re.sub(r'[，,]\s*(?:由于|这是|但无法|但目前|无法确认|无法读取).*$', '', conclusion)
                    # 去除模糊词：“很可能”“可能”“大概率”
                    conclusion = _re.sub(r'(?:很可能|很可能是|大概率|可能)', '', conclusion)
                    # 提取前一句上下文（原因/背景），拼成完整因果链
                    before = text[:m.start()].strip()
                    if before:
                        prev_sents = _re.split(r'[。！？]', before)
                        prev_sents = [s.strip() for s in prev_sents if len(s.strip()) >= 8]
                        if prev_sents:
                            context = prev_sents[-1]
                            # 前句过长时从句子边界截取尾部，避免截断单词
                            if len(context) > 100:
                                sub = _re.split(r'[，,、]', context)
                                context = '，'.join(sub[-2:]) if len(sub) > 1 else context[-60:]
                            return (context + '，' + conclusion).strip()
                    return conclusion.strip()
            # 3. 回退：返回全文
            return text.strip()

        def _split_semantic_sentences(text: str) -> list:
            """将长文本按句子拆分，用于逐句语义兆底对比"""
            import re as _re
            parts = _re.split(r'([。！？；;!?])', text)
            sentences, cur = [], ""
            for i in range(len(parts)):
                cur += parts[i]
                if i % 2 == 1:  # 标点符号
                    s = cur.strip()
                    if len(s) >= 6:
                        sentences.append(s)
                    cur = ""
            if cur.strip() and len(cur.strip()) >= 6:
                sentences.append(cur.strip())
            return sentences
        
        def _extract_conclusion_only(text: str) -> str:
            """提取最干净的结论句（避免负面句子拉低对比分）"""
            import re as _re
            m = _re.search(r'(?:因此[，,]?\s*)([\u4e00-\u9fff].{10,})', text)
            if m:
                conclusion = m.group(1).strip()
                end = _re.search(r'[。！]', conclusion)
                if end and end.start() > 6:
                    conclusion = conclusion[:end.end()]
                else:
                    conclusion = conclusion[:200]
                conclusion = _re.sub(r'[，,]\s*(?:由于|这是|但无法|但目前|无法确认|无法读取).*$', '', conclusion)
                conclusion = _re.sub(r'(?:很可能|很可能是|大概率|可能)', '', conclusion)
                return conclusion.strip()
            return ""

        def _extract_entity_sentence(text: str, keywords: list) -> str:
            """从文本中提取同时包含最多关键词的句子，用于更精准的语义对比"""
            import re as _re
            parts = _re.split(r'[。！？]', text)
            best_sent = ""
            best_count = 0
            for part in parts:
                s = part.strip()
                if len(s) < 8:
                    continue
                count = sum(1 for kw in keywords if kw in s)
                if count > best_count:
                    best_count = count
                    best_sent = s
            return best_sent if best_count >= 2 else ""

        for idx, t in enumerate(targets):
            if await request.is_disconnected():
                yield f"data: {_json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
                return
            bugid = t["jira号"]
            conf_empty = t.get("conf_empty", False)
            fields_to_write = {}
            jira_rc = t["rootcause"]
            ai_rc = t["ai_rootcause"]
            try:
                # 1. rootcause：始终从 Jira API 取最新值，覆盖表格旧数据
                if rc_field:
                    try:
                        issue = await loop.run_in_executor(None, jira_client.fetch_issue, bugid)
                        fresh_rc = jira_client.extract_rootcause(issue) or ""
                        if fresh_rc:
                            jira_rc = fresh_rc
                            fields_to_write[rc_field] = fresh_rc
                    except Exception as e:
                        logger.warning("bugid=%s Jira rootcause获取失败，回退表格值: %s", bugid, e)
                # 2. AI问题分析根因：表格已有数据则直接用，否则从飞书文档提取
                if not ai_rc and ai_rc_field and t["feishu_link"]:
                    try:
                        ai_content = await loop.run_in_executor(
                            None, pipeline._get_ai_report_content, bugid, t["feishu_link"])
                        ai_rc = doc_generator.parse_root_cause_section(ai_content) or ""
                        if ai_rc:
                            fields_to_write[ai_rc_field] = ai_rc
                    except Exception as e:
                        logger.warning("bugid=%s AI文档根因获取失败: %s", bugid, e)
                # 3. 两个根因都为空则跳过
                if not jira_rc and not ai_rc:
                    _sse_d = {'type': 'progress', 'index': idx + 1, 'total': total,
                                                'bugid': bugid, 'status': 'skipped', 'score': 0,
                                                'record_id': t['record_id'], 'write_fields': fields_to_write,
                                                'conf_empty': conf_empty,
                                                'msg': '两个根因字段均为空'}
                    yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
                    fail_count += 1
                    continue
                if not jira_rc or not ai_rc:
                    missing = 'Jira根因' if not jira_rc else 'AI根因'
                    _sse_d = {'type': 'progress', 'index': idx + 1, 'total': total,
                                                'bugid': bugid, 'status': 'skipped', 'score': 0,
                                                'jira_rootcause': jira_rc, 'ai_rootcause': ai_rc,
                                                'record_id': t['record_id'], 'write_fields': fields_to_write,
                                                'conf_empty': conf_empty,
                                                'msg': f'{missing}为空，无法对比'}
                    yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
                    fail_count += 1
                    continue
                # 4. 通用/无效/重复根因：置信度写"无法判断"
                _SKIP_ROOTCAUSE_KEYWORDS = ("同根因重复", "重复BUG", "重复问题", "重复缺陷", "根因一致")
                _INVALID_AI_RC_KEYWORDS = ("无法复现", "日志无法", "无法定位", "暂无分析", "无法获取日志")
                skip_reason = ""
                if pipeline._is_generic_rootcause(jira_rc):
                    skip_reason = f"Jira根因为通用表述: {jira_rc[:60]}"
                elif any(kw in jira_rc for kw in _SKIP_ROOTCAUSE_KEYWORDS):
                    hit = next(kw for kw in _SKIP_ROOTCAUSE_KEYWORDS if kw in jira_rc)
                    skip_reason = f"Jira根因含重复标记关键词[{hit}]: {jira_rc[:60]}"
                elif any(kw in ai_rc for kw in _INVALID_AI_RC_KEYWORDS):
                    hit = next(kw for kw in _INVALID_AI_RC_KEYWORDS if kw in ai_rc)
                    skip_reason = f"AI根因含无效关键词[{hit}]: {ai_rc[:60]}"
                if skip_reason:
                    cf_type = field_type_map.get(cf_field, 0)
                    write_val = "无法判断" if cf_type != 2 else 0
                    fields_to_write[cf_field] = write_val
                    success_count += 1
                    logger.info("置信度跳过 bugid=%s reason=%s", bugid, skip_reason)
                    _sse_d = {'type': 'progress', 'index': idx + 1, 'total': total,
                                                'bugid': bugid, 'status': 'invalid', 'score': '无法判断',
                                                'jira_rootcause': jira_rc, 'ai_rootcause': ai_rc,
                                                'record_id': t['record_id'], 'write_fields': fields_to_write,
                                                'conf_empty': conf_empty,
                                                'msg': skip_reason}
                    yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
                    continue
                # 5. 多路语义对比：取最高分
                jira_core = _extract_core_rootcause(jira_rc)
                ai_core = _extract_core_rootcause(ai_rc)
                logger.info("置信度对比 bugid=%s | jira_core=[%s] | ai_core=[%s]", bugid, jira_core[:80], ai_core[:80])
                # 路1: 核心语义对比（可能带上下文）
                score = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_core, ai_core)
                score = round(score, 3)
                is_pass = score >= threshold
                logger.info("置信度核心对比 bugid=%s score=%.3f pass=%s", bugid, score, is_pass)
                ai_conclusion = ""
                # 路2: 仅结论句对比（避免负面上下文拉低分数）
                if not is_pass:
                    ai_conclusion = _extract_conclusion_only(ai_rc)
                    if ai_conclusion and ai_conclusion != ai_core:
                        sc2 = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_core, ai_conclusion)
                        sc2 = round(sc2, 3)
                        logger.info("置信度结论对比 bugid=%s score=%.3f conclusion=[%s]", bugid, sc2, ai_conclusion[:80])
                        if sc2 > score:
                            score = sc2
                            is_pass = score >= threshold
                # 路3: 实体句匹配（从AI根因中提取同时含Jira关键实体的句子对比）
                if not is_pass:
                    import re as _re2
                    # 提取Jira根因中的有意义短关键词（2-3字），过滤噪声词
                    _noise_kw = {"这个", "问题", "符合", "设计", "导致", "因为", "所以", "因此", "但是", "然后"}
                    # 先用标点拆分，再对每个子串提取2-3字关键词
                    _jira_parts = _re2.split(r'[^\u4e00-\u9fff]+', jira_rc)
                    jira_keywords = []
                    for p in _jira_parts:
                        for kw_len in (3, 2):
                            for i in range(len(p) - kw_len + 1):
                                kw = p[i:i+kw_len]
                                if kw not in _noise_kw and kw not in jira_keywords:
                                    jira_keywords.append(kw)
                    if jira_keywords:
                        entity_sent = _extract_entity_sentence(ai_rc, jira_keywords)
                        if entity_sent and entity_sent != ai_core:
                            sc3 = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_core, entity_sent)
                            sc3 = round(sc3, 3)
                            logger.info("置信度实体句对比 bugid=%s score=%.3f entity_sent=[%s] keywords=%s", bugid, sc3, entity_sent[:80], jira_keywords[:8])
                            if sc3 > score:
                                score = sc3
                                is_pass = score >= threshold
                # 路4: 逐句兆底对比
                if not is_pass and len(ai_rc) > 80:
                    ai_sents = _split_semantic_sentences(ai_rc)
                    if len(ai_sents) > 1:
                        sent_max = 0.0
                        sent_best = ""
                        for s in ai_sents:
                            sc = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_core, s)
                            if sc > sent_max:
                                sent_max = sc
                                sent_best = s[:60]
                        sent_max = round(sent_max, 3)
                        logger.info("置信度逐句兆底 bugid=%s sent_max=%.3f best=[%s] sents=%d", bugid, sent_max, sent_best, len(ai_sents))
                        if sent_max >= threshold:
                            score = sent_max
                            is_pass = True
                # 路5: 全文原始对比（用原始Jira根因与原始AI根因，让模型看完整上下文）
                if not is_pass and len(ai_rc) > 50:
                    sc5 = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_rc[:300], ai_rc[:500])
                    sc5 = round(sc5, 3)
                    logger.info("置信度全文对比 bugid=%s score=%.3f", bugid, sc5)
                    if sc5 > score:
                        score = sc5
                        is_pass = score >= threshold
                cf_type = field_type_map.get(cf_field, 0)
                write_val = float(score) if cf_type == 2 else str(score)
                fields_to_write[cf_field] = write_val
                if is_pass:
                    success_count += 1
                _sse_d = {'type': 'progress', 'index': idx + 1, 'total': total,
                                            'bugid': bugid, 'status': 'pass' if is_pass else 'low',
                                            'score': score,
                                            'jira_rootcause': jira_rc, 'ai_rootcause': ai_rc,
                                            'record_id': t['record_id'], 'write_fields': fields_to_write,
                                            'conf_empty': conf_empty,
                                            'msg': '' if is_pass else f'相似度{score}<{threshold}'}
                yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
            except Exception as e:
                fail_count += 1
                _sse_d = {'type': 'progress', 'index': idx + 1, 'total': total,
                                            'bugid': bugid, 'status': 'fail', 'score': 0,
                                            'conf_empty': conf_empty,
                                            'msg': str(e)[:120]}
                yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
        
        _sse_d = {'type': 'done', 'total': total, 'updated': 0,
                                    'passed': success_count, 'failed': fail_count,
                                    'msg': f'分析完成: {total}条, 达标{success_count}条, 未达标{total - success_count - fail_count}条, 跳过/失败{fail_count}条'}
        yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/api/test/confidence_batch_commit", response_model=ApiResponse)
async def test_confidence_batch_commit(request: Request):
    """置信度批量写入提交：接收前端筛选后的记录列表，批量写入多维表格"""
    import os, re, json
    from src.clients import feishu_client
    body = await request.json() or {}
    items = body.get("items") or []
    if not items:
        return _fail("待写入列表为空")
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    # 逐条写入，跳过 record_id 为空的
    written = 0
    errors = []
    for item in items:
        record_id = item.get("record_id", "")
        fields = item.get("write_fields") or {}
        if not record_id or not fields:
            continue
        try:
            await _run_blocking(feishu_client.update_bitable_records, app_token, table_id, [{"record_id": record_id, "fields": fields}])
            written += 1
        except Exception as e:
            errors.append(f"{item.get('bugid', '?')}: {str(e)[:80]}")
    msg = f"写入完成: {written}/{len(items)} 条"
    if errors:
        msg += f"，{len(errors)} 条失败"
    return _ok({"written": written, "errors": errors}, msg)


# ---- 未分析 Bug 提取（以往/新增）----


@router.post("/api/test/unanalyzed_bugs")
async def test_unanalyzed_bugs(request: Request):
    """提取未分析的 Bug：JQL 搜索时直接带 customfield_13714，筛选该字段不存在或为空的记录"""
    import os, re, json
    import asyncio
    import csv as _csv
    import json as _json
    body = await request.json() or {}
    jql = body.get("jql", "").strip()
    filter_ai_init = body.get("filter_ai_init", True)
    if not jql:
        return _fail("JQL 不能为空")

    async def event_generator():
        from src.clients import jira_client as _jc
        loop = asyncio.get_event_loop()
        yield f"data: {_json.dumps({'type': 'start', 'jql': jql}, ensure_ascii=False)}\n\n"
        # 搜索时直接带上 customfield_13714 字段，无需逐个 fetch
        def _search():
            cfg = load_config()["jira_api"]
            headers, auth = {}, None
            token = cfg.get("token", "")
            if token:
                auth_type = cfg.get("auth_type", "bearer").lower()
                if auth_type == "bearer":
                    headers["Authorization"] = f"Bearer {token}"
                elif cfg.get("username"):
                    auth = (cfg["username"], token)
            search_url = cfg["url"].rsplit("/issue", 1)[0] + "/search"
            fields = "summary,status,created," + _AI_INIT_FIELD_ID
            all_issues, start_at, page_size = [], 0, 1000
            while len(all_issues) < 25000:
                result = _jc.http_get(search_url, params={"jql": jql, "maxResults": page_size,
                                                          "startAt": start_at, "fields": fields},
                                      timeout=cfg.get("timeout", 30), auth=auth, headers=headers)
                issues = result.get("issues", [])
                if not issues:
                    break
                all_issues.extend(issues)
                total = result.get("total", 0)
                if len(all_issues) >= total or len(issues) < page_size:
                    break
                start_at += len(issues)
            return all_issues[:25000]
        try:
            issues = await loop.run_in_executor(None, _search)
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'message': f'JQL 搜索失败: {e}'}, ensure_ascii=False)}\n\n"
            return
        yield f"data: {_json.dumps({'type': 'searched', 'total': len(issues)}, ensure_ascii=False)}\n\n"
        if not issues:
            yield f"data: {_json.dumps({'type': 'done', 'results': [], 'message': '搜索无结果'}, ensure_ascii=False)}\n\n"
            return
        # 筛选未分析记录：filter_ai_init=True时过滤已有AI初步分析的，False时保留全部
        unanalyzed = []
        for iss in issues:
            f = iss.get("fields") or {}
            if filter_ai_init:
                val = f.get(_AI_INIT_FIELD_ID)
                has_val = bool(val and str(val).strip() and str(val).strip().lower() not in ("none", "null"))
                if has_val:
                    continue
            unanalyzed.append({
                "bugid": iss.get("key", ""),
                "created": (f.get("created") or "")[:19].replace("T", " "),
                "status": ((f.get("status") or {}).get("name") or ""),
                "summary": (f.get("summary") or "")[:80],
            })
        unanalyzed.sort(key=lambda x: x["created"])
        # 保存 CSV（每个文件最多 2000 条，超出自动拆分）
        os.makedirs(_UNANALYZED_DIR, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        csv_paths = []
        chunk_size = 2000
        for i in range(0, max(len(unanalyzed), 1), chunk_size):
            chunk = unanalyzed[i:i + chunk_size]
            if not chunk:
                break
            idx = i // chunk_size + 1
            fname = f"unanalyzed_{date_str}_{idx}.csv" if len(unanalyzed) > chunk_size else f"unanalyzed_{date_str}.csv"
            csv_path = os.path.join(_UNANALYZED_DIR, fname)
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as cf:
                writer = _csv.writer(cf)
                writer.writerow(["Jira号", "创建时间", "状态", "摘要"])
                for r in chunk:
                    writer.writerow([r["bugid"], r["created"], r["status"], r["summary"]])
            csv_paths.append(csv_path)
        paths_str = ", ".join(os.path.basename(p) for p in csv_paths)
        logger.info("未分析 Bug 提取完成: %d/%d 未分析, 已保存 %d 个文件: %s",
                    len(unanalyzed), len(issues), len(csv_paths), paths_str)
        yield f"data: {_json.dumps({'type': 'done', 'results': unanalyzed, 'csv_paths': csv_paths, 'total': len(issues), 'message': f'提取完成: {len(unanalyzed)}/{len(issues)} 未分析，已保存 {len(csv_paths)} 个文件'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- 线上AI日志分析批量执行 ----


@router.get("/api/test/prod_csv_files", response_model=ApiResponse)
def test_prod_csv_files():
    """列出 data/unanalyzed/ 下所有 CSV 文件，分为未分析文件和执行结果文件（含成功/失败统计）"""
    import os, re, json
    import csv as _csv
    unanalyzed, prod_results = [], []
    if os.path.isdir(_UNANALYZED_DIR):
        for fname in sorted(os.listdir(_UNANALYZED_DIR), reverse=True):
            if not fname.endswith(".csv"):
                continue
            fpath = os.path.join(_UNANALYZED_DIR, fname)
            count = 0
            success = 0
            fail = 0
            try:
                with open(fpath, "r", encoding="utf-8-sig") as f:
                    reader = _csv.DictReader(f)
                    for row in reader:
                        count += 1
                        result_val = (row.get("执行结果") or "").strip()
                        if result_val == "成功":
                            success += 1
                        elif result_val == "失败":
                            fail += 1
            except Exception:
                pass
            info = {"name": fname, "path": fpath, "count": count, "total": count, "success": success, "fail": fail}
            if fname.startswith("prod_batch_"):
                prod_results.append(info)
            else:
                unanalyzed.append(info)
    return _ok({"unanalyzed": unanalyzed, "prod_results": prod_results},
               f"未分析文件 {len(unanalyzed)} 个，结果文件 {len(prod_results)} 个")


@router.post("/api/test/prod_csv_read", response_model=ApiResponse)
async def test_prod_csv_read(request: Request):
    """读取指定 CSV 文件并返回全部记录，用于流程二的历史记录加载"""
    import os, re, json
    import csv as _csv
    body = await request.json() or {}
    fpath = str(body.get("path", "")).strip()
    if not fpath or not os.path.isfile(fpath):
        return _fail("文件不存在")
    records = []
    try:
        with open(fpath, "r", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                records.append(dict(row))
    except Exception as e:
        return _fail(f"读取 CSV 失败: {e}")
    return _ok({"records": records, "total": len(records)},
               f"已读取 {len(records)} 条记录")


@router.post("/api/test/prod_csv_bitable", response_model=ApiResponse)
async def test_prod_csv_bitable(request: Request):
    """读取批量执行 CSV 的 Jira 号，聚合多维表格分析数据（分析结果/触发来源/置信度/rootcause 等）"""
    import os, re, json
    import csv as _csv
    body = await request.json() or {}
    fpath = str(body.get("path", "")).strip()
    if not fpath or not os.path.isfile(fpath):
        return _fail("文件不存在")
    # 读取 CSV 获取 Jira 号和执行结果（兼容不同大小写列名）
    csv_items = []
    try:
        with open(fpath, "r", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                # 兼容 Jira号 / jira号 两种列名
                jira = (row.get("Jira号") or row.get("jira号") or "").strip()
                if jira:
                    csv_items.append({
                        "jira号": jira,
                        "执行结果": (row.get("执行结果") or "").strip(),
                        "备注": (row.get("备注") or "").strip(),
                        "执行时间": (row.get("执行时间") or "").strip(),
                    })
    except Exception as e:
        return _fail(f"读取 CSV 失败: {e}")
    if not csv_items:
        return _fail("CSV 中无有效 Jira 号")
    jira_set = set(item["jira号"] for item in csv_items)
    # 从文件名解析执行时间，用于过滤多维表格历史记录
    fname = os.path.basename(fpath)
    batch_exec_time = ""
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{6})", fname)
    if m:
        batch_exec_time = f"{m.group(1)} {m.group(2)[:2]}:{m.group(2)[2:4]}:{m.group(2)[4:]}"
    # 查询多维表格匹配记录
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
    bitable_map = {}
    if app_token and table_id:
        try:
            records = await _run_blocking(feishu_client.list_bitable_records, app_token, table_id)
            for rec in records:
                fields = rec.get("fields", {})
                jira_key = _bitable_text(fields.get(bugid_field, ""))
                if not jira_key or jira_key not in jira_set:
                    continue
                rec_done = _bitable_text(fields.get("分析完成时间", ""))
                if batch_exec_time and rec_done and rec_done < batch_exec_time:
                    continue
                flat = _flatten_bitable_record(fields, report_field)
                flat["rootcause"] = _bitable_text(fields.get("rootcause", ""))
                flat["AI评论总结"] = _bitable_text(fields.get("AI评论总结", ""))
                flat["结果置信度"] = _bitable_text(fields.get("结果置信度", ""))
                bitable_map.setdefault(jira_key, []).append(flat)
        except Exception as e:
            logger.warning("聚合多维表格失败: %s", e)
    # 合并 CSV + 多维表格数据
    results = []
    for item in csv_items:
        jira_no = item["jira号"]
        bt_list = bitable_map.get(jira_no, [])
        if bt_list:
            bt_list.sort(key=lambda x: x.get("分析完成时间", ""))
            bf = bt_list[0]
            results.append({
                "jira号": jira_no,
                "执行结果": item["执行结果"],
                "分析结果": bf.get("分析结果", ""),
                "触发来源": bf.get("触发来源", ""),
                "结果置信度": bf.get("结果置信度", ""),
                "rootcause": bf.get("rootcause", ""),
                "AI评论总结": bf.get("AI评论总结", ""),
                "飞书报告链接": bf.get("飞书报告链接", ""),
                "错误信息": bf.get("错误信息", ""),
                "分析问题时间": bf.get("分析问题时间", ""),
                "分析完成时间": bf.get("分析完成时间", ""),
                "人工审核结果": bf.get("人工审核结果", ""),
                "备注": item["备注"],
            })
        else:
            results.append({
                "jira号": jira_no,
                "执行结果": item["执行结果"],
                "分析结果": "", "触发来源": "", "结果置信度": "",
                "rootcause": "", "AI评论总结": "", "飞书报告链接": "",
                "错误信息": "", "分析问题时间": "", "分析完成时间": "",
                "人工审核结果": "", "备注": item["备注"],
            })
    matched = len(jira_set & set(bitable_map.keys()))
    success_cnt = sum(1 for r in results if r["分析结果"] == "成功")
    fail_cnt = sum(1 for r in results if r["分析结果"] == "失败")
    return _ok({"records": results, "total": len(results), "matched": matched,
                "success_count": success_cnt, "fail_count": fail_cnt},
               f"已加载 {len(results)} 条记录，多维表格命中 {matched} 个")


@router.post("/api/test/prod_batch_run", response_model=ApiResponse)
async def test_prod_batch_run(request: Request):
    """AI日志分析批量执行：读取CSV → 提取触发时间(优先云端) → 去重 → 批量调用接口（支持PC/线上模式）"""
    import os, re, json
    import asyncio
    import json as _json
    import csv as _csv
    import queue
    from src.services.trigger_ops import (
        _save_trigger_time_to_cloud, _load_cloud_trigger_cache,
    )
    from src.services.report_ops import _upload_batch_to_cloud
    from src.services.server_legacy import _diag_extract_time_from_video_simple
    body = await request.json() or {}
    csv_files = body.get("csv_files") or []
    direct_bugids = body.get("bugids") or []
    skip_existing = body.get("skip_existing", True)  # 是否过滤已执行成功的 Jira 号
    skip_cloud_cache = body.get("skip_cloud_cache", False)  # 跳过云端缓存，强制重新提取触发时间
    filter_pc_only = body.get("filter_pc_only", False)  # 仅过滤PC来源的正确+通用失败
    filter_online_only = body.get("filter_online_only", False)  # 仅过滤线上来源的正确+通用失败
    max_count = int(body.get("max_count") or 0)  # 抽取数量上限，0 表示不限制
    exec_mode = body.get("exec_mode") or ""  # 执行模式：online(线上) / pc
    # 兼容旧版前端未传 exec_mode 时，从 trigger_source 推断
    if not exec_mode:
        _ts = (body.get("trigger_source") or "").upper()
        exec_mode = "pc" if _ts in ("PC", "JIRA_ANALYZE") else "online"
    # 前端已提取的触发时间（抽样步骤已获取，优先使用避免重复提取）
    frontend_trigger_times = body.get("trigger_times") or {}
    # 批量执行元数据
    mode_label = "线上" if exec_mode == "online" else "PC"
    _batch_meta = {
        "分析并发数": str(body.get("analysis_concurrency", "5")),
        "下载并发数": str(body.get("download_concurrency", "2")),
        "模型": str(body.get("model", "deepseek-v-pro")),
        "触发来源": str(body.get("trigger_source", mode_label)),
    }
    # 从 CSV 和直接输入两种来源收集 Jira 号
    all_bugids = list(direct_bugids)
    for fpath in csv_files:
        try:
            with open(fpath, "r", encoding="utf-8-sig") as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    jira = row.get("Jira号", "").strip()
                    if jira:
                        all_bugids.append(jira)
        except Exception as e:
            logger.warning("读取 CSV 失败 %s: %s", fpath, e)
    if not all_bugids:
        return _fail("无 Jira 号，请选择 CSV 文件或输入 Jira 号")
    # 去重
    seen = set()
    bugids = []
    for b in all_bugids:
        if b not in seen:
            seen.add(b)
            bugids.append(b)
    dedup_count = len(all_bugids) - len(bugids)
    # 重复过滤：查询多维表格，跳过已执行成功或人工审核确认为无效bug的 Jira 号
    # 支持 skip_existing（全量过滤）和 filter_pc_only/filter_online_only（按来源过滤）
    any_filter = skip_existing or filter_pc_only or filter_online_only
    skipped_count = 0
    if any_filter:
        try:
            from src.clients import feishu_client
            cfg_fb = load_config().get("feishu_bitable", {})
            bt_records = await _run_blocking(feishu_client.list_bitable_records, cfg_fb.get("app_token", ""), cfg_fb.get("table_id", ""))
            bugid_field = cfg_fb.get("bugid_field", "jira号")
            existing_exclude = set()
            for rec in bt_records:
                fields = rec.get("fields", {})
                fv = fields.get(bugid_field, "")
                if isinstance(fv, list):
                    fv = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in fv)
                elif isinstance(fv, dict):
                    fv = fv.get("text", str(fv))
                jira_key = str(fv).strip()
                if not jira_key:
                    continue
                if not _is_bitable_excluded(fields, bugid_field):
                    continue
                # 按来源过滤：PC/线上分别判断
                trigger_source = _bitable_text(fields.get("触发来源", ""))
                is_pc = trigger_source == "jira_analyze"
                if filter_pc_only and filter_online_only:
                    existing_exclude.add(jira_key)
                elif filter_pc_only:
                    if is_pc:
                        existing_exclude.add(jira_key)
                elif filter_online_only:
                    if not is_pc:
                        existing_exclude.add(jira_key)
                else:
                    existing_exclude.add(jira_key)
            if existing_exclude:
                before = len(bugids)
                bugids = [b for b in bugids if b not in existing_exclude]
                skipped_count = before - len(bugids)
                logger.info("多维表格过滤: 跳过 %d 个 Jira 号 (skip=%s, pc=%s, online=%s)",
                            skipped_count, skip_existing, filter_pc_only, filter_online_only)
            # 同来源云端批量记录去重：只排除同来源已执行的Jira，PC和线上允许重复
            cloud_source = "jira_analyze" if filter_pc_only else ("parseFullTicket" if filter_online_only else "")
            if cloud_source:
                cloud_executed = _get_same_source_executed_keys(cloud_source)
                if cloud_executed:
                    before_cloud = len(bugids)
                    bugids = [b for b in bugids if b not in cloud_executed]
                    added_cloud = before_cloud - len(bugids)
                    if added_cloud:
                        skipped_count += added_cloud
                        logger.info("云端同来源去重(%s): 排除 %d 条", cloud_source, added_cloud)
        except Exception as e:
            logger.warning("多维表格重复过滤查询失败（跳过此检查）: %s", e)

    async def event_generator():
        import threading
        stop_event = threading.Event()
        batch_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        loop = asyncio.get_event_loop()
        run_bugids = list(bugids)  # 局部副本，避免闭包变量赋值冲突
        # 提取触发时间（优先前端已传入 > 云端缓存 > 重新提取）
        trigger_times = {}  # bugid -> time（只包含已成功获取的时间）
        skip_empty_mark = 0
        # 先合并前端传入的触发时间（抽样步骤已提取，包含 CSV 导入的时间）
        for b in run_bugids:
            if b in frontend_trigger_times and frontend_trigger_times[b]:
                trigger_times[b] = frontend_trigger_times[b]
        frontend_hit = len(trigger_times)
        cloud_keys = set()
        cloud_hit_count = 0
        skip_empty_mark = 0
        if not skip_cloud_cache:
            try:
                cloud_times, cloud_keys = await loop.run_in_executor(None, _load_cloud_trigger_cache)
                for b in run_bugids:
                    if b not in trigger_times and b in cloud_times and cloud_times[b]:
                        trigger_times[b] = cloud_times[b]
                    elif b not in trigger_times and b in cloud_keys:
                        skip_empty_mark += 1
            except Exception as e:
                logger.warning("云端触发时间加载失败: %s", e)
                cloud_keys = set()
            cloud_hit_count = len(trigger_times) - frontend_hit
        # 跳过云端缓存时，所有 bugid 都进入待提取池
        pending_pool = [b for b in run_bugids if b not in trigger_times and (skip_cloud_cache or b not in cloud_keys)]
        logger.info("前端传入 %d 条，云端补充 %d 条，空标记跳过 %d 条，待提取池 %d 条%s",
                    frontend_hit, cloud_hit_count, skip_empty_mark, len(pending_pool),
                    " (跳过云端缓存)" if skip_cloud_cache else "")
        yield f"data: {_json.dumps({'type': 'start', 'total': len(run_bugids), 'dedup': dedup_count, 'skipped': skipped_count, 'raw': len(all_bugids), 'max_count': max_count, 'frontend_hit': frontend_hit, 'cloud_hit': cloud_hit_count, 'skip_empty_mark': skip_empty_mark, 'need_fetch': len(pending_pool)}, ensure_ascii=False)}\n\n"
        extract_batch_size = 50
        while pending_pool:
            need = (max_count - len(trigger_times)) if max_count > 0 else len(pending_pool)
            if need <= 0:
                break
            batch = pending_pool[:extract_batch_size]
            pending_pool = pending_pool[extract_batch_size:]
            if not batch:
                break
            from src.services.server_legacy import _diag_extract_time_from_video_simple, _has_gmlogger_logs, _diag_extract_time_from_images
            from src.clients import jira_client as _jc
            def _extract_one(bugid):
                try:
                    issue = _jc.fetch_issue(bugid)
                    # gmlogger 前置检查：无 gmlogger 附件直接跳过所有时间提取（与机器人流程一致）
                    attachments = (issue.get("fields") or {}).get("attachment") or []
                    if not _has_gmlogger_logs(attachments, bugid):
                        logger.info("触发时间: %s 无gmlogger附件，跳过", bugid)
                        return bugid, None  # None 表示无gmlogger，不写空标签
                    # 评论/字段提取优先（基于对比实验结果：文本提取准确率最高且速度最快）
                    # skip_attachment=True：有视频时先试视频，附件名才是真正最后兑底
                    tt = _jc.extract_trigger_time_from_issue(issue, skip_attachment=True)
                    if tt:
                        if not isinstance(tt, str):
                            tt = tt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(tt, 'strftime') else str(tt)
                        return bugid, tt
                    # 文本未命中，视频OCR兑底
                    tt = _diag_extract_time_from_video_simple(issue)
                    if tt:
                        if not isinstance(tt, str):
                            tt = tt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(tt, 'strftime') else str(tt)
                        return bugid, tt
                    # 视频也未命中，图片OCR再兑底
                    cfg_api = load_config().get("jira_api", {})
                    img_h = {}
                    img_tok = cfg_api.get("token", "")
                    if img_tok:
                        img_h["Authorization"] = f"Bearer {img_tok}"
                    img_to = max(int(cfg_api.get("timeout", 30)), 120)
                    img_tt, _ = _diag_extract_time_from_images(issue, img_h, img_to, bugid)
                    if img_tt:
                        if not isinstance(img_tt, str):
                            img_tt = img_tt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(img_tt, 'strftime') else str(img_tt)
                        return bugid, img_tt
                    # 所有方法均失败，附件文件名作为最终兑底
                    att_tt = _jc.extract_attachment_time(issue)
                    if att_tt:
                        return bugid, att_tt
                except Exception:
                    pass
                return bugid, ""
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                futures = {pool.submit(_extract_one, b): b for b in batch}
                done_count = 0
                for future in concurrent.futures.as_completed(futures):
                    done_count += 1
                    try:
                        bugid, tt = future.result()
                        if tt:
                            trigger_times[bugid] = tt
                            _save_trigger_time_to_cloud(bugid, tt, source="线上批量(预提取)")
                        elif tt is None:
                            pass  # 无gmlogger，不写空标签到云端（下次仍可重试）
                        else:
                            _save_trigger_time_to_cloud(bugid, "", source="线上批量(预提取失败)")
                    except Exception:
                        pass
                    if done_count % 20 == 0 or done_count == len(batch):
                        yield f"data: {_json.dumps({'type': 'extract_progress', 'current': done_count, 'total': len(batch), 'hit': len(trigger_times)}, ensure_ascii=False)}\n\n"
        if max_count > 0:
            run_bugids = [b for b in run_bugids if b in trigger_times][:max_count]
        else:
            run_bugids = [b for b in run_bugids if b in trigger_times]
        skipped_no_time = len(bugids) - len(run_bugids)
        yield f"data: {_json.dumps({'type': 'extract_done', 'total': len(run_bugids), 'with_time': len(trigger_times), 'without_time': skipped_no_time, 'skip_empty_mark': skip_empty_mark}, ensure_ascii=False)}\n\n"
        # 批量执行接口（支持PC/线上模式）
        result_queue = queue.Queue()
        import threading as _th
        _exec_concurrency = int(body.get("analysis_concurrency") or 5)
        _exec_sem = _th.Semaphore(_exec_concurrency)  # 执行阶段并发控制
        _MAX_RETRIES = 1  # 失败后重试次数
        _RETRY_DELAY = 3  # 重试间隔（秒）

        def _run_one(bugid):
            if stop_event.is_set():
                return
            from src.clients.base import http_post
            # 无触发时间的 Jira 号跳过
            exec_time = trigger_times.get(bugid, "")
            if not exec_time:
                result_queue.put({"Jira号": bugid, "执行结果": "失败",
                                  "备注": "无触发时间", "触发时间": "",
                                  "执行时间": batch_start_time,
                                  "status": "fail", "msg": "无触发时间"})
                return
            last_err = ""
            for _attempt in range(1 + _MAX_RETRIES):
                if stop_event.is_set():
                    return
                try:
                    with _exec_sem:
                        if exec_mode == "online":
                            payload = _build_prod_ai_payload(bugid, exec_time)
                            resp = http_post(_get_prod_ai_url(), payload, timeout=_get_prod_ai_cfg()["timeout"])
                        else:
                            cfg = load_config()["ai_log_api"]
                            payload = {cfg["bugid_field"]: bugid}
                            if cfg.get("trigger_time_field") and exec_time:
                                payload[cfg["trigger_time_field"]] = exec_time
                            resp = http_post(cfg["url"], payload, timeout=int(cfg.get("timeout", 60)))
                    if stop_event.is_set():
                        return
                    resp_code = resp.get("code") if isinstance(resp, dict) else None
                    resp_msg = str(resp.get("msg", "")) if isinstance(resp, dict) else str(resp)[:200]
                    is_ok = (resp_code == 200 or resp_code == 0 or resp_code == "200")
                    if is_ok and exec_mode == "pc":
                        is_ok = any(kw in resp_msg for kw in ["分析任务已启动", "后台处理", "正在分析"])
                    retry_note = f"（重试成功）" if _attempt > 0 else ""
                    result_queue.put({"Jira号": bugid, "执行结果": "成功" if is_ok else "失败",
                                      "备注": f"{retry_note}{resp_msg[:200]}", "触发时间": exec_time,
                                      "执行时间": batch_start_time,
                                      "status": "success" if is_ok else "fail", "msg": f"{retry_note}{resp_msg[:100]}"})
                    return  # 成功或业务失败都不重试，只有异常才重试
                except Exception as e:
                    last_err = str(e)[:200]
                    if _attempt < _MAX_RETRIES:
                        logger.info("%s 执行失败(第%d次)，%ds后重试: %s", bugid, _attempt + 1, _RETRY_DELAY, last_err)
                        import time as _time
                        _time.sleep(_RETRY_DELAY)
            # 所有重试耗尽
            retry_note = "（已重试）" if _MAX_RETRIES > 0 else ""
            result_queue.put({"Jira号": bugid, "执行结果": "失败",
                              "备注": f"{retry_note}{last_err}", "触发时间": trigger_times.get(bugid, ""),
                              "执行时间": batch_start_time,
                              "status": "fail", "msg": f"{retry_note}{last_err[:100]}"})

        for bugid in run_bugids:
            loop.run_in_executor(None, _run_one, bugid)

        results = []
        while len(results) < len(run_bugids):
            if await request.is_disconnected():
                stop_event.set()
                break
            try:
                item = result_queue.get_nowait()
                results.append(item)
                yield f"data: {_json.dumps({'type': 'progress', 'index': len(results), 'total': len(run_bugids), 'bugid': item['Jira号'], 'status': item['status'], 'msg': item.get('msg', ''), 'exec_time': item.get('触发时间', ''), 'analysis_time': item.get('执行时间', '')}, ensure_ascii=False)}\n\n"
            except queue.Empty:
                await asyncio.sleep(1)
        # 保存结果 CSV（同时写入 docs 目录供每日播报统计）
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        os.makedirs(_UNANALYZED_DIR, exist_ok=True)
        batch_csv = os.path.join(_UNANALYZED_DIR, f"prod_batch_{date_str}_{time_str}.csv")
        with open(batch_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = _csv.writer(f)
            writer.writerow(["Jira号", "执行结果", "触发时间", "执行时间", "备注",
                             "分析并发数", "下载并发数", "模型", "触发来源"])
            for r in results:
                writer.writerow([r["Jira号"], r["执行结果"], r.get("触发时间", ""), r.get("执行时间", ""), r.get("备注", ""),
                                 _batch_meta["分析并发数"], _batch_meta["下载并发数"],
                                 _batch_meta["模型"], _batch_meta["触发来源"]])
        success_count = sum(1 for r in results if r["执行结果"] == "成功")
        fail_count = len(results) - success_count
        no_time_count = sum(1 for r in results if r.get("备注") == "无触发时间")
        done_msg = f"执行完成：成功 {success_count}，失败 {fail_count}，去重 {dedup_count}，重复跳过 {skipped_count}，无触发时间 {no_time_count}"
        logger.info("%s批量执行完成: %s", mode_label, done_msg)
        # 内存级去重：标记本次执行的 JIRA 号，防止下一批次多维表格未更新导致重复
        _mark_executed(run_bugids)
        # 上传执行记录到云端
        cloud_url = ""
        try:
            doc_title = f"线上批量执行 {date_str} {time_str} ({success_count}/{len(results)})"
            cloud_url = _upload_batch_to_cloud(batch_csv, doc_title)
        except Exception as e:
            logger.warning("线上批量执行记录上传云端失败: %s", e)
        yield f"data: {_json.dumps({'type': 'done', 'total': len(results), 'success': success_count, 'fail': fail_count, 'dedup': dedup_count, 'skipped': skipped_count, 'csv_path': batch_csv, 'cloud_url': cloud_url, 'message': done_msg}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})




@router.post("/api/test/upload_bug_file", response_model=ApiResponse)
async def upload_bug_file(file: UploadFile = File(None)):
    """上传 bug 单数据文件（CSV/Excel），解析后缓存，返回 file_id 供批量对比引用"""
    import os, re, json
    from src.services.server_legacy import _uploaded_files
    from src.clients import bug_source
    if not file or not file.filename:
        return _fail("未找到上传文件或文件名为空")
    try:
        content = await _read_upload_limited(file, "上传文件")
        rows = bug_source.parse_uploaded_file(content, file.filename)
        if not rows:
            return _fail("文件中未找到有效数据或缺少 bugid 列")
        global _upload_seq
        _upload_seq += 1
        file_id = f"file_{_upload_seq}"
        _uploaded_files[file_id] = rows
        # 只保留最近 N 个上传结果，避免全局 dict 无限增长
        while len(_uploaded_files) > _MAX_UPLOADED_FILES:
            _uploaded_files.pop(next(iter(_uploaded_files)), None)
        logger.info("上传文件解析完成: file_id=%s, %d 行", file_id, len(rows))
        return _ok({"file_id": file_id, "row_count": len(rows)}, f"文件解析完成，共 {len(rows)} 条数据")
    except Exception as e:
        logger.error("文件上传解析失败: %s", e)
        return _fail(str(e))


@router.post("/api/test/batch_compare", response_model=ApiResponse)
async def batch_compare(request: Request):
    """批量评论对比：支持分号/逗号分隔的 bugid 列表（最多 30 个），返回汇总表格"""
    import os, re, json
    from src.services.server_legacy import _uploaded_files
    body = await request.json() or {}
    raw_bugids = str(body.get("bugids", "")).strip()
    if not raw_bugids:
        return _fail("bugid 列表不能为空")
    bugids = _parse_bugids(raw_bugids)
    if not bugids:
        return _fail("未解析到有效 bugid")
    trigger_times = body.get("trigger_times") or {}
    # 获取上传文件数据（可选）
    file_id = body.get("file_id")
    uploaded_rows = _uploaded_files.get(file_id) if file_id else None
    try:
        results = []
        for bugid in bugids:
            try:
                result = _compare_single_bug(bugid, trigger_times.get(bugid), uploaded_rows)
                results.append(result)
            except Exception as e:
                logger.error("批量对比中 bugid=%s 失败: %s", bugid, e)
                results.append({
                    "bugid": bugid, "error": str(e)[:200],
                    "root_cause_ok": False, "comment_compare_ok": False, "all_ok": False,
                    "root_cause_score": 0.0, "layer1_score": 0.0, "layer2_score": 0.0,
                    "conclusion": f"分析异常: {str(e)[:80]}",
                })
        summary = {
            "total": len(results),
            "all_match_count": sum(1 for r in results if r.get("all_ok")),
            "root_cause_match_count": sum(1 for r in results if r.get("root_cause_ok")),
            "comment_match_count": sum(1 for r in results if r.get("comment_compare_ok")),
            "skipped_count": sum(1 for r in results if r.get("skipped")),
            "results": results,
        }
        return _ok(summary, f"批量对比完成: {len(results)} 个 bug")
    except Exception as e:
        logger.error("批量对比失败: %s", e)
        return _fail(str(e))


@router.post("/api/test/check_endpoints", response_model=ApiResponse)
def check_endpoints(request: Request):
    """接口连通性检测：逐个测试所有已配置 API 的可达性与响应"""
    import os, re, json
    import time as _time
    import httpx as _httpx
    cfg = load_config()
    results = []

    def _test(name, url, method, timeout=10, headers=None, json_body=None, data_body=None,
              truncate=True):
        t0 = _time.time()
        try:
            ht = _httpx.Timeout(timeout, connect=5)
            if method == "GET":
                r = _httpx.get(url, headers=headers, timeout=ht, follow_redirects=True)
            elif data_body:
                r = _httpx.post(url, data=data_body, headers=headers, timeout=ht)
            else:
                r = _httpx.post(url, json=json_body or {}, headers=headers, timeout=ht)
            elapsed = round(_time.time() - t0, 2)
            # 只要有 HTTP 响应（任何状态码），即认为可达
            ok = True
            try:
                raw = r.json()
                detail = raw if not truncate else str(raw)[:300]
            except Exception:
                detail = r.text if not truncate else r.text[:300]
            return {"name": name, "url": url, "ok": ok, "elapsed": elapsed,
                    "status_code": r.status_code, "detail": detail}
        except _httpx.ConnectTimeout:
            return {"name": name, "url": url, "ok": False,
                    "elapsed": round(_time.time() - t0, 2), "detail": "ConnectTimeout - 连接超时，服务不可达"}
        except _httpx.ReadTimeout:
            return {"name": name, "url": url, "ok": True,
                    "elapsed": round(_time.time() - t0, 2),
                    "detail": "ReadTimeout - 接口可达但响应超时（异步任务可能仍在执行）"}
        except _httpx.ConnectError as e:
            msg = str(e)
            if "10061" in msg:
                detail = "连接被拒绝，端口未开放"
            elif "getaddrinfo" in msg:
                detail = "DNS 解析失败"
            else:
                detail = f"ConnectError: {msg[:80]}"
            return {"name": name, "url": url, "ok": False,
                    "elapsed": round(_time.time() - t0, 2), "detail": detail}
        except Exception as e:
            return {"name": name, "url": url, "ok": False,
                    "elapsed": round(_time.time() - t0, 2),
                    "detail": f"{type(e).__name__}: {str(e)[:80]}"}

    # 1. AI 日志分析接口（异步接口，返回 200 即表示可达，不截断响应内容）
    ai_cfg = cfg.get("ai_log_api", {})
    if not ai_cfg.get("mock") and ai_cfg.get("url"):
        # 按实际 API 规格发送 issue_key + problem_time
        ai_body = {ai_cfg.get("bugid_field") or "issue_key": "VCU-501224"}
        time_field = ai_cfg.get("trigger_time_field") or ""
        if time_field:
            ai_body[time_field] = "2026-08-19 10:00:00"
        results.append(_test("AI 日志分析接口", ai_cfg["url"], "POST",
                             timeout=float(ai_cfg.get("timeout", 15)),
                             headers={"Content-Type": "application/json"},
                             json_body=ai_body,
                             truncate=False))

    # 2. Jira REST API
    jira_cfg = cfg.get("jira_api", {})
    if not jira_cfg.get("mock") and jira_cfg.get("url"):
        jira_url = jira_cfg["url"]
        if not jira_url.endswith("/issue"):
            jira_url = jira_url.rstrip("/") + "/issue"
        headers = {}
        if jira_cfg.get("auth_type") == "bearer" and jira_cfg.get("token"):
            headers["Authorization"] = f"Bearer {jira_cfg['token']}"
        results.append(_test("Jira REST API", f"{jira_url}/VCU-501224", "GET", headers=headers))

    ok_count = sum(1 for r in results if r["ok"])
    return _ok(results, f"检测完成：{ok_count}/{len(results)} 个接口可用")


@router.post("/api/test/internal_api", response_model=ApiResponse)
async def test_internal_api(request: Request):
    """单独测试内网接口（AI日志/Diana/Token），返回完整原始响应"""
    import os, re, json
    import time as _time
    import httpx as _httpx
    body = await request.json() or {}
    which = body.get("which", "")
    cfg = body.get("config", {})
    t0 = _time.time()
    try:
        timeout = float(cfg.get("timeout", 15))
        ht = _httpx.Timeout(timeout, connect=8)
        if which == "ai_log":
            url = cfg.get("url", "")
            # bugid_field 是 API 参数名（如 issue_key），"VCU-501224" 为测试值
            param_name = cfg.get("bugid_field") or "issue_key"
            payload = {param_name: "VCU-501224"}
            # 排除 meta 配置字段，避免误发送给 API
            meta_keys = ("url", "timeout", "bugid_field", "trigger_time_field",
                         "mock", "custom_header")
            for k, v in cfg.items():
                if k not in meta_keys and v:
                    try:
                        payload[k] = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        payload[k] = v
            r = _httpx.post(url, json=payload, timeout=ht,
                            headers={"Content-Type": "application/json"})
        elif which == "feishu_bitable":
            # 飞书多维表格连通性测试：支持 Token/Cookie 两种模式
            from src.clients import feishu_client
            wiki_token = cfg.get("wiki_token", "")
            table_id = cfg.get("table_id", "")
            view_id = cfg.get("view_id", "")
            app_token = ""
            # 临时更新配置以便 feishu_client 使用
            import src.config as cfg_module
            original_cfg = cfg_module.load_config()
            merged = dict(original_cfg.get("feishu_bitable", {}))
            merged.update({k: v for k, v in cfg.items() if v})
            original_cfg["feishu_bitable"] = merged
            # 根据模式获取 app_token
            if feishu_client._is_cookie_mode():
                # Cookie 模式：从 wiki 页面提取
                if wiki_token:
                    app_token = feishu_client.cookie_get_app_token_from_wiki(wiki_token)
            else:
                # Token 模式：通过 Open API
                app_id = cfg.get("app_id", "")
                app_secret = cfg.get("app_secret", "")
                feishu_client.get_tenant_access_token(app_id, app_secret)
                if wiki_token:
                    try:
                        app_token = feishu_client.get_wiki_node_app_token(wiki_token)
                    except Exception:
                        app_token = wiki_token
            # 查询表格记录
            records = await _run_blocking(feishu_client.list_bitable_records, app_token, table_id, view_id)
            elapsed = round(_time.time() - t0, 2)
            mode = "Cookie" if feishu_client._is_cookie_mode() else "Token"
            return _ok({"ok": True, "elapsed": elapsed, "status_code": 200,
                         "response": {"record_count": len(records), "app_token": app_token,
                                      "mode": mode,
                                      "sample_fields": list(records[0].get("fields", {}).keys()) if records else []}})
        else:
            return _fail(f"未知接口类型: {which}")
        elapsed = round(_time.time() - t0, 2)
        # 完整原始响应，不做任何提取或截断
        try:
            raw = r.json()
        except Exception:
            raw = r.text
        # 内网接口连通性测试：只要服务器有 HTTP 响应（任何状态码），即认为可用。
        # HTTP 4xx/5xx 表示参数或服务端业务问题，不代表接口不可达。
        return _ok({"status_code": r.status_code, "response": raw,
                     "elapsed": elapsed, "ok": True})
    except _httpx.ConnectTimeout:
        return _ok({"ok": False, "elapsed": round(_time.time() - t0, 2),
                     "status_code": 0, "response": "ConnectTimeout - 连接超时，服务不可达"})
    except _httpx.ReadTimeout:
        return _ok({"ok": True, "elapsed": round(_time.time() - t0, 2),
                     "status_code": 0, "response": "ReadTimeout - 接口可达但响应超时（异步分析任务可能仍在后台执行）"})
    except _httpx.ConnectError as e:
        msg = str(e)
        detail = "连接被拒绝，端口未开放" if "10061" in msg else (
            "DNS 解析失败" if "getaddrinfo" in msg else f"ConnectError: {msg[:100]}")
        return _ok({"ok": False, "elapsed": round(_time.time() - t0, 2),
                     "status_code": 0, "response": detail})
    except Exception as e:
        return _ok({"ok": False, "elapsed": round(_time.time() - t0, 2),
                     "status_code": 0, "response": f"{type(e).__name__}: {str(e)}"})


@router.post("/api/test/diana_flow", response_model=ApiResponse)
async def test_diana_flow(request: Request):
    """Diana 接口自动化流程：分步执行 Token 获取 → 对话接口调用 → 返回值提取，每步展示完整结果"""
    import os, re, json
    import time as _time
    import httpx as _httpx
    body = await request.json() or {}
    content = body.get("content", "回复OK").strip() or "回复OK"
    steps = []
    active = _diana_client._get_active_cfg()
    env = active.get("env", "test")
    # ── 步骤1：获取 Token ──
    t0 = _time.time()
    try:
        token_url = active["token_url"]
        token_data = {
            "scope": "ALL", "grant_type": "client_credentials",
            "client_id": active["client_id"],
            "client_secret": active["client_secret"],
        }
        ht = _httpx.Timeout(30, connect=8)
        r = _httpx.post(token_url, data=token_data, timeout=ht,
                        headers={"Content-Type": "application/x-www-form-urlencoded", "Connection": "close"})
        elapsed = round(_time.time() - t0, 2)
        try:
            token_resp = r.json()
        except Exception:
            token_resp = r.text
        token = token_resp.get("access_token", "") if isinstance(token_resp, dict) else ""
        expires_in = token_resp.get("expires_in", "-") if isinstance(token_resp, dict) else "-"
        steps.append({"step": "步骤1：获取 Token", "ok": r.status_code == 200 and bool(token),
                      "status_code": r.status_code, "elapsed": elapsed,
                      "request_url": token_url, "request_data": token_data,
                      "response": token_resp,
                      "summary": f"token 长度: {len(token)}, 有效期: {expires_in}s" if token else "Token 获取失败"})
        if not token:
            return _ok({"steps": steps, "env": env, "ok": False}, "Token 获取失败，流程终止")
    except _httpx.ConnectTimeout:
        steps.append({"step": "步骤1：获取 Token", "ok": False, "elapsed": round(_time.time() - t0, 2),
                      "response": "ConnectTimeout - 连接超时", "summary": "Token 服务不可达"})
        return _ok({"steps": steps, "env": env, "ok": False}, "Token 接口连接超时")
    except _httpx.ConnectError as e:
        msg = str(e)
        detail = "连接被拒绝，端口未开放" if "10061" in msg else ("DNS 解析失败" if "getaddrinfo" in msg else f"ConnectError: {msg[:100]}")
        steps.append({"step": "步骤1：获取 Token", "ok": False, "elapsed": round(_time.time() - t0, 2),
                      "response": detail, "summary": "Token 服务不可达"})
        return _ok({"steps": steps, "env": env, "ok": False}, "Token 接口不可达")
    except Exception as e:
        steps.append({"step": "步骤1：获取 Token", "ok": False, "elapsed": round(_time.time() - t0, 2),
                      "response": f"{type(e).__name__}: {str(e)}", "summary": "Token 获取异常"})
        return _ok({"steps": steps, "env": env, "ok": False}, f"Token 获取异常: {e}")
    # ── 步骤2：调用 Diana 对话接口 ──
    t1 = _time.time()
    try:
        api_url = active["url"]
        if active.get("api_key"):
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}", "x-api-key": active["api_key"]}
        else:
            headers = {"access_token": token, "Content-Type": "application/json",
                       "apiTag": "V1", "clientRequestId": "01", "client_id": active.get("client_id", "")}
        model = active.get("model", "deepseek-v-flash")
        payload = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 500, "temperature": 0}
        ht2 = _httpx.Timeout(60, connect=10)
        r2 = _httpx.post(api_url, json=payload, timeout=ht2, headers=headers)
        elapsed2 = round(_time.time() - t1, 2)
        try:
            api_resp = r2.json()
        except Exception:
            api_resp = r2.text
        extracted = ""
        if isinstance(api_resp, dict):
            extracted = api_resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        steps.append({"step": "步骤2：调用 Diana 对话接口", "ok": r2.status_code == 200,
                      "status_code": r2.status_code, "elapsed": elapsed2,
                      "request_url": api_url, "request_headers": {k: (v[:50] + "..." if len(str(v)) > 50 else v) for k, v in headers.items()},
                      "request_payload": payload, "response": api_resp,
                      "summary": f"HTTP {r2.status_code}, 提取内容长度: {len(extracted)}"})
    except _httpx.ConnectTimeout:
        steps.append({"step": "步骤2：调用 Diana 对话接口", "ok": False, "elapsed": round(_time.time() - t1, 2),
                      "response": "ConnectTimeout - 连接超时", "summary": "Diana API 不可达"})
        return _ok({"steps": steps, "env": env, "ok": False}, "Diana API 连接超时")
    except _httpx.ConnectError as e:
        msg = str(e)
        detail = "连接被拒绝" if "10061" in msg else ("DNS 解析失败" if "getaddrinfo" in msg else f"ConnectError: {msg[:100]}")
        steps.append({"step": "步骤2：调用 Diana 对话接口", "ok": False, "elapsed": round(_time.time() - t1, 2),
                      "response": detail, "summary": "Diana API 不可达"})
        return _ok({"steps": steps, "env": env, "ok": False}, "Diana API 不可达")
    except Exception as e:
        steps.append({"step": "步骤2：调用 Diana 对话接口", "ok": False, "elapsed": round(_time.time() - t1, 2),
                      "response": f"{type(e).__name__}: {str(e)}", "summary": "API 调用异常"})
        return _ok({"steps": steps, "env": env, "ok": False}, f"API 调用异常: {e}")
    # ── 步骤3：提取返回值 content ──
    steps.append({"step": "步骤3：提取返回值 content", "ok": bool(extracted),
                  "elapsed": 0, "extracted_content": extracted,
                  "extract_path": "choices[0].message.content",
                  "summary": f"提取成功，内容长度: {len(extracted)}" if extracted else "未提取到 content 内容"})
    return _ok({"steps": steps, "env": env, "ok": True,
                "config": {"env": env, "token_url": active["token_url"], "url": active["url"],
                           "model": model, "client_id": active.get("client_id", "")}},
               f"Diana 自动化流程执行完成（{env} 环境）")


@router.post("/api/test/feishu_im_query", response_model=ApiResponse)
async def test_feishu_im_query(request: Request):
    """查询飞书 IM 对话消息：支持按群名查找或直接传 chat_id，返回最近消息"""
    import os, re, json
    import asyncio
    import traceback
    from src.clients import feishu_client
    body = await request.json() or {}
    chat_name = str(body.get("chat_name", "")).strip()
    chat_id = str(body.get("chat_id", "")).strip()
    start_time = str(body.get("start_time", "")).strip()
    page_size = int(body.get("page_size", 20))
    list_only = body.get("list_chats", False)  # 仅列出聊天，不查询消息
    loop = asyncio.get_event_loop()
    try:
        # 步骤1: 获取 chat_id
        step1 = {}
        if list_only or (not chat_id and not chat_name):
            # 列出所有聊天（群聊+单聊）
            all_chats = await loop.run_in_executor(None, feishu_client.list_chats, 100)
            chat_list = [{"chat_id": c.get("chat_id", ""), "name": c.get("name", ""),
                          "chat_type": c.get("chat_type", "")} for c in all_chats]
            return _ok({"chats": chat_list, "total": len(chat_list)},
                        f"共 {len(chat_list)} 个聊天")
        if not chat_id and chat_name:
            try:
                # 先查群聊，再查单聊
                chat_id = await loop.run_in_executor(None, feishu_client.find_chat_by_name, chat_name)
                step1 = {"action": "按名称查找", "chat_name": chat_name, "chat_id": chat_id or "未找到"}
            except Exception as e:
                step1 = {"action": "按名称查找", "chat_name": chat_name, "error": str(e)}
                return _fail(f"查找聊天失败: {e}", {"step1": step1})
        elif chat_id:
            step1 = {"action": "直接使用 chat_id", "chat_id": chat_id}
        if not chat_id:
            return _ok({"step1": step1}, f"未找到聊天 '{chat_name}'")
        # 步骤2: 拉取消息
        try:
            messages = await loop.run_in_executor(
                None, lambda: feishu_client.list_messages(chat_id, start_time=start_time or None, page_size=page_size))
        except Exception as e:
            return _fail(f"拉取消息失败: {e}", {"step1": step1})
        # 步骤3: 解析每条消息
        parsed = []
        for msg in messages:
            item = {"msg_type": msg.get("msg_type", ""), "create_time": msg.get("create_time", ""),
                    "sender": (msg.get("sender") or {}).get("sender_type", "")}
            body_content = msg.get("body", {}).get("content", "")
            if msg.get("msg_type") == "interactive" and body_content:
                import json as _json
                try:
                    card = _json.loads(body_content)
                    header = card.get("header", {})
                    title = (header.get("title", {}) or {}).get("content", "") if isinstance(header, dict) else ""
                    link = feishu_client.extract_report_link_from_card(msg)
                    item["card_title"] = title
                    item["report_link"] = link
                except Exception:
                    item["raw"] = body_content[:200]
            elif body_content:
                item["content"] = body_content[:300]
            parsed.append(item)
        return _ok({"step1": step1, "message_count": len(messages), "messages": parsed},
                    f"获取到 {len(messages)} 条消息")
    except Exception as e:
        logger.error("飞书 IM 查询失败: %s\n%s", e, traceback.format_exc())
        return _fail(str(e))


@router.post("/api/test/feishu_doc", response_model=ApiResponse)
async def test_feishu_doc(request: Request):
    """飞书文档下载：支持直接传入链接或从表格查找，内网兼容"""
    import os, re, json
    import asyncio
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    feishu_link = str(body.get("feishu_link") or "").strip()
    if not bugid and not feishu_link:
        return _fail("bugid 或 feishu_link 至少提供一个")
    try:
        from src.clients import feishu_client
        loop = asyncio.get_event_loop()
        # 如果直接传入了飞书链接，跳过表格查找
        if feishu_link and feishu_link.startswith("http"):
            logger.info("使用直接传入的飞书链接: %s", feishu_link)
        else:
            # 从飞书表格查找记录
            record = await loop.run_in_executor(
                None, lambda: __import__("src.clients.feishu_client", fromlist=["find_record_by_bugid"]).find_record_by_bugid(bugid)
            )
            if not record:
                return _fail(f"飞书表格中未找到 bugid={bugid} 的记录")
            fields = record.get("fields", {})
            feishu_link = feishu_client.extract_report_from_bitable(fields)
            if not feishu_link or not feishu_link.startswith("http"):
                return _fail(f"未找到有效飞书链接，提取值: {feishu_link}")
        # 提取 doc_id 并下载文档
        doc_id = feishu_client.extract_doc_id_from_url(feishu_link)
        if not doc_id:
            return _fail(f"无法从链接提取文档 ID: {feishu_link}")
        feishu_domain = feishu_client.extract_domain_from_url(feishu_link)
        md_content = await loop.run_in_executor(
            None, lambda: feishu_client.fetch_docx_as_markdown(doc_id, bugid=bugid, feishu_domain=feishu_domain)
        )
        doc_path = doc_generator.save_document(bugid, md_content)
        return _ok({
            "doc_path": doc_path,
            "feishu_link": feishu_link,
            "doc_id": doc_id,
            "content_length": len(md_content),
            "content": md_content,
        }, f"飞书文档下载成功，内容长度 {len(md_content)} 字")
    except Exception as e:
        logger.error("飞书文档下载失败: %s", e)
        return _fail(f"{type(e).__name__}: {e}")


# ==================== 功能11：线上正确执行跟进 ====================


@router.post("/api/test/online_followup_compare", response_model=ApiResponse)
def online_followup_compare(request: Request):
    """对比 PC 执行成功 vs 线上执行成功，找出线上缺失/失败的 Jira"""
    import os, re, json
    import json as _json
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
    except Exception as e:
        return _fail(f"多维表格查询失败: {e}")
    # 分类收集 PC 和线上执行成功的记录
    pc_success = {}   # jira号 -> {记录摘要}
    online_success = {}  # jira号 -> {记录摘要}
    online_all = {}   # jira号 -> [{记录摘要}]（包含失败的）
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(cfg.get("bugid_field", "jira号"), ""))
        if not jira_no:
            continue
        result_status = _bitable_text(fields.get("分析结果", ""))
        source = _bitable_text(fields.get("触发来源", ""))
        done_time = _bitable_text(fields.get("分析完成时间", ""))
        entry = {
            "jira号": jira_no, "分析结果": result_status, "触发来源": source,
            "分析完成时间": done_time,
            "触发时间": _bitable_text(fields.get("分析问题时间", "")),
            "错误信息": _bitable_text(fields.get("错误信息", "")),
        }
        if result_status == "成功":
            if source == "jira_analyze":
                pc_success[jira_no] = entry
            elif source in ("parseFullTicket", "feishu_bot"):
                online_success[jira_no] = entry
        # 收集线上所有记录（含失败）
        if source in ("parseFullTicket", "feishu_bot"):
            online_all.setdefault(jira_no, []).append(entry)
    # 计算差集：PC 成功但线上未成功
    pc_keys = set(pc_success.keys())
    online_ok_keys = set(online_success.keys())
    overlap_keys = pc_keys & online_ok_keys  # PC 成功中线上也成功的
    diff_keys = pc_keys - online_ok_keys
    diff_records = []
    for k in sorted(diff_keys):
        pc_entry = pc_success[k]
        online_recs = online_all.get(k, [])
        online_failed = [r for r in online_recs if r["分析结果"] != "成功"]
        if online_failed:
            status = "线上失败"
            err = online_failed[-1]["错误信息"][:100]
        else:
            status = "线上未执行"
            err = ""
        diff_records.append({
            "jira号": k, "pc分析完成时间": pc_entry["分析完成时间"],
            "触发时间": pc_entry["触发时间"],
            "线上状态": status, "线上错误信息": err,
        })
    # 保存到本地 data/online_followup/
    date_str = datetime.now().strftime("%Y-%m-%d")
    save_dir = os.path.join(PROJECT_ROOT, "data", "online_followup")
    os.makedirs(save_dir, exist_ok=True)
    result_data = {
        "date": date_str,
        "pc_success_count": len(pc_success),
        "online_success_count": len(online_success),  # 触发来源为线上且分析结果为成功的总数
        "diff_count": len(diff_records),
        "diff_records": diff_records,
        "pc_success_jiras": sorted(pc_keys),
        "online_success_jiras": sorted(online_ok_keys),
    }
    save_path = os.path.join(save_dir, f"{date_str}_diff.json")
    latest_path = os.path.join(save_dir, "latest.json")
    with open(save_path, "w", encoding="utf-8") as f:
        _json.dump(result_data, f, ensure_ascii=False, indent=2)
    with open(latest_path, "w", encoding="utf-8") as f:
        _json.dump(result_data, f, ensure_ascii=False, indent=2)
    return _ok(result_data,
               f"PC成功 {len(pc_success)} 条，线上成功 {len(online_success)} 条，差集 {len(diff_records)} 条")


@router.get("/api/test/online_followup_load", response_model=ApiResponse)
def online_followup_load(date: str = None):
    """加载已保存的线上跟进对比结果"""
    import os, re, json
    import json as _json
    save_dir = os.path.join(PROJECT_ROOT, "data", "online_followup")
    if date:
        path = os.path.join(save_dir, f"{date}_diff.json")
    else:
        path = os.path.join(save_dir, "latest.json")
    if not os.path.exists(path):
        return _ok(None, "无历史对比数据")
    with open(path, "r", encoding="utf-8") as f:
        data = _json.load(f)
    return _ok(data, f"已加载 {data.get('date', '')} 对比数据")


# ==================== 自动检测执行 ====================

# 全局停止事件，用于强制停止自动检测循环


@router.post("/api/test/auto_detect_stop", response_model=ApiResponse)
def auto_detect_stop():
    """强制停止自动检测执行"""
    import os, re, json
    import src.api.routes.shared as _shared
    _shared.auto_detect_stop = True
    return _ok(None, "已发送停止信号")


@router.post("/api/test/auto_detect_run")
async def auto_detect_run(request: Request):
    """自动检测+执行：每轮搜索JQL→过滤→抽样→调用线上AI接口→存云端"""
    import os, re, json
    import asyncio, json as _json, csv as _csv, random
    import src.api.routes.shared as _shared
    from src.services.report_ops import _upload_batch_to_cloud
    from src.services.trigger_ops import _save_trigger_time_to_cloud
    _shared.auto_detect_stop = False
    body = await request.json() or {}
    jql = str(body.get("jql") or "issuetype = bug AND created >= -10m AND status != closed").strip()
    filter_ai_init = bool(body.get("filter_ai_init", False))
    interval_min = max(1, int(body.get("interval", 6)))
    max_rounds = int(body.get("rounds", 0))  # 0=持续执行
    _batch_meta = {
        "分析并发数": str(body.get("analysis_concurrency", "5")),
        "下载并发数": str(body.get("download_concurrency", "2")),
        "模型": str(body.get("model", "deepseek-v-pro")),
        "触发来源": str(body.get("trigger_source", "线上")),
    }

    async def event_generator():
        from src.clients import jira_client, feishu_client
        from src.clients.base import http_post
        loop = asyncio.get_event_loop()
        round_num = 0
        total_executed = 0
        total_success = 0
        total_fail = 0

        while True:
            if _shared.auto_detect_stop:
                yield f"data: {_json.dumps({'type': 'stopped', 'round': round_num, 'message': '已手动停止'}, ensure_ascii=False)}\n\n"
                break
            if await request.is_disconnected():
                break
            round_num += 1
            if max_rounds > 0 and round_num > max_rounds:
                yield f"data: {_json.dumps({'type': 'done', 'round': round_num - 1, 'total_executed': total_executed, 'total_success': total_success, 'total_fail': total_fail, 'message': f'已完成 {max_rounds} 轮'}, ensure_ascii=False)}\n\n"
                break
            yield f"data: {_json.dumps({'type': 'round_start', 'round': round_num}, ensure_ascii=False)}\n\n"
            # 步骤1：JQL搜索
            try:
                issues = await loop.run_in_executor(None, lambda: jira_client.search_issues(jql, max_results=200))
                bugids = [i.get("key", "") for i in issues if "VCU" in (i.get("key") or "").upper()]
                yield f"data: {_json.dumps({'type': 'search', 'round': round_num, 'total': len(issues), 'vcu': len(bugids)}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {_json.dumps({'type': 'round_error', 'round': round_num, 'error': f'JQL搜索失败: {e}'}, ensure_ascii=False)}\n\n"
                if max_rounds <= 0:
                    await asyncio.sleep(interval_min * 60)
                continue
            if not bugids:
                yield f"data: {_json.dumps({'type': 'round_skip', 'round': round_num, 'reason': '无新增bug'}, ensure_ascii=False)}\n\n"
                if max_rounds <= 0:
                    await asyncio.sleep(interval_min * 60)
                continue
            # 步骤2：去重过滤（查询多维表格已存在的记录）
            try:
                cfg_fb = load_config().get("feishu_bitable", {})
                at, tid = cfg_fb.get("app_token", ""), cfg_fb.get("table_id", "")
                bf = cfg_fb.get("bugid_field", "jira号")
                existing = set()
                if at and tid:
                    records = await loop.run_in_executor(None, lambda: feishu_client.list_bitable_records(at, tid))
                    for rec in records:
                        fields = rec.get("fields", {})
                        jn = _bitable_text(fields.get(bf, ""))
                        if jn:
                            existing.add(jn.upper())
                bugids = [b for b in bugids if b.upper() not in existing]
                yield f"data: {_json.dumps({'type': 'filter', 'round': round_num, 'after_dedup': len(bugids)}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.warning("自动检测: 去重过滤失败: %s", e)
            if not bugids:
                yield f"data: {_json.dumps({'type': 'round_skip', 'round': round_num, 'reason': '过滤后无新增'}, ensure_ascii=False)}\n\n"
                if max_rounds <= 0:
                    await asyncio.sleep(interval_min * 60)
                continue
            # 步骤3：AI初步分析过滤（可选）
            if filter_ai_init:
                try:
                    cfg_fb = load_config().get("feishu_bitable", {})
                    at, tid = cfg_fb.get("app_token", ""), cfg_fb.get("table_id", "")
                    bf = cfg_fb.get("bugid_field", "jira号")
                    ai_init_set = set()
                    if at and tid:
                        records = await loop.run_in_executor(None, lambda: feishu_client.list_bitable_records(at, tid))
                        for rec in records:
                            fields = rec.get("fields", {})
                            jn = _bitable_text(fields.get(bf, "")).upper()
                            ar = _bitable_text(fields.get("分析结果", ""))
                            if jn and ar == "成功":
                                ai_init_set.add(jn)
                    before = len(bugids)
                    bugids = [b for b in bugids if b.upper() not in ai_init_set]
                    yield f"data: {_json.dumps({'type': 'ai_filter', 'round': round_num, 'before': before, 'after': len(bugids)}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    logger.warning("自动检测: AI初步分析过滤失败: %s", e)
            if not bugids:
                yield f"data: {_json.dumps({'type': 'round_skip', 'round': round_num, 'reason': 'AI过滤后无新增'}, ensure_ascii=False)}\n\n"
                if max_rounds <= 0:
                    await asyncio.sleep(interval_min * 60)
                continue
            # 步骤4：智能抽样（<10全执行，>10抽10个）
            if len(bugids) > 10:
                bugids = random.sample(bugids, 10)
            # 步骤5：检查gmlogger附件 + 提取触发时间
            trigger_times = {}
            no_gmlogger = 0
            for bugid in list(bugids):
                if _shared.auto_detect_stop:
                    break
                try:
                    issue = await loop.run_in_executor(None, lambda b=bugid: jira_client.fetch_issue(b))
                    attachments = (issue.get("fields") or {}).get("attachment") or []
                    has_gmlogger = any("gmlogger" in (att.get("filename", "") or "").lower() for att in attachments)
                    if not has_gmlogger:
                        bugids.remove(bugid)
                        no_gmlogger += 1
                        continue
                    from src.core.trigger_time import extract_trigger_time_from_issue
                    tt = await loop.run_in_executor(None, lambda b=bugid, iss=issue: extract_trigger_time_from_issue(b, iss))
                    if tt:
                        trigger_times[bugid] = tt
                        _save_trigger_time_to_cloud(bugid, tt, source="自动检测")
                except Exception as e:
                    logger.warning("自动检测: 处理 %s 失败: %s", bugid, e)
            yield f"data: {_json.dumps({'type': 'prepare', 'round': round_num, 'to_run': len(bugids), 'no_gmlogger': no_gmlogger, 'with_time': len(trigger_times)}, ensure_ascii=False)}\n\n"
            if not bugids:
                yield f"data: {_json.dumps({'type': 'round_skip', 'round': round_num, 'reason': '无gmlogger附件或触发时间'}, ensure_ascii=False)}\n\n"
                if max_rounds <= 0:
                    await asyncio.sleep(interval_min * 60)
                continue
            # 步骤6：调用线上AI接口
            batch_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            results = []
            batch_fail_all = False
            for bugid in bugids:
                if _shared.auto_detect_stop:
                    break
                exec_time = trigger_times.get(bugid, "")
                if not exec_time:
                    results.append({"Jira号": bugid, "执行结果": "失败", "备注": "无触发时间"})
                    continue
                try:
                    payload = _build_prod_ai_payload(bugid, exec_time)
                    resp = await loop.run_in_executor(None, lambda p=payload: http_post(_get_prod_ai_url(), p, timeout=_get_prod_ai_cfg()["timeout"]))
                    resp_code = resp.get("code") if isinstance(resp, dict) else None
                    resp_msg = str(resp.get("msg", "")) if isinstance(resp, dict) else str(resp)[:200]
                    is_ok = (resp_code == 200 or resp_code == 0 or resp_code == "200")
                    results.append({"Jira号": bugid, "执行结果": "成功" if is_ok else "失败", "备注": resp_msg[:200]})
                except Exception as e:
                    results.append({"Jira号": bugid, "执行结果": "失败", "备注": str(e)[:200]})
                    # 检查是否整批失败（接口完全不可用）
                    if len(results) >= 3 and all(r["执行结果"] == "失败" for r in results):
                        batch_fail_all = True
                        break
                yield f"data: {_json.dumps({'type': 'progress', 'round': round_num, 'index': len(results), 'total': len(bugids), 'bugid': bugid, 'status': results[-1]['执行结果']}, ensure_ascii=False)}\n\n"
            # 步骤7：保存结果到云端
            success_count = sum(1 for r in results if r["执行结果"] == "成功")
            fail_count = len(results) - success_count
            total_executed += len(results)
            total_success += success_count
            total_fail += fail_count
            date_str = datetime.now().strftime("%Y-%m-%d")
            time_str = datetime.now().strftime("%H%M%S")
            os.makedirs(_UNANALYZED_DIR, exist_ok=True)
            batch_csv = os.path.join(_UNANALYZED_DIR, f"auto_add_{date_str}_{time_str}.csv")
            try:
                with open(batch_csv, "w", newline="", encoding="utf-8-sig") as f:
                    writer = _csv.writer(f)
                    writer.writerow(["Jira号", "执行结果", "触发时间", "执行时间", "备注",
                                     "分析并发数", "下载并发数", "模型", "触发来源"])
                    for r in results:
                        writer.writerow([r["Jira号"], r["执行结果"], trigger_times.get(r["Jira号"], ""),
                                         batch_start, r.get("备注", ""),
                                         _batch_meta["分析并发数"], _batch_meta["下载并发数"],
                                         _batch_meta["模型"], _batch_meta["触发来源"]])
                doc_title = f"auto_add {date_str} {time_str} ({success_count}/{len(results)})"
                cloud_url = _upload_batch_to_cloud(batch_csv, doc_title)
            except Exception as e:
                cloud_url = ""
                logger.warning("自动检测: 保存云端失败: %s", e)
            yield f"data: {_json.dumps({'type': 'round_done', 'round': round_num, 'total': len(results), 'success': success_count, 'fail': fail_count, 'cloud_url': cloud_url}, ensure_ascii=False)}\n\n"
            # 整批失败时自动停止
            if batch_fail_all:
                yield f"data: {_json.dumps({'type': 'auto_stopped', 'round': round_num, 'reason': '接口连续失败，自动停止'}, ensure_ascii=False)}\n\n"
                break
            # 等待下一轮
            if max_rounds <= 0 or round_num < max_rounds:
                yield f"data: {_json.dumps({'type': 'waiting', 'round': round_num, 'interval': interval_min}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(interval_min * 60)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ==================== 回归执行 ====================


@router.post("/api/test/regression_batches")
async def regression_batches(request: Request):
    """按时间获取云端批次列表（按日期逐天加载，避免超时），统计每批次的失败 Jira 数量"""
    import asyncio
    import json as _json
    body = await request.json() or {}
    after_time = str(body.get("after_time", "") or "").strip()
    cutoff_date = after_time[:10] if after_time else ""

    async def event_generator():
        from src.services.report_ops import _scan_all_batch_records, _read_csv_rows, _parse_markdown_batch_table
        from src.clients import feishu_client
        loop = asyncio.get_event_loop()
        cfg = load_config().get("feishu_bitable", {})
        app_token = cfg.get("app_token", "")
        table_id = cfg.get("table_id", "")
        bugid_field = cfg.get("bugid_field", "jira号")
        folder_token = cfg.get("batch_folder_token", "")
        _jira_col = bugid_field

        # 步骤1：加载本地批次（快速）
        yield f"data: {_json.dumps({'type': 'progress', 'message': '正在扫描本地批次...'}, ensure_ascii=False)}\n\n"
        local_batches = []
        try:
            doc_dir = get_path("doc_dir")
            # 本地 docs/日期/batch_*.csv
            if os.path.isdir(doc_dir):
                for date_folder in sorted(os.listdir(doc_dir), reverse=True):
                    if cutoff_date and date_folder < cutoff_date:
                        continue
                    day_dir = os.path.join(doc_dir, date_folder)
                    if not os.path.isdir(day_dir):
                        continue
                    for fname in sorted(os.listdir(day_dir)):
                        if not fname.lower().startswith("batch_") or not fname.endswith(".csv"):
                            continue
                        path = os.path.join(day_dir, fname)
                        rows = _read_csv_rows(path)
                        if not rows:
                            continue
                        jira_list = [r.get(_jira_col, "").strip() or r.get("jira号", "").strip() for r in rows if (r.get(_jira_col, "") or r.get("jira号", "")).strip()]
                        success = sum(1 for r in rows if (r.get("执行结果") or "").strip() == "成功")
                        source = next((r.get("触发来源", "").strip() for r in rows if r.get("触发来源")), "")
                        local_batches.append({
                            "batch_id": f"{date_folder}/{fname.replace('.csv', '')}",
                            "date": date_folder, "name": fname.replace(".csv", ""),
                            "source": source, "total": len(rows),
                            "success": success, "fail": len(rows) - success,
                            "jira_list": jira_list,
                        })
        except Exception as e:
            logger.warning("扫描本地批次失败: %s", e)

        # 步骤2：获取云端文件列表（快速）
        yield f"data: {_json.dumps({'type': 'progress', 'message': '正在获取云端文件列表...'}, ensure_ascii=False)}\n\n"
        cloud_files_by_date = {}  # {date: [file_info, ...]}
        try:
            if folder_token:
                all_files = await loop.run_in_executor(None, lambda: feishu_client.list_folder_files(folder_token, recursive=True))
                seen_ids = {b["batch_id"] for b in local_batches}
                for f in all_files:
                    if f.get("type") != "docx":
                        continue
                    fname = f.get("name", "")
                    f_folder = f.get("folder", "")
                    if cutoff_date and f_folder and f_folder < cutoff_date:
                        continue
                    doc_token = f.get("token", "")
                    if not doc_token or not fname.startswith(("批量执行", "线上批量执行")):
                        continue
                    bid = f"cloud/{f_folder}/{fname}"
                    if bid in seen_ids:
                        continue
                    cloud_files_by_date.setdefault(f_folder, []).append({"fname": fname, "doc_token": doc_token, "batch_id": bid, "folder": f_folder})
        except Exception as e:
            logger.warning("获取云端文件列表失败: %s", e)

        # 步骤3：加载多维表格记录（一次性）
        yield f"data: {_json.dumps({'type': 'progress', 'message': '正在加载多维表格记录...'}, ensure_ascii=False)}\n\n"
        bt_result_map = {}
        if app_token and table_id:
            try:
                records = await loop.run_in_executor(None, lambda: feishu_client.list_bitable_records(app_token, table_id))
                for rec in records:
                    fields = rec.get("fields", {})
                    jn = _bitable_text(fields.get(bugid_field, ""))
                    if jn:
                        result_status = _bitable_text(fields.get("分析结果", ""))
                        bt_result_map.setdefault(jn, []).append(result_status)
            except Exception as e:
                logger.warning("regression_batches: 多维表格查询失败: %s", e)

        # 步骤4：逐天获取云端批次文档
        dates_sorted = sorted(cloud_files_by_date.keys(), reverse=True)
        total_dates = len(dates_sorted)
        cloud_batches = []
        for idx, date_str in enumerate(dates_sorted):
            if await request.is_disconnected():
                return
            files = cloud_files_by_date[date_str]
            yield f"data: {_json.dumps({'type': 'progress', 'message': f'正在加载 {date_str} 的批次文档... ({idx+1}/{total_dates})'}, ensure_ascii=False)}\n\n"
            for fi in files:
                try:
                    md = await loop.run_in_executor(None, lambda t=fi['doc_token']: feishu_client.fetch_docx_as_markdown(t))
                    batch_rows = _parse_markdown_batch_table(md)
                    if not batch_rows:
                        continue
                    jira_list = []
                    success = 0
                    source = ""
                    for r in batch_rows:
                        jira_no = (r.get(_jira_col) or r.get("jira号") or r.get("Jira号") or "").strip()
                        if jira_no:
                            jira_list.append(jira_no)
                        if (r.get("执行结果") or "").strip() == "成功":
                            success += 1
                        src = (r.get("触发来源") or "").strip()
                        if src:
                            source = src
                    if not source:
                        if fi["fname"].startswith("线上批量执行"):
                            source = "parseFullTicket"
                        elif fi["fname"].startswith("批量执行") and "_bot_online_" in fi["fname"]:
                            source = "parseFullTicket"
                        elif fi["fname"].startswith("批量执行"):
                            source = "jira_analyze"
                    cloud_batches.append({
                        "batch_id": fi["batch_id"], "date": fi["folder"],
                        "name": fi["fname"], "source": source,
                        "total": len(batch_rows), "success": success,
                        "fail": len(batch_rows) - success, "jira_list": jira_list,
                    })
                except Exception as e:
                    logger.warning("读取云端批次 %s 失败: %s", fi["fname"], e)

        # 步骤5：合并所有批次，统计失败 Jira
        all_batches = local_batches + cloud_batches
        all_batches.sort(key=lambda x: x.get("date", ""), reverse=True)
        result_batches = []
        for b in all_batches:
            jira_list = b.get("jira_list", [])
            failed_jiras = []
            for jn in jira_list:
                results = bt_result_map.get(jn, [])
                if "失败" in results and "成功" not in results:
                    failed_jiras.append(jn)
                elif not results:
                    failed_jiras.append(jn)
            if not failed_jiras:
                continue
            source = b.get("source", "")
            source_label = "线上" if source == "parseFullTicket" else ("PC" if source == "jira_analyze" else source)
            result_batches.append({
                "batch_id": b.get("batch_id", ""),
                "date": b.get("date", ""),
                "name": b.get("name", ""),
                "source": source_label,
                "total": b.get("total", 0),
                "fail_count": len(failed_jiras),
                "failed_jiras": failed_jiras,
            })
        yield f"data: {_json.dumps({'type': 'done', 'batches': result_batches, 'count': len(result_batches), 'message': f'共 {len(result_batches)} 个批次含失败记录'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/test/regression_stop", response_model=ApiResponse)
def regression_stop():
    """停止回归执行"""
    from src.api.routes.shared import regression_stop_event
    regression_stop_event.set()
    return _ok(None, "已发送停止信号")


@router.post("/api/test/regression_run")
async def regression_run(request: Request):
    """回归执行：从错误统计中筛选有成功记录的Jira号，抽样后调用AI接口，支持PC/线上模式和多轮执行"""
    import os, re, json
    import asyncio, json as _json, csv as _csv, random
    from src.services.report_ops import _upload_batch_to_cloud
    from src.services.trigger_ops import _load_trigger_times_from_cloud
    body = await request.json() or {}
    after_time = str(body.get("after_time", "")).strip()
    sample_count = max(1, int(body.get("sample_count", 10)))
    exec_mode = str(body.get("exec_mode", "pc")).strip()
    interval_min = max(0, int(body.get("interval_min", 0)))
    total_rounds = max(1, int(body.get("total_rounds", 1)))
    input_bugids = body.get("bugids") or []  # 前端传入的已勾选批次 Jira 号
    _batch_meta = {
        "分析并发数": str(body.get("analysis_concurrency", "5")),
        "下载并发数": str(body.get("download_concurrency", "2")),
        "模型": str(body.get("model", "deepseek-v-pro")),
        "触发来源": str(body.get("trigger_source", "线上" if exec_mode == "online" else "PC")),
    }

    async def event_generator():
        from src.clients import feishu_client, jira_client
        from src.clients.base import http_post
        from src.api.routes.shared import regression_stop_event as _stop_event
        _stop_event.clear()  # 新执行开始时清除停止标志
        loop = asyncio.get_event_loop()
        # 读取配置中的 Jira 号字段名
        cfg = load_config().get("feishu_bitable", {})
        jira_col = cfg.get("bugid_field", "jira号")
        # 步骤1：获取候选 Jira 号（优先使用前端传入的 bugids）
        if input_bugids:
            candidates = list(dict.fromkeys(input_bugids))  # 去重且保序
            yield f"data: {_json.dumps({'type': 'search', 'total': len(candidates)}, ensure_ascii=False)}\n\n"
        else:
            try:
                at, tid = cfg.get("app_token", ""), cfg.get("table_id", "")
                bf = cfg.get("bugid_field", "jira号")
                if not at or not tid:
                    yield f"data: {_json.dumps({'type': 'error', 'message': '多维表格未配置'}, ensure_ascii=False)}\n\n"
                    return
                records = await loop.run_in_executor(None, lambda: feishu_client.list_bitable_records(at, tid))
                cutoff = _ts_parse_datetime(after_time) if after_time else None
                stats = {}
                for rec in records:
                    fields = rec.get("fields", {})
                    jn = _bitable_text(fields.get(bf, ""))
                    if not jn:
                        continue
                    # 按分析完成时间过滤
                    if cutoff:
                        done_time = _bitable_text(fields.get("分析完成时间", ""))
                        done_dt = _ts_parse_datetime(done_time) if done_time else None
                        if not done_dt or done_dt <= cutoff:
                            continue
                    result_status = _bitable_text(fields.get("分析结果", ""))
                    entry = stats.setdefault(jn, {"has_success": False, "fail_count": 0})
                    if result_status == "成功":
                        entry["has_success"] = True
                    elif result_status == "失败":
                        entry["fail_count"] += 1
                candidates = [jn for jn, e in stats.items() if e["has_success"]]
                yield f"data: {_json.dumps({'type': 'search', 'total': len(candidates)}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {_json.dumps({'type': 'error', 'message': f'查询失败: {e}'}, ensure_ascii=False)}\n\n"
                return
        if not candidates:
            yield f"data: {_json.dumps({'type': 'done', 'total': 0, 'success': 0, 'fail': 0, 'message': '无候选 Jira 号'}, ensure_ascii=False)}\n\n"
            return
        # 步骤2：加载触发时间
        trigger_times = {}
        cloud_times = await loop.run_in_executor(None, _load_trigger_times_from_cloud)
        for bugid in candidates:
            tt = cloud_times.get(bugid, "")
            if tt:
                trigger_times[bugid] = tt
        # 加载PC配置（如需要）
        pc_cfg = None
        if exec_mode != "online":
            pc_cfg = load_config().get("ai_log_api", {})
        # 多轮执行
        all_results = []
        total_success = 0
        total_fail = 0
        for round_num in range(1, total_rounds + 1):
            if _stop_event.is_set():
                break
            if total_rounds > 1:
                yield f"data: {_json.dumps({'type': 'round', 'round': round_num, 'total_rounds': total_rounds}, ensure_ascii=False)}\n\n"
            # 每轮独立抽样
            if len(candidates) > sample_count:
                round_candidates = random.sample(candidates, sample_count)
            else:
                round_candidates = list(candidates)
            yield f"data: {_json.dumps({'type': 'sample', 'total': len(round_candidates), 'round': round_num}, ensure_ascii=False)}\n\n"
            batch_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            results = []
            for bugid in round_candidates:
                if _stop_event.is_set():
                    yield f"data: {_json.dumps({'type': 'stopped', 'total': len(all_results), 'success': total_success, 'fail': total_fail, 'round': round_num, 'message': '用户手动停止'}, ensure_ascii=False)}\n\n"
                    return
                exec_time = trigger_times.get(bugid, "")
                if not exec_time:
                    results.append({jira_col: bugid, "执行结果": "失败", "备注": "无触发时间"})
                    continue
                try:
                    if exec_mode == "online":
                        payload = _build_prod_ai_payload(bugid, exec_time)
                        resp = await loop.run_in_executor(None, lambda p=payload: http_post(_get_prod_ai_url(), p, timeout=_get_prod_ai_cfg()["timeout"]))
                    else:
                        payload = {pc_cfg.get("bugid_field", "jira号"): bugid}
                        if pc_cfg.get("trigger_time_field"):
                            payload[pc_cfg["trigger_time_field"]] = exec_time
                        resp = await loop.run_in_executor(None, lambda p=payload: http_post(pc_cfg.get("url", ""), p, timeout=int(pc_cfg.get("timeout", 60))))
                    resp_code = resp.get("code") if isinstance(resp, dict) else None
                    resp_msg = str(resp.get("msg", "")) if isinstance(resp, dict) else str(resp)[:200]
                    is_ok = (resp_code == 200 or resp_code == 0 or resp_code == "200")
                    results.append({jira_col: bugid, "执行结果": "成功" if is_ok else "失败", "备注": resp_msg[:200]})
                except Exception as e:
                    results.append({jira_col: bugid, "执行结果": "失败", "备注": str(e)[:200]})
                yield f"data: {_json.dumps({'type': 'progress', 'index': len(results), 'total': len(round_candidates), 'bugid': bugid, 'status': results[-1]['执行结果'], 'round': round_num, 'total_rounds': total_rounds}, ensure_ascii=False)}\n\n"
            round_success = sum(1 for r in results if r["执行结果"] == "成功")
            round_fail = len(results) - round_success
            total_success += round_success
            total_fail += round_fail
            all_results.extend(results)
            # 轮次间隔
            if round_num < total_rounds and interval_min > 0:
                yield f"data: {_json.dumps({'type': 'waiting', 'interval_min': interval_min, 'round': round_num}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(interval_min * 60)
        # 步骤4：保存
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        mode_label = "线上" if exec_mode == "online" else "PC"
        os.makedirs(_UNANALYZED_DIR, exist_ok=True)
        batch_csv = os.path.join(_UNANALYZED_DIR, f"regression_{date_str}_{time_str}.csv")
        try:
            with open(batch_csv, "w", newline="", encoding="utf-8-sig") as f:
                writer = _csv.writer(f)
                writer.writerow([jira_col, "执行结果", "触发时间", "执行时间", "备注",
                                 "分析并发数", "下载并发数", "模型", "触发来源", "执行模式"])
                for r in all_results:
                    writer.writerow([r[jira_col], r["执行结果"], trigger_times.get(r[jira_col], ""),
                                     datetime.now().strftime("%Y-%m-%d %H:%M:%S"), r.get("备注", ""),
                                     _batch_meta["分析并发数"], _batch_meta["下载并发数"],
                                     _batch_meta["模型"], _batch_meta["触发来源"], mode_label])
            doc_title = f"回归执行 {mode_label} {date_str} {time_str} ({total_success}/{len(all_results)}, {total_rounds}轮)"
            cloud_url = _upload_batch_to_cloud(batch_csv, doc_title)
        except Exception as e:
            cloud_url = ""
            logger.warning("回归执行: 保存失败: %s", e)
        yield f"data: {_json.dumps({'type': 'done', 'total': len(all_results), 'success': total_success, 'fail': total_fail, 'rounds': total_rounds, 'cloud_url': cloud_url}, ensure_ascii=False)}\n\n"

    # 注册作业：/api/jobs 可查进度，/api/jobs/{id}/stop 可单独停止本作业
    from src.core.job_registry import JOBS as _JOBS
    from src.api.routes.jobs import job_stream as _job_stream
    from src.api.routes.shared import regression_stop_event as _reg_stop
    _job = _JOBS.create("regression", f"回归执行（样本 {sample_count}，{total_rounds} 轮）")
    return StreamingResponse(_job_stream(_job, event_generator, _reg_stop), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ==================== AB实验 ====================


@router.post("/api/test/ab_experiment")
async def ab_experiment(request: Request):
    """AB实验：对A/B两组配置使用相同输入进行对比验证"""
    import os, re, json
    import asyncio, json as _json, random
    body = await request.json() or {}
    input_raw = str(body.get("input", "")).strip()
    exp_a = body.get("exp_a") or {}
    exp_b = body.get("exp_b") or {}
    sample_count = int(body.get("sample_count", 0))  # 0=不抽样，全量执行
    if not input_raw:
        return _fail("请输入 Jira 号或 JQL")

    async def event_generator():
        from src.clients import jira_client
        from src.clients.base import http_post
        loop = asyncio.get_event_loop()
        # 步骤1：解析输入——JQL搜索或直接Jira号
        if input_raw.startswith("issuetype") or "ORDER BY" in input_raw.upper() or "~" in input_raw or " AND " in input_raw.upper():
            try:
                issues = await loop.run_in_executor(None, lambda: jira_client.search_issues(input_raw, max_results=500))
                all_bugids = [i.get("key", "") for i in issues if "VCU" in (i.get("key") or "").upper()]
                yield f"data: {_json.dumps({'type': 'search', 'total': len(issues), 'vcu': len(all_bugids)}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {_json.dumps({'type': 'error', 'message': f'JQL搜索失败: {e}'}, ensure_ascii=False)}\n\n"
                return
        else:
            all_bugids = [b.strip() for b in input_raw.replace("，", ",").replace(";", ",").split(",") if b.strip()]
            yield f"data: {_json.dumps({'type': 'search', 'total': len(all_bugids), 'vcu': len(all_bugids)}, ensure_ascii=False)}\n\n"
        if not all_bugids:
            yield f"data: {_json.dumps({'type': 'error', 'message': '无有效Jira号'}, ensure_ascii=False)}\n\n"
            return
        # 步骤2：统一抽样——同一份结果分给A和B
        if sample_count > 0 and len(all_bugids) > sample_count:
            bugids = random.sample(all_bugids, sample_count)
            yield f"data: {_json.dumps({'type': 'sample', 'before': len(all_bugids), 'after': len(bugids)}, ensure_ascii=False)}\n\n"
        else:
            bugids = list(all_bugids)
            yield f"data: {_json.dumps({'type': 'sample', 'before': len(all_bugids), 'after': len(bugids)}, ensure_ascii=False)}\n\n"
        # 步骤3：对A和B分别用相同bugids执行
        async def _run_exp(exp_cfg, label):
            module = exp_cfg.get("module", "prod_batch")
            results = []
            start_time = datetime.now()
            for bugid in bugids:
                if await request.is_disconnected():
                    break
                try:
                    if module == "prod_batch":
                        payload = _build_prod_ai_payload(bugid)
                        resp = await loop.run_in_executor(None, lambda p=payload: http_post(_get_prod_ai_url(), p, timeout=_get_prod_ai_cfg()["timeout"]))
                        resp_code = resp.get("code") if isinstance(resp, dict) else None
                        is_ok = (resp_code == 200 or resp_code == 0 or resp_code == "200")
                        results.append({"bugid": bugid, "success": is_ok})
                    elif module == "batch_ai":
                        cfg_ai = load_config().get("ai_log_api", {})
                        payload = {cfg_ai.get("bugid_field", "bugid"): bugid}
                        resp = await loop.run_in_executor(None, lambda p=payload, u=cfg_ai.get("url", ""): http_post(u, p, timeout=30))
                        resp_code = resp.get("code") if isinstance(resp, dict) else None
                        is_ok = (resp_code == 200 or resp_code == 0 or resp_code == "200")
                        results.append({"bugid": bugid, "success": is_ok})
                    else:
                        results.append({"bugid": bugid, "success": True})
                except Exception:
                    results.append({"bugid": bugid, "success": False})
                yield f"data: {_json.dumps({'type': f'progress_{label}', 'done': len(results), 'total': len(bugids), 'success': sum(1 for r in results if r['success']), 'fail': sum(1 for r in results if not r['success']), 'bugid': bugid, 'status': '成功' if results[-1]['success'] else '失败'}, ensure_ascii=False)}\n\n"
            elapsed = (datetime.now() - start_time).total_seconds()
            success = sum(1 for r in results if r["success"])
            fail = len(results) - success
            rate = f"{success / len(results) * 100:.1f}%" if results else "0%"
            avg_time = f"{elapsed / len(results):.1f}s" if results else "-"
            yield f"data: {_json.dumps({'type': f'result_{label}', 'total': len(results), 'success': success, 'fail': fail, 'rate': rate, 'avg_time': avg_time, 'elapsed': round(elapsed, 1)}, ensure_ascii=False)}\n\n"
        # 顺序执行A和B，用同一份bugids
        async for chunk in _run_exp(exp_a, "a"):
            yield chunk
        async for chunk in _run_exp(exp_b, "b"):
            yield chunk
        yield f"data: {_json.dumps({'type': 'done', 'message': f'AB实验完成，共用 {len(bugids)} 条数据'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ==================== 冒烟测试：多维表格查询 ====================


@router.post("/api/test/smoke_test_query", response_model=ApiResponse)
async def smoke_test_query(request: Request):
    """冒烟测试：查询指定 Jira 号在多维表格中 exec_time 之后最接近的分析记录"""
    import os, re, json
    body = await request.json() or {}
    jira_ids = [b.strip().upper() for b in (body.get("jira_ids") or []) if b.strip()]
    if not jira_ids:
        return _fail("请输入 Jira 号")
    exec_time = (body.get("exec_time") or "").strip()  # 执行时间，过滤分析完成时间 >= 此时间的记录
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = await _run_blocking(feishu_client.list_bitable_records, app_token, table_id)
    except Exception as e:
        logger.error("冒烟测试查询：多维表格查询失败: %s", e)
        return _fail(f"多维表格查询失败: {e}")
    target_set = set(jira_ids)
    picked = {}  # jira号 -> exec_time 之后最接近的记录
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(bugid_field, ""))
        if not jira_no or jira_no not in target_set:
            continue
        done_time = _bitable_text(fields.get("分析完成时间", ""))
        # 有执行时间时，仅保留分析完成时间 >= 执行时间的记录
        if exec_time and done_time and done_time < exec_time:
            continue
        prev = picked.get(jira_no)
        if prev is None or done_time < prev.get("分析完成时间", ""):
            # 取 exec_time 之后最早的一条（最接近执行时间的）
            row = _flatten_bitable_record(fields, report_field)
            row["jira号"] = jira_no
            picked[jira_no] = row
    rows = sorted(picked.values(), key=lambda r: r.get("分析完成时间", ""))
    return _ok({"rows": rows, "count": len(rows)},
               f"查询到 {len(rows)} 条记录（共 {len(jira_ids)} 个 Jira 号）")


@router.post("/api/test/smoke_test_save_record", response_model=ApiResponse)
async def smoke_test_save_record(request: Request):
    """冒烟测试：生成执行记录文档，保存本地并上传云端"""
    import os, re, json
    body = await request.json() or {}
    version = (body.get("version") or "-").strip() or "-"
    exec_time = (body.get("exec_time") or "").strip()
    results = body.get("results") or []  # [{case_name, jira_id, bitable_record}]
    exec_mode = (body.get("exec_mode") or "online").strip()
    # 从配置文件读取接口参数，根据执行模式选择对应配置段
    cfg = load_config()
    params = cfg.get("params", {})
    # 优先使用前端传入的版本号，否则从配置读取
    tool_version = (body.get("tool_version") or "").strip() or str(params.get("version", "-"))
    logagent_version = (body.get("logagent_version") or "").strip() or str(params.get("logagent_version", "-"))
    if exec_mode == "pc":
        pc_cfg = cfg.get("pc", {})
        params = {**params, **pc_cfg}  # pc 覆盖 params 中的同名字段
        trigger_source = "PC"
    else:
        trigger_source = params.get("trigger_source", "线上")
    basic_fields = {
        "analysis_concurrency": str(params.get("analysis_concurrency", 5)),
        "download_concurrency": str(params.get("download_concurrency", 2)),
        "model": params.get("model", "deepseek-v-pro"),
        "trigger_source": trigger_source,
    }
    if not exec_time:
        return _fail("缺少执行时间")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y-%m-%d")
    # 构建 Markdown 内容
    lines = [
        f"# 冒烟测试执行记录 - {date_str}", "",
        f"## 基本信息", "",
        f"- **版本号**：{version}",
        f"- **测试工具版本**：{tool_version}",
        f"- **LogAgent版本**：{logagent_version}",
        f"- **执行时间**：{exec_time}",
        f"- **记录生成时间**：{now_str}", "",
        f"## 接口配置", "",
        f"- 分析并发数：{basic_fields.get('analysis_concurrency', '-')}",
        f"- 下载并发数：{basic_fields.get('download_concurrency', '-')}",
        f"- 模型：{basic_fields.get('model', '-')}",
        f"- 触发来源：{basic_fields.get('trigger_source', '-')}", "",
        f"## 用例配置", "",
    ]
    for r in results:
        lines.append(f"- {r.get('case_name', '?')}：{r.get('jira_id', '-')}")
    lines.append("")
    lines.append("## 执行结果")
    lines.append("")
    lines.append("| 用例 | Jira号 | 是否成功 | 分析耗时 | 总耗时 | 错误原因 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for r in results:
        rec = r.get("bitable_record") or {}
        case_name = r.get("case_name", "?")
        jira_id = r.get("jira_id", "-")
        result_status = rec.get("分析结果", "-") or "-"
        is_success = "是" if result_status == "成功" else "否"
        # 分析耗时：优先使用多维表格自带字段，兜底用时间戳计算
        analysis_dur = rec.get("分析耗时", "") or ""
        if not analysis_dur or analysis_dur == "-":
            analysis_dur = _calc_smoke_duration(rec.get("分析问题时间", ""), rec.get("分析完成时间", ""))
        # 总耗时：同上
        total_dur = rec.get("总耗时", "") or analysis_dur
        if not total_dur or total_dur == "-":
            total_dur = analysis_dur
        # 错误原因
        error_reason = ""
        if result_status != "成功":
            error_reason = rec.get("错误信息", "") or rec.get("rootcause", "") or "-"
        else:
            error_reason = "-"
        lines.append(f"| {case_name} | {jira_id} | {is_success} | {analysis_dur} | {total_dur} | {error_reason} |")
    md_content = "\n".join(lines)
    # 本地保存
    local_dir = os.path.join(PROJECT_ROOT, "data", "smoke_test")
    os.makedirs(local_dir, exist_ok=True)
    time_suffix = datetime.now().strftime("%H%M%S")
    local_path = os.path.join(local_dir, f"冒烟测试_{date_str}_{time_suffix}.md")
    try:
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(md_content)
    except Exception as e:
        logger.warning("冒烟测试记录本地保存失败: %s", e)
        local_path = ""
    # 云端上传
    cloud_url = ""
    try:
        from src.clients import feishu_client
        cfg = load_config().get("feishu_bitable", {})
        folder_token = cfg.get("smoke_test_folder", "") or cfg.get("drive_folder", "")
        doc_title = f"冒烟测试_{date_str}_{time_suffix}"
        result = await _run_blocking(feishu_client.create_docx_document, doc_title, md_content, folder_token)
        cloud_url = result.get("url", "")
    except Exception as e:
        logger.warning("冒烟测试记录云端上传失败: %s", e)
    return _ok({"local_path": local_path, "cloud_url": cloud_url}, "冒烟测试记录已保存")


@router.post("/api/test/error_stats", response_model=ApiResponse)
async def error_stats_query(request: Request):
    """错误统计：查询多维表格中分析失败的 Jira 号，聚合失败次数/最新人工审核原因/是否有成功记录"""
    import os, re, json
    body = await request.json() or {}
    after_time = str(body.get("after_time", "")).strip()
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        # 60 秒内复用上次全表结果，避免连续点击“按时间查询/全量查询”重复拉整张多维表格
        with _ERROR_STATS_LOCK:
            _cached_records, _cached_ts = _ERROR_STATS_CACHE["records"], _ERROR_STATS_CACHE["ts"]
        if _cached_records is not None and _time_mod.time() - _cached_ts < _ERROR_STATS_TTL:
            records = _cached_records
            logger.info("错误统计命中缓存（%d 条，%.0fs 前拉取）",
                        len(records), _time_mod.time() - _cached_ts)
        else:
            records = await _run_blocking(feishu_client.list_bitable_records, app_token, table_id)
            with _ERROR_STATS_LOCK:
                _ERROR_STATS_CACHE["records"] = records
                _ERROR_STATS_CACHE["ts"] = _time_mod.time()
    except Exception as e:
        logger.error("错误统计查询：多维表格查询失败: %s", e)
        return _fail(f"多维表格查询失败: {e}")
    cutoff = _ts_parse_datetime(after_time) if after_time else None
    # 按 Jira 号聚合
    stats = {}  # jira号 -> entry
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(bugid_field, ""))
        if not jira_no:
            continue
        result_status = _bitable_text(fields.get("分析结果", ""))
        done_time = _bitable_text(fields.get("分析完成时间", ""))
        # 时间过滤
        if cutoff and done_time:
            done_dt = _ts_parse_datetime(done_time)
            if not done_dt or done_dt <= cutoff:
                continue
        entry = stats.setdefault(jira_no, {
            "jira号": jira_no, "失败次数": 0,
            "最新人工审核原因": "", "有成功记录": False,
            "最新失败时间": "", "_review_done": "", "_review_result": "",
        })
        if result_status == "成功":
            entry["有成功记录"] = True
        elif result_status == "失败":
            entry["失败次数"] += 1
            if done_time > entry["最新失败时间"]:
                entry["最新失败时间"] = done_time
        # 跟踪有人工审核结果的最新记录
        review = _bitable_text(fields.get("人工审核结果", ""))
        if review and done_time > entry["_review_done"]:
            entry["_review_done"] = done_time
            entry["_review_result"] = result_status
            entry["最新人工审核原因"] = review
    # 过滤：有人工审核结果 且 该条记录分析结果为失败
    rows = [v for v in stats.values()
            if v["_review_result"] == "失败" and v["最新人工审核原因"]]
    rows.sort(key=lambda r: -r["失败次数"])
    # 并发从 Jira 获取每个 Jira 号附件中的 gmlogger 文件名
    import asyncio
    from src.clients import jira_client as _jc
    loop = asyncio.get_event_loop()
    async def _fetch_gmlogger(jira_id):
        try:
            issue = await asyncio.wait_for(
                loop.run_in_executor(None, _jc.fetch_issue, jira_id), timeout=15)
            atts = ((issue.get("fields") or {}).get("attachment") or [])
            names = [a.get("filename", "") for a in atts
                     if a.get("filename", "") and "gmlogger" in a.get("filename", "").lower()]
            return ", ".join(names) if names else ""
        except Exception:
            return ""
    jira_ids = list({r["jira号"] for r in rows})
    if jira_ids:
        results = await asyncio.gather(*[_fetch_gmlogger(j) for j in jira_ids])
        gm_map = dict(zip(jira_ids, results))
        for r in rows:
            r["gmlogger文件"] = gm_map.get(r["jira号"], "")
    # 清理内部字段
    for r in rows:
        r.pop("_review_done", None)
        r.pop("_review_result", None)
    return _ok({"rows": rows, "count": len(rows)},
               f"统计到 {len(rows)} 个 Jira 号存在失败记录")


@router.post("/api/test/delete_dirty_data", response_model=ApiResponse)
async def delete_dirty_data(request: Request):
    """批量删除脏数据：删除指定 Jira 号的所有失败记录
    
    用于清理有分析成功记录的 Jira 号下的失败行。
    """
    import os, re, json
    body = await request.json() or {}
    jira_ids = body.get("jira_ids", [])
    if not jira_ids:
        return _fail("未提供要删除的 Jira 号列表")
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = await _run_blocking(feishu_client.list_bitable_records, app_token, table_id)
    except Exception as e:
        logger.error("删除脏数据：多维表格查询失败: %s", e)
        return _fail(f"多维表格查询失败: {e}")
    # 筛选要删除的记录：匹配 Jira 号且分析结果为“失败”
    jira_id_set = set(jira_ids)
    record_ids_to_delete = []
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(bugid_field, ""))
        result_status = _bitable_text(fields.get("分析结果", ""))
        if jira_no in jira_id_set and result_status == "失败":
            record_ids_to_delete.append(rec.get("record_id"))
    if not record_ids_to_delete:
        return _ok({"deleted_count": 0}, "无符合条件的失败记录")
    try:
        await _run_blocking(feishu_client.batch_delete_records, app_token, table_id, record_ids_to_delete)
        logger.info("批量删除脏数据成功: Jira 号 %d 个，删除记录 %d 条", len(jira_ids), len(record_ids_to_delete))
        return _ok({"deleted_count": len(record_ids_to_delete)}, 
                   f"已删除 {len(record_ids_to_delete)} 条失败记录")
    except Exception as e:
        logger.error("批量删除脏数据失败: %s", e)
        return _fail(f"删除失败: {e}")


@router.post("/api/test/write_trigger_time", response_model=ApiResponse)
async def write_trigger_time_batch(request: Request):
    """批量写入触发时间到云端：直接写入已确定的时间，不涉及重新提取

    :param trigger_times: {jira号: 触发时间}
    :param skip_cloud_cache: 为 True 时先对比云端缓存，已有的跳过，仅写入缺失的；为 False 时强制覆盖写入
    """
    import os, re, json
    from src.services.trigger_ops import (
        _batch_save_trigger_times_to_cloud,
        _load_cloud_trigger_cache,
    )
    body = await request.json() or {}
    trigger_times = body.get("trigger_times") or {}
    skip_cloud_cache = body.get("skip_cloud_cache", False)
    if not trigger_times:
        return _fail("未提供触发时间数据")
    # 分类：跳过已有 / 待写入
    skipped_count = 0
    to_write = {}  # {bugid: trigger_time}
    results = []
    if skip_cloud_cache:
        # 勾选“跳过云端缓存”：先对比云端，已有的跳过，仅写入缺失的
        cloud_times = {}
        try:
            cloud_times, _ = await asyncio.get_event_loop().run_in_executor(None, _load_cloud_trigger_cache)
        except Exception as e:
            logger.warning("加载云端触发时间缓存失败: %s", e)
        for bugid, tt in trigger_times.items():
            if not tt:
                continue
            if bugid in cloud_times and cloud_times[bugid]:
                skipped_count += 1
                results.append({"jira号": bugid, "触发时间": cloud_times[bugid], "结果": "云端已有，跳过"})
            else:
                to_write[bugid] = tt
    else:
        # 不勾选：不检查云端，全部强制覆盖写入
        for bugid, tt in trigger_times.items():
            if tt:
                to_write[bugid] = tt
    # 一次性批量写入云端，避免逐条加载表数据
    written_count = 0
    failed_count = 0
    if to_write:
        try:
            ok = _batch_save_trigger_times_to_cloud(
                to_write, {k: "批量应用(人工)" for k in to_write})
            if ok:
                written_count = len(to_write)
                for bugid, tt in to_write.items():
                    results.append({"jira号": bugid, "触发时间": tt, "结果": "写入成功"})
            else:
                failed_count = len(to_write)
                for bugid, tt in to_write.items():
                    results.append({"jira号": bugid, "触发时间": tt, "结果": "批量写入失败"})
        except Exception as e:
            failed_count = len(to_write)
            for bugid, tt in to_write.items():
                results.append({"jira号": bugid, "触发时间": tt, "结果": f"写入失败: {str(e)[:50]}"})
    logger.info("批量写入触发时间完成: 写入 %d 条, 跳过已有 %d 条, 失败 %d 条 (跳过缓存=%s)",
                written_count, skipped_count, failed_count, skip_cloud_cache)
    return _ok({
        "written_count": written_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "results": results[:50]
    }, f"写入完成: 写入 {written_count} 条, 跳过已有 {skipped_count} 条")


# ==================== 功能12：AI日志分析自学习内容可视化 ====================

# AI日志分析服务的接口地址


@router.post("/api/test/ai_log_visual", response_model=ApiResponse)
async def ai_log_visual(request: Request):
    """读取AI日志分析服务的日志，按 Jira 号过滤并分组展示"""
    import os, re, json
    from src.api.routes.shared import _parse_ai_log_lines
    from src.services.server_legacy import _fetch_ai_logs
    body = await request.json() or {}
    jira_id = str(body.get("jira_id", "")).strip()
    log_name = str(body.get("log_name", "all")).strip()
    limit = int(body.get("limit", 5000))
    if not jira_id:
        return _fail("请输入 Jira 号")
    if log_name not in ("all", "app", "perf"):
        log_name = "all"
    try:
        lines = _fetch_ai_logs(name=log_name, limit=limit)
        result = _parse_ai_log_lines(lines, jira_id)
        result["jira_id"] = jira_id
        result["log_name"] = log_name
        return _ok(result, f"读取 {len(lines)} 行日志，匹配 {result['matched_lines']} 行，{len(result['rounds'])} 轮分析")
    except Exception as e:
        return _fail(f"读取日志失败: {e}")


@router.post("/api/test/ai_log_visual_upload", response_model=ApiResponse)
async def ai_log_visual_upload(jira_id: str = "", file: UploadFile = File(None)):
    """上传本地日志文件或压缩包，解析后按 Jira 号过滤并分组展示

    支持的文件类型：
    - 文本文件：.log, .txt, .md
    - 压缩包：.zip, .tar.gz, .tgz, .gz（解压后查找日志文件）
    """
    import os, re, json
    import zipfile
    import tarfile
    import gzip
    from src.api.routes.shared import _parse_ai_log_lines
    if not file or not file.filename:
        return _fail("未找到上传文件或文件名为空")
    jira_id = jira_id.strip()
    if not jira_id:
        return _fail("请输入 Jira 号")
    try:
        content = await _read_upload_limited(file, "上传文件")
        filename = file.filename.lower()
        lines = []
        file_info = []  # 记录解压后的文件信息

        if filename.endswith(".zip"):
            # ZIP 压缩包：解压后读取所有文本文件（限制条目数与解压总量）
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                names = zf.namelist()
                _check_archive_entries(names, "ZIP 压缩包")
                _budget = _ExpandBudget(label="ZIP 压缩包")
                for name in names:
                    if name.endswith("/"):
                        continue
                    name_lower = name.lower()
                    if any(name_lower.endswith(ext) for ext in (".log", ".txt", ".md", ".csv")):
                        _budget.take(zf.getinfo(name).file_size)
                        try:
                            text = zf.read(name).decode("utf-8", errors="replace")
                            file_lines = text.splitlines()
                            file_info.append({"name": name, "lines": len(file_lines)})
                            lines.extend(file_lines)
                        except Exception:
                            pass
        elif filename.endswith((".tar.gz", ".tgz")):
            # tar.gz 压缩包（限制条目数与解压总量）
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tf:
                members = tf.getmembers()
                _check_archive_entries(members, "tar.gz 压缩包")
                _budget = _ExpandBudget(label="tar.gz 压缩包")
                for member in members:
                    if not member.isfile():
                        continue
                    name_lower = member.name.lower()
                    if any(name_lower.endswith(ext) for ext in (".log", ".txt", ".md", ".csv")):
                        _budget.take(member.size)
                        try:
                            f_obj = tf.extractfile(member)
                            if f_obj:
                                text = f_obj.read().decode("utf-8", errors="replace")
                                file_lines = text.splitlines()
                                file_info.append({"name": member.name, "lines": len(file_lines)})
                                lines.extend(file_lines)
                        except Exception:
                            pass
        elif filename.endswith(".gz") and not filename.endswith(".tar.gz"):
            # 单个 .gz 文件（限制解压后大小，避免压缩炸弹）
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as _gz:
                _raw = _gz.read(_MAX_EXPAND_BYTES + 1)
            if len(_raw) > _MAX_EXPAND_BYTES:
                return _fail(f"gz 文件解压后超过 {_MAX_EXPAND_BYTES // 1024 // 1024}MB 限制")
            text = _raw.decode("utf-8", errors="replace")
            lines = text.splitlines()
            file_info.append({"name": file.filename, "lines": len(lines)})
        elif any(filename.endswith(ext) for ext in (".log", ".txt", ".md", ".csv")):
            # 普通文本文件
            text = content.decode("utf-8", errors="replace")
            lines = text.splitlines()
            file_info.append({"name": file.filename, "lines": len(lines)})
        else:
            # 尝试直接当文本读取
            try:
                text = content.decode("utf-8", errors="replace")
                lines = text.splitlines()
                file_info.append({"name": file.filename, "lines": len(lines)})
            except Exception:
                return _fail(f"不支持的文件类型: {file.filename}")

        if not lines:
            return _fail("文件中未找到有效文本内容")
        result = _parse_ai_log_lines(lines, jira_id)
        result["jira_id"] = jira_id
        result["file_info"] = file_info
        result["upload_filename"] = file.filename
        file_summary = f"{len(file_info)} 个文件" if len(file_info) > 1 else file.filename
        return _ok(result, f"{file_summary}，共 {len(lines)} 行，匹配 {result['matched_lines']} 行，{len(result['rounds'])} 轮分析")
    except Exception as e:
        logger.error("上传日志解析失败: %s", e)
        return _fail(f"解析失败: {e}")

# ==================== 本地文档分析（study目录） ====================


@router.post("/api/test/study_analysis", response_model=ApiResponse)
async def study_analysis(request: Request):
    """本地文档分析：扫描study目录或解析指定文件夹的推理轮次"""
    import os, re, json
    body = await request.json() or {}
    folder_path = str(body.get("folder_path", "")).strip()
    try:
        if folder_path:
            # 解析指定文件夹
            if not os.path.isdir(folder_path):
                return _fail(f"文件夹不存在: {folder_path}")
            result = _parse_reasoning_rounds(folder_path)
            result["folder_name"] = os.path.relpath(folder_path, _STUDY_DIR)
            return _ok(result, f"解析完成，共 {result['total_rounds']} 轮分析，总耗时 {result['elapsed_seconds']}秒")
        else:
            # 扫描全部文件夹
            folders = _scan_study_folders()
            if not folders:
                return _fail("study 目录下未找到任何分析文档")
            return _ok({"folders": folders}, f"找到 {len(folders)} 个分析文件夹")
    except Exception as e:
        return _fail(f"分析失败: {e}")


@router.get("/api/test/ai_report/{bugid}")
async def get_ai_report(bugid: str, source: str = "pc"):
    """获取 AI 日志分析报告：优先读本地 docs/日期/bugid.md，不存在则从远程下载并保存"""
    import httpx, os
    from src.config import PROJECT_ROOT
    # 本地路径：docs/{today}/{bugid}.md
    today = datetime.now().strftime("%Y-%m-%d")
    docs_dir = os.path.join(PROJECT_ROOT, "docs", today)
    local_path = os.path.join(docs_dir, f"{bugid}.md")
    # 优先读本地已有文件
    if os.path.isfile(local_path):
        with open(local_path, "r", encoding="utf-8") as f:
            content = f.read()
        return _ok({
            "content": content, "bugid": bugid,
            "file_path": local_path, "dir_path": docs_dir, "source": "local",
        }, "本地已有报告")
    # 远程下载：根据 source 选择 PC 或线上服务器
    cfg_all = load_config().get("app_log_server", {})
    if source not in cfg_all and "host" in cfg_all:
        cfg = cfg_all
    else:
        cfg = cfg_all.get(source, cfg_all.get("pc", {}))
    host = cfg.get("host", "10.22.126.133")
    port = cfg.get("port", 8001)
    debug_endpoint = cfg.get("debug_endpoint", "/api/logs/debug")
    url = f"http://{host}:{port}{debug_endpoint}/{bugid}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return _fail(f"接口返回 status={resp.status_code}")
        raw = resp.content
        if not raw:
            return _fail("报告内容为空")
        # 判断是否为压缩包（ZIP/RAR 魔数检测）
        is_archive = (raw[:4] == b'PK\x03\x04' or
                      raw[:7] in (b'Rar!\x1a\x07\x00', b'Rar!\x1a\x07\x01'))
        if is_archive:
            from src.services.observability_service import _extract_debug_archive
            os.makedirs(docs_dir, exist_ok=True)
            files = _extract_debug_archive(raw, docs_dir, bugid)
            content = files.get("02_reasoning_rounds.md", "")
            if not content:
                return _fail(f"压缩包中无匹配文件，实际文件列表: {list(files.keys())}")
            # 保存的文件名（带 case_id 前缀）
            import re as _re
            saved_rr = _re.sub(r'^\d+_', f'{bugid}_', "02_reasoning_rounds.md")
            return _ok({
                "content": content, "bugid": bugid,
                "file_path": os.path.join(docs_dir, saved_rr),
                "dir_path": docs_dir, "source": "remote",
                "archive_files": list(files.keys()),
            }, f"已从 {source} 下载压缩包并解压（{len(files)} 个文件）")
        else:
            # 兼容旧接口：返回纯文本 Markdown
            content = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            if not content.strip():
                return _fail("报告内容为空")
            os.makedirs(docs_dir, exist_ok=True)
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(content)
            return _ok({
                "content": content, "bugid": bugid,
                "file_path": local_path, "dir_path": docs_dir, "source": "remote",
            }, f"已从 {source} 下载并保存到本地")
    except httpx.ConnectTimeout:
        return _fail(f"连接超时，AI日志分析服务({source}: {host}:{port})不可达，请检查网络连接或VPN")
    except httpx.ConnectError:
        return _fail(f"连接失败，AI日志分析服务({source}: {host}:{port})无法连通，请检查网络连接或VPN")
    except Exception as e:
        return _fail(f"获取失败: {e}")


@router.post("/api/test/ai_report_analyze", response_model=ApiResponse)
async def ai_report_analyze(request: Request):
    """直接分析 MD 内容（02_reasoning_rounds 格式），返回轮次解析结果"""
    from src.api.routes.shared import parse_reasoning_content
    body = await request.json() or {}
    content = body.get("content", "")
    if not content or not content.strip():
        return _fail("报告内容为空")
    try:
        result = parse_reasoning_content(content)
        return _ok(result, f"解析完成: {result['total_rounds']} 轮")
    except Exception as e:
        return _fail(f"解析失败: {e}")


@router.get("/api/test/open_dir")
def open_dir(path: str = ""):
    """在系统文件管理器中打开本地目录（Windows/macOS/Linux 通用）"""
    import subprocess, os, sys
    if not path or not os.path.isdir(path):
        return _fail(f"目录不存在: {path}")
    try:
        if sys.platform == "win32":
            # 部分受限环境下 os.startfile 会 WinError 5，改由 explorer 打开；其退出码常为 1，故不等待
            subprocess.Popen(["explorer", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return _ok(None, f"已打开: {path}")
    except Exception as e:
        return _fail(f"打开失败: {e}")


# ========== 功能14：表单执行 ==========


@router.post("/api/test/form_upload")
async def form_upload(file: UploadFile = File(None)):
    """表单执行：上传 CSV/Excel 文件，解析 Jira 号和触发时间"""
    import os, csv as _csv, io
    if not file or not file.filename:
        return _fail("未找到上传文件")
    ext = os.path.splitext(file.filename)[1].lower()
    keys, csv_trigger_times, seen = [], {}, set()
    try:
        content = await _read_upload_limited(file, "表单文件")
        if ext in (".xlsx", ".xls"):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
                ws = wb.active
                headers = [str(c.value or "").strip() for c in next(ws.iter_rows(min_row=1, max_row=1))]
                # 查找 Jira 号和触发时间列索引
                jira_idx = next((i for i, h in enumerate(headers) if h in ("jira号", "Jira号", "JIRA号", "VCU号", "bugid", "BugID")), None)
                time_idx = next((i for i, h in enumerate(headers) if h in ("触发时间", "创建时间", "执行时间", "分析执行时间")), None)
                if jira_idx is None:
                    return _fail("Excel 文件中未找到 Jira 号列")
                for row in ws.iter_rows(min_row=2, values_only=True):
                    jira = str(row[jira_idx] or "").strip()
                    if jira and jira not in seen:
                        seen.add(jira)
                        keys.append(jira)
                        if time_idx is not None and time_idx < len(row):
                            tt = str(row[time_idx] or "").strip()
                            if tt:
                                csv_trigger_times[jira] = tt
            except ImportError:
                return _fail("服务器未安装 openpyxl，请使用 CSV 格式上传")
        else:
            text = content.decode("utf-8-sig")
            reader = _csv.DictReader(io.StringIO(text))
            for row in reader:
                jira = (row.get("jira号") or row.get("Jira号") or row.get("JIRA号") or row.get("VCU号") or row.get("bugid") or row.get("BugID") or "").strip()
                if jira and jira not in seen:
                    seen.add(jira)
                    keys.append(jira)
                    tt = (row.get("触发时间") or row.get("创建时间") or row.get("执行时间") or row.get("分析执行时间") or "").strip()
                    if tt:
                        csv_trigger_times[jira] = tt
    except Exception as e:
        return _fail(f"文件解析失败: {e}")
    if not keys:
        return _fail("文件中未找到有效 Jira 号")
    msg = f"导入 {len(keys)} 个 Jira 号"
    if csv_trigger_times:
        msg += f"，其中 {len(csv_trigger_times)} 个有触发时间"
    return _ok({"keys": keys, "csv_trigger_times": csv_trigger_times}, msg)


@router.post("/api/test/form_exec")
async def form_exec(request: Request):
    """表单执行：多轮抽样 + 执行，SSE 实时推送，触发时间优先云端缓存→新提取"""
    import os, re, json, random, csv as _csv, queue, asyncio, threading
    import json as _json
    from src.services.report_ops import _upload_batch_to_cloud
    from src.services.trigger_ops import (
        _load_cloud_trigger_cache, _save_trigger_time_to_csv,
        _batch_save_trigger_times_to_cloud,
    )
    from src.services.report_ops import _load_all_doc_jira_keys
    from src.services.server_legacy import _diag_extract_time_from_video_simple, _has_gmlogger_logs, _diag_extract_time_from_images
    body = await request.json() or {}
    keys = body.get("keys") or []
    csv_trigger_times = body.get("csv_trigger_times") or {}
    sample_count = max(1, int(body.get("sample_count", 10)))
    interval_min = max(0, int(body.get("interval_min", 0)))
    total_rounds = max(1, int(body.get("total_rounds", 1)))
    exec_mode = str(body.get("exec_mode", "pc")).strip()
    _batch_meta = {
        "分析并发数": str(body.get("analysis_concurrency", "10")),
        "下载并发数": str(body.get("download_concurrency", "4")),
        "模型": str(body.get("model", "deepseek-v-pro")),
        "触发来源": str(body.get("trigger_source", "PC")),
    }
    if not keys:
        return _fail("待执行列表为空，请先上传文件")

    async def event_generator():
        from src.clients import jira_client as _jc
        from src.clients.base import http_post
        from src.api.routes.shared import form_exec_stop_event as _stop_event
        _stop_event.clear()
        loop = asyncio.get_event_loop()
        cfg = load_config()
        cfg_api = cfg.get("ai_log_api", {})
        # 去重 keys
        seen_keys = set()
        unique_keys = []
        for k in keys:
            if k not in seen_keys:
                seen_keys.add(k)
                unique_keys.append(k)
        keys_dedup = unique_keys
        yield f"data: {_json.dumps({'type': 'start', 'total': len(keys_dedup)}, ensure_ascii=False)}\n\n"
        # 加载云端缓存
        local_times, cloud_keys = _load_cloud_trigger_cache()
        trigger_times = {}
        for k in keys_dedup:
            if k in local_times and local_times[k]:
                trigger_times[k] = local_times[k]
        # 合并 CSV 触发时间（云端优先）
        for k in keys_dedup:
            if k not in trigger_times and k in csv_trigger_times and csv_trigger_times[k]:
                trigger_times[k] = csv_trigger_times[k]
        # 分类
        with_time = [k for k in keys_dedup if k in trigger_times]
        pending_pool = [k for k in keys_dedup if k not in trigger_times and k not in cloud_keys]
        random.shuffle(pending_pool)
        yield f"data: {_json.dumps({'type': 'cache', 'cached': len(with_time), 'pending': len(pending_pool)}, ensure_ascii=False)}\n\n"
        # PC 配置
        pc_cfg = cfg_api if exec_mode != "online" else None
        all_results = []
        total_success, total_fail = 0, 0
        all_no_time = []
        # 多轮执行
        for round_num in range(1, total_rounds + 1):
            if _stop_event.is_set():
                break
            if total_rounds > 1:
                yield f"data: {_json.dumps({'type': 'round', 'round': round_num, 'total_rounds': total_rounds}, ensure_ascii=False)}\n\n"
            # 本轮抽样：优先有触发时间的，不够则提取
            remaining = sample_count
            round_selected = []
            round_cloud = 0
            round_extracted = 0
            round_extract_failed = 0
            round_no_time = []
            # 从有触发时间的池中抽取
            available_with_time = [k for k in keys_dedup if k in trigger_times and k not in [r.get("bugid") for r in all_results]]
            if available_with_time:
                pick = min(remaining, len(available_with_time))
                round_selected.extend(random.sample(available_with_time, pick))
                round_cloud = pick
                remaining -= pick
            # 不够则从 pending_pool 提取
            if remaining > 0 and pending_pool:
                extract_batch = 20
                _cloud_flush_counter = 0
                new_to_cloud = {}
                batch = pending_pool[:extract_batch * 3]  # 多取一些以防提取失败
                pending_pool = pending_pool[len(batch):]
                for k in batch:
                    if remaining <= 0:
                        break
                    if _stop_event.is_set():
                        break
                    try:
                        issue = await loop.run_in_executor(None, _jc.fetch_issue, k)
                        attachments = (issue.get("fields") or {}).get("attachment") or []
                        if not _has_gmlogger_logs(attachments, k):
                            round_extract_failed += 1
                            continue
                        tt = await loop.run_in_executor(None, lambda iss=issue: _jc.extract_trigger_time_from_issue(iss, skip_attachment=True))
                        if not tt:
                            tt = await loop.run_in_executor(None, _diag_extract_time_from_video_simple, issue)
                        if not tt:
                            cfg_jira = cfg.get("jira_api", {})
                            img_h, img_tok = {}, cfg_jira.get("token", "")
                            if img_tok:
                                img_h["Authorization"] = f"Bearer {img_tok}"
                            img_to = max(int(cfg_jira.get("timeout", 30)), 120)
                            img_result = await loop.run_in_executor(None, _diag_extract_time_from_images, issue, img_h, img_to, k)
                            img_tt = img_result[0] if isinstance(img_result, tuple) else img_result
                            if img_tt:
                                tt = img_tt
                        # 附件文件名最终兑底
                        if not tt:
                            tt = await loop.run_in_executor(None, _jc.extract_attachment_time, issue)
                        if tt and not isinstance(tt, str):
                            tt = tt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(tt, 'strftime') else str(tt)
                        if tt:
                            trigger_times[k] = tt
                            await loop.run_in_executor(None, _save_trigger_time_to_csv, k, tt)
                            new_to_cloud[k] = tt
                            round_selected.append(k)
                            round_extracted += 1
                            remaining -= 1
                        else:
                            await loop.run_in_executor(None, _save_trigger_time_to_csv, k, "")
                            new_to_cloud[k] = ""
                            round_extract_failed += 1
                    except Exception as e:
                        logger.warning("表单执行提取触发时间失败 %s: %s", k, e)
                        await loop.run_in_executor(None, _save_trigger_time_to_csv, k, "")
                        new_to_cloud[k] = ""
                        round_extract_failed += 1
                    _cloud_flush_counter += 1
                    if _cloud_flush_counter >= 2 and new_to_cloud:
                        await loop.run_in_executor(None, _batch_save_trigger_times_to_cloud, new_to_cloud)
                        new_to_cloud.clear()
                        _cloud_flush_counter = 0
                if new_to_cloud:
                    await loop.run_in_executor(None, _batch_save_trigger_times_to_cloud, new_to_cloud)
            # 推送抽样结果
            yield f"data: {_json.dumps({'type': 'sample', 'round': round_num, 'selected': len(round_selected), 'cloud': round_cloud, 'extracted': round_extracted, 'failed': round_extract_failed}, ensure_ascii=False)}\n\n"
            # 本轮执行
            batch_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            round_results = []
            for bugid in round_selected:
                if _stop_event.is_set():
                    yield f"data: {_json.dumps({'type': 'stopped', 'total': len(all_results), 'success': total_success, 'fail': total_fail}, ensure_ascii=False)}\n\n"
                    return
                exec_time = trigger_times.get(bugid, "")
                if not exec_time:
                    round_results.append({"bugid": bugid, "执行结果": "失败", "备注": "无触发时间", "触发时间": "", "执行时间": batch_start})
                    all_no_time.append(bugid)
                    yield f"data: {_json.dumps({'type': 'progress', 'index': len(round_results), 'total': len(round_selected), 'bugid': bugid, 'status': 'fail', 'round': round_num}, ensure_ascii=False)}\n\n"
                    continue
                try:
                    if exec_mode == "online":
                        payload = {"jiraNumber": bugid, "questionTimes": [exec_time]}
                        resp = await loop.run_in_executor(None, lambda p=payload: http_post(_get_prod_ai_url(), p, timeout=30))
                    else:
                        payload = {cfg_api.get("bugid_field", "jira号"): bugid}
                        if cfg_api.get("trigger_time_field"):
                            payload[cfg_api["trigger_time_field"]] = exec_time
                        resp = await loop.run_in_executor(None, lambda p=payload: http_post(cfg_api.get("url", ""), p, timeout=int(cfg_api.get("timeout", 60))))
                    resp_code = resp.get("code") if isinstance(resp, dict) else None
                    resp_msg = str(resp.get("msg", "")) if isinstance(resp, dict) else str(resp)[:200]
                    is_ok = (resp_code == 200 or resp_code == 0 or resp_code == "200")
                    round_results.append({"bugid": bugid, "执行结果": "成功" if is_ok else "失败", "备注": resp_msg[:200], "触发时间": exec_time, "执行时间": batch_start})
                except Exception as e:
                    round_results.append({"bugid": bugid, "执行结果": "失败", "备注": str(e)[:200], "触发时间": exec_time, "执行时间": batch_start})
                yield f"data: {_json.dumps({'type': 'progress', 'index': len(round_results), 'total': len(round_selected), 'bugid': bugid, 'status': round_results[-1]['执行结果'], 'round': round_num}, ensure_ascii=False)}\n\n"
            round_success = sum(1 for r in round_results if r["执行结果"] == "成功")
            round_fail = len(round_results) - round_success
            total_success += round_success
            total_fail += round_fail
            all_results.extend(round_results)
            # 轮次间隔
            if round_num < total_rounds and interval_min > 0:
                yield f"data: {_json.dumps({'type': 'waiting', 'interval_min': interval_min, 'round': round_num}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(interval_min * 60)
        # 收集所有无触发时间的 Jira 号
        for k in keys_dedup:
            if k not in trigger_times and k not in [r.get("bugid") for r in all_results]:
                all_no_time.append(k)
        all_no_time_dedup = list(dict.fromkeys(all_no_time))
        if all_no_time_dedup:
            yield f"data: {_json.dumps({'type': 'no_time', 'jiras': all_no_time_dedup}, ensure_ascii=False)}\n\n"
        # 保存结果 CSV
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        mode_label = "线上" if exec_mode == "online" else "PC"
        os.makedirs(_UNANALYZED_DIR, exist_ok=True)
        batch_csv = os.path.join(_UNANALYZED_DIR, f"form_exec_{date_str}_{time_str}.csv")
        cloud_url = ""
        try:
            with open(batch_csv, "w", newline="", encoding="utf-8-sig") as f:
                writer = _csv.writer(f)
                writer.writerow(["jira号", "执行结果", "触发时间", "执行时间", "备注",
                                 "分析并发数", "下载并发数", "模型", "触发来源", "执行模式"])
                for r in all_results:
                    writer.writerow([r["bugid"], r["执行结果"], r.get("触发时间", ""),
                                     r.get("执行时间", ""), r.get("备注", ""),
                                     _batch_meta["分析并发数"], _batch_meta["下载并发数"],
                                     _batch_meta["模型"], _batch_meta["触发来源"], mode_label])
            doc_title = f"表单执行 {mode_label} {date_str} {time_str} ({total_success}/{len(all_results)}, {total_rounds}轮)"
            cloud_url = _upload_batch_to_cloud(batch_csv, doc_title)
        except Exception as e:
            logger.warning("表单执行: 保存失败: %s", e)
        yield f"data: {_json.dumps({'type': 'done', 'total': len(all_results), 'success': total_success, 'fail': total_fail, 'rounds': total_rounds, 'no_time_count': len(all_no_time_dedup), 'cloud_url': cloud_url}, ensure_ascii=False)}\n\n"

    # 注册作业：/api/jobs 可查进度，/api/jobs/{id}/stop 可单独停止本作业
    from src.core.job_registry import JOBS as _JOBS
    from src.api.routes.jobs import job_stream as _job_stream
    from src.api.routes.shared import form_exec_stop_event as _form_stop
    _job = _JOBS.create("form_exec", f"表单执行（样本 {sample_count}，{total_rounds} 轮）")
    return StreamingResponse(_job_stream(_job, event_generator, _form_stop), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ========== 功能13：配置参数调优 ==========


# ==================== 功能14：ADP 测试 ====================

@router.post("/api/test/adp_single")
async def test_adp_single(request: Request):
    """ADP 单条分析：输入 Jira 号，自动获取描述和触发时间，调用 ADP v2 分析并写入飞书"""
    import json as _json
    import asyncio
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("bugid 不能为空")

    async def event_generator():
        loop = asyncio.get_event_loop()
        # Step 0: 获取 Jira 信息（描述 + 触发时间）
        yield f"data: {_json.dumps({'type': 'step', 'step': 'jira_info', 'status': 'running'}, ensure_ascii=False)}\n\n"
        try:
            from src.clients import jira_client as _jc
            issue = await loop.run_in_executor(None, _jc.fetch_issue, bugid)
            fields = issue.get("fields") or {}
            description = (fields.get("description") or "")[:500]
            # description 为空时用 summary 兖底
            if not description.strip():
                description = (fields.get("summary") or "")[:500]
            trigger_time = ""
            try:
                trigger_time = await loop.run_in_executor(
                    None, lambda: _jc.extract_trigger_time_from_issue(issue))
            except Exception as e:
                logger.warning("ADP 触发时间提取失败: %s", e)
            yield f"data: {_json.dumps({'type': 'step', 'step': 'jira_info', 'status': 'done', 'description': description[:200], 'trigger_time': trigger_time}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'step', 'step': 'jira_info', 'status': 'fail', 'error': str(e)[:100]}, ensure_ascii=False)}\n\n"
            yield f"data: {_json.dumps({'type': 'done', 'ok': False, 'error': f'Jira 查询失败: {e}'}, ensure_ascii=False)}\n\n"
            return

        # Step 1-5: ADP 分析全流程（带心跳 + 实时步骤推送）
        import queue as _queue
        from src.services.adp_ops import run_adp_single
        _ka_queue = _queue.Queue()
        _step_queue = _queue.Queue()  # 实时步骤事件队列
        _result_ref = [None]

        def _ka_cb(elapsed_sec):
            _ka_queue.put(elapsed_sec)

        def _progress_cb(step, status, detail=""):
            _step_queue.put({"step": step, "status": status, "detail": detail})

        def _run_in_thread():
            try:
                _result_ref[0] = run_adp_single(bugid, description, trigger_time,
                                                progress_cb=_progress_cb, keepalive_cb=_ka_cb)
            except Exception as e:  # 线程内异常也要带回结构化结果，避免前端只看到“线程异常”
                logger.error("ADP 单条分析线程异常 %s: %s", bugid, e, exc_info=True)
                _result_ref[0] = {"ok": False, "jira_key": bugid, "error": f"分析异常: {str(e)[:200]}",
                                  "attachment_count": 0, "results": {}}

        import threading
        _thread = threading.Thread(target=_run_in_thread, daemon=True)
        _thread.start()
        # 等待线程完成，期间每 5s 发送心跳 + 实时步骤事件
        while _thread.is_alive():
            await asyncio.sleep(5)
            # 推送实时步骤事件
            while not _step_queue.empty():
                try:
                    evt = _step_queue.get_nowait()
                    step_data = {'type': 'step', 'step': evt['step'], 'status': evt['status']}
                    if evt['step'] == 'attachments' and evt.get('detail'):
                        step_data['detail'] = evt['detail']
                    if evt['step'] == 'adp_analysis' and evt.get('detail'):
                        step_data['detail'] = evt['detail']
                    yield f"data: {_json.dumps(step_data, ensure_ascii=False)}\n\n"
                except _queue.Empty:
                    break
            # 清空心跳队列，取最新的
            latest_ka = None
            while not _ka_queue.empty():
                try:
                    latest_ka = _ka_queue.get_nowait()
                except _queue.Empty:
                    break
            yield f"data: {_json.dumps({'type': 'keepalive', 'elapsed': latest_ka or 0}, ensure_ascii=False)}\n\n"
        # 排空剩余步骤事件
        while not _step_queue.empty():
            try:
                evt = _step_queue.get_nowait()
                step_data = {'type': 'step', 'step': evt['step'], 'status': evt['status']}
                yield f"data: {_json.dumps(step_data, ensure_ascii=False)}\n\n"
            except _queue.Empty:
                break
        result = _result_ref[0] or {"ok": False, "error": "线程异常"}
        # ADP 执行批次记录（本地CSV + 云端多维表格）
        try:
            from src.services.adp_ops import save_adp_batch_log as _save_batch_log
            _save_batch_log([{"jira_key": bugid, "ok": result.get("ok", False),
                              "error": result.get("error", ""),
                              "fail_type": _adp_fail_type(result),
                              "traceid": (result.get("results") or {}).get("traceid", ""),
                              "traceid排查": (result.get("results") or {}).get("traceid排查", "")}])
        except Exception:
            logger.warning("ADP 单条执行批次记录保存失败", exc_info=True)
        # 推送附件数 + 飞书状态等补充信息
        yield f"data: {_json.dumps({'type': 'step', 'step': 'attachments', 'status': 'done' if result.get('attachment_count', 0) > 0 else 'fail', 'count': result.get('attachment_count', 0)}, ensure_ascii=False)}\n\n"
        if not result.get('attachment_count'):
            yield f"data: {_json.dumps({'type': 'done', 'ok': False, 'error': result.get('error') or '无附件', 'fail_type': _adp_fail_type(result), **_adp_text_payload(result)}, ensure_ascii=False)}\n\n"
            return
        fs = result.get('feishu') or {}
        yield f"data: {_json.dumps({'type': 'step', 'step': 'write_feishu', 'status': 'done' if fs.get('ok') else 'fail', 'message': fs.get('message', '')}, ensure_ascii=False)}\n\n"
        # 推送最终结果
        yield f"data: {_json.dumps({'type': 'done', 'ok': result.get('ok', False), 'results': result.get('results', {}), 'elapsed': result.get('total_elapsed', 0), 'attachment_count': result.get('attachment_count', 0), 'feishu_ok': fs.get('ok', False), 'fail_type': _adp_fail_type(result), **_adp_text_payload(result), 'file_urls': result.get('file_urls', [])}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/test/adp_report")
def adp_report_file(jira_key: str = ""):
    """读取 ADP 分析报告全文（只允许读取 adp_results 下对应 bugid 的 md 报告）

    前端不再接收完整文本，改为点「查看完整报告」时按需打开本接口。
    """
    import os
    import re as _re
    key = (jira_key or "").strip()
    if not key or not _re.fullmatch(r"[A-Za-z0-9_\-]+", key):
        return _fail("jira_key 不合法")
    from src.config import get_path
    from src.services.adp_ops import _get_adp_cfg
    cfg = _get_adp_cfg()
    base = get_path("doc_dir") if cfg.get("save_dir", "docs/adp_results") == "docs/adp_results" else cfg["save_dir"]
    path = os.path.join(base, "adp_results", key, f"{key}_full_analysis.md")
    if not os.path.isfile(path):
        # 回退：失败快照（<key>_fail_*.md）取最新的一个，保证失败时也能看到返回内容
        day_dir = os.path.join(base, "adp_results", key)
        fails = sorted(
            (f for f in os.listdir(day_dir) if f.startswith(f"{key}_fail_") and f.endswith(".md")),
            reverse=True) if os.path.isdir(day_dir) else []
        if not fails:
            return _fail(f"报告不存在: {key}")
        path = os.path.join(day_dir, fails[0])
    return FileResponse(path, media_type="text/markdown; charset=utf-8")


@router.post("/api/test/adp_batch")
async def test_adp_batch(request: Request):
    """ADP 批量分析：Excel 导入 → 分批执行(2个/批) → 写入飞书，支持连续/单次模式"""
    import json as _json
    import asyncio
    import concurrent.futures
    body = await request.json() or {}
    items = body.get("items") or []  # [{bugid, description, trigger_time}]
    batch_size = int(body.get("batch_size") or 3)
    continuous = body.get("continuous", False)
    if not items:
        return _fail("无待执行项")

    async def event_generator():
        loop = asyncio.get_event_loop()
        from src.services.adp_ops import run_adp_single
        from src.api.routes.shared import adp_lookup_stop_event as _batch_stop
        _batch_stop.clear()

        # 去重：排除已执行的
        executed_keys = set()
        try:
            from src.api.routes.testing import _get_same_source_executed_keys
            executed_keys = _get_same_source_executed_keys("adp")
        except Exception:
            pass
        todo = [it for it in items if it.get("bugid", "") not in executed_keys]
        skipped = len(items) - len(todo)
        if skipped:
            yield f"data: {_json.dumps({'type': 'dedup', 'skipped': skipped}, ensure_ascii=False)}\n\n"

        total = len(todo)
        total_batches = (total + batch_size - 1) // batch_size
        # 非连续模式只执行第一批
        if not continuous:
            todo = todo[:batch_size]
            total_batches = 1

        yield f"data: {_json.dumps({'type': 'start', 'total': len(todo), 'batch_size': batch_size, 'total_batches': total_batches, 'continuous': continuous}, ensure_ascii=False)}\n\n"

        all_results = []
        batch_results = []
        next_idx = 0
        import time as _time
        _t0 = _time.time()

        def _run_one(item):
            bugid = item.get("bugid", "")
            desc = item.get("description", "")
            tt = item.get("trigger_time", "")
            # 描述或时间为空时用 Jira API 兜底
            if not desc.strip() or not tt.strip():
                try:
                    from src.clients import jira_client as _jc_fallback
                    _issue = _jc_fallback.fetch_issue(bugid)
                    _f = (_issue.get("fields") or {})
                    if not desc.strip():
                        desc = (_f.get("description") or "")[:500]
                    if not desc.strip():
                        desc = (_f.get("summary") or "")[:500]
                    if not tt.strip():
                        try:
                            tt = _jc_fallback.extract_trigger_time_from_issue(_issue) or ""  
                        except Exception:
                            pass
                except Exception as _e:
                    logger.warning("ADP batch Jira兜底失败 %s: %s", bugid, _e)
            try:
                return run_adp_single(bugid, desc, tt, stop_event=_batch_stop)
            except Exception as e:
                return {"ok": False, "jira_key": bugid, "error": str(e)[:100]}

        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as pool:
            futures = {}
            for it in todo[:batch_size]:
                f = pool.submit(_run_one, it)
                futures[f] = it
            next_idx = batch_size
            batch_deadline = _time.time() + 600
            while futures:
                if _batch_stop.is_set():
                    for f in futures:
                        f.cancel()
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                if _time.time() > batch_deadline:
                    for f in list(futures):
                        f.cancel()
                        it = futures.pop(f)
                        r = {"ok": False, "jira_key": it.get("bugid", ""), "error": "ADP 分析超时"}
                        batch_results.append(r)
                        yield f"data: {_json.dumps({'type': 'item_done', 'jira_key': r['jira_key'], 'ok': False, 'results': {}, 'error': r['error'], 'fail_type': _adp_fail_type(r), **_adp_text_payload({}), 'file_urls': []}, ensure_ascii=False)}\n\n"
                    break
                done_now = [f for f in futures if f.done()]
                for future in done_now:
                    it = futures.pop(future)
                    try:
                        r = future.result()
                    except Exception as e:
                        r = {"ok": False, "jira_key": it.get("bugid", ""), "error": str(e)[:100]}
                    batch_results.append(r)
                    yield f"data: {_json.dumps({'type': 'item_done', 'jira_key': r.get('jira_key', ''), 'ok': r.get('ok', False), 'results': r.get('results', {}), 'error': r.get('error', ''), 'fail_type': _adp_fail_type(r), **_adp_text_payload(r), 'file_urls': r.get('file_urls', [])}, ensure_ascii=False)}\n\n"
                    # 动态补位：只要完成一个，立即从 todo 取下一个
                    if next_idx < len(todo):
                        next_item = todo[next_idx]
                        nf = pool.submit(_run_one, next_item)
                        futures[nf] = next_item
                        next_idx += 1
                if futures and not done_now:
                    running_keys = [futures[f].get('bugid', '') for f in futures]
                    yield f"data: {_json.dumps({'type': 'keepalive', 'running': running_keys}, ensure_ascii=False)}\n\n"
                if futures:
                    await asyncio.sleep(5)

        all_results.extend(batch_results)

        total_ok = sum(1 for r in all_results if r.get('ok'))
        # ADP 执行批次记录（本地CSV + 云端多维表格）
        try:
            from src.services.adp_ops import save_adp_batch_log as _save_batch_log
            _save_batch_log([{"jira_key": r.get('jira_key', ''), 'ok': r.get('ok', False),
                              'error': r.get('error', ''), 'fail_type': _adp_fail_type(r),
                              'traceid': (r.get('results') or {}).get('traceid', ''),
                              'traceid排查': (r.get('results') or {}).get('traceid排查', '')}
                             for r in all_results],
                            total_elapsed=round(_time.time() - _t0, 1))
        except Exception:
            logger.warning("ADP 批量执行批次记录保存失败", exc_info=True)
        _elapsed = round(_time.time() - _t0, 1)
        yield f"data: {_json.dumps({'type': 'done', 'total': len(all_results), 'success': total_ok, 'fail': len(all_results) - total_ok, 'total_elapsed': _elapsed}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/test/adp_enrich")
async def test_adp_enrich(request: Request):
    """ADP 补全：对多条 Jira 号通过 API 获取 description 和 trigger_time，用于 Excel 导入后补全缺失字段"""
    import json as _json
    import asyncio
    import concurrent.futures
    body = await request.json() or {}
    bugids = body.get("bugids") or []
    if not bugids:
        return _fail("bugids 不能为空")

    def _enrich_one(bugid):
        from src.clients import jira_client as _jc
        try:
            issue = _jc.fetch_issue(bugid)
            fields = issue.get("fields") or {}
            desc = (fields.get("description") or "")[:500]
            if not desc.strip():
                desc = (fields.get("summary") or "")[:500]
            tt = ""
            try:
                tt = _jc.extract_trigger_time_from_issue(issue) or ""
            except Exception:
                pass
            return {"bugid": bugid, "description": desc, "trigger_time": tt}
        except Exception as e:
            return {"bugid": bugid, "description": "", "trigger_time": "", "error": str(e)[:80]}

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None, lambda: list(concurrent.futures.ThreadPoolExecutor(max_workers=5)
                           .map(_enrich_one, bugids)))
    return _ok(results, f"补全完成: {len(results)} 条")


@router.post("/api/test/adp_lookup")
async def test_adp_lookup(request: Request):
    """ADP 按 Jira 号查找：多维表格读记录 → 补全字段 → 2个并发执行 → 失败重试一次 → 写回
    mode=manual: 使用传入的 bugids
    mode=auto:   自动从多维表格中查找无报告记录，按顺序取前 limit 条执行
    """
    import json as _json
    import asyncio
    import concurrent.futures
    import threading
    import queue as _queue
    from src.api.routes.shared import adp_lookup_stop_event as _stop_event
    body = await request.json() or {}
    mode = body.get("mode") or "manual"
    bugids = body.get("bugids") or []
    limit = int(body.get("limit") or 10)
    batch_size = int(body.get("batch_size") or 3)
    if mode == "manual" and not bugids:
        return _fail("bugids 不能为空")
    _stop_event.clear()

    async def event_generator():
        import time as _time
        _t0 = _time.time()  # 批量执行起始时间
        loop = asyncio.get_event_loop()
        from src.clients import feishu_client, jira_client as _jc
        from src.services.adp_ops import run_adp_single, _get_adp_cfg, classify_adp_failure
        adp_cfg = _get_adp_cfg()
        app_token = adp_cfg["bitable_app_token"]
        table_id = adp_cfg["bitable_table_id"]
        view_id = adp_cfg.get("bitable_view_id", "") or None
        jira_field = adp_cfg["jira_field"]
        table_name = adp_cfg.get("bitable_table_name", "")

        # ── Step 1: 读取多维表格记录，构建 bugid → record 映射 ──
        yield f"data: {_json.dumps({'type': 'step', 'step': 'read_bitable', 'status': 'running'}, ensure_ascii=False)}\n\n"
        try:
            records = await loop.run_in_executor(
                None, lambda: feishu_client.list_bitable_records(app_token, table_id, view_id=view_id))
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'step', 'step': 'read_bitable', 'status': 'fail', 'error': str(e)[:100]}, ensure_ascii=False)}\n\n"
            return
        # ── 校验日志：确认读取到的表格与配置一致 ──
        logger.info("ADP lookup 读取多维表格: config_name='%s' table_id=%s 记录数=%d", table_name, table_id, len(records))
        if table_name and len(records) > 100 and "回归测试" in table_name:
            logger.warning("ADP lookup 读取到 %d 条记录，但配置表格 '%s' 预期记录数较少，请确认 table_id 是否正确", len(records), table_name)
        import re as _re
        bt_map = {}
        # auto 模式：收集未完成记录（完成状态为空），按表格顺序取前 limit 条
        no_report_keys = []
        for rec in records:
            fv = rec.get("fields", {}).get(jira_field, "")
            if isinstance(fv, list) and fv:
                fv_text = fv[0].get("text", "") if isinstance(fv[0], dict) else str(fv[0])
            else:
                fv_text = str(fv)
            m = _re.search(r'([A-Z]+-\d+)', fv_text)
            if m:
                key = m.group(1)
                bt_map[key] = rec
                # 判断该行是否已完成分析（只看完成状态是否有值）
                fields = rec.get("fields", {})
                status = ""
                sv = fields.get("完成状态", "")
                if isinstance(sv, list) and sv:
                    status = sv[0].get("text", "") if isinstance(sv[0], dict) else str(sv[0])
                elif isinstance(sv, str):
                    status = sv.strip()
                is_done = bool(status)
                if not is_done:
                    no_report_keys.append(key)
        if mode == "auto":
            effective_bugids = no_report_keys[:limit]
            yield f"data: {_json.dumps({'type': 'step', 'step': 'read_bitable', 'status': 'done', 'table_name': table_name, 'total_records': len(records), 'matched': len(effective_bugids), 'no_report_total': len(no_report_keys), 'mode': 'auto', 'limit': limit}, ensure_ascii=False)}\n\n"
            if not effective_bugids:
                yield f"data: {_json.dumps({'type': 'done', 'total': 0, 'success': 0, 'fail': 0, 'msg': '无待分析记录'}, ensure_ascii=False)}\n\n"
                return
        else:
            effective_bugids = list(bugids)
            yield f"data: {_json.dumps({'type': 'step', 'step': 'read_bitable', 'status': 'done', 'table_name': table_name, 'total_records': len(records), 'matched': len([b for b in effective_bugids if b in bt_map])}, ensure_ascii=False)}\n\n"

        # ── 准备每条的 desc / tt ──
        def _prepare_fields(bugid):
            """从多维表格 + Jira API 补全 desc 和 tt"""
            rec = bt_map.get(bugid)
            bt_desc = ""
            bt_time = ""
            if rec:
                fields = rec.get("fields", {})
                bt_desc = _bitable_text(fields.get("问题描述", ""))
                raw_time = _bitable_text(fields.get("问题发生时间锚点", ""))
                if raw_time and raw_time.isdigit() and len(raw_time) >= 10:
                    try:
                        ts = int(raw_time)
                        if ts > 1e12:
                            ts = ts / 1000
                        bt_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                    except (ValueError, OSError):
                        bt_time = raw_time
                else:
                    bt_time = raw_time
            desc = bt_desc
            tt = bt_time
            if not desc or not tt:
                try:
                    issue = _jc.fetch_issue(bugid)
                    issue_fields = issue.get("fields") or {}
                    if not desc:
                        desc = (issue_fields.get("description") or "")[:500]
                    if not desc:
                        desc = (issue_fields.get("summary") or "")[:500]
                    if not tt:
                        try:
                            tt = _jc.extract_trigger_time_from_issue(issue) or ""
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning("ADP lookup Jira补全失败 %s: %s", bugid, e)
            return {"bugid": bugid, "desc": desc, "tt": tt, "rec": rec,
                    "bt_desc": bt_desc, "bt_time": bt_time}

        # ── 单条 ADP 执行（线程内调用）──
        def _run_one_adp(bugid):
            """在子线程中执行字段补全 + ADP 分析，返回结果 dict
            跳过内部飞书写回，由 _write_back 统一使用已知 record_id 写回，避免重复查询全部记录
            """
            try:
                info = _prepare_fields(bugid)
                result = run_adp_single(bugid, info["desc"], info["tt"], skip_feishu=True, stop_event=_stop_event)
                has_html = bool((result.get("results") or {}).get("_report_file_token", ""))
                return {"bugid": bugid, "result": result, "has_html": has_html, "info": info}
            except Exception as e:
                return {"bugid": bugid, "result": {"ok": False, "jira_key": bugid, "error": str(e)[:100]},
                        "has_html": False, "info": {"bugid": bugid, "desc": "", "tt": "", "rec": bt_map.get(bugid),
                                                    "bt_desc": "", "bt_time": ""}}

        # ── 保存失败结果到本地 MD ──
        def _save_fail_md(bugid, result):
            """将失败时接口返回内容保存为本地 MD 文档"""
            import os
            from datetime import datetime as _dt
            save_dir = os.path.join("docs", "adp_results", bugid)
            os.makedirs(save_dir, exist_ok=True)
            ts = _dt.now().strftime("%Y%m%d_%H%M%S")
            full_text = result.get("full_text") or ""
            error = result.get("error") or ""
            content = f"# {bugid} 分析失败\n\n"
            content += f"## 错误信息\n\n{error}\n\n"
            content += f"## 返回内容\n\n{full_text[:5000]}\n"
            path = os.path.join(save_dir, f"{bugid}_fail_{ts}.md")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                logger.warning("ADP 保存失败MD失败 %s: %s", bugid, e)
                return ""
            return path

        # ── 写回多维表格 ──
        async def _write_back(bugid, result, rec):
            if not rec:
                return False
            results_dict = result.get("results") or {}
            # 无 ok 且状态不是"无法分析"/"分析失败"时跳过写回
            status = results_dict.get("完成状态", "")
            if not result.get("ok") and status not in ("无法分析", "分析失败"):
                return False
            try:
                write_fields = {k: v for k, v in results_dict.items()
                                if not k.startswith("_") and k != "一致性判定(agent vs 真实情况)"}
                # traceid排查 是 URL 类型字段，必须用 {link, text} 格式，空值则移除
                tid_check = write_fields.get("traceid排查", "")
                if tid_check and isinstance(tid_check, str) and tid_check.startswith("http"):
                    write_fields["traceid排查"] = {"link": tid_check, "text": tid_check}
                else:
                    write_fields.pop("traceid排查", None)
                file_token = results_dict.get("_report_file_token", "")
                if file_token:
                    write_fields["报告链接（分析报告、可观测报告）"] = [{"file_token": file_token}]
                else:
                    # 无 file_token 时移除报告链接字段，避免 URL 字符串写入附件类型字段
                    write_fields.pop("报告链接（分析报告、可观测报告）", None)
                record_id = rec.get("record_id", "")
                if record_id:
                    await loop.run_in_executor(
                        None, lambda: feishu_client.update_bitable_records(
                            app_token, table_id,
                            [{"record_id": record_id, "fields": write_fields}]))
                    return True
            except Exception as e:
                logger.error("ADP lookup 写回失败 %s: %s", bugid, e)
                result["error"] = f"写回失败: {e}"
            return False

        # ── Step 2: 队列式并发执行 ──
        yield f"data: {_json.dumps({'type': 'start', 'total': len(effective_bugids), 'batch_size': batch_size}, ensure_ascii=False)}\n\n"
        pending = list(effective_bugids)
        all_results = []
        total_success = 0
        total_fail = 0
        total_skip = 0
        group_idx = 0

        # 动态并发池：始终保持 batch_size 个任务在跑，一个完成立即补位
        batch_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as pool:
            futures = {}
            next_idx = 0
            # 初始提交 batch_size 个
            for _ in range(min(batch_size, len(effective_bugids))):
                bugid = effective_bugids[next_idx]
                f = pool.submit(_run_one_adp, bugid)
                futures[f] = {"bugid": bugid}
                next_idx += 1
            
            batch_deadline = _time.time() + adp_cfg["timeout"] + 120
            while futures:
                if _stop_event.is_set():
                    for f in futures:
                        f.cancel()
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                # 检查超时的 future
                if _time.time() > batch_deadline:
                    for f in list(futures):
                        f.cancel()
                        bugid = futures.pop(f)["bugid"]
                        rec = bt_map.get(bugid)
                        item = {
                            "jira_key": bugid, "ok": False, "has_html": False,
                            "skipped": False,
                            "results": {"完成状态": "分析失败"}, "error": "ADP 分析超时",
                            "bt_found": rec is not None,
                            "desc_source": "bitable" if rec else "none",
                            "time_source": "bitable" if rec else "none",
                            "text_len": 0, "text_preview": "", "report_path": "",
                            "fail_type": "ADP 分析超时", "file_urls": [],
                        }
                        batch_results.append(item)
                        yield f"data: {_json.dumps({'type': 'item_done', **item}, ensure_ascii=False)}\n\n"
                    break
                # 收集已完成的 future
                done_now = [f for f in futures if f.done()]
                for future in done_now:
                    bugid = futures.pop(future)["bugid"]
                    try:
                        r = future.result()
                    except Exception as e:
                        r = {"bugid": bugid, "result": {"ok": False, "jira_key": bugid, "error": str(e)[:100]},
                             "has_html": False, "info": {"bugid": bugid, "desc": "", "tt": "", "rec": bt_map.get(bugid),
                                                         "bt_desc": "", "bt_time": ""}}
                    info = r.get("info") or {"bugid": bugid, "desc": "", "tt": "", "rec": bt_map.get(bugid),
                                             "bt_desc": "", "bt_time": ""}
                    result = r.get("result", {})
                    has_html = r.get("has_html", False)

                    # 判断是否为"无法分析"（无有效日志附件）→ 不算失败，跳过
                    results_dict = result.get("results") or {}
                    is_skipped = results_dict.get("完成状态") == "无法分析"

                    # 失败（没拿到html且非跳过）：设"分析失败"+ 自动归因并保存本地MD
                    if not has_html and not is_skipped:
                        results_dict["完成状态"] = "分析失败"
                        # 自动归因：分析ADP返回内容判定失败类型
                        if not results_dict.get("分析失败归因"):
                            results_dict["分析失败归因"] = classify_adp_failure(
                                error=result.get("error", ""),
                                full_text=result.get("full_text", ""),
                                attachment_count=result.get("attachment_count", 0))
                        # 失败快照落到本地，并把路径带回前端，失败行也能点「查看完整报告」
                        fail_md = _save_fail_md(bugid, result)
                        if fail_md and not result.get("report_path"):
                            result["report_path"] = fail_md

                    feishu_ok = True
                    ok = result.get("ok", False) and has_html and feishu_ok

                    item = {
                        "jira_key": bugid, "ok": ok, "has_html": has_html,
                        "skipped": is_skipped,
                        "results": results_dict,
                        "error": result.get("error", ""),
                        "bt_found": info["rec"] is not None,
                        "desc_source": "bitable" if info["bt_desc"] else ("api" if info["desc"] else "none"),
                        "time_source": "bitable" if info["bt_time"] else ("api" if info["tt"] else "none"),
                        "fail_type": _adp_fail_type(result),
                        **_adp_text_payload(result),
                        "file_urls": result.get("file_urls", []),
                    }
                    batch_results.append(item)
                    yield f"data: {_json.dumps({'type': 'item_done', **item}, ensure_ascii=False)}\n\n"
                    # 动态补位：只要完成一个，立即从队列取下一个
                    if next_idx < len(effective_bugids):
                        next_bugid = effective_bugids[next_idx]
                        nf = pool.submit(_run_one_adp, next_bugid)
                        futures[nf] = {"bugid": next_bugid}
                        next_idx += 1
                # 还有未完成的，发心跳并等待
                if futures and not done_now:
                    running_keys = [futures[f]["bugid"] for f in futures]
                    yield f"data: {_json.dumps({'type': 'keepalive', 'running': running_keys}, ensure_ascii=False)}\n\n"
                if futures:
                    await asyncio.sleep(5)

        all_results.extend(batch_results)
        total_success = sum(1 for r in batch_results if r["has_html"])
        total_fail = len(batch_results) - total_success
        total_skip = sum(1 for r in batch_results if r.get("skipped"))

        # ADP 执行批次记录（本地CSV）
        try:
            from src.services.adp_ops import save_adp_batch_log as _save_batch_log
            _save_batch_log([{"jira_key": r.get("jira_key", ""), "ok": r.get("ok", False),
                              "error": r.get("error", ""), "fail_type": r.get("fail_type", ""),
                              "traceid": (r.get("results") or {}).get("traceid", ""),
                              "traceid排查": (r.get("results") or {}).get("traceid排查", "")}
                             for r in all_results],
                            total_elapsed=round(_time.time() - _t0, 1))
        except Exception:
            logger.warning("ADP 查找执行批次记录保存失败", exc_info=True)

        # 批量写回飞书多维表格（执行完成后统一写入）
        _lookup_elapsed = round(_time.time() - _t0, 1)
        # 格式化总执行时间
        _elapsed_mins, _elapsed_secs = divmod(int(_lookup_elapsed), 60)
        _elapsed_hours, _elapsed_mins = divmod(_elapsed_mins, 60)
        _elapsed_str = f"{_elapsed_hours}时{_elapsed_mins:02d}分{_elapsed_secs:02d}秒" if _elapsed_hours else f"{_elapsed_mins}分{_elapsed_secs:02d}秒"
        try:
            update_records = []
            for r in all_results:
                bugid = r.get("jira_key", "")
                rec = bt_map.get(bugid)
                if not rec:
                    continue
                results_dict = r.get("results") or {}
                status = results_dict.get("完成状态", "")
                # 只写入有结果或状态为"无法分析"/"分析失败"的记录
                if not r.get("ok") and status not in ("无法分析", "分析失败"):
                    continue
                write_fields = {k: v for k, v in results_dict.items()
                                if not k.startswith("_") and k != "一致性判定(agent vs 真实情况)"}
                # traceid排查 是 URL 类型字段，必须用 {link, text} 格式，空值则移除
                tid_check = write_fields.get("traceid排查", "")
                if tid_check and isinstance(tid_check, str) and tid_check.startswith("http"):
                    write_fields["traceid排查"] = {"link": tid_check, "text": tid_check}
                else:
                    write_fields.pop("traceid排查", None)
                file_token = results_dict.get("_report_file_token", "")
                if file_token:
                    write_fields["报告链接（分析报告、可观测报告）"] = [{"file_token": file_token}]
                else:
                    write_fields.pop("报告链接（分析报告、可观测报告）", None)
                # 总执行时间字段（飞书表格可能没有该列，先不写入）
                write_fields.pop("总执行时间", None)
                record_id = rec.get("record_id", "")
                if record_id and write_fields:
                    update_records.append({"record_id": record_id, "fields": write_fields})
            if update_records:
                await loop.run_in_executor(
                    None, lambda: feishu_client.update_bitable_records(app_token, table_id, update_records))
                logger.info("ADP lookup 批量写回成功: %d 条（总耗时 %s）", len(update_records), _elapsed_str)
        except Exception as e:
            logger.error("ADP lookup 批量写回失败: %s", e)

        yield f"data: {_json.dumps({'type': 'done', 'total': len(effective_bugids), 'success': total_success, 'skip': total_skip, 'fail': max(0, total_fail), 'total_elapsed': round(_time.time() - _t0, 1)}, ensure_ascii=False)}\n\n"

    # 注册作业：/api/jobs 可查进度，/api/jobs/{id}/stop 可单独停止本作业
    from src.core.job_registry import JOBS as _JOBS
    from src.api.routes.jobs import job_stream as _job_stream
    from src.api.routes.shared import adp_lookup_stop_event as _job_stop
    _job = _JOBS.create("adp_lookup", "ADP 表格查找作业")
    return StreamingResponse(_job_stream(_job, event_generator, _job_stop), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/test/adp_lookup/stop")
def stop_adp_lookup():
    """停止 ADP 表格查找执行"""
    from src.api.routes.shared import adp_lookup_stop_event as _stop_event, ok
    _stop_event.set()
    logger.info("收到 ADP lookup 停止信号")
    return _ok(None, "停止信号已发送")

