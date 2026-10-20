"""Testing routes - test endpoints"""
from fastapi import APIRouter, Request, Body, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from datetime import datetime
import random

from src import pipeline
from src.config import PROJECT_ROOT, get_path, load_config, setup_logger
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
    ok as _ok,
)
from fastapi.responses import JSONResponse as _JSONResponse


def _fail(message: str, extra: dict = None):
    data = {"ok": False, "message": message}
    if extra:
        data.update(extra)
    return _JSONResponse(content=data, status_code=200)


logger = setup_logger("web.testing")
router = APIRouter()


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
async def test_batch_ai_csv_files():
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
        issues = jira_client.search_issues(jql, max_results=5000)
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
        rows = []; failed = []
        if is_jql:
            try:
                issues = jira_client.search_issues(raw, max_results=500)
                # 逐个拉取详情以拿到根因字段（search_issues 只返回基础字段）
                for i in issues:
                    bugid = (i.get("key") or "").strip()
                    if not bugid:
                        continue
                    try:
                        detail = jira_client.fetch_issue(bugid)
                        fields = detail.get("fields") or {}
                        rows.append({
                            "key": bugid,
                            "summary": (fields.get("summary") or (i.get("fields") or {}).get("summary") or "")[:200] or "（无概要）",
                            "status": ((fields.get("status") or {}).get("name") or "") or "-",
                            "created": (fields.get("created") or "")[:10] or "-",
                            "root_cause": jira_client.extract_rootcause(detail) or "（未填写）",
                        })
                    except Exception as e:
                        failed.append({"key": bugid, "error": str(e)[:120]})
            except Exception as e:
                return _fail(f"JQL 查询失败: {e}")
        else:
            import re
            keys = [k.upper().strip() for k in re.split(r"[,，;；\s]+", raw) if k.strip()]
            seen = set(); dedup = []
            for k in keys:
                if k not in seen:
                    seen.add(k); dedup.append(k)
            for bugid in dedup:
                try:
                    issue = jira_client.fetch_issue(bugid)
                    fields = issue.get("fields") or {}
                    rows.append({
                        "key": (issue.get("key") or bugid).strip(),
                        "summary": (fields.get("summary") or "")[:200] or "（无概要）",
                        "status": ((fields.get("status") or {}).get("name") or "") or "-",
                        "created": (fields.get("created") or "")[:10] or "-",
                        "root_cause": jira_client.extract_rootcause(issue) or "（未填写）",
                    })
                except Exception as e:
                    failed.append({"key": bugid, "error": str(e)[:120]})
        msg = f"查询成功 {len(rows)} 条" + (f"，失败 {len(failed)} 条" if failed else "")
        return _ok({"total": len(rows) + len(failed), "success": len(rows),
                    "failed": len(failed), "mode": "jql" if is_jql else "keys",
                    "rows": rows, "errors": failed}, msg)
    except Exception as e:
        logger.error("Jira 查询失败: %s", e)
        return _fail(str(e))


