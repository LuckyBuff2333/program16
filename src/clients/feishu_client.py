"""飞书客户端：支持文档获取与多维表格（Bitable）API 操作

功能：
1. 文档获取：HTTP GET 飞书公开链接并解析纯文本
2. 多维表格：获取 tenant_access_token、查询表格记录、按 bugid 轮询结果
"""
import time
from typing import Optional

import httpx
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log,
)

from src.clients.base import cancellable_sleep as _cancellable_sleep
from src.clients import base as _base  # noqa: F401  确保 urllib3 警告抑制生效
from src.config import load_config, setup_logger

logger = setup_logger("feishu")

# 默认重试次数与超时
DEFAULT_RETRIES = 2
DEFAULT_TIMEOUT = 30
# 飞书 API 基础地址
_FEISHU_API = "https://open.feishu.cn/open-apis"

# Token 缓存（有效期 2 小时，缓存到过期前 5 分钟刷新）
_token_cache = {"token": None, "expire_at": 0}
_refresh_lock = __import__('threading').Lock()


@retry(
    stop=stop_after_attempt(DEFAULT_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException)),
    before_sleep=before_sleep_log(logger, 20),
    reraise=True,
)
def fetch_feishu_doc(url: str, timeout: int = DEFAULT_TIMEOUT, headers: dict = None) -> str:
    """HTTP GET 飞书链接获取文档纯文本内容

    :param url: 飞书文档链接
    :param timeout: 请求超时秒数
    :param headers: 可选请求头（cookie/token 等认证信息）
    :return: 文档纯文本内容
    """
    logger.info("GET 飞书文档: %s", url)
    response = httpx.get(url, timeout=timeout, headers=headers or {}, follow_redirects=True, verify=False)
    response.raise_for_status()
    content = response.text
    return _extract_text_from_html(content)


def _extract_text_from_html(html: str) -> str:
    """从 HTML 内容中提取纯文本（去除标签，保留换行）"""
    import re
    text = re.sub(r"<(?:br\s*/?|/?(?:p|div|li|h[1-6]|tr))[^>]*>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text


# ============ 飞书事件存储（接收机器人消息推送） ============
_feishu_events: dict = {}  # bugid -> {"link": str, "time": str, "chat_id": str, "title": str}
_feishu_card_events: list = []  # 按时间排序的所有卡片事件

# 事件持久化文件（防止服务重启丢失）
import os as _os
_EVENTS_FILE = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "data", "feishu_events.json")


def _load_persisted_events():
    """从文件加载持久化的事件数据"""
    global _feishu_events, _feishu_card_events
    try:
        if _os.path.exists(_EVENTS_FILE):
            import json as _json
            with open(_EVENTS_FILE, "r", encoding="utf-8") as f:
                data = _json.load(f)
            _feishu_events = data.get("events", {})
            _feishu_card_events = data.get("card_events", [])
    except Exception:
        pass


def _save_persisted_events():
    """将事件数据持久化到文件"""
    try:
        import json as _json
        _os.makedirs(_os.path.dirname(_EVENTS_FILE), exist_ok=True)
        with open(_EVENTS_FILE, "w", encoding="utf-8") as f:
            _json.dump({"events": _feishu_events, "card_events": _feishu_card_events[-50:]}, f, ensure_ascii=False)
    except Exception:
        pass


# 服务启动时加载持久化事件
_load_persisted_events()


def get_feishu_event(bugid: str) -> dict:
    """按 bugid 获取飞书事件推送的分析完成通知"""
    return _feishu_events.get(bugid, {})


def clear_feishu_event(bugid: str):
    """清除已处理的飞书事件"""
    _feishu_events.pop(bugid, None)
    _save_persisted_events()


def get_feishu_event_after_time(after_time: str) -> dict:
    """获取执行时间之后最近的一条卡片事件（按时间顺序匹配）

    :param after_time: API 调用时的 Unix 时间戳（秒字符串）
    :return: {"link": str, "time": str, "chat_id": str, "title": str} 或空 dict
    """
    try:
        after_ts = int(float(after_time)) if after_time else 0
    except (ValueError, TypeError):
        after_ts = 0
    for event in _feishu_card_events:
        try:
            event_ts = int(float(event.get("time", "0")) // 1000)  # 飞书时间戳为毫秒
        except (ValueError, TypeError):
            event_ts = 0
        if event_ts >= after_ts and event.get("link"):
            return event
    return {}


def remove_feishu_card_event(report_link: str):
    """移除已处理的卡片事件"""
    global _feishu_card_events
    _feishu_card_events = [e for e in _feishu_card_events if e.get("link") != report_link]
    _save_persisted_events()


# ============ 飞书机器人（长连接接收 + 主动发消息）============

def _get_bot_cfg() -> dict:
    """获取机器人配置：feishu_bot 优先，未配置时回退复用 feishu_bitable 的 app凭证"""
    cfg = load_config().get("feishu_bot", {})
    bitable_cfg = load_config().get("feishu_bitable", {})
    return {
        "enabled": cfg.get("enabled", True),
        "app_id": cfg.get("app_id") or bitable_cfg.get("app_id", ""),
        "app_secret": cfg.get("app_secret") or bitable_cfg.get("app_secret", ""),
    }


# 机器人 token 独立缓存（避免与 bitable 应用的全局 token 缓存串应用）
_bot_token_cache = {"token": None, "expire_at": 0}


def _get_bot_token() -> str:
    """获取机器人应用的 tenant_access_token（独立缓存，过期前 5 分钟刷新）"""
    bot_cfg = _get_bot_cfg()
    if not bot_cfg["app_id"] or not bot_cfg["app_secret"]:
        raise ValueError("feishu_bot 未配置 app_id/app_secret")
    now = time.time()
    if _bot_token_cache["token"] and now < _bot_token_cache["expire_at"] - 300:
        return _bot_token_cache["token"]
    url = f"{_FEISHU_API}/auth/v3/tenant_access_token/internal"
    resp = httpx.post(url, json={"app_id": bot_cfg["app_id"], "app_secret": bot_cfg["app_secret"]},
                      timeout=15, verify=False)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"获取机器人 tenant_access_token 失败: {data.get('msg')}")
    _bot_token_cache["token"] = data["tenant_access_token"]
    _bot_token_cache["expire_at"] = now + data.get("expire", 7200)
    return _bot_token_cache["token"]


def send_bot_message(chat_id: str, text: str) -> bool:
    """以机器人身份向指定会话发送文本消息（Open API: POST /im/v1/messages）"""
    import json as _json
    try:
        token = _get_bot_token()
        url = f"{_FEISHU_API}/im/v1/messages?receive_id_type=chat_id"
        payload = {"receive_id": chat_id, "msg_type": "text",
                   "content": _json.dumps({"text": text}, ensure_ascii=False)}
        resp = httpx.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                          json=payload, timeout=15, verify=False)
        data = resp.json()
        if data.get("code") != 0:
            logger.warning("机器人发消息失败: code=%s, msg=%s", data.get("code"), data.get("msg"))
            return False
        logger.info("机器人发消息成功: chat=%s, len=%d", chat_id[:12], len(text))
        return True
    except Exception as e:
        logger.warning("机器人发消息异常: %s", e)
        return False


def start_feishu_ws_client(event_handler):
    """启动飞书长连接 WebSocket 客户端（官方 lark-oapi SDK 推荐模式，守护线程+断线自动重连）

    长连接由客户端主动连出，无需公网 IP/内网穿透，适合本机工具接收机器人消息。
    :param event_handler: 消息回调函数，参数为 lark P2ImMessageReceiveV1 事件对象
    """
    import threading
    bot_cfg = _get_bot_cfg()
    if not bot_cfg["enabled"]:
        logger.info("feishu_bot.enabled=false，跳过长连接客户端")
        return
    if not bot_cfg["app_id"] or not bot_cfg["app_secret"]:
        logger.info("feishu_bot 未配置 app凭证，跳过长连接客户端")
        return

    def _run():
        import lark_oapi as lark
        while True:
            try:
                handler = (lark.EventDispatcherHandler.builder("", "")
                           .register_p2_im_message_receive_v1(event_handler)
                           .build())
                cli = lark.ws.Client(bot_cfg["app_id"], bot_cfg["app_secret"],
                                     event_handler=handler, log_level=lark.LogLevel.ERROR)
                logger.info("飞书长连接客户端启动 (app_id=%s...)", bot_cfg["app_id"][:8])
                cli.start()  # 阻塞，断开后返回进入重连循环
                logger.warning("飞书长连接断开，5秒后重连...")
            except Exception as e:
                logger.error("飞书长连接客户端异常: %s", e)
            time.sleep(5)

    threading.Thread(target=_run, name="feishu-ws", daemon=True).start()


