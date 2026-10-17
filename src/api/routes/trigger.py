"""触发时间管理路由：批量读取、更新、重新提取、云端缓存批量操作"""
import asyncio
import os

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.config import PROJECT_ROOT, load_config, setup_logger
from src.schemas.common import ApiResponse
from src.schemas.trigger import (
    BugidListRequest, UpdateTriggerTimeRequest, BatchUpdateRequest,
    ReExtractScanRequest, CacheBatchScanRequest, CacheBatchExtractRequest,
)

logger = setup_logger("web.trigger")
router = APIRouter()


@router.post("/api/trigger_time/batch_read", response_model=ApiResponse)
async def batch_read_trigger_times(req: BugidListRequest):
    """批量读取指定 jira 号的当前触发时间"""
    from src.services.trigger_ops import (
        _load_trigger_times_from_cloud, _save_trigger_time_to_csv,
        _batch_save_trigger_times_to_cloud,
    )
    from src.api.routes.shared import ok as _ok, fail as _fail
    bugids = req.bugids
    if not bugids:
        return _fail("请输入 jira 号列表")
    local_times = _load_trigger_times_from_cloud()
    result, extracted_count, batch_to_cloud = [], 0, {}
    for bugid in bugids:
        bugid = bugid.strip()
        if not bugid:
            continue
        current_time = local_times.get(bugid, "")
        if not current_time:
            try:
                from src.clients import jira_client as _jc
                loop = asyncio.get_event_loop()
                issue = await loop.run_in_executor(None, _jc.fetch_issue, bugid)
                tt = await loop.run_in_executor(None, _jc.extract_trigger_time_from_issue, issue)
                if tt:
                    current_time = tt
                    _save_trigger_time_to_csv(bugid, tt)
                    batch_to_cloud[bugid] = tt
                    extracted_count += 1
            except Exception as e:
                logger.warning("批量读取触发时间-提取失败 %s: %s", bugid, e)
        result.append({"bugid": bugid, "current_time": current_time})
    if batch_to_cloud:
        _batch_save_trigger_times_to_cloud(batch_to_cloud)
    hit_count = sum(1 for r in result if r["current_time"])
    return _ok({"rows": result, "total": len(result), "hit": hit_count},
               f"查询完成：{len(result)} 个 Jira 号，{hit_count} 个有记录（本地命中 {hit_count - extracted_count}，新提取 {extracted_count}）")


@router.post("/api/trigger_time/update", response_model=ApiResponse)
async def update_trigger_time(req: UpdateTriggerTimeRequest):
    """修改指定bugid的触发时间"""
    from src.api.routes.shared import (
        ok as _ok,
        fail as _fail,
    )
    from src.services.report_ops import (
        _load_diagnose_cache,
        _save_diagnose_cache,
    )
    from src.services.trigger_ops import _save_trigger_time_to_cloud
    bugid = req.bugid.strip()
    new_time = req.new_time.strip()
    if not bugid:
        return _fail("请输入 bugid/jira号")
    if not new_time:
        return _fail("请输入新的触发时间")
    try:
        _save_trigger_time_to_cloud(bugid, new_time)
        cached = _load_diagnose_cache(bugid)
        if cached:
            cached["verify_status"] = "corrected"
            cached["suggested_time"] = new_time
            _save_diagnose_cache(bugid, cached)
        return _ok({"bugid": bugid, "new_time": new_time, "updated": True},
                   f"已更新 {bugid} 的触发时间为 {new_time}（云端+本地+诊断缓存）")
    except Exception as e:
        logger.warning("更新触发时间失败 %s: %s", bugid, e)
        return _fail(f"更新失败: {e}")


@router.post("/api/trigger_time/batch_update", response_model=ApiResponse)
async def batch_update_trigger_time(req: BatchUpdateRequest):
    """批量应用修正时间"""
    from src.services.trigger_ops import _batch_save_trigger_times_to_cloud
    from src.services.report_ops import _load_diagnose_cache, _save_diagnose_cache
    from src.api.routes.shared import ok as _ok, fail as _fail
    items = req.items
    if not items:
        return _fail("待应用列表为空")
    valid_items, skip_corrected = {}, 0
    for item in items:
        bugid = item.bugid.strip()
        new_time = item.new_time.strip()
        if not bugid or not new_time:
            continue
        cached = _load_diagnose_cache(bugid)
        if cached and cached.get("verify_status") == "corrected":
            skip_corrected += 1
            continue
        valid_items[bugid] = new_time
    if not valid_items:
        msg = "无待应用记录"
        if skip_corrected:
            msg += f"（已修正跳过 {skip_corrected} 条）"
        return _fail(msg)
    cloud_ok = _batch_save_trigger_times_to_cloud(valid_items)
    if not cloud_ok:
        return _fail("云端写入失败")
    cache_updated = 0
    for bugid, new_time in valid_items.items():
        cached = _load_diagnose_cache(bugid)
        if cached:
            cached["verify_status"] = "corrected"
            cached["suggested_time"] = new_time
            _save_diagnose_cache(bugid, cached)
            cache_updated += 1
    success = len(valid_items)
    msg = f"批量应用完成：成功 {success} 条"
    if skip_corrected:
        msg += f"，已修正跳过 {skip_corrected} 条"
    return _ok({"success": success, "failed": 0, "skip_corrected": skip_corrected}, msg)


