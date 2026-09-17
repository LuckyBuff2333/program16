"""Jira RESTAPI 客户端：根据 bugid 提取报错原因与评论区评论

mock 模式下直接从本地测试数据表（bug_test_data.csv）读取评论与根因，
不再使用硬编码兜底数据。
"""
import re
from datetime import datetime, timedelta

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
    # expand=comment,names 确保返回评论区数据 + 字段显示名映射，否则 Jira API 默认不包含
    return http_get(url, params={"expand": "comment,names"}, timeout=cfg.get("timeout", 30), auth=auth, headers=headers)


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

    优先取配置中指定的自定义字段，回退尝试常见字段名。
    根因字段为空时返回空字符串（不回退 description，避免误读测试时间等非根因内容）。
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
    # 3. 根因字段为空，返回空字符串（不再回退 description）
    return ""


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
# 斜杠日期格式：YYYY/M/D HH:MM 或 YYYY/MM/DD HH:MM:SS（月/日支持单位数）
_TIMESTAMP_SLASH_RE = re.compile(r"(\d{4}/\d{1,2}/\d{1,2}\s+\d{2}:\d{2}(?::\d{2})?)")
# 点分隔日期格式：YYYY.M.D HH:MM 或 YYYY.M.DD HH:MM:SS（月/日支持单位数，如 2026.8.28 14:50）
_TIMESTAMP_DOT_RE = re.compile(r"(\d{4}\.\d{1,2}\.\d{1,2}\s+\d{2}:\d{2}(?::\d{2})?)")
# ISO 8601 格式：YYYY-MM-DDTHH:MM:SS（可带毫秒和时区，捕获时区用于转换）
_TIMESTAMP_ISO_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.\d+)?([+\-]\d{2}:\d{2})?(Z?)")
# UTC+8 时区偏移量（用于将 UTC 时间转换为本地时间）
_UTC8_OFFSET = timedelta(hours=8)

# 紧凑日期格式：前缀+YYYYMMDD_HHMM（如 HMI:20240708_1556）
_TIMESTAMP_HMI_RE = re.compile(r"[A-Za-z]+:(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})")
# 附件文件名时间正则
_GMLOGGER_RE = re.compile(r"gmlogger[_\-](\d{4})[_\-](\d{1,2})[_\-](\d{1,2})[_\-](\d{1,2})[_\-](\d{1,2})(?:[_\-](\d{1,2}))?")
_US_DATE_RE = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})\s+(\d{1,2})-(\d{1,2})(?:-(\d{1,2}))?\s*(am|pm)?", re.IGNORECASE)
_COMPACT_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:(\d{2}))?")


def _normalize_datetime_text(text: str) -> str:
    """标准化非标准日期时间文本，提升提取兼容性

    处理两类常见异常格式：
    1. 破折号分隔符：YYYY/MM/DD——HH:MM → YYYY/MM/DD HH:MM（全角/半角破折号替换为空格）
    2. 冒号空格：HH: MM → HH:MM（去除时间冒号旁的空格）
    """
    # 破折号/全角横线替换为空格（U+2013 en-dash, U+2014 em-dash, U+2015 horizontal bar, U+FF0D fullwidth hyphen-minus）
    text = re.sub(r'[\u2013\u2014\u2015\uFF0D]+', ' ', text)
    # 时间冒号旁空格去除（14: 57 → 14:57，不影响日期部分）
    text = re.sub(r'(\d)\s*:\s*(\d)', r'\1:\2', text)
    return text


# 附件分类后缀
_ARCHIVE_SUFFIXES = (".7z", ".zip", ".rar", ".gz", ".tar", ".z001", ".001")
_MEDIA_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".mp4", ".avi", ".mov", ".mkv")


def _is_valid_date(year: int, month: int, day: int) -> bool:
    """校验日期是否符合公历逻辑（如 2 月 31 日、4 月 31 日等无效日期返回 False）"""
    if not (2020 <= year <= 2030):
        return False
    if not (1 <= month <= 12):
        return False
    # 每月最大天数
    max_days = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return 1 <= day <= max_days[month - 1]