@router.post("/api/test/batch_ai_extract_times/stop", response_model=ApiResponse)
async def stop_batch_ai_extract_times():
    """触发批量提取停止信号（优雅停止：当前条目完成后停止后续）"""
    import os, re, json
    from src.api.routes.shared import batch_extract_stop_event as _batch_extract_stop_event
    _batch_extract_stop_event.set()
    logger.info("收到批量提取停止信号，当前条目完成后将停止后续处理")
    return ok(None, "停止信号已发送，当前条目完成后停止")


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
        _batch_save_trigger_times_to_cloud, _save_trigger_time_to_csv,
    )
    from src.services.report_ops import _load_bitable_success_jiras
    from src.services.server_legacy import _diag_extract_time_from_video_simple, _has_gmlogger_logs, _diag_extract_time_from_images
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
                                tt = _jc.extract_trigger_time_from_issue(issue, skip_attachment=True)
                                if tt:
                                    sources[key] = "新提取"
                        else:
                            # 默认不勾选：评论 → 视频 → 图片
                            tt = _jc.extract_trigger_time_from_issue(issue, skip_attachment=True)
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
                    async def _sem_process(key):
                        async with sem:
                            if interrupted or _batch_extract_stop_event.is_set() or stop_event.is_set():
                                return key, "skipped", ""
                            return await _process_one(key)
                    tasks = [asyncio.ensure_future(_sem_process(k)) for k in need_fetch]
                    for coro in asyncio.as_completed(tasks):
                        if _batch_extract_stop_event.is_set() or stop_event.is_set():
                            interrupted = True
                            for t in tasks:
                                t.cancel()
                            break
                        if await request.is_disconnected():
                            interrupted = True
                            for t in tasks:
                                t.cancel()
                            break
                        key, status, tt_val = await coro
                        if status == "skipped" or status == "stopped":
                            continue
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
                            try:
                                batch_items = dict(_write_buffer)
                                await loop.run_in_executor(None, _batch_save_trigger_times_to_cloud, batch_items)
                                for bid, btt in _write_buffer:
                                    _save_trigger_time_to_csv(bid, btt)
                                logger.info("并行批量写入触发时间: %d 条", len(_write_buffer))
                            except Exception as e:
                                logger.warning("并行批量写入触发时间失败: %s", e)
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
                            try:
                                batch_items = dict(_write_buffer)
                                await loop.run_in_executor(None, _batch_save_trigger_times_to_cloud, batch_items)
                                for bid, btt in _write_buffer:
                                    _save_trigger_time_to_csv(bid, btt)
                                logger.info("批量写入触发时间: %d 条", len(_write_buffer))
                            except Exception as e:
                                logger.warning("批量写入触发时间失败: %s", e)
                            _write_buffer.clear()
            # 最终批量写入缓冲区剩余数据
            if _write_buffer:
                try:
                    batch_items = dict(_write_buffer)
                    await loop.run_in_executor(None, _batch_save_trigger_times_to_cloud, batch_items)
                    for bid, btt in _write_buffer:
                        _save_trigger_time_to_csv(bid, btt)
                    logger.info("最终批量写入触发时间: %d 条", len(_write_buffer))
                except Exception as e:
                    logger.warning("最终批量写入触发时间失败: %s", e)
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


