"""Jira RESTAPI 客户端：根据 bugid 提取报错原因与评论区评论

mock 模式下直接从本地测试数据表（bug_test_data.csv）读取评论与根因，
不再使用硬编码兜底数据。
"""
import re
from datetime import datetime

from src.clients.ai_log_client import _load_testdata_row
from src.clients.base import http_get
from src.config import load_config, setup_logger

logger = setup_logger("jira")



def _build_mock_response(bugid: str) -> dict:
    """构造 mock Jira 响应：从测试数据表读取根因与评论

    bugid 含 FAIL 时返回与 AI 报告不一致的根因，用于验证比对失败分支。
    bugid 含 OPEN 时返回未关闭状态，用于验证状态过滤。
    """
    if "FAIL" in bugid.upper():
        # 失败分支：根因与 AI 报告不一致，评论为空
        return {
            "key": bugid,
            "fields": {
                "description": "线上服务报错，原因：数据库连接池耗尽导致服务超时",
                "status": {"name": "Closed"},
            },
            "comments": [],
        }
    # OPEN 分支：模拟未关闭状态
    status_name = "Open" if "OPEN" in bugid.upper() else "Closed"
    # 从测试数据表读取
    testdata_row = _load_testdata_row(bugid)
    if testdata_row:
        root_cause = testdata_row["根因分析"]
        comments = [c.strip() for c in testdata_row["评论"].split("|") if c.strip()]
    else:
        root_cause = ""
        comments = []
    return {
        "key": bugid,
        "fields": {
            "description": f"线上服务报错，原因：{root_cause}",
            "status": {"name": status_name},
        },
        "comments": comments,
    }


def fetch_issue(bugid: str) -> dict:
    """根据 bugid 调用 Jira RESTAPI，返回 issue 信息（只读操作）"""
    cfg = load_config()["jira_api"]
    if cfg.get("mock", False):
        logger.info("[mock] 获取 Jira 信息: bugid=%s", bugid)
        return _build_mock_response(bugid)
    # 构造认证参数：支持 Bearer Token / Basic Auth
    headers = {}
    auth = None
    token = cfg.get("token", "")
    if token:
        auth_type = cfg.get("auth_type", "bearer").lower()
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {token}"
        elif cfg.get("username"):
            auth = (cfg["username"], token)
    url = f"{cfg['url']}/{bugid}"
    logger.info("调用 Jira RESTAPI (GET): %s", url)
    # expand=comment 确保返回评论区数据，否则 Jira API 默认不包含评论
    return http_get(url, params={"expand": "comment"}, timeout=cfg.get("timeout", 30), auth=auth, headers=headers)


def search_issues(jql: str, max_results: int = 500) -> list:
    """通过 JQL 搜索 Jira issue，支持自动分页（突破单次 1000 条限制）

    :param jql: JQL 查询语句
    :param max_results: 最大返回数量
    :return: issue 列表，每项含 key 和 fields
    """
    cfg = load_config()["jira_api"]
    if cfg.get("mock", False):
        logger.info("[mock] JQL 搜索: %s", jql)
        return []
    headers = {}
    auth = None
    token = cfg.get("token", "")
    if token:
        auth_type = cfg.get("auth_type", "bearer").lower()
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {token}"
        elif cfg.get("username"):
            auth = (cfg["username"], token)
    search_url = cfg["url"].rsplit("/issue", 1)[0] + "/search"
    logger.info("JQL 搜索: %s (max=%d)", search_url, max_results)
    all_issues = []
    start_at = 0
    page_size = min(max_results, 1000)  # Jira 单次上限 1000
    while len(all_issues) < max_results:
        result = http_get(search_url, params={"jql": jql, "maxResults": page_size,
                                              "startAt": start_at, "fields": "summary,status,created"},
                          timeout=cfg.get("timeout", 30), auth=auth, headers=headers)
        issues = result.get("issues", [])
        if not issues:
            break
        all_issues.extend(issues)
        total = result.get("total", 0)
        logger.info("JQL 分页: 已获取 %d/%d 条", len(all_issues), total)
        if len(all_issues) >= total or len(issues) < page_size:
            break
        start_at += len(issues)
    return all_issues[:max_results]


def extract_error_cause(issue: dict) -> str:
    """从 issue 中提取报错原因（description 字段）"""
    return (issue.get("fields") or {}).get("description") or ""


def extract_status(issue: dict) -> str:
    """从 issue 中提取状态字段（fields.status.name）"""
    status = (issue.get("fields") or {}).get("status") or {}
    return (status.get("name") or "").strip()


