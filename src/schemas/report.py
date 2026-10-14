"""report 模块请求模型 — 11 端点（大部分 GET）"""
from typing import Optional

from pydantic import BaseModel, Field


class ClassifyDocsRequest(BaseModel):
    """评论分析文档分类"""
    date: Optional[str] = Field(default=None, description="日期 YYYY-MM-DD，默认今天")
