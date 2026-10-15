"""数据管理路由：历史批次查询、云端同步、Jira 聚合"""
import os
import re
from datetime import datetime

from fastapi import APIRouter, Request, Query

from src.config import get_path, load_config, setup_logger
from src.schemas.common import ApiResponse
from src.schemas.misc import SyncCloudBatchesRequest

logger = setup_logger("web.data")
router = APIRouter()


def _get_batch_folder_token() -> str:
    """获取 batch_folder_token，缓存缺失时自动从文件重新加载"""
    token = load_config().get("feishu_bitable", {}).get("batch_folder_token", "")
    if not token:
        try:
            import src.config as _cfg_mod
            _cfg_mod._CONFIG = None
            token = load_config().get("feishu_bitable", {}).get("batch_folder_token", "")
        except Exception:
            pass
    return token


@router.get("/api/data/history_batches", response_model=ApiResponse)
def data_history_batches():
    """数据面板：从飞书云端文件夹列出所有历史批量执行批次"""
    from src.clients import feishu_client
    from src.api.routes.shared import ok as _ok, fail as _fail
    folder_token = _get_batch_folder_token()
    if not folder_token:
        return _fail("未配置 batch_folder_token，无法读取云端历史")
    try:
        files = feishu_client.list_folder_files(folder_token, recursive=True)
    except Exception as e:
        logger.warning("读取云端批次列表失败: %s", e)
        return _fail(f"读取云端批次列表失败: {e}")
    batches = []
    for f in files:
        f_name = f.get("name", "")
        f_token = f.get("token", "")
        f_type = f.get("type", "")
        f_url = f.get("url", "")
        created = f.get("created_time", "")
        f_folder = f.get("folder", "")
        if not f_token:
            continue
        if f_type and f_type != "docx":
            continue
        date_label = created[:10] if len(created) >= 10 else created
        prefix = f"{f_folder} / " if f_folder else ""
        batches.append({
            "token": f_token, "name": f_name,
            "label": f"{prefix}{f_name} ({date_label})",
            "value": f_token, "url": f_url,
            "created_time": created, "folder": f_folder,
        })
    batches.sort(key=lambda b: b.get("created_time", ""), reverse=True)
    return _ok({"batches": batches, "count": len(batches)},
               f"共找到 {len(batches)} 个云端批次")


@router.get("/api/data/history_batch_preview", response_model=ApiResponse)
def data_history_batch_preview(batch_token: str = Query(default="", description="批次文档 token")):
    """预览指定云端批次文档内容"""
    from src.clients import feishu_client
    from src.api.routes.shared import ok as _ok, fail as _fail, parse_markdown_batch_table as _parse_markdown_batch_table
    if not batch_token:
        return _fail("缺少 batch_token 参数")
    try:
        md = feishu_client.fetch_docx_as_markdown(batch_token)
    except Exception as e:
        logger.warning("读取云端批次文档失败: %s", e)
        return _fail(f"读取云端文档失败: {e}")
    batch_rows = _parse_markdown_batch_table(md)
    rows = []
    for r in batch_rows:
        jira_no = (r.get("jira号") or "").strip()
        if not jira_no:
            continue
        trigger_time = (r.get("触发时间") or "").strip()
        exec_time = (r.get("执行时间") or "").strip()
        if not trigger_time and exec_time and "分析执行时间" not in r:
            trigger_time = exec_time
            exec_time = (r.get("分析执行时间") or "").strip()
        rows.append({
            "jira号": jira_no,
            "执行结果": (r.get("执行结果") or "").strip(),
            "报告长度": "",
            "触发时间": trigger_time,
            "执行时间": exec_time,
            "备注": (r.get("备注") or "").strip(),
        })
    return _ok({"rows": rows, "count": len(rows), "batch_token": batch_token},
               f"云端批次预览: {len(rows)} 条")


