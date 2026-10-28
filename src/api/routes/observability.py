"""可观测模块路由：Case 台账、详情、上传审计、一键复测、配置、文件上传

接口契约：
    -- 一级页面（观测看板） --
    POST /api/v1/observability/config          — 保存 COS 凭据（加密落盘）
    GET  /api/v1/observability/config          — 读取已保存的凭据（脱敏返回）
    POST /api/v1/observability/upload          — 文件上传 + SHA-256 去重审计
    GET  /api/v1/observability/upload-audits   — 分页查询上传审计记录

    -- 二级页面（观测台账） --
    GET  /api/v1/observability/cases           — 分页查询 Case 列表（模糊 VCU + status）
    GET  /api/v1/observability/cases/:id       — 获取 Case 完整详情（含 JSON 嵌套字段）
    POST /api/obs/cases                        — 创建/更新 Case（upsert）
    DELETE /api/obs/cases/:id                  — 软删除 Case
    GET  /api/obs/audits                       — 获取上传审计记录
    POST /api/obs/audits/check                 — 检查文件哈希是否已存在（去重）
    POST /api/obs/audits                       — 创建上传审计记录
    POST /api/obs/retest/:id                   — 触发一键复测（异步）
"""
import hashlib
import os
import threading

from fastapi import APIRouter, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import Optional

from src.api.routes.shared import ok, fail
from src.config import setup_logger
from src.schemas.common import ApiResponse
from src.services import observability_service as svc

logger = setup_logger("web.observability")
router = APIRouter()


# ── Request Schema ──


class CaseUpsertRequest(BaseModel):
    case_id: str = Field(..., description="Case 唯一标识")
    vcu_number: Optional[str] = None
    finish_time: Optional[str] = None
    duration: Optional[str] = None
    conf: Optional[float] = None
    converged: Optional[bool] = False
    case_status: Optional[str] = None
    backflow_status: Optional[str] = None
    problem_desc: Optional[str] = None
    root_cause_summary: Optional[str] = None
    decision_chain: Optional[list] = None
    hypothesis_table: Optional[list] = None


class AuditCreateRequest(BaseModel):
    doc_id: Optional[str] = None
    file_name: Optional[str] = None
    cos_hash: Optional[str] = None
    upload_status: str = "success"


class HashCheckRequest(BaseModel):
    cos_hash: str = Field(..., description="文件内容 SHA256 哈希值")


class ConfigSaveRequest(BaseModel):
    secret_id: str = Field(..., min_length=1, description="COS SecretId")
    secret_key: str = Field(..., min_length=1, description="COS SecretKey")


# ── 一级页面：观测看板接口 ──


@router.post("/api/v1/observability/config", response_model=ApiResponse)
def save_obs_config(req: ConfigSaveRequest):
    """保存 COS 凭据（XOR + base64 加密落盘，不明文存储）"""
    try:
        result = svc.save_credentials(req.secret_id, req.secret_key)
        return ok(result, "凭据已加密保存到 config/obs_credentials.json")
    except Exception as e:
        logger.error("保存凭据失败: %s", e)
        return fail(str(e))


@router.get("/api/v1/observability/config", response_model=ApiResponse)
def load_obs_config():
    """读取已保存的 COS 凭据（脱敏返回，不返回明文 SecretKey）"""
    creds = svc.load_credentials()
    if not creds:
        return ok({"configured": False}, "尚未配置凭据")
    sid = creds["secret_id"]
    masked_id = sid[:4] + "****" + sid[-4:] if len(sid) > 8 else "****"
    return ok({
        "configured": True,
        "secret_id_masked": masked_id,
        "saved_at": creds.get("saved_at"),
    })


@router.post("/api/v1/observability/upload", response_model=ApiResponse)
def upload_obs_file(
    file: UploadFile = File(..., description="Case 档案文件"),
    target_kb: str = Form(default="", description="目标知识库名称"),
):
    """文件上传 + SHA-256 去重审计

    流程：计算哈希 → 去重校验 → 保存文件 → 落库审计
    """
    try:
        result = svc.upload_and_dedup(file.file, file.filename or "unknown")
        return ok(result, "文件上传成功")
    except ValueError as e:
        # 业务异常（重复上传）
        return fail(str(e))
    except Exception as e:
        logger.error("文件上传失败: %s", e)
        return fail(f"上传失败: {e}")


