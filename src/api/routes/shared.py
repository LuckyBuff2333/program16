"""路由共享模块：全局状态、响应工具函数、通用数据读取

所有 Router 文件从此模块导入公共依赖，避免 server.py 的循环引用。
"""
import concurrent.futures as _futures
import json
import os
import re
import signal
import sys
import threading
from datetime import datetime

import pandas as pd
from fastapi import Request
from fastapi.responses import JSONResponse

from src import config as cfg_module
from src import pipeline
from src.config import get_path, load_config, setup_logger, PROJECT_ROOT

logger = setup_logger("web")

# ── 全局状态 ──
# 流程取消标志：bugid -> bool，用于跨线程通知后端任务停止
flow_cancel: dict = {}

# 诊断取消标志：bugid -> bool，前端停止按钮或 Ctrl+C 时设置
diag_cancel: dict = {}

# 全局中断标志：Ctrl+C 时设为 True
interrupted = False
prev_sigint = None  # 保存 uvicorn/asyncio 的原始 SIGINT 处理器


def handle_sigint(signum, frame):
    """SIGINT 处理：设置中断标志 + 取消诊断任务，然后让 uvicorn 正常关闭"""
    global interrupted, prev_sigint
    if interrupted:
        ppid = os.getppid()
        if ppid > 1 and ppid != os.getpid():
            try:
                if sys.platform == 'win32':
                    os.system(f'taskkill /F /T /PID {ppid} >nul 2>&1')
                else:
                    os.kill(ppid, signal.SIGTERM)
            except Exception:
                pass
        os._exit(1)
    interrupted = True
    for bugid in list(diag_cancel):
        diag_cancel[bugid] = True
    logger.warning("收到 Ctrl+C，正在停止当前操作（再次按 Ctrl+C 强制退出）")
    if prev_sigint and callable(prev_sigint) and prev_sigint not in (signal.SIG_IGN, signal.SIG_DFL):
        prev_sigint(signum, frame)

# 批量提取触发时间停止标志
batch_extract_stop_event = threading.Event()
cache_batch_stop_event = threading.Event()

# 全局线程池（限制诊断等同步操作的最大并发数）
_DIAG_EXECUTOR = None
_DIAG_EXECUTOR_MAX_WORKERS = 1
_DIAG_TIMEOUT_SECONDS = 300

# 内存缓存：上传文件解析后的行数据
uploaded_files: dict = {}

# OAuth2 回调缓存
oauth_cache = {"code": None, "token": None}

# 飞书机器人取消事件：{chat_id: threading.Event}
bot_cancel_events: dict = {}
# 当前正在执行的任务描述：{chat_id: 任务名称}
bot_running_tasks: dict = {}

# ── 多维表格批量缓存（全局共享，trigger_ops / report_ops 共用） ──
_bitable_bulk_cache = {}  # key -> (timestamp, data)
_BITABLE_CACHE_TTL = 300  # 5分钟

# 自动检测停止标志
auto_detect_stop = False


# ── 状态检查函数 ──

def check_interrupt():
    """检查是否已中断，已中断则抛出异常"""
    if interrupted:
        raise InterruptedError("用户已按 Ctrl+C 中断操作")


def check_diag_cancel(bugid: str):
    """检查诊断是否被取消，已取消则抛出异常"""
    if diag_cancel.get(bugid):
        raise InterruptedError(f"诊断已取消: {bugid}")
    if interrupted:
        raise InterruptedError("用户已按 Ctrl+C 中断操作")


def get_diag_executor():
    """获取诊断专用线程池（懒加载）"""
    global _DIAG_EXECUTOR
    if _DIAG_EXECUTOR is None:
        _DIAG_EXECUTOR = _futures.ThreadPoolExecutor(
            max_workers=_DIAG_EXECUTOR_MAX_WORKERS,
            thread_name_prefix="diag_"
        )
        logger.info("诊断线程池已初始化: max_workers=%d", _DIAG_EXECUTOR_MAX_WORKERS)
    return _DIAG_EXECUTOR


def shutdown_diag_executor():
    """关闭诊断线程池"""
    global _DIAG_EXECUTOR
    if _DIAG_EXECUTOR is not None:
        _DIAG_EXECUTOR.shutdown(wait=False)
        _DIAG_EXECUTOR = None
        logger.info("诊断线程池已关闭")