def extract_rootcause(issue: dict) -> str:
    """从 issue 中提取 rootcause 字段

    优先取配置中指定的自定义字段，回退尝试常见字段名，最后回退 description。
    """
    fields = issue.get("fields") or {}
    # 1. 优先取配置中指定的自定义字段名
    cfg = load_config().get("jira_api", {})
    custom_field = cfg.get("root_cause_field", "")
    if custom_field:
        val = fields.get(custom_field)
        if val:
            return _parse_rootcause_value(val)
    # 2. 尝试常见字段名
    for key in ("rootcause", "rootCause", "Root Cause"):
        val = fields.get(key)
        if val:
            return _parse_rootcause_value(val)
    # 3. 回退：从 description 中提取
    import re
    description = fields.get("description") or ""
    cleaned = re.sub(r"^线上服务报错[\uff0c,]\s*原因[\uff1a:]\s*", "", description.strip())
    return cleaned.strip()


def _parse_rootcause_value(val) -> str:
    """解析根因字段值：处理字符串和对象两种格式"""
    if isinstance(val, dict):
        val = val.get("value") or val.get("name") or str(val)
    text = str(val).strip()
    # 去除常见前缀如 "RootCause:item"
    import re
    text = re.sub(r"^RootCause\s*[:\uff1a]\s*(item)?\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def extract_comments(issue: dict) -> list:
    """从 issue 中提取评论区评论列表（按时间正序）

    兼容两种格式：
    - mock 归一化格式：顶层 comments 列表
    - 原始 Jira 响应：fields.comment.comments 嵌套结构
    """
    # 优先取归一化的顶层 comments（mock 格式，已排序）
    comments = issue.get("comments")
    if comments:
        return comments
    # 回退：从 fields.comment.comments 提取（真实 Jira 格式）
    fields = issue.get("fields") or {}
    comment_obj = fields.get("comment") or {}
    raw_comments = comment_obj.get("comments") or []
    # 按创建时间正序排序（Jira 返回顺序不一定保证）
    raw_comments.sort(key=lambda c: c.get("created", ""))
    # 提取每条评论的 body 文本
    result = []
    for c in raw_comments:
        body = c.get("body") or ""
        # Jira Cloud 可能返回 ADF 格式（dict），转换为纯文本
        if isinstance(body, dict):
            body = _extract_adf_text(body)
        if body.strip():
            result.append(body.strip())
    return result


def _extract_adf_text(adf: dict) -> str:
    """从 Jira ADF (Atlassian Document Format) 中提取纯文本"""
    texts = []
    for node in adf.get("content", []):
        for child in node.get("content", []):
            if child.get("type") == "text":
                texts.append(child.get("text", ""))
    return "\n".join(texts)


# 时间戳正则：完整格式 YYYY-MM-DD HH:MM:SS 和 无年份格式 MM-DD HH:MM:SS（可带毫秒）
_TIMESTAMP_FULL_RE = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")
_TIMESTAMP_SHORT_RE = re.compile(r"(?<!\d)(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})(?:\.\d+)?")

# 附件文件名时间正则
_GMLOGGER_RE = re.compile(r"gmlogger[_\-](\d{4})[_\-](\d{1,2})[_\-](\d{1,2})[_\-](\d{1,2})[_\-](\d{1,2})(?:[_\-](\d{1,2}))?")
_US_DATE_RE = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})\s+(\d{1,2})-(\d{1,2})(?:-(\d{1,2}))?\s*(am|pm)?", re.IGNORECASE)
_COMPACT_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:(\d{2}))?")

# 附件分类后缀
_ARCHIVE_SUFFIXES = (".7z", ".zip", ".rar", ".gz", ".tar", ".z001", ".001")
_MEDIA_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".mp4", ".avi", ".mov", ".mkv")


def _extract_attachment_time(issue: dict) -> str:
    """从附件文件名提取时间，优先级：gmlogger > 压缩包 > 图片/视频"""
    attachments = (issue.get("fields") or {}).get("attachment") or []
    gmlogger_times = []
    archive_times = []
    media_times = []
    for att in attachments:
        filename = att.get("filename", "")
        if not filename:
            continue
        fn_lower = filename.lower()
        # gmlogger 日志文件（最高优先级）
        if "gmlogger" in fn_lower:
            t = _parse_filename_time(filename, "gmlogger")
            if t:
                gmlogger_times.append(t)
        # 压缩包
        elif any(fn_lower.endswith(s) for s in _ARCHIVE_SUFFIXES):
            t = _parse_filename_time(filename, "archive")
            if t:
                archive_times.append(t)
        # 图片/视频
        elif any(fn_lower.endswith(s) for s in _MEDIA_SUFFIXES):
            t = _parse_filename_time(filename, "media")
            if t:
                media_times.append(t)
    # 按优先级返回
    for label, times in [("gmlogger", gmlogger_times), ("压缩包", archive_times), ("图片/视频", media_times)]:
        if times:
            result = times[0][0]
            logger.info("从附件[%s]提取到时间: %s（共 %d 个候选）", label, result, len(times))
            return result
    return ""


