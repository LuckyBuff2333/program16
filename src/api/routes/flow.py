"""核心分析流程路由：analyze / flow / retry / store / audit"""
import asyncio
import json as _json
import os
import queue

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src import pipeline
from src.config import load_config, setup_logger
from src.core import audit as audit_module
from src.api.routes.shared import ok, fail, read_csv_rows, daily_csv_path, spotcheck_csv_path, flow_cancel
from src.schemas.common import ApiResponse
from src.schemas.flow import (
    AnalyzeRequest, ExtractTimeRequest, FlowSingleRequest,
    BugidRequest, AuditRequest,
)

logger = setup_logger("web.flow")
router = APIRouter()


@router.post("/api/analyze", response_model=ApiResponse)
def run_analyze(req: AnalyzeRequest):
    """执行内容补充流程，接收表格行数据，返回补充后的完整数据"""
    rows = req.rows
    if not rows and req.bugids:
        bugids = [b.strip() for b in req.bugids.replace("，", ",").split(",") if b.strip()]
        trigger_times = req.trigger_times
        rows = [{"jira号": b, "分析问题时间": trigger_times.get(b, ""),
                 "AI分析结果(飞书链接)": "", "AI评论总结": "", "rootcause": "", "结果置信度": ""} for b in bugids]
    if not rows:
        return fail("表格数据不能为空")
    try:
        result = pipeline.run_pipeline(rows)
        return ok({"rows": result["rows"], "stats": result["stats"]},
                   f"补充完成：总 {result['stats']['total']} 条，已完整 {result['stats']['complete']} 条")
    except Exception as e:
        logger.error("analyze 执行失败: %s", e)
        return fail(str(e))


@router.post("/api/flow/extract_time", response_model=ApiResponse)
async def flow_extract_time(req: ExtractTimeRequest):
    """提取单个 Jira 号的触发时间：优先本地缓存，否则从 Jira 提取"""
    bugid = req.bugid.strip()
    if not bugid:
        return fail("bugid 不能为空")
    # 延迟导入 server.py 中的触发时间函数（后续会拆分到 trigger.py）
    from src.services.trigger_ops import _load_trigger_times_from_cloud, _save_trigger_time_to_cloud
    local_times = _load_trigger_times_from_cloud()
    if bugid in local_times:
        return ok({"trigger_time": local_times[bugid], "source": "local"}, f"本地缓存命中: {local_times[bugid]}")
    try:
        from src.clients import jira_client as _jc
        loop = asyncio.get_event_loop()
        issue = await loop.run_in_executor(None, _jc.fetch_issue, bugid)
        tt = await loop.run_in_executor(None, _jc.extract_trigger_time_from_issue, issue)
        if tt:
            _save_trigger_time_to_cloud(bugid, tt, source="flow(单Jira提取)")
            return ok({"trigger_time": tt, "source": "jira"}, f"提取成功: {tt}")
        return fail(f"{bugid} 未提取到触发时间（评论中未找到有效时间戳）")
    except Exception as e:
        logger.warning("单Jira时间提取失败 %s: %s", bugid, e)
        return fail(f"提取失败: {e}")


@router.post("/api/flow/single")
async def flow_single(req: FlowSingleRequest, request: Request):
    """单 bugid 流程执行：SSE 实时推送每步结果"""
    bugid = req.bugid.strip()
    trigger_time = req.trigger_time.strip()
    if not bugid:
        return fail("bugid 不能为空")
    flow_cancel[bugid] = False

    async def event_generator():
        step_queue = queue.Queue()
        yield f"data: {_json.dumps({'step': 0, 'name': 'start', 'ok': True, 'summary': bugid}, ensure_ascii=False)}\n\n"
        loop = asyncio.get_event_loop()
        cancel_check = lambda: flow_cancel.get(bugid, False)

        def _run_flow():
            try:
                def on_step(step_result):
                    step_queue.put(step_result)
                result = pipeline.execute_single_flow(
                    bugid, trigger_time, cancel_check=cancel_check, step_callback=on_step)
                step_queue.put({"_done": True, "all_ok": result["all_ok"],
                                "cancelled": result.get("cancelled", False), "row": result["row"]})
            except Exception as e:
                logger.error("flow/single 执行失败: %s", e)
                step_queue.put({"_done": True, "all_ok": False, "error": str(e)})

        loop.run_in_executor(None, _run_flow)
        try:
            while True:
                if await request.is_disconnected():
                    logger.info("flow/single: 客户端已断开 bugid=%s", bugid)
                    break
                try:
                    item = step_queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.3)
                    continue
                if item.get("_done"):
                    yield f"data: {_json.dumps({'done': True, 'all_ok': item['all_ok'], 'cancelled': item.get('cancelled', False), 'row': item.get('row')}, ensure_ascii=False)}\n\n"
                    break
                yield f"data: {_json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            flow_cancel.pop(bugid, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/flow/stop/{bugid}", response_model=ApiResponse)
