"""评论 Agent 过滤模块：从 Jira 评论区评论中提取日志分析步骤信息

支持双模式：规则 + 关键词过滤（默认）、LLM Agent 语义过滤（配置启用时激活）。
LLM Agent 模式可识别隐含分析意图，有效评论召回率显著提升。
"""
import json
import os
import re

from src.config import load_config, setup_logger
from src.core import semantic as semantic_module
from src.core import similarity

logger = setup_logger("filter")

# 判定评论与日志分析相关的关键词（仅多字关键词，避免单字误判）
ANALYSIS_KEYWORDS = ["日志", "排查步骤", "根因", "定位", "分析", "查询", "测试", "打印", "关闭", "确认", "因为", "log", "根据"]
# 无效评论关键词：含此类词的评论（如转发类、致谢类、协调类）判定为无效，但同时含有效关键词时以有效为准
INVALID_KEYWORDS = ["转给", "辛苦了", "感谢大家", "感谢各位"]
# 有效评论不足该数量时，自动将最后几条评论补充为有效评论
MIN_VALID_COMMENTS = 3
# 有效评论为 0 时，自动提取最后 2 条评论作为兜底
FALLBACK_LAST_COUNT = 2
# 步骤文本的分隔符：中英文分号、句号、换行
STEP_SPLIT_PATTERN = re.compile(r"[；;。\n]+")
# 步骤前的引导词前缀，如 "日志分析步骤："
PREFIX_PATTERN = re.compile(r"^(日志分析步骤|分析步骤|排查步骤|日志分析)\s*[:：]")
# LLM 过滤系统提示词（已移除千问-flash，保留常量占位）


def _is_analysis_comment(comment: str) -> bool:
    """判断评论是否为日志分析相关内容

    规则：含无效关键词（如"转给"）判定为无效；若同时含有效关键词则以有效为准
    """
    has_valid = any(keyword in comment for keyword in ANALYSIS_KEYWORDS)
    if any(keyword in comment for keyword in INVALID_KEYWORDS) and not has_valid:
        return False
    return has_valid


def _keyword_hit_ratio(text: str, keywords: list) -> float:
    """计算根因关键词在文本中的命中比例"""
    if not keywords:
        return 0.0
    hits = sum(1 for k in keywords if k in text)
    return hits / len(keywords)


def truncate_comments_by_conclusion(comments: list, conclusion: str, threshold: float = None) -> list:
    """按顺序遍历评论，到达根因相似结论后截断，后续评论不再参与步骤对比

    截断判定策略：Diana LLM 优先，关键词/语义兜底。
    1. Diana LLM（优先）：内网大模型判断评论是否与根因相关；
    2. 关键词命中（兜底）：Diana 不可用时，根因关键词命中比例 >= root_cause_hit_ratio；
    3. 语义相似度（兜底）：仅当无关键词时，用语义相似度 >= threshold 判定。
    对比区间为「开头 → 首次到达结论的评论（含该条）」；未到达时全部评论参与对比。

    :param comments: 按时间排序的原始评论列表
    :param conclusion: 分析报告的根因结论，作为截断判定基准
    :param threshold: 语义相似度阈值，默认取配置 similarity.threshold
    :return: 截断后的评论列表
    """
    if not conclusion:
        return comments
    cfg = load_config()["similarity"]
    if threshold is None:
        threshold = cfg.get("threshold", 0.7)
    hit_threshold = cfg.get("root_cause_hit_ratio", 0.5)
    # 预检 Diana 可用性（一次探测，避免每条评论都探测）
    from src.clients import diana_client
    diana_available = diana_client.is_diana_mode() and diana_client.check_connectivity()
    if diana_available:
        logger.info("评论截断: 使用 Diana LLM 判定")
    # 提取根因关键词（只取原因部分，过滤现象、停用词与单字），用于关键词命中兜底
    keywords = similarity.extract_cause_keywords(conclusion)
    for idx, comment in enumerate(comments):
        comment = (comment or "").strip()
        if not comment:
            continue
        # Diana LLM 优先：内网大模型判断评论是否与根因相关
        if diana_available:
            try:
                if diana_client.llm_is_cause_related(comment, conclusion):
                    logger.info("第 %d 条评论 Diana LLM 判定相关，截断后续 %d 条评论不参与对比",
                                idx + 1, len(comments) - idx - 1)
                    return comments[:idx + 1]
                continue  # Diana 已判定不相关，无需走关键词兜底
            except Exception as e:
                logger.warning("Diana LLM 评论判定失败，回退关键词: %s", e)
                diana_available = False
        # 关键词兜底：命中比例达标即截断
        hit_ratio = _keyword_hit_ratio(comment, keywords)
        if keywords and hit_ratio >= hit_threshold:
            logger.info("第 %d 条评论关键词命中 %.2f（%d/%d）达标，截断后续 %d 条评论不参与对比",
                        idx + 1, hit_ratio, int(round(hit_ratio * len(keywords))), len(keywords),
                        len(comments) - idx - 1)
            return comments[:idx + 1]
        # 语义兜底：无关键词时用语义相似度判定
        if not keywords:
            sem_score = semantic_module.semantic_similarity(comment, conclusion)
            if sem_score >= threshold:
                logger.info("第 %d 条评论语义相似度 %.3f 达标（无关键词，语义兜底），截断后续 %d 条评论不参与对比",
                            idx + 1, sem_score, len(comments) - idx - 1)
                return comments[:idx + 1]
    return comments