def _parse_datetime_string(text: str) -> tuple:
    """尝试多种格式解析日期时间字符串，返回 (标准化时间字符串, datetime) 或 None

    支持格式：YYYY-MM-DD HH:MM:SS, YYYY/MM/DD HH:MM, YYYY/MM/DD HH:MM:SS,
               YYYY-MM-DDTHH:MM:SS, YYYY-MM-DD HH:MM
    """
    text = _normalize_datetime_text(text.strip())
    # YYYY-MM-DD HH:MM:SS
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            ts = datetime.strptime(text[:len("2025-04-15 19:07:30")], fmt)
            if _is_valid_date(ts.year, ts.month, ts.day):
                return (ts.strftime("%Y-%m-%d %H:%M:%S"), ts)
        except (ValueError, IndexError):
            continue
    # 正则提取 YYYY/MM/DD HH:MM 格式
    m = _TIMESTAMP_SLASH_RE.search(text)
    if m:
        raw = m.group(1)
        for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                ts = datetime.strptime(raw, fmt)
                if _is_valid_date(ts.year, ts.month, ts.day):
                    return (ts.strftime("%Y-%m-%d %H:%M:%S"), ts)
            except ValueError:
                continue
    # 正则提取 YYYY.M.D HH:MM 格式
    m = _TIMESTAMP_DOT_RE.search(text)
    if m:
        raw = m.group(1)
        for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M"):
            try:
                ts = datetime.strptime(raw, fmt)
                if _is_valid_date(ts.year, ts.month, ts.day):
                    return (ts.strftime("%Y-%m-%d %H:%M:%S"), ts)
            except ValueError:
                continue
    return None


