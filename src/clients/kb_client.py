"""知识库入库接口客户端：分析正确的 bug 由开发手工触发入库"""
from src.clients.base import http_post
from src.config import load_config, setup_logger

logger = setup_logger("kb")


def store_to_knowledge_base(bugid: str, content: str) -> dict:
    """将 bug 分析文档内容传入知识库接口

    :param bugid: Jira bugid
    :param content: 分析文档全文内容
    :return: 接口返回值（mock 模式返回成功标识）
    """
    cfg = load_config()["knowledge_base_api"]
    if cfg.get("mock", False):
        logger.info("[mock] 知识库入库成功: bugid=%s, 内容长度=%d", bugid, len(content))
        return {"code": 0, "message": "success"}
    payload = {cfg["bugid_field"]: bugid, cfg["content_field"]: content}
    logger.info("调用知识库入库接口: bugid=%s", bugid)
    result = http_post(cfg["url"], payload, timeout=cfg.get("timeout", 30))
    logger.info("知识库入库完成: bugid=%s, 返回: %s", bugid, result)
    return result
