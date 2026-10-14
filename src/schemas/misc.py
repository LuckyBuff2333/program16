"""杂项模块请求模型 — data/system/misc/feishu/tuning 等小模块"""
from typing import List, Optional

from pydantic import BaseModel, Field


# ── data.py ──
class SyncCloudBatchesRequest(BaseModel):
    """从云端同步批量执行记录"""
    dates: List[str] = Field(default_factory=list, description="要同步的日期列表 YYYY-MM-DD")


# ── system.py ──
class SaveConfigRequest(BaseModel):
    """保存配置"""
    config: dict = Field(default_factory=dict, description="配置字典")


class GitPullRequest(BaseModel):
    """Git 拉取并可选重启"""
    restart: bool = Field(default=True, description="是否重启服务")


# ── misc.py ──
class AiLogVisualRequest(BaseModel):
    """AI 日志可视化上传"""
    content: str = Field(default="", description="日志内容")


# ── feishu.py ──
class FeishuMsgRequest(BaseModel):
    """飞书消息调试"""
    chat_id: str = Field(default="", description="群聊 ID")
    message: str = Field(default="", description="消息内容")


# ── tuning.py ──
class SaveStylePreferenceRequest(BaseModel):
    """保存风格偏好"""
    preference: str = Field(default="", description="偏好文本")
