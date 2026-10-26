"""配置参数调优路由：批次列表与成功率/耗时分析"""
from fastapi import APIRouter, Request, Query

from src.api.routes.shared import ok, fail
from src.schemas.common import ApiResponse

router = APIRouter()


@router.get("/api/tuning/batch_list", response_model=ApiResponse)
def tuning_batch_list(source: str = Query(default="", description="来源过滤(pc/online/空)")):
    """配置参数调优：列出所有批量执行批次，按 source 过滤（pc/online/空=全部）"""
    from src.api.routes.shared import ok as _ok
    from src.services.report_ops import _scan_all_batch_records
    all_batches = _scan_all_batch_records()
    if source:
        src_filter = "jira_analyze" if source == "pc" else "parseFullTicket" if source == "online" else ""
        if src_filter:
            all_batches = [b for b in all_batches if b.get("source", "") == src_filter]
    result = []
    for b in all_batches:
        item = {k: v for k, v in b.items() if k != "jira_list"}
        item["jira_count"] = len(b.get("jira_list", []))
        result.append(item)
    return _ok(result, f"找到 {len(result)} 个批次")


@router.post("/api/tuning/analyze", response_model=ApiResponse)
async def tuning_analyze(request: Request):
    """配置参数调优：对选中的批次查多维表格，计算成功率/分析耗时等指标"""
    from src.api.routes.shared import fail as _fail, ok as _ok, bitable_text as _bitable_text, run_blocking
    from src.services.report_ops import (
        _scan_all_batch_records,
        _flatten_bitable_record_all,
        _parse_dur_sec,
        _format_dur,
    )
    from src.config import load_config
    from src.clients import feishu_client

    body = await request.json() or {}
    batch_ids = body.get("batch_ids") or []
    if not batch_ids:
        return _fail("请选择至少一个批次")
    all_batches = _scan_all_batch_records()
    id_map = {b["batch_id"]: b for b in all_batches}
    all_jiras = set()
    selected_batches = []
    for bid in batch_ids:
        b = id_map.get(bid)
        if b:
            selected_batches.append(b)
            all_jiras.update(b.get("jira_list", []))
    if not selected_batches:
        return _fail("未找到匹配的批次")
    cfg = load_config().get("feishu_bitable", {})
    app_token, table_id = cfg.get("app_token", ""), cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    bt_map = {}
    if app_token and table_id:
        try:
            records = await run_blocking(feishu_client.list_bitable_records, app_token, table_id)
            for rec in records:
                fields = rec.get("fields", {})
                jira_key = _bitable_text(fields.get(bugid_field, ""))
                if jira_key and jira_key in all_jiras:
                    bt_map.setdefault(jira_key, []).append(
                        _flatten_bitable_record_all(fields, cfg.get("report_field", "")))
        except Exception as e:
            return _fail(f"多维表格查询失败: {e}")
    results = []
    for b in selected_batches:
        jira_list = b.get("jira_list", [])
        success = 0
        fail_cnt = 0
        analysis_times = []
        version = "-"
        for jira_no in jira_list:
            bt_records = bt_map.get(jira_no, [])
            if not bt_records:
                continue
            bt_records.sort(key=lambda x: x.get("分析完成时间", ""))
            bf = bt_records[-1]
            result_status = bf.get("分析结果", "")
            if result_status == "成功":
                success += 1
            elif result_status == "失败":
                fail_cnt += 1
            if version == "-":
                v = (bf.get("版本号") or "").strip()
                if v:
                    version = v
            dur_sec = _parse_dur_sec(bf.get("分析耗时", ""))
            if dur_sec > 0:
                analysis_times.append(dur_sec)
        total = success + fail_cnt
        rate = f"{success / total * 100:.1f}%" if total else "0%"
        avg_time = _format_dur(sum(analysis_times) / len(analysis_times)) if analysis_times else "-"
        sorted_times = sorted(analysis_times)
        median_time = _format_dur(sorted_times[len(sorted_times) // 2]) if sorted_times else "-"
        results.append({
            "batch_id": b["batch_id"], "date": b["date"], "name": b["name"],
            "version": version, "base_info": b.get("base_info", {}),
            "total": b.get("total", 0), "matched": total,
            "success": success, "fail": fail_cnt, "success_rate": rate,
            "avg_analysis_time": avg_time, "median_analysis_time": median_time,
            "analysis_times": analysis_times,
        })
    return _ok({"batches": results}, f"分析完成，{len(results)} 个批次")