# ── 飞书机器人任务状态 ──


def get_cancel_event(chat_id: str):
    """获取或创建该 chat_id 的取消事件"""
    if chat_id not in bot_cancel_events:
        bot_cancel_events[chat_id] = threading.Event()
    return bot_cancel_events[chat_id]


def reset_cancel_event(chat_id: str):
    """重置取消标记（新任务开始时调用）"""
    evt = bot_cancel_events.get(chat_id)
    if evt:
        evt.clear()


def set_running_task(chat_id: str, task_desc: str):
    """标记当前 chat_id 正在执行的任务名称"""
    bot_running_tasks[chat_id] = task_desc
    reset_cancel_event(chat_id)


def clear_running_task(chat_id: str):
    """清除当前 chat_id 的任务标记"""
    bot_running_tasks.pop(chat_id, None)


def is_cancelled(chat_id: str) -> bool:
    """检查当前任务是否被用户取消"""
    evt = bot_cancel_events.get(chat_id)
    return evt.is_set() if evt else False


# ── 响应工具函数 ──

def ok(data=None, message: str = "success"):
    """统一成功响应格式"""
    return JSONResponse(content={"ok": True, "message": message, "data": data})


def fail(message: str, extra: dict = None):
    """统一失败响应格式"""
    data = {"ok": False, "message": message}
    if extra:
        data.update(extra)
    return JSONResponse(content=data, status_code=200)


def parse_conf(val) -> float:
    """安全解析置信度值，返回 float，解析失败返回 0"""
    try:
        v = float(str(val).strip() or "0")
        return v if not (v != v) else 0  # NaN 检查
    except (ValueError, TypeError):
        return 0.0


# ── 通用数据读取 ──

def read_csv_rows(path: str) -> list:
    """读取 CSV 报表为字典行列表，文件不存在返回空列表，自动过滤批次分隔空行"""
    if not os.path.exists(path):
        return []
    df = pd.read_csv(path, encoding="utf-8-sig")
    first_col = df.columns[0] if len(df.columns) else "jira号"
    df = df[df[first_col].notna() & (df[first_col].astype(str).str.strip() != "")]
    return df.fillna("").astype(str).to_dict(orient="records")


def daily_csv_path(date_str: str = None) -> str:
    """每日分析结论报表路径：docs/日期/YYYY-MM-DD_daily.csv"""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    return os.path.join(get_path("doc_dir"), date_str, f"{date_str}_daily.csv")


def spotcheck_csv_path(filename: str, date_str: str = None) -> str:
    """抽查报表路径：spotcheck/日期/filename"""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    return os.path.join(get_path("report_dir"), "spotcheck", date_str, filename)


# ── 共享常量 ──

_UNANALYZED_DIR = os.path.join(PROJECT_ROOT, "data", "unanalyzed")
_AI_INIT_FIELD_ID = "customfield_13714"
_STUDY_DIR = os.path.join(get_path("doc_dir"), "study")
_PROD_AI_URL_DEFAULT = "https://dpportal.apps.saic-gm.com/api/logAnalysis/parseFullTicket"

_EXCLUDE_REASONS = {
    "无gmlogger", "无gmlogger文件", "无gmlogger日志文件", "日志文件已损坏",
    "问题重复", "问题重复，无需排查", "问题未复现", "触发时间无日志", "无日志附件",
    "该jira无日志附件，属于正常处理机制", "该Jira无日志附件，属于正常处理机制",
    "该jira无日志附件", "该Jira无日志附件",
    "日志里无对应触发时间相关文件，但是标题里明确说了触发时间",
    "解压问题，待排查", "解压问题",
}

_GMLOGGER_REVIEW_KEYWORDS = {
    "无gmlogger", "无gmlogger文件", "无gmlogger日志文件", "无日志附件",
    "该jira无日志附件", "该Jira无日志附件",
    "该jira无日志附件，属于正常处理机制", "该Jira无日志附件，属于正常处理机制",
}


# ── 共享工具函数 ──