def _split_comment_steps(comment: str) -> list:
    """将单条评论去除引导词前缀后按分隔符拆分为步骤片段（过滤过短片段）"""
    cleaned = PREFIX_PATTERN.sub("", _agent_filter(comment)).strip()
    return [p.strip() for p in STEP_SPLIT_PATTERN.split(cleaned) if len(p.strip()) >= 6]


def _agent_filter(comment: str) -> str:
    """Agent 过滤：当前直接返回原文"""
    return comment




# 规则过滤中的非技术内容模式（mock 模式下替代 LLM 语义过滤）
_RULE_CLEANUP_PATTERNS = [
    # 协调请求："请XX确认/处理/跟进/支持分析"
    re.compile(r"请[\u4e00-\u9fa5]{1,5}(确认|处理|跟进|协助排查|支持分析|关注)"),
    # 通知/同步类："已同步给/已通知/已添加附件/已上传/已转交/已转发 相关同学/团队"
    re.compile(r"已(?:同步给|通知|添加附件|上传|转交|转发)[\u4e00-\u9fa5]{0,10}"),
    # 附件引用
    re.compile(r"(?:附件|Attachment|attachment)\s*[:：]?\s*[\u4e00-\u9fa5a-zA-Z0-9._\-]+"),
    # 致谢/慰问
    re.compile(r"(?:辛苦(?:大家|了|各位)?|感谢(?:大家|各位|支持)?|处理得[\u4e00-\u9fa5]{1,5})"),
    # 安排/休息
    re.compile(r"(?:大家先休息|明天(?:继续)?跟进|先休息)"),
    # 纯沟通确认
    re.compile(r"^(?:收到[，,。]|好的[，,。]|辛苦了[，,。]|问题已解决[，,。]|已解决[，,。])"),
]


def _mock_batch_refine(comments: list) -> list:
    """规则模式评论精炼：去除协调性/致谢/附件引用等非技术内容（mock 模式下替代 LLM）"""
    refined = []
    for c in comments:
        cleaned = c.strip()
        if len(cleaned) < 6:
            continue
        # 逐条去除非技术内容短语
        for pattern in _RULE_CLEANUP_PATTERNS:
            cleaned = pattern.sub("", cleaned)
        # 去除前后空白和残留分隔符
        cleaned = re.sub(r"^[，,。：:；;\s]+|[，,。：:；;\s]+$", "", cleaned).strip()
        if not cleaned or len(cleaned) < 4:
            logger.info("规则过滤去除非技术评论: %s", c[:40])
            continue
        refined.append(cleaned)
    logger.info("规则精炼完成: %d 条 → %d 条", len(comments), len(refined))
    return refined


