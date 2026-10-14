"""Verify routes - 6 endpoints: 验证和填入"""
from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse

from src.schemas.common import ApiResponse
from src.schemas.verify import VerifyWriteRequest

router = APIRouter()


@router.get("/api/verify/history_files", response_model=ApiResponse)
async def list_verify_history_files():
    from src.api.routes.shared import read_csv_rows as _read_csv_rows, parse_conf as _parse_conf, ok as _ok
    from src.config import PROJECT_ROOT, get_path
    import os
    files = []
    scan_dirs = [
        os.path.join(PROJECT_ROOT, "data"),
        get_path("doc_dir"),
    ]
    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for day in sorted(os.listdir(scan_dir), reverse=True):
            day_dir = os.path.join(scan_dir, day)
            if not os.path.isdir(day_dir):
                continue
            for fname in sorted(os.listdir(day_dir), reverse=True):
                if "_compare_log" not in fname.lower() or not fname.lower().endswith(".csv"):
                    continue
                full_path = os.path.join(day_dir, fname)
                size_kb = round(os.path.getsize(full_path) / 1024, 1)
                rows = _read_csv_rows(full_path)
                low_conf_count = sum(1 for r in rows if _parse_conf(r.get("结果置信度", "")) < 0.7)
                files.append({"name": fname, "day": day, "path": full_path,
                              "size_kb": size_kb, "total": len(rows),
                              "low_conf": low_conf_count})
    return _ok(files)


@router.get("/api/verify/history_load", response_model=ApiResponse)
async def load_verify_history(path: str = Query(default="", description="文件路径")):
    from src.api.routes.shared import read_csv_rows as _read_csv_rows, ok as _ok, fail as _fail
    import os
    if not path or not os.path.isfile(path):
        return _fail(f"文件不存在: {path}")
    rows = _read_csv_rows(path)
    return _ok({"rows": rows, "total": len(rows), "path": path})


@router.post("/api/verify_and_fill")
async def verify_and_fill(request: Request):
    from src.services.server_legacy import _verify_and_fill_impl
    return await _verify_and_fill_impl(request)


@router.post("/api/verify_write", response_model=ApiResponse)
async def verify_write(req: VerifyWriteRequest, request: Request):
    from src.api.routes.shared import read_csv_rows as _read_csv_rows, ok as _ok, fail as _fail
    import csv as _csv
    import os
    csv_path = req.csv_path.strip()
    items = req.items
    if not csv_path or not os.path.isfile(csv_path):
        return _fail(f"文件不存在: {csv_path}")
    if not items:
        return _fail("无待写入的记录")
    rows = _read_csv_rows(csv_path)
    if not rows:
        return _fail("CSV 为空")
    bugid_col = None
    for col in ["jira号", "bugid", "key", "issue_key", "Bug ID"]:
        if col in rows[0]:
            bugid_col = col
            break
    if not bugid_col:
        for c in rows[0].keys():
            if "jira" in c.lower() or "bug" in c.lower():
                bugid_col = c
                break
    if not bugid_col:
        return _fail("无法识别 bugid 列")
    write_map = {}
    for item in items:
        bugid = item.bugid.strip()
        if bugid:
            write_map[bugid] = {"rootcause": item.rootcause, "comment_summary": item.comment_summary, "confidence": item.confidence}
    written = []
    for row in rows:
        row_bugid = str(row.get(bugid_col, "")).strip()
        if row_bugid in write_map:
            item = write_map[row_bugid]
            row["rootcause"] = item.get("rootcause", "")
            row["AI评论总结"] = item.get("comment_summary", "")
            row["结果置信度"] = item.get("confidence", "")
            written.append(row_bugid)
    fieldnames = list(rows[0].keys())
    for f in ["AI评论总结", "rootcause", "结果置信度"]:
        if f not in fieldnames:
            fieldnames.append(f)
    try:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fout:
            writer = _csv.DictWriter(fout, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    except Exception as e:
        return _fail(f"写入失败: {e}")
    return _ok({"written": written, "count": len(written)}, f"已写入 {len(written)} 条记录")


@router.get("/api/verify_bitable_eligible", response_model=ApiResponse)
async def verify_bitable_eligible():
    from src.api.routes.shared import ok as _ok, fail as _fail
    from src.config import load_config
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
        eligible = set()
        for rec in records:
            fields = rec.get("fields", {})
            jira_key = fields.get(bugid_field, "")
            if isinstance(jira_key, list):
                jira_key = "".join(str(v) for v in jira_key)
            jira_key = str(jira_key).strip()
            if not jira_key:
                continue
            result_status = str(fields.get("分析结果", "")).strip()
            conf_val = fields.get("结果置信度", "")
            conf_empty = (conf_val is None or conf_val == "" or conf_val == 0 or str(conf_val).strip() in ("", "0", "0.0"))
            if result_status == "成功" and conf_empty:
                eligible.add(jira_key)
        return _ok({"eligible": list(eligible), "count": len(eligible)}, f"可写入 {len(eligible)} 条")
    except Exception as e:
        return _fail(f"查询多维表格失败: {e}")


@router.post("/api/verify_write_bitable")
async def verify_write_bitable(request: Request):
    from src.services.server_legacy import _verify_write_bitable_impl
    return await _verify_write_bitable_impl(request)