def _parse_filename_time(filename: str, file_type: str) -> tuple:
    """从文件名解析时间，返回 (时间字符串, datetime) 或 None"""
    if file_type == "gmlogger":
        m = _GMLOGGER_RE.search(filename)
        if m:
            year, month, day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
            second = int(m.group(6)) if m.group(6) else 0
            try:
                ts = datetime(year, month, day, hour, minute, second)
                return (ts.strftime("%Y-%m-%d %H:%M:%S"), ts)
            except ValueError:
                return None
    else:
        # 压缩包和图片/视频：先尝试 US 日期格式 (M-D-YYYY H-M-S am/pm)
        m = _US_DATE_RE.search(filename)
        if m:
            month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            hour, minute = int(m.group(4)), int(m.group(5))
            second = int(m.group(6)) if m.group(6) else 0
            if m.group(7) and m.group(7).lower() == "pm" and hour < 12:
                hour += 12
            elif m.group(7) and m.group(7).lower() == "am" and hour == 12:
                hour = 0
            try:
                ts = datetime(year, month, day, hour, minute, second)
                return (ts.strftime("%Y-%m-%d %H:%M:%S"), ts)
            except ValueError:
                pass
        # 再尝试紧凑格式 (YYYYMMDDHHmm 或 YYYYMMDDHHmmss)
        m = _COMPACT_RE.search(filename)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            hour, minute = int(m.group(4)), int(m.group(5))
            second = int(m.group(6)) if m.group(6) else 0
            try:
                ts = datetime(year, month, day, hour, minute, second)
                return (ts.strftime("%Y-%m-%d %H:%M:%S"), ts)
            except ValueError:
                pass
    return None


def _is_log_related(text: str) -> bool:
    """判断文本是否为日志相关内容"""
    log_keywords = ["gmlogger", "log", "line ", "timestamp", "error", "fail", "exception", "trace"]
    lower = text.lower()
    if any(kw in lower for kw in log_keywords):
        return True
    # 检查是否为 Android logcat 格式: MM-DD HH:MM:SS 或带行号的格式
    import re
    # 匹配 "数字: MM-DD" 或 " MM-DD HH:MM" 格式
    if re.search(r'\d{1,6}:\s*\d{2}-\d{2}\s+\d{2}:\d{2}', text):
        return True
    if re.search(r'^\s*\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', text):
        return True
    return False


def _pick_best_time(text: str, times: list) -> tuple:
    """从多个时间中选择最佳的一个：取最早的时间（按时间戳从小到大排序取第一个）

    :param text: 原始文本
    :param times: [(time_str, datetime), ...]
    :return: 最佳时间 (time_str, datetime)，如果只有一个直接返回
    """
    if not times:
        return None
    if len(times) == 1:
        return times[0]
    # 去重
    seen = set()
    unique = []
    for t in times:
        if t[0] not in seen:
            seen.add(t[0])
            unique.append(t)
    if len(unique) == 1:
        return unique[0]
    # 按时间戳从小到大排序，取最早的一个
    unique.sort(key=lambda t: t[1])
    best = unique[0]
    logger.info("从 %d 个时间中选择最早的一个: %s", len(unique), best[0])
    return best


def _extract_times_from_text(text: str, year: str = "") -> list:
    """从文本中提取时间，返回 [(time_str, datetime), ...]"""
    times = []
    # 完整格式
    for match in _TIMESTAMP_FULL_RE.finditer(text):
        try:
            ts = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
            times.append((match.group(1), ts))
        except ValueError:
            continue
    # 短格式
    if year:
        for match in _TIMESTAMP_SHORT_RE.finditer(text):
            short_str = match.group(1)
            full_str = f"{year}-{short_str}"
            try:
                ts = datetime.strptime(full_str, "%Y-%m-%d %H:%M:%S")
                times.append((full_str, ts))
            except ValueError:
                continue
    return times