def bitable_text(val) -> str:
    """多维表格字段值归一化为纯文本（兼容 list/dict/url/普通类型）"""
    if val is None:
        return ""
    if isinstance(val, list):
        return "".join(bitable_text(item) for item in val)
    if isinstance(val, dict):
        return str(val.get("text", "") or val.get("name", "") or "").strip()
    return str(val).strip()


# 兼容旧引用：server.py 中仍定义 _bitable_text，但内部调用此函数
_bitable_text = bitable_text


def is_bitable_excluded(fields: dict, bugid_field: str = "jira号") -> bool:
    """多维表格记录是否应被去重排除"""
    result_status = bitable_text(fields.get("分析结果", ""))
    trigger_source = bitable_text(fields.get("触发来源", ""))
    if trigger_source == "parseFullTicket" and result_status == "成功":
        return True
    if result_status == "成功":
        return True
    human_review = bitable_text(fields.get("人工审核结果", ""))
    if human_review:
        if human_review in _EXCLUDE_REASONS:
            return True
        human_lower = human_review.lower()
        if any(human_lower == r.lower() for r in _EXCLUDE_REASONS):
            return True
    return False


_is_bitable_excluded = is_bitable_excluded


def flatten_bitable_record(fields: dict, report_field: str) -> dict:
    """提取多维表格单条记录的关键展示字段"""
    def pick(*names):
        for n in names:
            if n in fields:
                return fields[n]
        return ""
    report_val = fields.get(report_field, "")
    report_link = ""
    if isinstance(report_val, dict):
        report_link = str(report_val.get("link", "") or "").strip()
    elif isinstance(report_val, str):
        report_link = report_val.strip()
    return {
        "分析结果": bitable_text(pick("分析结果")),
        "错误信息": bitable_text(pick("错误信息")),
        "分析问题时间": bitable_text(pick("分析问题时间")),
        "分析完成时间": bitable_text(pick("分析完成时间")),
        "分析耗时": bitable_text(pick("分析耗时")),
        "总耗时": bitable_text(pick("总耗时")),
        "飞书报告链接": report_link,
        "人工审核结果": bitable_text(pick("人工审核结果")),
        "触发来源": bitable_text(pick("触发来源")),
        "rootcause": bitable_text(pick("rootcause")),
        "AI评论总结": bitable_text(pick("AI评论总结")),
        "结果置信度": bitable_text(pick("结果置信度")),
    }


_flatten_bitable_record = flatten_bitable_record


def get_prod_ai_url() -> str:
    """从配置读取线上AI分析接口地址"""
    cfg = load_config()
    return (cfg.get("prod_ai") or {}).get("url", _PROD_AI_URL_DEFAULT)


def get_prod_ai_cfg() -> dict:
    """读取线上AI分析接口完整配置，提供默认值"""
    cfg = load_config()
    pai = cfg.get("prod_ai") or {}
    return {
        "url": pai.get("url", _PROD_AI_URL_DEFAULT),
        "bugid_field": pai.get("bugid_field", "jiraNumber"),
        "trigger_time_field": pai.get("trigger_time_field", "questionTimes"),
        "timeout": int(pai.get("timeout", 30)),
        "mock": pai.get("mock", False),
    }


def build_prod_ai_payload(bugid: str, exec_time: str = None) -> dict:
    """构建线上AI分析接口请求体，字段名从配置读取"""
    pai = get_prod_ai_cfg()
    payload = {pai["bugid_field"]: bugid}
    if exec_time and pai["trigger_time_field"]:
        # questionTimes 类型字段需要数组包装
        if pai["trigger_time_field"] == "questionTimes":
            payload[pai["trigger_time_field"]] = [exec_time]
        else:
            payload[pai["trigger_time_field"]] = exec_time
    return payload


_get_prod_ai_url = get_prod_ai_url
_get_prod_ai_cfg = get_prod_ai_cfg
_build_prod_ai_payload = build_prod_ai_payload


def parse_bugids(raw: str) -> list:
    """解析 bugid 输入：支持分号、逗号、中英文逗号分隔，最多 30 个"""
    raw = raw.replace("，", ",").replace(";", ",")
    return [b.strip() for b in raw.split(",") if b.strip()][:30]


_parse_bugids = parse_bugids


