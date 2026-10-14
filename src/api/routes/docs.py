"""文档管理路由：列出和预览 docs/ 目录下的 CSV 文件"""
import os

from fastapi import APIRouter, Query

from src.config import get_path, setup_logger
from src.schemas.common import ApiResponse

logger = setup_logger("web.docs")
router = APIRouter()


@router.get("/api/docs/files", response_model=ApiResponse)
async def list_docs_files():
    """列出 docs/ 目录下所有 CSV 文件，按日期分组倒序"""
    from src.api.routes.shared import ok as _ok
    doc_dir = get_path("doc_dir")
    files = []
    if not os.path.isdir(doc_dir):
        return _ok(files)
    for day in sorted(os.listdir(doc_dir), reverse=True):
        day_dir = os.path.join(doc_dir, day)
        if not os.path.isdir(day_dir):
            continue
        for fname in sorted(os.listdir(day_dir), reverse=True):
            if not fname.lower().endswith(".csv"):
                continue
            full_path = os.path.join(day_dir, fname)
            size_kb = round(os.path.getsize(full_path) / 1024, 1)
            files.append({"name": fname, "day": day, "path": full_path,
                          "size_kb": size_kb, "date": day})
    return _ok(files)


@router.get("/api/docs/preview", response_model=ApiResponse)
async def preview_docs_file(path: str = Query(default="", description="文件路径")):
    """预览指定 CSV 文件内容（前 50 行）"""
    from src.api.routes.shared import read_csv_rows as _read_csv_rows, ok as _ok, fail as _fail
    if not path or not os.path.isfile(path):
        return _fail(f"文件不存在: {path}")
    rows = _read_csv_rows(path)
    return _ok({"rows": rows[:50], "total": len(rows)})
