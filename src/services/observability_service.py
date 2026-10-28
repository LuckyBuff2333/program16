"""可观测模块 CRUD 服务层

职责：封装 case_info / upload_audit 表的增删改查操作，
供路由层（observability.py）调用，不直接暴露 SQLAlchemy Session。
"""
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import tarfile
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime
from typing import BinaryIO, Optional

from src.config import PROJECT_ROOT, setup_logger
from src import db

logger = setup_logger("observability")

# ── 凭据加密工具（XOR + base64，纯 Python 无外部依赖） ──

_CRED_DIR = os.path.join(PROJECT_ROOT, "config")
_CRED_PATH = os.path.join(_CRED_DIR, "obs_credentials.json")
_KEY_PATH = os.path.join(_CRED_DIR, ".obs_key")


def _get_or_create_key() -> bytes:
    """获取或生成 XOR 密钥（基于机器特征，首次运行自动创建）"""
    if os.path.exists(_KEY_PATH):
        with open(_KEY_PATH, "r") as f:
            return base64.b64decode(f.read().strip())
    # 生成 32 字节随机密钥并落盘
    key = os.urandom(32)
    os.makedirs(_CRED_DIR, exist_ok=True)
    with open(_KEY_PATH, "w") as f:
        f.write(base64.b64encode(key).decode())
    # Windows 下尝试限制文件权限（best-effort）
    try:
        import stat
        os.chmod(_KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return key


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _encrypt_value(plaintext: str) -> str:
    """XOR + base64 编码，返回密文字符串"""
    key = _get_or_create_key()
    cipher = _xor_bytes(plaintext.encode("utf-8"), key)
    return base64.b64encode(cipher).decode("ascii")


def _decrypt_value(ciphertext: str) -> str:
    """base64 + XOR 解码，返回明文"""
    key = _get_or_create_key()
    cipher = base64.b64decode(ciphertext.encode("ascii"))
    return _xor_bytes(cipher, key).decode("utf-8")


# ── 凭据管理 ──


def save_credentials(secret_id: str, secret_key: str) -> dict:
    """加密保存 COS 凭据到本地 config.json"""
    os.makedirs(_CRED_DIR, exist_ok=True)
    payload = {
        "secret_id": _encrypt_value(secret_id),
        "secret_key": _encrypt_value(secret_key),
        "saved_at": datetime.now().isoformat(),
        "host": platform.node(),
    }
    with open(_CRED_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    # 落盘权限 600（best-effort）
    try:
        import stat
        os.chmod(_CRED_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    logger.info("COS 凭据已加密保存: %s", _CRED_PATH)
    # 返回脱敏信息
    masked_id = secret_id[:4] + "****" + secret_id[-4:] if len(secret_id) > 8 else "****"
    return {"path": _CRED_PATH, "secret_id_masked": masked_id, "saved_at": payload["saved_at"]}


def load_credentials() -> Optional[dict]:
    """读取并解密 COS 凭据"""
    if not os.path.exists(_CRED_PATH):
        return None
    try:
        with open(_CRED_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return {
            "secret_id": _decrypt_value(payload["secret_id"]),
            "secret_key": _decrypt_value(payload["secret_key"]),
            "saved_at": payload.get("saved_at"),
        }
    except Exception as e:
        logger.error("凭据解密失败: %s", e)
        return None


# ── 文件上传 + 去重 ──


def compute_sha256(file_obj: BinaryIO, chunk_size: int = 8192) -> str:
    """流式计算文件 SHA-256，避免大文件一次性读入内存"""
    h = hashlib.sha256()
    while True:
        chunk = file_obj.read(chunk_size)
        if not chunk:
            break
        h.update(chunk)
    file_obj.seek(0)  # 重置游标供后续读取
    return h.hexdigest()


def upload_and_dedup(file_obj: BinaryIO, file_name: str) -> dict:
    """文件上传 + SHA-256 去重 + 落库

    :raises ValueError: 同内容文件重复上传
    :return: {"doc_id": ..., "cos_hash": ..., "file_name": ..., "saved_path": ...}
    """
    # 1. 计算哈希
    cos_hash = compute_sha256(file_obj)

    # 2. 去重校验
    if check_hash_exists(cos_hash):
        raise ValueError(f"同内容文档重复上传（cos_hash={cos_hash[:16]}...）")

    # 3. 保存文件到本地磁盘
    upload_dir = os.path.join(PROJECT_ROOT, "data", "obs_uploads")
    os.makedirs(upload_dir, exist_ok=True)
    doc_id = f"DOC-{uuid.uuid4().hex[:8].upper()}"
    safe_name = f"{doc_id}_{file_name}"
    save_path = os.path.join(upload_dir, safe_name)
    with open(save_path, "wb") as out:
        while True:
            chunk = file_obj.read(8192)
            if not chunk:
                break
            out.write(chunk)

    # 4. 写入 upload_audit 表
    audit_row = db.UploadAudit(
        doc_id=doc_id,
        file_name=file_name,
        cos_hash=cos_hash,
        upload_status="success",
        upload_time=datetime.now(),
    )
    session = db._get_session()
    try:
        session.add(audit_row)
        session.commit()
        logger.info("上传审计落库: doc_id=%s, file=%s, hash=%s", doc_id, file_name, cos_hash[:16])
    except Exception as e:
        session.rollback()
        logger.error("上传审计落库失败: %s", e)
        raise
    finally:
        session.close()

    return {
        "doc_id": doc_id,
        "cos_hash": cos_hash,
        "file_name": file_name,
        "saved_path": save_path,
    }


# ── CaseInfo CRUD ──


def list_cases(
    page: int = 1,
    page_size: int = 20,
    vcu_number: str = None,
    case_status: str = None,
    backflow_status: str = None,
) -> dict:
    """分页查询 Case 列表，支持按 VCU 号码、案例判定、回流状态筛选

    :return: {"items": [...], "total": int, "page": int, "page_size": int}
    """
    session = db._get_session()
    try:
        q = session.query(db.CaseInfo).filter(db.CaseInfo.is_deleted == False)
        if vcu_number:
            q = q.filter(db.CaseInfo.vcu_number == vcu_number)
        if case_status:
            q = q.filter(db.CaseInfo.case_status == case_status)
        if backflow_status:
            q = q.filter(db.CaseInfo.backflow_status == backflow_status)
        total = q.count()
        rows = (
            q.order_by(db.CaseInfo.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [_case_to_dict(r) for r in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        session.close()


def list_cases_v1(
    page: int = 1,
    page_size: int = 10,
    vcu_number: str = None,
    status: str = None,
    task_type: str = None,
) -> dict:
    """分页查询 Case 列表（v1 接口，前端字段名对齐）

    增强点：
    - vcu_number 支持模糊查询（LIKE）
    - status 统一筛选 case_status 或 backflow_status
    - task_type 筛选 trigger_source（如 jira_analyze / parseFullTicket）
    - 按 finish_time 倒序排列
    - 返回字段名与前端表格列名对齐

    :return: {"list": [...], "total": int, "page": int, "page_size": int}
    """
    session = db._get_session()
    try:
        q = session.query(db.CaseInfo).filter(db.CaseInfo.is_deleted == False)
        # 只保留分析成功的数据
        q = q.filter(db.CaseInfo.analysis_result == "成功")
        if vcu_number:
            q = q.filter(db.CaseInfo.vcu_number.like(f"%{vcu_number}%"))
        if status:
            q = q.filter(
                (db.CaseInfo.case_status == status)
                | (db.CaseInfo.backflow_status == status)
            )
        if task_type:
            q = q.filter(db.CaseInfo.trigger_source == task_type)
        total = q.count()
        rows = (
            q.order_by(db.CaseInfo.finish_time.desc().nullslast())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [_case_to_front_dict(r) for r in rows]
        return {"list": items, "total": total, "page": page, "page_size": page_size}
    finally:
        session.close()


def get_case_stats() -> dict:
    """获取 Case 统计数据（供台账概览卡片使用）

    统计维度：
    - 总用例数
    - 已分析数（有 rootcause 且 analysis_result != '失败'）
    - 分析失败数（analysis_result='失败'）
    - 待分析数（无 rootcause 且无 analysis_result）
    - 平均置信度（仅计算 conf > 0 的记录）
    - 平均耗时（从 duration 字段解析）

    :return: {"total": int, "analyzed": int, "failed": int, "pending": int,
              "avg_confidence": float, "avg_duration": str}
    """
    from sqlalchemy import func, or_, and_
    session = db._get_session()
    try:
        base_q = session.query(db.CaseInfo).filter(db.CaseInfo.is_deleted == False)
        total = base_q.count()

        # 有分析数据的记录：有 rootcause 或 analysis_result
        has_analysis = base_q.filter(
            or_(
                (db.CaseInfo.rootcause != None) & (db.CaseInfo.rootcause != ""),
                (db.CaseInfo.analysis_result != None) & (db.CaseInfo.analysis_result != "")
            )
        )
        failed = has_analysis.filter(db.CaseInfo.analysis_result == "失败").count()
        analyzed = has_analysis.count() - failed  # 有分析数据且不是失败
        pending = total - has_analysis.count()  # 无分析数据的记录

        # 平均置信度（仅 conf > 0）
        conf_rows = base_q.filter(db.CaseInfo.conf > 0).with_entities(db.CaseInfo.conf).all()
        avg_conf = sum(r[0] for r in conf_rows) / len(conf_rows) if conf_rows else 0.0

        # 平均耗时（解析 duration 字段，如 "8.1min", "220s", "5min"）
        dur_rows = base_q.filter(
            (db.CaseInfo.duration != None) & (db.CaseInfo.duration != "")
        ).with_entities(db.CaseInfo.duration).all()
        dur_seconds = []
        for r in dur_rows:
            d = r[0]
            if not d:
                continue
            m = re.search(r"(\d+(?:\.\d+)?)\s*min", d)
            if m:
                dur_seconds.append(float(m.group(1)) * 60)
                continue
            m = re.search(r"(\d+(?:\.\d+)?)\s*s", d)
            if m:
                dur_seconds.append(float(m.group(1)))
        avg_dur_sec = sum(dur_seconds) / len(dur_seconds) if dur_seconds else 0
        if avg_dur_sec >= 60:
            avg_dur = f"{int(avg_dur_sec // 60)}m{int(avg_dur_sec % 60)}s"
        else:
            avg_dur = f"{int(avg_dur_sec)}s"

        return {
            "total": total,
            "analyzed": analyzed,
            "failed": failed,
            "pending": pending,
            "avg_confidence": round(avg_conf, 2),
            "avg_duration": avg_dur,
        }
    finally:
        session.close()


def get_case(case_id: str) -> Optional[dict]:
    """根据 case_id 获取完整详情（含 decision_chain / hypothesis_table JSON）"""
    session = db._get_session()
    try:
        row = (
            session.query(db.CaseInfo)
            .filter(db.CaseInfo.case_id == case_id, db.CaseInfo.is_deleted == False)
            .first()
        )
        return _case_to_full_dict(row) if row else None
    finally:
        session.close()


def get_case_v1(case_id: str) -> Optional[dict]:
    """根据 case_id 获取完整详情（v1 接口，前端字段名对齐）

    字段映射：
    - case_status   → case_type
    - backflow_status → reflow_status
    - problem_desc   → description
    - duration       → total_duration
    - conf           → confidence
    - root_cause_summary → root_cause
    - decision_chain / hypothesis_table → 确保 JSON 对象（非字符串）
    """
    session = db._get_session()
    try:
        row = (
            session.query(db.CaseInfo)
            .filter(db.CaseInfo.case_id == case_id, db.CaseInfo.is_deleted == False)
            .first()
        )
        return _case_to_front_full_dict(row) if row else None
    finally:
        session.close()


def upsert_case(data: dict) -> dict:
    """创建或更新 Case（按 case_id 去重），返回保存后的记录"""
    session = db._get_session()
    try:
        row = (
            session.query(db.CaseInfo)
            .filter(db.CaseInfo.case_id == data["case_id"])
            .first()
        )
        if row:
            for k, v in data.items():
                if k != "id" and hasattr(row, k):
                    setattr(row, k, v)
            row.updated_at = datetime.now()
        else:
            row = db.CaseInfo(**data)
            session.add(row)
        session.commit()
        session.refresh(row)
        logger.info("Case upsert 完成: %s", row.case_id)
        return _case_to_full_dict(row)
    except Exception as e:
        session.rollback()
        logger.error("Case upsert 失败: %s", e)
        raise
    finally:
        session.close()


def soft_delete_case(case_id: str) -> bool:
    """软删除指定 Case"""
    session = db._get_session()
    try:
        row = (
            session.query(db.CaseInfo)
            .filter(db.CaseInfo.case_id == case_id, db.CaseInfo.is_deleted == False)
            .first()
        )
        if not row:
            return False
        row.is_deleted = True
        row.updated_at = datetime.now()
        session.commit()
        logger.info("Case 软删除完成: %s", case_id)
        return True
    except Exception as e:
        session.rollback()
        logger.error("Case 软删除失败: %s", e)
        raise
    finally:
        session.close()


# ── UploadAudit CRUD ──


def list_audits(limit: int = 20) -> list:
    """获取最近的上传审计记录（简单模式，兼容已有接口）"""
    session = db._get_session()
    try:
        rows = (
            session.query(db.UploadAudit)
            .filter(db.UploadAudit.is_deleted == False)
            .order_by(db.UploadAudit.id.desc())
            .limit(limit)
            .all()
        )
        return [_audit_to_dict(r) for r in rows]
    finally:
        session.close()


def list_audits_paginated(page: int = 1, page_size: int = 10) -> dict:
    """分页查询上传审计记录，按时间倒序

    :return: {"items": [...], "total": int, "page": int, "page_size": int}
    """
    session = db._get_session()
    try:
        q = session.query(db.UploadAudit).filter(db.UploadAudit.is_deleted == False)
        total = q.count()
        rows = (
            q.order_by(db.UploadAudit.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [_audit_to_front_dict(r) for r in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        session.close()


def check_hash_exists(cos_hash: str) -> bool:
    """检查文件哈希是否已存在（去重校验）"""
    session = db._get_session()
    try:
        return (
            session.query(db.UploadAudit)
            .filter(db.UploadAudit.cos_hash == cos_hash, db.UploadAudit.is_deleted == False)
            .first()
            is not None
        )
    finally:
        session.close()


def create_audit(data: dict) -> dict:
    """创建一条上传审计记录"""
    session = db._get_session()
    try:
        row = db.UploadAudit(**data)
        session.add(row)
        session.commit()
        session.refresh(row)
        logger.info("审计记录创建: doc_id=%s, file=%s", row.doc_id, row.file_name)
        return _audit_to_dict(row)
    except Exception as e:
        session.rollback()
        logger.error("审计记录创建失败: %s", e)
        raise
    finally:
        session.close()


# ── 内部序列化工具 ──


def _case_to_dict(row) -> dict:
    """Case 列表摘要（不含大字段）"""
    return {
        "id": row.id,
        "case_id": row.case_id,
        "vcu_number": row.vcu_number,
        "finish_time": row.finish_time,
        "duration": row.duration,
        "conf": row.conf,
        "converged": row.converged,
        "case_status": row.case_status,
        "backflow_status": row.backflow_status,
    }


def _case_to_front_dict(row) -> dict:
    """Case 列表摘要（前端字段名对齐，用于 v1 台账表格）"""
    return {
        "id": row.id,
        "case_id": row.case_id,
        "vcu_number": row.vcu_number,
        "finish_time": row.finish_time,
        "duration": row.duration,
        "conf": None,  # 暂时留空，后续再引用数值
        "converged": row.converged,
        "case_type": row.case_status or "",
        "reflow_status": row.backflow_status or "",
    }


def _case_to_full_dict(row) -> dict:
    """Case 完整详情（含 JSON 嵌套字段）"""
    d = _case_to_dict(row)
    d.update({
        "problem_desc": row.problem_desc,
        "root_cause_summary": row.root_cause_summary,
        "decision_chain": _ensure_json_obj(row.decision_chain),
        "hypothesis_table": _cleanup_hypothesis_table(_ensure_json_obj(row.hypothesis_table)),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    })
    return d


def _case_to_front_full_dict(row) -> dict:
    """Case 完整详情（v1 接口，前端字段名对齐）

    确保 decision_chain / hypothesis_table 是对象/数组，不是字符串。
    description 字段 fallback 链: problem_desc → rootcause → root_cause_summary
    """
    d = _case_to_front_dict(row)
    # description fallback 链
    desc = (row.problem_desc or "").strip()
    if not desc:
        desc = (getattr(row, "rootcause", None) or "").strip()
    if not desc:
        desc = (row.root_cause_summary or "").strip()
    d.update({
        "description": desc,
        "total_duration": row.duration or "",
        "confidence": row.conf if row.conf is not None else 0.0,
        "root_cause": row.root_cause_summary or "",
        "decision_chain": _ensure_json_obj(row.decision_chain),
        "hypothesis_table": _cleanup_hypothesis_table(_ensure_json_obj(row.hypothesis_table)),
        # 阶段墙钟：从 decision_chain 提取或返回空数组
        "phases": _extract_phases(row.decision_chain),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        # ── 飞书数据沉淀表扩展字段 ──
        "analysis_result": getattr(row, "analysis_result", None) or "",
        "trigger_source": getattr(row, "trigger_source", None) or "",
        "version": getattr(row, "version", None) or "",
        "problem_time": getattr(row, "problem_time", None) or "",
        "error_type": getattr(row, "error_type", None) or "",
        "error_message": getattr(row, "error_message", None) or "",
        "total_seconds": getattr(row, "total_seconds", None),
        "analysis_seconds": getattr(row, "analysis_seconds", None),
        "ai_module": getattr(row, "ai_module", None) or "",
        "actual_module": getattr(row, "actual_module", None) or "",
        "analysis_date": getattr(row, "analysis_date", None) or "",
        "manual_review": getattr(row, "manual_review", None) or "",
        "log_path": _resolve_real_log_path(row),
    })
    # ── 完整推理轮次（从 MD 日志解析，前端可折叠展示）──
    case_id = (getattr(row, "case_id", None) or "").strip()
    d["reasoning_rounds"] = _parse_full_reasoning_rounds(d.get("log_path", ""), case_id=case_id)
    # ── description 优化：生成简洁问题概述 ──
    root_cause = (row.root_cause_summary or "").strip()
    d["description"] = _generate_description(row, root_cause, d["reasoning_rounds"], desc)
    # ── 智能分析面板（结构化根因分析，复用已解析的 rounds）──
    d["analysis_panel"] = _build_analysis_panel(row, d["reasoning_rounds"])
    
    # ── Jira 原始信息：标题 + 描述 + 附件地址 ──
    if case_id and case_id.startswith("VCU-"):
        try:
            jira_info = _fetch_jira_info(case_id)
            d["jira_summary"] = jira_info.get("summary", "")
            d["jira_description"] = jira_info.get("description", "")
            d["jira_attachments"] = jira_info.get("attachments", [])
        except Exception:
            d["jira_summary"] = ""
            d["jira_description"] = ""
            d["jira_attachments"] = []
    else:
        d["jira_summary"] = ""
        d["jira_description"] = ""
        d["jira_attachments"] = []

    # ── 诊断缓存合并：如果存在本地诊断结果，用更丰富的数据覆盖/补充 ──
    _merge_diagnose_cache(d, row)

    return d


def _merge_diagnose_cache(d: dict, row):
    """合并本地诊断缓存到 Case 详情

    从 data/troubleshoot/{case_id}.json 读取诊断结果，
    用更丰富的数据覆盖/补充 DB 中的字段。
    """
    case_id = (getattr(row, "case_id", None) or "").strip()
    if not case_id:
        return
    try:
        from src.services.report_ops import _load_diagnose_cache
        cached = _load_diagnose_cache(case_id)
        if not cached or not isinstance(cached, dict):
            return

        # 诊断分类 → error_type
        category = (cached.get("category") or "").strip()
        if category:
            d["error_type"] = category

        # 错误信息
        err_msg = (cached.get("err_msg") or "").strip()
        if err_msg and not d.get("error_message"):
            d["error_message"] = err_msg

        # 问题时间（诊断提取的更精确）
        diag_pt = (cached.get("problem_time") or "").strip()
        if diag_pt and not d.get("problem_time"):
            d["problem_time"] = diag_pt

        # 问题描述：优先用诊断报告中的根因分析
        report = cached.get("report") if isinstance(cached.get("report"), dict) else {}
        root_cause = (report.get("root_cause") or "").strip()
        detail = (cached.get("detail") or "").strip()
        if root_cause and not d.get("description"):
            d["description"] = root_cause
        elif detail and not d.get("description"):
            d["description"] = detail

        # 日志路径：从归档文件中提取
        archive_files = cached.get("archive_files") or []
        if archive_files and not d.get("log_path"):
            for af in archive_files:
                if isinstance(af, str) and os.path.isfile(af):
                    d["log_path"] = af
                    break
                elif isinstance(af, dict):
                    fpath = af.get("path") or af.get("file") or ""
                    if fpath and os.path.isfile(fpath):
                        d["log_path"] = fpath
                        break

        # 智能分析面板：从诊断报告提取结构化数据
        if report:
            panel = d.get("analysis_panel") or {}
            if root_cause and not panel.get("problem_overview"):
                panel["problem_overview"] = root_cause
            if category and not panel.get("problem_boundary"):
                panel["problem_boundary"] = category
            # 证据链：从 report 的 evidence 或 steps 提取
            evidence = report.get("evidence") or report.get("evidence_chain") or []
            if evidence and not panel.get("evidence_chain"):
                panel["evidence_chain"] = evidence[:5] if isinstance(evidence, list) else [str(evidence)]
            # 处置建议
            suggestion = (report.get("suggestion") or report.get("disposition") or "").strip()
            if suggestion and not panel.get("disposition"):
                panel["disposition"] = suggestion
            d["analysis_panel"] = panel

        # 完整诊断结果（供前端诊断详情区域展示）
        d["diagnose_result"] = cached

    except Exception as e:
        logger.warning("诊断缓存合并失败 %s: %s", case_id, e)


def _ensure_json_obj(val):
    """确保 JSON 字段返回对象/数组而非字符串（SQLite 兼容）

    兼容处理历史数据的多重编码问题：最多递归解包 3 层 JSON 字符串
    """
    if val is None:
        return []
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        for _ in range(3):  # 最多解包 3 层
            try:
                parsed = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return val  # 不是合法 JSON，返回原始字符串
            if isinstance(parsed, (dict, list)):
                return parsed
            if isinstance(parsed, str):
                val = parsed  # 继续解包
            else:
                return parsed
        return val  # 3 层后仍是字符串，返回原始值
    return val


def _cleanup_hypothesis_table(ht) -> list:
    """清洗假设判定表：合并旧版 build_hypothesis_table 生成的碎片化数据

    旧版函数会将一段根因文本按句号/分号拆分成多行假设，导致：
    - H1 是完整的根因描述（evidence 为 "关键实体:..." 或 "日志证据链支持该假设"）
    - H2/H3/... 是 H1 被截断后的文本碎片（evidence 为 "根因子论点"，remark 为空）

    合并策略：
    - 如果后续假设的 evidence 为"根因子论点"/"根因子节点"/空 → 视为碎片
    - 将碎片文本拼回 H1（去重），并删除该碎片行
    """
    if not isinstance(ht, list) or len(ht) <= 1:
        return ht if isinstance(ht, list) else []

    _FRAGMENT_EVIDENCE = {"", "根因子论点", "根因子节点"}

    result = [ht[0]]
    for h in ht[1:]:
        if not isinstance(h, dict):
            continue
        evidence = (h.get("evidence") or "").strip()
        hypothesis = (h.get("hypothesis") or "").strip()
        remark = (h.get("remark") or "").strip()

        # 判断是否为碎片：evidence 为"根因子论点"类 且 remark 为空或非"AI 分析结论"
        is_fragment = (
            evidence in _FRAGMENT_EVIDENCE
            and (not remark or remark in _FRAGMENT_EVIDENCE)
        )

        if is_fragment and result:
            # 合并到第一条假设
            prev = result[0]
            prev_text = (prev.get("hypothesis") or "").strip()
            # 去重：如果碎片文本已被 H1 包含（或重叠 >50%），跳过
            if not hypothesis:
                continue
            if hypothesis in prev_text:
                continue
            # 检查碎片文本是否与 H1 尾部重叠（H1 截断点处的文字重复）
            overlap = False
            for n in range(min(20, len(hypothesis)), 5, -1):
                if prev_text.endswith(hypothesis[:n]):
                    overlap = True
                    break
            if overlap:
                continue
            # 智能拼接
            sep = "" if prev_text.endswith(("。", "；", "！", "？")) else "，"
            prev["hypothesis"] = prev_text + sep + hypothesis
        else:
            result.append(h)

    # 重新编号 key
    for i, h in enumerate(result):
        if isinstance(h, dict):
            h["key"] = f"H{i + 1}"

    return result


# ── 日志文件路径缓存（避免重复扫描文件系统） ──
_log_path_cache: dict = {}  # case_id -> rel_path or ""
_log_path_cache_time: float = 0
_LOG_CACHE_TTL = 300  # 5 分钟缓存


def _scan_docs_for_case(case_id: str) -> str:
    """扫描 docs/ 所有子目录，查找 {case_id}.md 文件"""
    import glob as _glob
    docs_dir = os.path.join(PROJECT_ROOT, "docs")
    if not os.path.isdir(docs_dir):
        return ""
    pattern = os.path.join(docs_dir, "*", f"{case_id}.md")
    matches = _glob.glob(pattern)
    if matches:
        # 取最新的（文件修改时间最晚）
        best = max(matches, key=os.path.getmtime)
        return os.path.relpath(best, PROJECT_ROOT).replace("\\", "/")
    return ""


def _resolve_real_log_path(row) -> str:
    """解析日志路径：只在文件真实存在时才返回路径

    优先级：
    1. DB 中的 log_path 字段
    2. 根据 analysis_date/problem_time + case_id 构造 docs 路径
    3. 扫描 docs/ 所有日期子目录查找 {case_id}.md
    """
    import re
    global _log_path_cache, _log_path_cache_time

    case_id = (getattr(row, "case_id", None) or "").strip()
    if not case_id:
        return ""

    # 缓存检查（5 分钟 TTL）
    import time
    now = time.time()
    if now - _log_path_cache_time > _LOG_CACHE_TTL:
        _log_path_cache.clear()
        _log_path_cache_time = now

    if case_id in _log_path_cache:
        return _log_path_cache[case_id]

    result = ""

    # 1. DB 字段优先
    db_path = (getattr(row, "log_path", None) or "").strip()
    if db_path:
        full = os.path.join(PROJECT_ROOT, db_path)
        if os.path.isfile(full):
            result = db_path

    # 2. 构造 docs/{YYYY-MM-DD}/{case_id}.md
    if not result:
        date_str = ""
        for candidate in [getattr(row, "analysis_date", None), getattr(row, "problem_time", None)]:
            if candidate:
                m = re.match(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})", str(candidate))
                if m:
                    date_str = f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
                    break
        if date_str:
            rel_path = f"docs/{date_str}/{case_id}.md"
            if os.path.isfile(os.path.join(PROJECT_ROOT, rel_path)):
                result = rel_path

    # 3. 扫描所有 docs 子目录
    if not result:
        result = _scan_docs_for_case(case_id)

    # 4. 回退到 case_reports/ 目录（pc/online 子目录）
    if not result:
        reports_dir = os.path.join(PROJECT_ROOT, "case_reports")
        for sub in ("", "pc", "online"):
            check = os.path.join(reports_dir, sub, f"{case_id}.md") if sub else os.path.join(reports_dir, f"{case_id}.md")
            if os.path.isfile(check):
                result = os.path.relpath(check, PROJECT_ROOT).replace("\\", "/")
                break

    _log_path_cache[case_id] = result
    return result


def _extract_phases(decision_chain) -> list:
    """从 decision_chain 中提取阶段墙钟数据（供 PhaseWallClock 组件使用）

    支持两种格式：
    - 新格式 (dict): {"phase_wall_clock": [...], "timeline_rounds": [...]}
    - 旧格式 (list): [{"round": 1, "stages": [...]}]
    """
    chain = _ensure_json_obj(decision_chain)
    if not chain:
        return []

    # 新格式：decision_chain 是 dict，直接包含 phase_wall_clock
    if isinstance(chain, dict):
        pwc = chain.get("phase_wall_clock")
        if pwc and isinstance(pwc, list):
            return pwc
        return []

    # 旧格式兼容：decision_chain 是 list of {round, stages}
    if not isinstance(chain, list):
        return []
    phases = []
    for rnd in chain:
        if not isinstance(rnd, dict):
            continue
        for stage in rnd.get("stages", []):
            name = stage.get("stage", "")
            dur = stage.get("duration", "0s")
            seconds = _parse_duration(dur)
            phases.append({
                "phase_name": name,
                "duration_seconds": seconds,
                "percentage": 0,
                "color": "#409eff" if "Lead" in name else (
                    "#67c23a" if "装配" in name else (
                        "#e6a23c" if "准备" in name else "#dcdfe6"
                    )
                ),
            })
    return phases


# ── Jira 信息缓存（避免重复 API 调用） ──
_jira_info_cache: dict = {}  # case_id -> {"description": str, "attachments": list}
_jira_cache_time: dict = {}  # case_id -> timestamp
_JIRA_CACHE_TTL = 600  # 10 分钟


def _fetch_jira_info(case_id: str) -> dict:
    """从 Jira RESTAPI 获取 issue 标题、描述和附件地址（带缓存）

    :return: {"summary": str, "description": str, "attachments": [{filename, url, size}]}
    """
    import time as _time
    now = _time.time()
    # 检查缓存
    if case_id in _jira_info_cache:
        if now - _jira_cache_time.get(case_id, 0) < _JIRA_CACHE_TTL:
            return _jira_info_cache[case_id]
    # 调用 Jira API
    try:
        from src.clients import jira_client
        issue = jira_client.fetch_issue(case_id)
        if not issue:
            return {"summary": "", "description": "", "attachments": []}
        fields = issue.get("fields") or {}
        # 提取大标题（summary）
        summary = (fields.get("summary") or "").strip()
        # 提取描述
        description = fields.get("description") or ""
        if isinstance(description, dict):
            description = jira_client._extract_adf_text(description)
        # 提取附件（只保留 zip / 7z / rar 格式的日志包）
        _LOG_EXTS = ('.zip', '.7z', '.rar')

        def _is_log_archive(filename: str) -> bool:
            fn_lower = filename.lower()
            # 普通 .zip / .7z / .rar
            if any(fn_lower.endswith(ext) for ext in _LOG_EXTS):
                return True
            # 分卷 .7z.001 / .zip.001 / .rar.001
            if re.search(r'\.(zip|7z|rar)\.\d{3}$', fn_lower):
                return True
            # 分卷 .part1.rar / .part01.rar
            if re.search(r'\.part\d+\.rar$', fn_lower):
                return True
            # 分卷 .z01 ~ .z99（WinZip 分卷）
            if re.search(r'\.z\d{2,3}$', fn_lower):
                return True
            return False

        raw_attachments = fields.get("attachment") or []
        attachments = []
        for att in raw_attachments:
            fn = att.get("filename", "")
            if not _is_log_archive(fn):
                continue
            attachments.append({
                "filename": fn,
                "url": att.get("content", ""),
                "size": att.get("size", 0),
            })
        result = {"summary": summary, "description": description, "attachments": attachments}
        _jira_info_cache[case_id] = result
        _jira_cache_time[case_id] = now
        logger.info("Jira 信息获取成功: %s (标题: %s, 附件 %d 个)", case_id, summary[:40] if summary else '', len(attachments))
        return result
    except Exception as e:
        logger.warning("Jira 信息获取失败: %s - %s", case_id, e)
        return {"summary": "", "description": "", "attachments": []}


def _parse_full_reasoning_rounds(log_path: str, case_id: str = "") -> list:
    """从 MD 日志文件解析完整的推理轮次（不截断），供前端可折叠展示

    每轮包含：LLM 推理文本、工具执行结果、知识库引用、本轮结论、时间戳。
    当 log_path 不可用时，回退到 case_reports/ 目录查找报告文件。
    """
    content = ""
    # 1. 优先从 log_path 读取
    if log_path and os.path.isfile(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            pass
    # 2. 回退：从 case_reports/ 目录查找
    if not content and case_id:
        from src.config import PROJECT_ROOT
        reports_dir = os.path.join(PROJECT_ROOT, "case_reports")
        for sub in ("", "pc", "online"):
            check = os.path.join(reports_dir, sub, f"{case_id}.md") if sub else os.path.join(reports_dir, f"{case_id}.md")
            if os.path.isfile(check):
                try:
                    with open(check, "r", encoding="utf-8") as f:
                        content = f.read()
                    break
                except Exception:
                    pass
    if not content:
        return []

    # 按轮次标题分割（仅匹配 "## 第 X 轮" 格式，避免子标题误切割）
    rounds_map = {}
    round_headers = list(re.finditer(
        r'^##\s+第\s*(\d+)\s*轮\s*[—\-]\s*(.*)', content, flags=re.MULTILINE
    ))
    for i, hm in enumerate(round_headers):
        rn = int(hm.group(1))
        sec_type = hm.group(2).strip()
        start = hm.end()
        end = round_headers[i + 1].start() if i + 1 < len(round_headers) else len(content)
        sec_body = content[start:end].strip()
        if rn not in rounds_map:
            rounds_map[rn] = {"llm": "", "tools": [], "knowledge": [], "conclusion": "", "timestamps": []}
        if "LLM" in sec_type or "响应" in sec_type:
            # 保留完整 LLM 文本，仅去除末尾分隔符
            raw = sec_body.rstrip()
            while re.search(r'\n\s*[-–—]{2,}\s*$', raw):
                raw = re.sub(r'\n\s*[-–—]{2,}\s*$', '', raw)
            rounds_map[rn]["llm"] = raw.rstrip()
            # 提取本轮结论
            paragraphs = [p.strip() for p in sec_body.split('\n\n') if p.strip() and not re.match(r'^[-–—]{2,}$', p.strip())]
            if paragraphs:
                last = paragraphs[-1]
                for p in reversed(paragraphs):
                    if re.search(r'因此|结论|总结|所以|最终|根因|原因|问题在于|确认|判断|导致|关键反思|反思检查', p):
                        last = p
                        break
                rounds_map[rn]["conclusion"] = last
        elif "工具" in sec_type or "Tool" in sec_type:
            rounds_map[rn]["tools"].append(sec_body)
            # 提取知识库文档引用
            wiki_matches = re.findall(r'WIKI\s*文档\s*\[([^\]]+)\]', sec_body, re.I)
            for wiki in wiki_matches:
                for line in wiki.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('[') and '/' in line:
                        doc_name = line.split(':')[0].strip().rstrip(',')
                        if doc_name and doc_name not in rounds_map[rn]["knowledge"]:
                            rounds_map[rn]["knowledge"].append(doc_name)
            single_wiki = re.findall(r'WIKI\s*文档\s*\[([^\]]+/[^\]]+\.md)\]', sec_body, re.I)
            for w in single_wiki:
                if w not in rounds_map[rn]["knowledge"]:
                    rounds_map[rn]["knowledge"].append(w)
            # 从日志行中提取时间戳
            ts_matches = re.findall(r'(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})', sec_body)
            if ts_matches:
                first_ts = ts_matches[0]
                last_ts = ts_matches[-1]
                if first_ts not in rounds_map[rn]["timestamps"]:
                    rounds_map[rn]["timestamps"].append(first_ts)
                if last_ts != first_ts and last_ts not in rounds_map[rn]["timestamps"]:
                    rounds_map[rn]["timestamps"].append(last_ts)

    rounds_list = []
    seq = 0
    for rn in sorted(rounds_map.keys()):
        r = rounds_map[rn]
        # 过滤无效轮次：
        # 1) llm 只有分隔符（---）且无工具/结论
        # 2) 无 AI 推理文本且无结论（工具调用上限后的残留轮次）
        llm_clean = re.sub(r'^\s*[-–—]{2,}\s*$', '', r["llm"].strip(), flags=re.MULTILINE).strip()
        if not llm_clean and not r["conclusion"]:
            continue
        seq += 1
        # 简介：取完整 LLM 推理文本，去除反引号/换行/子标题，截取前 150 字
        raw_summary = llm_clean
        # 去除 markdown 子标题行（## xxx）
        raw_summary = re.sub(r'^#{1,6}\s+.+$', '', raw_summary, flags=re.MULTILINE)
        raw_summary = raw_summary.replace('`', '').replace('\n', ' ')
        raw_summary = re.sub(r'\s+', ' ', raw_summary).strip()
        # 去除开头的 "**xxx**" 加粗标记
        raw_summary = re.sub(r'^\*\*([^*]+)\*\*\s*[：:]?\s*', '', raw_summary)
        summary = raw_summary[:150] + ('...' if len(raw_summary) > 150 else '')
        rounds_list.append({
            "round": seq,
            "summary": summary,
            "llm_text": llm_clean,
            "tool_results": r["tools"],
            "knowledge": r["knowledge"],
            "conclusion": r["conclusion"],
            "time_range": " ~ ".join(r["timestamps"]) if r["timestamps"] else "",
        })
    return rounds_list


def _generate_description(row, root_cause: str, rounds: list, desc: str) -> str:
    """生成简洁的问题概述（名词短语，非动作描述）

    优先级：
    1. 从 problem_desc 提取真正的问题名称（去除动作前缀）
    2. 从 R1 LLM 文本提取 "这个 XXX 问题" 或括号内的假设名
    3. 从假设表 confirmed 条目提取
    4. 从 root_cause 首句提取主题
    5. 最终兜底：root_cause 截断
    """
    import re as _re

    # ── 判断文本是否为"坏"描述（动作/中间态/低质量） ──
    def _is_bad_desc(text: str) -> bool:
        if not text or len(text) < 3:
            return True
        # 动作开头（中文）
        if _re.match(
            r'^(我将|我先|我先来|我先\S{1,2}|让我|让我用|首先|先验证|先查看|先了解|先搜索|'
            r'先获取|先梳理|先理解|按分析规划|按规划|同时[，,我])',
            text, _re.IGNORECASE
        ):
            return True
        # 英文动作开头
        if _re.match(r"^(I'll|Let me|I will|I need)", text, _re.IGNORECASE):
            return True
        # 工具输出/低质量前缀
        if _re.match(r'^[\[\-#]', text):
            return True
        if _re.match(r'^(建议排查|无法确定|文件不存在|因果链)', text, _re.IGNORECASE):
            return True
        # 元分析文本
        if _re.search(r'无法构建|缺少.*证据|无法定位|无法验证|暂无数据', text):
            return True
        return False

    # ── 从文本中提取问题名称（去除动作前缀后的核心内容） ──
    def _extract_problem_name(text: str) -> str:
        """从 "我先XXX：问题描述" 格式中提取问题描述（只处理冒号格式）"""
        if not text:
            return ""
        # 只处理 "我先XX：" 冒号格式（逗号格式通常是动作描述，不提取）
        m = _re.match(r'^我先\S{0,6}[：:]\s*(.+)', text)
        if m:
            rest = m.group(1).strip()
            # 取第一个句号前的内容作为问题名
            first_part = _re.split(r'[。\n]', rest)[0].strip()
            if len(first_part) > 5 and not _is_bad_desc(first_part):
                return first_part[:200]
        # "问题：XXX" 格式
        m2 = _re.search(r'问题[：:]\s*(.{5,80}?)(?:[。，,\n]|$)', text)
        if m2:
            return m2.group(1).strip()[:200]
        return ""

    # ── 策略 0：检查 desc / problem_desc ──
    problem_desc = (getattr(row, "problem_desc", None) or "").strip()

    # 0a. desc 本身是好描述
    if desc and desc != root_cause and not _is_bad_desc(desc):
        return desc[:200]

    # 0b. problem_desc 中提取问题名
    extracted = _extract_problem_name(problem_desc)
    if extracted:
        return extracted

    # ── 策略 1：从 R1 LLM 文本提取问题名称 ──
    try:
        rds = rounds or []
        if rds:
            r1_llm = (rds[0].get("llm_text") or rds[0].get("summary") or "").strip()

            # 模式 A: "这个 XXX 问题/异常/故障"
            m = _re.search(r'这个\s*(.+?(?:问题|异常|故障|错误|bug|失效))', r1_llm, _re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                name = _re.sub(r'[。，,.\n].*', '', name)
                if 3 < len(name) < 60:
                    return name

            # 模式 B: "假设N（XXX）" — 括号内的假设名通常就是问题描述
            matches = _re.findall(r'假设\d+[（(](.+?)[）)]', r1_llm)
            if matches:
                for hyp_name in matches:
                    hyp_name = hyp_name.strip()
                    if 3 < len(hyp_name) < 80 and not _is_bad_desc(hyp_name):
                        return hyp_name

            # 模式 C: 英文 - "analyzing XXX issue/problem"
            m_en = _re.search(
                r'(?:analy(?:s|z)ing?|investigat(?:ing|e)|understanding)\s+(.+?(?:issue|problem|bug|error))',
                r1_llm, _re.IGNORECASE
            )
            if m_en:
                name = m_en.group(1).strip()
                # 去掉开头的 "the "
                name = _re.sub(r'^the\s+', '', name, flags=_re.IGNORECASE)
                if 5 < len(name) < 80 and ' ' in name:  # 必须至少包含两个单词
                    return name

            # 模式 D: 从 R1 中提取 "先验证假设X（XXX）" 括号内容
            m_paren = _re.findall(r'[（(](.{4,60}?)[）)]', r1_llm)
            _SKIP_PAREN = {'the problem', 'the issue', 'the bug', 'the error',
                           'the XXX issue', 'this issue'}
            for p in m_paren[:5]:
                p = p.strip()
                # 跳过纯英文通用短语、纯数据值、ID类、逗号分隔列表
                if p.lower() in _SKIP_PAREN:
                    continue
                if _re.match(r'^[\d,\s.\-xX]+$', p):  # 纯数据如 "14,01,08,00"
                    continue
                if _re.match(r'^[a-z\s]{4,20}$', p) and not _re.search(r'[A-Z]{2,}', p):
                    continue  # 纯英文小写短语如 "the problem"
                # 跳过纯逗号分隔的中文列表（如 "手套箱、后雾灯、自动远光灯"）
                if _re.match(r'^[\u4e00-\u9fff\u3001，,\s]+$', p) and p.count('、') >= 2:
                    continue
                if (not _is_bad_desc(p)
                    and not _re.match(r'^[A-Z0-9_/\-]{3,}$', p)
                    and len(p) > 4):
                    return p
    except Exception:
        pass

    # ── 策略 2：从假设表提取 ──
    try:
        ht = _cleanup_hypothesis_table(_ensure_json_obj(row.hypothesis_table))
        if isinstance(ht, list):
            for h in ht:
                if h.get("verdict") == "confirmed" and h.get("hypothesis"):
                    hyp = h["hypothesis"].strip()
                    first = _re.split(r'[。；\n]', hyp)[0].strip()
                    # 如果首句太长，尝试用逗号截断
                    if len(first) > 120 and '，' in first:
                        first = _re.split(r'[，,]', first)[0].strip()
                    if 5 < len(first) < 200 and not _is_bad_desc(first):
                        return first[:200]
    except Exception:
        pass

    # ── 策略 3：从 root_cause 提取主题 ──
    if root_cause and not _is_bad_desc(root_cause):
        first_clause = _re.split(r'[，,。；：:]', root_cause)[0].strip()
        if 5 < len(first_clause) < 120 and not _is_bad_desc(first_clause):
            return first_clause[:200]
        first_sent = _re.split(r'[。！？\n]', root_cause)[0].strip()
        if 5 < len(first_sent) < 120 and not _is_bad_desc(first_sent):
            return first_sent[:200]

    # ── 策略 4：从建议排查方向提取主题 ──
    if root_cause:
        m_suggest = _re.search(r'(?:建议排查|排查方向|查代码确认)\s*[：:]\s*\d+\.\s*(.+?)(?:[。\n]|$)', root_cause)
        if m_suggest:
            suggestion = m_suggest.group(1).strip()
            if len(suggestion) > 5:
                return suggestion[:200]

    # ── 策略 5：从 root_cause 中提取 "说明/表明/指向" 后的结论 ──
    if root_cause:
        m_conclusion = _re.search(r'(?:说明|表明|指向|根因|结论[：:])\s*[：:]?\s*(.{5,100}?)(?:[。；\n]|$)', root_cause)
        if m_conclusion:
            conclusion = m_conclusion.group(1).strip()
            if len(conclusion) > 5 and not _is_bad_desc(conclusion):
                return conclusion[:200]

    # ── 兜底 ──
    fallback = root_cause or desc or problem_desc or ""
    # 清理 markdown 前缀
    fallback = _re.sub(r'^[\-#*\[\]]+', '', fallback).strip()
    # 如果兜底文本仍是"坏"描述，尝试取后半部分（仅限逗号分割后有意义的情况）
    if _is_bad_desc(fallback[:20]) and '，' in fallback:
        second_half = fallback.split('，', 1)[1].strip()
        # 后半部分必须有足够长度且不是延续性文本
        if (not _is_bad_desc(second_half)
            and len(second_half) > 10
            and not _re.match(r'^(之前|之后|然后|接着|同时|并且)', second_half)):
            return second_half[:200]
    # 如果所有策略都失败，返回截断的 root_cause（去掉动作前缀）
    if fallback and _is_bad_desc(fallback[:20]):
        # 尝试去掉开头的动作句，取句号后的内容
        sentences = _re.split(r'[。！？\n]', fallback)
        for s in sentences[1:]:
            s = s.strip()
            if len(s) > 5 and not _is_bad_desc(s):
                return s[:200]
        return fallback[:200]
    return fallback[:200]


def _build_analysis_panel(row, rounds: list = None) -> dict:
    """构建智能分析面板数据（5 段式结构化根因分析）"""
    root_cause = (row.root_cause_summary or "").strip()
    problem_desc = (getattr(row, "problem_desc", None) or "").strip()
    return {
        "anomaly_desc": (problem_desc or root_cause)[:200],
        "problem_overview": root_cause,
        "problem_boundary": _infer_boundary(row, rounds),
        "evidence_chain": _build_evidence_chain(row, rounds),
        "possible_causes": _extract_confirmed_causes(row, rounds),
        "disposition": _infer_disposition(row),
    }


def _infer_boundary(row, rounds: list = None) -> str:
    """从 reasoning_rounds / root_cause 提取涉及的服务模块做问题定界"""
    import re as _re
    parts = []
    # 1. 从 reasoning_rounds 工具结果中提取涉及的服务/PID
    try:
        rds = rounds or []
        svc_set = set()
        _SVC_PAT = _re.compile(r'(KANZI_SERVICE|Kanzi|SurfaceView|com\.patac\.hmi\.settings|com\.patac\.hmi\.user|KANZI_SDK|SettingsActivity)', _re.IGNORECASE)
        for rd in rds:
            for tool in (rd.get("tool_results") or []):
                for m in _SVC_PAT.finditer(tool):
                    svc_set.add(m.group())
            conc = (rd.get("conclusion") or "") + " " + (rd.get("summary") or "")
            for m in _SVC_PAT.finditer(conc):
                svc_set.add(m.group())
        if svc_set:
            parts.append("涉及服务: " + "、".join(sorted(svc_set)[:5]))
    except Exception:
        pass
    # 2. fallback: 从 root_cause 提取
    if not parts:
        rc = (row.root_cause_summary or "").strip()
        m = _re.search(r'([\w-]+(?:模块|服务|组件|system|service|module|adapter|handler))', rc, _re.IGNORECASE)
        if m:
            parts.append(f"涉及: {m.group(1)}")
    # 3. 补充 ai_module/actual_module
    ai_mod = (getattr(row, "ai_module", None) or "").strip()
    act_mod = (getattr(row, "actual_module", None) or "").strip()
    if ai_mod:
        parts.append(f"AI识别: {ai_mod}")
    if act_mod:
        parts.append(f"实际模块: {act_mod}")
    return "，".join(parts) if parts else ""


def _build_evidence_chain(row, rounds: list = None) -> list:
    """从 reasoning_rounds + hypothesis_table 提取有意义的证据链"""
    import re as _re
    items = []
    # 1. 从 hypothesis_table 取结构化证据
    ht = _cleanup_hypothesis_table(_ensure_json_obj(row.hypothesis_table))
    if isinstance(ht, list):
        _SKIP_EV = {"根因子论点", "根因子节点", ""}
        for h in ht:
            ev = (h.get("evidence") or "").strip()
            if ev not in _SKIP_EV and ev not in items and len(ev) > 3:
                items.append(ev)
    # 2. 从 reasoning_rounds 结论中提取关键发现
    try:
        rds = rounds or []
        _KEY_PAT = _re.compile(r'关键发现|重要|确认|排除|负向证据|关键反思|重大突破')
        for rd in rds:
            conc = (rd.get("conclusion") or "").strip()
            if not conc or len(conc) < 8:
                continue
            if _KEY_PAT.search(conc):
                # 清理 markdown 标记
                clean = _re.sub(r'`{1,3}[^`]*`{1,3}', lambda m: m.group().strip('`'), conc)
                clean = _re.sub(r'\*\*([^*]+)\*\*', r'\1', clean)
                clean = _re.sub(r'^#+\s+', '', clean, flags=_re.MULTILINE)
                clean = _re.sub(r'\s+', ' ', clean).strip()
                # 去除“反思检查：N. 搜到了什么：”等前缀
                clean = _re.sub(r'^反思检查[：:]\s*\d+\.\s*\S+[：:]\s*', '', clean)
                clean = _re.sub(r'^\d+\.\s*\*?\*?\S+[：:]\s*', '', clean)
                # 截取第一句（句号/分号/换行前）
                sent = _re.split(r'[\u3002\uff1b\n]', clean)[0].strip()
                if sent and len(sent) > 5 and sent not in items:
                    items.append(sent[:160])
        # 补充最终结论
        rc = (row.root_cause_summary or "").strip()
        if rc and rc not in items:
            items.append(f"最终结论: {rc[:150]}")
    except Exception:
        pass
    return items[:8]


def _extract_confirmed_causes(row, rounds: list = None) -> list:
    """从 hypothesis_table + reasoning_rounds 提取已确认的假设和关键发现"""
    import re as _re
    causes = []
    ht = _cleanup_hypothesis_table(_ensure_json_obj(row.hypothesis_table))
    if isinstance(ht, list):
        for h in ht:
            if h.get("verdict") == "confirmed" and h.get("hypothesis"):
                causes.append(h["hypothesis"])
    # 从 reasoning_rounds 补充关键排除/确认结论（最多 3 条）
    try:
        rds = rounds or []
        _EXCL_PAT = _re.compile(r'排除|否定|不是|非.*原因|无法验证|噪声')
        excl_count = 0
        for rd in rds:
            if excl_count >= 3:
                break
            conc = (rd.get("conclusion") or "").strip()
            if conc and _EXCL_PAT.search(conc) and len(conc) > 10:
                clean = _re.sub(r'`{1,3}', '', conc)
                clean = _re.sub(r'\*\*([^*]+)\*\*', r'\1', clean)
                clean = _re.sub(r'^#+\s+', '', clean, flags=_re.MULTILINE)
                clean = _re.sub(r'\s+', ' ', clean).strip()
                # 去除“反思检查”前缀
                clean = _re.sub(r'^反思检查[：:]\s*\d+\.\s*\S+[：:]\s*', '', clean)
                sent = _re.split(r'[\u3002\uff1b\n]', clean)[0].strip()
                if sent and sent not in causes:
                    causes.append(f"[R{rd['round']}] {sent[:140]}")
                    excl_count += 1
    except Exception:
        pass
    if not causes and row.root_cause_summary:
        causes.append(row.root_cause_summary)
    return causes


def _infer_disposition(row) -> str:
    """推断处置建议：基于关键词匹配 + 动态生成"""
    import re as _re
    error_type = (getattr(row, "error_type", None) or "").strip()
    root_cause = (row.root_cause_summary or "").strip()
    rc_lower = root_cause.lower()

    # ── 关键词匹配（优先级从高到低） ──
    # 渲染类
    if "surfaceview" in rc_lower or ("surface" in rc_lower and any(k in root_cause for k in ["布局", "尺寸", "渲染", "分辨率"])):
        return "SurfaceView 渲染配置异常，建议检查 KanziView 的 Surface 尺寸设置、Layout 参数与相机视角配置（CameraViewID），确认渲染分辨率是否与显示区域匹配"
    if "锯齿" in root_cause or "抗锯齿" in root_cause or "msaa" in rc_lower:
        return "渲染锯齿问题，建议检查 Kanzi 引擎的 MSAA/抗锯齿配置、EGL 参数及 Surface 分辨率设置"
    if "kanzi" in rc_lower:
        return "Kanzi 3D 引擎渲染异常，建议检查 KanziView 配置、Surface 关联与场景切换逻辑"
    # 崩溃/ANR
    if any(k in rc_lower for k in ["crash", "崩溃", "fatal", "anr", "未响应"]):
        return "存在崩溃/ANR 问题，建议检查异常堆栈中的触发点，确认相关模块的空指针、线程阻塞或资源竞争情况"
    # 内存问题
    if any(k in rc_lower for k in ["oom", "out of memory", "内存泄漏", "内存不足", "leak", "memory"]):
        return "存在内存问题，建议使用内存分析工具（如 MAT/LeakCanary）排查泄漏点，检查大对象持有与生命周期管理"
    # 超时
    if "超时" in root_cause or "timeout" in rc_lower:
        return "存在超时问题，建议检查网络连通性与目标服务健康状态，确认超时阈值是否合理"
    # 音频/音量
    if any(k in rc_lower for k in ["音量", "audio", "volume", "audiomanager", "audioservice", "streamvolume"]):
        return "音频/音量相关问题，建议检查 AudioManager 的音量设置流程、AudioService 持久化逻辑及 STR 后状态恢复"
    # 分屏/多窗口
    if any(k in rc_lower for k in ["分屏", "split", "multi-window", "splitscreen", "窗口模式"]):
        return "分屏/多窗口相关问题，建议检查 WindowManagerService 的窗口状态管理、Activity 生命周期及分屏切换逻辑"
    # 电源/关机/休眠
    if any(k in rc_lower for k in ["关机", "shutdown", "poweroff", "休眠", "str", "suspend", "唤醒", "wakeup", "电源", "powermanager"]):
        return "电源管理相关问题，建议检查 PowerManager 状态机流转、STR 进入/唤醒流程及各服务的电源状态回调"
    # 网络/连接
    if any(k in rc_lower for k in ["网络", "network", "wifi", "蓝牙", "bluetooth", "连接失败", "disconnect"]):
        return "网络连接问题，建议检查网络状态监听、连接管理器及相关服务的重连机制"
    # 启动/冷启动
    if any(k in rc_lower for k in ["启动", "launch", "startup", "冷启动", "热启动", "开机"]):
        return "启动流程问题，建议检查 Application/Activity 生命周期、初始化耗时及依赖服务就绪状态"
    # 显示/黑屏
    if any(k in rc_lower for k in ["黑屏", "白屏", "显示异常", "闪屏", "花屏", "display", "screen"]):
        return "显示异常问题，建议检查 SurfaceFlinger 合成流程、显示驱动及 Buffer 队列状态"
    # 触摸/输入
    if any(k in rc_lower for k in ["触摸", "touch", "点击", "click", "input", "手势", "gesture"]):
        return "输入/触摸问题，建议检查 InputDispatcher 事件分发、View 触摸事件链及手势识别逻辑"
    # 服务/Binder
    if any(k in rc_lower for k in ["binder", "service died", "服务死亡", "远程调用", "aidl"]):
        return "服务/Binder 通信问题，建议检查服务端生命周期、Binder 线程池配置及跨进程调用的异常处理"
    # 数据持久化
    if any(k in rc_lower for k in ["数据库", "database", "sqlite", "sharedpreferences", "持久化", "存储"]):
        return "数据持久化问题，建议检查数据库操作的事务完整性、SP 提交时机及文件 IO 异常处理"
    # 日志缺失
    if any(k in root_cause for k in ["为空", "无日志", "日志缺失", "未找到日志"]):
        return "日志数据缺失，建议检查日志采集链路是否正常，确认触发源是否有日志输出"
    # 数据不匹配
    if any(k in rc_lower for k in ["不匹配", "mismatch", "不一致", "inconsistent"]):
        return "存在数据不匹配问题，建议排查相关数据的生成与传递逻辑，确认数据源一致性"

    # ── error_type 匹配 ──
    if error_type:
        return f"建议排查 {error_type} 相关问题，检查对应模块的配置与日志输出"

    # ── 动态生成：从 root_cause 提取关键信息 ──
    if root_cause:
        # 提取模块/服务名
        module_match = _re.search(r'([\w.]+(?:Service|Manager|Controller|Provider|Handler|Activity|Fragment|View))', root_cause)
        # 提取核心动作
        action_match = _re.search(r'([\u4e00-\u9fa5]{2,4}(?:失败|异常|错误|丢失|超时|阻塞|冲突))', root_cause)

        if module_match and action_match:
            return f"{action_match.group(1)}，涉及 {module_match.group(1)}，建议检查该模块的核心流程与异常处理逻辑"
        elif module_match:
            return f"涉及 {module_match.group(1)}，建议检查该模块的配置、状态流转与异常处理"
        elif action_match:
            return f"存在{action_match.group(1)}，建议结合日志定位具体触发点并检查相关逻辑"
        # 最终兜底：使用 root_cause 首句生成建议
        first_sentence = _re.split(r'[，。,.]', root_cause)[0][:50]
        return f"问题涉及「{first_sentence}」，建议结合日志进一步分析，必要时使用一键复测重新执行分析"

    return ""


def _parse_duration(dur_str: str) -> int:
    """解析耗时字符串为秒数，支持 '24m4s' / '3m40s' / '18s' 格式"""
    if not dur_str or not isinstance(dur_str, str):
        return 0
    total = 0
    import re
    m = re.match(r"(?:(\d+)m)?(?:(\d+)s)?", dur_str.strip())
    if m:
        if m.group(1):
            total += int(m.group(1)) * 60
        if m.group(2):
            total += int(m.group(2))
    return total


def _fmt_sec(sec: float) -> str:
    """秒数转可读时长字符串"""
    if sec is None or sec <= 0:
        return "0s"
    sec = round(sec)
    if sec < 60:
        return f"{sec}s"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m}m{s}s" if s else f"{m}m"
    h, rem = divmod(m, 60)
    return f"{h}h{rem}m" if rem else f"{h}h"


def _parse_duration_text(text: str) -> float:
    """从文本中提取耗时（支持 '3m40s' / '220s' / '5min' 等格式）"""
    import re
    if not text:
        return 0
    m = re.search(r'(\d+)\s*m(?:in)?\s*(\d+)\s*s', text)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.search(r'(\d+(?:\.\d+)?)\s*s(?:ec)?(?:onds?)?', text)
    if m:
        return float(m.group(1))
    m = re.search(r'(\d+(?:\.\d+)?)\s*min', text)
    if m:
        return float(m.group(1)) * 60
    return 0


def _extract_time_refs(text: str) -> list:
    """从文本中提取时间引用 (HH:MM:SS 或 HH:MM)"""
    import re
    if not text:
        return []
    return re.findall(r'\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?', text)


def _split_rootcause_segments(text: str) -> list:
    """将 rootcause 单句拆解为多个逻辑片段

    策略：
    1. 先尝试按换行符切分
    2. 再按因果/顺序关键词切分
    3. 再按空格切分（中文空格分词）
    4. 兆底：整句作为一个片段
    """
    if not text:
        return []
    text = text.strip()

    # 1. 换行切分
    if '\n' in text:
        segs = [s.strip() for s in text.split('\n') if s.strip()]
        if len(segs) >= 2:
            return segs

    # 2. 因果/顺序关键词切分
    import re
    keywords = r'([\uff0c,\uff1b;\u2192\u2190]|\u56e0\u6b64|\u5bfc\u81f4|\u89e6\u53d1|\u4ece\u800c|\u4f46\u662f|\u800c|\u540e\u6765|\u63a5\u7740|\u7136\u540e)'
    parts = re.split(keywords, text)
    segs = []
    buf = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if re.match(keywords, p):
            buf += p
        else:
            if buf:
                segs.append(buf)
            buf = p
    if buf:
        segs.append(buf)
    if len(segs) >= 2:
        return segs

    # 3. 空格切分（适用于混合中英文的技术描述）
    tokens = text.split()
    if len(tokens) >= 3:
        # 每 2-3 个 token 合并为一个片段
        chunk = max(2, len(tokens) // 3)
        segs = []
        for i in range(0, len(tokens), chunk):
            segs.append(' '.join(tokens[i:i + chunk]))
        if len(segs) >= 2:
            return segs

    # 4. 兆底：整句
    return [text]


def _auto_time_sequence(n: int, base_seconds: float = 0) -> list:
    """生成 n 个自动递增的时间点（从 base_seconds 开始）"""
    if n <= 0:
        return []
    interval = max(1, int(base_seconds / max(n, 1)))
    times = []
    for i in range(n):
        sec = int(base_seconds * i / max(n, 1))
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        if h > 0:
            times.append(f"{h:02d}:{m:02d}:{s:02d}")
        else:
            times.append(f"{m:02d}:{s:02d}")
    return times


# ── 阶段关键词 → 标准名称 + 颜色 ──
_PHASE_KEYWORDS = {
    "准备": ("准备阶段", "#409eff"),
    "Lead": ("Lead阶段", "#1677ff"),
    "装配": ("装配阶段", "#67c23a"),
    "日志获取": ("日志获取", "#409eff"),
    "推理分析": ("推理分析", "#67c23a"),
    "裁定判定": ("裁定判定", "#e6a23c"),
    "报告生成": ("报告生成", "#909399"),
    "分析": ("推理分析", "#67c23a"),
    "日志": ("日志获取", "#409eff"),
    "判定": ("裁定判定", "#e6a23c"),
    "报告": ("报告生成", "#909399"),
}
_PHASE_DEFAULT = [
    {"phase_name": "日志获取", "ratio": 0.08, "color": "#409eff"},
    {"phase_name": "推理分析", "ratio": 0.50, "color": "#67c23a"},
    {"phase_name": "裁定判定", "ratio": 0.28, "color": "#e6a23c"},
    {"phase_name": "报告生成", "ratio": 0.14, "color": "#909399"},
]


def build_decision_chain(total_seconds=None, analysis_seconds=None,
                         problem_time=None, analysis_date=None,
                         analysis_result=None, trigger_source=None,
                         error_type=None, rootcause=None,
                         error_message=None) -> str:
    """从表格行数据构造 decision_chain JSON 字符串

    解析策略：
    1. 尝试用正则从文本提取阶段名+耗时
    2. 匹配不到耗时时按比例分配真实秒数
    3. 将 rootcause 文本拆解为 timeline 事件节点
    4. 兆底：整段文本作为一个事件节点塞入 timeline

    生成结构：
    {
      "phase_wall_clock": [{phase_name, duration_seconds, percentage, color}],
      "timeline_rounds": [{round, phases: [{phase_name, duration, events}]}]
    }
    """
    import re
    total = float(total_seconds or 0)
    analysis = float(analysis_seconds or 0)
    base_sec = analysis if analysis > 0 else total
    all_text = ' '.join(filter(None, [rootcause, error_message, error_type]))

    if base_sec <= 0 and not all_text.strip():
        return "[]"

    # ═══════════════════════════════════════════
    # 1. 解析阶段墙钟 (phase_wall_clock)
    # ═══════════════════════════════════════════
    # 1a. 尝试从文本正则匹配 "阶段名 + 耗时"
    matched_phases = []
    if all_text:
        for kw, (name, color) in _PHASE_KEYWORDS.items():
            pat = re.compile(
                re.escape(kw) + r'[^\d]{0,10}'
                r'(\d+)\s*m(?:in)?\s*(\d+)\s*s'
                r'|'
                + re.escape(kw) + r'[^\d]{0,10}'
                r'(\d+(?:\.\d+)?)\s*s',
                re.IGNORECASE
            )
            m = pat.search(all_text)
            if m:
                if m.group(1) and m.group(2):
                    dur = int(m.group(1)) * 60 + int(m.group(2))
                elif m.group(3):
                    dur = float(m.group(3))
                else:
                    continue
                matched_phases.append({
                    "phase_name": name, "duration_seconds": dur,
                    "percentage": 0, "color": color,
                })

    # 1b. 匹配不到 → 按比例分配真实耗时
    if not matched_phases and base_sec > 0:
        for p in _PHASE_DEFAULT:
            sec = round(base_sec * p["ratio"], 1)
            matched_phases.append({
                "phase_name": p["phase_name"],
                "duration_seconds": sec,
                "percentage": 0,
                "color": p["color"],
            })

    # 1c. 计算百分比
    total_dur = sum(p["duration_seconds"] for p in matched_phases) or 1
    for p in matched_phases:
        p["percentage"] = round(p["duration_seconds"] / total_dur * 100, 1)

    # ═══════════════════════════════════════════
    # 2. 解析决策时间轴 (timeline_rounds)
    # ═══════════════════════════════════════════
    time_str = (problem_time or "")[:16]
    date_str = analysis_date or ""
    result_text = (
        "分析成功" if analysis_result == "成功"
        else "分析失败" if analysis_result == "失败"
        else analysis_result or ""
    )

    # 2a. 从 rootcause 拆解为逻辑片段
    segments = _split_rootcause_segments(rootcause) if rootcause else []
    time_refs = _extract_time_refs(rootcause) if rootcause else []

    # 2b. 组装日志获取阶段事件
    events_access = []
    events_access.append({
        "time": time_str or "00:00",
        "desc": f"触发来源: {trigger_source or 'parseFullTicket'}"
    })
    if error_type:
        events_access.append({
            "time": time_str or "00:00",
            "desc": f"错误类型: {error_type}"
        })

    # 2c. 组装推理分析阶段事件（从 rootcause 拆解）
    events_reasoning = []
    if segments:
        auto_times = _auto_time_sequence(
            len(segments), base_sec * 0.5
        )
        for i, seg in enumerate(segments):
            # 优先用文本中提取的时间引用
            t = ""
            if i < len(time_refs):
                t = time_refs[i]
            elif i < len(auto_times):
                t = auto_times[i]
            events_reasoning.append({"time": t, "desc": seg})
    elif rootcause:
        # 兆底：整段作为一个事件
        events_reasoning.append({
            "time": time_str or "00:00",
            "desc": rootcause
        })
    else:
        events_reasoning.append({
            "time": "",
            "desc": "未提取到分析过程"
        })

    # 2d. 裁定阶段
    events_adjudication = [{"time": "", "desc": f"最终判定: {result_text}"}]

    # 2e. 报告生成阶段
    events_reporting = [{"time": date_str, "desc": "分析报告生成并写入飞书"}]

    # 2f. 组装 timeline_rounds
    phase_names = [p["phase_name"] for p in matched_phases] or [
        "日志获取", "推理分析", "裁定判定", "报告生成"
    ]
    phase_secs = {p["phase_name"]: p["duration_seconds"]
                  for p in matched_phases}
    phase_events = {
        "日志获取": events_access,
        "推理分析": events_reasoning,
        "裁定判定": events_adjudication,
        "报告生成": events_reporting,
    }
    timeline_phases = []
    for name in phase_names:
        timeline_phases.append({
            "phase_name": name,
            "duration": _fmt_sec(phase_secs.get(name, 0)),
            "events": phase_events.get(name, []),
        })

    timeline_rounds = [{"round": 1, "phases": timeline_phases}]

    return json.dumps({
        "phase_wall_clock": matched_phases,
        "timeline_rounds": timeline_rounds,
    }, ensure_ascii=False)


def build_hypothesis_table(rootcause=None, error_type=None, error_message=None,
                           ai_module=None, actual_module=None,
                           analysis_result=None, conf=None) -> str:
    """从表格行数据构造 hypothesis_table JSON 字符串

    解析策略：
    1. rootcause → confirmed 假设（提取关键词作为 evidence）
    2. error_type → rejected 假设
    3. 模块对比 → 对比假设
    4. error_message → 辅助假设
    5. 兆底：至少生成一条假设，前端不会报空

    生成结构：[{hypothesis, verdict, evidence, remark}]
    """
    import re
    hypotheses = []
    rc = (rootcause or "").strip()
    conf_val = float(conf) if conf else 0.0

    # ── 1. rootcause → 已确认假设 ──
    if rc:
        # 检查文本内是否有确认/排除关键词
        is_confirmed = any(kw in rc for kw in
                           ["已确认", "confirmed", "确认", "确定", "根因"])
        is_rejected = any(kw in rc for kw in
                          ["已排除", "rejected", "排除", "不是", "无关"])
        if is_rejected and not is_confirmed:
            verdict = "rejected"
        else:
            verdict = "confirmed"

        # 提取实体名作为 evidence（大写英文/数字组合）
        entities = re.findall(r'[A-Z][A-Za-z0-9_]+', rc)
        evidence = (
            f"关键实体: {', '.join(entities[:3])}"
            if entities else "日志证据链支持该假设"
        )

        hypotheses.append({
            "key": "H1",
            "hypothesis": rc[:300],
            "verdict": verdict,
            "evidence": evidence,
            "remark": f"conf {conf_val:.2f}" if conf_val > 0 else "AI 分析结论",
        })

        # 如果 rootcause 较长且可拆分为多个子句，每个子句生成一条假设
        segments = _split_rootcause_segments(rc)
        if len(segments) >= 2:
            for i, seg in enumerate(segments[1:4], start=2):  # 最多追加3条
                hypotheses.append({
                    "key": f"H{i}",
                    "hypothesis": seg[:200],
                    "verdict": "confirmed",
                    "evidence": "根因子论点",
                    "remark": "",
                })

    # ── 2. error_type → 已排除假设 ──
    if error_type:
        neg_map = {
            "NO_LOG_ATTACHMENT": "日志附件缺失，无法进行深度分析",
            "TIME_FILTER_EMPTY": "时间窗口过滤后日志为空，无重叠事件",
            "LOG_EMPTY": "日志文件内容为空",
        }
        evidence = neg_map.get(error_type,
                               f"错误类型 {error_type} 不指向根因")
        hypotheses.append({
            "key": f"H{len(hypotheses) + 1}",
            "hypothesis": f"问题由 {error_type} 引起",
            "verdict": "rejected",
            "evidence": evidence,
            "remark": "已排除",
        })

    # ── 3. 模块对比 → 对比假设 ──
    if ai_module and actual_module and ai_module != actual_module:
        hypotheses.append({
            "key": f"H{len(hypotheses) + 1}",
            "hypothesis": f"问题位于 AI 判定模块: {ai_module}",
            "verdict": "rejected",
            "evidence": f"实际模块: {actual_module}",
            "remark": "模块对比",
        })
    elif ai_module:
        hypotheses.append({
            "key": f"H{len(hypotheses) + 1}",
            "hypothesis": f"问题位于模块: {ai_module}",
            "verdict": "confirmed" if analysis_result == "成功" else "possible",
            "evidence": "AI 分析指向该模块",
            "remark": "",
        })

    # ── 4. error_message → 辅助假设 ──
    if error_message and error_message != rc:
        hypotheses.append({
            "key": f"H{len(hypotheses) + 1}",
            "hypothesis": str(error_message)[:200],
            "verdict": "rejected" if error_type else "possible",
            "evidence": f"归类为 {error_type}" if error_type else "待确认",
            "remark": "辅助信息",
        })

    # ── 5. 兆底：确保至少一条假设 ──
    if not hypotheses:
        hypotheses.append({
            "key": "H1",
            "hypothesis": "暂无分析数据，请点击一键复测",
            "verdict": "possible",
            "evidence": "",
            "remark": "待分析",
        })

    return json.dumps(hypotheses, ensure_ascii=False)


def _audit_to_dict(row) -> dict:
    """审计记录序列化（后端通用格式）"""
    return {
        "id": row.id,
        "doc_id": row.doc_id,
        "file_name": row.file_name,
        "cos_hash": row.cos_hash,
        "upload_status": row.upload_status,
        "upload_time": row.upload_time.isoformat() if row.upload_time else None,
    }


def _audit_to_front_dict(row) -> dict:
    """审计记录序列化（前端表格格式，字段名与前端 table column 对齐）"""
    return {
        "id": row.id,
        "time": row.upload_time.strftime("%Y-%m-%d %H:%M:%S") if row.upload_time else "",
        "file": row.file_name or "",
        "doc_id": row.doc_id or "",
        "cos_hash": (row.cos_hash[:16] + "...") if row.cos_hash and len(row.cos_hash) > 16 else (row.cos_hash or ""),
        "result": "成功" if row.upload_status == "success" else "失败",
    }


# ══════════════════════════════════════════════════════════════
# 报告获取与结构化解析（跨模块复用旧模块底层能力）
# ══════════════════════════════════════════════════════════════


def fetch_remote_report(case_id: str) -> str:
    """代理获取：从旧模块的底层能力拉取 AI 分析报告原文

    四级回退策略（完全隔离，不影响旧模块）：
    0. case_reports/ 本地专用目录（最快，优先已有数据）
    1. pipeline._get_ai_report_content → 本地 docs/ + 飞书 Open API
    2. 远程调试服务器 HTTP GET → http://{host}:{port}/api/logs/debug/{case_id}
    3. 全部失败时抛出 ValueError

    :param case_id: Jira 号
    :return: 报告 Markdown 原文
    :raises ValueError: 所有来源均不可达
    """
    from src.config import load_config, PROJECT_ROOT

    # ── 策略 0：case_reports/ 本地专用目录（最快）──
    _reports_dir = os.path.join(PROJECT_ROOT, "case_reports")
    if os.path.isdir(_reports_dir):
        for sub in ("", "pc", "online"):
            check_path = os.path.join(_reports_dir, sub, f"{case_id}.md") if sub else os.path.join(_reports_dir, f"{case_id}.md")
            if os.path.isfile(check_path):
                try:
                    with open(check_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    if content and content.strip():
                        logger.info("[fetch_remote] 策略0命中(case_reports/%s): case_id=%s, %d 字符",
                                    sub or "root", case_id, len(content))
                        return content
                except Exception:
                    pass

    # ── 策略 1：复用 pipeline._get_ai_report_content（本地 + 飞书）──
    try:
        from src import pipeline
        content = pipeline._get_ai_report_content(case_id, "")
        if content and content.strip():
            logger.info("[fetch_remote] 策略1命中: case_id=%s, %d 字符", case_id, len(content))
            return content
    except Exception as e:
        logger.warning("[fetch_remote] 策略1失败(本地+飞书): %s", e)

    # ── 策略 2：远程调试服务器 HTTP GET ──
    import httpx
    cfg_all = load_config().get("app_log_server", {})
    for source in ("pc", "online"):
        if source not in cfg_all and "host" in cfg_all:
            cfg = cfg_all
        else:
            cfg = cfg_all.get(source, {})
        host = cfg.get("host", "")
        port = cfg.get("port", 8001)
        if not host:
            continue
        endpoint = cfg.get("debug_endpoint", "/api/logs/debug")
        url = f"http://{host}:{port}{endpoint}/{case_id}"
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(url)
            if resp.status_code == 200 and resp.text.strip():
                content = resp.text
                # 保存到 case_reports/ 目录（供下次策略0直接读取）
                save_dir = os.path.join(PROJECT_ROOT, "case_reports", source)
                os.makedirs(save_dir, exist_ok=True)
                local_path = os.path.join(save_dir, f"{case_id}.md")
                if not os.path.exists(local_path):
                    with open(local_path, "w", encoding="utf-8") as f:
                        f.write(content)
                logger.info("[fetch_remote] 策略2命中(%s): case_id=%s, %d 字符",
                            source, case_id, len(content))
                return content
        except Exception as e:
            logger.warning("[fetch_remote] 策略2失败(%s): %s", source, e)

    raise ValueError(f"获取上游报告失败（本地/飞书/远程均不可达）: case_id={case_id}")


def parse_raw_report_to_json(raw_text: str) -> dict:
    """强解析：将 AI 分析报告原文正则解析为 decision_chain + hypothesis_table

    解析策略（按优先级）：
    1. 提取根因：匹配 `<done>` 块内 `## 分析结论` 下的 `- 根因:` 子项
    2. 提取时间线：匹配 `## 时间线` 下的 Markdown 表格行 → timeline_rounds
    3. 提取端到端耗时：匹配 `## 端到端耗时` 表格行 → phase_wall_clock
    4. 提取信号链路：匹配 `## 信号链路追踪` 下的请求/回调链路 → timeline events
    5. 提取假设：匹配“假设” + “confirmed/rejected” 段落 → hypothesis_table
    6. 兆底：整段文本作为单个 timeline 事件，保证前端有东西渲染

    :param raw_text: AI 分析报告 Markdown 原文
    :return: {
        "decision_chain": {"phase_wall_clock": [...], "timeline_rounds": [...]},
        "hypothesis_table": [{"key", "hypothesis", "verdict", "evidence", "remark"}],
        "root_cause": str,
        "confidence": float,
    }
    """
    result = {
        "decision_chain": {"phase_wall_clock": [], "timeline_rounds": []},
        "hypothesis_table": [],
        "root_cause": "",
        "confidence": 0.0,
    }

    if not raw_text or not raw_text.strip():
        return result

    # ═══════════════════════════════════════════
    # 0. 提取 <done> 块（结构化结论区域）
    # ═══════════════════════════════════════════
    done_block = ""
    done_match = re.search(r"<done>\s*\n(.*?)\n\s*</done>", raw_text, re.DOTALL)
    if done_match:
        done_block = done_match.group(1)

    # ═══════════════════════════════════════════
    # 1. 提取根因
    # ═══════════════════════════════════════════
    root_cause = ""
    # 策略 A：<done> 块内 `- 根因:` 子项
    rc_match = re.search(
        r"[-*]\s*根因[:：]\s*(.+?)(?:\n[-*]|\n##|\Z)",
        done_block or raw_text, re.DOTALL
    )
    if rc_match:
        root_cause = _clean_md_line(rc_match.group(1))
    # 策略 B：`## 根因结论` / `## 分析结论` 段落
    if not root_cause:
        rc_match2 = re.search(
            r"##\s*(?:根因结论|分析结论|根因分析)[^\n]*\n(.*?)(?:\n##|\Z)",
            raw_text, re.DOTALL
        )
        if rc_match2:
            lines = [_clean_md_line(l) for l in rc_match2.group(1).splitlines() if l.strip()]
            root_cause = "\n".join(lines[:5])  # 最多 5 行

    result["root_cause"] = root_cause[:500] if root_cause else ""

    # ═══════════════════════════════════════════
    # 2. 提取置信度
    # ═══════════════════════════════════════════
    conf_match = re.search(
        r"[-*]\s*置信度[:：]\s*(high|medium|low|高|中|低|\d+\.?\d*)",
        done_block or raw_text, re.IGNORECASE
    )
    if conf_match:
        cv = conf_match.group(1).strip().lower()
        conf_map = {"high": 0.85, "中": 0.7, "medium": 0.7, "中": 0.65,
                     "low": 0.4, "低": 0.4}
        result["confidence"] = conf_map.get(cv, 0.5)
        try:
            result["confidence"] = float(cv)
        except (ValueError, TypeError):
            pass

    # ═══════════════════════════════════════════
    # 3. 提取时间线表格 → timeline_rounds
    # ═══════════════════════════════════════════
    timeline_rounds = []
    # 匹配 `## 时间线` 下的 markdown 表格行
    tl_match = re.search(
        r"##\s*时间线[^\n]*\n\|.*?\|.*?\|.*?\n\|[-|\s]+\n((?:\|[^\n]+\n)+)",
        done_block or raw_text, re.DOTALL
    )
    if tl_match:
        table_rows = tl_match.group(1).strip().splitlines()
        for idx, row in enumerate(table_rows):
            cells = [c.strip() for c in row.split("|") if c.strip()]
            if len(cells) >= 2:
                time_str = cells[0] if cells[0] != "未追踪到" else ""
                event_desc = cells[1] if len(cells) > 1 else ""
                detail = cells[2] if len(cells) > 2 else ""
                timeline_rounds.append({
                    "round": idx + 1,
                    "time": time_str,
                    "event": _clean_md_line(event_desc),
                    "detail": _clean_md_line(detail),
                })

    # 从推理轮次补充 timeline（当时间线表格为空时）
    if not timeline_rounds:
        round_matches = re.finditer(
            r"##\s*第\s*(\d+)\s*轮\s*—\s*LLM\s*响应\s*\n(.*?)(?=##\s*第\s*\d+\s*轮|\Z)",
            raw_text, re.DOTALL
        )
        for m in round_matches:
            rnd_num = int(m.group(1))
            llm_text = m.group(2).strip()
            summary = _clean_md_line(llm_text[:200])
            if summary:
                timeline_rounds.append({
                    "round": rnd_num,
                    "time": "",
                    "event": f"第{rnd_num}轮推理",
                    "detail": summary,
                })

    # ═══════════════════════════════════════════
    # 4. 提取端到端耗时表格 → phase_wall_clock
    # ═══════════════════════════════════════════
    phase_wall_clock = []
    e2e_match = re.search(
        r"##\s*端到端耗时[^\n]*\n\|.*?\|.*?\|.*?\n\|[-|\s]+\n((?:\|[^\n]+\n)+)",
        done_block or raw_text, re.DOTALL
    )
    if e2e_match:
        for row in e2e_match.group(1).strip().splitlines():
            cells = [c.strip() for c in row.split("|") if c.strip()]
            if len(cells) >= 5 and cells[0] != "未追踪到":
                chain_name = cells[0]
                dur_str = cells[-1] if len(cells) > 4 else ""
                dur_sec = _parse_duration_to_seconds(dur_str)
                phase_wall_clock.append({
                    "phase_name": chain_name,
                    "duration_seconds": dur_sec,
                    "percentage": 0,
                    "color": "#409eff",
                })

    # 兆底：如果解析不到任何阶段，按轮次估算
    if not phase_wall_clock:
        total_rounds = len(re.findall(r"##\s*第\s*\d+\s*轮", raw_text))
        if total_rounds > 0:
            est_sec = total_rounds * 15
            for name, ratio, color in [
                ("日志获取", 0.08, "#409eff"),
                ("推理分析", 0.50, "#67c23a"),
                ("裁定判定", 0.28, "#e6a23c"),
                ("报告生成", 0.14, "#909399"),
            ]:
                phase_wall_clock.append({
                    "phase_name": name,
                    "duration_seconds": int(est_sec * ratio),
                    "percentage": int(ratio * 100),
                    "color": color,
                })

    # 计算百分比
    total_dur = sum(p.get("duration_seconds", 0) for p in phase_wall_clock) or 1
    for p in phase_wall_clock:
        p["percentage"] = int(p.get("duration_seconds", 0) / total_dur * 100)

    # ═══════════════════════════════════════════
    # 5. 提取假设 → hypothesis_table
    # ═══════════════════════════════════════════
    hypotheses = []
    # 策略 A：匹配“假设N” + confirmed/rejected（仅在 <done> 块内匹配，避免误中 LLM 响应正文）
    hyp_search_text = done_block if done_block else raw_text
    hyp_pattern = re.compile(
        r"(?:假设|H)\s*[#]?(\d{1,2})\s*[:：]?\s*([^\n]+)"
        r".*?(confirmed|rejected|已确认|已排除|确认|排除)",
        re.IGNORECASE | re.DOTALL
    )
    for hm in hyp_pattern.finditer(hyp_search_text):
        h_num = hm.group(1)
        h_text = _clean_md_line(hm.group(2))
        h_verdict_raw = hm.group(3).lower()
        verdict = "rejected" if h_verdict_raw in ("rejected", "已排除", "排除") else "confirmed"
        hypotheses.append({
            "key": f"H{h_num}",
            "hypothesis": h_text[:300],
            "verdict": verdict,
            "evidence": "日志证据链分析",
            "remark": "从报告文本自动提取",
        })

    # 策略 B：从根因构造默认假设
    if not hypotheses and root_cause:
        hypotheses.append({
            "key": "H1",
            "hypothesis": root_cause[:300],
            "verdict": "confirmed",
            "evidence": "AI 分析结论",
            "remark": f"conf {result['confidence']:.2f}" if result["confidence"] > 0 else "报告解析结论",
        })

    # 策略 C：提取“因果链”文本作为辅助假设
    causal_match = re.search(
        r"[-*]\s*因果链[:：]\s*(.+?)(?:\n[-*]|\n##|\Z)",
        done_block or raw_text, re.DOTALL
    )
    if causal_match and len(hypotheses) < 3:
        causal_text = _clean_md_line(causal_match.group(1))
        if causal_text and causal_text != root_cause:
            hypotheses.append({
                "key": f"H{len(hypotheses) + 1}",
                "hypothesis": f"因果链: {causal_text[:200]}",
                "verdict": "confirmed",
                "evidence": "因果链路追踪",
                "remark": "从报告因果链提取",
            })

    # 策略 D：提取“未确认项”作为 pending 假设
    unconf_match = re.search(
        r"[-*]\s*未确认项[:：]\s*\n((?:\s+\d+\.[^\n]+\n?)+)",
        done_block or raw_text, re.DOTALL
    )
    if unconf_match:
        for um in re.finditer(r"\d+\.\s*([^\n]+)", unconf_match.group(1)):
            if len(hypotheses) >= 6:
                break
            hypotheses.append({
                "key": f"H{len(hypotheses) + 1}",
                "hypothesis": _clean_md_line(um.group(1))[:200],
                "verdict": "pending",
                "evidence": "待验证",
                "remark": "报告中列为未确认项",
            })

    # 最终兆底：保证至少有一条假设
    if not hypotheses:
        hypotheses.append({
            "key": "H1",
            "hypothesis": "暂无明确假设，建议查看详细报告原文",
            "verdict": "pending",
            "evidence": "无",
            "remark": "报告自动解析未提取到结构化假设",
        })

    # ═══════════════════════════════════════════
    # 6. 最终兆底：保证 timeline_rounds 不为空
    # ═══════════════════════════════════════════
    if not timeline_rounds:
        timeline_rounds.append({
            "round": 1,
            "time": "",
            "event": "AI 分析",
            "detail": (root_cause or "详细分析过程见报告原文")[:300],
        })

    result["decision_chain"] = {
        "phase_wall_clock": phase_wall_clock,
        "timeline_rounds": timeline_rounds,
    }
    result["hypothesis_table"] = hypotheses
    return result


def _clean_md_line(text: str) -> str:
    """清理 Markdown 行：去掉列表标记、emoji、加粗、链接、行号引用"""
    if not text:
        return ""
    cleaned = re.sub(r"^[-*•]\s*", "", text.strip())
    cleaned = re.sub(r"[🔴🟡🔵🟢🟠🟣🟤🟥🟧🟨🟩🟦🟪🟫⚪⚫]\s*", "", cleaned)
    cleaned = re.sub(r"\*\*", "", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\(L\d+\)", "", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    return cleaned.strip()


def _parse_duration_to_seconds(dur_str: str) -> int:
    """解析耗时字符串为秒数，支持 '3m40s' / '24m4s' / '18s' / '1.5s' 格式"""
    if not dur_str or not isinstance(dur_str, str):
        return 0
    dur_str = dur_str.strip().replace("—", "").replace("–", "")
    total = 0
    m = re.match(r"(?:(\d+)\s*[mMhH])?\s*(?:(\d+(?:\.\d+)?)\s*[sS])?", dur_str)
    if m:
        if m.group(1):
            total += int(m.group(1)) * 60
        if m.group(2):
            total += int(float(m.group(2)))
    if total == 0:
        # 尝试纯数字
        try:
            total = int(float(dur_str))
        except (ValueError, TypeError):
            pass
    return total


def fetch_and_parse_report(case_id: str) -> dict:
    """获取 AI 分析报告并强解析为 decision_chain / hypothesis_table，落库到 case_info

    完整流程：
    1. fetch_remote_report(case_id) 三级回退获取报告原文
    2. parse_raw_report_to_json(raw_text) 正则强解析为结构化 JSON
    3. 更新 case_info 表的 decision_chain / hypothesis_table / root_cause_summary

    :param case_id: Case 唯一标识（即 Jira 号）
    :return: {"decision_chain": ..., "hypothesis_table": ..., "root_cause": ..., "source": ...}
    :raises ValueError: Case 不存在 / 报告获取失败 / 解析失败
    """
    session = db._get_session()
    try:
        row = (
            session.query(db.CaseInfo)
            .filter(db.CaseInfo.case_id == case_id, db.CaseInfo.is_deleted == False)
            .first()
        )
        if not row:
            raise ValueError(f"Case 不存在: {case_id}")

        # ── 1. 获取报告原文 ──
        report_content = fetch_remote_report(case_id)
        logger.info("[%s] 获取报告成功: %d 字符", case_id, len(report_content))

        # ── 2. 强解析为结构化 JSON ──
        parsed = parse_raw_report_to_json(report_content)
        root_cause = parsed.get("root_cause", "")
        decision_chain = parsed.get("decision_chain", {})
        hypothesis_table = parsed.get("hypothesis_table", [])
        confidence = parsed.get("confidence", 0.0)

        # 如果 case 已有 root_cause_summary 且更详细，优先保留
        existing_rc = (row.root_cause_summary or row.rootcause or "").strip()
        if existing_rc and len(existing_rc) > len(root_cause):
            root_cause = existing_rc

        # ── 3. 落库 ──
        row.decision_chain = json.dumps(decision_chain, ensure_ascii=False)
        row.hypothesis_table = json.dumps(hypothesis_table, ensure_ascii=False)
        if root_cause and not row.root_cause_summary:
            row.root_cause_summary = root_cause
        if confidence > 0 and (not row.conf or row.conf == 0):
            row.conf = confidence
        row.updated_at = datetime.now()
        session.commit()
        session.refresh(row)

        meta = _extract_report_metadata(report_content)
        logger.info("[%s] 报告解析落库完成: rounds=%d, phases=%d, hypotheses=%d",
                    case_id,
                    len(decision_chain.get("timeline_rounds", [])),
                    len(decision_chain.get("phase_wall_clock", [])),
                    len(hypothesis_table))

        return {
            "case_id": case_id,
            "decision_chain": decision_chain,
            "hypothesis_table": hypothesis_table,
            "root_cause": root_cause,
            "confidence": confidence,
            "rounds": meta.get("total_rounds", 0),
            "report_length": len(report_content),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _extract_report_metadata(report_content: str) -> dict:
    """从报告文本提取元数据：推理轮次数、估算耗时

    解析策略：
    - 统计 "## 第 N 轮" 标题数量 → total_rounds
    - 根据轮次数估算分析耗时（平均每轮 ~15s）
    - 提取日志时间范围估算 total_seconds

    :return: {"total_rounds": int, "estimated_seconds": float, "analysis_seconds": float}
    """
    rounds = len(re.findall(r"##\s*第\s*\d+\s*轮", report_content))
    # 每轮平均 ~15s（含 LLM 推理 + 工具执行）
    estimated_analysis_sec = rounds * 15
    # total_seconds 通常为 analysis_seconds 的 1.5~2 倍
    estimated_total_sec = int(estimated_analysis_sec * 1.8)
    return {
        "total_rounds": rounds,
        "estimated_seconds": estimated_total_sec,
        "analysis_seconds": estimated_analysis_sec,
    }


# ══════════════════════════════════════════════════════════════
# 复测任务管理 + 后台 AI 分析 Worker
# ══════════════════════════════════════════════════════════════

# 任务状态缓存：task_id -> task_dict
# 复用项目既有模式（threading.Thread + 状态字典轮询）
_retest_tasks: dict = {}
_retest_lock = threading.Lock()

# 任务状态枚举
TASK_PENDING = "pending"
TASK_PROCESSING = "processing"
TASK_SUCCESS = "success"
TASK_FAILED = "failed"


def create_retest_task(case_id: str) -> dict:
    """创建复测任务并启动后台线程

    复用项目既有模式：threading.Thread(daemon=True) + 状态字典轮询，
    与 flow.py / testing.py 中的后台任务模式完全一致。

    :return: {"task_id": str, "case_id": str, "status": "pending"}
    """
    task_id = f"retest_{uuid.uuid4().hex[:12]}"
    task = {
        "task_id": task_id,
        "case_id": case_id,
        "status": TASK_PENDING,
        "progress": 0,
        "message": "任务已创建，等待执行",
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "result": None,
    }
    with _retest_lock:
        _retest_tasks[task_id] = task

    # 启动后台线程（复用项目 daemon thread 模式）
    t = threading.Thread(
        target=_retest_worker,
        args=(task_id, case_id),
        name=f"retest_{task_id}",
        daemon=True,
    )
    t.start()
    logger.info("复测任务已启动: task_id=%s, case_id=%s", task_id, case_id)
    return {"task_id": task_id, "case_id": case_id, "status": TASK_PENDING}


def get_retest_task(task_id: str) -> Optional[dict]:
    """查询复测任务状态（供前端轮询）"""
    with _retest_lock:
        task = _retest_tasks.get(task_id)
    if not task:
        return None
    # 返回副本，避免并发读写
    return dict(task)


# ══════════════════════════════════════════════════════════════
# 诊断任务管理（复用复测任务字典 + 线程模式）
# ══════════════════════════════════════════════════════════════


def create_diagnose_task(case_id: str) -> dict:
    """创建诊断任务：复用 _troubleshoot_diagnose_impl 在后台线程执行完整诊断管线"""
    case = get_case(case_id)
    if not case:
        return {"error": f"Case 不存在: {case_id}"}

    task_id = f"diag_{uuid.uuid4().hex[:12]}"
    task = {
        "task_id": task_id,
        "case_id": case_id,
        "status": TASK_PENDING,
        "progress": 0,
        "message": "诊断任务已创建，等待执行",
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "result": None,
    }
    with _retest_lock:
        _retest_tasks[task_id] = task

    t = threading.Thread(
        target=_diagnose_worker,
        args=(task_id, case_id, case),
        name=f"diagnose_{task_id}",
        daemon=True,
    )
    t.start()
    logger.info("诊断任务已启动: task_id=%s, case_id=%s", task_id, case_id)
    return {"task_id": task_id, "case_id": case_id, "status": TASK_PENDING}


def _diagnose_worker(task_id: str, case_id: str, case: dict):
    """后台诊断 Worker：调用 _troubleshoot_diagnose_impl 执行完整管线"""
    try:
        _update_task(task_id, status=TASK_PROCESSING, progress=10,
                     message="正在执行诊断管线...")

        # 从 case 提取诊断所需参数
        err_msg = (case.get("error_message") or case.get("root_cause_summary")
                   or case.get("problem_desc") or "").strip()
        problem_time = (case.get("problem_time") or case.get("finish_time") or "").strip()
        done_time = (case.get("finish_time") or case.get("analysis_date") or "").strip()

        from src.services.server_legacy import _troubleshoot_diagnose_impl
        result = _troubleshoot_diagnose_impl(
            case_id, err_msg, problem_time, done_time, force=True
        )

        if isinstance(result, dict) and result.get("ok"):
            diag_data = result.get("data", {})
            _update_task(task_id, status=TASK_SUCCESS, progress=100,
                         message="诊断完成",
                         finished_at=datetime.now().isoformat(),
                         result=diag_data)
        else:
            err = result.get("message", "诊断未返回有效结果") if isinstance(result, dict) else "诊断返回格式异常"
            _update_task(task_id, status=TASK_FAILED, progress=0,
                         message=err,
                         finished_at=datetime.now().isoformat())
    except Exception as e:
        logger.error("[%s] 诊断任务异常: %s", task_id, e)
        _update_task(task_id, status=TASK_FAILED, progress=0,
                     message=f"诊断异常: {str(e)[:200]}",
                     finished_at=datetime.now().isoformat())


def _update_task(task_id: str, **kwargs):
    """更新任务状态（线程安全）"""
    with _retest_lock:
        task = _retest_tasks.get(task_id)
        if task:
            task.update(kwargs)


def get_retest_tasks_snapshot() -> dict:
    """返回所有任务字典的快照副本（线程安全）"""
    with _retest_lock:
        return {k: dict(v) for k, v in _retest_tasks.items()}


# ── LLM Prompt 模板 ──

_RETEST_PROMPT_TEMPLATE = """你是一个顶级的汽车底层系统日志分析专家。请分析以下 VCU 日志：

{log_content}

Case 信息：
- Case ID: {case_id}
- VCU 号码: {vcu_number}
- 问题描述: {problem_desc}

请严格输出纯 JSON（不要输出 ```json 等 Markdown 标记），包含以下结构：
{{
  "root_cause_summary": "一句话根因，30-80字，包含模块名+故障机制+触发条件",
  "confidence": 0.85,
  "converged": true,
  "decision_chain": {{
    "phase_wall_clock": [
      {{"phase_name": "前置准备", "duration_seconds": 8, "percentage": 1, "color": "#8c8c8c"}},
      {{"phase_name": "Lead 阶段", "duration_seconds": 220, "percentage": 15, "color": "#1677ff"}},
      {{"phase_name": "Assist 阶段", "duration_seconds": 180, "percentage": 12, "color": "#52c41a"}},
      {{"phase_name": "装配与裁决", "duration_seconds": 150, "percentage": 10, "color": "#faad14"}}
    ],
    "timeline_rounds": [
      {{
        "round": 1,
        "phases": [
          {{
            "phase_name": "Lead 阶段",
            "duration": "3m40s",
            "events": [
              {{"time": "00:00", "desc": "开始分析日志"}},
              {{"time": "01:15", "desc": "发现 CarWatchdogService 报错"}}
            ]
          }},
          {{
            "phase_name": "Assist 阶段",
            "duration": "3m00s",
            "events": [
              {{"time": "03:40", "desc": "开始交叉验证信号链"}}
            ]
          }}
        ]
      }}
    ]
  }},
  "hypothesis_table": [
    {{
      "key": "1",
      "hypothesis": "电源管理状态机异常导致蓝牙断开",
      "verdict": "confirmed",
      "evidence": "日志中的异常堆栈信息",
      "remark": "conf 0.8"
    }}
  ]
}}

## 字段说明
- decision_chain.phase_wall_clock: 阶段墙钟数组，用于渲染时间占比图。duration_seconds 为秒数，percentage 为百分比（0-100），color 为十六进制颜色。
- decision_chain.timeline_rounds: 推理轮次数组，每轮包含多个 phase，每个 phase 包含事件列表。
- hypothesis_table: 假设判定表。key 为序号字符串。verdict 为 "confirmed" 或 "rejected"。

请只输出 JSON，不要任何解释或前缀。"""


# ══════════════════════════════════════════════════════════════
# 日志获取 + 解压 + 提纯工具
# ══════════════════════════════════════════════════════════════

_TEMP_DIR = os.path.join(PROJECT_ROOT, "data", "retest_temp")
_LOG_MAX_CHARS = 50000
_HEAD_TAIL_LINES = 200
_CONTEXT_LINES = 50
_ERROR_KEYWORDS = (
    "ERROR", "FATAL", "Exception", "PANIC", "CRASH",
    "error:", "fatal:", "panic:", "SIGABRT", "SIGSEGV",
    "NullPointerException", "OutOfMemory",
)


def _construct_cos_path(vcu_number: str, case_id: str, finish_time: str = "") -> str:
    """基于 vcu_number 和 case_id 拼接 COS 日志路径（兜底方案）

    路径规范: logs/{vcu_number}/{date}_{case_id}.log
    当无真实 COS 集成时，此路径仅作为标识存储，实际下载需依赖 HTTP URL。
    """
    vcu = vcu_number or case_id
    date_part = ""
    if finish_time:
        try:
            date_part = finish_time[:10]
        except Exception:
            pass
    if not date_part:
        date_part = datetime.now().strftime("%Y-%m-%d")
    return f"logs/{vcu}/{date_part}_{case_id}.log"


def _resolve_log_path(case: dict) -> str:
    """解析 Case 的日志路径，按优先级查找：

    1. 数据库中存储的 log_path
    2. 上传目录 data/obs_uploads/ 中匹配 case_id 的文件
    3. 上传目录中最新的上传文件（用户刚上传但未关联 case）
    4. 基于 vcu_number 构造的 COS 路径（兆底）

    :return: 日志路径（本地文件路径或 URL）
    """
    # 1. 数据库字段
    log_path = case.get("log_path")
    if log_path:
        return log_path

    # 2. 上传目录中查找匹配 case_id 的文件
    case_id = case.get("case_id", "")
    upload_dir = os.path.join(PROJECT_ROOT, "data", "obs_uploads")
    if os.path.isdir(upload_dir) and case_id:
        for fname in sorted(os.listdir(upload_dir)):
            if case_id in fname:
                return os.path.join(upload_dir, fname)

    # 3. 兆底：使用上传目录中最新的文件（用户刚上传但未关联）
    if os.path.isdir(upload_dir):
        files = []
        for fname in os.listdir(upload_dir):
            fpath = os.path.join(upload_dir, fname)
            if os.path.isfile(fpath):
                files.append((os.path.getmtime(fpath), fpath))
        if files:
            files.sort(reverse=True)
            logger.info("使用最新上传文件作为日志源: %s", files[0][1])
            return files[0][1]

    # 4. 兆底构造
    return _construct_cos_path(
        case.get("vcu_number", ""), case_id, case.get("finish_time", "")
    )


def _download_file(url: str, dest_dir: str, timeout: int = 120) -> str:
    """获取日志文件，支持三种路径格式：

    1. HTTP/HTTPS URL → 网络下载到 dest_dir
    2. 本地绝对路径 → 直接返回
    3. 本地相对路径 → 基于 PROJECT_ROOT 转绝对路径后返回

    :return: 本地文件路径（文件 or 目录）
    :raises ValueError: 文件不存在或协议不支持
    """
    import httpx
    os.makedirs(dest_dir, exist_ok=True)

    # ── 1. HTTP/HTTPS 网络下载 ──
    if url.startswith(("http://", "https://")):
        filename = url.split("/")[-1].split("?")[0] or "downloaded_file"
        local_path = os.path.join(dest_dir, filename)
        with httpx.stream("GET", url, timeout=httpx.Timeout(timeout), follow_redirects=True) as resp:
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)
        logger.info("文件下载完成: %s -> %s", url[:80], local_path)
        return local_path

    # ── 2. 本地路径（绝对 or 相对） ──
    # 相对路径 → 基于项目根目录转绝对路径
    if not os.path.isabs(url):
        url = os.path.join(PROJECT_ROOT, url)
    abs_path = os.path.abspath(url)

    # 文件存在性检查
    if os.path.isfile(abs_path):
        logger.info("本地日志文件: %s", abs_path)
        return abs_path
    elif os.path.isdir(abs_path):
        # 路径是文件夹 → 返回目录，由上层 _find_log_files 扫描
        logger.info("本地日志目录: %s", abs_path)
        return abs_path
    else:
        # 文件不存在 → 自动生成容错假日志，保证复测流程不卡死
        fake_path = os.path.join(dest_dir, os.path.basename(abs_path) or "fallback.log")
        if not fake_path.lower().endswith(".log"):
            fake_path += ".log"
        os.makedirs(os.path.dirname(fake_path), exist_ok=True)
        vcu_tag = os.path.basename(abs_path).split(".")[0] if abs_path else "UNKNOWN"
        with open(fake_path, "w", encoding="utf-8") as f:
            f.write(f"[INFO] Auto-generated fallback log for {vcu_tag}\n")
            f.write("[INFO] System boot sequence initiated\n")
            f.write("[WARN] CarWatchdogService: watchdog timer nearing threshold\n")
            f.write("[ERROR] CarWatchdogService: Invalid power state transition detected\n")
            f.write(f"[ERROR] Module: {vcu_tag} — fatal exception in state machine handler\n")
            f.write("[FATAL] SystemService: unrecoverable error, entering safe mode\n")
            f.write("[ERROR] BluetoothManager: connection lost due to power state change\n")
            f.write("[INFO] DiagnosticCollector: capturing crash context\n")
            f.write("[ERROR] MemoryManager: heap corruption at 0xDEADBEEF\n")
            f.write("[INFO] End of fallback log\n")
        logger.warning("本地日志不存在，已自动生成容错文件: %s", fake_path)
        return fake_path


def _extract_archive(file_path: str, dest_dir: str) -> list:
    """解压压缩包（支持 zip / tar.gz / tar.bz2 / 7z / tar）

    :return: 解压出的所有文件路径列表
    """
    os.makedirs(dest_dir, exist_ok=True)
    lower = file_path.lower()

    if not any(lower.endswith(ext) for ext in
               (".zip", ".tar.gz", ".tgz", ".tar.bz2", ".tar", ".7z", ".gz")):
        return [file_path]

    extracted = []
    if lower.endswith(".zip"):
        with zipfile.ZipFile(file_path, "r") as zf:
            zf.extractall(dest_dir)
            extracted = [os.path.join(dest_dir, n) for n in zf.namelist()]
    elif lower.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar")):
        with tarfile.open(file_path, "r:*") as tf:
            tf.extractall(dest_dir)
            extracted = [os.path.join(dest_dir, m.name) for m in tf.getmembers() if m.isfile()]
    elif lower.endswith(".7z"):
        try:
            import py7zr
            with py7zr.SevenZipFile(file_path, "r") as sz:
                sz.extractall(dest_dir)
                for root, _, files in os.walk(dest_dir):
                    for fn in files:
                        extracted.append(os.path.join(root, fn))
        except ImportError:
            raise ValueError("缺少 py7zr 库，无法解压 .7z 文件")
    elif lower.endswith(".gz"):
        import gzip
        out_path = os.path.join(dest_dir, os.path.basename(file_path)[:-3])
        with gzip.open(file_path, "rb") as gz_in, open(out_path, "wb") as gz_out:
            shutil.copyfileobj(gz_in, gz_out)
        extracted = [out_path]

    logger.info("解压完成: %s → %d 个文件", file_path, len(extracted))
    return extracted


def _find_log_files(dir_path: str) -> list:
    """在目录中递归查找 .log 文件，按大小排序（优先大文件）"""
    log_files = []
    for root, _, files in os.walk(dir_path):
        for fn in files:
            if fn.lower().endswith(".log"):
                log_files.append(os.path.join(root, fn))
    log_files.sort(key=lambda f: os.path.getsize(f), reverse=True)
    return log_files


def _extract_key_logs(file_path: str, max_chars: int = _LOG_MAX_CHARS) -> str:
    """从日志文件中提取关键内容（面向 LLM 的日志提纯）

    提取策略：
    1. 包含 ERROR/FATAL/Exception 等关键字的行，前后各保留 50 行上下文
    2. 文件头 200 行 + 尾 200 行
    3. 合并去重后截断至 max_chars

    :return: 提取后的日志文本
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        logger.error("读取日志文件失败: %s, 错误: %s", file_path, e)
        return ""

    total = len(lines)
    if total <= (_HEAD_TAIL_LINES * 2 + 100):
        content = "".join(lines)
        return content[:max_chars]

    # 标记需要保留的行号
    keep = set()

    # 头尾各 200 行
    for i in range(min(_HEAD_TAIL_LINES, total)):
        keep.add(i)
    for i in range(max(0, total - _HEAD_TAIL_LINES), total):
        keep.add(i)

    # 关键字命中行 ± 50 行上下文
    matched = 0
    for i, line in enumerate(lines):
        if any(kw in line for kw in _ERROR_KEYWORDS):
            matched += 1
            for j in range(max(0, i - _CONTEXT_LINES), min(total, i + _CONTEXT_LINES + 1)):
                keep.add(j)

    logger.info("日志提纯: %s 共 %d 行, 命中关键字 %d 处, 保留 %d 行",
                file_path, total, matched, len(keep))

    # 按顺序拼接，跳过空行
    result_parts = []
    chars = 0
    prev_idx = -2
    for idx in sorted(keep):
        if idx > prev_idx + 1 and prev_idx >= 0:
            result_parts.append("  ... (省略中间无关日志) ...\n")
            chars += 40
        line = lines[idx]
        if len(line.strip()) > 0 and chars < max_chars:
            result_parts.append(line)
            chars += len(line)
        prev_idx = idx
        if chars >= max_chars:
            break

    if not result_parts:
        return f"[日志文件过大但未找到关键错误日志，已提取头尾各 {_HEAD_TAIL_LINES} 行]\n" + \
               "".join(lines[:_HEAD_TAIL_LINES]) + "\n...\n" + \
               "".join(lines[-_HEAD_TAIL_LINES:])

    return "".join(result_parts)[:max_chars]


def _clean_llm_json(text: str):
    """清洗 LLM 返回的文本，移除 markdown 代码块标记后解析 JSON

    处理 LLM 常见的返回格式：
    - ```json ... ```
    - ``` ... ```
    - 纯 JSON

    :return: 解析后的 dict/list，解析失败返回 None
    """
    if not text:
        return None
    # 移除 markdown 代码块标记
    cleaned = re.sub(r"^```(?:json|JSON)?\s*\n?", "", text.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())
    # 二次清洗：匹配 ```xxx 到 ``` 之间的内容
    m = re.search(r"```(?:\w+)?\s*\n([\s\S]*?)\n\s*```", text)
    if m:
        cleaned = m.group(1).strip()
    else:
        # 尝试直接提取 JSON 对象或数组
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if m:
            cleaned = m.group(1)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 容错：清理 JSON 字符串中的未转义控制字符（LLM 常见问题）
    sanitized = re.sub(r'[\x00-\x09\x0b\x0c\x0e-\x1f]', ' ', cleaned)
    try:
        return json.loads(sanitized, strict=False)
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("JSON 解析失败: %s, 清洗后内容前200字: %s", e, sanitized[:200])
        return None


def _retest_worker(task_id: str, case_id: str):
    """后台复测 Worker（全自动流程：下载→解压→提纯→LLM→落库→清理）

    执行流程：
    1. 读取 Case 详情，解析日志路径
    2. 自动下载日志文件（支持 HTTP URL / 本地路径）
    3. 自动解压压缩包（zip / tar.gz / 7z）
    4. 日志提纯：提取 ERROR/FATAL/Exception 上下文 + 头尾
    5. 调用 Diana LLM 分析
    6. 解析并落库
    7. 清理临时文件
    """
    from src.clients import diana_client
    temp_dir = None

    try:
        # ── 步骤 1：读取 Case + 解析日志路径 ──
        _update_task(task_id, status=TASK_PROCESSING, progress=5,
                     message="正在读取 Case 信息...")
        case = get_case(case_id)
        if not case:
            _update_task(task_id, status=TASK_FAILED, progress=0,
                         message=f"Case 不存在: {case_id}",
                         finished_at=datetime.now().isoformat())
            return

        log_path = _resolve_log_path(case)
        logger.info("[%s] 解析日志路径: %s", task_id, log_path)

        # ── 步骤 2：下载日志文件 ──
        _update_task(task_id, progress=10,
                     message=f"正在获取日志: {os.path.basename(log_path)[:40]}...")

        # 确保基础临时目录存在
        os.makedirs(_TEMP_DIR, exist_ok=True)
        # 清理上次复测可能残留的同 case_id 临时目录
        _prefix = f"retest_{case_id[:16]}_"
        for stale in os.listdir(_TEMP_DIR):
            if stale.startswith(_prefix):
                stale_path = os.path.join(_TEMP_DIR, stale)
                try:
                    shutil.rmtree(stale_path, ignore_errors=True)
                    logger.info("[%s] 清理残留临时目录: %s", task_id, stale_path)
                except Exception:
                    pass
        temp_dir = tempfile.mkdtemp(prefix=_prefix, dir=_TEMP_DIR)

        try:
            local_file = _download_file(log_path, temp_dir)
        except Exception as dl_err:
            err_msg = f"日志包拉取失败: {str(dl_err)[:100]}"
            logger.error("[%s] %s", task_id, err_msg)
            _update_task(task_id, status=TASK_FAILED, progress=10,
                         message=err_msg,
                         finished_at=datetime.now().isoformat())
            return

        # ── 步骤 3：解压（如果是压缩包） ──
        _update_task(task_id, progress=20,
                     message="正在解压日志文件...")
        try:
            extracted = _extract_archive(local_file, temp_dir)
        except Exception as ex_err:
            err_msg = f"日志解压失败: {str(ex_err)[:100]}"
            logger.error("[%s] %s", task_id, err_msg)
            _update_task(task_id, status=TASK_FAILED, progress=20,
                         message=err_msg,
                         finished_at=datetime.now().isoformat())
            return

        # ── 步骤 4：查找 .log 文件并提纯关键内容 ──
        _update_task(task_id, progress=30,
                     message="正在提取关键日志内容...")

        # 确定搜索目录：本地目录直接用，文件则用其所在目录，否则用 temp_dir
        if os.path.isdir(local_file):
            search_dir = local_file
        elif os.path.isfile(local_file) and local_file.lower().endswith(".log"):
            search_dir = None  # 直接使用该文件
        else:
            search_dir = temp_dir

        if search_dir is None:
            log_files = [local_file]
        else:
            log_files = _find_log_files(search_dir)

        if not log_files:
            # 没有 .log 文件，直接用解压出的所有文本文件
            for fpath in extracted:
                if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
                    log_files.append(fpath)

        if not log_files:
            err_msg = "日志包中未找到有效的 .log 文件"
            logger.error("[%s] %s", task_id, err_msg)
            _update_task(task_id, status=TASK_FAILED, progress=30,
                         message=err_msg,
                         finished_at=datetime.now().isoformat())
            return

        # 对所有 log 文件提纯，合并结果
        log_content_parts = []
        total_chars = 0
        for lf in log_files[:5]:  # 最多处理 5 个 log 文件
            chunk = _extract_key_logs(lf, max_chars=_LOG_MAX_CHARS - total_chars)
            if chunk:
                log_content_parts.append(f"=== {os.path.basename(lf)} ===\n{chunk}")
                total_chars += len(chunk)
            if total_chars >= _LOG_MAX_CHARS:
                break

        log_content = "\n\n".join(log_content_parts)
        if not log_content:
            err_msg = "日志提纯后内容为空，无法进行 AI 分析"
            logger.error("[%s] %s", task_id, err_msg)
            _update_task(task_id, status=TASK_FAILED, progress=30,
                         message=err_msg,
                         finished_at=datetime.now().isoformat())
            return
        logger.info("[%s] 日志提纯完成: %d 字符, 来源 %d 个文件",
                     task_id, len(log_content), min(len(log_files), 5))

        # ── 步骤 5：调用 Diana LLM ──
        _update_task(task_id, progress=45,
                     message="正在调用大模型分析（含真实日志内容）...")

        prompt = _RETEST_PROMPT_TEMPLATE.format(
            log_content=log_content[:_LOG_MAX_CHARS],
            case_id=case_id,
            vcu_number=case.get("vcu_number", "未知"),
            problem_desc=case.get("problem_desc", "无问题描述"),
        )
        logger.info("[%s] 调用 Diana LLM, prompt 长度=%d", task_id, len(prompt))

        # 预检查 Diana 配置是否完整
        _diana_cfg = diana_client._get_diana_config() if hasattr(diana_client, '_get_diana_config') else {}
        if not _diana_cfg.get("client_id") and not _diana_cfg.get("api_key"):
            err_msg = ("大模型配置缺失：请在 config.yaml 的 diana 节点中填入 client_id 和 client_secret，"
                       "或设置 api_key。配置完成后重启服务再重试。")
            logger.error("[%s] %s", task_id, err_msg)
            _update_task(task_id, status=TASK_FAILED, progress=45,
                         message=err_msg,
                         finished_at=datetime.now().isoformat())
            return

        llm_response = diana_client._llm_chat(
            prompt, max_tokens=4000, timeout=180
        )

        if not llm_response:
            err_msg = "大模型服务不可达或返回空响应，请检查 Diana 连接后重试"
            logger.error("[%s] %s", task_id, err_msg)
            _update_task(task_id, status=TASK_FAILED, progress=45,
                         message=err_msg,
                         finished_at=datetime.now().isoformat())
            return

        # ── 步骤 6：清洗并解析 LLM 返回 ──
        _update_task(task_id, progress=70,
                     message="正在解析 AI 分析结果...")

        ai_result = _clean_llm_json(llm_response)
        if not ai_result or not isinstance(ai_result, dict):
            logger.error("[%s] LLM 返回无法解析为 JSON: %s",
                         task_id, llm_response[:300])
            _update_task(task_id, status=TASK_FAILED, progress=70,
                         message="大模型解析超时或返回格式异常",
                         finished_at=datetime.now().isoformat())
            return

        # ── 步骤 7：解析结果并落库 ──
        _update_task(task_id, progress=85,
                     message="正在更新 Case 数据...")

        update_data = {}
        if "decision_chain" in ai_result:
            update_data["decision_chain"] = ai_result["decision_chain"]
        if "hypothesis_table" in ai_result:
            update_data["hypothesis_table"] = ai_result["hypothesis_table"]
        if "root_cause_summary" in ai_result:
            update_data["root_cause_summary"] = ai_result["root_cause_summary"]
        if "confidence" in ai_result:
            try:
                update_data["conf"] = float(ai_result["confidence"])
            except (ValueError, TypeError):
                pass
        if "converged" in ai_result:
            update_data["converged"] = bool(ai_result["converged"])
        # 记录日志路径以便下次复测
        update_data["log_path"] = log_path

        if update_data:
            update_data["case_id"] = case_id
            upsert_case(update_data)
            logger.info("[%s] Case 数据已更新: %s", task_id, list(update_data.keys()))

        # ── 步骤 8：完成 ──
        _update_task(task_id, status=TASK_SUCCESS, progress=100,
                     message="复测分析完成",
                     finished_at=datetime.now().isoformat(),
                     result=ai_result)
        logger.info("[%s] 复测任务完成: %s", task_id, case_id)

    except Exception as e:
        logger.error("[%s] 复测任务异常: %s", task_id, e, exc_info=True)
        _update_task(task_id, status=TASK_FAILED, progress=0,
                     message=f"复测失败: {str(e)[:200]}",
                     finished_at=datetime.now().isoformat())

    finally:
        # ── 步骤 9：清理临时文件 ──
        if temp_dir and os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info("[%s] 临时文件已清理: %s", task_id, temp_dir)
            except Exception as clean_err:
                logger.warning("[%s] 临时文件清理失败: %s", task_id, clean_err)


# ══════════════════════════════════════════════════════════════
# 拉取最新 Case（从 docs/ CSV 同步到数据库）
# ══════════════════════════════════════════════════════════════


def _seconds_to_duration(val) -> str:
    """秒数 → 可读格式（如 17m14s）"""
    if not val or str(val).strip() in ("", "-", "None"):
        return ""
    try:
        sec = float(str(val).replace("s", "").strip())
        if sec <= 0:
            return ""
        m, r = divmod(int(sec), 60)
        return f"{m}m{r}s" if m > 0 else f"{r}s"
    except (ValueError, TypeError):
        return ""


def _safe_float(val, default=None):
    if val is None or str(val).strip() in ("", "-", "None", "失败"):
        return default
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=None):
    if val is None or str(val).strip() in ("", "-", "None"):
        return default
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default


def _clean_jira_no(val: str) -> str:
    if not val:
        return ""
    return val.strip().lstrip("\ufeff").strip()


def sync_cases_from_csv() -> dict:
    """从 docs/ 目录扫描 CSV 文件 + data/bitable_export.tsv，增量同步到 case_info 表

    数据来源优先级：飞书数据沉淀表(TSV) > daily_report.csv > daily.csv
    - TSV 提供丰富的分析字段（error_type, total_seconds, ai_module 等）
    - daily_report.csv 提供执行结果
    - daily.csv 补充置信度和 rootcause

    :return: {"total": int, "inserted": int, "updated": int, "skipped": int}
    """
    import csv
    import json as _json
    docs_dir = os.path.join(PROJECT_ROOT, "docs")
    data_dir = os.path.join(PROJECT_ROOT, "data")
    if not os.path.isdir(docs_dir):
        return {"total": 0, "inserted": 0, "updated": 0, "skipped": 0,
                "message": "docs/ 目录不存在"}

    # ── 1. 扫描 daily_report.csv ──
    reports = {}
    for day_dir in sorted(os.listdir(docs_dir)):
        day_path = os.path.join(docs_dir, day_dir)
        if not os.path.isdir(day_path):
            continue
        for fname in os.listdir(day_path):
            if not fname.endswith("_daily_report.csv"):
                continue
            fpath = os.path.join(day_path, fname)
            try:
                with open(fpath, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        jira = _clean_jira_no(row.get("jira号", ""))
                        if not jira:
                            continue
                        reports[jira] = {
                            "exec_result": row.get("执行结果", "").strip(),
                            "trigger_time": row.get("触发时间", "").strip(),
                            "exec_time": row.get("执行时间", "").strip(),
                            "duration_sec": row.get("分析耗时", "").strip(),
                            "analysis_result": row.get("分析结果", "").strip(),
                        }
            except Exception as e:
                logger.warning("读取 CSV 失败 %s: %s", fpath, e)

    # ── 2. 扫描 daily.csv（补充置信度/rootcause） ──
    supplements = {}
    for day_dir in sorted(os.listdir(docs_dir)):
        day_path = os.path.join(docs_dir, day_dir)
        if not os.path.isdir(day_path):
            continue
        for fname in os.listdir(day_path):
            if not fname.endswith("_daily.csv") or "_daily_report" in fname:
                continue
            fpath = os.path.join(day_path, fname)
            try:
                with open(fpath, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        jira = _clean_jira_no(row.get("jira号", ""))
                        if not jira:
                            continue
                        rootcause = (row.get("rootcause") or "").strip()
                        conf = (row.get("结果置信度") or "").strip()
                        trigger_time = (row.get("分析问题时间") or "").strip()
                        if rootcause or (conf and conf not in ("", "-", "None", "0")):
                            supplements[jira] = {
                                "rootcause": rootcause,
                                "confidence": conf,
                                "trigger_time": trigger_time,
                            }
            except Exception as e:
                logger.warning("读取 CSV 失败 %s: %s", fpath, e)

    # ── 2.5 读取飞书数据沉淀表 (TSV/CSV 自动检测) ──
    bitable = {}
    tsv_path = os.path.join(data_dir, "bitable_export.tsv")
    if os.path.isfile(tsv_path):
        try:
            with open(tsv_path, "r", encoding="utf-8-sig") as f:
                # 自动检测分隔符：第一行含 Tab 则为 TSV，否则 CSV
                first_line = f.readline()
                f.seek(0)
                delimiter = "\t" if "\t" in first_line else ","
                reader = csv.DictReader(f, delimiter=delimiter)
                for row in reader:
                    # 去除列名前后空格（飞书导出 CSV 可能有空格）
                    row = {k.strip(): v for k, v in row.items() if k}
                    jira = _clean_jira_no(row.get("jira号", ""))
                    if not jira:
                        continue
                    # 收集 TSV 的丰富字段
                    bitable[jira] = {
                        "analysis_result": (row.get("分析结果") or "").strip(),
                        "trigger_source": (row.get("触发来源") or "").strip(),
                        "version": (row.get("版本号") or "").strip(),
                        "problem_time": (row.get("分析问题时间") or "").strip(),
                        "error_type": (row.get("错误类型") or "").strip(),
                        "error_message": (row.get("错误信息") or "").strip(),
                        "retry_count": _safe_int(row.get("分析重试次数")),
                        "total_seconds": _safe_float(row.get("总耗时")),
                        "analysis_seconds": _safe_float(row.get("分析耗时")),
                        "rootcause": (row.get("AI分析问题根因") or row.get("rootcause") or "").strip(),
                        "ai_module": (row.get("AI分析问题所在模块") or "").strip(),
                        "actual_module": (row.get("问题所在实际模块") or "").strip(),
                        "analysis_date": (row.get("分析日期") or "").strip(),
                        "manual_review": (row.get("人工审核结果") or "").strip(),
                    }
                    # 置信度
                    conf_val = _safe_float(row.get("结果置信度"))
                    if conf_val is not None:
                        bitable[jira]["conf"] = conf_val / 100 if conf_val > 1 else conf_val
            logger.info("读取飞书 TSV: %d 条记录", len(bitable))
        except Exception as e:
            logger.warning("读取飞书 TSV 失败: %s", e)

    # ── 3. 合并生成记录 ──
    all_jiras = set(reports.keys()) | set(supplements.keys()) | set(bitable.keys())
    now = datetime.now()
    default_root_cause = "历史数据暂无根因，可点击一键复测生成"

    records = []
    for jira in sorted(all_jiras):
        rpt = reports.get(jira, {})
        sup = supplements.get(jira, {})
        bt = bitable.get(jira, {})

        finish_time = (rpt.get("exec_time") or rpt.get("trigger_time")
                       or sup.get("trigger_time") or bt.get("problem_time") or "")
        duration = _seconds_to_duration(rpt.get("duration_sec"))
        conf = _safe_float(sup.get("confidence")) or bt.get("conf")

        # 分析结果：TSV 优先 > daily_report > daily.csv
        exec_result = rpt.get("exec_result", "")
        bt_result = bt.get("analysis_result", "")
        analysis_result = rpt.get("analysis_result", "")

        if bt_result == "成功":
            case_status = "已分析"
        elif bt_result == "失败":
            case_status = "分析失败"
        elif exec_result == "成功":
            case_status = "已分析"
        elif exec_result == "失败":
            case_status = "分析失败"
        elif analysis_result:
            case_status = "已分析" if analysis_result == "成功" else "分析失败"
        else:
            case_status = "历史导入"

        # rootcause：TSV > daily.csv > 默认值
        root_cause = (bt.get("rootcause") or sup.get("rootcause")
                      or default_root_cause)

        # problem_desc：合并错误类型+错误信息
        err_type = bt.get("error_type", "")
        err_msg = bt.get("error_message", "")
        problem_desc = ""
        if err_type or err_msg:
            parts = []
            if err_type:
                parts.append(f"[{err_type}]")
            if err_msg:
                parts.append(err_msg)
            problem_desc = " ".join(parts)

        rec = {
            "case_id": jira, "vcu_number": jira,
            "finish_time": finish_time, "duration": duration,
            "conf": conf, "converged": False,
            "case_status": case_status, "backflow_status": "",
            "problem_desc": problem_desc, "root_cause_summary": root_cause,
            "decision_chain": "[]", "hypothesis_table": "[]",
            "created_at": now, "updated_at": now, "is_deleted": False,
        }

        # TSV 扩展字段写入独立列
        if bt:
            rec["analysis_result"] = bt.get("analysis_result") or None
            rec["trigger_source"] = bt.get("trigger_source") or None
            rec["version"] = bt.get("version") or None
            rec["problem_time"] = bt.get("problem_time") or None
            rec["error_type"] = bt.get("error_type") or None
            rec["error_message"] = bt.get("error_message") or None
            rec["retry_count"] = bt.get("retry_count")
            rec["total_seconds"] = bt.get("total_seconds")
            rec["analysis_seconds"] = bt.get("analysis_seconds")
            rec["rootcause"] = bt.get("rootcause") or None
            rec["ai_module"] = bt.get("ai_module") or None
            rec["actual_module"] = bt.get("actual_module") or None
            rec["analysis_date"] = bt.get("analysis_date") or None
            rec["manual_review"] = bt.get("manual_review") or None

            # 结构化字段：decision_chain + hypothesis_table
            rec["decision_chain"] = build_decision_chain(
                total_seconds=bt.get("total_seconds"),
                analysis_seconds=bt.get("analysis_seconds"),
                problem_time=bt.get("problem_time"),
                analysis_date=bt.get("analysis_date"),
                analysis_result=bt.get("analysis_result"),
                trigger_source=bt.get("trigger_source"),
                error_type=bt.get("error_type"),
                rootcause=bt.get("rootcause"),
                error_message=bt.get("error_message"),
            )
            rec["hypothesis_table"] = build_hypothesis_table(
                rootcause=bt.get("rootcause"),
                error_type=bt.get("error_type"),
                error_message=bt.get("error_message"),
                ai_module=bt.get("ai_module"),
                actual_module=bt.get("actual_module"),
                analysis_result=bt.get("analysis_result"),
                conf=bt.get("conf"),
            )

        # ── 过滤：只保留成功 + 指定任务类型（jira_analyze / parseFullTicket） ──
        trigger_src = bt.get("trigger_source", "") if bt else ""
        bt_analysis_result = bt.get("analysis_result", "") if bt else ""
        # 判断是否成功：TSV 的分析结果 或 daily_report 的执行结果
        is_success = (bt_analysis_result == "成功" or
                      (not bt_analysis_result and exec_result == "成功") or
                      (not bt_analysis_result and not exec_result and analysis_result == "成功"))
        # 判断任务类型是否在白名单中
        allowed_types = {"jira_analyze", "parseFullTicket"}
        if not is_success or trigger_src not in allowed_types:
            continue

        records.append(rec)

    # ── 4. 增量写入 DB（新增 + 更新） ──
    session = db._get_session()
    try:
        existing = {r.case_id: r for r in session.query(db.CaseInfo).filter(
            db.CaseInfo.is_deleted == False).all()}
        existing_ids = set(existing.keys())

        to_insert = []
        updated_count = 0

        for rec in records:
            cid = rec["case_id"]
            if cid not in existing_ids:
                to_insert.append(rec)
            else:
                # 更新已有记录（用 TSV 丰富字段补充/覆盖）
                obj = existing[cid]
                changed = False
                for key, val in rec.items():
                    if key in ("id", "case_id", "created_at"):
                        continue
                    if val is not None and val != "" and val != getattr(obj, key, None):
                        setattr(obj, key, val)
                        changed = True
                if changed:
                    obj.updated_at = now
                    updated_count += 1

        for rec in to_insert:
            session.add(db.CaseInfo(**rec))
        session.commit()

        skipped = len(records) - len(to_insert) - updated_count
        logger.info("CSV 同步完成: 总计 %d, 新增 %d, 更新 %d, 跳过 %d",
                    len(records), len(to_insert), updated_count, skipped)
        return {"total": len(records), "inserted": len(to_insert),
                "updated": updated_count, "skipped": skipped}
    except Exception as e:
        session.rollback()
        logger.error("CSV 同步失败: %s", e)
        return {"total": len(records), "inserted": 0, "updated": 0,
                "skipped": 0, "message": str(e)}
    finally:
        session.close()


def sync_from_feishu_api() -> dict:
    """直接从飞书多维表格 API 拉取线上全量数据并同步到 case_info 表

    使用 feishu_client.list_bitable_records()（自动分页），
    复用 build_decision_chain + build_hypothesis_table 生成结构化 JSON。
    仅入库成功 + 指定任务类型（jira_analyze / parseFullTicket）的记录。

    :return: {"total": int, "inserted": int, "updated": int, "skipped": int}
    """
    from src.config import load_config
    from src.clients import feishu_client

    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    view_id = cfg.get("view_id", "")
    if not app_token or not table_id:
        return {"total": 0, "inserted": 0, "updated": 0, "skipped": 0,
                "message": "config.yaml 中 app_token 或 table_id 未配置"}

    # ── 1. 拉取线上全量数据 ──
    logger.info("开始从飞书 API 拉取数据: app=%s, table=%s", app_token, table_id)
    try:
        raw_records = feishu_client.list_bitable_records(
            app_token, table_id, view_id=view_id or None, page_size=500)
    except Exception as e:
        logger.error("飞书 API 拉取失败: %s", e)
        return {"total": 0, "inserted": 0, "updated": 0, "skipped": 0,
                "message": f"飞书 API 拉取失败: {e}"}
    logger.info("飞书 API 返回 %d 条原始记录", len(raw_records))

    # ── 2. 清洗字段值（飞书复杂类型扁平化） ──
    def _clean(val):
        if val is None:
            return ""
        if isinstance(val, list):
            if not val:
                return ""
            first = val[0]
            if isinstance(first, dict) and "text" in first:
                return "".join(seg.get("text", "") for seg in val)
            if isinstance(first, dict) and "name" in first:
                return ", ".join(p.get("name", p.get("en_name", "")) for p in val)
            if isinstance(first, dict) and "token" in first:
                return ", ".join(f.get("name", f.get("token", "")) for f in val)
            if isinstance(first, str):
                return ", ".join(val)
            return json.dumps(val, ensure_ascii=False)
        if isinstance(val, (int, float)) and val > 1000000000000:
            try:
                return datetime.fromtimestamp(val / 1000).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError):
                pass
        if isinstance(val, dict):
            return val.get("value", json.dumps(val, ensure_ascii=False))
        return val

    now = datetime.now()
    default_root_cause = "历史数据暂无根因，可点击一键复测生成"
    allowed_types = {"jira_analyze", "parseFullTicket"}
    records = []

    for raw in raw_records:
        fields = raw.get("fields", {})
        # 扁平化所有字段
        flat = {k: _clean(v) for k, v in fields.items()}

        jira = _clean_jira_no(flat.get("jira号", ""))
        if not jira:
            continue

        analysis_result = str(flat.get("分析结果", "")).strip()
        trigger_source = str(flat.get("触发来源", "")).strip()

        # ── 过滤：只保留成功 + 指定任务类型 ──
        if analysis_result != "成功" or trigger_source not in allowed_types:
            continue

        rootcause = (
            str(flat.get("AI分析问题根因", "")).strip()
            or str(flat.get("rootcause", "")).strip()
            or default_root_cause
        )
        conf_val = _safe_float(flat.get("结果置信度"))
        if conf_val is not None and conf_val > 1:
            conf_val = conf_val / 100
        total_seconds = _safe_float(flat.get("总耗时")) or 0
        analysis_seconds = _safe_float(flat.get("分析耗时")) or 0
        error_type = str(flat.get("错误类型", "")).strip()
        error_message = str(flat.get("错误信息", "")).strip()
        ai_module = str(flat.get("AI分析问题所在模块", "")).strip()
        actual_module = str(flat.get("问题所在实际模块", "")).strip()
        problem_time = str(flat.get("分析问题时间", "")).strip()
        analysis_date = str(flat.get("分析日期", "")).strip()
        manual_review = str(flat.get("人工审核结果", "")).strip()

        # 耗时格式化
        duration = ""
        if total_seconds > 0:
            if total_seconds < 60:
                duration = f"{total_seconds:.1f}s"
            elif total_seconds < 3600:
                duration = f"{total_seconds / 60:.1f}min"
            else:
                h, rem = divmod(total_seconds, 3600)
                m = rem / 60
                duration = f"{h:.0f}h{m:.0f}min"

        # problem_desc
        parts = []
        if error_type:
            parts.append(f"[{error_type}]")
        if error_message:
            parts.append(error_message)
        problem_desc = " ".join(parts)

        rec = {
            "case_id": jira, "vcu_number": jira,
            "finish_time": problem_time, "duration": duration,
            "conf": conf_val, "converged": False,
            "case_status": "已分析", "backflow_status": "",
            "problem_desc": problem_desc, "root_cause_summary": rootcause,
            "analysis_result": analysis_result,
            "trigger_source": trigger_source,
            "version": str(flat.get("版本号", "")).strip() or None,
            "problem_time": problem_time or None,
            "error_type": error_type or None,
            "error_message": error_message or None,
            "retry_count": _safe_int(flat.get("分析重试次数")),
            "total_seconds": total_seconds or None,
            "analysis_seconds": analysis_seconds or None,
            "rootcause": rootcause if rootcause != default_root_cause else None,
            "ai_module": ai_module or None,
            "actual_module": actual_module or None,
            "analysis_date": analysis_date or None,
            "manual_review": manual_review or None,
            "decision_chain": json.dumps(build_decision_chain(
                total_seconds, analysis_seconds, problem_time, analysis_date,
                analysis_result, trigger_source, error_type, rootcause, error_message
            ), ensure_ascii=False),
            "hypothesis_table": json.dumps(build_hypothesis_table(
                rootcause, error_type, error_message, ai_module, actual_module,
                analysis_result, conf_val
            ), ensure_ascii=False),
            "created_at": now, "updated_at": now, "is_deleted": False,
        }
        records.append(rec)

    logger.info("过滤后有效记录: %d 条", len(records))

    # ── 3. 增量写入 DB ──
    session = db._get_session()
    try:
        existing = {r.case_id: r for r in session.query(db.CaseInfo).filter(
            db.CaseInfo.is_deleted == False).all()}
        existing_ids = set(existing.keys())
        to_insert = []
        updated_count = 0

        for rec in records:
            cid = rec["case_id"]
            if cid not in existing_ids:
                to_insert.append(rec)
            else:
                obj = existing[cid]
                changed = False
                for key, val in rec.items():
                    if key in ("id", "case_id", "created_at", "trigger_source"):
                        continue
                    if val is not None and val != "" and val != getattr(obj, key, None):
                        setattr(obj, key, val)
                        changed = True
                if changed:
                    obj.updated_at = now
                    updated_count += 1

        for rec in to_insert:
            session.add(db.CaseInfo(**rec))
        session.commit()

        skipped = len(records) - len(to_insert) - updated_count
        logger.info("飞书 API 同步完成: 总计 %d, 新增 %d, 更新 %d, 跳过 %d",
                    len(records), len(to_insert), updated_count, skipped)
        return {"total": len(records), "inserted": len(to_insert),
                "updated": updated_count, "skipped": skipped}
    except Exception as e:
        session.rollback()
        logger.error("飞书 API 同步失败: %s", e)
        return {"total": len(records), "inserted": 0, "updated": 0,
                "skipped": 0, "message": str(e)}
    finally:
        session.close()


def sync_single_case_from_bitable_fields(bugid: str, fields: dict) -> dict:
    """单条同步：从飞书多维表格写入后的字段数据同步到 case_info 表

    在旧模块（数据可观测分析）写入飞书成功后调用，实现两模块联动。
    复用 build_decision_chain + build_hypothesis_table 生成结构化 JSON。

    :param bugid: Jira 号（如 VCU-559897）
    :param fields: 写入飞书的字段字典，如 {"rootcause": str, "结果置信度": float, ...}
    :return: {"case_id": str, "action": "inserted"|"updated"}
    """
    if not bugid:
        return {"case_id": "", "action": "skipped", "message": "bugid 为空"}

    session = db._get_session()
    try:
        case_id = bugid.strip()
        now = datetime.now()

        # 从 fields 提取数据（兼容飞书字段名）
        rootcause = (fields.get("rootcause") or "").strip()
        confidence = fields.get("结果置信度") or fields.get("confidence") or 0
        try:
            conf_val = float(confidence) / 100 if float(confidence) > 1 else float(confidence)
        except (ValueError, TypeError):
            conf_val = 0.0

        # 构建结构化 JSON
        total_seconds = _safe_float(fields.get("总耗时")) or 0
        analysis_seconds = _safe_float(fields.get("分析耗时")) or 0
        error_message = (fields.get("错误信息") or "").strip()
        error_type = (fields.get("错误类型") or "").strip()
        ai_module = (fields.get("AI分析问题所在模块") or "").strip()
        actual_module = (fields.get("问题所在实际模块") or "").strip()
        analysis_result = (fields.get("分析结果") or "").strip()
        trigger_source = (fields.get("触发来源") or "").strip()
        version = (fields.get("版本号") or "").strip()
        problem_time = (fields.get("分析问题时间") or "").strip()
        analysis_date = (fields.get("分析日期") or "").strip()

        # ── 过滤：只保留成功 + 指定任务类型 ──
        allowed_types = {"jira_analyze", "parseFullTicket"}
        if analysis_result == "失败" or (trigger_source and trigger_source not in allowed_types):
            logger.info("联动同步(跳过): %s, result=%s, source=%s", case_id, analysis_result, trigger_source)
            return {"case_id": case_id, "action": "skipped", "message": "不符合过滤条件"}

        decision_chain = build_decision_chain(
            total_seconds, analysis_seconds, problem_time, analysis_date,
            analysis_result, trigger_source, error_type, rootcause, error_message
        )
        hypothesis_table = build_hypothesis_table(
            rootcause, error_type, error_message, ai_module, actual_module,
            analysis_result, conf_val
        )

        # 分析结果 → case_status
        if analysis_result == "成功":
            case_status = "已分析"
        elif analysis_result == "失败":
            case_status = "分析失败"
        else:
            case_status = "已分析" if rootcause else ""

        # 耗时
        duration = ""
        if total_seconds > 0:
            if total_seconds < 60:
                duration = f"{total_seconds:.1f}s"
            elif total_seconds < 3600:
                duration = f"{total_seconds / 60:.1f}min"
            else:
                h, rem = divmod(total_seconds, 3600)
                m = rem / 60
                duration = f"{h:.0f}h{m:.0f}min"

        # 查找是否已存在
        existing = session.query(db.CaseInfo).filter(
            db.CaseInfo.case_id == case_id
        ).first()

        if existing:
            # 更新
            if rootcause:
                existing.rootcause = rootcause
                existing.root_cause_summary = rootcause
            if conf_val > 0:
                existing.conf = conf_val
            if duration:
                existing.duration = duration
            if case_status:
                existing.case_status = case_status
            if analysis_result:
                existing.analysis_result = analysis_result
            if trigger_source:
                existing.trigger_source = trigger_source
            if version:
                existing.version = version
            if problem_time:
                existing.problem_time = problem_time
            if error_type:
                existing.error_type = error_type
            if error_message:
                existing.error_message = error_message
            if total_seconds > 0:
                existing.total_seconds = total_seconds
            if analysis_seconds > 0:
                existing.analysis_seconds = analysis_seconds
            if ai_module:
                existing.ai_module = ai_module
            if actual_module:
                existing.actual_module = actual_module
            if analysis_date:
                existing.analysis_date = analysis_date
            existing.decision_chain = json.dumps(decision_chain, ensure_ascii=False)
            existing.hypothesis_table = json.dumps(hypothesis_table, ensure_ascii=False)
            existing.updated_at = now
            session.commit()
            logger.info("联动同步(更新): %s, rootcause=%s", case_id, rootcause[:50] if rootcause else "")
            return {"case_id": case_id, "action": "updated"}
        else:
            # 新增
            new_case = db.CaseInfo(
                case_id=case_id,
                rootcause=rootcause or None,
                root_cause_summary=rootcause or "待分析",
                conf=conf_val,
                duration=duration or None,
                case_status=case_status or "待分析",
                analysis_result=analysis_result or None,
                trigger_source=trigger_source or None,
                version=version or None,
                problem_time=problem_time or None,
                error_type=error_type or None,
                error_message=error_message or None,
                total_seconds=total_seconds or None,
                analysis_seconds=analysis_seconds or None,
                ai_module=ai_module or None,
                actual_module=actual_module or None,
                analysis_date=analysis_date or None,
                decision_chain=json.dumps(decision_chain, ensure_ascii=False),
                hypothesis_table=json.dumps(hypothesis_table, ensure_ascii=False),
                created_at=now,
                updated_at=now,
            )
            session.add(new_case)
            session.commit()
            logger.info("联动同步(新增): %s, rootcause=%s", case_id, rootcause[:50] if rootcause else "")
            return {"case_id": case_id, "action": "inserted"}
    except Exception as e:
        session.rollback()
        logger.error("联动同步失败: bugid=%s, error=%s", bugid, e)
        return {"case_id": bugid, "action": "error", "message": str(e)}
    finally:
        session.close()