def _extract_from_custom_fields(issue: dict) -> str:
    """从 Jira issue 自定义字段中提取触发时间

    仅从以下指定字段提取：
    1. Operation Schedule（排期时间）
    2. Unit Test 中的 time stamp 值
    3. Initial Setting 中的 log time 值（最低优先级）
    """
    fields = issue.get("fields") or {}
    names = issue.get("names") or {}
    _SKIP_FIELDS = {"comment", "attachment", "description", "summary", "status", "issuetype",
                    "project", "assignee", "reporter", "creator", "priority", "labels",
                    "fixVersions", "versions", "components", "resolution", "watches", "votes"}
    # 构建 field_id -> display_name 映射
    id_to_name = {}
    for fid, fname in names.items():
        if fid not in _SKIP_FIELDS:
            id_to_name[fid] = str(fname)
    # 收集目标字段
    schedule_fields = []  # Operation Schedule
    unittest_fields = []  # Unit Test (提取其中的 time stamp)
    initial_fields = []  # Initial Setting (提取其中的 log time)
    operation_fields = []  # 操作顺序 / 执行结果（兆底提取）
    for fid, value in fields.items():
        if fid in _SKIP_FIELDS or value is None:
            continue
        name = id_to_name.get(fid, fid).lower()
        if "operation schedule" in name or "schedule" in name and "operation" in name:
            schedule_fields.append((fid, value, id_to_name.get(fid, fid)))
        elif "unit test" in name or "unittest" in name:
            unittest_fields.append((fid, value, id_to_name.get(fid, fid)))
        elif "initial setting" in name or "初始设定" in name:
            initial_fields.append((fid, value, id_to_name.get(fid, fid)))
        elif "操作顺序" in name or "operation sequence" in name or "执行结果" in name or "actual result" in name:
            operation_fields.append((fid, value, id_to_name.get(fid, fid)))
    # 优先 Operation Schedule
    for fid, value, name in schedule_fields:
        text = str(value).strip()
        if not text or text.lower() in ("none", "null", ""):
            continue
        parsed = _parse_datetime_string(text)
        if parsed:
            logger.info("从自定义字段[%s/%s]提取到时间: %s", fid, name, parsed[0])
            return parsed[0]
        for regex, fmt in [(_TIMESTAMP_FULL_RE, "%Y-%m-%d %H:%M:%S"),
                           (_TIMESTAMP_SLASH_RE, None)]:
            for m in regex.finditer(text):
                raw = m.group(1) if m.lastindex else m.group(0)
                p = _parse_datetime_string(raw) if fmt is None else None
                if p:
                    logger.info("从字段[%s/%s]文本提取到时间: %s", fid, name, p[0])
                    return p[0]
                if fmt:
                    try:
                        ts = datetime.strptime(raw, fmt)
                        if _is_valid_date(ts.year, ts.month, ts.day):
                            logger.info("从字段[%s/%s]文本提取到时间: %s", fid, name, ts.strftime(fmt))
                            return ts.strftime(fmt)
                    except ValueError:
                        continue
    # 其次 Unit Test 中的 time stamp
    for fid, value, name in unittest_fields:
        text = str(value).strip()
        if not text or text.lower() in ("none", "null", ""):
            continue
        # 优先查找 time stamp / timestamp 相关行
        for line in text.split("\n"):
            line_lower = line.lower()
            if "time stamp" in line_lower or "timestamp" in line_lower:
                parsed = _parse_datetime_string(line)
                if parsed:
                    logger.info("从字段[%s/%s] time stamp 提取到时间: %s", fid, name, parsed[0])
                    return parsed[0]
                for regex, fmt in [(_TIMESTAMP_FULL_RE, "%Y-%m-%d %H:%M:%S"),
                                   (_TIMESTAMP_SLASH_RE, None)]:
                    for m in regex.finditer(line):
                        raw = m.group(1) if m.lastindex else m.group(0)
                        p = _parse_datetime_string(raw) if fmt is None else None
                        if p:
                            logger.info("从字段[%s/%s] time stamp 提取到时间: %s", fid, name, p[0])
                            return p[0]
                        if fmt:
                            try:
                                ts = datetime.strptime(raw, fmt)
                                if _is_valid_date(ts.year, ts.month, ts.day):
                                    logger.info("从字段[%s/%s] time stamp 提取到时间: %s", fid, name, ts.strftime(fmt))
                                    return ts.strftime(fmt)
                            except ValueError:
                                continue
        # 没有 time stamp 行，从整个字段值中提取第一个有效时间
        parsed = _parse_datetime_string(text)
        if parsed:
            logger.info("从自定义字段[%s/%s]提取到时间: %s", fid, name, parsed[0])
            return parsed[0]
    # 最后 Initial Setting 中的 log time / Time
    for fid, value, name in initial_fields:
        text = str(value).strip()
        if not text or text.lower() in ("none", "null", ""):
            continue
        # 标准化破折号分隔符和冒号空格（如 2026/08/31——14: 57 → 2026/08/31 14:57）
        text = _normalize_datetime_text(text)
        for line in text.split("\n"):
            line_lower = line.lower().strip()
            if "log time" in line_lower or line_lower.startswith("time:") or line_lower.startswith("time "):
                parsed = _parse_datetime_string(line)
                if parsed:
                    logger.info("从字段[%s/%s] Initial Setting time 提取到时间: %s", fid, name, parsed[0])
                    return parsed[0]
                for regex, fmt in [(_TIMESTAMP_FULL_RE, "%Y-%m-%d %H:%M:%S"),
                                   (_TIMESTAMP_SLASH_RE, None)]:
                    for m in regex.finditer(line):
                        raw = m.group(1) if m.lastindex else m.group(0)
                        p = _parse_datetime_string(raw) if fmt is None else None
                        if p:
                            logger.info("从字段[%s/%s] Initial Setting time 提取到时间: %s", fid, name, p[0])
                            return p[0]
                        if fmt:
                            try:
                                ts = datetime.strptime(raw, fmt)
                                if _is_valid_date(ts.year, ts.month, ts.day):
                                    logger.info("从字段[%s/%s] Initial Setting time 提取到时间: %s", fid, name, ts.strftime(fmt))
                                    return ts.strftime(fmt)
                            except ValueError:
                                continue
    # 兆底：操作顺序 / 执行结果字段中的时间
    # 支持短格式 M/D HH:MM（无年份，从 issue 创建日期推断年份）
    _SHORT_TIME_RE = re.compile(r'(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?')
    created = ((issue.get("fields") or {}).get("created") or "")[:4]
    fallback_year = int(created) if created.isdigit() else datetime.now().year
    for fid, value, name in operation_fields:
        text = str(value).strip()
        if not text or text.lower() in ("none", "null", ""):
            continue
        # 先尝试完整格式
        for regex, fmt in [(_TIMESTAMP_FULL_RE, "%Y-%m-%d %H:%M:%S"),
                           (_TIMESTAMP_SLASH_RE, None)]:
            for m in regex.finditer(text):
                raw = m.group(1) if m.lastindex else m.group(0)
                p = _parse_datetime_string(raw) if fmt is None else None
                if p:
                    logger.info("从字段[%s/%s]提取到时间: %s", fid, name, p[0])
                    return p[0]
                if fmt:
                    try:
                        ts = datetime.strptime(raw, fmt)
                        if _is_valid_date(ts.year, ts.month, ts.day):
                            logger.info("从字段[%s/%s]提取到时间: %s", fid, name, ts.strftime(fmt))
                            return ts.strftime(fmt)
                    except ValueError:
                        continue
        # 短格式 M/D HH:MM 兆底
        for m in _SHORT_TIME_RE.finditer(text):
            month, day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            second = int(m.group(5)) if m.group(5) else 0
            if _is_valid_date(fallback_year, month, day) and 0 <= hour < 24 and 0 <= minute < 60:
                try:
                    ts = datetime(fallback_year, month, day, hour, minute, second)
                    result = ts.strftime("%Y-%m-%d %H:%M:%S")
                    logger.info("从字段[%s/%s]短格式提取到时间: %s", fid, name, result)
                    return result
                except ValueError:
                    continue
    return ""