# ============ 多维表格（Bitable）API ============


def _get_bitable_cfg() -> dict:
    """获取飞书多维表格配置（支持 Token 或 Cookie 两种模式）"""
    cfg = load_config().get("feishu_bitable", {})
    has_token = cfg.get("app_id") and cfg.get("app_secret")
    has_cookie = cfg.get("cookie")
    if not has_token and not has_cookie:
        raise ValueError("飞书 Bitable 未配置认证信息，请填写 app_id/app_secret 或 cookie")
    return cfg


def _is_cookie_mode() -> bool:
    """判断是否使用 Cookie 模式（无 app_id 但有 cookie）"""
    cfg = load_config().get("feishu_bitable", {})
    return bool(cfg.get("cookie")) and not (cfg.get("app_id") and cfg.get("app_secret"))


def get_tenant_access_token(app_id: str = None, app_secret: str = None) -> str:
    """获取飞书 tenant_access_token（自动缓存，过期前 5 分钟刷新）

    :param app_id: 飞书应用 App ID（默认从配置读取）
    :param app_secret: 飞书应用 App Secret（默认从配置读取）
    :return: tenant_access_token 字符串
    """
    global _token_cache
    now = time.time()
    # 缓存未过期，直接复用
    if _token_cache["token"] and now < _token_cache["expire_at"] - 300:
        return _token_cache["token"]
    if not app_id or not app_secret:
        cfg = _get_bitable_cfg()
        app_id = app_id or cfg["app_id"]
        app_secret = app_secret or cfg["app_secret"]
    url = f"{_FEISHU_API}/auth/v3/tenant_access_token/internal"
    resp = httpx.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=15, verify=False)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"获取 tenant_access_token 失败: {data.get('msg')}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expire_at"] = now + data.get("expire", 7200)
    logger.info("飞书 tenant_access_token 获取成功，有效期 %ds", data.get("expire", 7200))
    return _token_cache["token"]


def _bitable_headers() -> dict:
    """构造 Bitable API 请求头（Bearer Token 认证，优先 user_access_token）"""
    token = _get_doc_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _paginate_get(url: str, headers: dict, params: dict,
                   log_msg: str = "", retry_on_token_expire: bool = False) -> list:
    """飞书 API 分页拉取通用辅助：自动翻页直到 has_more=False

    :param url: API 地址
    :param headers: 请求头
    :param params: 查询参数（page_token 由内部自动管理）
    :param log_msg: 日志描述
    :param retry_on_token_expire: 遇到 token 过期错误码时自动刷新重试一次
    :return: 所有页的 items 列表
    """
    all_items = []
    page_token = None
    retried = False
    # 记录原始 token 类型，重试时保持一致
    _orig_auth = headers.get("Authorization", "")
    _is_tenant_token = False
    try:
        _tk = _orig_auth.split(" ", 1)[1] if " " in _orig_auth else ""
        _is_tenant_token = bool(_tk and _tk == _token_cache.get("token", ""))
    except Exception:
        pass
    while True:
        if page_token:
            params["page_token"] = page_token
        resp = httpx.get(url, headers=headers, params=params, timeout=30, verify=False)
        # HTTP 401/400 时尝试自动刷新 token 重试一次（飞书可能返回 400 而非 401）
        if retry_on_token_expire and resp.status_code in (401, 400) and not retried:
            logger.info("收到 HTTP %d，尝试自动刷新 token...", resp.status_code)
            if _is_tenant_token:
                # tenant_access_token 失败：重新获取 tenant token 重试
                try:
                    new_tenant = get_tenant_access_token()
                    retried = True
                    headers = {"Authorization": f"Bearer {new_tenant}", "Content-Type": "application/json"}
                    continue
                except Exception:
                    pass
            # user_access_token 或 tenant 刷新失败：尝试 user_access_token
            if _refresh_user_token():
                retried = True
                headers = {"Authorization": f"Bearer {_get_doc_token()}", "Content-Type": "application/json"}
                continue
        # 解析响应体，提供更详细的错误信息
        if resp.status_code >= 400:
            try:
                err_body = resp.json()
                err_detail = f"HTTP {resp.status_code}: {err_body.get('msg', resp.text[:200])} (code={err_body.get('code', 'N/A')})"
            except Exception:
                err_detail = f"HTTP {resp.status_code}: {resp.text[:300]}"
            raise ValueError(f"{log_msg}: {err_detail}")
        data = resp.json()
        # 业务层 token 过期/无效自动刷新重试一次（99991677=过期, 99991672=无效, 99991668=认证失败）
        if retry_on_token_expire and data.get("code") in (99991677, 99991672, 99991668) and not retried:
            logger.info("user_access_token 已过期，尝试自动刷新...")
            if _refresh_user_token():
                retried = True
                headers = {"Authorization": f"Bearer {_get_doc_token()}", "Content-Type": "application/json"}
                continue
        if data.get("code") != 0:
            raise ValueError(f"{log_msg}: {data.get('msg')} (code={data.get('code')})")
        items = data.get("data", {}).get("items", [])
        all_items.extend(items)
        if not data.get("data", {}).get("has_more", False):
            break
        page_token = data.get("data", {}).get("page_token")
    return all_items


def _get_doc_token() -> str:
    """获取文档 API 的认证 token：优先使用 user_access_token，回退 tenant_access_token"""
    cfg = _get_bitable_cfg()
    user_token = cfg.get("user_access_token", "").strip()
    if user_token:
        return user_token
    return get_tenant_access_token()


def _refresh_user_token() -> str:
    """使用 refresh_token 刷新 user_access_token 并保存到配置（线程安全）

    :return: 新的 user_access_token，失败返回空串
    """
    cfg = _get_bitable_cfg()
    refresh_token = cfg.get("user_refresh_token", "").strip()
    if not refresh_token:
        logger.warning("无 refresh_token，无法刷新 user_access_token")
        return ""
    with _refresh_lock:
        try:
            # 获取 app_access_token
            app_url = f"{_FEISHU_API}/auth/v3/app_access_token/internal"
            r1 = httpx.post(app_url, json={
                "app_id": cfg.get("app_id", ""),
                "app_secret": cfg.get("app_secret", ""),
            }, timeout=15, verify=False)
            app_token = r1.json().get("app_access_token", "")
            if not app_token:
                logger.warning("获取 app_access_token 失败")
                return ""
            # 刷新 user_access_token
            refresh_url = f"{_FEISHU_API}/authen/v1/oidc/refresh_access_token"
            r2 = httpx.post(refresh_url, headers={"Authorization": f"Bearer {app_token}"},
                            json={"grant_type": "refresh_token", "refresh_token": refresh_token},
                            timeout=15, verify=False)
            d2 = r2.json()
            if d2.get("code") != 0:
                logger.warning("刷新 user_access_token 失败: %s", d2.get("msg", ""))
                return ""
            new_token = d2.get("data", {}).get("access_token", "")
            new_refresh = d2.get("data", {}).get("refresh_token", "")
            # 保存到配置文件
            import yaml
            from src.config import CONFIG_PATH
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            if config is None:
                config = {}
            config.setdefault("feishu_bitable", {})["user_access_token"] = new_token
            if new_refresh:
                config["feishu_bitable"]["user_refresh_token"] = new_refresh
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            # 清除配置缓存，确保后续读取到新 token
            import src.config as _cfg_module
            _cfg_module._CONFIG = None
            logger.info("user_access_token 已自动刷新，有效期 %ds, scope=%s",
                        d2.get("data", {}).get("expires_in", 0),
                        d2.get("data", {}).get("scope", "未返回"))
            return new_token
        except Exception as e:
            logger.warning("刷新 user_access_token 异常: %s", e)
            return ""


def get_wiki_node_app_token(wiki_token: str) -> str:
    """通过 Wiki token 获取内嵌多维表格的 app_token

    Wiki 页面中嵌入的多维表格需要通过此 API 获取实际的 obj_token（即 app_token），
    直接 Bitable app（/base/XXX）的 URL 可直接提取 app_token，无需此步骤。

    :param wiki_token: Wiki 页面 token（URL 中 /wiki/ 后的部分）
    :return: 多维表格的 app_token
    """
    url = f"{_FEISHU_API}/wiki/v2/spaces/get_node?token={wiki_token}"
    resp = httpx.get(url, headers=_bitable_headers(), timeout=15, verify=False)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"获取 Wiki 节点信息失败: {data.get('msg')}")
    node = data.get("data", {}).get("node", {})
    obj_token = node.get("obj_token")
    obj_type = node.get("obj_type")
    logger.info("Wiki 节点: obj_type=%s, obj_token=%s", obj_type, obj_token)
    if obj_type != "bitable":
        logger.warning("Wiki 节点类型非 bitable（%s），obj_token 可能不可用", obj_type)
    return obj_token


