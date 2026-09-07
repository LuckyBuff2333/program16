"""Diana 大模型 API 客户端：认证管理与请求头构建

测试环境认证：Authorization: Bearer <OAuth2 Token> + x-api-key 双头
生产环境认证：access_token + apiTag + client_id

连通性预检：check_connectivity() 快速探测 Diana 是否可达（5s 超时，缓存 5 分钟），
不可达时上层自动降级到阿里云，避免每次调用都等待超时。
"""
import threading
import time

import httpx

from src.clients.base import http_post, CONNECT_TIMEOUT
from src.config import load_config, setup_logger

logger = setup_logger("diana")

# Token 缓存（进程级单例）
_token_cache = {"token": None, "expires_at": 0}
_lock = threading.Lock()

# 连通性状态缓存（避免每次调用都探测）
_diana_status = {"available": None, "checked_at": 0}
_STATUS_TTL = 300  # 缓存有效期 5 分钟


def _get_diana_config() -> dict:
    """获取 diana 配置段，不存在时返回空字典"""
    return load_config().get("diana", {})


def _is_prod() -> bool:
    """判断当前是否为生产环境模式"""
    return _get_diana_config().get("env", "test") == "prod"


def _get_active_cfg() -> dict:
    """根据 env 配置返回当前环境的参数（token_url/url/model/client_id/client_secret）

    prod 环境从 prod_xxx 字段读取，test 环境从原字段读取。
    """
    cfg = _get_diana_config()
    if _is_prod():
        return {
            "token_url": cfg.get("prod_token_url", ""),
            "url": cfg.get("prod_url", ""),
            "model": cfg.get("prod_model", cfg.get("model", "deepseek-v-flash")),
            "client_id": cfg.get("prod_client_id", ""),
            "client_secret": cfg.get("prod_client_secret", ""),
            "api_key": "",  # 生产环境不使用 x-api-key
            "env": "prod",
        }
    return {**cfg, "env": "test"}


def get_token() -> str:
    """获取 Diana API access_token（线程安全，过期自动刷新）

    通过 OAuth2 client_credentials 流程向 AIDM 服务请求 token。
    :return: access_token 字符串
    :raises ValueError: 配置缺失或获取失败
    """
    global _token_cache
    active = _get_active_cfg()
    if not active.get("client_id"):
        raise ValueError(f"diana [{active['env']}] 配置缺少 client_id，无法获取 token")

    with _lock:
        now = time.time()
        if _token_cache["token"] and now < _token_cache["expires_at"] - 120:
            return _token_cache["token"]

        logger.info("Diana token 已过期或未获取（%s），正在刷新...", active["env"])
        http_timeout = httpx.Timeout(30, connect=CONNECT_TIMEOUT)
        response = httpx.post(
            active["token_url"],
            data={
                "scope": "ALL",
                "grant_type": "client_credentials",
                "client_id": active["client_id"],
                "client_secret": active["client_secret"],
            },
            timeout=http_timeout,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Connection": "close"},
        )
        response.raise_for_status()
        result = response.json()
        token = result.get("access_token")
        if not token:
            raise ValueError(f"Diana token 获取失败，响应: {str(result)[:200]}")
        expires_in = result.get("expires_in", 3600)
        _token_cache = {"token": token, "expires_at": now + expires_in}
        logger.info("Diana token 刷新成功，有效期 %ds", expires_in)
        return token


def build_headers() -> dict:
    """构建 Diana API 请求头

    测试环境：Authorization: Bearer <OAuth2 Token> + x-api-key 双头认证
    生产环境：access_token + apiTag + client_id
    """
    active = _get_active_cfg()
    if active.get("api_key"):
        # 测试环境：OAuth2 Token + X-API-KEY 双头认证
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {get_token()}",
            "x-api-key": active["api_key"],
        }
    # 生产环境：access_token + apiTag + client_id
    return {
        "access_token": get_token(),
        "Content-Type": "application/json",
        "apiTag": "V1",
        "clientRequestId": "01",
        "client_id": active.get("client_id", ""),
    }


def get_url() -> str:
    """获取当前环境的 Diana 聊天补全 API 地址"""
    return _get_active_cfg().get("url", "")


def get_model() -> str:
    """获取当前环境的 Diana 模型名称"""
    return _get_active_cfg().get("model", "deepseek-v-flash")


def is_diana_mode() -> bool:
    """判断当前是否启用 Diana API 模式（已配置且非 mock）"""
    active = _get_active_cfg()
    return bool(active.get("url")) and not _get_diana_config().get("mock", True)