@router.post("/api/data/sync_cloud_batches", response_model=ApiResponse)
async def sync_cloud_batches(req: SyncCloudBatchesRequest):
    """从云端同步批量执行记录到本地CSV"""
    import csv as _csv
    from src.clients import feishu_client
    from src.api.routes.shared import read_csv_rows as _read_csv_rows, ok as _ok, fail as _fail, parse_markdown_batch_table as _parse_markdown_batch_table
    dates = req.dates
    if not dates:
        return _fail("请指定要同步的日期列表")
    folder_token = _get_batch_folder_token()
    if not folder_token:
        return _fail("未配置 batch_folder_token")
    doc_dir = get_path("doc_dir")
    synced_total = skipped_total = 0
    errors = []
    for date_str in dates:
        day_dir = os.path.join(doc_dir, date_str)
        os.makedirs(day_dir, exist_ok=True)
        existing_jiras = set()
        for fname in os.listdir(day_dir):
            if fname.startswith("batch_") and fname.endswith(".csv"):
                for r in _read_csv_rows(os.path.join(day_dir, fname)):
                    j = r.get("jira号", "").strip()
                    if j:
                        existing_jiras.add(j)
        try:
            all_files = feishu_client.list_folder_files(folder_token, recursive=True)
        except Exception as e:
            errors.append(f"{date_str}: 列出云端文件失败 - {e}")
            continue
        cloud_docs = [f for f in all_files
                      if f.get("folder", "") == date_str and f.get("type") == "docx"
                      and f.get("name", "").startswith("批量执行")]
        if not cloud_docs:
            continue
        for doc in cloud_docs:
            doc_token = doc.get("token", "")
            doc_name = doc.get("name", "")
            if not doc_token:
                continue
            safe_name = doc_name.replace("批量执行 ", "batch_cloud_").replace(" ", "_").replace(":", "")
            if not safe_name.endswith(".csv"):
                safe_name += ".csv"
            local_path = os.path.join(day_dir, safe_name)
            if os.path.exists(local_path):
                skipped_total += 1
                continue
            try:
                md = feishu_client.fetch_docx_as_markdown(doc_token)
                batch_rows = _parse_markdown_batch_table(md)
                if not batch_rows:
                    skipped_total += 1
                    continue
                new_rows = []
                for r in batch_rows:
                    jira_no = (r.get("jira号") or "").strip()
                    if jira_no and jira_no not in existing_jiras:
                        new_rows.append(r)
                        existing_jiras.add(jira_no)
                if not new_rows:
                    skipped_total += 1
                    continue
                fieldnames = ["jira号", "执行结果", "报告长度", "备注", "触发时间", "执行时间",
                              "分析并发数", "下载并发数", "模型", "触发来源"]
                with open(local_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = _csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for r in new_rows:
                        writer.writerow({
                            "jira号": (r.get("jira号") or "").strip(),
                            "执行结果": (r.get("执行结果") or "").strip(),
                            "报告长度": "",
                            "备注": (r.get("备注") or "").strip(),
                            "触发时间": (r.get("触发时间") or "").strip(),
                            "执行时间": (r.get("执行时间") or "").strip(),
                            "分析并发数": (r.get("分析并发数") or "").strip(),
                            "下载并发数": (r.get("下载并发数") or "").strip(),
                            "模型": (r.get("模型") or "").strip(),
                            "触发来源": (r.get("触发来源") or "").strip(),
                        })
                synced_total += 1
                logger.info("云端同步成功: %s → %s (%d条新记录)", doc_name, local_path, len(new_rows))
            except Exception as e:
                errors.append(f"{date_str}/{doc_name}: {e}")
                logger.warning("云端同步失败 %s/%s: %s", date_str, doc_name, e)
    msg = f"同步完成：新增 {synced_total} 个文件"
    if skipped_total:
        msg += f"，跳过 {skipped_total} 个已存在"
    if errors:
        msg += f"，失败 {len(errors)} 个"
    return _ok({"synced": synced_total, "skipped": skipped_total, "errors": errors}, msg)


@router.get("/api/data/history_jira", response_model=ApiResponse)
def data_history_jira(
    batch_token: str = Query(default="", description="批次文档 token"),
    batch_name: str = Query(default="", description="批次名称"),
    batch_created: str = Query(default="", description="创建时间"),
):
    """数据面板：从云端文档读取批次 Jira 列表并聚合多维表格匹配记录，支持多批次（逗号分隔 token）"""
    from src.clients import feishu_client
    from src.api.routes.shared import bitable_text as _bitable_text, ok as _ok, fail as _fail, flatten_bitable_record as _flatten_bitable_record, parse_markdown_batch_table as _parse_markdown_batch_table
    if not batch_token:
        return _fail("缺少 batch_token 参数")
    # 支持多批次：逗号分隔的 token
    tokens = [t.strip() for t in batch_token.split(",") if t.strip()]
    names = [n.strip() for n in (batch_name or "").split(",")]
    createds = [c.strip() for c in (batch_created or "").split(",")]
    # 解析每个批次的执行时间
    batch_exec_times = []
    for i, tk in enumerate(tokens):
        nm = names[i] if i < len(names) else ""
        ct = createds[i] if i < len(createds) else ""
        exec_time = ""
        m = re.search(r"(\d{4}-\d{2}-\d{2})[_\s](\d{6})", nm)
        if m:
            exec_time = f"{m.group(1)} {m.group(2)[:2]}:{m.group(2)[2:4]}:{m.group(2)[4:]}"
        if not exec_time and ct:
            try:
                ts = int(ct)
                exec_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError, OSError):
                iso_m = re.search(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", ct)
                if iso_m:
                    exec_time = f"{iso_m.group(1)} {iso_m.group(2)}"
        batch_exec_times.append(exec_time)
    if any(batch_exec_times):
        logger.info("多批次过滤时间: %s", batch_exec_times)
    # 遍历所有批次文档，收集 Jira 列表
    jira_list = []
    jira_seen = set()  # 跨批次去重
    for i, tk in enumerate(tokens):
        try:
            md = feishu_client.fetch_docx_as_markdown(tk)
        except Exception as e:
            logger.warning("读取云端批次文档 %s 失败: %s", tk, e)
            continue
        batch_rows = _parse_markdown_batch_table(md)
        exec_time = batch_exec_times[i] if i < len(batch_exec_times) else ""
        for r in batch_rows:
            jira_no = (r.get("jira号") or "").strip()
            if jira_no and jira_no not in jira_seen:
                jira_seen.add(jira_no)
                jira_list.append({
                    "jira号": jira_no,
                    "执行结果": (r.get("执行结果") or "").strip(),
                    "执行时间": (r.get("执行时间") or "").strip(),
                    "备注": (r.get("备注") or "").strip(),
                    "_exec_time": exec_time,
                })
    if not jira_list:
        return _ok({"rows": [], "count": 0}, "该批次无有效 Jira 记录")
    jira_set = set(item["jira号"] for item in jira_list)
    # 取所有批次中最早的时间作为兜底过滤（多批次时放宽过滤条件）
    earliest_time = min((t for t in batch_exec_times if t), default="")
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
    bitable_records_map = {}
    if app_token and table_id:
        try:
            records = feishu_client.list_bitable_records(app_token, table_id)
            for rec in records:
                fields = rec.get("fields", {})
                jira_key = _bitable_text(fields.get(bugid_field, ""))
                if jira_key and jira_key in jira_set:
                    rec_done = _bitable_text(fields.get("分析完成时间", ""))
                    if earliest_time and (not rec_done or rec_done < earliest_time):
                        continue
                    bitable_records_map.setdefault(jira_key, []).append(
                        _flatten_bitable_record(fields, report_field))
        except Exception as e:
            logger.warning("批次聚合：多维表格查询失败: %s", e)
    rows = []
    for item in jira_list:
        jira_no = item["jira号"]
        bt_records = bitable_records_map.get(jira_no, [])
        if bt_records:
            bt_records.sort(key=lambda x: x.get("分析完成时间", ""), reverse=True)
            bf = bt_records[0]
            rows.append({
                "jira号": jira_no, "执行结果": item["执行结果"],
                "执行时间": item["执行时间"],
                "分析结果": bf.get("分析结果", ""), "错误信息": bf.get("错误信息", ""),
                "飞书报告链接": bf.get("飞书报告链接", ""),
                "分析问题时间": bf.get("分析问题时间", ""),
                "分析完成时间": bf.get("分析完成时间", ""),
                "人工审核结果": bf.get("人工审核结果", ""),
                "触发来源": bf.get("触发来源", ""),
                "rootcause": bf.get("rootcause", ""),
                "AI评论总结": bf.get("AI评论总结", ""),
                "结果置信度": bf.get("结果置信度", ""),
            })
        else:
            rows.append({
                "jira号": jira_no, "执行结果": item["执行结果"],
                "执行时间": item["执行时间"],
                "分析结果": "", "错误信息": "", "飞书报告链接": "", "分析问题时间": "", "分析完成时间": "",
                "触发来源": "", "rootcause": "", "AI评论总结": "", "结果置信度": "",
            })
    matched = len(jira_set & set(bitable_records_map.keys()))
    return _ok({"rows": rows, "count": len(rows), "matched": matched,
               "batch_token": batch_token},
               f"云端批次: {len(jira_list)} 个 Jira，多维表格命中 {matched} 个，展开 {len(rows)} 行")