@router.post("/api/test/batch_ai_filter", response_model=ApiResponse)
async def test_batch_ai_filter(request: Request):
    """步骤3：查询多维表格，过滤掉已存在的记录。支持多种过滤模式组合"""
    import os, re, json
    body = await request.json() or {}
    keys = body.get("keys") or []
    filter_all = body.get("filter_all", False)
    filter_pc_only = body.get("filter_pc_only", False)  # 仅过滤触发来源为PC的记录
    filter_online_only = body.get("filter_online_only", False)  # 仅过滤线上的记录
    filter_ai_preliminary = body.get("filter_ai_preliminary", False)  # 过滤AI初步分析结果
    if not keys:
        return _fail("候选列表为空，请先执行步骤1")
    # 查询多维表格，获取应排除的 jira 号
    exclude_keys = set()
    try:
        import asyncio
        from src.clients import feishu_client
        loop = asyncio.get_event_loop()
        records = await loop.run_in_executor(None, feishu_client.list_bitable_records,
                                             load_config().get("feishu_bitable", {}).get("app_token", ""),
                                             load_config().get("feishu_bitable", {}).get("table_id", ""))
        bugid_field = load_config().get("feishu_bitable", {}).get("bugid_field", "jira号")
        for rec in records:
            fields = rec.get("fields", {})
            field_value = fields.get(bugid_field, "")
            if isinstance(field_value, list):
                field_value = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in field_value)
            elif isinstance(field_value, dict):
                field_value = field_value.get("text", str(field_value))
            jira_key = str(field_value).strip()
            if not jira_key:
                continue
            # 按来源过滤：PC/线上分别判断是否排除（正确+通用失败）
            trigger_source = _bitable_text(fields.get("触发来源", ""))
            is_pc = trigger_source == "jira_analyze"
            if filter_pc_only and filter_online_only:
                # 两个都勾选：排除PC和线上中的正确+通用失败记录
                if not _is_bitable_excluded(fields, bugid_field):
                    continue
            elif filter_pc_only:
                # 仅PC：只处理PC来源记录，排除其中的正确+通用失败
                if not is_pc:
                    continue
                if not _is_bitable_excluded(fields, bugid_field):
                    continue
            elif filter_online_only:
                # 仅线上：只处理线上来源记录，排除其中的正确+通用失败
                if is_pc:
                    continue
                if not _is_bitable_excluded(fields, bugid_field):
                    continue
            # 排除逻辑：智能过滤排除已成功+无效审核
            if not filter_all:
                if _is_bitable_excluded(fields, bugid_field):
                    exclude_keys.add(jira_key)
            else:
                exclude_keys.add(jira_key)
        mode_parts = []
        if filter_all:
            mode_parts.append("所有已存在")
        if not filter_pc_only and not filter_online_only and not filter_all:
            mode_parts.append("成功+无需重试")
        if filter_pc_only and filter_online_only:
            mode_parts.append("PC+线上正确和通用失败")
        else:
            if filter_pc_only:
                mode_parts.append("PC正确+通用失败")
            if filter_online_only:
                mode_parts.append("线上正确+通用失败")
        mode_desc = "+".join(mode_parts)
        logger.info("多维表格重复过滤(%s): 排除记录 %d 条", mode_desc, len(exclude_keys))
    except Exception as e:
        logger.warning("多维表格重复过滤查询失败（跳过此检查）: %s", e)
    # 过滤候选列表
    filtered = [k for k in keys if k not in exclude_keys]
    # 过滤AI初步分析结果：查询 Jira REST API customfield_13714
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
            logger.info("AI初步分析过滤(customfield_13714): 排除 %d 条", len(ai_exclude))
            filtered = [k for k in filtered if k not in ai_exclude]
            exclude_keys.update(ai_exclude)
    removed = len(keys) - len(filtered)
    if not filtered:
        return _fail(f"所有候选均已被过滤（共过滤 {removed} 条）")
    bitable_removed = len(exclude_keys) - len(ai_exclude)
    filter_desc = f"候选 {len(keys)} 条，多维表格过滤 {bitable_removed} 条"
    if ai_exclude:
        filter_desc += f"，AI字段过滤 {len(ai_exclude)} 条"
    filter_desc += f"，剩余 {len(filtered)} 条"
    return _ok({"filtered": filtered, "removed": removed, "total": len(keys),
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
    # 扫描 docs/ 下所有 CSV 已测试的 jira 号（含历史批量文件）
    tested = _load_all_doc_jira_keys()
    # 排除 docs/ 已测试记录（步骤3已过滤多维表格成功记录）
    available = [k for k in keys if k not in tested]
    if not available:
        return _fail(f"所有候选 bug 均已测试过（已测试 {len(tested)} 条）")
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
                    issue = _jc.fetch_issue(k)
                    # gmlogger 前置检查：无 gmlogger 附件直接跳过（与批量提取保持一致）
                    attachments = (issue.get("fields") or {}).get("attachment") or []
                    if not _has_gmlogger_logs(attachments, k):
                        logger.info("抽样提取: %s 无gmlogger附件，跳过", k)
                        extract_failed += 1
                        continue
                    # 评论/字段提取优先（文本提取准确率最高且速度最快）
                    tt = _jc.extract_trigger_time_from_issue(issue, skip_attachment=True)
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
                    _batch_save_trigger_times_to_cloud(new_to_cloud)
                    new_to_cloud.clear()
                    _cloud_flush_counter = 0
    # 循环结束后保存剩余未上传的到云端
    if new_to_cloud:
        _batch_save_trigger_times_to_cloud(new_to_cloud)
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
    bitable = feishu_client.list_bitable_records(app_token, table_id)
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
            feishu_client.update_bitable_records(app_token, table_id, updates[i:i + 100])
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
        field_defs = feishu_client.list_bitable_fields(app_token, table_id)
        field_name_map = {fd.get("field_name", ""): fd.get("field_name", "") for fd in field_defs}
        field_type_map = {fd.get("field_name", ""): fd.get("type", 0) for fd in field_defs}

        # 无 bugid 时：返回全量记录（供数据看板展示）
        if not bugid:
            records = feishu_client.list_bitable_records(app_token, table_id)
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
        records = feishu_client.list_bitable_records(app_token, table_id)
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
                        doc_result = feishu_client.create_docx_document(doc_title, doc_content)
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

        feishu_client.update_bitable_records(app_token, table_id, update_records)
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
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("请输入 bugid")
    try:
        cfg = load_config()["jira_api"]
        is_mock = cfg.get("mock", False)
        # 调用 Jira 接口获取完整响应
        raw_response = jira_client.fetch_issue(bugid)
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
        issue = jira_client.fetch_issue(bugid)
        # gmlogger 前置检查
        attachments = (issue.get("fields") or {}).get("attachment") or []
        if not _has_gmlogger_logs(attachments, bugid):
            return _fail("无gmlogger附件，跳过提取")
        # 评论/字段提取优先（文本提取准确率最高且速度最快）
        trigger_time = jira_client.extract_trigger_time_from_issue(issue, skip_attachment=True)
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
        # 提取成功后保存到云端+本地
        _save_trigger_time_to_cloud(bugid, trigger_time)
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
        doc_result = feishu_client.create_docx_document(title, content)
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
        records = feishu_client.list_bitable_records(app_token, table_id)
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
async def test_gmlogger_rescan(request: Request):
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
                feishu_client.update_bitable_records(app_token, table_id, batch)
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
    """置信度批量写入：填充 rootcause + AI问题分析根因，对比语义相似度写回置信度

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
            field_defs = feishu_client.list_bitable_fields(app_token, table_id)
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
            records = feishu_client.list_bitable_records(app_token, table_id)
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

        def _write_one(record_id, fields_to_write):
            """单条写入，失败时返回错误信息，不中断流程"""
            try:
                feishu_client.update_bitable_records(app_token, table_id,
                                                     [{"record_id": record_id, "fields": fields_to_write}])
                return ""
            except Exception as e:
                return str(e)[:120]
        
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

    return StreamingResponse(generate(), media_type="text/event-stream")


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
            feishu_client.update_bitable_records(app_token, table_id,
                                                 [{"record_id": record_id, "fields": fields}])
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
async def test_prod_csv_files():
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
            records = feishu_client.list_bitable_records(app_token, table_id)
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
            bt_records = feishu_client.list_bitable_records(
                cfg_fb.get("app_token", ""), cfg_fb.get("table_id", ""))
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
                            _save_trigger_time_to_cloud(bugid, tt)
                        elif tt is None:
                            pass  # 无gmlogger，不写空标签到云端（下次仍可重试）
                        else:
                            _save_trigger_time_to_cloud(bugid, "")
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


@router.post("/api/test/comment_compare", response_model=ApiResponse)
async def test_comment_compare(request: Request):
    """功能测试2：评论提取与对比（单条），返回评论原文、提取步骤及双重比对结果"""
    import os, re, json
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("bugid 不能为空")
    try:
        result = _compare_single_bug(bugid, body.get("trigger_time") or None)
        return _ok(result, "评论提取与对比完成")
    except Exception as e:
        logger.error("评论对比功能测试失败: %s", e)
        return _fail(str(e))


@router.post("/api/test/comment_compare_strategies", response_model=ApiResponse)
async def comment_compare_strategies(request: Request):
    """评论分析侧重点对比：对同一 Jira 用多种 prompt 策略各跑一次评论分析，并列展示"""
    import os, re, json
    from src.core.filter import COMMENT_ANALYSIS_STRATEGIES, summarize_comments, generate_comment_analysis
    from src.clients import jira_client, diana_client as _dc
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("bugid 不能为空")
    try:
        # 获取评论和 AI 结论（只执行一次，所有策略共用）
        issue = jira_client.fetch_issue(bugid)
        comments = jira_client.extract_comments(issue)
        summaries = summarize_comments(comments)
        # 获取 AI 日志分析结论（优先本地文档，回退从多维表格查飞书链接再下载）
        ai_conclusion = ""
        try:
            ai_content = pipeline._get_ai_report_content(bugid, "")
            ai_conclusion = doc_generator.parse_conclusion(ai_content) or ""
        except Exception:
            # 本地无文档，从多维表格查找飞书链接
            feishu_link = ""
            try:
                from src.clients import feishu_client
                cfg_bitable = load_config().get("feishu_bitable", {})
                at = cfg_bitable.get("app_token", "")
                tid = cfg_bitable.get("table_id", "")
                bf = cfg_bitable.get("bugid_field", "jira号")
                lf = "AI分析结果(飞书链接)"
                if at and tid:
                    records = feishu_client.list_bitable_records(at, tid)
                    for rec in records:
                        fields = rec.get("fields", {})
                        bid_val = str(fields.get(bf, ""))
                        if bid_val == bugid:
                            link_val = fields.get(lf, "")
                            if isinstance(link_val, dict):
                                link_val = link_val.get("link", "") or link_val.get("text", "")
                            feishu_link = str(link_val).strip() if link_val else ""
                            break
            except Exception as e:
                logger.warning("从多维表格查找飞书链接失败: %s", e)
            if feishu_link:
                try:
                    ai_content = pipeline._get_ai_report_content(bugid, feishu_link)
                    ai_conclusion = doc_generator.parse_conclusion(ai_content) or ""
                except Exception as e:
                    logger.warning("bugid=%s 通过飞书链接下载AI报告失败: %s", bugid, e)
        # 提取 Jira 根因
        bug_rootcause = ""
        try:
            bug_rootcause = jira_client.extract_rootcause(issue) or ""
        except Exception:
            pass
        # 对每种策略各跑一次评论分析
        results = []
        for key, strategy in COMMENT_ANALYSIS_STRATEGIES.items():
            try:
                analysis = generate_comment_analysis(
                    summaries, ai_conclusion, style_instruction=strategy["instruction"])
                # 从分析结果提取排查结论段落
                conclusion_text = ""
                if analysis:
                    in_section = False
                    for line in analysis.split("\n"):
                        if "## 排查结论" in line or "### 排查结论" in line:
                            in_section = True
                            continue
                        if in_section and line.startswith("##"):
                            break
                        if in_section and line.strip():
                            conclusion_text += line.strip() + " "
                    conclusion_text = conclusion_text.strip()[:120]
                # 用 Diana 生成 8-20 字的表格结论
                table_conclusion = ""
                if conclusion_text:
                    try:
                        simplify_prompt = (
                            f"用一句话（8到20字）概括以下排查结论，偏bug分析方向，必须是完整语义，只输出概括本身：\n"
                            f"{conclusion_text}\n概括："
                        )
                        tc = _dc._llm_chat(simplify_prompt, max_tokens=50, timeout=15)
                        if tc:
                            from src.pipeline import _strip_conclusion_prefix
                            table_conclusion = _strip_conclusion_prefix(tc.strip().rstrip('。.'))
                    except Exception:
                        pass
                results.append({
                    "key": key, "label": strategy["label"],
                    "instruction": strategy["instruction"],
                    "analysis": analysis or "（生成失败）",
                    "bugid": bugid,
                    "root_cause": bug_rootcause[:100] if bug_rootcause else "（未提取）",
                    "table_conclusion": table_conclusion or conclusion_text[:40] or "（无）",
                    "has_ai_conclusion": bool(ai_conclusion),
                    "confidence_assessment": (
                        "高" if (analysis and ai_conclusion and conclusion_text)
                        else "中" if analysis and not analysis.startswith("（")
                        else "低"
                    ),
                })
            except Exception as e:
                results.append({
                    "key": key, "label": strategy["label"],
                    "instruction": strategy["instruction"],
                    "analysis": f"（异常: {str(e)[:60]}）",
                    "bugid": bugid, "root_cause": "（异常）",
                    "table_conclusion": "（异常）", "has_ai_conclusion": False,
                    "confidence_assessment": "低",
                })
        # 读取当前已保存的风格偏好
        cfg = load_config()
        current_style = cfg.get("comment_analysis", {}).get("style_keywords", "")
        return _ok({"strategies": results, "current_style": current_style,
                    "comments_count": len(comments), "summaries_count": len(summaries)},
                   f"对比完成: {len(results)} 种策略, {len(comments)} 条评论")
    except Exception as e:
        logger.error("评论分析侧重点对比失败: %s", e, exc_info=True)
        return _fail(f"对比失败: {e}")


@router.post("/api/test/save_style_preference", response_model=ApiResponse)
async def save_style_preference(request: Request):
    """保存评论分析风格偏好到配置"""
    import os, re, json
    body = await request.json() or {}
    strategy_key = str(body.get("strategy_key", "")).strip()
    instruction = str(body.get("instruction", "")).strip()
    if not instruction:
        return _fail("instruction 不能为空")
    try:
        cfg = load_config()
        if "comment_analysis" not in cfg:
            cfg["comment_analysis"] = {}
        cfg["comment_analysis"]["style_keywords"] = instruction
        cfg["comment_analysis"]["strategy_key"] = strategy_key
        with open(cfg_module.CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        load_config(cfg_module.CONFIG_PATH)
        logger.info("评论分析风格偏好已保存: key=%s, keywords=%s", strategy_key, instruction[:40])
        return _ok({"strategy_key": strategy_key, "style_keywords": instruction},
                   f"风格偏好已保存: {instruction[:40]}")
    except Exception as e:
        logger.error("保存风格偏好失败: %s", e)
        return _fail(f"保存失败: {e}")


@router.post("/api/test/upload_bug_file", response_model=ApiResponse)
async def upload_bug_file(file: UploadFile = File(None)):
    """上传 bug 单数据文件（CSV/Excel），解析后缓存，返回 file_id 供批量对比引用"""
    import os, re, json
    from src.services.server_legacy import _uploaded_files
    from src.clients import bug_source
    if not file or not file.filename:
        return _fail("未找到上传文件或文件名为空")
    try:
        content = await file.read()
        rows = bug_source.parse_uploaded_file(content, file.filename)
        if not rows:
            return _fail("文件中未找到有效数据或缺少 bugid 列")
        file_id = f"file_{len(_uploaded_files) + 1}"
        _uploaded_files[file_id] = rows
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
async def check_endpoints(request: Request):
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
            records = feishu_client.list_bitable_records(app_token, table_id, view_id)
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
async def online_followup_compare(request: Request):
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
async def auto_detect_stop():
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
            if _server._auto_detect_stop:
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
                if _server._auto_detect_stop:
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
                        _save_trigger_time_to_cloud(bugid, tt)
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
                if _server._auto_detect_stop:
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
async def regression_stop():
    """停止回归执行"""
    from src.api.routes.shared import batch_extract_stop_event
    batch_extract_stop_event.set()
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
        from src.api.routes.shared import batch_extract_stop_event as _stop_event
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

    return StreamingResponse(event_generator(), media_type="text/event-stream",
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
        records = feishu_client.list_bitable_records(app_token, table_id)
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
        result = feishu_client.create_docx_document(doc_title, md_content, folder_token)
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
        records = feishu_client.list_bitable_records(app_token, table_id)
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
        records = feishu_client.list_bitable_records(app_token, table_id)
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
        feishu_client.batch_delete_records(app_token, table_id, record_ids_to_delete)
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
            ok = _batch_save_trigger_times_to_cloud(to_write)
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
        content = await file.read()
        filename = file.filename.lower()
        lines = []
        file_info = []  # 记录解压后的文件信息

        if filename.endswith(".zip"):
            # ZIP 压缩包：解压后读取所有文本文件
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    name_lower = name.lower()
                    if any(name_lower.endswith(ext) for ext in (".log", ".txt", ".md", ".csv")):
                        try:
                            text = zf.read(name).decode("utf-8", errors="replace")
                            file_lines = text.splitlines()
                            file_info.append({"name": name, "lines": len(file_lines)})
                            lines.extend(file_lines)
                        except Exception:
                            pass
        elif filename.endswith((".tar.gz", ".tgz")):
            # tar.gz 压缩包
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    name_lower = member.name.lower()
                    if any(name_lower.endswith(ext) for ext in (".log", ".txt", ".md", ".csv")):
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
            # 单个 .gz 文件
            text = gzip.decompress(content).decode("utf-8", errors="replace")
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
async def get_ai_report(bugid: str):
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
    # 远程下载
    url = f"http://10.22.126.133:8001/api/logs/debug/{bugid}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return _fail(f"接口返回 status={resp.status_code}")
        content = resp.text
        if not content.strip():
            return _fail("报告内容为空")
        # 保存到本地
        os.makedirs(docs_dir, exist_ok=True)
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(content)
        return _ok({
            "content": content, "bugid": bugid,
            "file_path": local_path, "dir_path": docs_dir, "source": "remote",
        }, "已下载并保存到本地")
    except httpx.ConnectTimeout:
        return _fail("连接超时，AI日志分析服务不可达")
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
async def open_dir(path: str = ""):
    """打开本地目录（xdg-open）"""
    import subprocess, os
    if not path or not os.path.isdir(path):
        return _fail(f"目录不存在: {path}")
    try:
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
        content = await file.read()
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
        from src.api.routes.shared import batch_extract_stop_event as _stop_event
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

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ========== 功能13：配置参数调优 ==========