@router.get("/api/v1/observability/upload-audits", response_model=ApiResponse)
def get_upload_audits(page: int = 1, page_size: int = 10):
    """分页查询上传审计记录（按时间倒序）"""
    try:
        result = svc.list_audits_paginated(page, page_size)
        return ok(result)
    except Exception as e:
        logger.error("查询审计记录失败: %s", e)
        return fail(str(e))


# ── 二级页面：观测台账接口（v1） ──


@router.get("/api/v1/observability/cases", response_model=ApiResponse)
def get_cases_v1(
    page: int = 1,
    page_size: int = 10,
    vcu_number: str = None,
    status: str = None,
    task_type: str = None,
):
    """分页查询 Case 列表（v1 接口）

    - vcu_number: 支持模糊查询（LIKE %keyword%）
    - status: 统一筛选 case_status 或 backflow_status
    - task_type: 筛选 trigger_source（如 jira_analyze / parseFullTicket）
    - 按 finish_time 倒序排列
    - 返回 {"list": [...], "total": int}
    """
    try:
        result = svc.list_cases_v1(page, page_size, vcu_number, status, task_type)
        return ok(result)
    except Exception as e:
        logger.error("查询 Case 列表失败: %s", e)
        return fail(str(e))


@router.get("/api/v1/observability/cases/{case_id}", response_model=ApiResponse)
async def get_case_detail_v1(case_id: str, auto_fetch: bool = False):
    """获取 Case 完整详情（v1 接口，字段名与前端对齐）

    包含 decision_chain / hypothesis_table 的 JSON 反序列化，
    确保前端拿到的是对象/数组而非字符串。

    auto_fetch=true 时，若 decision_chain 为空则自动获取报告并解析。
    """
    import asyncio

    def _get_case_sync():
        result = svc.get_case_v1(case_id)
        if not result:
            return None
        if auto_fetch and not result.get("decision_chain"):
            try:
                parsed = svc.fetch_and_parse_report(case_id)
                result = svc.get_case_v1(case_id)
                result["_report_fetched"] = True
                result["_report_source"] = parsed.get("source", "")
            except Exception as e:
                logger.warning("自动获取报告失败（不影响详情返回）: %s", e)
                result["_report_fetch_error"] = str(e)[:120]
        return result

    result = await asyncio.to_thread(_get_case_sync)
    if not result:
        return fail(f"数据不存在: case_id={case_id}")
    return ok(result)


@router.post("/api/v1/observability/cases/{case_id}/fetch_report", response_model=ApiResponse)
def fetch_report_for_case(case_id: str):
    """手动触发：获取 AI 分析报告并强解析 decision_chain / hypothesis_table

    三级回退获取报告原文 → parse_raw_report_to_json 正则强解析 → 落库
    容错：所有网络/解析失败只记录日志，不影响服务稳定性。
    """
    try:
        result = svc.fetch_and_parse_report(case_id)
        return ok(result, f"报告解析完成: rounds={result.get('rounds', 0)}, root_cause={result.get('root_cause', '')[:60]}")
    except ValueError as e:
        return fail(str(e))
    except Exception as e:
        logger.error("报告解析失败: case_id=%s, error=%s", case_id, e)
        return fail(f"报告解析失败: {str(e)[:200]}")


@router.get("/api/v1/observability/case_stats", response_model=ApiResponse)
def get_case_stats():
    """获取 Case 统计数据（供台账概览卡片使用）

    返回：
    - total: 总用例数
    - analyzed: 已分析数
    - failed: 分析失败数
    - pending: 待分析数
    - avg_confidence: 平均置信度
    - avg_duration: 平均耗时
    """
    try:
        result = svc.get_case_stats()
        return ok(result)
    except Exception as e:
        logger.error("获取 Case 统计失败: %s", e)
        return fail(str(e))


@router.get("/api/v1/observability/cases/{case_id}/report_download")
def download_case_report(case_id: str):
    """下载 Case 报告原始 MD 文件

    查找顺序：case_reports/ → docs/（兼容旧路径）
    """
    from fastapi.responses import FileResponse
    from src.config import PROJECT_ROOT

    # 1. 优先查 case_reports/
    reports_dir = os.path.join(PROJECT_ROOT, "case_reports")
    if os.path.isdir(reports_dir):
        for sub in ("", "pc", "online"):
            path = os.path.join(reports_dir, sub, f"{case_id}.md") if sub else os.path.join(reports_dir, f"{case_id}.md")
            if os.path.isfile(path):
                return FileResponse(path, media_type="text/markdown", filename=f"{case_id}.md")

    # 2. 回退查 docs/{date}/
    docs_dir = os.path.join(PROJECT_ROOT, "docs")
    if os.path.isdir(docs_dir):
        for day in os.listdir(docs_dir):
            day_path = os.path.join(docs_dir, day)
            if not os.path.isdir(day_path):
                continue
            fpath = os.path.join(day_path, f"{case_id}.md")
            if os.path.isfile(fpath):
                return FileResponse(fpath, media_type="text/markdown", filename=f"{case_id}.md")

    return fail(f"未找到报告文件: {case_id}")