def list_bitable_records(app_token: str, table_id: str,
                         view_id: str = None, page_size: int = 100) -> list:
    """获取多维表格所有记录（自动分页，支持 Token/Cookie 两种模式）

    :param app_token: 多维表格 app_token
    :param table_id: 数据表 ID
    :param view_id: 可选的视图 ID
    :param page_size: 每页记录数（最大 500）
    :return: 记录列表，每条为 {"record_id": str, "fields": dict}
    """
    # Cookie 模式：使用内部 API
    if _is_cookie_mode():
        return cookie_list_records(app_token, table_id, view_id)
    # Token 模式：使用 Open API
    url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    params = {"page_size": min(page_size, 500)}
    if view_id:
        params["view_id"] = view_id
    all_records = _paginate_get(url, _bitable_headers(), params, "获取 Bitable 记录失败",
                                retry_on_token_expire=True)
    logger.info("Bitable 记录获取完成: app=%s, table=%s, 共 %d 条",
                app_token, table_id, len(all_records))
    return all_records


def list_bitable_fields(app_token: str, table_id: str) -> list:
    """获取多维表格字段（列）定义

    :param app_token: 多维表格 app_token
    :param table_id: 数据表 ID
    :return: 字段列表，每条为 {"field_id": str, "field_name": str, "type": int}
    """
    url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    resp = httpx.get(url, headers=_bitable_headers(), timeout=15, verify=False)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"获取 Bitable 字段失败: {data.get('msg')}")
    return data.get("data", {}).get("items", [])


def update_bitable_records(app_token: str, table_id: str, records: list) -> dict:
    """批量更新多维表格记录（支持 Token/Cookie 两种模式，自动刷新过期 token）

    :param app_token: 多维表格 app_token
    :param table_id: 数据表 ID
    :param records: 待更新记录列表，每条为 {"record_id": str, "fields": dict}
    :return: API 响应
    """
    if not records:
        return {"code": 0, "msg": "无待更新记录"}
    url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"
    payload = {"records": [{"record_id": r["record_id"], "fields": r["fields"]} for r in records]}
    headers = _bitable_headers()
    resp = httpx.post(url, headers=headers, json=payload, timeout=30, verify=False)
    # HTTP 401：token 过期，刷新后重试
    if resp.status_code == 401:
        logger.info("Bitable 更新收到 HTTP 401，尝试刷新 token 重试")
        _token_cache["token"] = None  # 强制刷新
        headers = _bitable_headers()
        resp = httpx.post(url, headers=headers, json=payload, timeout=30, verify=False)
    # HTTP 400：数据格式问题，提取飞书具体错误信息并抛出
    if resp.status_code == 400:
        try:
            err_body = resp.json()
            err_detail = f"{err_body.get('msg', '')} (code={err_body.get('code', '')})"
        except Exception:
            err_detail = resp.text[:300]
        logger.error("Bitable 400 Bad Request: %s", err_detail)
        import json as _json
        logger.error("发送的 payload: %s", _json.dumps(payload, ensure_ascii=False)[:1000])
        raise ValueError(f"多维表格写入失败(400): {err_detail}")
    resp.raise_for_status()
    data = resp.json()
    # 业务层 token 过期：自动刷新重试一次
    if data.get("code") in (99991677, 99991672, 99991668):
        logger.info("Bitable 更新 token 过期(code=%s)，刷新后重试", data.get("code"))
        _token_cache["token"] = None
        headers = _bitable_headers()
        resp = httpx.post(url, headers=headers, json=payload, timeout=30, verify=False)
        resp.raise_for_status()
        data = resp.json()
    if data.get("code") != 0:
        err_msg = data.get("msg", "未知错误")
        logger.error("Bitable 批量更新失败: code=%s, msg=%s, records=%d",
                     data.get("code"), err_msg, len(records))
        raise ValueError(f"Bitable 批量更新失败: {err_msg} (code={data.get('code')})")
    logger.info("Bitable 批量更新成功: app=%s, table=%s, 共 %d 条",
                app_token, table_id, len(records))
    return data


def create_bitable(name: str, folder_token: str) -> dict:
    """在指定文件夹创建多维表格，返回 {"app_token": str, "url": str}

    :param name: 多维表格名称
    :param folder_token: 目标文件夹 token
    """
    url = f"{_FEISHU_API}/bitable/v1/apps"
    body = {"name": name, "folder_token": folder_token}
    headers = _bitable_headers()
    resp = httpx.post(url, headers=headers, json=body, timeout=30, verify=False)
    if resp.status_code in (401, 400):
        err_data = resp.json()
        if err_data.get("code") in (99991677, 99991672) and _refresh_user_token():
            headers = _bitable_headers()
            resp = httpx.post(url, headers=headers, json=body, timeout=30, verify=False)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"创建多维表格失败: {data.get('msg')} (code={data.get('code')})")
    app = data.get("data", {}).get("app", {})
    logger.info("多维表格已创建: name=%s, app_token=%s", name, app.get("app_token"))
    return {"app_token": app.get("app_token", ""), "url": app.get("url", "")}


def create_bitable_table(app_token: str, name: str, fields: list) -> str:
    """在多维表格中创建数据表，返回 table_id

    :param app_token: 多维表格 app_token
    :param name: 数据表名称
    :param fields: 字段定义列表，如 [{"field_name": "jira号", "type": 1}]
    """
    url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables"
    body = {"table": {"name": name, "default_view_name": "默认视图", "fields": fields}}
    headers = _bitable_headers()
    resp = httpx.post(url, headers=headers, json=body, timeout=30, verify=False)
    if resp.status_code in (401, 400):
        err_data = resp.json()
        if err_data.get("code") in (99991677, 99991672) and _refresh_user_token():
            headers = _bitable_headers()
            resp = httpx.post(url, headers=headers, json=body, timeout=30, verify=False)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"创建数据表失败: {data.get('msg')} (code={data.get('code')})")
    table_id = data.get("data", {}).get("table_id", "")
    logger.info("数据表已创建: app=%s, table=%s, name=%s", app_token, table_id, name)
    return table_id


def batch_create_records(app_token: str, table_id: str, records: list) -> dict:
    """批量创建多维表格记录（单次上限 500 条）

    :param app_token: 多维表格 app_token
    :param table_id: 数据表 ID
    :param records: 记录列表，每条为 {"fields": {"字段名": 值, ...}}
    :return: API 响应
    """
    if not records:
        return {"code": 0, "msg": "无待创建记录"}
    url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    # 分批处理，每批最多 500 条
    all_data = []
    for i in range(0, len(records), 500):
        batch = records[i:i + 500]
        payload = {"records": [{"fields": r["fields"]} for r in batch]}
        headers = _bitable_headers()
        resp = httpx.post(url, headers=headers, json=payload, timeout=30, verify=False)
        if resp.status_code == 401:
            logger.info("批量创建收到 HTTP 401，尝试刷新 token 重试")
            _token_cache["token"] = None
            headers = _bitable_headers()
            resp = httpx.post(url, headers=headers, json=payload, timeout=30, verify=False)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") in (99991677, 99991672, 99991668):
            logger.info("批量创建 token 过期(code=%s)，刷新后重试", data.get("code"))
            _token_cache["token"] = None
            headers = _bitable_headers()
            resp = httpx.post(url, headers=headers, json=payload, timeout=30, verify=False)
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") != 0:
            raise ValueError(f"批量创建记录失败: {data.get('msg')} (code={data.get('code')})")
        all_data.extend(data.get("data", {}).get("records", []))
    logger.info("Bitable 批量创建成功: app=%s, table=%s, 共 %d 条",
                app_token, table_id, len(all_data))
    return {"code": 0, "records": all_data}


def batch_delete_records(app_token: str, table_id: str, record_ids: list) -> dict:
    """批量删除多维表格记录（单次上限 500 条）

    :param app_token: 多维表格 app_token
    :param table_id: 数据表 ID
    :param record_ids: 待删除的 record_id 列表
    :return: API 响应
    """
    if not record_ids:
        return {"code": 0, "msg": "无待删除记录"}
    url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete"
    for i in range(0, len(record_ids), 500):
        batch = record_ids[i:i + 500]
        payload = {"records": batch}
        headers = _bitable_headers()
        resp = httpx.post(url, headers=headers, json=payload, timeout=30, verify=False)
        if resp.status_code == 401:
            _token_cache["token"] = None
            headers = _bitable_headers()
            resp = httpx.post(url, headers=headers, json=payload, timeout=30, verify=False)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise ValueError(f"批量删除记录失败: {data.get('msg')} (code={data.get('code')})")
    logger.info("Bitable 批量删除成功: app=%s, table=%s, 共 %d 条", app_token, table_id, len(record_ids))
    return {"code": 0}


