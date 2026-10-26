"""Troubleshoot routes - 10 endpoints: 排查诊断

路由层只负责 HTTP 解析和响应格式化，业务逻辑委托给 troubleshoot_service。
"""
from fastapi import APIRouter

from src.api.routes.shared import ok, fail
from src.schemas.common import ApiResponse
from src.schemas.troubleshoot import (
    RecordsQueryRequest, DirectQueryRequest, SearchJiraRequest,
    CancelDiagRequest, DiagnoseRequest, UpdateCacheRequest,
    BatchWriteReviewRequest, ExportIssuesRequest,
    BatchPreClassifyRequest, SendToDeveloperRequest,
)

router = APIRouter()


@router.post("/api/troubleshoot/records", response_model=ApiResponse)
def troubleshoot_records(req: RecordsQueryRequest):
    from src.services import troubleshoot_service as svc
    try:
        result = svc.query_records(
            after_time=req.after_time.strip(),
            result_filter=req.result_filter.strip(),
            source_filter=req.source_filter.strip(),
            dedup=req.dedup,
            no_manual_review=req.no_manual_review,
        )
        return ok({"rows": result["rows"], "count": result["count"]}, result["message"])
    except ValueError as e:
        return fail(str(e))
    except Exception as e:
        return fail(f"多维表格查询失败: {e}")


@router.post("/api/troubleshoot/direct", response_model=ApiResponse)
def troubleshoot_direct(req: DirectQueryRequest):
    from src.services import troubleshoot_service as svc
    bugids = [b.strip().upper() for b in req.bugids if b.strip()]
    if not bugids:
        return fail("请输入Jira号")
    try:
        result = svc.query_by_bugids(bugids)
        return ok(
            {"rows": result["rows"], "count": result["count"], "not_found": result["not_found"]},
            result["message"],
        )
    except ValueError as e:
        return fail(str(e))
    except Exception as e:
        return fail(f"多维表格查询失败: {e}")


@router.post("/api/troubleshoot/search_jira", response_model=ApiResponse)
def troubleshoot_search_jira(req: SearchJiraRequest):
    from src.services import troubleshoot_service as svc
    keyword = req.keyword.strip().upper()
    if not keyword:
        return fail("请输入 Jira 号")
    try:
        result = svc.search_by_keyword(keyword)
        return ok({"rows": result["rows"], "count": result["count"]}, result["message"])
    except ValueError as e:
        return fail(str(e))
    except Exception as e:
        return fail(f"多维表格查询失败: {e}")


@router.post("/api/troubleshoot/cancel_diag", response_model=ApiResponse)
def troubleshoot_cancel_diag(req: CancelDiagRequest):
    from src.api.routes.shared import diag_cancel
    bugids = req.bugids
    if bugids:
        for bugid in bugids:
            diag_cancel[bugid] = True
        return ok(None, f"已发送取消信号: {', '.join(bugids)}")
    for bugid in list(diag_cancel):
        diag_cancel[bugid] = True
    return ok(None, f"已发送全部取消信号: {len(diag_cancel)} 个")


@router.post("/api/troubleshoot/diagnose", response_model=ApiResponse)
def troubleshoot_diagnose(req: DiagnoseRequest):
    import concurrent.futures as _futures
    from src.api.routes.shared import (
        ok as _ok,
        fail as _fail,
        diag_cancel,
        get_diag_executor as _get_diag_executor,
        _DIAG_TIMEOUT_SECONDS,
    )
    from src.services.server_legacy import (
        _load_diagnose_cache,
        _save_diagnose_cache,
        _save_video_time_cache,
        _load_video_time_cache,
        _troubleshoot_diagnose_impl,
        _SKIP_ANALYSIS_CATEGORIES,
    )
    from src.services.troubleshoot_service import _diag_pre_classify
    from src.services.report_ops import _generate_troubleshoot_report
    bugid = req.bugid.strip()
    err_msg = req.err_msg.strip()
    problem_time = req.problem_time.strip()
    done_time = req.done_time.strip()
    force = req.force
    skip_video_cache = req.skip_video_cache
    if not bugid:
        return fail("bugid 不能为空")
    # 预归类保护：错误信息命中跳过类别时直接返回，不执行诊断
    if not force:
        _pre_cat = ""
        if not err_msg or err_msg == "服务有报错":
            _pre_cat = "服务关闭"
        else:
            _pre_cat = _diag_pre_classify(err_msg)
        if _pre_cat and _pre_cat in _SKIP_ANALYSIS_CATEGORIES:
            _pre_report = _generate_troubleshoot_report(bugid, _pre_cat, err_msg, f"预归类：{_pre_cat}")
            _pre_result = {
                "bugid": bugid, "category": _pre_cat, "needs_analysis": False,
                "done_time": done_time, "problem_time": problem_time,
                "err_msg": err_msg[:200], "report": _pre_report,
                "detail": f"根据失败原因预归类：{_pre_cat}",
                "archive_files": [], "verify_status": "", "suggested_time": "",
            }
            _save_diagnose_cache(bugid, _pre_result)
            return ok(_pre_result, f"{bugid} 预归类跳过：{_pre_cat}")
    if skip_video_cache:
        cache = _load_video_time_cache()
        prefix = f"{bugid}:"
        removed = [k for k in cache if k.startswith(prefix)]
        for k in removed:
            del cache[k]
        if removed:
            _save_video_time_cache()
    diag_cancel[bugid] = False
    try:
        if not force:
            cached = _load_diagnose_cache(bugid)
            if cached is not None:
                if done_time:
                    cached["done_time"] = done_time
                # 注入 needs_analysis 标识
                if "category" in cached:
                    cached["needs_analysis"] = cached["category"] not in _SKIP_ANALYSIS_CATEGORIES
                return ok(cached, f"{bugid} 诊断结果（本地缓存）")
        executor = _get_diag_executor()
        future = executor.submit(_troubleshoot_diagnose_impl, bugid, err_msg, problem_time, done_time, force=force)
        try:
            return future.result(timeout=_DIAG_TIMEOUT_SECONDS)
        except _futures.TimeoutError:
            diag_cancel[bugid] = True
            return fail(f"{bugid} 诊断超时（超过{_DIAG_TIMEOUT_SECONDS}秒），请稍后重试")
    finally:
        if not diag_cancel.get(bugid):
            diag_cancel.pop(bugid, None)


