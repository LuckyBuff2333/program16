"""语义相似度模块：Diana LLM 优先，词向量模型（BAAI/bge-small-zh-v1.5）兜底

调用链：Diana LLM（prompt 方式）→ 句向量模型 → TF-IDF 词面相似度
LLM 适合精细判断，句向量适合批量，TF-IDF 为最终兜底。
"""
import os

from src.config import PROJECT_ROOT, load_config, setup_logger

logger = setup_logger("semantic")

# 模型单例缓存，避免重复加载
_MODEL = None
_MODEL_FAILED = False


def _get_model():
    """懒加载中文句向量模型，加载失败时记录状态并返回 None（触发回退）"""
    global _MODEL, _MODEL_FAILED
    if _MODEL is not None or _MODEL_FAILED:
        return _MODEL
    try:
        cfg = load_config().get("semantic", {})
        # 使用国内镜像端点加速模型文件下载
        if cfg.get("hf_mirror"):
            os.environ.setdefault("HF_ENDPOINT", cfg["hf_mirror"])
        # 模型已缓存时禁止联网检查更新，避免网络超时阻塞
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer
        cache_dir = cfg.get("cache_dir") or os.path.join(PROJECT_ROOT, "tools", "models")
        _MODEL = SentenceTransformer(cfg.get("model", "BAAI/bge-small-zh-v1.5"), cache_folder=cache_dir)
        logger.info("语义模型加载成功: %s", cfg.get("model", "BAAI/bge-small-zh-v1.5"))
    except Exception as e:
        _MODEL_FAILED = True
        logger.error("语义模型加载失败，已回退 TF-IDF 词面对比: %s", e)
    return _MODEL


def semantic_similarity(text_a: str, text_b: str) -> float:
    """计算两段文本的语义相似度（0~1）

    调用链：Diana LLM → 句向量模型 → TF-IDF 兜底
    """
    if not text_a or not text_b:
        return 0.0
    # Diana LLM 优先
    try:
        from src.clients import diana_client
        if diana_client.is_diana_mode() and diana_client.check_connectivity():
            score = diana_client.llm_similarity(text_a, text_b)
            if score > 0:
                return score
    except Exception as e:
        logger.debug("Diana LLM 相似度不可用，回退 embedding: %s", e)
    # 句向量模型兜底
    model = _get_model()
    if model is None:
        from src.core.similarity import cosine_of_texts
        return cosine_of_texts(text_a, text_b)
    vectors = model.encode([text_a, text_b], normalize_embeddings=True)
    return float((vectors[0] * vectors[1]).sum())


def semantic_best_matches(steps_a: list, steps_b: list) -> list:
    """逐条最佳匹配语义相似度：steps_a 每条取与 steps_b 各条的最大语义相似度

    模型不可用时回退 TF-IDF 逐对余弦；steps_b 为空时全部记 0 分。
    """
    if not steps_a:
        return []
    if not steps_b:
        return [0.0] * len(steps_a)
    model = _get_model()
    if model is None:
        from src.core.similarity import cosine_of_texts
        return [max(cosine_of_texts(a, b) for b in steps_b) for a in steps_a]
    vectors_a = model.encode(steps_a, normalize_embeddings=True)
    vectors_b = model.encode(steps_b, normalize_embeddings=True)
    matrix = vectors_a @ vectors_b.T
    return [float(row.max()) for row in matrix]


def compare_mode() -> str:
    """当前生效的对比方式，供页面展示"""
    try:
        from src.clients import diana_client
        if diana_client.is_diana_mode() and diana_client.check_connectivity():
            return f"Diana LLM 语义对比（{diana_client.get_model()}）"
    except Exception:
        pass
    return "句向量对比" if _get_model() is not None else "词面对比（LLM/语义模型均不可用，已回退）"