def extract_trigger_time_from_issue(issue: dict) -> str:
    """从 issue 评论区提取日志时间，优先从最新评论的日志内容中提取

    策略：
    - 按评论创建时间倒序（最新在前）
    - 优先从日志相关内容中提取（如包含 gmlogger/log/Line 等关键字的行）
    - 如果最新评论的日志内容中有时间，直接返回第一个
    - 如果最新评论无日志时间，再从普通文本中提取
    - 如果都没有，继续往前找
    :param issue: Jira issue 原始响应
    :return: 提取的时间字符串，未找到返回空字符串
    """
    fields = issue.get("fields") or {}
    comment_obj = fields.get("comment") or {}
    raw_comments = comment_obj.get("comments") or []
    # 按创建时间倒序，最新的评论在前
    raw_comments.sort(key=lambda c: c.get("created", ""), reverse=True)
    # mock 格式：顶层 comments 列表，无创建时间信息
    if not raw_comments and issue.get("comments"):
        return extract_trigger_time_from_comments(issue["comments"])

    for c in raw_comments:
        body = c.get("body") or ""
        if isinstance(body, dict):
            body = _extract_adf_text(body)
        if not body.strip():
            continue
        # 从评论创建时间获取年份（用于补充短格式）
        created = c.get("created", "")
        comment_year = created[:4] if created and len(created) >= 4 else ""
        # 检查评论是否包含日志相关内容
        lines = body.split("\n")
        log_lines = [line for line in lines if _is_log_related(line)]
        if log_lines:
            # 包含日志相关行：优先从日志相关行中提取时间，取最早的
            log_text = "\n".join(log_lines)
            log_times = _extract_times_from_text(log_text, comment_year)
            if log_times:
                best = _pick_best_time(log_text, log_times)
                if best:
                    logger.info("从最新评论日志相关行中提取到最早时间: %s", best[0])
                    return best[0]
            # 日志相关行中没有时间，尝试从普通行中提取
            normal_lines = [line for line in lines if not _is_log_related(line)]
            if normal_lines:
                normal_text = "\n".join(normal_lines)
                normal_times = _extract_times_from_text(normal_text, comment_year)
                if normal_times:
                    best = _pick_best_time(normal_text, normal_times)
                    if best:
                        logger.info("从最新评论普通文本中提取到最早时间: %s", best[0])
                        return best[0]
        else:
            # 不包含日志相关行：从普通文本中提取时间
            normal_times = _extract_times_from_text(body, comment_year)
            if normal_times:
                best = _pick_best_time(body, normal_times)
                if best:
                    logger.info("从最新评论普通文本中提取到最早时间: %s", best[0])
                    return best[0]
    # 评论无时间，尝试从描述(description)中提取时间
    description = fields.get("description") or ""
    if isinstance(description, dict):
        description = _extract_adf_text(description)
    if description:
        desc_times = []
        for match in _TIMESTAMP_FULL_RE.finditer(description):
            try:
                ts = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
                desc_times.append((match.group(1), ts))
            except ValueError:
                continue
        if desc_times:
            if len(desc_times) == 1:
                logger.info("从描述中提取到 1 个时间: %s", desc_times[0][0])
                return desc_times[0][0]
            mean_ts = sum(t[1].timestamp() for t in desc_times) / len(desc_times)
            closest = min(desc_times, key=lambda t: abs(t[1].timestamp() - mean_ts))
            logger.info("从描述中提取到 %d 个时间，均值附近最近: %s", len(desc_times), closest[0])
            return closest[0]
    # 描述中也没有时间
    return ""


def extract_trigger_time_from_comments(comments: list) -> str:
    """从评论文本列表中提取日志时间（仅支持完整格式）

    :param comments: 评论文本列表
    :return: 提取的时间字符串，未找到返回空字符串
    """
    all_times = []
    for body in comments:
        for match in _TIMESTAMP_FULL_RE.finditer(str(body)):
            try:
                ts = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
                all_times.append((match.group(1), ts))
            except ValueError:
                continue
    if not all_times:
        return ""
    if len(all_times) == 1:
        logger.info("从评论中提取到 1 个时间: %s", all_times[0][0])
        return all_times[0][0]
    # 去重后取均值最近
    seen = set()
    unique_times = []
    for t in all_times:
        if t[0] not in seen:
            seen.add(t[0])
            unique_times.append(t)
    if len(unique_times) == 1:
        logger.info("从评论中提取到 %d 个时间（去重后 1 个）: %s", len(all_times), unique_times[0][0])
        return unique_times[0][0]
    mean_ts = sum(t[1].timestamp() for t in unique_times) / len(unique_times)
    closest = min(unique_times, key=lambda t: abs(t[1].timestamp() - mean_ts))
    logger.info("从评论中提取到 %d 个时间（去重后 %d 个），均值附近最近: %s", len(all_times), len(unique_times), closest[0])
    return closest[0]
