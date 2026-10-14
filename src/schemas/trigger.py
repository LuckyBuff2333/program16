"""trigger 模块请求模型 — 10 端点"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class BugidListRequest(BaseModel):
    """Jira 号列表请求"""
    bugids: List[str] = Field(default_factory=list, description="Jira 编号列表")


class UpdateTriggerTimeRequest(BaseModel):
    """修改单条触发时间"""
    bugid: str = Field(..., description="Jira 编号", min_length=1)
    new_time: str = Field(..., description="新触发时间", min_length=1)


class BatchUpdateItem(BaseModel):
    """批量更新项"""
    bugid: str
    new_time: str


class BatchUpdateRequest(BaseModel):
    """批量应用修正时间"""
    items: List[BatchUpdateItem] = Field(default_factory=list, description="修正项列表")


class ReExtractScanRequest(BaseModel):
    """重新提取扫描"""
    cache_only: bool = Field(default=False, description="仅扫描缓存（不查 Jira）")


class CacheBatchScanRequest(BaseModel):
    """云端缓存批量扫描"""
    exclude_bitable_success: bool = Field(default=False, description="排除多维表格已成功项")
    exclude_corrected: bool = Field(default=False, description="排除已修正项")


class CacheBatchExtractRequest(BaseModel):
    """云端缓存批量提取"""
    bugids: List[str] = Field(default_factory=list, description="待提取 Jira 列表")
    old_times: Dict[str, str] = Field(default_factory=dict, description="旧触发时间映射")
    video_first: bool = Field(default=True, description="视频优先策略")