def find_record_by_bugid(bugid: str, app_token: str = None,
                         table_id: str = None, view_id: str = None) -> Optional[dict]:
    """在多维表格中查找指定 bugid 的记录（返回第一条匹配）

    :param bugid: Jira bug ID（如 VCU-501224）
    :param app_token: 多维表格 app_token（默认从配置读取）
    :param table_id: 数据表 ID（默认从配置读取）
    :param view_id: 视图 ID（默认从配置读取）
    :return: 匹配的记录 {"record_id": str, "fields": dict}，未找到返回 None
    """
    records = find_records_by_bugid(bugid, app_token, table_id, view_id)
    return records[0] if records else None


def find_records_by_bugid(bugid: str, app_token: str = None,
                          table_id: str = None, view_id: str = None) -> list:
    """在多维表格中查找指定 bugid 的所有匹配记录

    用于同一 bugid 存在多条记录时（如多次执行），按分析完成时间筛选最新记录。
    :return: 匹配的记录列表，未找到返回空列表
    """
    cfg = _get_bitable_cfg()
    app_token = app_token or cfg.get("app_token", "")
    table_id = table_id or cfg["table_id"]
    view_id = view_id or cfg.get("view_id", "")
    bugid_field = cfg.get("bugid_field", "issue_key")
    if not app_token and cfg.get("wiki_token"):
        if _is_cookie_mode():
            app_token = cookie_get_app_token_from_wiki(cfg["wiki_token"])
        else:
            app_token = get_wiki_node_app_token(cfg["wiki_token"])
    all_records = list_bitable_records(app_token, table_id, view_id)
    matched = []
    for record in all_records:
        fields = record.get("fields", {})
        field_value = fields.get(bugid_field, "")
        if isinstance(field_value, list):
            field_value = "".join(
                item.get("text", str(item)) if isinstance(item, dict) else str(item)
                for item in field_value
            )
        elif isinstance(field_value, dict):
            field_value = field_value.get("text", str(field_value))
        if str(field_value).strip() == bugid:
            matched.append(record)
    # 精确匹配无结果时尝试后缀模糊匹配
    if not matched:
        for record in all_records:
            fields = record.get("fields", {})
            field_value = str(fields.get(bugid_field, "")).strip()
            if field_value.endswith(bugid):
                matched.append(record)
    logger.info("查找 bugid=%s: 匹配 %d 条记录", bugid, len(matched))
    return matched


def poll_bitable_for_result(bugid: str, poll_interval: int = None,
                            max_wait: int = None, cancel_check=None) -> Optional[dict]:
    """轮询多维表格，等待指定 bugid 的分析结果出现

    :param bugid: Jira bug ID
    :param poll_interval: 轮询间隔秒数（默认从配置读取）
    :param max_wait: 最大等待秒数（默认使用 ai_log_api.timeout）
    :return: 匹配的记录（含 fields），超时返回 None
    """
    cfg = _get_bitable_cfg()
    poll_interval = poll_interval or int(cfg.get("poll_interval", 30))
    if max_wait is None:
        max_wait = int(load_config().get("ai_log_api", {}).get("timeout", 900))
    waited = 0
    logger.info("开始轮询飞书表格: bugid=%s, 间隔=%ds, 最大=%ds", bugid, poll_interval, max_wait)
    while waited < max_wait:
        if cancel_check and cancel_check():
            logger.info("飞书表格轮询收到取消信号，已等待 %ds", waited)
            return None
        try:
            record = find_record_by_bugid(bugid)
            if record:
                fields = record.get("fields", {})
                logger.info("飞书表格中找到 bugid=%s 的结果，已等待 %ds", bugid, waited)
                return fields
        except Exception as e:
            logger.warning("轮询飞书表格请求失败（%ds）: %s", waited, e)
        if _cancellable_sleep(poll_interval, cancel_check):
            logger.info("飞书表格轮询收到取消信号（sleep期间），已等待 %ds", waited)
            return None
        waited += poll_interval
        logger.info("轮询飞书表格: bugid=%s, 已等待 %ds/%ds", bugid, waited, max_wait)
    logger.warning("飞书表格轮询超时（%ds），bugid=%s 未找到结果", max_wait, bugid)
    return None


def extract_report_from_bitable(fields: dict) -> str:
    """从多维表格记录中提取分析报告内容

    自动识别 report_field 配置对应的字段，兼容富文本、纯文本和 URL 类型字段。
    URL 类型字段（type=15）返回链接地址，文本类型返回字段内容。

    :param fields: 记录中的 fields 字典
    :return: 报告文本内容或链接 URL
    """
    cfg = _get_bitable_cfg()
    report_field = cfg.get("report_field", "report")
    value = fields.get(report_field)
    if not value:
        # 尝试查找包含“报告”或“report”关键词的字段
        for key, val in fields.items():
            if any(kw in key.lower() for kw in ("报告", "分析", "report", "result", "content", "链接")):
                value = val
                report_field = key
                break
    if not value:
        available = list(fields.keys())
        raise ValueError(f"多维表格记录中未找到报告字段 '{report_field}'，可用字段: {available}")
    # 解析飞书字段值（URL 类型字段为 {"link": url, "text": text}）
    if isinstance(value, dict) and "link" in value:
        # URL 类型字段：提取链接地址
        text = value["link"]
    elif isinstance(value, list):
        text = "".join(
            item.get("text", str(item)) if isinstance(item, dict) else str(item)
            for item in value
        )
    elif isinstance(value, dict):
        text = value.get("text", str(value))
    else:
        text = str(value)
    logger.info("从飞书表格提取报告: 字段=%s, 长度=%d", report_field, len(text))
    return text


# ============ 飞书文档 API（docx/v1）============


def _extract_elements_text(elements: list) -> str:
    """从飞书文档 element 列表中提取文本，支持样式（加粗/斜体/代码/链接/行内图片）"""
    parts = []
    for elem in (elements or []):
        text_run = elem.get("text_run")
        if text_run:
            text = text_run.get("content", "")
            style = text_run.get("text_element_style", {})
            # 链接
            link = style.get("link", {})
            if link and link.get("url"):
                url = link["url"]
                text = f"[{text}]({url})"
            # 行内代码
            if style.get("inline_code"):
                text = f"`{text}`"
            # 加粗
            if style.get("bold"):
                text = f"**{text}**"
            # 斜体
            if style.get("italic"):
                text = f"*{text}*"
            # 删除线
            if style.get("strikethrough"):
                text = f"~~{text}~~"
            parts.append(text)
        mention = elem.get("mention_doc")
        if mention:
            parts.append(mention.get("title", ""))
        # 行内图片元素
        img = elem.get("image")
        if img:
            token = img.get("token", "")
            if token:
                parts.append(f"![图片]({token})")
    return "".join(parts)


def _download_feishu_image(file_token: str, bugid: str = "") -> str:
    """下载飞书文档中的图片到本地 assets 目录

    :param file_token: 图片文件 token
    :param bugid: 用于分目录存储
    :return: 前端可访问的 URL 路径，失败返回空串
    """
    import os as _os
    assets_dir = _os.path.join(_os.path.dirname(_os.path.dirname(
        _os.path.dirname(_os.path.abspath(__file__)))), "docs", "assets")
    if bugid:
        assets_dir = _os.path.join(assets_dir, bugid)
    _os.makedirs(assets_dir, exist_ok=True)

    url = f"{_FEISHU_API}/drive/v1/medias/{file_token}/download"
    headers = {"Authorization": f"Bearer {_get_doc_token()}"}
    try:
        resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True, verify=False)
        if resp.status_code != 200:
            logger.warning("图片下载失败: token=%s, status=%d", file_token, resp.status_code)
            return ""
        # 根据内容类型确定扩展名
        ct = resp.headers.get("content-type", "")
        ext = ".png"
        if "jpeg" in ct or "jpg" in ct:
            ext = ".jpg"
        elif "gif" in ct:
            ext = ".gif"
        elif "webp" in ct:
            ext = ".webp"
        elif "svg" in ct:
            ext = ".svg"
        filename = f"{file_token}{ext}"
        filepath = _os.path.join(assets_dir, filename)
        with open(filepath, "wb") as f:
            f.write(resp.content)
        logger.info("图片已下载: %s (%d bytes)", filepath, len(resp.content))
        return f"/api/doc-images/{bugid}/{filename}" if bugid else f"/api/doc-images/{filename}"
    except Exception as e:
        logger.warning("图片下载异常: token=%s, error=%s", file_token, e)
        return ""