@router.post("/api/trigger_time/re_extract_scan", response_model=ApiResponse)
async def re_extract_scan(req: ReExtractScanRequest):
    """扫描云端触发时间记录，找出触发时间为空的候选项"""
    from src.api.routes.shared import (
        bitable_text as _bitable_text,
        ok as _ok,
        fail as _fail,
    )
    from src.services.trigger_ops import _load_all_cloud_trigger_records
    cache_only = req.cache_only
    try:
        loop = asyncio.get_event_loop()
        all_records = await loop.run_in_executor(None, _load_all_cloud_trigger_records)
        empty_records = [r for r in all_records if not r["trigger_time"]]
        if not empty_records:
            return _ok({"candidates": [], "total_empty": 0, "total_cloud": len(all_records)},
                       "云端所有记录均已提取到触发时间")
        if cache_only:
            candidates = [{"bugid": r["jira_no"], "jira_status": "", "table_id": r["table_id"], "record_id": r["record_id"]} for r in empty_records]
            return _ok({"candidates": candidates, "total_empty": len(empty_records), "total_cloud": len(all_records)},
                       f"缓存扫描完成: 云端共 {len(all_records)} 条，触发时间为空 {len(candidates)} 条")
        from src.clients import jira_client as _jc
        candidates = []
        for i, rec in enumerate(empty_records):
            if await request.is_disconnected():
                break
            await asyncio.sleep(0)
            try:
                issue = await loop.run_in_executor(None, _jc.fetch_issue, rec["jira_no"])
                status = ((issue.get("fields") or {}).get("status") or {}).get("name", "")
                if status.lower() != "closed":
                    candidates.append({"bugid": rec["jira_no"], "jira_status": status, "table_id": rec["table_id"], "record_id": rec["record_id"]})
            except Exception as e:
                candidates.append({"bugid": rec["jira_no"], "jira_status": f"查询失败: {e}", "table_id": rec["table_id"], "record_id": rec["record_id"]})
        return _ok({"candidates": candidates, "total_empty": len(empty_records), "total_cloud": len(all_records)},
                    f"扫描完成: 云端共 {len(all_records)} 条，空触发时间 {len(empty_records)} 条，可重新提取（非 Closed）{len(candidates)} 条")
    except Exception as e:
        logger.error("重新提取扫描失败: %s", e)
        return _fail(f"扫描失败: {e}")


@router.post("/api/trigger_time/re_extract", response_model=ApiResponse)
async def re_extract(req: BugidListRequest):
    """对指定的 bugid 列表重新提取触发时间（视频优先）"""
    from src.services.server_legacy import _diag_extract_time_from_video_simple
    from src.services.trigger_ops import _save_trigger_time_to_cloud
    from src.api.routes.shared import ok as _ok, fail as _fail
    from src.clients import jira_client as _jc
    bugids = req.bugids
    if not bugids:
        return _fail("待重新提取列表为空")
    try:
        loop = asyncio.get_event_loop()
        results = []
        for i, bugid in enumerate(bugids):
            if await request.is_disconnected():
                break
            await asyncio.sleep(0)
            try:
                issue = await loop.run_in_executor(None, _jc.fetch_issue, bugid)
                tt = await loop.run_in_executor(None, _diag_extract_time_from_video_simple, issue)
                if not tt:
                    tt = await loop.run_in_executor(None, _jc.extract_trigger_time_from_issue, issue)
                status = ((issue.get("fields") or {}).get("status") or {}).get("name", "")
                if tt:
                    await loop.run_in_executor(None, _save_trigger_time_to_cloud, bugid, tt)
                    results.append({"bugid": bugid, "trigger_time": tt, "status": status, "success": True})
                else:
                    results.append({"bugid": bugid, "trigger_time": "", "status": status, "success": False, "error": "未提取到时间"})
            except Exception as e:
                results.append({"bugid": bugid, "trigger_time": "", "success": False, "error": str(e)})
        success_count = sum(1 for r in results if r["success"])
        return _ok({"results": results, "success_count": success_count, "total": len(bugids)},
                    f"重新提取完成: {success_count}/{len(bugids)} 成功")
    except Exception as e:
        logger.error("重新提取失败: %s", e)
        return _fail(f"重新提取失败: {e}")


