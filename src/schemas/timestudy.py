"""timestudy 模块请求/响应模型

覆盖 4 个端点：
- POST /api/timestudy/analyze       → TimestudyAnalyzeRequest  → TimestudyAnalyzeData
- GET  /api/timestudy/summary       → (无入参)                → TimestudyAnalyzeData
- GET  /api/timestudy/records       → ?limit=50               → list[TimestudyRecord]
- POST /api/timestudy/root-causes   → RootCauseRequest        → dict[str, RootCauseItem]
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ── 请求模型 ──

class TimestudyAnalyzeRequest(BaseModel):
    """触发分析请求"""
    after_time: str = Field(default="", description="起始时间过滤，格式 YYYY-MM-DD 或空")


class RootCauseRequest(BaseModel):
    """批量根因查询请求"""
    bugids: List[str] = Field(default_factory=list, description="Jira 编号列表", min_length=0)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"bugids": ["VCU-123456", "VCU-789012"]},
            ]
        }
    }


# ── 响应数据模型 ──

class TimestudyAnalyzeData(BaseModel):
    """分析结果数据"""
    total_records: int = Field(default=0, description="总记录数")
    success_rate: float = Field(default=0, description="成功率(%)")
    error_distribution: Dict[str, int] = Field(
        default_factory=dict, description="错误类型分布 {类型: 次数}"
    )
    recent_trend: Optional[List[dict]] = Field(
        default=None, description="近期趋势数据"
    )


class TimestudyRecord(BaseModel):
    """单条自学习记录（对应 records.csv 一行）"""
    jira_id: str = Field(default="", alias="jira号", description="Jira 编号")
    record_time: str = Field(default="", alias="记录时间", description="记录时间")
    source: str = Field(default="", alias="提取来源", description="提取来源")
    result: str = Field(default="", alias="提取结果", description="提取结果")
    is_correct: str = Field(default="", alias="是否正确", description="是否正确")
    error_type: str = Field(default="", alias="错误类型", description="错误类型")
    error_detail: str = Field(default="", alias="错误详情", description="错误详情")
    corrected_time: str = Field(default="", alias="修正后时间", description="修正后时间")
    video_count: str = Field(default="", alias="视频数量", description="视频数量")
    gmlogger_count: str = Field(default="", alias="gmlogger数量", description="gmlogger 数量")
    reference_time: str = Field(default="", alias="参考时间", description="参考时间")
    ocr_text: str = Field(default="", alias="OCR原文", description="OCR 原文")
    match_diff_sec: str = Field(default="", alias="匹配差秒", description="匹配差秒")
    hour12_conversion: str = Field(default="", alias="12h转换", description="12h 转换")
    jira_created_time: str = Field(default="", alias="jira创建时间", description="Jira 创建时间")
    trace_steps: str = Field(default="", alias="trace_steps", description="trace 步骤链")

    model_config = {"populate_by_name": True}


class RootCauseItem(BaseModel):
    """单个 Jira 的根因分析结果"""
    root_cause: str = Field(default="", description="根因描述")
    trace: str = Field(default="", description="trace 步骤链原始字符串")
    error_type: str = Field(default="", description="错误类型")
    source: str = Field(default="", description="提取来源")
    result: str = Field(default="", description="提取结果")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "root_cause": "OCR未识别到文字",
                    "trace": "fetch:ok→video:3→gm:2→ocr:empty",
                    "error_type": "ocr:empty",
                    "source": "视频OCR",
                    "result": "",
                }
            ]
        }
    }
