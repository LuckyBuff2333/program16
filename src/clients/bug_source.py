"""Bug 单数据源抽象层：统一从 API 接口或上传文件中加载 bug 单数据

优先级：上传文件数据 > Jira API 接口（含 mock 模式下的本地测试数据表）
返回标准化结构 {bugid, root_cause, comments, trigger_time}，供对比模块直接使用。
"""
import csv
import io
import os
import re

from src.clients import jira_client
from src.clients.ai_log_client import _load_testdata_row
from src.config import load_config, setup_logger

logger = setup_logger("bug_source")

# 上传文件列名到标准字段的映射：支持中英文及常见别名
FIELD_ALIASES = {
    "bugid": ["bugid", "bug_id", "bug号", "bug编号", "jira号"],
    "root_cause": ["根因分析", "根本原因", "根因", "root_cause", "原因分析"],
    "comments": ["评论", "评论内容", "comments", "评论列表"],
    "trigger_time": ["问题触发时间", "触发时间", "trigger_time", "发生时间"],
}


def _match_field(csv_columns: list, standard_name: str) -> str:
    """从 CSV 列名中模糊匹配标准字段，返回实际列名；未命中返回空字符串"""
    aliases = FIELD_ALIASES.get(standard_name, [])
    for col in csv_columns:
        col_lower = col.strip().lower()
        if col_lower in [a.lower() for a in aliases]:
            return col
    return ""


def load_bug_data(bugid: str, trigger_time: str = None, uploaded_rows: list = None) -> dict:
    """加载指定 bugid 的 bug 单数据，返回标准化结构

    优先级：上传文件数据 > Jira API 接口（mock 模式下走本地测试数据表）
    :param bugid: bug 编号
    :param trigger_time: 可选触发时间
    :param uploaded_rows: 上传文件解析后的行列表（已标准化字段名），为空时走 API
    :return: {"bugid", "root_cause", "comments", "trigger_time"}
    """
    # 优先从上传文件数据中查找
    if uploaded_rows:
        for row in uploaded_rows:
            if row.get("bugid") == bugid:
                comments = row.get("comments", "")
                if isinstance(comments, str):
                    comments = [c.strip() for c in comments.split("|") if c.strip()]
                result = {
                    "bugid": bugid,
                    "root_cause": row.get("root_cause", ""),
                    "comments": comments,
                    "trigger_time": row.get("trigger_time") or trigger_time,
                }
                logger.info("bugid=%s 从上传文件中加载成功", bugid)
                return result
        logger.warning("bugid=%s 在上传文件中未找到，回退到 API 接口", bugid)

    # 回退到 Jira API 接口（mock 模式下走本地测试数据表）
    issue = jira_client.fetch_issue(bugid)
    error_cause = jira_client.extract_error_cause(issue)
    comments = jira_client.extract_comments(issue)
    # 从 description 中提取纯根因：去掉「线上服务报错，原因：」前缀
    root_cause = _clean_root_cause(error_cause)
    # 如果 API 未返回根因，尝试从测试数据表补充
    if not root_cause:
        testdata_row = _load_testdata_row(bugid)
        if testdata_row:
            root_cause = testdata_row.get("根因分析", "")
    logger.info("bugid=%s 从 API 接口加载成功", bugid)
    return {
        "bugid": bugid,
        "root_cause": root_cause,
        "comments": comments,
        "trigger_time": trigger_time,
    }


def _clean_root_cause(description: str) -> str:
    """清洗 description 中的前缀，提取纯根因文本

    例：「线上服务报错，原因：数据库连接池耗尽」→「数据库连接池耗尽」
    """
    if not description:
        return ""
    # 去掉常见前缀模式
    cleaned = re.sub(r"^线上服务报错[，,]\s*原因[：:]\s*", "", description.strip())
    return cleaned.strip()


def parse_uploaded_file(file_content: bytes, filename: str) -> list:
    """解析上传的 CSV/Excel 文件为标准化行列表

    :param file_content: 文件二进制内容
    :param filename: 文件名（用于判断格式）
    :return: [{"bugid": ..., "root_cause": ..., "comments": ..., "trigger_time": ...}, ...]
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".xlsx", ".xls"):
        rows = _parse_excel(file_content)
    else:
        rows = _parse_csv(file_content)
    if not rows:
        return []
    # 字段映射：将实际列名映射为标准字段名
    columns = list(rows[0].keys())
    field_map = {}
    for standard in ["bugid", "root_cause", "comments", "trigger_time"]:
        matched = _match_field(columns, standard)
        if matched:
            field_map[matched] = standard
    if "bugid" not in field_map.values():
        logger.warning("上传文件中未找到 bugid 列，可用列: %s", columns)
        return []
    # 标准化输出
    result = []
    for row in rows:
        std_row = {}
        for col, standard in field_map.items():
            std_row[standard] = (row.get(col) or "").strip() if isinstance(row.get(col), str) else str(row.get(col) or "")
        if std_row.get("bugid"):
            result.append(std_row)
    logger.info("上传文件解析完成: %d 行，字段映射 %s", len(result), field_map)
    return result


def _parse_csv(content: bytes) -> list:
    """解析 CSV 文件内容为字典列表"""
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _parse_excel(content: bytes) -> list:
    """解析 Excel 文件内容为字典列表"""
    try:
        import pandas as pd
        df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
        return df.fillna("").astype(str).to_dict(orient="records")
    except ImportError:
        logger.error("解析 Excel 文件需要安装 openpyxl，请执行 pip install openpyxl")
        return []
