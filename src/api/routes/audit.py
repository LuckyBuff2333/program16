"""抽查复核路由：清空已抽查记录"""
from fastapi import APIRouter

from src.api.routes.shared import ok, fail
from src.schemas.common import ApiResponse

router = APIRouter()


@router.post("/api/audit/clear", response_model=ApiResponse)
def clear_audited():
    """清空已抽查记录，允许重新抽查"""
    from src.services.server_legacy import _clear_audited_impl
    return _clear_audited_impl()