@router.post("/api/v1/observability/sync_feishu", response_model=ApiResponse)
def sync_from_feishu():
    """手动触发：从飞书多维表格拉取最新数据并同步到 case_info

    优先使用飞书 API 直接拉取线上数据，失败则回退到本地 CSV/TSV 文件。
    """
    try:
        # 优先尝试 API 直拉
        result = svc.sync_from_feishu_api()
        if result.get("message"):
            # API 失败，回退 CSV
            logger.warning("飞书 API 同步失败，回退 CSV: %s", result.get("message"))
            result = svc.sync_cases_from_csv()
        return ok(result, f"同步完成: 总计 {result.get('total', 0)}, 新增 {result.get('inserted', 0)}, 更新 {result.get('updated', 0)}")
    except Exception as e:
        logger.error("飞书同步失败: %s", e)
        return fail(str(e))


# ── 本地文档缓存（一次性扫描所有已有 MD 文件，避免逐个 find_latest_document）──
_local_doc_set: set = set()     # 已有 MD 文件的 case_id 集合
_local_doc_set_time: float = 0
_LOCAL_DOC_SET_TTL = 300  # 5 分钟


def _get_local_doc_set() -> set:
    """扫描 case_reports/ 目录，返回所有已有 MD 文件的 case_id 集合（带缓存）"""
    import time as _time
    global _local_doc_set, _local_doc_set_time
    now = _time.time()
    if _local_doc_set and (now - _local_doc_set_time) < _LOCAL_DOC_SET_TTL:
        return _local_doc_set

    from src.config import PROJECT_ROOT
    doc_dir = os.path.join(PROJECT_ROOT, _REPORTS_DIR_NAME)
    doc_set = set()
    if os.path.isdir(doc_dir):
        for entry in os.listdir(doc_dir):
            entry_path = os.path.join(doc_dir, entry)
            if os.path.isfile(entry_path) and entry.endswith(".md"):
                doc_set.add(entry[:-3])  # case_reports/{case_id}.md
            elif os.path.isdir(entry_path):
                # case_reports/pc/ 或 case_reports/online/ 子目录
                for fn in os.listdir(entry_path):
                    if fn.endswith(".md"):
                        doc_set.add(fn[:-3])
    _local_doc_set = doc_set
    _local_doc_set_time = now
    logger.info("本地报告集合已缓存: %d 个 (case_reports/)", len(doc_set))
    return doc_set


# ── Bitable 链接映射缓存（避免每次批量拉取都重新获取 6000+ 条记录）──
_bitable_link_map: dict = {}   # {jira_key: feishu_link}
_bitable_link_map_time: float = 0
_BITABLE_LINK_MAP_TTL = 1800  # 30 分钟


def _get_bitable_link_map() -> dict:
    """获取 Bitable jira号 → 飞书链接 映射（带缓存）"""
    import time as _time
    global _bitable_link_map, _bitable_link_map_time
    now = _time.time()
    if _bitable_link_map and (now - _bitable_link_map_time) < _BITABLE_LINK_MAP_TTL:
        return _bitable_link_map

    from src.clients import feishu_client
    from src.config import load_config
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
    if not app_token or not table_id:
        return {}

    logger.info("正在从 Bitable 获取飞书链接映射...")
    records = feishu_client.list_bitable_records(app_token, table_id)
    link_map = {}
    for rec in records:
        fields = rec.get("fields", {})
        jira_raw = fields.get(bugid_field, "")
        if isinstance(jira_raw, list):
            jira_raw = jira_raw[0] if jira_raw else ""
        elif isinstance(jira_raw, dict):
            jira_raw = jira_raw.get("text", "") or jira_raw.get("value", "")
        jira_key = str(jira_raw).strip()
        link_raw = fields.get(report_field, "")
        if isinstance(link_raw, list):
            link_raw = link_raw[0] if link_raw else ""
        elif isinstance(link_raw, dict):
            link_raw = link_raw.get("text", "") or link_raw.get("link", "") or link_raw.get("value", "")
        feishu_link = str(link_raw).strip()
        if jira_key and feishu_link and feishu_link.startswith("http"):
            link_map[jira_key] = feishu_link
    _bitable_link_map = link_map
    _bitable_link_map_time = now
    logger.info("Bitable 链接映射已缓存: %d 条", len(link_map))
    return link_map


