"""分析文档生成模块：提取报告内容生成 Markdown 文档（按日期分文件夹，bugid 命名）"""
import os
import re

from src.config import get_day_dir, get_path, setup_logger

logger = setup_logger("doc_gen")

# 匹配文档中带序号的步骤行，如 "1. 查看服务错误日志"
STEP_LINE_PATTERN = re.compile(r"^\s*\d+[.、)]\s*(.+)$")
# 匹配 AI 报告中的证据标题行，如 "**证据 1：展开→收起→再展开操作序列完整发生**"
EVIDENCE_PATTERN = re.compile(r"^\*\*证据\s*\d+[：:]\s*(.+?)\*\*$")


def save_document(bugid: str, report_text: str, date_str: str = None) -> str:
    """将分析报告保存为文档：docs/YYYY-MM-DD/bugid.md

    :param bugid: Jira bugid，用作文件名
    :param report_text: 报告内容
    :param date_str: 日期字符串，默认当天
    :return: 生成的文档绝对路径
    """
    day_dir = get_day_dir("doc_dir", date_str)
    doc_path = os.path.join(day_dir, f"{bugid}.md")
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    logger.info("分析文档已生成: %s", doc_path)
    return doc_path


def parse_doc_steps(report_text: str) -> list:
    """从报告文本中提取分析步骤行

    兼容两种格式：
    - 标准格式："1. 查看服务错误日志"（带序号行）
    - AI 报告格式："**证据 N：xxx**"（证据标题行，位于 ② 关键证据段落中）
    优先提取证据段落（分析依据），无证据时回退序号行（修复建议）。
    """
    numbered_steps = []
    evidence_steps = []
    in_evidence_section = False
    for line in report_text.splitlines():
        stripped = line.strip()
        # 检测是否进入 ② 关键证据段落
        if stripped.startswith("#") and ("证据" in stripped or "关键证据" in stripped):
            in_evidence_section = True
            continue
        # 离开证据段落（遇到下一个同级标题）
        if in_evidence_section and stripped.startswith("#") and "证据" not in stripped:
            in_evidence_section = False
            continue
        # 提取证据标题
        if in_evidence_section:
            ev_match = EVIDENCE_PATTERN.match(stripped)
            if ev_match:
                evidence_steps.append(ev_match.group(1).strip())
                continue
        # 提取带序号的步骤行
        matched = STEP_LINE_PATTERN.match(line)
        if matched:
            numbered_steps.append(matched.group(1).strip())
    # 优先使用证据步骤，无证据时回退序号步骤
    steps = evidence_steps if evidence_steps else numbered_steps
    logger.info("文档步骤提取完成: 共 %d 条（证据 %d / 序号 %d）", len(steps), len(evidence_steps), len(numbered_steps))
    return steps


def parse_conclusion(report_text: str) -> str:
    """从报告文本中提取根因结论段落

    兼容两种标题格式：
    - 标准格式：## 根因结论
    - AI 报告格式：### ④ 根因分析与关键发现 / ### 根因分析
    """
    lines = report_text.splitlines()
    conclusion = []
    capturing = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if capturing:
                break
            # 兼容多种根因标题格式
            capturing = ("根因结论" in stripped or "根因分析" in stripped or
                         ("关键发现" in stripped and "根因" in stripped))
            continue
        if capturing and stripped:
            # 清理 markdown 列表标记、emoji、加粗、链接
            cleaned = re.sub(r"^[-*•]\s*", "", stripped)  # 去掉 -/• 列表前缀
            cleaned = re.sub(r"[🔴🟡🔵🟢🟠🟣🟤🟥🟧🟨🟩🟦🟪🟫⚪⚫]\s*", "", cleaned)  # 去掉彩色圆形/方形 emoji
            cleaned = re.sub(r"\*\*", "", cleaned)  # 去掉加粗
            cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)  # [text](url) → text
            cleaned = re.sub(r"\(L\d+\)", "", cleaned)  # 去掉行号引用 (L1366395)
            cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)  # *text* → text (markdown 斜体)
            cleaned = cleaned.strip()
            if cleaned:
                conclusion.append(cleaned)
    return "\n".join(conclusion)


def read_document(doc_path: str) -> str:
    """读取已生成的分析文档内容，文件不存在时抛出明确错误"""
    if not os.path.exists(doc_path):
        raise FileNotFoundError(f"分析文档不存在: {doc_path}")
    with open(doc_path, "r", encoding="utf-8") as f:
        return f.read()


def find_latest_document(bugid: str) -> str:
    """在文档目录中查找指定 bugid 最新日期的分析文档

    支持查找日期目录下的直接文件和 True/False 分类子目录。
    :return: 文档绝对路径，未找到时抛出 FileNotFoundError
    """
    doc_dir = get_path("doc_dir")
    # 日期子目录按名称倒序（YYYY-MM-DD 字典序即时间序），取最新一份
    for day in sorted(os.listdir(doc_dir), reverse=True):
        day_path = os.path.join(doc_dir, day)
        if not os.path.isdir(day_path):
            continue
        # 直接在日期目录下查找
        candidate = os.path.join(day_path, f"{bugid}.md")
        if os.path.exists(candidate):
            return candidate
        # 在 True/False 分类子目录下查找
        for sub in ("True", "False"):
            sub_candidate = os.path.join(day_path, sub, f"{bugid}.md")
            if os.path.exists(sub_candidate):
                return sub_candidate
    raise FileNotFoundError(f"未找到 bugid={bugid} 的分析文档，请先执行 analyze 生成")