def ts_parse_datetime(val):
    """多维表格/Jira时间字段归一化为 datetime"""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val / 1000)
        except Exception:
            return None
    if isinstance(val, str):
        val = val.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f%z",
                     "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
        try:
            ts = float(val)
            return datetime.fromtimestamp(ts / 1000)
        except (ValueError, OSError):
            pass
    return None


_ts_parse_datetime = ts_parse_datetime


def calc_smoke_duration(start: str, end: str) -> str:
    """计算冒烟测试耗时"""
    if not start or not end:
        return "-"
    try:
        s = datetime.strptime(start.strip()[:19], "%Y-%m-%d %H:%M:%S")
        e = datetime.strptime(end.strip()[:19], "%Y-%m-%d %H:%M:%S")
        sec = max(0, int((e - s).total_seconds()))
        if sec < 60:
            return f"{sec}秒"
        return f"{sec // 60}分{sec % 60}秒"
    except Exception:
        return "-"


_calc_smoke_duration = calc_smoke_duration


def compare_single_bug(bugid: str, trigger_time: str = None, uploaded_rows: list = None) -> dict:
    """对单个 bug 执行完整对比"""
    result = pipeline.compare_bug_analysis(bugid, trigger_time, uploaded_rows)
    if result.get("skipped"):
        conclusion = f"已跳过：{result.get('skip_reason', '未知原因')}"
    elif result["all_ok"]:
        conclusion = "分析正确：根因与评论对比均通过"
    elif result["root_cause_ok"]:
        conclusion = "需人工复核：根因匹配但评论对比不通过"
    elif result["comment_compare_ok"]:
        conclusion = "需人工复核：评论对比通过但根因不匹配"
    else:
        conclusion = "分析不一致：根因与评论对比均不通过，需人工复核"
    return {
        **result, "conclusion": conclusion, "error": None,
        "comments_total": len(result["comments"]),
        "comments_used": len(result["valid_comments"]),
        "truncated": len(result["valid_comments"]) < len(result["comments"]),
        "error_cause": result["bug_root_cause"],
    }


_compare_single_bug = compare_single_bug


def scan_study_folders(jira_id: str = "") -> list:
    """扫描 study 目录，找到包含推理轮次文件的文件夹"""
    results = []
    if not os.path.isdir(_STUDY_DIR):
        return results
    for entry in os.listdir(_STUDY_DIR):
        if jira_id and not entry.upper().startswith(jira_id.upper()):
            continue
        top_dir = os.path.join(_STUDY_DIR, entry)
        if not os.path.isdir(top_dir):
            continue
        for root, dirs, files in os.walk(top_dir):
            if "02_reasoning_rounds.md" in files:
                results.append({
                    "name": os.path.relpath(root, _STUDY_DIR),
                    "path": root,
                })
    return results


_scan_study_folders = scan_study_folders


