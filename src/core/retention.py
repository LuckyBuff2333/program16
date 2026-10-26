"""运行期数据保留策略：按天数清理生成物，避免 docs/reports/logs 无限增长

只清理「运行期生成」的目录（日期目录、报表、日志、ADP 结果、诊断缓存），
不碰源码、配置、设计文档（docs/plans）。

默认 180 天；支持 dry-run（默认）与 apply 两种模式。
"""
import os
import shutil
import time

from src.config import PROJECT_ROOT, get_path, setup_logger

logger = setup_logger("retention")

DEFAULT_RETENTION_DAYS = 180
# 永不清理的相对路径（源码/配置/设计文档）
_KEEP_PREFIXES = (
    os.path.join("docs", "plans"),
    os.path.join("config"),
    os.path.join("src"),
    os.path.join("frontend"),
    os.path.join("tests"),
    os.path.join("tools"),
    os.path.join(".git"),
)


def _target_roots() -> list:
    """需要参与保留期清理的目录（绝对路径）

    注意：docs/ 只清理「日期命名的子目录」（docs/YYYY-MM-DD），
    不碰 docs/plans、docs/study 以及放在 docs 根目录下的人工文档。
    """
    import re
    roots = []
    try:
        doc_dir = get_path("doc_dir")
        if os.path.isdir(doc_dir):
            for name in os.listdir(doc_dir):
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", name) and os.path.isdir(os.path.join(doc_dir, name)):
                    roots.append(os.path.join(doc_dir, name))
        roots.append(get_path("report_dir"))     # reports/（全部为运行期生成）
        roots.append(get_path("log_dir"))        # logs/
    except Exception as e:  # 配置异常时不阻断
        logger.warning("读取输出目录失败: %s", e)
    roots.append(os.path.join(PROJECT_ROOT, "data", "troubleshoot"))
    roots.append(os.path.join(PROJECT_ROOT, "data", "cache"))
    return [r for r in roots if os.path.isdir(r)]


def _is_kept(path: str) -> bool:
    rel = os.path.relpath(path, PROJECT_ROOT)
    return any(rel == p or rel.startswith(p + os.sep) for p in _KEEP_PREFIXES)


def plan_cleanup(days: int = DEFAULT_RETENTION_DAYS) -> dict:
    """只扫描不删除：返回 {files, dirs, bytes, newest, oldest} 统计"""
    cutoff = time.time() - days * 86400
    files, dirs, total = [], [], 0
    for root in _target_roots():
        for dirpath, dirnames, filenames in os.walk(root):
            if _is_kept(dirpath):
                dirnames[:] = []
                continue
            for name in filenames:
                p = os.path.join(dirpath, name)
                if name in (".gitkeep", ".gitignore"):
                    continue
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if st.st_mtime < cutoff:
                    files.append(p)
                    total += st.st_size
            # 整个日期目录都已过期时，删除后一并清掉空目录
            try:
                if dirpath != root and not os.listdir(dirpath):
                    dirs.append(dirpath)
            except OSError:
                pass
    return {"files": files, "empty_dirs": dirs, "bytes": total,
            "days": days, "roots": _target_roots()}


def apply_cleanup(plan: dict) -> dict:
    """执行清理：删文件 + 删空目录，返回 {removed, failed, freed_bytes}"""
    removed, failed, freed = 0, 0, 0
    for p in plan.get("files", []):
        try:
            size = os.path.getsize(p)
            os.remove(p)
            removed += 1
            freed += size
        except OSError as e:
            failed += 1
            logger.warning("清理文件失败 %s: %s", p, e)
    for p in plan.get("empty_dirs", []):
        try:
            shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass
    logger.info("保留期清理完成: 删除 %d 个文件, 失败 %d, 释放 %.1fMB（保留 %d 天）",
                removed, failed, freed / 1024 / 1024, plan.get("days", DEFAULT_RETENTION_DAYS))
    return {"removed": removed, "failed": failed, "freed_bytes": freed}


def prune_runtime_data(days: int = DEFAULT_RETENTION_DAYS, dry_run: bool = True) -> dict:
    """对外入口：按天数清理运行期数据（dry_run=True 只统计不删除）"""
    if days <= 0:
        raise ValueError("保留天数必须为正整数")
    plan = plan_cleanup(days)
    summary = {
        "mode": "dry-run" if dry_run else "apply",
        "days": days,
        "file_count": len(plan["files"]),
        "bytes": plan["bytes"],
        "roots": [os.path.relpath(r, PROJECT_ROOT) for r in plan["roots"]],
        "sample": [os.path.relpath(p, PROJECT_ROOT) for p in plan["files"][:10]],
    }
    if not dry_run:
        summary.update(apply_cleanup(plan))
    else:
        logger.info("保留期清理(dry-run): %d 个文件, %.1fMB, 超过 %d 天",
                    summary["file_count"], summary["bytes"] / 1024 / 1024, days)
    return summary
