"""通用响应模型 — 所有 API 端点的统一契约

使用方式：
    from src.schemas.common import ApiResponse, success_response

    @router.post("/api/xxx", response_model=ApiResponse)
    async def handler(req: SomeRequest):
        return success_response(data={"key": "value"}, message="done")
"""
from typing import Any, Optional

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    """统一 API 响应结构 — 前后端唯一契约"""
    ok: bool = Field(..., description="请求是否成功")
    message: str = Field(default="", description="人可读的提示/错误信息")
    data: Optional[Any] = Field(default=None, description="业务数据")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"ok": True, "message": "success", "data": {"count": 42}},
                {"ok": False, "message": "参数错误: bugid 不能为空", "data": None},
            ]
        }
    }


def success_response(data: Any = None, message: str = "success") -> dict:
    """构造成功响应字典（配合 JSONResponse 使用）"""
    return {"ok": True, "message": message, "data": data}


def error_response(message: str, data: Any = None) -> dict:
    """构造失败响应字典（配合 JSONResponse 使用）"""
    return {"ok": False, "message": message, "data": data}