def _fetch_sheet_content(spreadsheet_token: str) -> str:
    """通过 Sheets API 读取电子表格数据并转为 Markdown 表格

    :return: Markdown 表格文本，失败或无数据返回空串
    """
    headers = {"Authorization": f"Bearer {_get_doc_token()}", "Content-Type": "application/json"}
    # 获取子表列表
    meta_url = f"{_FEISHU_API}/sheets/v2/spreadsheets/{spreadsheet_token}/metainfo"
    try:
        r = httpx.get(meta_url, headers=headers, timeout=15, verify=False)
        d = r.json()
        if d.get("code") != 0:
            logger.debug("表格元数据获取失败: code=%s, msg=%s", d.get("code"), d.get("msg", ""))
            return ""
    except Exception as e:
        logger.debug("表格元数据请求异常: %s", e)
        return ""

    sheets_info = d.get("data", {}).get("sheets", [])
    if not sheets_info:
        return ""

    md_parts = []
    for sheet in sheets_info[:3]:  # 最多渲染 3 个子表
        sheet_id = sheet.get("sheetId", "")
        title = sheet.get("title", "Sheet1")
        # 读取单元格数据
        val_url = f"{_FEISHU_API}/sheets/v2/spreadsheets/{spreadsheet_token}/values"
        params = {"range": f"{sheet_id}", "valueRenderOption": "ToString"}
        try:
            r2 = httpx.get(val_url, headers=headers, params=params, timeout=15, verify=False)
            d2 = r2.json()
            if d2.get("code") != 0:
                continue
        except Exception:
            continue

        values = d2.get("data", {}).get("valueRange", {}).get("values", [])
        if not values:
            md_parts.append(f"> 📊 **{title}**（空表格）")
            continue

        # 转为 markdown 表格
        rows = []
        for row in values:
            cells = [str(c) if c is not None else "" for c in row]
            rows.append(cells)
        if not rows:
            md_parts.append(f"> 📊 **{title}**（空表格）")
            continue
        # 表头 + 分隔线 + 数据行
        header = "| " + " | ".join(rows[0]) + " |"
        sep = "| " + " | ".join("---" for _ in rows[0]) + " |"
        body = "\n".join("| " + " | ".join(row) + " |" for row in rows[1:])
        table_md = f"**{title}**\n\n{header}\n{sep}\n{body}" if body else f"**{title}**\n\n{header}\n{sep}"
        md_parts.append(table_md)

    return "\n\n".join(md_parts)


def _block_to_markdown(block: dict, bugid: str = "", feishu_domain: str = "feishu.cn") -> str:
    """将单个飞书文档 block 转为 Markdown 文本行

    :param bugid: 用于图片下载分目录存储
    :param feishu_domain: 飞书域名，用于电子表格等链接生成
    """
    bt = block.get("block_type", 0)
    # block_type=27 图片块：下载图片并返回 markdown 图片语法
    if bt == 27:
        img = block.get("image", {})
        token = img.get("token", "")
        if not token:
            return ""
        img_url = _download_feishu_image(token, bugid) if bugid else ""
        if img_url:
            return f"![图片]({img_url})"
        return f"![图片](https://open.feishu.cn/open-apis/drive/v1/medias/{token}/download)"
    # block_type=40 插件组件：不可通过 API 提取，跳过
    if bt == 40:
        return ""
    # block_type → 内容键名映射（与飞书 API 实际字段一致）
    type_keys = {
        1: "page", 2: "text", 3: "heading1", 4: "heading2", 5: "heading3",
        6: "heading4", 7: "heading5", 8: "heading6", 9: "heading7",
        10: "heading8", 11: "heading9",
        12: "bullet", 13: "ordered", 14: "code", 15: "quote",
        17: "callout", 30: "sheet",
    }
    key = type_keys.get(bt)
    if not key or key not in block:
        return ""
    content = block[key]
    text = _extract_elements_text(content.get("elements", []))
    # heading1 → #, heading2 → ##, ...
    if 3 <= bt <= 11:
        level = bt - 2
        return f"{'#' * level} {text}"
    if bt == 12:
        return f"- {text}"
    if bt == 13:
        return f"1. {text}"
    if bt == 14:
        lang = content.get("style", {}).get("language", "") or content.get("language", "")
        return f"```{lang}\n{text}\n```"
    if bt == 15:
        return f"> {text}"
    if bt == 17:
        # callout 块：带 emoji 前缀的引用
        emoji = content.get("emoji_id", "")
        prefix = f"{emoji} " if emoji else ""
        return f"> {prefix}{text}"
    if bt == 30:
        # 嵌入式电子表格：尝试读取数据并内联渲染为 Markdown 表格
        token = content.get("token", "")
        if token:
            sheet_md = _fetch_sheet_content(token)
            if sheet_md:
                return sheet_md
        # 回退：无权限或无数据时显示占位提示
        title = content.get("title", "电子表格")
        return f"> 📊 **{title}**（内嵌电子表格，内容为空或暂无权限读取）"
    if bt == 20:
        return "---"
    return text


def fetch_docx_as_markdown(document_id: str, bugid: str = "", feishu_domain: str = "") -> str:
    """通过飞书 Open API 获取 docx 文档内容并转为 Markdown

    需要应用权限: docx:document 或 docx:document:readonly
    :param document_id: 文档 ID（从 URL /docx/xxx 中提取）
    :param bugid: 用于图片分目录存储和去重标识
    :param feishu_domain: 飞书域名，用于电子表格链接生成；为空则从配置读取
    :return: Markdown 格式文档内容
    """
    # 确定飞书域名
    if not feishu_domain:
        cfg = _get_bitable_cfg()
        feishu_domain = cfg.get("domain", "feishu.cn")
    url = f"{_FEISHU_API}/docx/v1/documents/{document_id}/blocks"
    params = {"page_size": 500, "document_revision_id": -1}
    headers = {"Authorization": f"Bearer {_get_doc_token()}", "Content-Type": "application/json"}
    all_blocks = _paginate_get(url, headers, params, "获取飞书文档失败", retry_on_token_expire=True)
    # 跳过第一个 page 块（文档标题），其余转 Markdown；去除连续重复标题
    md_lines = []
    prev_line = ""
    for block in all_blocks:
        line = _block_to_markdown(block, bugid=bugid, feishu_domain=feishu_domain)
        if line:
            # 去重：连续完全相同的行只保留一条
            if line != prev_line:
                md_lines.append(line)
            prev_line = line
    md_text = "\n\n".join(md_lines)
    # 统计图片数量
    img_count = md_text.count("![图片]")
    logger.info("飞书文档获取成功: doc_id=%s, blocks=%d, 长度=%d, 图片=%d",
                document_id, len(all_blocks), len(md_text), img_count)
    return md_text


def extract_doc_id_from_url(url: str) -> str:
    """从飞书文档 URL 中提取 document_id

    支持格式: /docx/xxx, /wiki/xxx, /docs/xxx
    :return: document_id 字符串，无法提取返回空串
    """
    import re as _re
    match = _re.search(r"/(?:docx|wiki|docs)/([A-Za-z0-9]+)", url)
    return match.group(1) if match else ""


def extract_domain_from_url(url: str) -> str:
    """从飞书 URL 中提取域名

    :return: 域名字符串，无法提取返回默认域名
    """
    import re as _re
    match = _re.search(r"https?://([^/]+\.feishu\.cn)", url)
    if match:
        return match.group(1)
    # 回退：从配置中读取
    cfg = _get_bitable_cfg()
    return cfg.get("domain", "feishu.cn")


# ============ 飞书文档创建（docx/v1）============


def _parse_md_text_elements(text: str) -> list:
    """将文本中的 **bold** 标记解析为飞书 text_element 列表"""
    import re as _re
    elements = []
    pattern = _re.compile(r'\*\*(.+?)\*\*')
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            elements.append({"text_run": {"content": text[pos:m.start()], "text_element_style": {}}})
        elements.append({"text_run": {"content": m.group(1),
                                      "text_element_style": {"bold": True}}})
        pos = m.end()
    if pos < len(text):
        elements.append({"text_run": {"content": text[pos:], "text_element_style": {}}})
    return elements if elements else [{"text_run": {"content": text, "text_element_style": {}}}] 


