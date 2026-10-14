"""Pydantic 请求/响应模型：替代 request.json() 手动取字段

为每个路由模块定义 Request/Response model，实现：
1. 自动参数校验与类型转换
2. OpenAPI 文档自动生成
3. IDE 类型提示
"""
from src.schemas.common import ApiResponse

__all__ = ["ApiResponse"]