# ── 报告专用存储目录 ──
_REPORTS_DIR_NAME = "case_reports"


def _get_reports_dir(source: str = "") -> str:
    """获取报告存储目录: case_reports/{source}/  或 case_reports/"""
    from src.config import PROJECT_ROOT
    if source:
        d = os.path.join(PROJECT_ROOT, _REPORTS_DIR_NAME, source)
    else:
        d = os.path.join(PROJECT_ROOT, _REPORTS_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _download_one_doc(case_id: str, feishu_link: str, source: str = "") -> str:
    """下载单个飞书文档到 case_reports/{source}/ 目录，返回本地路径或空字符串"""
    from src.clients import feishu_client
    doc_id = feishu_client.extract_doc_id_from_url(feishu_link)
    if not doc_id:
        return ""
    feishu_domain = feishu_client.extract_domain_from_url(feishu_link)
    content = feishu_client.fetch_docx_as_markdown(doc_id, bugid=case_id, feishu_domain=feishu_domain)
    if not content or not content.strip():
        return ""
    save_dir = _get_reports_dir(source)
    local_path = os.path.join(save_dir, f"{case_id}.md")
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(content)
    return local_path


@router.post("/api/v1/observability/batch_fetch_reports", response_model=ApiResponse)
async def batch_fetch_reports(limit: int = 20, source: str = ""):
    """批量拉取 AI 分析报告并填充 Case 详情

    source: pc=只拉取parseFullTicket, online=只拉取jira_analyze, 空=全部
    优化：缓存文档集合 + 缓存链接映射 + 10线程并行下载 + 5线程并行解析
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # source → trigger_source 映射
    _SOURCE_MAP = {"pc": "jira_analyze", "online": "parseFullTicket"}
    trigger_filter = _SOURCE_MAP.get(source)  # None = 不过滤

    def _batch_sync():
        from src import db

        session = db._get_session()
        try:
            # 1. 一次性扫描本地已有文档（集合查找 O(1)）
            doc_set = _get_local_doc_set()

            # 2. 查询所有成功 case，按 source 过滤
            q = (
                session.query(db.CaseInfo.case_id, db.CaseInfo.id)
                .filter(
                    db.CaseInfo.is_deleted == False,
                    db.CaseInfo.analysis_result == "成功",
                )
            )
            if trigger_filter:
                q = q.filter(db.CaseInfo.trigger_source == trigger_filter)
            all_rows = q.order_by(db.CaseInfo.finish_time.desc()).all()
            # 快速筛选：本地无文档的 case
            pending = [(r.case_id, r.id) for r in all_rows if r.case_id not in doc_set]
            remaining_total = len(pending)
            fetched_total = len(all_rows) - remaining_total

            # 取本批要处理的
            batch = pending[:limit]
            if not batch:
                return {"total": 0, "success": 0, "skip": 0, "fail": 0,
                        "fetched": fetched_total, "remaining": 0, "details": []}

            # 3. 获取飞书链接映射（带缓存 30min）
            link_map = {}
            try:
                link_map = _get_bitable_link_map()
            except Exception as e:
                logger.warning("获取飞书链接映射失败: %s", e)

            # 4. 并行下载飞书文档（10 线程）
            download_tasks = [(cid, link_map[cid]) for cid, _ in batch if cid in link_map]
            if download_tasks:
                logger.info("并行下载 %d 个飞书文档 (10 线程)...", len(download_tasks))
                with ThreadPoolExecutor(max_workers=10) as pool:
                    futs = {pool.submit(_download_one_doc, cid, link, source): cid for cid, link in download_tasks}
                    for fut in as_completed(futs):
                        cid = futs[fut]
                        try:
                            path = fut.result()
                            if path:
                                doc_set.add(cid)  # 更新本地集合
                                logger.info("[%s] 下载OK", cid)
                        except Exception as e:
                            logger.warning("[%s] 下载失败: %s", cid, e)

            # 5. 并行解析报告（5 线程）
            def _parse_one(case_id: str) -> dict:
                try:
                    result = svc.fetch_and_parse_report(case_id)
                    return {"case_id": case_id, "status": "ok", "source": result.get("source", "")}
                except ValueError as e:
                    return {"case_id": case_id, "status": "skip", "error": str(e)[:100]}
                except Exception as e:
                    return {"case_id": case_id, "status": "fail", "error": str(e)[:100]}

            logger.info("并行解析 %d 个报告 (5 线程)...", len(batch))
            results = []
            with ThreadPoolExecutor(max_workers=5) as pool:
                futs = {pool.submit(_parse_one, cid): cid for cid, _ in batch}
                for fut in as_completed(futs):
                    r = fut.result()
                    results.append(r)

            success_count = sum(1 for r in results if r["status"] == "ok")
            skip_count = sum(1 for r in results if r["status"] == "skip")
            fail_count = sum(1 for r in results if r["status"] == "fail")

            remaining_after = remaining_total - success_count

            # 刷新本地文档缓存，让下次点击立刻识别到新下载的文档
            global _local_doc_set, _local_doc_set_time
            _local_doc_set = set()  # 清空缓存，下次重新扫描
            _local_doc_set_time = 0

            return {"total": len(batch), "success": success_count, "skip": skip_count, "fail": fail_count,
                    "fetched": fetched_total + success_count, "remaining": max(0, remaining_after), "details": results}
        finally:
            session.close()

    try:
        result = await asyncio.to_thread(_batch_sync)
        msg = f"拉取完成: 成功 {result['success']}, 跳过 {result['skip']}, 失败 {result['fail']}"
        return ok(result, msg)
    except Exception as e:
        logger.error("批量拉取报告失败: %s", e)
        return fail(str(e))


# ── 二级页面：Case 接口（兼容旧路径） ──


@router.get("/api/obs/cases", response_model=ApiResponse)
def get_cases(
    page: int = 1,
    page_size: int = 20,
    vcu_number: str = None,
    case_status: str = None,
    backflow_status: str = None,
):
    """分页查询 Case 列表，支持筛选"""
    try:
        result = svc.list_cases(page, page_size, vcu_number, case_status, backflow_status)
        return ok(result)
    except Exception as e:
        logger.error("查询 Case 列表失败: %s", e)
        return fail(str(e))


@router.get("/api/obs/cases/{case_id}", response_model=ApiResponse)
def get_case_detail(case_id: str):
    """获取 Case 完整详情（含 decision_chain / hypothesis_table）"""
    result = svc.get_case(case_id)
    if not result:
        return fail(f"Case 不存在: {case_id}")
    return ok(result)


@router.post("/api/obs/cases", response_model=ApiResponse)
def upsert_case(req: CaseUpsertRequest):
    """创建或更新 Case（按 case_id 去重）"""
    try:
        data = req.model_dump(exclude_none=True)
        result = svc.upsert_case(data)
        return ok(result, "Case 保存成功")
    except Exception as e:
        logger.error("Case upsert 失败: %s", e)
        return fail(str(e))


@router.delete("/api/obs/cases/{case_id}", response_model=ApiResponse)
def delete_case(case_id: str):
    """软删除指定 Case"""
    success = svc.soft_delete_case(case_id)
    if not success:
        return fail(f"Case 不存在或已删除: {case_id}")
    return ok(message="删除成功")


# ── 上传审计接口 ──


@router.get("/api/obs/audits", response_model=ApiResponse)
def get_audits(limit: int = 20):
    """获取最近上传审计记录"""
    try:
        items = svc.list_audits(limit)
        return ok({"items": items, "total": len(items)})
    except Exception as e:
        logger.error("查询审计记录失败: %s", e)
        return fail(str(e))


@router.post("/api/obs/audits/check", response_model=ApiResponse)
def check_hash(req: HashCheckRequest):
    """检查文件哈希是否已存在（去重）"""
    exists = svc.check_hash_exists(req.cos_hash)
    return ok({"exists": exists, "cos_hash": req.cos_hash})


@router.post("/api/obs/audits", response_model=ApiResponse)
def create_audit(req: AuditCreateRequest):
    """创建上传审计记录"""
    try:
        result = svc.create_audit(req.model_dump())
        return ok(result, "审计记录已创建")
    except Exception as e:
        logger.error("创建审计记录失败: %s", e)
        return fail(str(e))


# ── 一键复测（v1 异步任务） ──


@router.post("/api/v1/observability/cases/{case_id}/retest", response_model=ApiResponse)
def trigger_retest_v1(case_id: str):
    """触发一键复测（后台线程执行，立即返回 task_id）

    复用项目既有模式：threading.Thread(daemon=True) + 状态字典轮询。
    Worker 内部调用 diana_client._llm_chat() 进行 AI 分析。
    """
    # 检查 Case 是否存在
    case = svc.get_case(case_id)
    if not case:
        return fail(f"Case 不存在: {case_id}")

    # 创建任务并启动后台线程
    result = svc.create_retest_task(case_id)
    return ok(result, "复测任务已提交")


@router.get("/api/v1/observability/tasks/{task_id}", response_model=ApiResponse)
def get_task_status(task_id: str):
    """查询复测任务进度（供前端轮询）

    返回字段：status(pending/processing/success/failed), progress(0-100), message
    """
    task = svc.get_retest_task(task_id)
    if not task:
        return fail(f"任务不存在: {task_id}")
    # 只返回前端需要的字段
    return ok({
        "task_id": task["task_id"],
        "case_id": task["case_id"],
        "status": task["status"],
        "progress": task["progress"],
        "message": task["message"],
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at"),
    })


# ── 一键复测（兼容旧路径） ──

_retest_status: dict = {}


@router.post("/api/obs/retest/{case_id}", response_model=ApiResponse)
def trigger_retest(case_id: str):
    """触发一键复测（兼容旧路径，内部复用 v1 任务机制）"""
    case = svc.get_case(case_id)
    if not case:
        return fail(f"Case 不存在: {case_id}")
    result = svc.create_retest_task(case_id)
    # 兼容旧接口返回格式
    _retest_status[case_id] = {"status": "running", "message": "复测任务已提交，正在执行..."}
    return ok({"case_id": case_id, "task_id": result["task_id"], "status": "running"}, "复测任务已提交")


@router.get("/api/obs/retest/{case_id}/status", response_model=ApiResponse)
def get_retest_status(case_id: str):
    """轮询复测任务状态（兼容旧路径）"""
    status = _retest_status.get(case_id)
    if not status:
        return fail(f"未找到复测任务: {case_id}")
    return ok({"case_id": case_id, **status})


# ── 诊断管线（复用 troubleshoot 完整诊断流程） ──


@router.post("/api/v1/observability/cases/{case_id}/diagnose", response_model=ApiResponse)
def trigger_diagnose(case_id: str):
    """触发诊断管线（后台线程执行完整诊断 Steps 0-9）"""
    case = svc.get_case(case_id)
    if not case:
        return fail(f"Case 不存在: {case_id}")
    result = svc.create_diagnose_task(case_id)
    if "error" in result:
        return fail(result["error"])
    return ok(result, "诊断任务已提交")


@router.get("/api/v1/observability/cases/{case_id}/diagnose/status", response_model=ApiResponse)
def get_diagnose_status(case_id: str):
    """查询诊断状态：返回该 case 最新的诊断任务状态"""
    # 查找最新的 diag_ 开头的任务
    tasks = svc.get_retest_tasks_snapshot()
    latest = None
    for tid, task in tasks.items():
        if tid.startswith("diag_") and task.get("case_id") == case_id:
            if latest is None or task.get("started_at", "") > latest.get("started_at", ""):
                latest = task
    if not latest:
        # 检查是否有本地诊断缓存
        from src.services.report_ops import _load_diagnose_cache
        cached = _load_diagnose_cache(case_id)
        if cached:
            return ok({
                "status": "cached",
                "message": "已有诊断缓存结果",
                "result": cached,
            })
        return fail(f"未找到诊断任务: {case_id}")
    return ok({
        "task_id": latest["task_id"],
        "case_id": latest["case_id"],
        "status": latest["status"],
        "progress": latest["progress"],
        "message": latest["message"],
        "started_at": latest.get("started_at"),
        "finished_at": latest.get("finished_at"),
    })


# ── 拉取最新 Case（从 docs/ CSV 增量同步） ──


@router.post("/api/v1/observability/sync", response_model=ApiResponse)
def sync_cases():
    """从 docs/ 目录扫描 CSV 文件，增量同步到 Case 数据库

    返回 {"total": int, "inserted": int, "skipped": int}
    """
    try:
        result = svc.sync_cases_from_csv()
        inserted = result.get("inserted", 0)
        total = result.get("total", 0)
        skipped = result.get("skipped", 0)
        msg = f"同步完成: 扫描 {total} 条, 新增 {inserted} 条, 跳过 {skipped} 条(已存在)"
        return ok(result, msg)
    except Exception as e:
        logger.error("同步 Case 失败: %s", e)
        return fail(str(e))