def flow_stop(bugid: str):
    """通知后端停止执行指定 bugid 的流程"""
    if bugid in flow_cancel:
        flow_cancel[bugid] = True
        return ok({"bugid": bugid}, "已发送停止信号")
    return fail("未找到正在执行的流程")


@router.get("/api/flow/check/{bugid}", response_model=ApiResponse)
def flow_check(bugid: str):
    """快速检查 bugid 的 6 字段状态（不执行补充）"""
    csv_path = daily_csv_path()
    rows = read_csv_rows(csv_path)
    target = None
    for r in rows:
        if (r.get("jira号") or "").strip() == bugid.strip():
            target = r
            break
    if not target:
        fields = {f: {"value": "", "missing": True} for f in pipeline.SUPPLEMENT_FIELDS}
        return ok({"found": False, "fields": fields, "missing_count": len(pipeline.SUPPLEMENT_FIELDS)},
                   f"今日报表中未找到 {bugid}")
    fields = {}
    missing_count = 0
    for f in pipeline.SUPPLEMENT_FIELDS:
        val = (target.get(f) or "").strip()
        is_missing = val in ("", "-", "None")
        fields[f] = {"value": val, "missing": is_missing}
        if is_missing:
            missing_count += 1
    return ok({"found": True, "fields": fields, "missing_count": missing_count},
               f"{bugid}: {len(pipeline.SUPPLEMENT_FIELDS) - missing_count}/{len(pipeline.SUPPLEMENT_FIELDS)} 字段已有值")


@router.post("/api/retry", response_model=ApiResponse)
def run_retry(req: BugidRequest):
    """失败 bug 重新补充"""
    bugid = req.bugid.strip()
    if not bugid:
        return fail("bugid 不能为空")
    try:
        result = pipeline.retry_bug(bugid)
        return ok({"rows": result["rows"]}, f"bugid={bugid} 重新补充完成")
    except Exception as e:
        logger.error("retry 执行失败: %s", e)
        return fail(str(e))


@router.post("/api/store", response_model=ApiResponse)
def run_store(req: BugidRequest):
    """手工将分析文档推入知识库"""
    bugid = req.bugid.strip()
    if not bugid:
        return fail("bugid 不能为空")
    try:
        pipeline.store_bug(bugid)
        return ok(message=f"bugid={bugid} 分析文档已推入知识库")
    except Exception as e:
        logger.error("store 执行失败: %s", e)
        return fail(str(e))


@router.post("/api/audit", response_model=ApiResponse)
def run_audit(req: AuditRequest):
    """随机抽查复核，返回人工审核表格数据（含达标/不达标判定）"""
    count = req.count
    try:
        audit_module.sample_and_audit(int(count) if count else None)
        cfg = load_config()["audit"]
        rows = read_csv_rows(spotcheck_csv_path(cfg["report_file"]))
        passed = sum(1 for r in rows if r.get("判定结果") == "达标")
        failed = len(rows) - passed
        msg = f"抽查完成：共 {len(rows)} 条，达标 {passed} 条，不达标 {failed} 条"
        return ok({"rows": rows, "passed": passed, "failed": failed}, msg)
    except Exception as e:
        logger.error("audit 执行失败: %s", e)
        return fail(str(e))