def parse_reasoning_content(content: str, elapsed: float = 0, conclusions: list = None) -> dict:
    """解析 02_reasoning_rounds.md 内容字符串，提取每轮的推理、工具结果、知识库、本轮结论"""
    if not content or not content.strip():
        return {"rounds": [], "total_rounds": 0, "elapsed_seconds": 0, "conclusions": conclusions or []}
    sections = re.split(r'^## ', content, flags=re.MULTILINE)
    rounds_map = {}
    for sec in sections:
        m = re.match(r'第\s*(\d+)\s*轮\s*[—-]\s*(.*)', sec)
        if not m:
            continue
        rn = int(m.group(1))
        sec_type = m.group(2).strip()
        sec_body = sec[m.end():].strip()
        if rn not in rounds_map:
            rounds_map[rn] = {"llm": "", "tools": [], "knowledge": [], "conclusion": ""}
        if "LLM" in sec_type or "响应" in sec_type:
            raw = sec_body[:500]
            while re.search(r'\n\s*[-–—]{2,}\s*$', raw):
                raw = re.sub(r'\n\s*[-–—]{2,}\s*$', '', raw)
            raw = raw.rstrip()
            rounds_map[rn]["llm"] = raw
            # 提取本轮结论：最后一段有意义的文本（排除空行和分隔符）
            paragraphs = [p.strip() for p in sec_body.split('\n\n') if p.strip() and not re.match(r'^[-–—]{2,}$', p.strip())]
            if paragraphs:
                last = paragraphs[-1][:200]
                # 优先提取含关键词的段落
                for p in reversed(paragraphs):
                    if re.search(r'因此|结论|总结|所以|最终|根因|原因|问题在于|确认|判断|导致', p):
                        last = p[:200]
                        break
                rounds_map[rn]["conclusion"] = last
        elif "工具" in sec_type or "Tool" in sec_type:
            rounds_map[rn]["tools"].append(sec_body[:300])
            # 从工具结果中提取知识库文档（WIKI 文档）
            wiki_matches = re.findall(r'WIKI\s*文档\s*\[([^\]]+)\]', sec_body, re.I)
            for wiki in wiki_matches:
                # 展开多文档条目（如 "车控娱乐/Seat.md"）
                for line in wiki.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('[') and '/' in line:
                        # 提取文档名（去除路径前缀）
                        doc_name = line.split(':')[0].strip().rstrip(',')
                        if doc_name and doc_name not in rounds_map[rn]["knowledge"]:
                            rounds_map[rn]["knowledge"].append(doc_name)
            # 匹配 knowledge_list 格式：“- 分类/文档.md: 描述”
            if 'knowledge_list' in sec_body.lower():
                for km in re.finditer(r'^- ([\w\u4e00-\u9fff]+/[\w\u4e00-\u9fff.-]+\.md)', sec_body, re.MULTILINE):
                    doc = km.group(1)
                    if doc not in rounds_map[rn]["knowledge"]:
                        rounds_map[rn]["knowledge"].append(doc)
            # 也匹配单个文档引用如 "WIKI 文档 [车控娱乐/Seat.md]:"
            single_wiki = re.findall(r'WIKI\s*文档\s*\[([^\]]+/[^\]]+\.md)\]', sec_body, re.I)
            for w in single_wiki:
                if w not in rounds_map[rn]["knowledge"]:
                    rounds_map[rn]["knowledge"].append(w)
        elif "知识" in sec_type:
            rounds_map[rn]["knowledge"].append(sec_body[:300])
    total_rounds = len(rounds_map)
    avg_time = round(elapsed / total_rounds, 1) if total_rounds else 0
    rounds_list = []
    for rn in sorted(rounds_map.keys()):
        r = rounds_map[rn]
        rounds_list.append({
            "round": rn,
            "llm_summary": r["llm"],
            "tool_count": len(r["tools"]),
            "tools": r["tools"],
            "knowledge": r["knowledge"],
            "knowledge_count": len(r["knowledge"]),
            "avg_time": avg_time,
            "conclusion": r["conclusion"],
        })
    return {
        "rounds": rounds_list,
        "total_rounds": total_rounds,
        "elapsed_seconds": round(elapsed, 1),
        "conclusions": conclusions or [],
    }


def parse_reasoning_rounds(folder_path: str) -> dict:
    """解析 02_reasoning_rounds.md，提取每轮的推理、工具结果、知识库、耗时"""
    rounds_path = os.path.join(folder_path, "02_reasoning_rounds.md")
    if not os.path.isfile(rounds_path):
        return {"rounds": [], "total_rounds": 0, "elapsed_seconds": 0, "conclusions": []}
    with open(rounds_path, "r", encoding="utf-8") as f:
        content = f.read()
    elapsed = 0
    budget_path = os.path.join(folder_path, "05_budget_observation.json")
    if os.path.isfile(budget_path):
        try:
            with open(budget_path, "r", encoding="utf-8") as f:
                budget = json.loads(f.read())
            elapsed = budget.get("elapsed_seconds", 0)
        except Exception:
            pass
    conclusions = []
    adj_path = os.path.join(folder_path, "03_adjudication_result.json")
    if os.path.isfile(adj_path):
        try:
            with open(adj_path, "r", encoding="utf-8") as f:
                adj = json.loads(f.read())
            for c in adj.get("conclusions", []):
                conclusions.append({
                    "statement": c.get("statement", ""),
                    "confidence": c.get("confidence", ""),
                    "severity": c.get("severity", ""),
                    "category": c.get("category", ""),
                })
        except Exception:
            pass
    return parse_reasoning_content(content, elapsed=elapsed, conclusions=conclusions)


_parse_reasoning_rounds = parse_reasoning_rounds


