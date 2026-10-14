"""verify 模块请求模型 — 6 端点"""
from typing import List, Optional

from pydantic import BaseModel, Field


class VerifyWriteItem(BaseModel):
    """单条验证写入项"""
    bugid: str
    rootcause: str = ""
    comment_summary: str = ""
    confidence: str = ""


class VerifyWriteRequest(BaseModel):
    """写入验证结果到 CSV"""
    csv_path: str = Field(..., description="CSV 文件路径", min_length=1)
    items: List[VerifyWriteItem] = Field(default_factory=list, description="待写入项")