def _md_to_feishu_blocks(md: str) -> list:
    """将 Markdown 内容转为飞书文档 block 列表（支持标题/加粗/列表/段落）"""
    import re as _re
    blocks = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        # 标题 (# ## ###)
        hm = _re.match(r'^(#{1,6})\s+(.+)', stripped)
        if hm:
            heading_level = len(hm.group(1))  # # → 1, ## → 2, ### → 3...
            block_type = heading_level + 2  # heading1 → 3, heading2 → 4, heading3 → 5...
            blocks.append({"block_type": block_type,
                           f"heading{heading_level}": {"elements": _parse_md_text_elements(hm.group(2)), "style": {}}})
            i += 1
            continue
        # 列表项 (- * •)
        lm = _re.match(r'^[-*•]\s+(.+)', stripped)
        if lm:
            bullets = []
            while i < len(lines):
                s = lines[i].strip()
                bm = _re.match(r'^[-*•]\s+(.+)', s)
                if not bm:
                    break
                bullets.append({"block_type": 12,
                                "bullet": {"elements": _parse_md_text_elements(bm.group(1)), "style": {}}})
                i += 1
            blocks.extend(bullets)
            continue
        # 分隔线
        if _re.match(r'^---+$', stripped):
            blocks.append({"block_type": 22, "divider": {}})
            i += 1
            continue
        # 跳过 Markdown 表格分隔行（如 |--------|----------|）
        if _re.match(r'^\|[-|:\s]+\|$', stripped):
            i += 1
            continue
        # 普通段落
        blocks.append({"block_type": 2, "text": {"elements": _parse_md_text_elements(stripped), "style": {}}})
        i += 1
    return blocks


def create_docx_document(title: str, md_content: str, folder_token: str = "") -> dict:
    """创建飞书在线文档并将 Markdown 内容写入

    需要应用权限: docx:document, drive:drive
    :param title: 文档标题
    :param md_content: Markdown 格式文档内容
    :param folder_token: 可选，指定文档所在的飞书文件夹 token
    :return: {"document_id": str, "url": str}，失败返回 {"document_id": "", "url": ""}
    """
    token = _get_doc_token()
    if not token:
        logger.warning("无可用 doc token，跳过在线文档创建")
        return {"document_id": "", "url": ""}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # 1. 创建空文档（可指定文件夹）
    url = f"{_FEISHU_API}/docx/v1/documents"
    body = {"title": title}
    if folder_token:
        body["folder_token"] = folder_token
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=15, verify=False)
        # token 过期时自动刷新重试一次
        if resp.status_code in (401, 400):
            try:
                err_data = resp.json()
                err_code = err_data.get("code", 0)
            except Exception:
                err_code = 0
            # 99991677 = token 过期，直接重试
            if err_code == 99991677 and _refresh_user_token():
                headers["Authorization"] = f"Bearer {_get_doc_token()}"
                resp = httpx.post(url, headers=headers, json=body, timeout=15, verify=False)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        try:
            err_body = e.response.json()
            err_code = err_body.get("code")
            err_msg = err_body.get("msg", "")
            logger.error("创建飞书文档 HTTP 错误: status=%s, code=%s, msg=%s", e.response.status_code, err_code, err_msg)
            if err_code == 99991679:
                raise ValueError(f"创建飞书文档失败: user_access_token 缺少 docx:document 权限，请重新授权 (code=99991679)")
            raise ValueError(f"创建飞书文档失败: {err_msg} (code={err_code}, status={e.response.status_code})")
        except ValueError:
            raise
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"创建飞书文档失败: {data.get('msg')} (code={data.get('code')})")
    doc = data.get("data", {}).get("document", {})
    doc_id = doc.get("document_id", "")
    logger.info("飞书文档创建成功: doc_id=%s, title=%s", doc_id, title)
    # 2. 将 Markdown 转为飞书 blocks 并批量添加（每批最多50个）
    blocks = _md_to_feishu_blocks(md_content)
    if blocks:
        add_url = f"{_FEISHU_API}/docx/v1/documents/{doc_id}/blocks/{doc_id}/children"
        for start in range(0, len(blocks), 50):
            batch = blocks[start:start + 50]
            payload = {"children": batch, "index": -1}
            r = httpx.post(add_url, headers=headers, json=payload, timeout=30, verify=False)
            r.raise_for_status()
            rd = r.json()
            if rd.get("code") in (99991677, 99991672, 99991668):
                token = _get_doc_token()
                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                r = httpx.post(add_url, headers=headers, json=payload, timeout=30, verify=False)
                r.raise_for_status()
                rd = r.json()
            if rd.get("code") != 0:
                logger.warning("添加文档块失败(批次%d): %s (code=%s)",
                               start // 50 + 1, rd.get("msg"), rd.get("code"))
    # 3. 构建文档 URL
    cfg = _get_bitable_cfg()
    domain = cfg.get("domain", "feishu.cn")
    doc_url = f"https://{domain}/docx/{doc_id}"
    logger.info("在线文档 URL: %s", doc_url)
    return {"document_id": doc_id, "url": doc_url}


def create_folder(name: str, parent_folder_token: str) -> dict:
    """在飞书云端文件夹下创建子文件夹

    需要应用权限: drive:drive
    :param name: 文件夹名称
    :param parent_folder_token: 父文件夹 token
    :return: {"token": str, "url": str}，失败返回空值
    """
    token = _get_doc_token()
    if not token:
        logger.warning("无可用 token，无法创建文件夹")
        return {"token": "", "url": ""}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{_FEISHU_API}/drive/v1/files/create_folder"
    body = {"name": name, "folder_token": parent_folder_token}
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=15, verify=False)
        # token 过期时自动刷新重试一次
        if resp.status_code in (401, 400):
            try:
                err_data = resp.json()
                err_code = err_data.get("code", 0)
            except Exception:
                err_code = 0
            if err_code == 99991677 and _refresh_user_token():
                headers["Authorization"] = f"Bearer {_get_doc_token()}"
                resp = httpx.post(url, headers=headers, json=body, timeout=15, verify=False)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            logger.error("创建文件夹失败: %s (code=%s)", data.get("msg"), data.get("code"))
            return {"token": "", "url": ""}
        folder_token = data.get("data", {}).get("token", "")
        cfg = _get_bitable_cfg()
        domain = cfg.get("domain", "feishu.cn")
        folder_url = f"https://{domain}/drive/folder/{folder_token}"
        logger.info("文件夹创建成功: %s -> %s", name, folder_url)
        return {"token": folder_token, "url": folder_url}
    except Exception as e:
        logger.warning("创建文件夹异常: %s", e)
        return {"token": "", "url": ""}


def delete_drive_file(file_token: str, file_type: str = "docx") -> bool:
    """删除飞书云盘文件/文档

    :param file_token: 文件 token
    :param file_type: 文件类型（docx/file/folder）
    :return: 是否删除成功
    """
    token = _get_doc_token()
    if not token:
        return False
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{_FEISHU_API}/drive/v1/files/{file_token}"
    try:
        resp = httpx.delete(url, headers=headers, params={"type": file_type}, timeout=15, verify=False)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            logger.warning("删除文件失败: %s (code=%s)", data.get("msg"), data.get("code"))
            return False
        logger.info("文件已删除: %s", file_token)
        return True
    except Exception as e:
        logger.warning("删除文件异常: %s", e)
        return False


def list_folder_files(folder_token: str, recursive: bool = False) -> list:
    """列出飞书云端文件夹下的文件列表

    需要应用权限: drive:drive
    :param folder_token: 文件夹 token
    :param recursive: 是否递归扫描子文件夹
    :return: [{"token": str, "name": str, "type": str, "created_time": str, "url": str, "folder": str}]
    """
    token = _get_doc_token()
    if not token:
        logger.warning("无可用 token，无法列出文件夹内容")
        return []
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{_FEISHU_API}/drive/v1/files"
    cfg = _get_bitable_cfg()
    domain = cfg.get("domain", "feishu.cn")
    files = []
    sub_folders = []
    page_token = ""
    retried = False
    while True:
        params = {"folder_token": folder_token, "page_size": 200}
        if page_token:
            params["page_token"] = page_token
        try:
            resp = httpx.get(url, headers=headers, params=params, timeout=30, verify=False)
            # token 过期时自动刷新重试一次
            if resp.status_code in (401, 400) and not retried:
                retried = True
                if _refresh_user_token():
                    headers = {"Authorization": f"Bearer {_get_doc_token()}"}
                    continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                logger.error("列出文件夹文件失败: %s (code=%s)", data.get("msg"), data.get("code"))
                break
            items = data.get("data", {}).get("files", [])
            for item in items:
                f_token = item.get("token", "")
                f_type = item.get("type", "")
                f_name = item.get("name", "")
                created = item.get("created_time", "")
                if f_type == "docx":
                    f_url = f"https://{domain}/docx/{f_token}"
                elif f_type == "file":
                    f_url = f"https://{domain}/file/{f_token}"
                else:
                    f_url = f"https://{domain}/file/{f_token}"
                files.append({"token": f_token, "name": f_name, "type": f_type,
                              "created_time": created, "url": f_url, "folder": ""})
                if recursive and f_type == "folder":
                    sub_folders.append((f_token, f_name))
            if not data.get("data", {}).get("has_more", False):
                break
            page_token = data.get("data", {}).get("page_token", "")
        except Exception as e:
            logger.warning("列出文件夹文件异常: %s", e)
            break
    # 递归扫描子文件夹
    if recursive and sub_folders:
        for sub_token, sub_name in sub_folders:
            sub_files = list_folder_files(sub_token, recursive=True)
            for sf in sub_files:
                sf["folder"] = f"{sub_name}/{sf.get('folder', '')}".rstrip("/") if sf.get("folder") else sub_name
            files.extend(sub_files)
    return files