def parse_markdown_batch_table(md: str) -> list:
    """解析飞书文档 Markdown 中的批量执行表格，返回字典行列表

    飞书文档读取时每个 block 之间用 \\n\\n 分隔，表格行之间有空行，
    需要动态定位分隔行并跳过。
    """
    rows = []
    lines = md.splitlines()
    header_idx = -1
    headers = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and "jira" in stripped.lower():
            header_idx = i
            headers = [h.strip() for h in stripped.strip("|").split("|")]
            break
    if header_idx < 0:
        return rows
    data_start = header_idx + 1
    for i in range(header_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if re.match(r'^\|[-|:\s]+\|$', stripped):
            data_start = i + 1
            break
        data_start = i
        break
    for line in lines[data_start:]:
        line = line.strip()
        if not line or not line.startswith("|"):
            continue
        if re.match(r'^\|[-|:\s]+\|$', line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < len(headers):
            cells.extend([""] * (len(headers) - len(cells)))
        row = {}
        for idx, h in enumerate(headers):
            row[h] = cells[idx] if idx < len(cells) else ""
        jira_val = ""
        for key in ("Jira号", "jira号"):
            if key in row:
                jira_val = row[key].strip()
                break
        if jira_val:
            row["jira号"] = jira_val
            rows.append(row)
    return rows


_parse_markdown_batch_table = parse_markdown_batch_table


def find_comment_doc(bugid: str) -> str:
    """在 docs/日期/ 中查找最新的 {bugid}_comments.md，返回内容；未找到返回空串"""
    try:
        doc_dir = get_path("doc_dir")
        for day in sorted(os.listdir(doc_dir), reverse=True):
            path = os.path.join(doc_dir, day, f"{bugid}_comments.md")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
    except Exception:
        pass
    return ""


_find_comment_doc = find_comment_doc


def parse_ai_log_lines(lines: list, jira_id: str) -> dict:
    """解析日志行，按 Jira 号过滤并按分析轮次分组"""
    jira_upper = jira_id.upper().strip()
    matched = []
    for i, line in enumerate(lines):
        line_str = str(line).strip() if not isinstance(line, str) else line.strip()
        if not line_str:
            continue
        if jira_upper and jira_upper not in line_str.upper():
            continue
        matched.append({"line_no": i + 1, "raw": line_str})
    rounds = []
    current_round = {"round": 1, "entries": []}
    round_counter = 1
    for item in matched:
        raw = item["raw"]
        new_round = False
        if re.search(r'第\s*\d+\s*轮', raw) or re.search(r'round\s*\d+', raw, re.I):
            round_counter += 1
            new_round = True
        elif re.search(r'分析开始|开始分析|start.*analy', raw, re.I):
            round_counter += 1
            new_round = True
        elif re.search(r'={5,}|-{5,}|\*{5,}', raw) and len(current_round["entries"]) > 0:
            round_counter += 1
            new_round = True
        if new_round and current_round["entries"]:
            rounds.append(current_round)
            current_round = {"round": round_counter, "entries": []}
        entry_type = "其他"
        if re.search(r'知识库|knowledge|\.md|\.txt|文件', raw, re.I):
            entry_type = "知识库调用"
        elif re.search(r'结果|result|成功|失败|rootcause|根因|结论', raw, re.I):
            entry_type = "分析结果"
        elif re.search(r'评论|comment|jira.*评论', raw, re.I):
            entry_type = "评论分析"
        elif re.search(r'触发时间|trigger.*time', raw, re.I):
            entry_type = "触发时间"
        elif re.search(r'视频|video|ocr', raw, re.I):
            entry_type = "视频/OCR"
        elif re.search(r'置信度|confidence', raw, re.I):
            entry_type = "置信度"
        elif re.search(r'提取|extract', raw, re.I):
            entry_type = "提取"
        time_str = ""
        tm = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2})', raw)
        if tm:
            time_str = tm.group(1)
        current_round["entries"].append({
            "line_no": item["line_no"],
            "time": time_str,
            "type": entry_type,
            "content": raw[:500],
        })
    if current_round["entries"]:
        rounds.append(current_round)
    return {
        "rounds": rounds,
        "total_lines": len(lines),
        "matched_lines": len(matched),
    }


_parse_ai_log_lines = parse_ai_log_lines