def check_connectivity(timeout: int = 5) -> bool:
    """检查 Diana API 是否可达（5s 快速探测，结果缓存 5 分钟，失败状态仅缓存 60s）

    不可达时上层可直接跳过 Diana 走兜底，避免每次调用都等待超时。
    :return: True=可达，False=不可达或未配置
    """
    global _diana_status
    if not is_diana_mode():
        return False
    now = time.time()
    # 如果缓存未过期，根据上次检查结果决定：
    # - 上次可达：正常缓存 5 分钟
    # - 上次不可达：仅缓存 60 秒，避免长时间缓存错误状态导致无法恢复
    if _diana_status["available"] is not None:
        elapsed = now - _diana_status["checked_at"]
        if _diana_status["available"] and elapsed < _STATUS_TTL:
            return True
        if not _diana_status["available"] and elapsed < 60:
            return False
    try:
        headers = build_headers()
        http_timeout = httpx.Timeout(timeout, connect=timeout)
        httpx.post(get_url(), json={}, timeout=http_timeout, headers=headers)
        _diana_status = {"available": True, "checked_at": now}
        logger.info("Diana API 可达（%s）", get_url())
        return True
    except (httpx.ConnectTimeout, httpx.ConnectError):
        _diana_status = {"available": False, "checked_at": now}
        logger.warning("Diana API 不可达（%s），将使用兜底模型", get_url())
        return False
    except Exception:
        # 其他异常（如 4xx/5xx）说明服务可达但请求格式不对
        _diana_status = {"available": True, "checked_at": now}
        logger.info("Diana API 可达（非连接错误）")
        return True


def reset_availability():
    """重置连通性缓存，下次调用 check_connectivity 时重新探测"""
    global _diana_status
    _diana_status = {"available": None, "checked_at": 0}


def diana_post(payload: dict, timeout: int = 60) -> dict:
    """发送请求至 Diana API（自动构建请求头）

    :param payload: OpenAI 兼容格式的请求体（model/messages/temperature 等）
    :param timeout: 请求超时秒数
    :return: API 响应字典
    """
    headers = build_headers()
    return http_post(get_url(), payload, timeout=timeout, headers=headers)