def _supplement_from_gmlogger(issue: dict, partial_time: str) -> str:
    """当提取的时间不完整时，从 gmlogger 文件名中补充年份和日期

    策略：找到文件名中日期与 partial_time 的月日最匹配的 gmlogger 文件，用其年份补全
    """
    if not partial_time:
        return partial_time
    attachments = (issue.get("fields") or {}).get("attachment") or []
    gmlogger_dates = []
    for att in attachments:
        filename = att.get("filename", "")
        if "gmlogger" not in filename.lower():
            continue
        m = _GMLOGGER_RE.search(filename)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if _is_valid_date(y, mo, d):
                gmlogger_dates.append((y, mo, d))
    if not gmlogger_dates:
        return partial_time
    # 尝试解析 partial_time 中的月日信息
    try:
        # partial_time 可能是 "MM-DD HH:MM:SS" 或 "04-15 19:07:30" 等无年份格式
        parts = partial_time.strip().split()
        date_part = parts[0] if parts else partial_time
        if re.match(r'^\d{2}-\d{2}$', date_part):
            mo, d = int(date_part.split('-')[0]), int(date_part.split('-')[1])
            time_part = parts[1] if len(parts) > 1 else "00:00:00"
            # 找月日匹配的 gmlogger
            for y, gmo, gd in gmlogger_dates:
                if gmo == mo and gd == d:
                    result = f"{y:04d}-{mo:02d}-{d:02d} {time_part}"
                    logger.info("gmlogger 补充年份: %s -> %s", partial_time, result)
                    return result
            # 无精确匹配，用最近的 gmlogger 年份
            y = gmlogger_dates[0][0]
            result = f"{y:04d}-{mo:02d}-{d:02d} {time_part}"
            logger.info("gmlogger 补充年份（无精确匹配）: %s -> %s", partial_time, result)
            return result
    except (ValueError, IndexError):
        pass
    return partial_time


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
    """从多个时间中选择最佳的一个：优先选择出现次数最多的时间，或相近时间簇中的代表值

    选择策略：
    1. 完全相同的时间合并计数，取出现最多的
    2. 若多个时间都在 1 分钟内视为同一簇，取簇中最早的一个
    3. 多个簇时取最大的簇

    :param text: 原始文本
    :param times: [(time_str, datetime), ...]
    :return: 最佳时间 (time_str, datetime)，如果只有一个直接返回
    """
    if not times:
        return None
    if len(times) == 1:
        return times[0]
    # 精确去重计数
    from collections import Counter
    count_map = Counter()
    time_map = {}
    for t_str, t_dt in times:
        count_map[t_str] += 1
        time_map[t_str] = t_dt
    unique = [(t_str, time_map[t_str]) for t_str in count_map]
    if len(unique) == 1:
        return unique[0]
    # 按时间戳排序后聚类（1分钟内视为同簇）
    unique.sort(key=lambda t: t[1])
    clusters = []
    current_cluster = [unique[0]]
    for t in unique[1:]:
        diff = (t[1] - current_cluster[-1][1]).total_seconds()
        if diff <= 60:  # 1分钟内视为同簇
            current_cluster.append(t)
        else:
            clusters.append(current_cluster)
            current_cluster = [t]
    clusters.append(current_cluster)
    # 计算每个簇的总出现次数
    cluster_scores = []
    for cluster in clusters:
        total_count = sum(count_map[t[0]] for t in cluster)
        cluster_scores.append((total_count, cluster))
    cluster_scores.sort(key=lambda x: x[0], reverse=True)
    best_cluster = cluster_scores[0][1]
    # 取最大簇中出现次数最多的时间
    best = max(best_cluster, key=lambda t: count_map[t[0]])
    logger.info("从 %d 个时间中选择最佳: %s（簇大小=%d，总出现=%d次，该时间出现=%d次）",
                len(unique), best[0], len(best_cluster), cluster_scores[0][0], count_map[best[0]])
    return best