def upload_md_to_drive(file_path: str, title: str = "", folder_token: str = "") -> dict:
    """上传本地 Markdown 文件到飞书云盘，返回可访问链接

    需要应用权限: drive:drive
    :param file_path: 本地 md 文件绝对路径
    :param title: 文件名（不含扩展名），默认使用原文件名
    :param folder_token: 可选，指定上传到的飞书文件夹 token
    :return: {"file_token": str, "url": str}，失败返回空值
    """
    token = _get_doc_token()
    if not token:
        logger.warning("无可用 token，跳过云盘上传")
        return {"file_token": "", "url": ""}

    if not _os.path.isfile(file_path):
        logger.warning("文件不存在: %s", file_path)
        return {"file_token": "", "url": ""}

    file_size = _os.path.getsize(file_path)
    file_name = title or _os.path.basename(file_path)
    if not file_name.endswith(".md"):
        file_name += ".md"

    headers = {"Authorization": f"Bearer {token}"}
    upload_url = f"{_FEISHU_API}/drive/v1/files/upload_all"
    # 读取配置的上传目录（可选），优先使用传入的 folder_token
    cfg = _get_bitable_cfg()
    parent_node = folder_token or cfg.get("drive_folder", "") or ""

    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f, "text/markdown")}
            data = {"file_name": file_name, "size": str(file_size),
                    "parent_type": "explorer", "parent_node": parent_node}
            resp = httpx.post(upload_url, headers=headers, data=data, files=files, timeout=60, verify=False)
            resp.raise_for_status()
            result = resp.json()
            if result.get("code") != 0:
                logger.error("上传文件失败: %s (code=%s)", result.get("msg"), result.get("code"))
                return {"file_token": "", "url": ""}

            file_token = result.get("data", {}).get("file_token", "")
            # 构建文件链接（复用已加载的 cfg）
            domain = cfg.get("domain", "feishu.cn")
            file_url = f"https://{domain}/file/{file_token}"
            logger.info("文件上传成功: %s -> %s", file_name, file_url)
            return {"file_token": file_token, "url": file_url}
    except Exception as e:
        logger.warning("上传文件到云盘失败: %s", e)
        return {"file_token": "", "url": ""}


# ============ Cookie 模式（无需创建飞书应用）============


def _cookie_headers() -> dict:
    """构造 Cookie 模式的请求头"""
    import re as _re
    cfg = _get_bitable_cfg()
    cookie = cfg.get("cookie", "")
    domain = cfg.get("domain", "saic-gm.feishu.cn")
    headers = {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://{domain}/",
    }
    # 从 cookie 中提取 CSRF token
    csrf_match = _re.search(r"(?:passport_csrf_token|tt_csrf_token|x_csrf_token)=([^;]+)", cookie)
    if csrf_match:
        headers["x-csrf-token"] = csrf_match.group(1)
    return headers


def _get_domain() -> str:
    """获取飞书域名"""
    cfg = _get_bitable_cfg()
    return cfg.get("domain", "saic-gm.feishu.cn")


def cookie_get_app_token_from_wiki(wiki_token: str) -> str:
    """Cookie 模式：从 Wiki 页面 HTML 中提取多维表格的 app_token

    访问 Wiki 页面，从内嵌的 bitable 组件中提取 app_token。
    优先从配置中读取 app_token，避免依赖 HTML 解析。
    """
    import re as _re
    cfg = _get_bitable_cfg()
    # 优先使用配置中的 app_token（最可靠）
    if cfg.get("app_token"):
        logger.info("使用配置中的 app_token: %s", cfg["app_token"])
        return cfg["app_token"]
    domain = _get_domain()
    url = f"https://{domain}/wiki/{wiki_token}"
    logger.info("Cookie 模式: 访问 Wiki 页面提取 app_token: %s", url)
    resp = httpx.get(url, headers=_cookie_headers(), timeout=30, follow_redirects=True, verify=False)
    resp.raise_for_status()
    html = resp.text
    # 提取 app_token：仅匹配 20+ 位字母数字（排除 "marketplace" 等短词）
    patterns = [
        r'"app_token"\s*:\s*"([A-Za-z0-9]{20,})"',
        r'/base/([A-Za-z0-9]{20,})[?"\']',
        r'"obj_token"\s*:\s*"([A-Za-z0-9]{20,})"',
    ]
    # 排除词列表（导航路径中的非 token 字符串）
    exclude = {"marketplace", "template", "explore", "discover"}
    for pattern in patterns:
        for match in _re.finditer(pattern, html):
            token = match.group(1)
            if token.lower() not in exclude:
                logger.info("从 Wiki 页面提取 app_token: %s", token)
                return token
    raise ValueError("无法从 Wiki 页面提取 app_token，请在 config 中配置 app_token 字段")


def cookie_list_records(app_token: str, table_id: str, view_id: str = None) -> list:
    """Cookie 模式：获取多维表格所有记录

    企业域名会将 API 请求重定向到 my.feishu.cn，Cookie 跨域失效。
    因此改用 Open API（open.feishu.cn），通过 user_access_token 或 tenant_access_token 认证。
    若未配置 token，则报错引导用户配置。
    """
    cfg = _get_bitable_cfg()
    # 优先使用 user_access_token（用户从开发者后台获取）
    user_token = cfg.get("user_access_token", "")
    if not user_token:
        raise ValueError(
            "企业域名 API 重定向导致 Cookie 模式不可用。"
            "请在 config.yaml 中配置以下任一项：\n"
            "  1. app_id + app_secret（推荐，使用 tenant_access_token）\n"
            "  2. user_access_token（从飞书开发者后台获取）\n"
            "参考: https://open.feishu.cn/app -> 创建应用 -> 凭证与基础信息"
        )
    url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {user_token}", "Content-Type": "application/json"}
    params = {"page_size": 500}
    if view_id:
        params["view_id"] = view_id
    all_records = _paginate_get(url, headers, params, "Cookie 模式: 获取 Bitable 记录失败",
                                retry_on_token_expire=True)
    logger.info("Cookie 模式: 获取到 %d 条记录", len(all_records))
    return all_records


# ============ IM 消息监控（Open API，用于监听分析完成通知） ============


def _im_headers() -> dict:
    """构造 IM API 请求头：优先 tenant_access_token（Bot 应用级），回退 user_access_token"""
    cfg = _get_bitable_cfg()
    has_app_cred = cfg.get("app_id") and cfg.get("app_secret")
    if has_app_cred:
        # Bot 应用级 token，权限取决于应用后台配置
        token = get_tenant_access_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # 无应用凭证时回退 user_access_token
    return {"Authorization": f"Bearer {_get_doc_token()}", "Content-Type": "application/json"}