@router.post("/api/trigger_time/cache_batch_scan", response_model=ApiResponse)
async def cache_batch_scan(req: CacheBatchScanRequest):
    """云端缓存批量更新：扫描需要重新提取触发时间的候选记录"""
    from src.api.routes.shared import (
        ok as _ok,
        fail as _fail,
    )
    from src.services.trigger_ops import _load_all_cloud_trigger_records
    from src.services import trigger_service as svc
    exclude_bitable_success = req.exclude_bitable_success
    exclude_corrected = req.exclude_corrected
    try:
        loop = asyncio.get_event_loop()
        all_records = await loop.run_in_executor(None, _load_all_cloud_trigger_records)
        result = svc.scan_candidates(all_records, exclude_bitable_success, exclude_corrected)
        return _ok({
            "candidates": result["candidates"],
            "total_cloud": result["total_cloud"],
            "total_cached": result["total_cached"],
            "bitable_success_count": result["bitable_success_count"],
            "corrected_count": result["corrected_count"],
        }, result["message"])
    except Exception as e:
        logger.error("云端缓存批量扫描失败: %s", e)
        return _fail(f"扫描失败: {e}")


@router.post("/api/trigger_time/cache_batch_extract/stop", response_model=ApiResponse)
async def stop_cache_batch_extract():
    """触发云端缓存批量提取停止信号"""
    from src.api.routes.shared import cache_batch_stop_event as _cache_batch_stop_event, ok
    _cache_batch_stop_event.set()
    logger.info("收到云端缓存批量提取停止信号")
    return ok(None, "停止信号已发送，当前条目完成后停止")


@router.post("/api/trigger_time/cache_batch_load_progress", response_model=ApiResponse)
def cache_batch_load_progress():
    """加载本地缓存批量提取进度"""
    from src.api.routes.shared import ok as _ok
    from src.services.trigger_ops import _load_cache_batch_progress
    data = _load_cache_batch_progress()
    return _ok({"progress": data}, f"本地进度: {len(data)} 条记录")


@router.post("/api/trigger_time/cache_batch_clear_progress", response_model=ApiResponse)
def cache_batch_clear_progress():
    """清除本地缓存批量提取进度"""
    from src.api.routes.shared import (
        ok as _ok,
        fail as _fail,
    )
    from src.services.trigger_ops import _CACHE_BATCH_PROGRESS_FILE
    try:
        if os.path.exists(_CACHE_BATCH_PROGRESS_FILE):
            os.remove(_CACHE_BATCH_PROGRESS_FILE)
        return _ok({}, "本地进度已清除")
    except Exception as e:
        return _fail(f"清除失败: {e}")


@router.post("/api/trigger_time/cache_batch_extract")
async def cache_batch_extract(req: CacheBatchExtractRequest, request: Request):
    """云端缓存批量更新：SSE 流式推送进度，重新提取触发时间"""
    from src.api.routes.shared import cache_batch_stop_event as _cache_batch_stop_event, fail as _fail
    from src.services.trigger_ops import (
        _load_cache_batch_progress, _save_cache_batch_progress,
        _save_trigger_time_to_cloud,
    )
    from src.services.server_legacy import _diag_extract_time_from_video_simple, _VIDEO_SUFFIXES
    from src.services import trigger_service as svc
    bugids = req.bugids
    old_times = req.old_times
    video_first = req.video_first
    if not bugids:
        return _fail("待提取列表为空")

    gen = svc.generate_extract_events(
        bugids=bugids,
        old_times=old_times,
        video_first=video_first,
        stop_event=_cache_batch_stop_event,
        progress_loader=_load_cache_batch_progress,
        progress_saver=_save_cache_batch_progress,
        video_extractor=_diag_extract_time_from_video_simple,
        cloud_saver=_save_trigger_time_to_cloud,
        video_suffixes=_VIDEO_SUFFIXES,
        request=request,
    )
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/trigger_time/rebalance", response_model=ApiResponse)
async def rebalance_trigger_time_tables_endpoint():
    """再平衡触发时间表：把超过500的表中多余记录搬运到不足500的表中"""
    from src.services.trigger_ops import rebalance_trigger_time_tables
    from src.api.routes.shared import ok as _ok, fail as _fail
    try:
        result = rebalance_trigger_time_tables()
        if result["moved"] > 0:
            return _ok(result, f"再平衡完成：搬运 {result['moved']} 条记录\n" + "\n".join(result["details"]))
        else:
            return _ok(result, result["details"][0] if result["details"] else "无需再平衡")
    except Exception as e:
        logger.error("触发时间表再平衡失败: %s", e, exc_info=True)
        return _fail(f"再平衡失败: {e}")
