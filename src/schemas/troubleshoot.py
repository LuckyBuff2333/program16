"""troubleshoot 模块请求模型 — 8 端点"""
from typing import List, Optional

from pydantic import BaseModel, Field


class RecordsQueryRequest(BaseModel):
    """查询排查记录"""
    after_time: str = Field(default="", description="起始时间过滤")
    result_filter: str = Field(default="", description="结果过滤(成功/失败)")
    source_filter: str = Field(default="", description="来源过滤")
    dedup: bool = Field(default=True, description="是否去重")
    no_manual_review: bool = Field(default=False, description="排除已人工审核")


class DirectQueryRequest(BaseModel):
    """按 Jira 号直接查询"""
    bugids: List[str] = Field(default_factory=list, description="Jira 号列表")


class SearchJiraRequest(BaseModel):
    """关键词搜索 Jira"""
    keyword: str = Field(default="", description="搜索关键词（Jira 号或描述）")


class CancelDiagRequest(BaseModel):
    """取消诊断请求"""
    bugids: List[str] = Field(default_factory=list, description="Jira 号列表")


class DiagnoseRequest(BaseModel):
    """单 Jira 诊断"""
    bugid: str = Field(..., description="Jira 编号", min_length=1)
    err_msg: str = Field(default="", description="错误信息")
    problem_time: str = Field(default="", description="问题发生时间")
    done_time: str = Field(default="", description="完成时间")
    force: bool = Field(default=False, description="强制重新诊断")
    skip_video_cache: bool = Field(default=False, description="跳过视频缓存")


class UpdateCacheRequest(BaseModel):
    """更新诊断缓存"""
    bugid: str = Field(..., description="Jira 编号", min_length=1)
    correction_time: Optional[str] = Field(default=None, description="修正后时间")
    correction_note: Optional[str] = Field(default=None, description="修正备注")
    human_reason: Optional[str] = Field(default=None, description="人工原因")
    category: Optional[str] = Field(default=None, description="分类")


class ReviewItem(BaseModel):
    """单条审核写入项"""
    bugid: str
    review: str = ""


class BatchWriteReviewRequest(BaseModel):
    """批量写入审核结论"""
    items: List[ReviewItem] = Field(default_factory=list, description="审核项列表")
    only_empty_review: bool = Field(default=False, description="仅写入空审核")


class ExportIssuesRequest(BaseModel):
    """导出触发时间问题"""
    items: List[dict] = Field(default_factory=list, description="问题记录列表")


class BatchPreClassifyRequest(BaseModel):
    """批量预归类"""
    records: List[dict] = Field(default_factory=list, description="待归类记录列表")


class SendToDeveloperRequest(BaseModel):
    """发送给开发者"""
    records: List[dict] = Field(default_factory=list, description="待发送记录列表")