def list_chats(page_size: int = 20, chat_type: str = None) -> list:
    """列出机器人所在的聊天列表（Open API: GET /im/v1/chats）

    先用 tenant_access_token 查群聊，再用 user_access_token 补充单聊。
    :param page_size: 每页数量
    :param chat_type: 可选过滤: 'group'(群聊) / 'p2p'(单聊)，默认返回全部
    :return: [{"chat_id": str, "name": str, "chat_type": str, ...}, ...]
    """
    url = f"{_FEISHU_API}/im/v1/chats"
    base_params = {"page_size": min(page_size, 100)}
    if chat_type:
        base_params["chat_type"] = chat_type
    all_chats = []
    seen_ids = set()
    # 第一步：tenant_access_token 查群聊（稳定，不依赖用户授权）
    try:
        tenant_headers = _im_headers()
        chats = _paginate_get(url, tenant_headers, dict(base_params), "获取群聊列表失败",
                              retry_on_token_expire=True)
        for c in chats:
            cid = c.get("chat_id", "")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                all_chats.append(c)
        logger.info("tenant_access_token 获取到 %d 个聊天", len(chats))
    except Exception as e:
        logger.warning("tenant_access_token 获取聊天失败: %s", e)
    # 第二步：user_access_token 补充单聊（P2P）
    cfg = _get_bitable_cfg()
    user_token = cfg.get("user_access_token", "").strip()
    if user_token:
        try:
            user_headers = {"Authorization": f"Bearer {user_token}", "Content-Type": "application/json"}
            user_chats = _paginate_get(url, user_headers, dict(base_params),
                                       "获取单聊列表失败", retry_on_token_expire=True)
            added = 0
            for c in user_chats:
                cid = c.get("chat_id", "")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    all_chats.append(c)
                    added += 1
            if added:
                logger.info("user_access_token 补充了 %d 个单聊", added)
        except Exception as e:
            logger.warning("user_access_token 获取单聊失败（可能未授权 IM 权限）: %s", e)
    logger.info("共获取到 %d 个聊天", len(all_chats))
    return all_chats


def find_chat_by_name(name_keyword: str) -> str:
    """在群聊列表中按名称关键词查找群聊 ID

    :param name_keyword: 群聊名称关键词（如「数据沉淀」）
    :return: chat_id 字符串，未找到返回空字符串
    """
    chats = list_chats()
    for chat in chats:
        chat_name = chat.get("name", "")
        if name_keyword in chat_name:
            logger.info("找到群聊: name=%s, chat_id=%s", chat_name, chat.get("chat_id"))
            return chat.get("chat_id", "")
    logger.warning("未找到名称包含 '%s' 的群聊，可用群聊: %s",
                   name_keyword, [c.get("name") for c in chats[:10]])
    return ""


def list_messages(chat_id: str, start_time: str = None, page_size: int = 50) -> list:
    """获取聊天消息列表（Open API: GET /im/v1/messages）

    先尝试 tenant_access_token，失败后用 user_access_token。
    :param chat_id: 聊天 ID
    :param start_time: 起始时间戳（秒级 Unix 时间戳字符串），仅返回此时间之后的消息
    :param page_size: 每页消息数
    :return: 消息列表
    """
    url = f"{_FEISHU_API}/im/v1/messages"
    base_params = {
        "container_id_type": "chat",
        "container_id": chat_id,
        "page_size": min(page_size, 50),
        "sort_type": "ByCreateTimeDesc",
    }
    if start_time:
        base_params["start_time"] = start_time
    # 先尝试 tenant_access_token
    try:
        tenant_h = _im_headers()
        logger.info("list_messages: 尝试 tenant_access_token, chat_id=%s", chat_id)
        all_msgs = _paginate_get(url, tenant_h, dict(base_params),
                                 "获取消息列表失败(tenant)", retry_on_token_expire=True)
        logger.info("tenant_access_token 获取到 %d 条消息 (chat=%s)", len(all_msgs), chat_id)
        return all_msgs
    except ValueError as e:
        err_str = str(e)
        logger.warning("tenant_access_token 失败: %s", err_str[:200])
        # 230027=缺少必要权限, 99991679=未授权, Unauthorized=未认证
        is_perm_error = any(kw in err_str for kw in ["99991679", "Unauthorized", "230027", "Lack of necessary"])
        if not is_perm_error:
            raise
    # 回退 user_access_token
    cfg = _get_bitable_cfg()
    user_token = cfg.get("user_access_token", "").strip()
    if not user_token:
        raise ValueError("tenant_access_token 无 IM 消息权限，且无 user_access_token 可用。"
                         "请在飞书开放平台后台开通 im:message:readonly 权限，或重新授权用户")
    logger.info("list_messages: 尝试 user_access_token, chat_id=%s", chat_id)
    user_headers = {"Authorization": f"Bearer {user_token}", "Content-Type": "application/json"}
    all_msgs = _paginate_get(url, user_headers, dict(base_params),
                             "获取消息列表失败(user)", retry_on_token_expire=True)
    logger.info("user_access_token 获取到 %d 条消息 (chat=%s)", len(all_msgs), chat_id)
    return all_msgs


def extract_report_link_from_card(message: dict) -> str:
    """从飞书消息卡片中提取「分析完成通知」的报告链接

    解析 interactive card JSON，查找标题包含「分析完成」的卡片，
    提取「查看分析报告」按钮或链接对应的 URL。
    :return: 报告链接 URL，非目标消息返回空字符串
    """
    import json as _json
    msg_type = message.get("msg_type", "")
    if msg_type != "interactive":
        return ""
    body = message.get("body", {})
    content_str = body.get("content", "")
    if not content_str:
        return ""
    try:
        card = _json.loads(content_str) if isinstance(content_str, str) else content_str
    except (ValueError, TypeError):
        return ""
    # 飞书卡片结构：{"elements": [...], "header": {"title": ...}}
    header = card.get("header", {})
    title = ""
    if isinstance(header, dict):
        title_obj = header.get("title", {})
        title = title_obj.get("content", "") if isinstance(title_obj, dict) else str(title_obj)
    # 标题不包含「分析完成」则跳过
    if "分析完成" not in title:
        return ""
    # 遍历 elements 查找报告链接
    for element in card.get("elements", []):
        # 类型1: 文本元素中的链接（markdown / text + href）
        tag = element.get("tag", "")
        if tag == "div":
            text_obj = element.get("text", {})
            content = text_obj.get("content", "") if isinstance(text_obj, dict) else ""
            # 匹配 markdown 链接: [查看分析报告](url)
            import re as _re
            link_match = _re.search(r'\[([^\]]*报告[^\]]*)\]\(([^)]+)\)', content)
            if link_match:
                return link_match.group(2)
            # 匹配裸 URL
            url_match = _re.search(r'https?://[^\s<>"\']+', content)
            if url_match and "报告" in content:
                return url_match.group(0)
        # 类型2: action 按钮元素
        if tag == "action":
            for action in element.get("actions", []):
                action_text = action.get("text", {})
                text_content = action_text.get("content", "") if isinstance(action_text, dict) else str(action_text)
                if "报告" in text_content or "查看" in text_content:
                    # 按钮的 URL 在 value 或 multi_url 中
                    multi_url = action.get("multi_url", {})
                    if multi_url:
                        urls = multi_url.get("urls", {})
                        return urls.get("default_url") or urls.get("pc_url") or next(iter(urls.values()), "")
                    value = action.get("value", {})
                    if isinstance(value, dict) and value.get("url"):
                        return value["url"]
        # 类型3: note 元素中的链接
        if tag == "note":
            for elem in element.get("elements", []):
                content = elem.get("content", "") if isinstance(elem, dict) else ""
                import re as _re
                url_match = _re.search(r'https?://[^\s<>"\']+', content)
                if url_match:
                    return url_match.group(0)
    logger.warning("卡片标题匹配但未能提取报告链接: title=%s", title)
    return ""


def poll_message_for_report(chat_id: str, after_time: str,
                            poll_interval: int = 15, max_wait: int = 600,
                            cancel_check=None) -> str:
    """轮询飞书消息，等待「分析完成通知」卡片出现并提取报告链接

    :param chat_id: 群聊 ID
    :param after_time: 触发分析时的 Unix 时间戳（秒），仅检查此时间之后的消息
    :param poll_interval: 轮询间隔秒数
    :param max_wait: 最大等待秒数
    :return: 报告链接 URL，超时返回空字符串
    """
    waited = 0
    logger.info("开始轮询飞书消息: chat=%s, after=%s, 间隔=%ds, 最大=%ds",
                chat_id, after_time, poll_interval, max_wait)
    while waited < max_wait:
        if cancel_check and cancel_check():
            logger.info("飞书消息轮询收到取消信号")
            return ""
        try:
            messages = list_messages(chat_id, start_time=after_time, page_size=20)
            for msg in messages:
                link = extract_report_link_from_card(msg)
                if link:
                    create_time = msg.get("create_time", "")
                    logger.info("找到分析完成通知: create_time=%s, link=%s", create_time, link)
                    return link
        except Exception as e:
            logger.warning("轮询飞书消息失败（%ds）: %s", waited, e)
        if _cancellable_sleep(poll_interval, cancel_check):
            logger.info("飞书消息轮询收到取消信号（sleep期间）")
            return ""
        waited += poll_interval
        logger.info("轮询飞书消息: 已等待 %ds/%ds", waited, max_wait)
    logger.warning("飞书消息轮询超时（%ds），未收到分析完成通知", max_wait)
    return ""