def _llm_chat(prompt: str, max_tokens: int = 200, timeout: int = 30) -> str:
    """通用 Diana LLM 调用，返回模型回复文本，失败时返回空字符串"""
    payload = {
        "model": get_model(),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    try:
        result = diana_post(payload, timeout=timeout)
        return result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.warning("Diana LLM 调用失败: %s", e)
        return ""


def llm_similarity(text_a: str, text_b: str, timeout: int = 30) -> float:
    """通过 Diana 大模型判断两段文本的语义相似度（0~1）

    使用 prompt 方式让模型输出相似度分数，适合少量文本的精细判断。
    :param text_a: 文本A
    :param text_b: 文本B
    :param timeout: 请求超时秒数
    :return: 相似度分数 0~1，失败时返回 0.0
    """
    if not text_a or not text_b:
        return 0.0
    # 长文本截断，避免超出模型上下文限制
    max_len = 500
    if len(text_a) > max_len:
        text_a = text_a[:max_len]
    if len(text_b) > max_len:
        text_b = text_b[:max_len]
    prompt = (
        f"将下列内容进行语义对比:\"{text_a}\",\"{text_b}\"。\n"
        f"相似度指两段文本描述的问题或含义是否相同，而非字面是否一致。"
        f"请只输出一个0到1之间的数字分数。"
    )
    content = _llm_chat(prompt, max_tokens=10, timeout=timeout)
    if not content:
        return 0.0
    import re
    match = re.search(r'(\d+\.?\d*)', content)
    if match:
        score = float(match.group(1))
        return max(0.0, min(1.0, score))
    logger.warning("Diana LLM 相似度返回无法解析: %s", content[:100])
    return 0.0


def llm_is_cause_related(comment: str, conclusion: str, timeout: int = 20) -> bool:
    """通过 Diana LLM 判断评论是否与根因结论相关（替代关键词命中）

    :param comment: Jira 评论内容
    :param conclusion: AI 报告的根因结论
    :return: True=相关，False=不相关或调用失败
    """
    if not comment or not conclusion:
        return False
    # 截断长文本
    comment = comment[:400]
    conclusion = conclusion[:300]
    prompt = (
        f"判断以下 Jira 评论是否涉及以下根因问题。\n"
        f"根因结论：{conclusion}\n"
        f"评论内容：{comment}\n"
        f"只回答“是”或“否”。"
    )
    content = _llm_chat(prompt, max_tokens=5, timeout=timeout)
    return content.startswith("是")


def llm_summarize_comment(comment: str, timeout: int = 30) -> dict:
    """通过 Diana LLM 简化 Jira 评论，提取排查动作、结果和日志证据

    :param comment: Jira 评论原文
    :return: {"action": str, "result": str, "summary": str, "evidence": list[str]}，失败时返回 None
    """
    if not comment:
        return None
    comment = comment[:1500]
    prompt = (
        f"对以下 Jira bug 评论进行简化分析，输出 JSON 格式：\n"
        f"1. action: 用5-15字描述评论中的排查动作或操作，"
        f"例如\"实车复测172.1.2版本\"、\"分析HMIC日志断层\"、\"排除VCU模块责任\"\n"
        f"2. result: 用5-20字描述排查结果或发现，"
        f"例如\"问题仍存在\"、\"PID从3604跳变为3798\"、\"信号正常，已排除\"\n"
        f"3. evidence: 提取评论中的日志证据行（含时间戳、ERROR、异常堆栈、关键配置值等），"
        f"尽量保留原始日志格式，没有则为空数组\n\n"
        f"评论内容：\n{comment}\n\n"
        f"只输出 JSON，不要其他内容。示例：{{\"action\": \"日志断层分析\", \"result\": \"PID跳变，3分15秒无痕崩溃\", \"evidence\": [\"日志行1\"]}}"
    )
    content = _llm_chat(prompt, max_tokens=250, timeout=timeout)
    if not content:
        return None
    # 解析 JSON
    import json, re
    # 去除 markdown 代码块标记
    cleaned = re.sub(r'```(?:json)?\s*', '', content).strip().rstrip('`').strip()
    # 尝试解析，失败时修复被截断的 JSON（如 evidence 数组中日志行被截断）
    result = _try_parse_json(cleaned)
    if result and isinstance(result, dict) and ("action" in result or "summary" in result):
        evidence = result.get("evidence", [])
        if isinstance(evidence, str):
            evidence = [evidence]
        action = str(result.get("action", result.get("summary", "")))
        res = str(result.get("result", ""))
        # 兼容保留 summary 字段（取 action + result 组合）
        summary = f"{action}，{res}" if action and res else (action or res)
        return {"action": action, "result": res, "summary": summary,
                "evidence": [str(e) for e in evidence if e]}
    logger.warning("Diana LLM 评论简化返回无法解析: %s", content[:100])
    return None


def _try_parse_json(text: str) -> dict:
    """尝试解析 JSON，失败时修复被截断的 JSON（截断字符串/数组/对象）"""
    import json, re
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 修复被截断的 JSON：截断未关闭的字符串、数组、对象
    repaired = text
    # 清理字符串内的控制字符（JSON 规范不允许原始换行/制表符）
    repaired = re.sub(r'[\x00-\x09\x0b\x0c\x0e-\x1f]', ' ', repaired)
    # 统计未关闭的引号（不在转义后的引号）
    in_str = False
    escape_next = False
    for i, ch in enumerate(repaired):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"':
            in_str = not in_str
    if in_str:
        repaired += '"'
    # 去除尾随逗号（截断可能导致闭合括号前遗留逗号）
    repaired = re.sub(r',\s*([\]}])', r'\1', repaired)
    # 统计未关闭的括号
    open_braces = repaired.count('{') - repaired.count('}')
    open_brackets = repaired.count('[') - repaired.count(']')
    repaired += ']' * max(open_brackets, 0)
    repaired += '}' * max(open_braces, 0)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass
    # 正则兆底：尝试提取 action 和 result 字段
    action_m = re.search(r'"action"\s*:\s*"([^"]+)"', text)
    result_m = re.search(r'"result"\s*:\s*"([^"]+)"', text)
    if action_m or result_m:
        return {
            "action": action_m.group(1) if action_m else "",
            "result": result_m.group(1) if result_m else "",
            "evidence": []
        }
    return None


def llm_combine_conclusions(summaries: list, ai_conclusion: str = "", timeout: int = 45) -> str:
    """通过 Diana LLM 将多条评论的排查动作合并为整体排查结论

    :param summaries: 每条评论的简化结果列表 [{"action": str, "result": str, ...}]
    :param ai_conclusion: AI 日志分析报告的根因结论（可选）
    :return: 合并后的排查结论段落，失败时返回空字符串
    """
    if not summaries:
        return ai_conclusion or ""
    # 构建评论摘要文本（使用排查动作+结果）
    items = []
    for i, s in enumerate(summaries):
        action = s.get("action", "")
        res = s.get("result", "")
        desc = f"{action} → {res}" if action and res else (action or s.get("summary", ""))
        if desc:
            items.append(f"评论{i+1}: {desc}")
    combined_text = "\n".join(items)[:1200]
    # 构造含 AI 报告结论的上下文
    ai_hint = f"\nAI日志分析报告结论：{ai_conclusion}\n" if ai_conclusion else ""
    prompt = (
        f"将以下 bug 排查过程合并为一段完整的排查结论。\n"
        f"要求：将各评论的排查动作和结果连起来分析，给出当前问题定位状态和下一步建议。"
        f"如有AI日志分析结论，请将其关键发现融入分析中。"
        f"禁止输出分析过程或论证步骤。\n"
        f"{ai_hint}\n"
        f"各评论排查过程：\n{combined_text}\n\n"
        f"排查结论："
    )
    content = _llm_chat(prompt, max_tokens=150, timeout=timeout)
    if content:
        logger.info("Diana LLM 合并结论成功，长度=%d", len(content))
    return content.strip() if content else ""