def _extract_times_from_text(text: str, year: str = "") -> list:
    """从文本中提取时间，返回 [(time_str, datetime), ...]

    支持格式：YYYY-MM-DD HH:MM:SS, MM-DD HH:MM:SS, YYYY/MM/DD HH:MM(:SS), ISO 8601
    """
    times = []
    # 标准化非标准分隔符和冒号空格，确保后续正则命中
    text = _normalize_datetime_text(text)
    # 完整格式 YYYY-MM-DD HH:MM:SS
    for match in _TIMESTAMP_FULL_RE.finditer(text):
        try:
            ts = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
            if _is_valid_date(ts.year, ts.month, ts.day):
                times.append((match.group(1), ts))
        except ValueError:
            continue
    # ISO 8601 格式 YYYY-MM-DDTHH:MM:SS（支持时区转换）
    for match in _TIMESTAMP_ISO_RE.finditer(text):
        date_str, time_str, tz_offset, z_suffix = match.group(1), match.group(2), match.group(3), match.group(4)
        try:
            ts = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            # UTC 时间（Z 后缀）转换为 UTC+8
            if z_suffix == "Z":
                ts = ts + _UTC8_OFFSET
                logger.debug("ISO时间 %sT%sZ 转换为 UTC+8: %s", date_str, time_str, ts)
            # 带偏移量的非 UTC+8 时区也进行转换
            elif tz_offset and tz_offset not in ("+08:00", "-08:00"):
                sign = 1 if tz_offset[0] == '+' else -1
                h, m = int(tz_offset[1:3]), int(tz_offset[4:6])
                offset_delta = timedelta(hours=h, minutes=m) * sign
                ts = ts - offset_delta + _UTC8_OFFSET
            if _is_valid_date(ts.year, ts.month, ts.day):
                fmt_str = ts.strftime("%Y-%m-%d %H:%M:%S")
                if fmt_str not in [t[0] for t in times]:
                    times.append((fmt_str, ts))
        except ValueError:
            continue
    # 斜杠格式 YYYY/MM/DD HH:MM(:SS)
    for match in _TIMESTAMP_SLASH_RE.finditer(text):
        p = _parse_datetime_string(match.group(1))
        if p and p[0] not in [t[0] for t in times]:
            times.append(p)
    # 点分隔格式 YYYY.M.D HH:MM(:SS)
    for match in _TIMESTAMP_DOT_RE.finditer(text):
        p = _parse_datetime_string(match.group(1))
        if p and p[0] not in [t[0] for t in times]:
            times.append(p)
    # HMI 紧凑格式 HMI:YYYYMMDD_HHMM
    for match in _TIMESTAMP_HMI_RE.finditer(text):
        y, mo, d, h, mi = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4)), int(match.group(5))
        if _is_valid_date(y, mo, d) and 0 <= h <= 23 and 0 <= mi <= 59:
            fmt_str = f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:00"
            if fmt_str not in [t[0] for t in times]:
                try:
                    ts = datetime(y, mo, d, h, mi, 0)
                    times.append((fmt_str, ts))
                except ValueError:
                    continue
    # 短格式 MM-DD HH:MM:SS（需补充年份）
    if year:
        for match in _TIMESTAMP_SHORT_RE.finditer(text):
            short_str = match.group(1)
            full_str = f"{year}-{short_str}"
            try:
                ts = datetime.strptime(full_str, "%Y-%m-%d %H:%M:%S")
                if _is_valid_date(ts.year, ts.month, ts.day):
                    times.append((full_str, ts))
            except ValueError:
                continue
    return times