@router.post("/api/troubleshoot/update_cache", response_model=ApiResponse)
def troubleshoot_update_cache(req: UpdateCacheRequest):
    from src.api.routes.shared import ok as _ok, fail as _fail
    from src.services.server_legacy import _load_diagnose_cache, _save_diagnose_cache
    bugid = req.bugid.strip()
    if not bugid:
        return fail("bugid 不能为空")
    cached = _load_diagnose_cache(bugid) or {}
    if req.correction_time is not None:
        cached["correction_time"] = req.correction_time
        cached["verify_status"] = "corrected"
        cached["suggested_time"] = req.correction_time
    if req.correction_note is not None:
        cached["correction_note"] = req.correction_note
    if req.human_reason is not None:
        if not isinstance(cached.get("report"), dict):
            cached["report"] = {}
        cached["report"]["human_reason"] = req.human_reason
    if req.category is not None:
        new_category = req.category
        cached["category"] = new_category
        if not isinstance(cached.get("report"), dict):
            cached["report"] = {}
        cached["report"]["final_category"] = new_category
    _save_diagnose_cache(bugid, cached)
    return ok(None, f"{bugid} 诊断缓存已更新")


@router.post("/api/troubleshoot/batch_write_review", response_model=ApiResponse)
def troubleshoot_batch_write_review(req: BatchWriteReviewRequest):
    from src.services import troubleshoot_service as svc
    items = [item.model_dump() for item in req.items]
    only_empty_review = req.only_empty_review
    if not items:
        return fail("待写入列表为空")
    try:
        result = svc.batch_write_review(items, only_empty_review=only_empty_review)
        return ok(
            {"matched": result["matched"], "unmatched": result["unmatched"],
             "skipped": result["skipped"], "updated": result["updated"]},
            result["message"],
        )
    except ValueError as e:
        return fail(str(e))


@router.post("/api/troubleshoot/export_trigger_time_issues", response_model=ApiResponse)
def troubleshoot_export_trigger_time_issues(req: ExportIssuesRequest):
    from src.services import troubleshoot_service as svc
    from src.services.server_legacy import _TRIGGER_ISSUE_FOLDER_TOKEN
    items = req.items if isinstance(req.items, list) else [item if isinstance(item, dict) else item.model_dump() for item in req.items]
    if not items:
        return fail("无触发时间问题记录")
    result = svc.export_trigger_time_issues(items, folder_token=_TRIGGER_ISSUE_FOLDER_TOKEN)
    return ok(
        {"count": result["count"], "csv_path": result["csv_path"], "cloud_url": result["cloud_url"]},
        result["message"],
    )


@router.post("/api/troubleshoot/batch_pre_classify", response_model=ApiResponse)
def troubleshoot_batch_pre_classify(req: BatchPreClassifyRequest):
    """批量预归类：根据错误信息和人工审核结果快速分类，跳过无需深度分析的记录"""
    from src.services import troubleshoot_service as svc
    try:
        result = svc.batch_pre_classify(req.records)
        return ok({"skip": result["skip"], "need_analysis": result["need_analysis"]}, result["message"])
    except ValueError as e:
        return fail(str(e))


@router.post("/api/troubleshoot/send_to_developer", response_model=ApiResponse)
def troubleshoot_send_to_developer(req: SendToDeveloperRequest):
    """将自动归类记录通过飞书机器人发送给后端开发者"""
    from src.services import troubleshoot_service as svc
    try:
        result = svc.send_to_developer(req.records)
        return ok(None, result["message"])
    except ValueError as e:
        return fail(str(e))
