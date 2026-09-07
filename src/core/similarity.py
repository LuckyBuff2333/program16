"""相似性比对模块：根因关键词比对 + 步骤 TF-IDF 余弦相似度"""
import json
import re

import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.config import load_config, setup_logger

logger = setup_logger("similarity")

# 常见停用词，避免干扰相似度计算
STOP_WORDS = {"的", "了", "和", "与", "是", "在", "对", "中", "后", "导致", "发现", "进行", "已经"}
# 因果连接词：用于从根因结论中分离「原因」与「现象」，关键词只从原因部分提取
CAUSE_CONNECTORS = ["导致", "引发", "造成", "引起", "致使", "使得"]


def parse_llm_json(content: str):
    """从 LLM 响应内容中提取 JSON（兼容 markdown 代码块包裹、裸 JSON 对象/数组）

    :return: 解析后的 Python 对象（list 或 dict），解析失败返回 None
    """
    if not content:
        return None
    # 去除 markdown 代码块包裹
    stripped = re.sub(r"^```(?:json)?\s*", "", content.strip())
    stripped = re.sub(r"\s*```$", "", stripped.strip())
    # 尝试直接解析
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # 提取 JSON 数组
    match = re.search(r"\[.*]", stripped, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    # 提取 JSON 对象
    match = re.search(r"\{[^}]+\}", stripped)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def tokenize(text: str) -> str:
    """中文分词并以空格拼接，过滤停用词与单字"""
    words = [w for w in jieba.cut(text) if len(w) >= 2 and w not in STOP_WORDS]
    return " ".join(words)


def cosine_of_texts(text_a: str, text_b: str) -> float:
    """计算两段文本的 TF-IDF 余弦相似度（0~1）"""
    if not text_a or not text_b:
        return 0.0
    vec_a, vec_b = tokenize(text_a), tokenize(text_b)
    if not vec_a.strip() or not vec_b.strip():
        return 0.0
    vectors = TfidfVectorizer().fit_transform([vec_a, vec_b])
    return float(cosine_similarity(vectors[0], vectors[1])[0][0])


def compare_steps(doc_steps: list, comment_steps: list) -> float:
    """步骤相似性比对：文档步骤与评论提取步骤逐条取最佳匹配后求平均

    :return: 平均相似度得分（0~1）
    """
    if not doc_steps or not comment_steps:
        logger.warning("步骤比对输入为空: 文档步骤 %d 条, 评论步骤 %d 条",
                       len(doc_steps), len(comment_steps))
        return 0.0
    scores = []
    for doc_step in doc_steps:
        best = max(cosine_of_texts(doc_step, c_step) for c_step in comment_steps)
        scores.append(best)
    score = sum(scores) / len(scores)
    logger.info("步骤相似度比对完成: 平均得分 %.3f", score)
    return score


def _extract_cause_text(text: str) -> str:
    """从根因结论中提取原因部分，去掉「导致」之后的现象描述

    例：「数据库连接池耗尽导致服务超时」→「数据库连接池耗尽」
    无因果连接词时返回全文。
    """
    for connector in CAUSE_CONNECTORS:
        idx = text.find(connector)
        if idx > 0:
            return text[:idx].strip()
    return text.strip()


def extract_cause_keywords(text: str) -> list:
    """从根因结论中提取原因部分的关键词（过滤现象、停用词与单字）"""
    cause_text = _extract_cause_text(text)
    keywords = [w for w in jieba.cut(cause_text) if len(w) >= 2 and w not in STOP_WORDS]
    return list(dict.fromkeys(keywords))


def compare_root_cause(error_cause: str, doc_text: str) -> tuple:
    """根因比对：报错原因关键词在分析文档中的命中比例

    :return: (命中比例, 命中关键词列表)
    """
    if not error_cause or not doc_text:
        return 0.0, []
    keywords = extract_cause_keywords(error_cause)
    if not keywords:
        return 0.0, []
    hits = [w for w in keywords if w in doc_text]
    ratio = len(hits) / len(keywords)
    logger.info("根因比对完成: 关键词命中 %d/%d, 比例 %.2f", len(hits), len(keywords), ratio)
    return ratio, hits


def judge_result(root_cause_ratio: float, step_score: float) -> tuple:
    """根据配置阈值判定根因与步骤是否一致，返回 (根因一致, 步骤一致)"""
    cfg = load_config()["similarity"]
    cause_ok = root_cause_ratio >= cfg.get("root_cause_hit_ratio", 0.5)
    step_ok = step_score >= cfg.get("threshold", 0.7)
    return cause_ok, step_ok


def llm_semantic_judge(text_a: str, text_b: str, aspect: str = "根因分析") -> dict:
    """判定两段文本的语义相似性（基于 TF-IDF 余弦相似度）

    :param text_a: 文本A（已入库数据）
    :param text_b: 文本B（抽查重新分析数据）
    :param aspect: 判定维度（根因分析/分析步骤/综合分析）
    :return: {"similar": bool, "score": float 0~1}
    """
    if not text_a or not text_b:
        return {"similar": False, "score": 0.0}
    score = cosine_of_texts(text_a, text_b)
    threshold = load_config().get("similarity", {}).get("threshold", 0.7)
    return {"similar": score >= threshold, "score": round(score, 3)}