def extract_analysis_steps(comments: list) -> tuple:
    """从评论列表中提取日志分析步骤

    :param comments: 评论区原始评论列表
    :return: (分析步骤文本列表, 有效评论列表) 元组
    """
    steps = []
    valid_comments = []
    for comment in comments:
        comment = (comment or "").strip()
        if not comment or not _is_analysis_comment(comment):
            continue
        valid_comments.append(comment)
        steps.extend(_split_comment_steps(comment))

    # 规则1：有效评论为 0 时，自动提取最后 2 条评论作为兜底
    if not valid_comments:
        for comment in reversed(comments[-FALLBACK_LAST_COUNT:]):
            comment = (comment or "").strip()
            if not comment:
                continue
            if any(keyword in comment for keyword in INVALID_KEYWORDS):
                continue
            steps.extend(_split_comment_steps(comment))
            valid_comments.append(comment)
        if steps:
            logger.info("有效评论为 0，已从最后 %d 条评论中提取 %d 条步骤", FALLBACK_LAST_COUNT, len(steps))
        return steps, valid_comments
    # 规则2：有效评论不足 MIN_VALID_COMMENTS 条时，自动补充最后几条评论为有效
    if len(valid_comments) < MIN_VALID_COMMENTS:
        added = 0
        for comment in comments[-MIN_VALID_COMMENTS:]:
            comment = (comment or "").strip()
            if not comment or comment in valid_comments:
                continue
            if any(keyword in comment for keyword in INVALID_KEYWORDS):
                continue
            steps.extend(_split_comment_steps(comment))
            valid_comments.append(comment)
            added += 1
        if added:
            logger.info("有效评论不足 %d 条，已从最后几条评论中补充 %d 条", MIN_VALID_COMMENTS, added)

    # 评论精炼：规则过滤去除协调/致谢/附件内容
    valid_comments = _mock_batch_refine(valid_comments)
    # 精炼后重新提取步骤（内容可能被改写/合并/清理）
    steps = []
    for comment in valid_comments:
        steps.extend(_split_comment_steps(comment))

    logger.info("评论过滤完成: %d 条评论提取出 %d 条分析步骤，有效评论 %d 条", len(comments), len(steps), len(valid_comments))
    return steps, valid_comments


def _rule_summarize_comment(comment: str) -> dict:
    """规则模式评论简化：去除非技术内容，保留分析要点和日志片段"""
    cleaned = comment.strip()
    # 去除协调/致谢类前缀
    for pattern in _RULE_CLEANUP_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"^[，,。：:；;\s]+|[，,。：:；;\s]+$", "", cleaned).strip()
    if not cleaned or len(cleaned) < 4:
        return {"summary": comment[:50], "evidence": []}
    # 提取日志证据：包含时间戳、ERROR/WARN、异常堆栈的行
    evidence = []
    log_pattern = re.compile(r'(?:\d{4}[-/]\d{2}[-/]\d{2}|ERROR|WARN|Exception|Traceback|at\s+\w+\.\w+)')
    for line in cleaned.splitlines():
        if log_pattern.search(line):
            evidence.append(line.strip())
    # 简化结论：取去除日志后的剩余文本，截取前100字
    text_without_logs = log_pattern.sub("", cleaned).strip()
    summary = text_without_logs[:100] if text_without_logs else cleaned[:100]
    return {"summary": summary, "action": summary[:15], "result": summary[:20], "evidence": evidence}