def extract_trigger_time_from_issue(issue: dict) -> str:
    """从 issue 中提取触发时间，按优先级逐级回退

    提取顺序：
    1. 评论区（按时间倒序，优先日志相关行）
    2. 描述(description)
    3. 标题(summary)
    4. 自定义字段（Operation Schedule > Unit Test 的 time stamp > Initial Setting 的 log time）
    附件文件名仅用于补充不完整时间的年月日，不直接作为触发时间
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
        # 检查评论是否包含日志相关内容（排除附件引用行，附件名中的时间仅用于补充不完整日期）
        lines = body.split("\n")
        log_lines = [line for line in lines if _is_log_related(line) and "附件" not in line and "attachment" not in line.lower()]
        if log_lines:
            # 仅从日志相关行中提取时间，非日志内容（验证/复测/变更等）跳过
            log_text = "\n".join(log_lines)
            log_times = _extract_times_from_text(log_text, comment_year)
            if log_times:
                best = _pick_best_time(log_text, log_times)
                if best:
                    logger.info("从最新评论日志相关行中提取到最早时间: %s", best[0])
                    return best[0]
    # ---- 评论无时间 → 从描述(description)中提取 ----
    description = fields.get("description") or ""
    if isinstance(description, dict):
        description = _extract_adf_text(description)
    if description:
        desc_times = _extract_times_from_text(description)
        if desc_times:
            best = _pick_best_time(description, desc_times)
            if best:
                logger.info("从描述中提取到时间: %s", best[0])
                return _supplement_from_gmlogger(issue, best[0])
    # ---- 描述无时间 → 从标题(summary)中提取 ----
    summary = fields.get("summary") or ""
    if summary:
        summary_times = _extract_times_from_text(summary)
        if summary_times:
            best = _pick_best_time(summary, summary_times)
            if best:
                logger.info("从标题中提取到时间: %s", best[0])
                return _supplement_from_gmlogger(issue, best[0])
    # ---- 标题无时间 → 从自定义字段(content页面)中提取 ----
    custom_time = _extract_from_custom_fields(issue)
    if custom_time:
        return _supplement_from_gmlogger(issue, custom_time)
    # 附件文件名仅用于补充年月日（已在 _supplement_from_gmlogger 中处理），不直接作为触发时间
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
