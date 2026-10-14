"""flow 模块请求模型 — 8 端点"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """执行内容补充流程"""
    rows: List[dict] = Field(default_factory=list, description="表格行数据")
    bugids: Optional[str] = Field(default=None, description="Jira 号（逗号分隔，rows 为空时使用）")
    trigger_times: Dict[str, str] = Field(default_factory=dict, description="触发时间映射")


class ExtractTimeRequest(BaseModel):
    """提取单 Jira 触发时间"""
    bugid: str = Field(..., description="Jira 编号", min_length=1)


class FlowSingleRequest(BaseModel):
    """单 bugid 流程执行（SSE）"""
    bugid: str = Field(..., description="Jira 编号", min_length=1)
    trigger_time: str = Field(default="", description="触发时间")


class BugidRequest(BaseModel):
    """通用 bugid 请求"""
    bugid: str = Field(..., description="Jira 编号", min_length=1)


class AuditRequest(BaseModel):
    """随机抽查"""
    count: Optional[int] = Field(default=None, description="抽查数量", ge=1)