def summarize_comments(comments: list) -> list:
    """对截断后的评论列表进行简化（Diana LLM 优先，规则兜底）

    每条评论生成 {comment, summary, evidence} 结构。
    :param comments: 截断后的评论列表
    :return: 简化后的评论字典列表
    """
    # 预检 Diana 可用性
    from src.clients import diana_client
    diana_available = diana_client.is_diana_mode() and diana_client.check_connectivity()
    if diana_available:
        logger.info("评论简化: 使用 Diana LLM")
    results = []
    for i, comment in enumerate(comments):
        comment = (comment or "").strip()
        if not comment:
            continue
        # Diana LLM 优先：内网大模型简化+证据提取
        simplified = None
        if diana_available:
            try:
                simplified = diana_client.llm_summarize_comment(comment)
            except Exception as e:
                logger.warning("Diana LLM 评论简化失败，回退规则: %s", e)
                diana_available = False
        # 规则兜底
        if simplified is None:
            simplified = _rule_summarize_comment(comment)
        results.append({
            "index": i + 1,
            "comment": comment,
            "action": simplified.get("action", simplified.get("summary", "")),
            "result": simplified.get("result", ""),
            "summary": simplified["summary"],
            "evidence": simplified["evidence"],
        })
    logger.info("评论简化完成: %d 条 → %d 条有效简化", len(comments), len(results))
    return results


def combine_comment_conclusions(summaries: list, ai_conclusion: str = "") -> str:
    """将多条评论分析结论合并为整体核心语义，融入 AI 日志分析结论（Diana LLM 优先，规则兜底）

    :param summaries: summarize_comments 返回的简化结果列表
    :param ai_conclusion: AI 日志分析报告的根因结论（可选，融入核心语义）
    :return: 核心语义分析段落（用于文档 核心语义 章节）
    """
    if not summaries:
        return ai_conclusion or ""
    # Diana LLM 优先（传入 AI 报告结论以融入分析）
    from src.clients import diana_client
    if diana_client.is_diana_mode() and diana_client.check_connectivity():
        try:
            conclusion = diana_client.llm_combine_conclusions(summaries, ai_conclusion=ai_conclusion)
            if conclusion:
                return conclusion
        except Exception as e:
            logger.warning("Diana LLM 合并结论失败，回退规则: %s", e)
    # 规则兜底：AI结论 + 最后两条有效排查动作拼接
    valid = [(s.get("action", "") or s.get("summary", "")).strip() for s in summaries if len((s.get("action", "") or s.get("summary", "")).strip()) >= 4]
    parts = []
    if ai_conclusion:
        parts.append(ai_conclusion)
    parts.extend(valid[-2:])
    return "。".join(parts) + "。" if parts else ""


def _truncate_to_one_sentence(text: str, max_len: int = 30) -> str:
    """截取文本为 1-2 句，优先按标点截断，超长时硬截断加省略号

    :param text: 原始文本
    :param max_len: 最大字符数，超过时按句截断
    """
    if not text:
        return ""
    import re
    # 提取前两句（按句号/感叹号/问号分割）
    sentences = re.findall(r'[^\u3002\uff01\uff1f]+[\u3002\uff01\uff1f]', text)
    if not sentences:
        # 无句末标点，硬截断
        return text[:max_len] + "..." if len(text) > max_len else text
    # 第一句必取，第二句仅在总长度不超 max_len 时追加
    result = sentences[0]
    if len(sentences) > 1 and len(result) + len(sentences[1]) <= max_len:
        result += sentences[1]
    if len(result) > max_len:
        result = result[:max_len] + "..."
    return result


