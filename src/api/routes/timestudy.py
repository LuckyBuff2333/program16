"""时间研究路由：触发时间提取的自学习与根因分析"""
import os

from fastapi import APIRouter, Query

from src.config import PROJECT_ROOT, setup_logger
from src.api.routes.shared import ok, fail
from src.schemas.common import ApiResponse
from src.schemas.timestudy import (
    TimestudyAnalyzeRequest,
    RootCauseRequest,
)

logger = setup_logger("web.timestudy")
router = APIRouter()

# 时间研究数据目录
_TIMESTUDY_DIR = os.path.join(PROJECT_ROOT, "data", "timestudy")
_TIMESTUDY_RECORDS = os.path.join(_TIMESTUDY_DIR, "records.csv")
_TIMESTUDY_REPORT_DIR = os.path.join(PROJECT_ROOT, "reports", "timestudy")

# trace 步骤中文描述
_TRACE_STAGE_DESC = {
    "cloud": "云端缓存", "diag": "诊断缓存", "video": "视频附件检查",
    "gm": "gmlogger解析", "dl": "视频下载", "frame": "帧提取",
    "ocr": "OCR识别", "full": "完整时间匹配", "12h": "12h转换",
    "cache": "缓存命中", "fn": "文件名回退", "partial": "部分结果兜底",
    "text": "文本提取回退", "result": "最终结果", "fetch": "Jira获取",
    "skip": "前置跳过"
}


@router.post("/api/timestudy/analyze", response_model=ApiResponse)
def timestudy_analyze(req: TimestudyAnalyzeRequest):
    """触发分析：统计错误模式，支持按时间范围过滤"""
    from src.services.server_legacy import _timestudy_analyze
    try:
        patterns = _timestudy_analyze(after_time=req.after_time)
        total = patterns.get("total_records", 0)
        rate = patterns.get("success_rate", 0)
        err_dist = patterns.get("error_distribution", {})
        top3 = list(err_dist.items())[:3]
        top3_str = ", ".join(f"{k}({v})" for k, v in top3) if top3 else "无"
        summary = (f"自学习分析完成: {total}条记录, 成功率{rate}%, "
                   f"Top3错误: {top3_str}")
        return ok(patterns, summary)
    except Exception as e:
        logger.error("自学习分析失败: %s", e)
        return fail(str(e))


@router.get("/api/timestudy/summary", response_model=ApiResponse)
def timestudy_summary():
    """获取自学习摘要（轻量级，不重新分析）"""
    import json as _json2
    patterns_path = os.path.join(_TIMESTUDY_DIR, "error_patterns.json")
    if not os.path.exists(patterns_path):
        return ok({"total_records": 0}, "尚无自学习数据")
    try:
        with open(patterns_path, "r", encoding="utf-8") as f:
            patterns = _json2.load(f)
        return ok(patterns)
    except Exception as e:
        return fail(str(e))


@router.get("/api/timestudy/records", response_model=ApiResponse)
def timestudy_records(limit: int = Query(default=50, ge=1, le=500, description="返回条数上限")):
    """获取最近的自学习记录"""
    import csv as _csv
    if not os.path.exists(_TIMESTUDY_RECORDS):
        return ok([], "尚无记录")
    try:
        rows = []
        with open(_TIMESTUDY_RECORDS, "r", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                rows.append(row)
        rows = rows[-limit:][::-1]
        return ok(rows, f"最近 {len(rows)} 条记录")
    except Exception as e:
        return fail(str(e))


@router.post("/api/timestudy/root-causes", response_model=ApiResponse)
def timestudy_root_causes(req: RootCauseRequest):
    """批量查询 Jira 的上次提取根因（从 records.csv 读取最新一条记录）"""
    import csv as _csv
    bugids = req.bugids
    if not bugids:
        return ok({}, "无查询目标")
    if not os.path.exists(_TIMESTUDY_RECORDS):
        return ok({}, "尚无自学习记录")
    try:
        last_record = {}
        with open(_TIMESTUDY_RECORDS, "r", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                bid = (row.get("jira号", "") or "").strip()
                if bid:
                    last_record[bid] = row
        _RESULT_MAP = {
            "video:0": "无视频附件", "dl:fail": "视频下载失败",
            "frame:fail": "帧提取失败", "ocr:empty": "OCR未识别到文字",
            "ocr:no_pattern": "OCR识别了文字但无时间模式",
            "full:hit": "完整时间匹配成功", "12h:hit": "12h转换命中",
            "12h:fallback": "12h兜底", "cache:hit": "缓存命中",
            "fn:try": "文件名回退",
            "partial:single": "单视频兜底(未匹配gmlogger)",
            "partial:multi": "多视频兜底(未匹配gmlogger)",
            "text:hit": "文本回退成功", "text:empty": "文本回退也失败",
            "result:video_hit": "视频提取成功", "cloud:hit": "云端缓存命中",
            "diag:correction": "诊断缓存修正值", "diag:suggested": "诊断缓存建议值",
            "skip:no_gmlogger": "无gmlogger前置跳过", "fetch:fail": "Jira获取失败",
        }
        results = {}
        for bid in bugids:
            rec = last_record.get(bid)
            if not rec:
                results[bid] = {"root_cause": "无历史提取记录", "trace": "", "error_type": ""}
                continue
            trace_str = (rec.get("trace_steps", "") or "").strip()
            error_type = (rec.get("错误类型", "") or "").strip()
            source = (rec.get("提取来源", "") or "").strip()
            result = (rec.get("提取结果", "") or "").strip()
            if trace_str:
                steps = [s.strip() for s in trace_str.split("→") if s.strip()]
                root_step = ""
                for s in reversed(steps):
                    code = s.split(":")[0] if ":" in s else s
                    if code not in ("result", "cloud", "diag"):
                        root_step = s
                        break
                root_desc = _RESULT_MAP.get(root_step, "")
                if not root_desc and root_step:
                    code = root_step.split(":")[0] if ":" in root_step else root_step
                    root_desc = _TRACE_STAGE_DESC.get(code, root_step)
                results[bid] = {
                    "root_cause": root_desc or root_step,
                    "trace": trace_str, "error_type": error_type,
                    "source": source, "result": result,
                }
            else:
                results[bid] = {
                    "root_cause": error_type or source or "无trace数据",
                    "trace": "", "error_type": error_type,
                    "source": source, "result": result,
                }
        return ok(results, f"查询 {len(bugids)} 个Jira根因")
    except Exception as e:
        logger.error("根因查询失败: %s", e)
        return fail(str(e))