def _smart_truncate(text: str, max_len: int) -> str:
    """智能截断文本：优先在自然断点截断，避免截断在词/时间戳/数字中间

    断点优先级：逗号 > 分号 > 空格 > 但/且/而等连词
    :param text: 原始文本
    :param max_len: 最大长度
    :return: 截断后的文本（不含省略号）
    """
    if len(text) <= max_len:
        return text
    # 在截断点附近查找自然断点（前 80% 范围内）
    search_start = max(max_len // 2, 6)  # 至少保留一半内容
    segment = text[search_start:max_len]
    # 按优先级查找断点：逗号 > 顿号 > 分号 > 但/且/而/而/因
    for sep in ('\uff0c', '\u3001', '\uff1b', ' ', '\u4f46', '\u4e14', '\u800c', '\u56e0', '\u5e76'):
        pos = segment.rfind(sep)
        if pos >= 0:
            return text[:search_start + pos].strip()
    # 无自然断点时回退到硬截断
    return text[:max(0, max_len - 3)] + "..."


def _extract_core_summary(text: str, max_len: int = 60) -> str:
    """从核心语义中提取精炼摘要作为表格字段

    提取策略：优先找结论性语句（含根因/故障/导致等关键词），其次取首句主句。
    :param text: 核心语义文本
    :param max_len: 最大字符数
    :return: 精炼摘要文本
    """
    if not text:
        return ""
    import re
    # 复用通用表格清理函数去掉 emoji/列表/链接等格式符号
    clean = _clean_table_text(text)
    # 按句号分割所有句子
    sentences = re.findall(r'[^\u3002\uff01\uff1f]+[\u3002\uff01\uff1f]', clean)
    # 策略1：找包含结论关键词的最短句子（优先于首句）
    _CONCLUSION_KW = ("根因", "故障", "导致", "原因", "结论", "问题在于", "是")
    if sentences:
        best = ""
        for sent in sentences:
            sent = sent.strip()
            if len(sent) > max_len:
                continue
            if len(sent) < 6:
                continue
            if any(kw in sent for kw in _CONCLUSION_KW):
                if not best or len(sent) < len(best):
                    best = sent
        if best:
            return best
    # 策略2：取首句的冒号前主句（主句≥8字时）
    if sentences:
        first_sent = sentences[0].strip()
        colon_pos = first_sent.find('：')
        if colon_pos < 0:
            colon_pos = first_sent.find(':')
        if 8 <= colon_pos <= max_len:
            return first_sent[:colon_pos].strip()
        if len(first_sent) <= max_len:
            return first_sent
        # 智能截断：优先在自然断点截断，避免截断在词/时间戳中间
        truncated = _smart_truncate(first_sent, max_len)
        return truncated
    # 策略3：无句号时，按换行/分号分割取首条
    parts = re.split(r'[\n；;]', clean)
    first_point = parts[0].strip()
    if len(first_point) <= max_len:
        colon_pos = first_point.find('：')
        if colon_pos < 0:
            colon_pos = first_point.find(':')
        if 8 <= colon_pos <= max_len:
            return first_point[:colon_pos].strip()
        return first_point
    colon_pos = first_point.find('：')
    if colon_pos < 0:
        colon_pos = first_point.find(':')
    if 0 < colon_pos <= max_len:
        return first_point[:colon_pos].strip()
    # 智能截断
    truncated = _smart_truncate(first_point, max_len)
    return truncated


def _clean_table_text(text: str) -> str:
    """清理写入多维表格的文本：去掉 emoji、markdown 表格/列表/链接等格式符号

    :param text: 原始文本
    :return: 纯文本内容
    """
    if not text:
        return ""
    import re
    # 去掉彩色 emoji
    clean = re.sub(r'[🔴🟡🔵🟢🟠🟣🟤🟥🟧🟨🟩🟦🟪🟫⚪⚫✅❌⚠️🔥💡📌📍🎯🚀💬📝🔍🔎]\s*', '', text)
    # 去掉 markdown 表格行（整行都是 |---|---| 的分隔行）
    clean = re.sub(r'^\s*\|?\s*[-:]+\s*(\|\s*[-:]+\s*)+\|?\s*$', '', clean, flags=re.MULTILINE)
    # 去掉行首列表标记 - * •
    clean = re.sub(r'^\s*[-*•]\s+', '', clean, flags=re.MULTILINE)
    # 去掉 markdown 表格竖线 | （替换为空格，避免文字粘连）
    clean = clean.replace('|', ' ')
    # 去掉加粗 **text** 和斜体 *text*
    clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean)
    clean = re.sub(r'\*([^*]+)\*', r'\1', clean)
    # 链接 [text](url) → text
    clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean)
    # 行号引用 (L123456)
    clean = re.sub(r'\(L\d+\)', '', clean)
    # 合并多余空格，去掉首尾空白
    clean = re.sub(r'  +', ' ', clean).strip()
    # 去掉首尾残留的换行（表格单元格应为单行）
    clean = re.sub(r'\s*\n+\s*', ' ', clean).strip()
    return clean


# AI评论分析侧重点策略定义
COMMENT_ANALYSIS_STRATEGIES = {
    "log_focus": {
        "label": "偏日志分析",
        "instruction": "重点关注日志断层、错误码、异常堆栈和进程状态变化，从日志证据链角度分析"
    },
    "action_focus": {
        "label": "偏排查动作",
        "instruction": "重点关注排查步骤的时序、操作方法和排查方向变化，从排查流程角度分析"
    },
    "conclusion_focus": {
        "label": "偏结论判定",
        "instruction": "重点关注最终结论、问题定位状态和责任归属判定，从问题定性角度分析"
    },
    "impact_focus": {
        "label": "偏影响评估",
        "instruction": "重点关注问题对用户的影响范围、严重程度和修复优先级，从影响面角度分析"
    },
}


def generate_comment_analysis(summaries: list, ai_conclusion: str = "",
                              style_instruction: str = "") -> str:
    """生成 AI评论分析：对全部评论进行整体分析并与 AI 日志分析对比

    Diana LLM 优先，规则兆底。
    :param summaries: 每条评论的简化结果 [{"summary": str, "evidence": list}]
    :param ai_conclusion: AI 日志分析报告结论
    :param style_instruction: 分析侧重点指令（如“偏日志分析”），为空时从配置读取
    :return: AI评论分析文本，失败时返回空字符串
    """
    if not summaries and not ai_conclusion:
        return ""
    # 自动从配置读取风格偏好（如果调用方未显式传入）
    if not style_instruction:
        try:
            from src.config import load_config
            cfg = load_config().get("comment_analysis", {})
            style_instruction = cfg.get("style_keywords", "")
        except Exception:
            pass
    # 构建评论摘要文本（包含排查动作、结果和日志证据）
    items = []
    for i, s in enumerate(summaries):
        action = s.get("action", "")
        res = s.get("result", "")
        summary = s.get("summary", "")
        evidence = s.get("evidence", [])
        desc = f"{action} → {res}" if action and res else (action or summary)
        if desc:
            items.append(f"评论{i+1}: {desc}")
            # 加入日志证据（每条评论最多取3条关键证据）
            for ev in (evidence or [])[:3]:
                ev_text = str(ev).strip()[:100]
                if ev_text:
                    items.append(f"  证据: {ev_text}")
    comments_text = "\n".join(items)[:1500]
    # Diana LLM 优先
    from src.clients import diana_client
    if diana_client.is_diana_mode() and diana_client.check_connectivity():
        try:
            ai_hint = f"\n\nAI日志分析结论：\n{ai_conclusion}" if ai_conclusion else ""
            prompt = (
                f"对以下 Jira 评论进行整体分析，生成结构化的 bug 排查报告。\n"
                f"要求输出以下 3 个段落，每段用标题标记：\n\n"
                f"### 问题现象\n用1-2句话描述 bug 的现象表现\n\n"
                f"### 排查过程\n按评论时序，以表格形式列出每步排查动作和结果：\n"
                f"| 步骤 | 排查动作 | 结果 | 关键证据 |\n"
                f"每行不超过30字，证据引用具体日志或评论内容\n\n"
                f"### 排查结论\n基于排查过程给出：\n"
                f"- 已确认的事实（引用具体证据）\n"
                f"- 尚未确认需进一步排查的方向\n"
                f"- 与AI日志分析结论的一致点和差异点（各1-2句）\n\n"
                f"重要：直接输出内容，禁止输出开场白或引导语。引用评论中的具体日志作为证据。\n"
            )
            # 注入分析侧重点指令
            if style_instruction:
                prompt += f"\n分析侧重点：{style_instruction}\n"
            prompt += f"\n评论摘要及日志证据：\n{comments_text}{ai_hint}"
            result = diana_client._llm_chat(prompt, max_tokens=700, timeout=60)
            if result:
                return result.strip()
        except Exception as e:
            logger.warning("Diana LLM 生成评论分析失败，回退规则: %s", e)
    # 规则兜底：结构化排查报告格式
    parts = ["### 问题现象\n", "（待人工补充）\n"]
    parts.append("\n### 排查过程\n")
    parts.append("| 步骤 | 排查动作 | 结果 | 关键证据 |")
    parts.append("| --- | --- | --- | --- |")
    for i, s in enumerate(summaries[:8]):
        action = s.get("action", s.get("summary", ""))[:15]
        res = s.get("result", "")[:20]
        ev_brief = ""
        if s.get("evidence"):
            ev_brief = str(s["evidence"][0]).strip()[:30]
        parts.append(f"| {i+1} | {action} | {res} | {ev_brief} |")
    parts.append("\n### 排查结论\n")
    if ai_conclusion:
        parts.append(f"AI日志分析指出：{ai_conclusion[:80]}")
    return "\n".join(parts)


def generate_comment_summary_doc(bugid: str, summaries: list, overall_conclusion: str = "",
                                 ai_conclusion: str = "", comment_analysis: str = "",
                                 date_str: str = None) -> str:
    """将评论简化结果生成 Markdown 文档并存入 docs/日期/ 目录

    格式：排查结论 + 排查过程分析 + 时序排查详情
    :param bugid: bug 编号
    :param summaries: summarize_comments 返回的简化结果列表
    :param overall_conclusion: 排查结论
    :param ai_conclusion: AI 日志分析报告结论
    :param comment_analysis: 排查过程分析文本
    :param date_str: 日期字符串，默认当天
    :return: 生成的文档路径
    """
    from src.config import get_day_dir

    day_dir = get_day_dir("doc_dir", date_str)
    doc_path = os.path.join(day_dir, f"{bugid}_comments.md")

    lines = [f"# {bugid} 评论分析总结\n"]
    # 排查结论（原“核心语义”）
    if overall_conclusion:
        lines.append("## 排查结论\n")
        lines.append(overall_conclusion)
        # 添加精炼摘要行
        summary_line = _extract_core_summary(overall_conclusion, max_len=60)
        if summary_line and summary_line != overall_conclusion:
            lines.append(f"\n\n**排查摘要**：{summary_line}")
        lines.append("")
    # 排查过程分析（原“AI评论分析”）
    if comment_analysis:
        lines.append("\n## 排查过程分析\n")
        lines.append(comment_analysis)
        lines.append("")
    # 时序排查详情（原“时序排查流程”）
    if summaries or ai_conclusion:
        lines.append("\n## 时序排查详情\n")
        # AI 日志分析结论作为第一步
        if ai_conclusion:
            lines.append("### AI日志分析\n")
            for ai_line in ai_conclusion.splitlines():
                ai_line = ai_line.strip()
                if ai_line:
                    lines.append(f"- {ai_line}")
            lines.append("")
        # 评论排查步骤
        for item in summaries:
            lines.append(f"### 评论 {item['index']}\n")
            action = item.get('action', item.get('summary', ''))
            lines.append(f"**排查动作**: {action}\n")
            result = item.get('result', '')
            if result:
                lines.append(f"**排查结果**: {result}\n")
            if item["evidence"]:
                lines.append("\n**日志证据**:\n")
                lines.append("```")
                for ev in item["evidence"]:
                    lines.append(ev)
                lines.append("```\n")
            lines.append("")

    with open(doc_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info("评论总结文档已生成: %s", doc_path)
    return doc_path
