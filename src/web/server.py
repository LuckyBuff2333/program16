"""Web 后端服务：基于 FastAPI 提供配置管理、流程执行、报表查询等 REST API"""
import asyncio
import json
import os
import re
import signal
import threading
from datetime import datetime

import pandas as pd
import yaml
from fastapi import Body, FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src import config as cfg_module
from src import pipeline
from src.clients import ai_log_client, bug_source, jira_client
from src.clients import diana_client as _diana_client
from src.config import get_path, load_config, setup_logger, PROJECT_ROOT
from src.core import audit as audit_module
from src.core import doc_generator

logger = setup_logger("web")
# 前端静态页面所在目录
WEB_DIR = os.path.dirname(os.path.abspath(__file__))

# 流程取消标志：bugid -> bool，用于跨线程通知后端任务停止
_flow_cancel: dict = {}

# 诊断取消标志：bugid -> bool，前端停止按钮或 Ctrl+C 时设置，诊断线程定期检查
_diag_cancel: dict = {}

# 全局中断标志：Ctrl+C 时设为 True，诊断等长时间操作定期检查
_interrupted = False


def _handle_sigint(signum, frame):
    """SIGINT 处理：设置中断标志 + 取消诊断任务，5秒后强制退出整个进程树"""
    global _interrupted
    if _interrupted:
        # 第二次 Ctrl+C：直接系统级退出，os._exit 无法被 asyncio 捕获
        os._exit(1)
    _interrupted = True
    for bugid in list(_diag_cancel):
        _diag_cancel[bugid] = True
    logger.warning("收到 Ctrl+C，正在停止当前操作（再次按 Ctrl+C 强制退出）")
    import threading
    def _force_exit():
        try:
            logger.error("后台操作未能在 5 秒内停止，强制退出")
            # reload 模式下同时终止父进程（reloader），防止自动重启
            ppid = os.getppid()
            if ppid > 0 and ppid != os.getpid():
                try:
                    if sys.platform == 'win32':
                        os.system(f'taskkill /F /T /PID {ppid} >nul 2>&1')
                    else:
                        os.kill(ppid, 2)  # SIGINT
                except Exception:
                    pass
        finally:
            # 无论 taskkill 是否成功，必须确保本进程退出
            os._exit(0)
    threading.Timer(5, _force_exit).start()


def _check_interrupt():
    """检查是否已中断，已中断则抛出异常"""
    if _interrupted:
        raise InterruptedError("用户已按 Ctrl+C 中断操作")


def _check_diag_cancel(bugid: str):
    """检查诊断是否被取消（前端停止按钮或 Ctrl+C），已取消则抛出异常"""
    if _diag_cancel.get(bugid):
        raise InterruptedError(f"诊断已取消: {bugid}")
    if _interrupted:
        raise InterruptedError("用户已按 Ctrl+C 中断操作")

app = FastAPI(title="Bug 文档沉淀工具", docs_url="/api/docs")

# ---- 批量提取触发时间全局停止标志 ----
# 用于前端“停止”按钮优雅中断当前批量提取（SSE流式响应）
_batch_extract_stop_event = threading.Event()
_cache_batch_stop_event = threading.Event()  # 云端缓存批量更新停止标志


@app.on_event("startup")
async def _on_startup():
    """服务启动初始化：过滤 favicon 日志 + 注册 Ctrl+C 处理 + 就绪后打开浏览器"""
    import logging
    import tempfile

    # 注册 Ctrl+C 信号处理（让诊断等阻塞操作可响应中断）
    global _interrupted
    _interrupted = False
    try:
        signal.signal(signal.SIGINT, _handle_sigint)
    except (ValueError, OSError):
        pass  # 非主线程时忽略

    class _AccessFilter(logging.Filter):
        def filter(self, record):
            return "favicon.ico" not in record.getMessage()

    logging.getLogger("uvicorn.access").addFilter(_AccessFilter())

    # 启动飞书机器人长连接客户端（接收机器人消息，命令交互）
    try:
        from src.clients import feishu_client
        feishu_client.start_feishu_ws_client(_feishu_ws_event_handler)
    except Exception as e:
        logger.warning("飞书长连接客户端启动失败（不影响主服务）: %s", e)

    # 初始化昨日播报调度器（如果有已开启的群聊）
    try:
        _init_daily_scheduler()
    except Exception as e:
        logger.warning("每日播报调度器初始化失败（不影响主服务）: %s", e)

    # 服务就绪后打开浏览器（仅首次，reload 时不重复打开）
    _open_url = os.environ.pop("_WEB_OPEN_URL", None)
    if _open_url:
        # 用文件标记防止热重载时重复打开（跨进程有效）
        _flag = os.path.join(tempfile.gettempdir(), ".web_browser_opened")
        if not os.path.exists(_flag):
            import webbrowser
            import threading
            threading.Timer(0.5, lambda: webbrowser.open(_open_url)).start()
            try:
                with open(_flag, "w") as f:
                    f.write("1")
            except Exception:
                pass


@app.on_event("shutdown")
async def _on_shutdown():
    """服务关闭时：设置所有取消标志，让轮询线程快速退出"""
    for bugid in list(_flow_cancel):
        _flow_cancel[bugid] = True
    logger.info("服务关闭，已设置所有流程取消标志")


# 挂载静态文件目录（JS/CSS 等前端资源）
_static_dir = os.path.join(WEB_DIR, "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# 文档图片资源目录
_DOC_IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "docs", "assets")


@app.get("/api/doc-images/{bugid}/{filename}")
async def serve_doc_image(bugid: str, filename: str):
    """服务飞书文档下载的图片资源"""
    from starlette.responses import FileResponse
    filepath = os.path.join(_DOC_IMAGES_DIR, bugid, filename)
    if not os.path.isfile(filepath):
        return JSONResponse({"ok": False, "message": "图片不存在"}, status_code=404)
    return FileResponse(filepath)

# 内存缓存：存放上传文件解析后的行数据，key 为 file_id
_uploaded_files = {}


def _ok(data=None, message: str = "success"):
    """统一成功响应格式"""
    return {"ok": True, "message": message, "data": data}


def _fail(message: str, extra: dict = None):
    """统一失败响应格式"""
    data = {"ok": False, "message": message}
    if extra:
        data.update(extra)
    return JSONResponse(content=data, status_code=200)


def _parse_conf(val) -> float:
    """安全解析置信度值，返回 float，解析失败返回 0"""
    try:
        v = float(str(val).strip() or "0")
        return v if not (v != v) else 0  # NaN 检查
    except (ValueError, TypeError):
        return 0.0


# OAuth2 回调缓存：授权码 → user_access_token
_oauth_cache = {"code": None, "token": None}


def _save_user_token_to_config(user_token: str, refresh_token: str):
    """将 user_access_token 保存到 config.yaml"""
    config_path = cfg_module.CONFIG_PATH
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data.setdefault("feishu_bitable", {})["user_access_token"] = user_token
    if refresh_token:
        data["feishu_bitable"]["user_refresh_token"] = refresh_token
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    logger.info("user_access_token 已保存到配置文件")


@app.get("/api/auth/authorize")
async def get_authorize_url():
    """生成飞书 OAuth 授权链接（含文档+表格+云文档权限）"""
    cfg = load_config().get("feishu_bitable", {})
    app_id = cfg.get("app_id", "")
    scopes = "bitable:app docx:document docx:document:readonly sheets:spreadsheet:readonly drive:drive drive:drive:readonly im:chat:readonly im:message:readonly im:message.p2p_msg:get_as_user im:message.group_msg:get_as_user wiki:wiki"
    redirect_uri = "http://localhost:8060/api/callback"
    url = (f"https://open.feishu.cn/open-apis/authen/v1/authorize"
           f"?app_id={app_id}&redirect_uri={redirect_uri}&scope={scopes}")
    return _ok({"authorize_url": url}, "请点击链接完成授权")


@app.post("/api/shutdown")
async def shutdown_server():
    """优雅关闭服务：发送 Ctrl+C 信号让整个进程组正常退出"""
    import asyncio
    import tempfile
    logger.info("收到关闭请求，正在优雅退出...")
    # 清除浏览器打开标记，下次启动可重新打开
    _flag = os.path.join(tempfile.gettempdir(), ".web_browser_opened")
    try:
        if os.path.exists(_flag):
            os.remove(_flag)
    except Exception:
        pass

    def _do_shutdown():
        if os.name == "nt":
            os.kill(0, signal.CTRL_C_EVENT)
        else:
            os.kill(os.getpid(), signal.SIGINT)

    loop = asyncio.get_event_loop()
    loop.call_later(0.3, _do_shutdown)
    return _ok(message="服务正在关闭...")


@app.post("/api/restart")
async def restart_server():
    """重启 worker：只终止当前 worker，reloader 会自动拉起新 worker 加载最新代码"""
    import asyncio
    import sys
    logger.info("收到重启请求，终止 worker 让 reloader 自动重启...")
    loop = asyncio.get_event_loop()
    loop.call_later(0.3, lambda: sys.exit(0))
    return _ok(message="worker 正在终止，reloader 将自动重启...")


def _save_user_token_to_config(user_token: str, refresh_token: str):
    """将 OAuth 授权获取的 user_access_token 保存到 config.yaml"""
    import yaml
    from src.config import CONFIG_PATH
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    config.setdefault("feishu_bitable", {})["user_access_token"] = user_token
    if refresh_token:
        config["feishu_bitable"]["user_refresh_token"] = refresh_token
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    # 清除配置缓存，确保后续读取到新 token
    import src.config as _cfg_module
    _cfg_module._CONFIG = None
    logger.info("user_access_token 已保存到配置")


@app.get("/api/callback")
async def oauth_callback(code: str = "", error: str = ""):
    """飞书 OAuth2 回调：接收授权码并换取 user_access_token"""
    import httpx as _httpx
    logger.info("OAuth 回调触发: code=%s, error=%s", bool(code), error)
    if error:
        logger.error("OAuth 授权失败: %s", error)
        return JSONResponse(content={"ok": False, "message": f"授权失败: {error}"}, status_code=200)
    if not code:
        logger.error("OAuth 回调未收到授权码")
        return JSONResponse(content={"ok": False, "message": "未收到授权码"}, status_code=200)
    # 用授权码换取 user_access_token
    cfg = load_config().get("feishu_bitable", {})
    url = "https://open.feishu.cn/open-apis/authen/v1/oidc/access_token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
    }
    # 先获取 app_access_token
    token_url = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
    token_resp = _httpx.post(token_url, json={
        "app_id": cfg.get("app_id", ""),
        "app_secret": cfg.get("app_secret", ""),
    }, timeout=10, verify=False)
    app_token = token_resp.json().get("app_access_token", "")
    logger.info("获取 app_access_token: %s", "成功" if app_token else "失败")
    # 换取 user_access_token
    resp = _httpx.post(url, json=payload, headers={
        "Authorization": f"Bearer {app_token}",
        "Content-Type": "application/json",
    }, timeout=10, verify=False)
    data = resp.json()
    logger.info("换取 user_access_token 响应: code=%s", data.get("code"))
    if data.get("code") == 0:
        user_token = data.get("data", {}).get("access_token", "")
        refresh_token = data.get("data", {}).get("refresh_token", "")
        expire = data.get("data", {}).get("expires_in", 7200)
        scope = data.get("data", {}).get("scope", "")
        logger.info("OAuth 授权成功: scope=%s, expires_in=%ds, token_prefix=%s", scope, expire, user_token[:20])
        _oauth_cache["token"] = user_token
        _oauth_cache["code"] = code
        # 自动保存到 config.yaml
        _save_user_token_to_config(user_token, refresh_token)
        html = (f"<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                f"<h2 style='color:#67c23a'>✅ 授权成功</h2>"
                f"<p>scope: <code>{scope}</code></p>"
                f"<p>有效期: {expire}s</p>"
                f"<p style='color:#999'>请关闭此页面，回到测试页面点击「列出所有聊天」</p>"
                f"</body></html>")
        return HTMLResponse(content=html, status_code=200)
    logger.error("换取 user_access_token 失败: %s", data.get("msg"))
    return JSONResponse(content={"ok": False, "message": f"换取 token 失败: {data.get('msg')}"}, status_code=200)


# ========== 飞书事件订阅（接收机器人消息） ==========

# 最近收到的所有消息（调试用，最多保留 50 条）
_feishu_recent_messages: list = []


def _process_feishu_message_event(event_data: dict):
    """处理飞书 im.message.receive_v1 事件（HTTP回调 和 长连接 共用）"""
    import re as _re
    from src.clients import feishu_client as _fc
    msg = event_data.get("message", {})
    sender = event_data.get("sender", {})
    chat_id = msg.get("chat_id", "")
    msg_type = msg.get("message_type", "")
    content_str = msg.get("content", "")
    sender_id = sender.get("sender_id", {}).get("open_id", "")
    sender_type = sender.get("sender_type", "")
    create_time = msg.get("create_time", "")
    logger.info("飞书消息事件: chat_id=%s, type=%s, sender=%s(%s)", chat_id, msg_type, sender_id[:12], sender_type)
    # 记录所有收到的消息（调试用）
    content_preview = content_str[:200] if content_str else ""
    _feishu_recent_messages.append({
        "chat_id": chat_id, "msg_type": msg_type, "sender_id": sender_id,
        "sender_type": sender_type, "time": create_time, "content_preview": content_preview
    })
    if len(_feishu_recent_messages) > 50:
        _feishu_recent_messages.pop(0)
    # 解析卡片消息提取报告链接
    if msg_type != "interactive" or not content_str:
        return
    try:
        card = json.loads(content_str)
        card_header = card.get("header", {})
        title = ""
        if isinstance(card_header, dict):
            title_obj = card_header.get("title", {})
            title = title_obj.get("content", "") if isinstance(title_obj, dict) else str(title_obj)
        # 查找报告链接
        report_link = ""
        for element in card.get("elements", []):
            if element.get("tag") == "div":
                text_content = (element.get("text", {}) or {}).get("content", "")
                link_match = _re.search(r'\[([^\]]*报告[^\]]*)\]\(([^)]+)\)', text_content)
                if link_match:
                    report_link = link_match.group(2)
                else:
                    url_match = _re.search(r'https?://[^\s<>"\']+', text_content)
                    if url_match and "报告" in text_content:
                        report_link = url_match.group(0)
            if element.get("tag") == "action":
                for action in element.get("actions", []):
                    multi_url = action.get("multi_url", {})
                    if multi_url and multi_url.get("android_url"):
                        report_link = multi_url["android_url"]
        # 存储卡片事件（所有带报告链接的卡片，不限 bugid）
        if report_link:
            event_info = {
                "link": report_link, "time": msg.get("create_time", ""),
                "chat_id": chat_id, "title": title
            }
            # 按 bugid 存储（如果 URL 含 bugid）
            bugid_match = _re.search(r'([A-Z]+-\d+)', report_link)
            if bugid_match:
                bugid = bugid_match.group(1)
                _fc._feishu_events[bugid] = event_info
            # 同时存入时间排序列表，用于时间匹配
            _fc._feishu_card_events.append(event_info)
            if len(_fc._feishu_card_events) > 100:
                _fc._feishu_card_events.pop(0)
            _fc._save_persisted_events()  # 持久化到文件，防止重启丢失
            logger.info("飞书卡片事件存储: title=%s, link=%s", title[:30], report_link[:60])
    except Exception as e:
        logger.warning("解析飞书消息卡片失败: %s", e)


# ========== 飞书机器人命令交互（测试页能力远程化）==========

# 会话状态机：chat_id -> {"state": "wait_jira"}，引导式对话（输入1→提示输入Jira号→执行）
_bot_sessions: dict = {}
# 分号命令链式执行：中间命令静默模式，仅最后一条展示反馈
_bot_silent_mode = False


def _feishu_ws_event_handler(data):
    """长连接统一事件回调：文本消息→机器人命令；卡片消息→复用现有报告链接解析"""
    global _bot_silent_mode
    try:
        msg = data.event.message
        msg_type = msg.message_type
        if msg_type == "text":
            content = json.loads(msg.content or "{}")
            raw_text = content.get("text", "")
            # 去除飞书回复引用（“| 回复 用户名: 引用内容”及后续引用行）
            if "| 回复" in raw_text:
                mention_match = re.search(r"@_user_\d+", raw_text)
                if mention_match:
                    # 有 @提及：提及后的文本是用户实际输入
                    raw_text = raw_text[mention_match.end():]
                else:
                    # 无 @提及：跳过所有以 | 开头的行
                    lines = raw_text.split("\n")
                    user_lines = [l for l in lines if not l.startswith("|")]
                    raw_text = "\n".join(user_lines)
            # 去除群聊 @机器人 的 mention 占位符与首尾标点，保留纯命令文本（兼容 "@机器人，1" 等输入）
            text = re.sub(r"@_user_\d+", "", raw_text).strip().strip(" \t,，.。!！")
            if "| \u56de\u590d" in content.get("text", ""):
                logger.info("\u56de\u590d\u6d88\u606f\u89e3\u6790: raw=%s, parsed=%s", content.get("text", "")[:100], text[:60])
            if text:
                # 支持分号分隔的链式命令（如 0;1;2026-09-20），中间命令静默，仅展示最后一级反馈
                parts = [p.strip() for p in re.split(r'[;；]', text) if p.strip()]
                if len(parts) > 1:
                    from src.clients import feishu_client as _fc
                    _orig_send = _fc.send_bot_message
                    try:
                        for i, part in enumerate(parts):
                            _bot_silent_mode = (i < len(parts) - 1)
                            if _bot_silent_mode:
                                _fc.send_bot_message = lambda *a, **kw: True
                            else:
                                _fc.send_bot_message = _orig_send
                            _process_bot_command(msg.chat_id, part)
                    finally:
                        _fc.send_bot_message = _orig_send
                        _bot_silent_mode = False
                else:
                    _process_bot_command(msg.chat_id, text)
        elif msg_type == "interactive":
            # 卡片事件（AI分析完成通知）走现有解析链路，兼容 dict 结构
            _process_feishu_message_event({
                "message": {"chat_id": msg.chat_id, "message_type": msg_type,
                            "content": msg.content, "create_time": msg.create_time},
                "sender": {},
            })
    except Exception as e:
        _bot_silent_mode = False
        logger.warning("处理飞书长连接事件失败: %s", e)


# 机器人会话超时时间（秒）
_BOT_SESSION_TIMEOUT = 120

# 任务取消标记：{chat_id: Event}，设置时表示用户发送了"退出"
_bot_cancel_events: dict = {}
# 当前正在执行的任务描述：{chat_id: 任务名称}
_bot_running_tasks: dict = {}


def _get_cancel_event(chat_id: str):
    """获取或创建该 chat_id 的取消事件"""
    import threading
    if chat_id not in _bot_cancel_events:
        _bot_cancel_events[chat_id] = threading.Event()
    return _bot_cancel_events[chat_id]


def _reset_cancel_event(chat_id: str):
    """重置取消标记（新任务开始时调用）"""
    evt = _bot_cancel_events.get(chat_id)
    if evt:
        evt.clear()


def _set_running_task(chat_id: str, task_desc: str):
    """标记当前 chat_id 正在执行的任务名称"""
    _bot_running_tasks[chat_id] = task_desc
    _reset_cancel_event(chat_id)


def _clear_running_task(chat_id: str):
    """清除当前 chat_id 的任务标记"""
    _bot_running_tasks.pop(chat_id, None)


def _is_cancelled(chat_id: str) -> bool:
    """检查当前任务是否被用户取消"""
    evt = _bot_cancel_events.get(chat_id)
    return evt.is_set() if evt else False


def _set_bot_session(chat_id: str, state: str, **kwargs):
    """设置机器人会话状态并启动 2 分钟自动超时定时器"""
    import threading
    # 取消旧的定时器
    old = _bot_sessions.get(chat_id)
    if old and old.get("timer"):
        old["timer"].cancel()
    # 设置新会话
    session_data = {"state": state, "created_at": datetime.now(), "timer": None}
    session_data.update(kwargs)
    _bot_sessions[chat_id] = session_data
    # 启动超时定时器
    def _on_timeout():
        cur = _bot_sessions.get(chat_id)
        if cur and cur.get("state"):
            _bot_sessions.pop(chat_id, None)
            try:
                from src.clients import feishu_client
                feishu_client.send_bot_message(chat_id, "会话已超时（2分钟无操作），已自动取消。\n发送“帮助”查看可用功能")
            except Exception:
                pass
    timer = threading.Timer(_BOT_SESSION_TIMEOUT, _on_timeout)
    timer.daemon = True
    timer.start()
    _bot_sessions[chat_id]["timer"] = timer


def _clear_bot_session(chat_id: str):
    """清除机器人会话并取消定时器"""
    old = _bot_sessions.pop(chat_id, None)
    if old and old.get("timer"):
        old["timer"].cancel()


def _process_bot_command(chat_id: str, text: str):
    """机器人命令状态机：支持子功能菜单（1.1/1.2/6.1/7.1等）"""
    import threading
    from src.clients import feishu_client
    # 链式命令中间步骤：静默执行，不发送任何消息（由事件处理器负责恢复）
    if _bot_silent_mode:
        feishu_client.send_bot_message = lambda *a, **kw: True
    session = _bot_sessions.get(chat_id)
    logger.info("机器人收到命令: chat=%s, text=%s", chat_id[:12], text[:60])

    # 退出命令：取消当前运行中的任务 或 清除会话等待状态
    if text.strip() in ("退出", "取消", "exit", "cancel", "stop"):
        task_desc = _bot_running_tasks.get(chat_id)
        if task_desc:
            # 有任务正在运行，设置取消标记并立即中断
            _get_cancel_event(chat_id).set()
            _bot_running_tasks.pop(chat_id, None)
            _clear_bot_session(chat_id)
            feishu_client.send_bot_message(chat_id,
                f"已中断任务：{task_desc}")
        elif session and session.get("state"):
            # 处于会话等待状态，清除会话
            state = session.get("state", "")
            _clear_bot_session(chat_id)
            feishu_client.send_bot_message(chat_id,
                f"已退出当前操作。\n发送「菜单」查看可用功能")
        else:
            feishu_client.send_bot_message(chat_id,
                "当前无运行中的任务。\n发送「菜单」查看可用功能")
        return

    # 帮助/功能菜单：显示菜单并等待子功能输入
    if any(kw in text for kw in ("功能", "帮助", "菜单", "help")):
        _set_bot_session(chat_id, "wait_menu")
        feishu_client.send_bot_message(chat_id,
            "当前可用功能：\n"
            "0. 工作日结论播报（单次/定时/状态）\n"
            "4.1 置信度批量写入（根因语义对比）\n"
            "5.1 失败批量排查（按时间）\n"
            "5.2 单个Jira诊断归类\n"
            "6.1.1 JQL批量执行（JQL编号,数量,PC/线上）\n"
            "6.1.2 CSV批量执行（选文件后自动执行）\n"
            "6.2 单个执行（Jira号,PC/线上）\n"
            "9.1 Bug未分析提取（JQL）\n"
            "10.1 线上批量执行（输入Jira号）\n\n"
            "发送「退出」可取消当前任务\n"
            "请输入子功能编号（如 0/6.1.1）唤醒对应功能（2分钟内有效）")
        return

    if session and session.get("state") == "wait_menu":
        stripped = text.strip()
        # 支持子功能编号直接跳转（0/4/5/6/9/10，支持6.1.1等三级编号）
        if re.match(r'^(0|4|5|6|9|10)\.\d(\.\d)?$', stripped):
            _clear_bot_session(chat_id)
            text = stripped  # 继续往下执行，让子功能处理逻辑接管
        elif stripped in ("0", "4", "5", "6", "9", "10"):
            _clear_bot_session(chat_id)
            text = stripped
        else:
            return  # 非子功能输入，忽略并保持等待

    # 快捷日期输入：直接触发每日播报单次执行（如 2026-09-21）
    _date_match = re.match(r'^(\d{4}[-／\/.\u5e74]\d{1,2}[-／\/.\u6708]\d{1,2})日?$', text.strip())
    if _date_match:
        _clear_bot_session(chat_id)
        _raw = _date_match.group(1)
        for sep in ['／', '/', '.', '年', '月']:
            _raw = _raw.replace(sep, '-')
        try:
            _dt = datetime.strptime(_raw, "%Y-%m-%d")
            date_str = _dt.strftime("%Y-%m-%d")
        except ValueError:
            feishu_client.send_bot_message(chat_id, "日期格式错误，请输入如 2026-09-21")
            return
        _set_running_task(chat_id, f"结论播报({date_str})")
        threading.Thread(target=_bot_daily_broadcast, args=(chat_id, date_str, False),
                         name=f"bot-daily-{date_str}", daemon=True).start()
        return

    # ==================== 功能0：每日结论播报 ====================
    if text == "0":
        _set_bot_session(chat_id, "wait_daily_broadcast_menu")
        feishu_client.send_bot_message(chat_id,
            "工作日结论播报\n子功能：\n"
            "1. 单次（查询指定日期的结论汇总）\n"
            "2. 定时设置（设置播报时间，工作日自动触发）\n"
            "3. 状态设置（开启/关闭当前群聊播报）\n"
            "4. 每周汇总（本周统计）\n\n"
            "请输入子功能编号（1/2/3/4）")
        return

    if session and session.get("state") == "wait_daily_broadcast_menu":
        choice = text.strip()
        if choice == "1":
            _set_bot_session(chat_id, "wait_daily_date")
            feishu_client.send_bot_message(chat_id, "请输入日期（如 2026-09-19）\n默认查询当天")
            return
        elif choice == "2":
            _set_bot_session(chat_id, "wait_daily_time")
            feishu_client.send_bot_message(chat_id, "请输入每日汇报时间（如 17:50）")
            return
        elif choice == "3":
            _set_bot_session(chat_id, "wait_daily_status")
            feishu_client.send_bot_message(chat_id, "请输入：\n1：开启\n2：关闭\n\n状态仅对当前群聊有效，其他群聊默认关闭")
            return
        elif choice == "4":
            _clear_bot_session(chat_id)
            today = datetime.now().strftime("%Y-%m-%d")
            _set_running_task(chat_id, f"每周汇总({today})")
            threading.Thread(target=_bot_weekly_broadcast, args=(chat_id, today),
                             name=f"bot-weekly-{today}", daemon=True).start()
            return
        else:
            feishu_client.send_bot_message(chat_id, "请输入 1/2/3/4")
            return

    # 快捷命令：0.4 直接触发每周汇总
    if text in ("0.4",):
        _clear_bot_session(chat_id)
        today = datetime.now().strftime("%Y-%m-%d")
        _set_running_task(chat_id, f"每周汇总({today})")
        threading.Thread(target=_bot_weekly_broadcast, args=(chat_id, today),
                         name=f"bot-weekly-{today}", daemon=True).start()
        return

    if session and session.get("state") == "wait_daily_date":
        date_str = text.strip()
        if not date_str or date_str in ("今天", "今日"):
            date_str = datetime.now().strftime("%Y-%m-%d")
        else:
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                feishu_client.send_bot_message(chat_id, "日期格式错误，请输入如 2026-09-19")
                return
        _clear_bot_session(chat_id)
        _set_running_task(chat_id, f"结论播报({date_str})")
        threading.Thread(target=_bot_daily_broadcast, args=(chat_id, date_str, False),
                         name=f"bot-daily-{date_str}", daemon=True).start()
        return

    if session and session.get("state") == "wait_daily_time":
        time_str = text.strip().replace("：", ":")  # 兼容中文冒号
        if not re.match(r'^\d{1,2}:\d{2}$', time_str):
            feishu_client.send_bot_message(chat_id, "时间格式错误，请输入如 17:50")
            return
        _clear_bot_session(chat_id)
        cfg = _load_daily_broadcast_config()
        old_time = cfg.get(chat_id, {}).get("report_time", "")
        cfg.setdefault(chat_id, {})
        cfg[chat_id]["report_time"] = time_str
        cfg[chat_id]["enabled"] = True
        _save_daily_broadcast_config(cfg)
        _restart_daily_scheduler()
        if old_time and old_time != time_str:
            tip = f"（已覆盖原设置 {old_time}）"
        else:
            tip = ""
        feishu_client.send_bot_message(chat_id,
            f"设置成功{tip}\n每个工作日 {time_str} 自动汇报结论汇总（含调休补班）\n"
            f"状态：已开启\n可重复输入 0→2 重新设置时间\n发送「菜单」返回功能列表")
        return

    if session and session.get("state") == "wait_daily_status":
        choice = text.strip()
        if choice not in ("1", "2"):
            feishu_client.send_bot_message(chat_id, "请输入 1（开启）或 2（关闭）")
            return
        _clear_bot_session(chat_id)
        cfg = _load_daily_broadcast_config()
        cfg.setdefault(chat_id, {})
        if choice == "1":
            cfg[chat_id]["enabled"] = True
            _save_daily_broadcast_config(cfg)
            _restart_daily_scheduler()
            report_time = cfg[chat_id].get("report_time", "17:50")
            feishu_client.send_bot_message(chat_id,
                f"开启成功\n工作日 {report_time} 将自动输出结论汇总\n"
                f"点击查看详情：{get_daily_report_url()}")
        else:
            cfg[chat_id]["enabled"] = False
            _save_daily_broadcast_config(cfg)
            _restart_daily_scheduler()
            feishu_client.send_bot_message(chat_id, "已关闭当前群聊的工作日结论播报")
        return

    # ==================== 功能4：置信度批量写入 ====================
    if text == "4" or text == "4.1":
        _set_bot_session(chat_id, "wait_confidence_batch")
        feishu_client.send_bot_message(
            chat_id, "4.1 置信度批量写入\n请输入筛选条件：\n"
                     "· 直接发送“开始”执行全量\n"
                     "· 发送时间（如 2026-09-10 19:00:00）筛选该时间之后的记录\n"
                     "· 发送“空”仅处理置信度为空的记录")
        return

    if session and session.get("state") == "wait_confidence_batch":
        input_text = text.strip()
        after_time = ""
        only_empty = False
        if input_text in ("开始", "全部", "all"):
            pass  # 全量执行
        elif input_text == "空":
            only_empty = True
        else:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    _ts = datetime.strptime(input_text, fmt)
                    after_time = _ts.strftime("%Y-%m-%d %H:%M:%S")
                    break
                except ValueError:
                    continue
            else:
                feishu_client.send_bot_message(chat_id, "格式错误，请发送“开始”、“空”或时间（如 2026-09-10 19:00:00）")
                return
        _clear_bot_session(chat_id)
        feishu_client.send_bot_message(chat_id, f"置信度批量写入执行中（筛选: {after_time or '全量'}{', 仅空值' if only_empty else ''}）\n请稍候...")
        _set_running_task(chat_id, f"置信度批量写入({after_time or '全量'})")
        threading.Thread(target=_bot_confidence_batch, args=(chat_id, after_time, only_empty),
                         name="bot-confidence-batch", daemon=True).start()
        return

    # ==================== 功能5：AI日志分析失败批量排查 ====================
    if text == "5" or text == "5.1":
        _set_bot_session(chat_id, "wait_troubleshoot")
        feishu_client.send_bot_message(
            chat_id, "5.1 失败批量排查（按时间）\n请输入排查时间（如 2026-09-10 19:00:00）\n\n默认提取分析失败结果且自动jira去重")
        return

    if text == "5.2":
        _set_bot_session(chat_id, "wait_diag_single")
        feishu_client.send_bot_message(
            chat_id, "5.2 单个Jira诊断归类\n请输入 Jira 号（多个用逗号隔开）\n示例：VCU-538942,VCU-200273")
        return

    if session and session.get("state") == "wait_troubleshoot":
        time_str = text.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                _ts = datetime.strptime(time_str, fmt)
                time_str = _ts.strftime("%Y-%m-%d %H:%M:%S")
                break
            except ValueError:
                continue
        else:
            feishu_client.send_bot_message(chat_id, "时间格式错误，请输入如 2026-09-10 19:00:00")
            return
        _clear_bot_session(chat_id)
        feishu_client.send_bot_message(chat_id, f"已收到排查时间: {time_str}\n执行中，请稍候（查询+诊断可能需要几分钟）...")
        _set_running_task(chat_id, f"失败批量排查(时间:{time_str})")
        threading.Thread(target=_bot_run_troubleshoot, args=(chat_id, time_str),
                         name="bot-troubleshoot", daemon=True).start()
        return

    if session and session.get("state") == "wait_diag_single":
        bugids = _parse_bugids(text)
        if not bugids:
            feishu_client.send_bot_message(chat_id, "未解析到 Jira 号，请重新输入")
            return
        _clear_bot_session(chat_id)
        feishu_client.send_bot_message(chat_id, f"已收到 {len(bugids)} 个 Jira 号：{','.join(bugids)}\n诊断归类中，请稍候...")
        _set_running_task(chat_id, f"Jira诊断归类({len(bugids)}个)")
        threading.Thread(target=_bot_diag_single, args=(chat_id, bugids),
                         name="bot-diag-single", daemon=True).start()
        return

    # ==================== 功能6：PC侧AI日志分析批量执行 ====================
    if text == "6" or text == "6.1":
        feishu_client.send_bot_message(chat_id,
            "PC侧AI日志分析批量执行\n"
            "子功能：\n"
            "6.1.1 JQL批量执行（JQL编号,数量,PC/线上）\n"
            "6.1.2 CSV批量执行（选文件后自动执行）\n"
            "6.2 单个执行（Jira号,PC/线上）\n\n"
            "请输入子功能编号")
        return

    # 6.1.1 JQL批量执行 → 子菜单
    if text == "6.1.1":
        _set_bot_session(chat_id, "wait_sub_menu", cmd="6.1.1")
        feishu_client.send_bot_message(chat_id,
            "6.1.1 JQL批量执行\n请输入功能：\n1: 基础信息修改\n2: 通用链路")
        return

    # 6.1.2 CSV批量执行 → 子菜单
    if text == "6.1.2":
        _set_bot_session(chat_id, "wait_sub_menu", cmd="6.1.2")
        feishu_client.send_bot_message(chat_id,
            "6.1.2 CSV批量执行\n请输入功能：\n1: 基础信息修改\n2: 通用链路")
        return

    # ========== 共享状态处理器：子菜单/基础信息修改/过滤选项 ==========

    # 子菜单选择（6.1.1/6.1.2/10.1共用）
    if session and session.get("state") == "wait_sub_menu":
        cmd = session.get("cmd", "")
        choice = text.strip()
        if choice == "1":
            # 基础信息修改：根据功能判断默认模式
            mode = "online" if cmd == "10.1" else "pc"
            defaults = {"analysis_concurrency": "5", "download_concurrency": "2", "model": "deepseek-v-pro", "trigger_source": "线上"} if mode == "online" else {"analysis_concurrency": "10", "download_concurrency": "4", "model": "deepseek-v-pro", "trigger_source": "PC"}
            meta = session.get("batch_meta", defaults)
            _set_bot_session(chat_id, "wait_batch_meta", cmd=cmd, batch_meta=meta)
            feishu_client.send_bot_message(chat_id,
                f"当前基础信息：\n1. 分析并发数: {meta.get('analysis_concurrency', '10')}\n"
                f"2. 下载并发数: {meta.get('download_concurrency', '4')}\n"
                f"3. 模型: {meta.get('model', 'deepseek-v-pro')}\n"
                f"4. 触发来源: {meta.get('trigger_source', 'PC')}\n\n"
                f"输入序号+新值修改（如：1,5），输入「确认」保存并返回")
            return
        elif choice == "2":
            # 通用链路
            if cmd == "6.1.1":
                _set_bot_session(chat_id, "wait_filter_options", cmd=cmd, batch_meta=session.get("batch_meta", {}))
                feishu_client.send_bot_message(chat_id,
                    "请选择过滤（多个用逗号分隔，如A1,A3）：\n"
                    "☑ A0: 过滤表中所有记录\n☐ A1: 过滤PC正确和通用失败的\n"
                    "☐ A2: 过滤线上正确和通用失败的\n☐ A3: 过滤AI初步分析结果\n\n"
                    "默认勾选A0，输入「默认」使用默认勾选")
            elif cmd == "6.1.2":
                _set_bot_session(chat_id, "wait_csv_filter_options", batch_meta=session.get("batch_meta", {}))
                feishu_client.send_bot_message(chat_id,
                    "请选择过滤（多个用逗号分隔，如A1,A3）：\n"
                    "☑ A0: 过滤表中所有记录\n☐ A1: 过滤PC正确和通用失败的\n"
                    "☐ A2: 过滤线上正确和通用失败的\n☐ A3: 过滤AI初步分析结果\n\n"
                    "默认勾选A0，输入「默认」使用默认勾选")
            elif cmd == "10.1":
                _set_bot_session(chat_id, "wait_prod_filter_options", batch_meta=session.get("batch_meta", {}), skip_duplicates=True)
                feishu_client.send_bot_message(chat_id,
                    "请选择过滤（多个用逗号分隔，如A1,A3）：\n"
                    "☐ A0: 过滤表中所有记录\n☐ A1: 过滤PC正确和通用失败的\n"
                    "☐ A2: 过滤线上正确和通用失败的\n☑ A3: 过滤AI初步分析结果\n\n"
                    "默认勾选A3，输入「默认」使用默认勾选")
            else:
                feishu_client.send_bot_message(chat_id, "未知功能，请重新输入")
                _clear_bot_session(chat_id)
            return
        else:
            feishu_client.send_bot_message(chat_id, "请输入 1（基础信息修改）或 2（通用链路）")
            return

    # 基础信息修改（共用）
    if session and session.get("state") == "wait_batch_meta":
        cmd = session.get("cmd", "")
        meta = dict(session.get("batch_meta", {}))
        stripped = text.strip()
        if stripped in ("确认", "确定", "ok", "保存"):
            _set_bot_session(chat_id, "wait_sub_menu", cmd=cmd, batch_meta=meta)
            feishu_client.send_bot_message(chat_id,
                f"基础信息已保存：\n分析并发: {meta.get('analysis_concurrency')}\n"
                f"下载并发: {meta.get('download_concurrency')}\n模型: {meta.get('model')}\n"
                f"触发来源: {meta.get('trigger_source')}\n\n请输入功能：\n1: 基础信息修改\n2: 通用链路")
            return
        m = re.match(r'(\d+)\s*[,，]\s*(.+)', stripped)
        if m:
            field_map = {"1": "analysis_concurrency", "2": "download_concurrency", "3": "model", "4": "trigger_source"}
            key = field_map.get(m.group(1))
            if key:
                meta[key] = m.group(2).strip()
                _set_bot_session(chat_id, "wait_batch_meta", cmd=cmd, batch_meta=meta)
                feishu_client.send_bot_message(chat_id,
                    f"已修改 {key}: {meta[key]}\n\n当前基础信息：\n1. 分析并发数: {meta.get('analysis_concurrency')}\n"
                    f"2. 下载并发数: {meta.get('download_concurrency')}\n3. 模型: {meta.get('model')}\n"
                    f"4. 触发来源: {meta.get('trigger_source')}\n\n继续修改或输入「确认」保存")
                return
        feishu_client.send_bot_message(chat_id, "格式错误，请输入「序号,新值」（如：1,5）或「确认」保存")
        return

    # 6.1.1 过滤选项处理
    if session and session.get("state") == "wait_filter_options":
        filters = _parse_filter_input(text)
        meta = session.get("batch_meta", {})
        jql_presets = _get_jql_presets()
        jql_desc = "\n".join(f"{i+1}. {v[0]}({k})" for i, (k, v) in enumerate(jql_presets.items()))
        _set_bot_session(chat_id, "wait_batch_jql_filter", filters=filters, batch_meta=meta)
        feishu_client.send_bot_message(chat_id,
            f"过滤已设置：{filters.get('desc', '默认')}\n\n"
            f"可用JQL：\n{jql_desc}\n\n"
            f"请输入：JQL编号,抽取数量,PC/线上\n示例: JQL1,50,PC")
        return

    # 6.1.1 JQL执行输入处理
    if session and session.get("state") == "wait_batch_jql_filter":
        m = re.match(r"(jql\s*\d+)\s*[,，]\s*(\d+)\s*[,，]\s*(pc|线上|online)", text, re.I)
        if not m:
            feishu_client.send_bot_message(chat_id, "格式错误，请输入「JQL编号,数量,PC/线上」\n示例: JQL1,50,PC")
            return
        jql_key = m.group(1).replace(" ", "").upper()
        count = int(m.group(2))
        exec_mode = "online" if m.group(3).lower() in ("online", "线上") else "pc"
        if count <= 0:
            feishu_client.send_bot_message(chat_id, "抽取数量必须大于 0")
            return
        jql_presets = _get_jql_presets()
        if jql_key not in jql_presets:
            feishu_client.send_bot_message(chat_id, f"未找到 {jql_key}，可用：{','.join(jql_presets.keys())}")
            return
        filters = session.get("filters", {})
        meta = session.get("batch_meta", {})
        _clear_bot_session(chat_id)
        mode_label = "线上" if exec_mode == "online" else "PC"
        label = jql_presets[jql_key][0]
        feishu_client.send_bot_message(chat_id,
            f"{jql_key}({label}) 开始执行\n抽取 {count} 条，{mode_label}模式\n"
            f"过滤：{filters.get('desc', '默认')}\n发送「退出」可中断任务")
        _set_running_task(chat_id, f"JQL批量执行({jql_key},{count}条,{mode_label})")
        threading.Thread(target=_bot_run_batch_ai, args=(chat_id, jql_key, count, exec_mode, filters, meta),
                         name=f"bot-batch-{jql_key}", daemon=True).start()
        return

    # 6.1.2 CSV过滤选项处理
    if session and session.get("state") == "wait_csv_filter_options":
        filters = _parse_filter_input(text)
        meta = session.get("batch_meta", {})
        # 自动扫描CSV文件
        import csv as _csv
        csv_files = []
        if os.path.isdir(_UNANALYZED_DIR):
            for fname in sorted(os.listdir(_UNANALYZED_DIR), reverse=True):
                if not fname.endswith(".csv"):
                    continue
                fpath = os.path.join(_UNANALYZED_DIR, fname)
                count = 0
                try:
                    with open(fpath, "r", encoding="utf-8-sig") as f:
                        reader = _csv.reader(f)
                        next(reader, None)
                        count = sum(1 for _ in reader)
                except Exception:
                    pass
                csv_files.append({"name": fname, "path": fpath, "count": count})
        if not csv_files:
            feishu_client.send_bot_message(chat_id, "data/unanalyzed/ 目录下无 CSV 文件")
            _clear_bot_session(chat_id)
            return
        file_list = "\n".join(f"{i+1}. {f['name']} ({f['count']}条)" for i, f in enumerate(csv_files))
        _set_bot_session(chat_id, "wait_csv_execute", csv_files=csv_files, filters=filters, batch_meta=meta)
        feishu_client.send_bot_message(chat_id,
            f"过滤已设置：{filters.get('desc', '默认')}\n\n"
            f"可用CSV文件：\n{file_list}\n\n"
            f"请输入：文件序号,抽取数量,PC/线上\n示例: 1,50,PC")
        return

    # 6.1.2 CSV执行输入处理
    if session and session.get("state") == "wait_csv_execute":
        csv_files = session.get("csv_files", [])
        m = re.match(r'(\d+)\s*[,，]\s*(\d+)\s*[,，]\s*(pc|线上|online)', text, re.I)
        if not m:
            feishu_client.send_bot_message(chat_id, f"格式错误，请输入「序号,数量,PC/线上」\n示例: 1,50,PC")
            return
        idx = int(m.group(1)) - 1
        count = int(m.group(2))
        exec_mode = "online" if m.group(3).lower() in ("online", "线上") else "pc"
        if idx < 0 or idx >= len(csv_files):
            feishu_client.send_bot_message(chat_id, f"序号无效，请输入1-{len(csv_files)}")
            return
        if count <= 0:
            feishu_client.send_bot_message(chat_id, "抽取数量必须大于 0")
            return
        selected = csv_files[idx]
        filters = session.get("filters", {})
        meta = session.get("batch_meta", {})
        # 读取 CSV 中 Jira 号
        import csv as _csv
        try:
            bugids = []
            seen = set()
            with open(selected["path"], "r", encoding="utf-8-sig") as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    jira = (row.get("Jira号") or row.get("jira号") or row.get("JIRA号") or "").strip()
                    if jira and jira not in seen:
                        seen.add(jira)
                        bugids.append(jira)
        except Exception as e:
            feishu_client.send_bot_message(chat_id, f"读取 CSV 失败: {e}")
            return
        if not bugids:
            feishu_client.send_bot_message(chat_id, "CSV 文件中无 Jira 号")
            return
        _clear_bot_session(chat_id)
        mode_label = "线上" if exec_mode == "online" else "PC"
        feishu_client.send_bot_message(chat_id,
            f"已选择: {selected['name']} ({len(bugids)}条)\n"
            f"抽取 {count} 条，{mode_label}模式\n"
            f"过滤：{filters.get('desc', '默认')}\n发送「退出」可中断任务")
        _set_running_task(chat_id, f"CSV批量执行({selected['name']},{count}条,{mode_label})")
        threading.Thread(target=_bot_run_csv_batch_ai, args=(chat_id, bugids, selected["name"], exec_mode, filters, meta),
                         name=f"bot-csv-batch", daemon=True).start()
        return

    # 6.2 单个执行（输入Jira号+执行模式）
    if text == "6.2":
        _set_bot_session(chat_id, "wait_single_execute")
        feishu_client.send_bot_message(
            chat_id, "6.2 单个执行\n请输入：Jira号,PC/线上\n"
                     "多个Jira号用逗号分隔\n\n"
                     "示例: VCU-538942,PC 或 VCU-538942,VCU-200273,线上\n"
                     "发送「退出」可中断任务")
        return

    if session and session.get("state") == "wait_single_execute":
        parts = re.split(r'[,，]', text.strip())
        if len(parts) < 2:
            feishu_client.send_bot_message(chat_id, "格式错误，请输入「Jira号,PC/线上」\n示例: VCU-538942,PC")
            return
        # 最后一个部分是执行模式
        mode_str = parts[-1].strip().lower()
        if mode_str not in ("pc", "线上", "online"):
            feishu_client.send_bot_message(chat_id, "执行模式错误，请填写 PC 或 线上\n示例: VCU-538942,PC")
            return
        exec_mode = "online" if mode_str in ("线上", "online") else "pc"
        # 前面部分都是Jira号
        bugids = _parse_bugids(",".join(parts[:-1]))
        if not bugids:
            feishu_client.send_bot_message(chat_id, "未解析到 Jira 号，请重新输入")
            return
        _clear_bot_session(chat_id)
        mode_label = "线上" if exec_mode == "online" else "PC"
        feishu_client.send_bot_message(chat_id,
            f"已收到 {len(bugids)} 个 Jira 号：{','.join(bugids)}\n"
            f"{mode_label}模式执行，发送「退出」可中断任务")
        _set_running_task(chat_id, f"单个执行({len(bugids)}个,{mode_label})")
        threading.Thread(target=_bot_run_single_execute, args=(chat_id, bugids, exec_mode),
                         name=f"bot-single-{bugids[0]}", daemon=True).start()
        return

    # ==================== 功能9：Bug未分析提取 ====================
    if text == "9" or text == "9.1":
        jql_presets_unanalyzed = _get_unanalyzed_jql_presets()
        jql_desc = "\n".join(f"{k}({label}): {jql}" for k, (label, jql) in jql_presets_unanalyzed.items())
        _set_bot_session(chat_id, "wait_unanalyzed")
        feishu_client.send_bot_message(
            chat_id, f"9.1 Bug未分析提取\n请输入：JQL编号 或 自定义JQL\n{jql_desc}\n\n示例: JQL1")
        return

    if session and session.get("state") == "wait_unanalyzed":
        jql_key = text.strip().replace(" ", "").upper()
        jql_presets_unanalyzed = _get_unanalyzed_jql_presets()
        if jql_key in jql_presets_unanalyzed:
            jql = jql_presets_unanalyzed[jql_key][1]
        else:
            jql = text.strip()  # 用户输入自定义 JQL
        _clear_bot_session(chat_id)
        feishu_client.send_bot_message(chat_id, f"Bug未分析提取执行中\nJQL: {jql[:80]}...\n请稍候...")
        _set_running_task(chat_id, "Bug未分析提取")
        threading.Thread(target=_bot_unanalyzed_bugs, args=(chat_id, jql),
                         name="bot-unanalyzed", daemon=True).start()
        return

    # ==================== 功能10：线上AI日志分析批量执行 ====================
    if text == "10" or text == "10.1":
        _set_bot_session(chat_id, "wait_sub_menu", cmd="10.1")
        feishu_client.send_bot_message(chat_id,
            "10.1 线上批量执行\n请输入功能：\n1: 基础信息修改\n2: 通用链路")
        return

    # 10.1 线上过滤选项处理
    if session and session.get("state") == "wait_prod_filter_options":
        filters = _parse_filter_input(text, default_skip=True)
        meta = session.get("batch_meta", {})
        _set_bot_session(chat_id, "wait_prod_input", filters=filters, batch_meta=meta)
        feishu_client.send_bot_message(chat_id,
            f"过滤已设置：{filters.get('desc', '默认')}\n\n"
            f"请输入 Jira 号（多个用逗号/空格/换行分隔）\n示例：VCU-540049, VCU-540050")
        return

    # 10.1 线上Jira号输入处理
    if session and session.get("state") == "wait_prod_input":
        bugids = _parse_bugids(text)
        if not bugids:
            feishu_client.send_bot_message(chat_id, "未解析到 Jira 号，请重新输入")
            return
        filters = session.get("filters", {})
        meta = session.get("batch_meta", {})
        _set_bot_session(chat_id, "wait_prod_execute", bugids=bugids, filters=filters, batch_meta=meta)
        feishu_client.send_bot_message(chat_id,
            f"已收到 {len(bugids)} 个 Jira 号\n"
            f"过滤：{filters.get('desc', '默认')}\n\n"
            f"请输入：抽取数量,PC/线上\n示例: 50,PC")
        return

    # 10.1 线上执行输入处理
    if session and session.get("state") == "wait_prod_execute":
        m = re.match(r'(\d+)\s*[,，]\s*(pc|线上|online)', text, re.I)
        if not m:
            feishu_client.send_bot_message(chat_id, "格式错误，请输入「数量,PC/线上」\n示例: 50,PC")
            return
        count = int(m.group(1))
        exec_mode = "online" if m.group(2).lower() in ("online", "线上") else "pc"
        if count <= 0:
            feishu_client.send_bot_message(chat_id, "抽取数量必须大于 0")
            return
        bugids = session.get("bugids", [])
        filters = session.get("filters", {})
        meta = session.get("batch_meta", {})
        _clear_bot_session(chat_id)
        mode_label = "线上" if exec_mode == "online" else "PC"
        feishu_client.send_bot_message(chat_id,
            f"开始执行 {min(count, len(bugids))}/{len(bugids)} 条\n"
            f"{mode_label}模式，过滤：{filters.get('desc', '默认')}\n发送「退出」可中断任务")
        _set_running_task(chat_id, f"线上批量执行({min(count, len(bugids))}条)")
        threading.Thread(target=_bot_prod_batch_run, args=(chat_id, bugids, filters, meta, exec_mode, count),
                         name="bot-prod-batch", daemon=True).start()
        return

    # 未识别命令：返回功能菜单
    feishu_client.send_bot_message(chat_id,
        "可用子功能：\n"
        "4.1 置信度批量写入（发送 4.1）\n"
        "5.1 失败批量排查（发送 5.1）\n"
        "5.2 单个Jira诊断（发送 5.2）\n"
        "6.1.1 JQL批量执行（发送 6.1.1）\n"
        "6.1.2 CSV批量执行（发送 6.1.2）\n"
        "6.2 单个执行（发送 6.2）\n"
        "9.1 Bug未分析提取（发送 9.1）\n"
        "10.1 线上批量执行（发送 10.1）\n\n"
        "发送「菜单」查看完整功能列表")


def _parse_bugids(text: str) -> list:
    """解析 Jira 号字符串，返回去重后的列表"""
    bugids = []
    for b in re.split(r"[\s,，;；]+", text):
        b = b.strip().upper()
        if b and b not in bugids:
            bugids.append(b)
    return bugids


def _parse_filter_input(text: str, default_skip: bool = False) -> dict:
    """解析过滤选项输入（A0/A1/A2/A3），返回过滤配置字典

    A0: 过滤表中所有已存在记录
    A1: 过滤PC正确和通用失败的
    A2: 过滤线上正确和通用失败的
    A3: 过滤AI初步分析结果
    default_skip=True时默认使用A3（重复过滤），否则默认A0
    """
    stripped = text.strip().upper()
    if stripped in ("默认", "DEFAULT", "默认勾选"):
        if default_skip:
            return {"filter_ai_preliminary": True, "desc": "重复过滤(A3)"}
        return {"filter_all": True, "desc": "过滤所有已存在(A0)"}
    # 解析A0-A3选项
    options = set(re.findall(r'A[0-3]', stripped))
    if not options:
        if default_skip:
            return {"filter_ai_preliminary": True, "desc": "重复过滤(A3)"}
        return {"filter_all": True, "desc": "过滤所有已存在(A0)"}
    result = {}
    parts = []
    if "A0" in options:
        result["filter_all"] = True
        parts.append("A0:所有已存在")
    if "A1" in options:
        result["filter_pc_only"] = True
        parts.append("A1:PC正确+通用失败")
    if "A2" in options:
        result["filter_online_only"] = True
        parts.append("A2:线上正确+通用失败")
    if "A3" in options:
        result["filter_ai_preliminary"] = True
        parts.append("A3:AI初步分析")
    result["desc"] = "+".join(parts)
    return result


def _bot_apply_bitable_filter(candidates: list, filters: dict = None) -> list:
    """根据过滤配置对候选Jira号进行多维表格去重过滤"""
    if filters is None:
        filters = {"filter_all": True, "filter_ai_preliminary": True}
    filter_all = filters.get("filter_all", False)
    filter_pc_only = filters.get("filter_pc_only", False)
    filter_online_only = filters.get("filter_online_only", False)
    filter_ai_preliminary = filters.get("filter_ai_preliminary", False)
    # 无任何过滤标志时，默认使用智能过滤
    if not any([filter_all, filter_pc_only, filter_online_only, filter_ai_preliminary]):
        filter_ai_preliminary = True
    exclude_keys = set()
    try:
        cfg_b = load_config().get("feishu_bitable", {})
        if cfg_b.get("app_token") and cfg_b.get("table_id"):
            from src.clients import feishu_client
            records = feishu_client.list_bitable_records(cfg_b["app_token"], cfg_b["table_id"])
            bugid_field = cfg_b.get("bugid_field", "jira号")
            for rec in records:
                fields = rec.get("fields", {})
                fv = fields.get(bugid_field, "")
                if isinstance(fv, list):
                    fv = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in fv)
                elif isinstance(fv, dict):
                    fv = fv.get("text", str(fv))
                jira_key = str(fv).strip()
                if not jira_key:
                    continue
                # 来源过滤：PC/线上分别判断
                trigger_source = _bitable_text(fields.get("触发来源", ""))
                is_pc = trigger_source == "jira_analyze"
                if filter_pc_only and filter_online_only:
                    if not _is_bitable_excluded(fields, bugid_field):
                        continue
                elif filter_pc_only:
                    if not is_pc:
                        continue
                    if not _is_bitable_excluded(fields, bugid_field):
                        continue
                elif filter_online_only:
                    if is_pc:
                        continue
                    if not _is_bitable_excluded(fields, bugid_field):
                        continue
                # 排除逻辑
                use_smart = filter_ai_preliminary or (not filter_all)
                if use_smart:
                    if _is_bitable_excluded(fields, bugid_field):
                        exclude_keys.add(jira_key)
                else:
                    exclude_keys.add(jira_key)
            logger.info("机器人过滤(%s): 排除 %d 条", filters.get('desc', ''), len(exclude_keys))
    except Exception as e:
        logger.warning("机器人多维表格过滤失败（跳过过滤）: %s", e)
    return [k for k in candidates if k not in exclude_keys]


def _get_jql_presets() -> dict:
    """获取 JQL 预设（与测试页同步），返回 {编号: (标签, JQL)} 字典"""
    presets = {
        "JQL1": ("远控", 'issuetype = bug AND text ~ "远控" AND text ~ "VCU"'),
        "JQL2": ("coreservice", 'issuetype = bug AND text ~ "coreservice" AND text ~ "VCU"'),
        "JQL3": ("导航", 'issuetype = bug AND text ~ "SGM_Navigation750" AND text ~ "VCU"'),
        "JQL4": ("VCU近期未关闭", 'issuetype = bug AND text ~ "VCU" AND created >= "2026/08/15" AND created <= now() AND status != CLOSED'),
        "JQL5": ("8.25后已关闭导航", 'issuetype = bug AND text ~ "SGM_Navigation750" AND created >= "2026/08/25" AND status = closed'),
        "JQL6": ("8.25后远控", 'issuetype = bug AND text ~ "远控" AND created >= "2026/08/25" AND status = closed'),
        "JQL7": ("8.25后coreservice", 'issuetype = bug AND text ~ "coreservice" AND created >= "2026/08/25" AND status = closed'),
        "JQL8": ("8.25后RES1.0/1.1", 'issuetype = bug AND created >= "2026/08/25" AND status = closed AND (text ~ "RES1.1" OR text ~ "RES1.0")'),
        "JQL9": ("9.1新增非close", 'issuetype = bug AND status != closed AND created >= "2026/09/01"'),
    }
    cfg_jqls = load_config().get("feishu_bot", {}).get("jqls", {}) or {}
    for k, v in cfg_jqls.items():
        key = k.upper()
        if key not in presets:  # 不覆盖硬编码的标签
            presets[key] = (k, v)
    return presets


def _bot_diag_single(chat_id: str, bugids: list):
    """功能5.2后台执行：单个Jira诊断归类"""
    from src.clients import feishu_client
    from collections import Counter
    _reset_cancel_event(chat_id)  # 重置取消标记
    try:
        cfg = load_config().get("feishu_bitable", {})
        app_token = cfg.get("app_token", "")
        table_id = cfg.get("table_id", "")
        if not app_token or not table_id:
            feishu_client.send_bot_message(chat_id, "多维表格 app_token/table_id 未配置")
            return
        # 查询多维表格获取记录
        records = feishu_client.list_bitable_records(app_token, table_id)
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        bugid_field = cfg.get("bugid_field", "jira号")
        # 构建 Jira号 -> 记录 映射
        record_map = {}
        for rec in records:
            fields = rec.get("fields", {})
            fv = fields.get(bugid_field, "")
            if isinstance(fv, list):
                fv = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in fv)
            elif isinstance(fv, dict):
                fv = fv.get("text", str(fv))
            jira_no = str(fv).strip().upper()
            if jira_no and jira_no not in record_map:
                record_map[jira_no] = rec
        # 逐个诊断
        categories = Counter()
        results = []
        not_found = []
        for bugid in bugids:
            if _is_cancelled(chat_id):
                break
            if bugid not in record_map:
                not_found.append(bugid)
                continue
            rec = record_map[bugid]
            fields = rec.get("fields", {})
            try:
                result = troubleshoot_diagnose({
                    "bugid": bugid,
                    "err_msg": _diag_pick_error_info(fields),
                    "problem_time": _bitable_text(fields.get("分析问题时间", "")),
                    "done_time": _bitable_text(fields.get("分析完成时间", "")),
                })
                data = result.get("data", {})
                cat = data.get("category", "待人工排查")
                categories[cat] += 1
                results.append({"bugid": bugid, "category": cat, "reason": data.get("reason", "")})
            except Exception as e:
                logger.warning("诊断失败 %s: %s", bugid, e)
                categories["诊断异常"] += 1
        # 检查是否被取消
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, f"任务已被用户取消，已诊断 {len(results)} 条")
            return
        # 汇总回复
        lines = [f"单个Jira诊断归类完成：共 {len(bugids)} 个"]
        if not_found:
            lines.append(f"未找到记录: {', '.join(not_found)}")
        for cat, cnt in categories.most_common():
            lines.append(f"  {cat}: {cnt} 个")
        lines.append("")
        for r in results:
            lines.append(f"  {r['bugid']}: {r['category']}")
            if r.get("reason"):
                lines.append(f"    原因: {r['reason'][:80]}")
        for i in range(0, len(lines), 15):
            feishu_client.send_bot_message(chat_id, "\n".join(lines[i:i+15]))
    except Exception as e:
        logger.error("功能5.2执行失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"诊断归类失败: {e}")
    finally:
        _clear_running_task(chat_id)


def _bot_jql_search_only(chat_id: str, jql_key: str):
    """功能6.4后台执行：仅JQL搜索统计"""
    from src.clients import feishu_client
    from src.clients import jira_client as _jc
    _reset_cancel_event(chat_id)  # 重置取消标记
    try:
        presets = _get_jql_presets()
        preset = presets.get(jql_key)
        if not preset:
            feishu_client.send_bot_message(chat_id, f"未找到 JQL 编号 {jql_key}")
            return
        label, jql = preset
        issues = _jc.search_issues(jql, max_results=2000)
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        candidates = [(i.get("key") or "").strip() for i in issues if "VCU" in (i.get("key") or "").upper()]
        feishu_client.send_bot_message(chat_id,
            f"JQL搜索完成 [{jql_key}({label})]\n"
            f"搜索结果: {len(issues)} 条\n"
            f"VCU候选: {len(candidates)} 条\n\n"
            f"前20条: {', '.join(candidates[:20])}" + (f"... 等{len(candidates)}条" if len(candidates) > 20 else ""))
    except Exception as e:
        logger.error("功能6.4执行失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"JQL搜索失败: {e}")


def _bot_run_troubleshoot(chat_id: str, after_time: str):
    """功能5.1后台执行：查询失败记录 → 逐个诊断 → 缓存结果 → 汇总回复"""
    from src.clients import feishu_client
    from src.clients import jira_client as _jc
    from collections import Counter
    _reset_cancel_event(chat_id)  # 重置取消标记
    try:
        # 步骤1：查询多维表格失败记录（结果=失败，jira去重）
        cfg = load_config().get("feishu_bitable", {})
        app_token = cfg.get("app_token", "")
        table_id = cfg.get("table_id", "")
        if not app_token or not table_id:
            feishu_client.send_bot_message(chat_id, "多维表格 app_token/table_id 未配置")
            return
        cutoff = _ts_parse_datetime(after_time)
        if not cutoff:
            feishu_client.send_bot_message(chat_id, "时间解析失败")
            return
        records = feishu_client.list_bitable_records(app_token, table_id)
        # 筛选失败记录 + jira去重
        seen = set()
        failed_records = []
        for rec in records:
            fields = rec.get("fields", {})
            done_dt = _ts_parse_datetime(fields.get("分析完成时间", ""))
            if not done_dt or done_dt <= cutoff:
                continue
            if _bitable_text(fields.get("分析结果", "")) != "失败":
                continue
            jira_no = _bitable_text(fields.get(cfg.get("bugid_field", "jira号"), ""))
            if not jira_no or jira_no in seen:
                continue
            seen.add(jira_no)
            failed_records.append({
                "jira号": jira_no,
                "err_msg": _diag_pick_error_info(fields),
                "problem_time": _bitable_text(fields.get("分析问题时间", "")),
                "done_time": _bitable_text(fields.get("分析完成时间", "")),
            })
        if not failed_records:
            feishu_client.send_bot_message(chat_id, f"排查时间 {after_time} 之后无失败记录")
            return
        # 步骤2：逐个诊断（复用诊断接口，自动缓存结果）
        categories = Counter()
        cached_count = 0
        total = len(failed_records)
        cancelled = False
        for idx, rec in enumerate(failed_records):
            if _is_cancelled(chat_id):
                cancelled = True
                total = idx  # 更新为已处理数量
                break
            bugid = rec["jira号"]
            # 优先读缓存
            cached = _load_diagnose_cache(bugid)
            if cached:
                cat = cached.get("category", "待人工排查")
                categories[cat] += 1
                cached_count += 1
                continue
            # 调用诊断逻辑
            try:
                result = troubleshoot_diagnose({
                    "bugid": bugid,
                    "err_msg": rec["err_msg"],
                    "problem_time": rec["problem_time"],
                    "done_time": rec["done_time"],
                })
                data = result.get("data", {})
                cat = data.get("category", "待人工排查")
                categories[cat] += 1
            except Exception as e:
                logger.warning("机器人诊断失败 %s: %s", bugid, e)
                categories["诊断异常"] += 1
        # 检查是否被取消
        if cancelled:
            feishu_client.send_bot_message(chat_id, f"任务已被用户取消，已诊断 {total}/{len(failed_records)} 条")
            return
        # 步骤3：汇总回复
        lines = [f"AI日志分析失败批量排查完成",
                 f"排查时间: {after_time}",
                 f"失败记录: {total} 条（其中缓存命中: {cached_count} 条）",
                 ""]
        # 按用户要求的 4 类展示，其余合并到“其他”
        main_cats = ["触发时间问题", "无gmlogger文件", "正常处理机制无需分析", "无报错信息，跳过排查", "分析任务执行超时，跳过排查"]
        for cat in main_cats:
            if cat in categories:
                lines.append(f"{cat}: {categories[cat]}/{total}")
        other_total = sum(v for k, v in categories.items() if k not in main_cats)
        if other_total:
            other_names = [f"{k}({v})" for k, v in categories.items() if k not in main_cats]
            lines.append(f"其他: {other_total}/{total} [{', '.join(other_names)}]")
        feishu_client.send_bot_message(chat_id, "\n".join(lines))
    except Exception as e:
        logger.error("机器人功能5.1执行失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"执行失败: {str(e)[:200]}")
    finally:
        _clear_running_task(chat_id)


# 分析结果为成功或人工审核确认为无效/无需重试的 Jira 号集合
_EXCLUDE_REASONS = {"无gmlogger", "无gmlogger文件", "无gmlogger日志文件", "日志文件已损坏", "问题重复", "问题重复，无需排查", "问题未复现", "触发时间无日志", "无日志附件", "该jira无日志附件，属于正常处理机制", "该Jira无日志附件，属于正常处理机制", "该jira无日志附件", "该Jira无日志附件", "JIRA 分析任务执行超时", "JIRA分析任务执行超时", "疑似接口拥堵导致的手动中断", "日志里无对应触发时间相关文件，但是标题里明确说了触发时间", "解压问题，待排查", "解压问题"}


def _is_bitable_excluded(fields: dict, bugid_field: str = "jira号") -> bool:
    """多维表格记录是否应被去重排除

    排除条件：
    1. 触发来源=parseFullTicket 且 分析结果=成功 → 已正常处理的记录
    2. 分析结果=失败 且 人工审核结果为无效bug原因（无gmlogger/无日志附件/问题重复/信息不全等）
    """
    result_status = _bitable_text(fields.get("分析结果", ""))
    # 触发来源=parseFullTicket 且分析成功 → 排除
    trigger_source = _bitable_text(fields.get("触发来源", ""))
    if trigger_source == "parseFullTicket" and result_status == "成功":
        return True
    # 分析成功（不论触发来源）→ 排除
    if result_status == "成功":
        return True
    # 分析失败但人工审核确认为无效bug → 排除
    human_review = _bitable_text(fields.get("人工审核结果", ""))
    if human_review:
        # 精确匹配 + 忽略大小写匹配（兼容 Jira/jira 等大小写差异）
        if human_review in _EXCLUDE_REASONS:
            return True
        human_lower = human_review.lower()
        if any(human_lower == r.lower() for r in _EXCLUDE_REASONS):
            return True
    return False


def _bot_get_trigger_times(bugids: list) -> dict:
    """批量获取触发时间（优先云端缓存，已标记空跳过，新提取结果存入云端+本地）

    提取顺序：视频 OCR（最高优先级）→ 标题 → 评论 → 描述 → 自定义字段
    优先级：云端已有值（含用户手动修正）> 重新提取
    """
    from src.clients import jira_client as _jc
    cloud_times, cloud_keys = _load_cloud_trigger_cache()
    trigger_times = {}
    need_fetch = []
    for bugid in bugids:
        if bugid in cloud_times:
            # 云端已有触发时间，直接使用（包含用户手动修正的值）
            trigger_times[bugid] = cloud_times[bugid]
            continue
        if bugid in cloud_keys:
            # 云端已标记无触发时间（空值），跳过
            continue
        need_fetch.append(bugid)
    if need_fetch:
        logger.info("触发时间: %d 个云端已有, %d 个需新提取", len(bugids) - len(need_fetch), len(need_fetch))
    for bugid in need_fetch:
        try:
            issue = _jc.fetch_issue(bugid)
            # 视频 OCR 优先级最高
            tt = _diag_extract_time_from_video_simple(issue)
            if not tt:
                tt = _jc.extract_trigger_time_from_issue(issue)
            if tt:
                trigger_times[bugid] = str(tt)
            try:
                _save_trigger_time_to_cloud(bugid, str(tt) if tt else "")
            except Exception as save_e:
                logger.warning("云端保存触发时间失败 %s（不影响流程）: %s", bugid, save_e)
        except Exception as e:
            logger.warning("机器人提取触发时间失败 %s: %s", bugid, e)
    return trigger_times


def _bot_extract_trigger_times(chat_id: str, bugids: list):
    """功能6.2后台执行：提取触发时间并汇报结果"""
    from src.clients import feishu_client
    _reset_cancel_event(chat_id)  # 重置取消标记
    try:
        trigger_times = _bot_get_trigger_times(bugids)
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        has_time = sum(1 for b in bugids if b in trigger_times)
        no_time = len(bugids) - has_time
        lines = [f"触发时间提取完成：共 {len(bugids)} 个",
                 f"✅ 有触发时间: {has_time} 个",
                 f"❌ 无触发时间: {no_time} 个", ""]
        for bugid in bugids:
            tt = trigger_times.get(bugid)
            if tt:
                lines.append(f"  {bugid}: {tt}")
            else:
                lines.append(f"  {bugid}: 未提取到")
        # 分批发送（防止消息过长）
        for i in range(0, len(lines), 15):
            feishu_client.send_bot_message(chat_id, "\n".join(lines[i:i+15]))
    except Exception as e:
        logger.error("功能6.2执行失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"触发时间提取失败: {e}")


def _bot_trigger_and_reply(chat_id: str, bugids: list, trigger_times: dict, realtime: bool = True,
                          exec_mode: str = "pc") -> tuple:
    """逐个触发 AI 日志分析，支持PC/线上模式切换"""
    from src.clients import feishu_client
    from src.clients.base import http_post
    cfg = load_config()["ai_log_api"]
    success = 0
    lines = []
    results = []
    batch_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for bugid in bugids:
        # 检查是否被用户取消
        if _is_cancelled(chat_id):
            lines.append(f"⊘ 任务已被用户取消，剩余 {len(bugids) - bugids.index(bugid)} 条未执行")
            break
        exec_time = trigger_times.get(bugid)
        if not exec_time:
            line = f"✗ Jira号 {bugid} 跳过（无触发时间）"
            results.append({"jira号": bugid, "执行结果": "失败", "报告长度": 0, "备注": "无触发时间", "触发时间": "", "执行时间": batch_start_time, "分析执行时间": batch_start_time})
            if realtime:
                feishu_client.send_bot_message(chat_id, line)
            else:
                lines.append(line)
            continue
        try:
            if exec_mode == "online":
                payload = {"jiraNumber": bugid, "questionTimes": [exec_time]}
                resp = http_post(_PROD_AI_URL, payload, timeout=30)
            else:
                payload = {cfg["bugid_field"]: bugid}
                if cfg.get("trigger_time_field"):
                    payload[cfg["trigger_time_field"]] = exec_time
                resp = http_post(cfg["url"], payload, timeout=int(cfg.get("timeout", 60)))
            resp_code = resp.get("code") if isinstance(resp, dict) else None
            resp_msg = str(resp.get("msg", "")) if isinstance(resp, dict) else ""
            ok = (resp_code == 200 or resp_code == 0 or resp_code == "200")
            if ok and exec_mode == "pc":
                ok = any(kw in resp_msg for kw in ["分析任务已启动", "后台处理", "正在分析"])
            if ok:
                success += 1
                line = f"✓ Jira号 {bugid} 执行成功（触发时间：{exec_time}）"
                results.append({"jira号": bugid, "执行结果": "成功", "报告长度": 0, "备注": resp_msg[:200], "触发时间": exec_time, "执行时间": batch_start_time, "分析执行时间": batch_start_time})
            else:
                line = f"✗ Jira号 {bugid} 执行失败（接口返回：{resp_msg[:100]}）"
                results.append({"jira号": bugid, "执行结果": "失败", "报告长度": 0, "备注": resp_msg[:150], "触发时间": exec_time, "执行时间": batch_start_time, "分析执行时间": batch_start_time})
        except Exception as e:
            logger.warning("机器人触发 AI 分析失败 %s: %s", bugid, e)
            line = f"✗ Jira号 {bugid} 执行失败（异常：{str(e)[:100]}）"
            results.append({"jira号": bugid, "执行结果": "失败", "报告长度": 0, "备注": str(e)[:200], "触发时间": exec_time, "执行时间": batch_start_time, "分析执行时间": batch_start_time})
        if realtime:
            feishu_client.send_bot_message(chat_id, line)
        else:
            lines.append(line)
    return success, lines, results


def _batch_csv_to_markdown(csv_path: str) -> str:
    """将批量执行 CSV 转为 Markdown 格式文档，含统计摘要和完整表格"""
    rows = _read_csv_rows(csv_path)
    if not rows:
        return "# 批量执行记录\n\n无执行记录"
    success = sum(1 for r in rows if r.get("执行结果", "").strip() == "成功")
    fail = len(rows) - success
    times = [r.get("执行时间", "").strip() for r in rows if r.get("执行时间", "").strip()]
    time_range = f"{min(times)} ~ {max(times)}" if len(times) >= 2 else (times[0] if times else "未知")
    # 构建 Markdown
    lines = [
        f"# 批量执行记录",
        f"",
        f"- 总条数：{len(rows)}",
        f"- 成功：{success}",
        f"- 失败：{fail}",
        f"- 触发时间：{time_range}",
        f"",
        f"## 执行明细",
        f"",
        "| Jira号 | 执行结果 | 触发时间 | 执行时间 | 备注 |",
        "|--------|----------|----------|----------|------|",
    ]
    for r in rows:
        jira = r.get("Jira号", "").strip() or r.get("jira号", "").strip()
        result = r.get("执行结果", "").strip()
        trigger_time = r.get("触发时间", "").strip()
        analysis_time = r.get("执行时间", "").strip() or r.get("分析执行时间", "").strip()
        note = r.get("备注", "").strip().replace("|", "\\|")[:100]
        lines.append(f"| {jira} | {result} | {trigger_time} | {analysis_time} | {note} |")
    return "\n".join(lines)


def _upload_batch_to_cloud(csv_path: str, doc_title: str) -> str:
    """将批量执行 CSV 转为飞书在线文档并上传到云端日期子文件夹，返回文档 URL"""
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    root_folder = cfg.get("batch_folder_token", "")
    if not root_folder:
        logger.warning("未配置 batch_folder_token，跳过云端上传")
        return ""
    # 按日期创建子文件夹
    date_str = datetime.now().strftime("%Y-%m-%d")
    target_folder = _get_or_create_date_folder(root_folder, date_str)
    is_subfolder = target_folder != root_folder
    logger.info("上传目标: 日期=%s, 文件夹=%s (%s)", date_str, target_folder[:12], "子文件夹" if is_subfolder else "根文件夹")
    md_content = _batch_csv_to_markdown(csv_path)
    doc_result = feishu_client.create_docx_document(doc_title, md_content, folder_token=target_folder)
    cloud_url = doc_result.get("url", "")
    if cloud_url:
        logger.info("批量执行记录已上传云端: %s", cloud_url)
    return cloud_url


def _get_or_create_date_folder(root_folder: str, date_str: str) -> str:
    """在根文件夹下获取或创建日期子文件夹，返回子文件夹 token"""
    from src.clients import feishu_client
    try:
        existing = feishu_client.list_folder_files(root_folder)
        for f in existing:
            if f.get("name") == date_str and f.get("type") == "folder":
                logger.info("日期文件夹已存在: %s (token=%s)", date_str, f["token"])
                return f["token"]
        result = feishu_client.create_folder(date_str, root_folder)
        token = result.get("token", "")
        if token:
            logger.info("日期文件夹已创建: %s (token=%s)", date_str, token)
            return token
    except Exception as e:
        logger.warning("获取/创建日期子文件夹失败: %s，将使用根文件夹", e)
    return root_folder


def _save_bot_execution_results(results: list, batch_name: str = None, batch_meta: dict = None):
    """将机器人执行结果保存到本地 CSV（batch + daily）并上传云端"""
    import csv as _csv
    from src.core import report as report_module

    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M%S")
    # 批量执行元数据默认值（机器人触发默认 PC）
    _meta = batch_meta or {
        "分析并发数": "10", "下载并发数": "4", "模型": "deepseek-v-pro", "触发来源": "PC",
    }
    # 保存 batch CSV: docs/日期/batch_*.csv
    batch_csv = os.path.join(get_path("doc_dir"), date_str, f"batch_{batch_name or time_str}.csv")
    os.makedirs(os.path.dirname(batch_csv), exist_ok=True)
    fieldnames = ["jira号", "执行结果", "报告长度", "备注", "触发时间", "执行时间",
                  "分析并发数", "下载并发数", "模型", "触发来源"]
    with open(batch_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = _csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "jira号": r["jira号"],
                "执行结果": r["执行结果"],
                "报告长度": r["报告长度"],
                "备注": r["备注"],
                "触发时间": r.get("触发时间", ""),
                "执行时间": r.get("执行时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                **_meta,
            })
    # 写入每日结论报表
    try:
        daily_rows = [
            {"jira号": r["jira号"],
             "分析问题时间": r.get("触发时间", ""),
             "AI分析结果(飞书链接)": "", "AI评论总结": "",
             "rootcause": "", "结果置信度": ""} for r in results]
        report_module.generate_daily_csv(daily_rows, date_str=date_str)
    except Exception as e:
        logger.warning("机器人执行结果写入每日报表失败: %s", e)
    # 上传到飞书云端文件夹
    try:
        _sc = sum(1 for r in results if (r.get("执行结果") or "") == "成功")
        doc_title = f"批量执行 {date_str}_{batch_name or time_str} ({_sc}/{len(results)})"
        cloud_url = _upload_batch_to_cloud(batch_csv, doc_title)
        if cloud_url:
            logger.info("机器人批量执行已上传云端: %s", cloud_url)
    except Exception as e:
        logger.warning("机器人批量执行上传云端失败（不影响主流程）: %s", e)
    return batch_csv


def _bot_send_batch_results(chat_id: str, success: int, total: int, lines: list):
    """批量执行完成后统一发送结果（汇总头 + 每条10条分条，避免单条消息超长）"""
    from src.clients import feishu_client
    feishu_client.send_bot_message(chat_id, f"批量执行完成：成功 {success}/{total}")
    for i in range(0, len(lines), 10):
        feishu_client.send_bot_message(chat_id, "\n".join(lines[i:i + 10]))


# ==================== 功能0：每日结论播报 辅助函数 ====================
_DAILY_BROADCAST_CONFIG_PATH = os.path.join(PROJECT_ROOT, "data", "daily_broadcast_config.json")
_DAILY_BROADCAST_FOLDER = "I8Bwf17aAl9LR1dazOic7Q70nic"  # 云端每日结论文件夹
_daily_scheduler_thread = None
_daily_scheduler_stop = None


def _load_daily_broadcast_config() -> dict:
    """加载每日播报配置：{chat_id: {enabled, report_time}}"""
    if os.path.exists(_DAILY_BROADCAST_CONFIG_PATH):
        try:
            with open(_DAILY_BROADCAST_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_daily_broadcast_config(cfg: dict):
    """保存每日播报配置"""
    os.makedirs(os.path.dirname(_DAILY_BROADCAST_CONFIG_PATH), exist_ok=True)
    with open(_DAILY_BROADCAST_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _auto_disable_daily_broadcast(chat_id: str):
    """群解散或发送失败时自动关闭该群的每日播报"""
    cfg = _load_daily_broadcast_config()
    if chat_id in cfg and cfg[chat_id].get("enabled"):
        cfg[chat_id]["enabled"] = False
        _save_daily_broadcast_config(cfg)
        logger.warning("群 %s 发送失败，已自动关闭每日播报", chat_id[:12])


def get_daily_report_url() -> str:
    """获取结论报表云端文件夹 URL"""
    return f"https://my.feishu.cn/drive/folder/{_DAILY_BROADCAST_FOLDER}"


def _parse_dur_sec(raw) -> float:
    """解析耗时字段值为秒数，支持 '3分20秒' / '123.45s' / '123秒' / 纯数字等格式"""
    if not raw:
        return 0.0
    import re
    s = str(raw).strip()
    # 匹配 "X分Y秒" 格式
    m = re.match(r'(\d+)\s*分\s*(\d+)\s*秒?', s)
    if m:
        return float(m.group(1)) * 60 + float(m.group(2))
    # 匹配纯分: "3分"
    m = re.match(r'(\d+)\s*分$', s)
    if m:
        return float(m.group(1)) * 60
    try:
        return float(s.replace("s", "").replace("秒", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _format_dur(sec: float) -> str:
    """将秒数格式化为可读时间字符串"""
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m}分{s}秒" if m else f"{s}秒"


def _generate_daily_report(date_str: str, bt_map: dict = None, preloaded_batch: tuple = None) -> dict:
    """生成指定工作日的结论汇总，自动扩展到后续非工作日（含周末/法定假日）

    :param date_str: 日期字符串
    :param bt_map: 可选，预查询的多维表格数据 {jira_no: [records]}，避免重复查询
    :param preloaded_batch: 可选，预读取的批次记录 (jira_exec, dedup_count)，避免重复读取
    """
    # 计算播报覆盖的日期范围（工作日 + 后续非工作日）
    report_dates = _get_report_date_range(date_str)
    # 读取批次记录（支持外部传入，避免重复读取云端文档）
    if preloaded_batch is not None:
        jira_exec, dedup_count = preloaded_batch
    else:
        jira_exec, dedup_count = _read_multi_day_batch_records(report_dates)
    if not jira_exec:
        return {"total": 0, "regression": 0, "success": 0, "fail": 0,
                "pending": 0, "failures": {}, "todo_items": [],
                "too_long": 0, "avg_total_duration": "-", "avg_analysis_duration": "-",
                "report_dates": report_dates, "rows": [], "dedup": 0}
    # 查多维表格（支持外部传入预查询数据，避免重复查询）
    from src.clients import feishu_client
    if bt_map is None:
        cfg = load_config().get("feishu_bitable", {})
        app_token, table_id = cfg.get("app_token", ""), cfg.get("table_id", "")
        bugid_field = cfg.get("bugid_field", "jira号")
        report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
        bt_map = {}
        if app_token and table_id:
            try:
                records = feishu_client.list_bitable_records(app_token, table_id)
                for rec in records:
                    fields = rec.get("fields", {})
                    jira_key = _bitable_text(fields.get(bugid_field, ""))
                    if jira_key and jira_key in jira_exec:
                        bt_map.setdefault(jira_key, []).append(
                            _flatten_bitable_record_all(fields, report_field))
            except Exception as e:
                logger.warning("每日播报：多维表格查询失败: %s", e)
    # 匹配并统计
    success_count = 0
    fail_count = 0
    fail_cats = {}  # {分类: 数量}
    fail_jiras = {}  # {分类: [{jira号, 错误信息}]}
    todo_items = []  # 待办跟进列表
    durations = []
    analysis_durations = []
    too_long_count = 0
    too_long_threshold = 900  # 15分钟
    rows = []
    for jira_no, exec_info in jira_exec.items():
        bt_records = bt_map.get(jira_no, [])
        row = {"jira号": jira_no}
        row.update(exec_info)
        if bt_records:
            exec_time = exec_info.get("执行时间", "")
            candidates = [r for r in bt_records
                         if r.get("分析完成时间", "") and r["分析完成时间"] >= exec_time]
            if not candidates:
                candidates = bt_records
            candidates.sort(key=lambda x: x.get("分析完成时间", ""))
            # 智能去重：有成功则取成功，否则取最后一次失败
            success_records = [r for r in candidates if r.get("分析结果", "") == "成功"]
            if success_records:
                bf = success_records[0]  # 有成功优先取成功
            else:
                bf = candidates[-1]  # 全失败取最后一次
            row.update(bf)
            # 保留批次记录中的原始触发来源，不被多维表格字段覆盖
            original_source = exec_info.get("触发来源", "")
            if original_source:
                row["触发来源"] = original_source
            result = bf.get("分析结果", "")
            # 解析耗时
            raw_dur = bf.get("总耗时", "")
            dur_sec = _parse_dur_sec(raw_dur)
            if dur_sec > 0:
                durations.append(dur_sec)
            # 解析分析耗时
            raw_analysis = bf.get("分析耗时", "")
            analysis_sec = _parse_dur_sec(raw_analysis)
            if analysis_sec > 0:
                analysis_durations.append(analysis_sec)
                if analysis_sec > too_long_threshold:
                    too_long_count += 1
            if result == "成功":
                success_count += 1
            else:
                fail_count += 1
                # 失败分类
                cat = _classify_failure(jira_no, bf)
                fail_cats[cat] = fail_cats.get(cat, 0) + 1
                row["失败分类"] = cat
                if cat not in fail_jiras:
                    fail_jiras[cat] = []
                err_short = (_bitable_text(bf.get("错误信息", "")) or "")[:80]
                fail_jiras[cat].append({"jira号": jira_no, "错误信息": err_short})
                # 失败未重新成功 = 待办（通用原因不计入待办）
                human_review = _bitable_text(bf.get("人工审核结果", ""))
                is_common_reason = human_review and (
                    human_review in _EXCLUDE_REASONS or
                    any(human_review.lower() == r.lower() for r in _EXCLUDE_REASONS))
                # 上游jira问题也不计入待办
                if not is_common_reason and cat != "上游jira卡住问题":
                    todo_items.append({"jira号": jira_no, "reason": f"分析失败: {cat}",
                                       "触发时间": exec_info.get("触发时间", "")})
        else:
            # 执行成功但多维表格无记录 → 计入统计，标记为"分析中"
            row["分析结果"] = "分析中"
        rows.append(row)
    rows.sort(key=lambda x: x["jira号"])
    regression_count = success_count + fail_count
    pending_count = sum(1 for r in rows if r.get("分析结果", "") == "分析中")
    regression_count += pending_count
    # 平均总耗时（按实际计入统计的记录数计算）
    counted = len(rows) or 1
    if durations:
        avg_total_sec = sum(durations) / counted
        avg_total_duration = _format_dur(avg_total_sec)
    else:
        avg_total_duration = "-"
    # 平均分析耗时
    if analysis_durations:
        avg_analysis_sec = sum(analysis_durations) / counted
        avg_analysis_duration = _format_dur(avg_analysis_sec)
    else:
        avg_analysis_duration = "-"
    # 统计 PC/线上数量（非线上的统一归为PC，确保 PC + 线上 = 总数）
    online_rows = [r for r in rows if r.get("触发来源", "") == "parseFullTicket"]
    pc_rows = [r for r in rows if r not in online_rows]
    pc_count = len(pc_rows)
    online_count = len(online_rows)
    # 分别统计 PC/线上的重复过滤数（非线上统一归为PC）
    online_dup = sum(1 for jno, info in jira_exec.items()
                     if info.get("触发来源", "") == "parseFullTicket" and jno not in bt_map)
    pc_dup = sum(1 for jno, info in jira_exec.items()
                   if info.get("触发来源", "") != "parseFullTicket" and jno not in bt_map)
    # 收集基础信息（取 PC/线上各自最常见的配置）
    def _collect_meta(group_rows: list) -> dict:
        if not group_rows:
            return {}
        # 取第一条的基础信息作为代表
        r = group_rows[0]
        return {
            "分析并发数": r.get("分析并发数", "") or "-",
            "下载并发数": r.get("下载并发数", "") or "-",
            "模型": r.get("模型", "") or "-",
            "版本": r.get("版本号", "") or "-",
        }
    pc_meta = _collect_meta(pc_rows)
    online_meta = _collect_meta(online_rows)
    return {"total": len(rows), "regression": regression_count,
            "success": success_count, "fail": fail_count,
            "pending": pending_count, "failures": fail_cats, "failure_jiras": fail_jiras,
            "todo_items": todo_items, "too_long": too_long_count,
            "avg_total_duration": avg_total_duration,
            "avg_analysis_duration": avg_analysis_duration,
            "pc_count": pc_count, "online_count": online_count,
            "pc_dup": pc_dup, "online_dup": online_dup,
            "pc_meta": pc_meta, "online_meta": online_meta,
            "report_dates": report_dates,
            "rows": rows,
            "dedup": dedup_count}


def _classify_failure(jira_no: str, bf: dict) -> str:
    """失败分类：优先诊断缓存，其次错误信息，最后人工审核结果倒推"""
    cached = _load_diagnose_cache(jira_no)
    if cached and cached.get("category"):
        return cached["category"]
    # 优先检查错误信息中的上游系统错误（504/500/502/503等）
    import re
    err_info = (bf.get("错误信息", "") or "").strip()
    if any(code in err_info for code in ("504 Gateway Timeout", "502 Bad Gateway",
                                         "503 Service Unavailable", "500 Internal Server Error",
                                         "Gateway Timeout", "Service Unavailable")):
        return "上游jira卡住问题"
    # 模型调用失败：第x轮LLM调用失败 / 第x轮调用失败
    if re.search(r"第\d+轮.*调用失败", err_info):
        return "模型调用失败"
    review = (bf.get("人工审核结果", "") or "").strip()
    if not review or review in ("-", "None"):
        return "待开发排查"
    if "模型调用失败" in review:
        return "模型调用失败"
    if "时间添加" in review or "时间异常" in review:
        return "触发时间问题"
    if "无gmlogger" in review or "无日志附件" in review or "损坏" in review:
        return "日志过滤逻辑"
    if "日志里无对应" in review or "信息不全" in review:
        return "日志过滤逻辑"
    if "解压问题" in review or "解压" in review:
        return "解压问题"
    if "接口无响应" in review:
        return "接口响应问题"
    if "接口拥堵" in review or "手动中断" in review:
        return "接口并发响应问题"
    if "服务有报错" in review:
        return "服务运行问题"
    if "正常处理机制" in review:
        return "正常处理机制"
    if "执行超时" in review:
        return "执行超时"
    if "问题重复" in review:
        return "问题重复"
    if "待人工排查" in review:
        return "待人工排查"
    if "分析can信号导致超时" in review:
        return "分析can信号导致超时"
    return review[:20]


def _format_daily_report_msg(report: dict, date_str: str, cloud_url: str = "") -> str:
    """将日报结果格式化为飞书消息"""
    total = report["total"]
    success = report["success"]
    fail = report["fail"]
    pending = report.get("pending", 0)
    if total == 0:
        return f"📊 {date_str} 每日结论\n\n当日无批量执行记录"
    rate = f"{success / total * 100:.0f}%" if total > 0 else "0%"
    # 日期标签：多天时显示范围
    report_dates = report.get("report_dates", [date_str])
    if len(report_dates) > 1:
        date_label = f"{report_dates[0]} ~ {report_dates[-1]}"
    else:
        date_label = date_str
    msg = f"📊 {date_label} 每日结论\n\n"
    msg += f"执行总数：{total}\n"
    pc_count = report.get("pc_count", 0)
    online_count = report.get("online_count", 0)
    # 基础信息格式化函数
    def _meta_str(meta: dict, dup: int) -> str:
        if not meta:
            return ""
        parts = []
        ac = meta.get("分析并发数", "-")
        dc = meta.get("下载并发数", "-")
        model = meta.get("模型", "-")
        ver = meta.get("版本", "-")
        if ac != "-" or dc != "-" or model != "-":
            parts.append(f"并发{ac}/{dc}")
        if model != "-":
            parts.append(model)
        if ver != "-":
            parts.append(f"版本{ver}")
        if dup:
            parts.append(f"重复{dup}")
        return f"（{', '.join(parts)}）" if parts else ""
    if pc_count or online_count:
        pc_info = _meta_str(report.get("pc_meta", {}), report.get("pc_dup", 0))
        online_info = _meta_str(report.get("online_meta", {}), report.get("online_dup", 0))
        if pc_count:
            msg += f"💻 PC：{pc_count} {pc_info}\n"
        if online_count:
            msg += f"🌐 线上：{online_count} {online_info}\n"
    msg += f"🔁 回归：{report.get('regression', 0)}\n"
    msg += f"✅ 成功：{success}\n"
    msg += f"❌ 失败：{fail}\n"
    if pending:
        msg += f"⏳ 待分析：{pending}\n"
    dedup = report.get("dedup", 0)
    if dedup:
        msg += f"🔀 去重：{dedup}\n"
    msg += f"成功率：{rate}\n"
    if report.get("avg_total_duration", "-") != "-":
        msg += f"平均总耗时：{report['avg_total_duration']}\n"
    if report.get("avg_analysis_duration", "-") != "-":
        too_long = report.get("too_long", 0)
        too_long_str = f"，耗时过长 {too_long} 条" if too_long else ""
        msg += f"平均分析耗时：{report['avg_analysis_duration']}{too_long_str}\n"
    else:
        too_long = report.get("too_long", 0)
        if too_long:
            msg += f"⚠️ 耗时过长：{too_long} 条\n"
    # 失败分类
    failures = report.get("failures", {})
    if failures:
        msg += "\n失败分析：\n"
        for cat, cnt in failures.items():
            msg += f"  · {cat}：{cnt}\n"
    # 待办跟进数量提示
    todo_items = report.get("todo_items", [])
    if todo_items:
        msg += f"\n📝 待办跟进：{len(todo_items)} 项（详见文档）\n"
    msg += "\n"
    detail_url = cloud_url or get_daily_report_url()
    msg += detail_url
    return msg


def _upload_daily_report_to_cloud(report: dict, date_str: str) -> str:
    """将每日结论上传到云端指定文件夹（先删后建，确保不产生重复文档）"""
    from src.clients import feishu_client
    report_dates = report.get("report_dates", [date_str])
    if len(report_dates) > 1:
        doc_title = f"每日结论_{report_dates[0]}~{report_dates[-1]}"
    else:
        doc_title = f"每日结论_{date_str}"
    # 查找所有同名文档（可能有历史重复）
    existing_docs = []  # [(token, url)]
    try:
        existing = feishu_client.list_folder_files(_DAILY_BROADCAST_FOLDER)
        for f in existing:
            if f.get("name") == doc_title and f.get("type") == "docx":
                existing_docs.append((f["token"], f.get("url", "")))
        logger.info("查找每日结论文档: 标题='%s', 文件夹共 %d 个文件, 匹配 %d 个同名文档",
                    doc_title, len(existing), len(existing_docs))
    except Exception as e:
        logger.warning("查找旧每日结论文档失败: %s", e)
    # 生成 Markdown 内容：结论→待办→详情
    total = report['total']
    success = report['success']
    fail = report['fail']
    rate = f"{success / total * 100:.1f}%" if total > 0 else "0%"
    # 基础信息格式化
    def _md_meta_str(meta: dict, dup: int) -> str:
        if not meta:
            return ""
        parts = []
        ac = meta.get("分析并发数", "-")
        dc = meta.get("下载并发数", "-")
        model = meta.get("模型", "-")
        ver = meta.get("版本", "-")
        if ac != "-" or dc != "-":
            parts.append(f"并发{ac}/{dc}")
        if model != "-":
            parts.append(model)
        if ver != "-":
            parts.append(f"版本{ver}")
        if dup:
            parts.append(f"重复{dup}")
        return f"（{', '.join(parts)}）" if parts else ""
    pc_info = _md_meta_str(report.get("pc_meta", {}), report.get("pc_dup", 0))
    online_info = _md_meta_str(report.get("online_meta", {}), report.get("online_dup", 0))
    lines = [f"# {doc_title}", "",
             "## 结论", "",
             f"- 执行总数：{total}",
             f"- 💻 PC：{report.get('pc_count', 0)} {pc_info}",
             f"- 🌐 线上：{report.get('online_count', 0)} {online_info}",
             f"- 回归：{report.get('regression', 0)}",
             f"- 成功：{success}",
             f"- 失败：{fail}",
             f"- 待分析：{report.get('pending', 0)}",
             f"- 去重：{report.get('dedup', 0)}",
             f"- 成功率：{rate}",
             f"- 平均总耗时：{report.get('avg_total_duration', '-')}",
             f"- 平均分析耗时：{report.get('avg_analysis_duration', '-')}{('，耗时过高 ' + str(report['too_long']) + ' 条') if report.get('too_long') else ''}", ""]
    # 失败分类
    failures = report.get("failures", {})
    if failures:
        lines.append("### 失败分析")
        lines.append("")
        for cat, cnt in failures.items():
            lines.append(f"- {cat}：{cnt} 条")
        lines.append("")
    # 待办跟进
    todo_items = report.get("todo_items", [])
    if todo_items:
        lines.append("## 待办跟进")
        lines.append("")
        lines.append(f"共 {len(todo_items)} 项待处理：")
        lines.append("")
        lines.append("| Jira号 | 原因 | 触发时间 |")
        lines.append("|--------|------|----------|")
        for item in todo_items:
            lines.append(f"| {item['jira号']} | {item['reason']} | {item['触发时间']} |")
        lines.append("")
    # 执行详情（分四个模块：分析失败、待开发排查、耗时过长、分析成功）
    lines.append("## 执行详情")
    lines.append("")
    rows = report.get("rows", [])
    too_long_threshold = 900
    # 分组（用分析结果而非执行结果，因为执行结果=成功仅代表接口正常返回）
    failed_rows, pending_rows, too_long_success_rows, normal_success_rows = [], [], [], []
    for r in rows:
        analysis_result = r.get("分析结果", "") or ""
        analysis_sec = _parse_dur_sec(r.get("分析耗时", ""))
        is_too_long = analysis_sec > too_long_threshold if analysis_sec > 0 else False
        if analysis_result == "失败":
            failed_rows.append(r)
        elif not analysis_result or analysis_result == "分析中":
            pending_rows.append(r)
        elif is_too_long:
            too_long_success_rows.append(r)
        else:
            normal_success_rows.append(r)
    # 失败排序：具体原因在前，待审核在后
    def _fail_sort_key(r):
        reason = r.get("人工审核结果", "") or ""
        is_pending = not reason or reason in ("-", "None")
        return (1 if is_pending else 0, reason)
    failed_rows.sort(key=_fail_sort_key)
    pending_rows.sort(key=lambda r: r.get("jira号", ""))
    too_long_success_rows.sort(key=lambda r: -_parse_dur_sec(r.get("分析耗时", "")))
    # 各模块表格表头
    detail_header = ["| Jira号 | 触发时间 | 执行时间 | 分析耗时 | 分析结果 |",
                     "|--------|----------|----------|----------|----------|"]
    def _detail_row(r):
        return (f"| {r.get('jira号', '')} | {r.get('触发时间', '')} | "
                f"{r.get('执行时间', '')} | {r.get('分析耗时', '')} | "
                f"{r.get('分析结果', '') or r.get('备注', '')[:50]} |")
    # 模块 1：分析失败（按失败分类归类）
    lines.append(f"### 分析失败（{len(failed_rows)}条）")
    lines.append("")
    if failed_rows:
        # 按失败分类归类
        fail_groups = {}  # {分类: [rows]}
        for r in failed_rows:
            cat = _classify_failure(r.get("jira号", ""), r)
            fail_groups.setdefault(cat, []).append(r)
        # 按分组数量降序排列
        for cat, group_rows in sorted(fail_groups.items(), key=lambda x: -len(x[1])):
            lines.append(f"#### {cat}（{len(group_rows)}条）")
            lines.append("")
            lines.extend(detail_header)
            for r in group_rows:
                lines.append(_detail_row(r))
            lines.append("")
    else:
        lines.append("无")
    lines.append("")
    # 模块 2：待开发排查
    lines.append(f"### 待开发排查（{len(pending_rows)}条）")
    lines.append("")
    if pending_rows:
        lines.extend(detail_header)
        for r in pending_rows:
            lines.append(_detail_row(r))
    else:
        lines.append("无")
    lines.append("")
    # 模块 3：耗时过长（成功但分析耗时>{threshold}s）
    lines.append(f"### 耗时过长（{len(too_long_success_rows)}条）")
    lines.append("")
    if too_long_success_rows:
        lines.extend(detail_header)
        for r in too_long_success_rows:
            lines.append(_detail_row(r))
    else:
        lines.append("无")
    lines.append("")
    # 模块 4：分析成功
    lines.append(f"### 分析成功（{len(normal_success_rows)}条）")
    lines.append("")
    if normal_success_rows:
        lines.extend(detail_header)
        for r in normal_success_rows:
            lines.append(_detail_row(r))
    else:
        lines.append("无")
    lines.append("")
    md_content = "\n".join(lines)
    # 上传：原地覆盖内容，保持链接不变，清理历史重复文档
    try:
        if existing_docs:
            # 用第一个文档原地覆盖内容
            main_token, main_url = existing_docs[0]
            ok = feishu_client.update_docx_content(main_token, md_content)
            if ok:
                logger.info("每日结论文档已原地覆盖: %s", main_url)
                # 清理多余的重复文档
                for dup_token, _ in existing_docs[1:]:
                    feishu_client.delete_drive_file(dup_token, "docx")
                    logger.info("已清理重复每日结论文档: %s", dup_token[:12])
                return main_url
            logger.warning("原地覆盖失败，回退为删除重建")
            # 回退：删除所有旧文档，创建新的
            for old_token, _ in existing_docs:
                feishu_client.delete_drive_file(old_token, "docx")
        # 无同名文档或回退：创建新文档
        doc_result = feishu_client.create_docx_document(
            doc_title, md_content, folder_token=_DAILY_BROADCAST_FOLDER)
        url = doc_result.get("url", "")
        if url:
            logger.info("每日结论文档已上传云端: %s", url)
        return url
    except Exception as e:
        logger.warning("每日结论文档上传失败: %s", e)
        return ""


def _sync_daily_stats_to_bitable(report: dict, date_str: str):
    """将每日播报数据同步到数据沉淀统计表，写入后按日期降序排列"""
    try:
        from src.clients import feishu_client
        app_token = load_config().get("feishu_bitable", {}).get("app_token", "")
        stats_table_id = "tbl2R1L3Xz9NyS7i"  # 统计表 table_id
        if not app_token:
            return
        total = report.get("total", 0)
        if total == 0:
            logger.info("统计表同步跳过: %s 无数据", date_str)
            return
        # 日期转毫秒时间戳
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_ts = int(dt.timestamp() * 1000)
        # 成功率
        success = report.get("success", 0)
        fail = report.get("fail", 0)
        rate_val = round(success / total * 100, 1) if total else 0
        # 失败分析标签
        failures = report.get("failures", {})
        fail_tags = [f"{cat} {cnt}条" for cat, cnt in sorted(failures.items(), key=lambda x: -x[1])]
        fields_to_write = {
            "日期": date_ts,
            "测试总数": total,
            "PC端": report.get("pc_count", 0),
            "jira线上": report.get("online_count", 0),
            "成功": success,
            "失败": fail,
            "成功率": rate_val,
            "平均总耗时": report.get("avg_total_duration", "-"),
            "平均分析耗时": report.get("avg_analysis_duration", "-"),
            "失败分析": fail_tags,
        }
        # 读取已有记录，合并或替换当前日期数据
        records = feishu_client.list_bitable_records(app_token, stats_table_id)
        all_data = {}  # {date_ts: fields}
        for rec in records:
            f = rec.get("fields", {})
            rd = f.get("日期", 0)
            if isinstance(rd, (int, float)) and int(rd) > 0:
                all_data[int(rd)] = f
        # 写入当天数据（覆盖）
        all_data[date_ts] = fields_to_write
        # 按日期降序排列
        sorted_dates = sorted(all_data.keys(), reverse=True)
        sorted_records = [{"fields": all_data[d]} for d in sorted_dates]
        # 删除所有旧记录
        old_ids = [rec.get("record_id") for rec in records if rec.get("record_id")]
        if old_ids:
            feishu_client.batch_delete_records(app_token, stats_table_id, old_ids)
        # 按日期降序重新写入
        feishu_client.batch_create_records(app_token, stats_table_id, sorted_records)
        logger.info("统计表已同步并排序: %s (total=%d, 共%d条)", date_str, total, len(sorted_records))
    except Exception as e:
        logger.warning("统计表同步失败: %s", e)


def _bot_daily_broadcast(chat_id: str, date_str: str, is_scheduled: bool):
    """昨日结论播报执行函数（单次和定时共用），自动扩展到后续非工作日"""
    from src.clients import feishu_client
    try:
        # 计算日期范围用于展示
        report_dates = _get_report_date_range(date_str)
        date_label = f"{report_dates[0]} ~ {report_dates[-1]}" if len(report_dates) > 1 else date_str
        if not is_scheduled:
            ok = feishu_client.send_bot_message(chat_id, f"正在生成 {date_label} 每日结论...")
            if not ok:
                _auto_disable_daily_broadcast(chat_id)
                return
        report = _generate_daily_report(date_str)
        # 先上传云端，拿到文档 URL 后再发消息
        cloud_url = _upload_daily_report_to_cloud(report, date_str)
        if cloud_url:
            logger.info("昨日结论已上传: %s", cloud_url)
        # 同步到数据沉淀统计表
        _sync_daily_stats_to_bitable(report, date_str)
        msg = _format_daily_report_msg(report, date_str, cloud_url=cloud_url)
        ok = feishu_client.send_bot_message(chat_id, msg)
        if not ok:
            _auto_disable_daily_broadcast(chat_id)
            return
        # 保存到本地 CSV
        doc_dir = get_path("doc_dir")
        day_dir = os.path.join(doc_dir, date_str)
        os.makedirs(day_dir, exist_ok=True)
        daily_path = os.path.join(day_dir, f"{date_str}_daily_report.csv")
        import csv as _csv
        fieldnames = ["jira号", "执行结果", "触发时间", "执行时间", "分析耗时", "分析结果", "备注"]
        with open(daily_path, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in report["rows"]:
                w.writerow({col: r.get(col, "") for col in fieldnames})
    except Exception as e:
        logger.error("昨日结论播报失败: %s", e)
        try:
            feishu_client.send_bot_message(chat_id, f"工作日结论播报失败: {str(e)[:200]}")
        except Exception:
            pass
    finally:
        _clear_running_task(chat_id)


# ==================== 功能0.4：每周汇总 ====================

def _get_week_dates(date_str: str) -> dict:
    """根据给定日期计算所在 ISO 周的工作日列表

    :return: {"week_label", "week_id", "working_days", "monday", "sunday"}
    """
    from datetime import timedelta
    base = datetime.strptime(date_str, "%Y-%m-%d").date()
    # ISO 周：周一=0
    monday = base - timedelta(days=base.weekday())
    sunday = monday + timedelta(days=6)
    iso_year, iso_week, _ = base.isocalendar()
    week_id = f"{iso_year}W{iso_week:02d}"
    week_label = f"{iso_year}年第{iso_week}周"
    # 收集本周工作日（周一到周日中属于中国工作日的）
    working_days = []
    for i in range(7):
        day = monday + timedelta(days=i)
        if _is_chinese_workday(day):
            working_days.append(day.strftime("%Y-%m-%d"))
    return {"week_label": week_label, "week_id": week_id,
            "working_days": working_days,
            "monday": monday.strftime("%Y-%m-%d"),
            "sunday": sunday.strftime("%Y-%m-%d")}


def _generate_weekly_report(date_str: str, chat_id: str = "") -> dict:
    """生成指定日期所在周的汇总报告，聚合本周所有工作日的每日播报数据"""
    week_info = _get_week_dates(date_str)
    working_days = week_info["working_days"]
    if not working_days:
        return {"total": 0, "success": 0, "fail": 0, "pending": 0, "dedup": 0,
                "regression": 0, "too_long": 0, "failures": {}, "todo_items": [],
                "daily_breakdown": [], "rows": [], "week_info": week_info,
                "pc_count": 0, "online_count": 0}
    # 优化：先收集所有天的 jira 号，只查询一次多维表格
    all_jira = set()
    day_batch_data = {}  # {day: (jira_exec, dedup_count)}
    for day in working_days:
        report_dates = _get_report_date_range(day)
        jira_exec, dedup_count = _read_multi_day_batch_records(report_dates)
        day_batch_data[day] = (jira_exec, dedup_count)
        all_jira.update(jira_exec.keys())
        logger.info("每周汇总: %s 读取到 %d 条记录", day, len(jira_exec))
    # 一次性查询多维表格
    bt_map = {}
    if all_jira:
        from src.clients import feishu_client
        cfg = load_config().get("feishu_bitable", {})
        app_token, table_id = cfg.get("app_token", ""), cfg.get("table_id", "")
        bugid_field = cfg.get("bugid_field", "jira号")
        report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
        if app_token and table_id:
            try:
                records = feishu_client.list_bitable_records(app_token, table_id)
                for rec in records:
                    fields = rec.get("fields", {})
                    jira_key = _bitable_text(fields.get(bugid_field, ""))
                    if jira_key and jira_key in all_jira:
                        bt_map.setdefault(jira_key, []).append(
                            _flatten_bitable_record_all(fields, report_field))
                logger.info("每周汇总: 多维表格查询完成, %d 条记录匹配", len(bt_map))
            except Exception as e:
                logger.warning("每周汇总: 多维表格查询失败: %s", e)
    # 逐日生成报告（使用共享的多维表格数据）
    daily_breakdown = []
    all_rows = []
    all_failures = {}
    all_failure_jiras = {}
    all_todo = []
    total = success = fail = pending = dedup = regression = too_long = 0
    pc_count = online_count = 0
    for day in working_days:
        if chat_id and _is_cancelled(chat_id):
            logger.info("每周汇总: 被用户取消")
            break
        # 跳过无数据的工作日
        preloaded = day_batch_data.get(day)
        if preloaded and not preloaded[0]:
            daily_breakdown.append({"date": day, "total": 0, "success": 0, "fail": 0,
                                    "pending": 0, "dedup": 0, "rate": "-", "avg_analysis": "-"})
            continue
        try:
            day_report = _generate_daily_report(day, bt_map=bt_map, preloaded_batch=preloaded)
        except Exception as e:
            logger.error("每周汇总: %s 日报生成失败: %s", day, e)
            day_report = {"total": 0, "success": 0, "fail": 0, "pending": 0,
                          "dedup": 0, "regression": 0, "too_long": 0, "failures": {},
                          "todo_items": [], "rows": [], "avg_analysis_duration": "-"}
        dt = day_report.get("total", 0)
        ds = day_report.get("success", 0)
        df = day_report.get("fail", 0)
        dp = day_report.get("pending", 0)
        dd = day_report.get("dedup", 0)
        dr = day_report.get("regression", 0)
        dtl = day_report.get("too_long", 0)
        rate = f"{ds / dt * 100:.0f}%" if dt else "-"
        daily_breakdown.append({
            "date": day, "total": dt, "success": ds, "fail": df,
            "pending": dp, "dedup": dd, "rate": rate,
            "avg_analysis": day_report.get("avg_analysis_duration", "-"),
        })
        total += dt; success += ds; fail += df; pending += dp
        dedup += dd; regression += dr; too_long += dtl
        pc_count += day_report.get("pc_count", 0)
        online_count += day_report.get("online_count", 0)
        for cat, cnt in day_report.get("failures", {}).items():
            all_failures[cat] = all_failures.get(cat, 0) + cnt
        for cat, jlist in day_report.get("failure_jiras", {}).items():
            all_failure_jiras.setdefault(cat, []).extend(jlist)
        for item in day_report.get("todo_items", []):
            item["日期"] = day
            all_todo.append(item)
        for r in day_report.get("rows", []):
            r["日期"] = day
            all_rows.append(r)
    all_rows.sort(key=lambda x: (x.get("日期", ""), x.get("jira号", "")))
    weekly_rate = f"{success / total * 100:.1f}%" if total else "0%"
    return {"total": total, "success": success, "fail": fail, "pending": pending,
            "dedup": dedup, "regression": regression, "too_long": too_long,
            "failures": all_failures, "failure_jiras": all_failure_jiras, "todo_items": all_todo,
            "daily_breakdown": daily_breakdown, "rows": all_rows,
            "week_info": week_info, "weekly_rate": weekly_rate,
            "pc_count": pc_count, "online_count": online_count}


def _generate_range_report(start_date: str, end_date: str, chat_id: str = "") -> dict:
    """生成自定义时间段汇总报告，聚合指定日期范围内所有工作日的每日播报数据"""
    from datetime import timedelta as _td
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    if start > end:
        start, end = end, start
        start_date, end_date = end_date, start_date
    # 收集范围内所有工作日
    working_days = []
    cur = start
    while cur <= end:
        if _is_chinese_workday(cur):
            working_days.append(cur.strftime("%Y-%m-%d"))
        cur += _td(days=1)
    range_label = f"{start_date} ~ {end_date}"
    range_info = {"range_label": range_label, "start": start_date, "end": end_date,
                  "working_days": working_days}
    if not working_days:
        return {"total": 0, "success": 0, "fail": 0, "pending": 0, "dedup": 0,
                "regression": 0, "too_long": 0, "failures": {}, "todo_items": [],
                "daily_breakdown": [], "rows": [], "range_info": range_info,
                "weekly_rate": "0%", "pc_count": 0, "online_count": 0}
    # 复用周报的核心逻辑：先收集 jira + 一次 bitable 查询 + 逐日生成
    all_jira = set()
    day_batch_data = {}
    for day in working_days:
        report_dates = _get_report_date_range(day)
        jira_exec, dedup_count = _read_multi_day_batch_records(report_dates)
        day_batch_data[day] = (jira_exec, dedup_count)
        all_jira.update(jira_exec.keys())
        logger.info("时间段汇总: %s 读取到 %d 条记录", day, len(jira_exec))
    bt_map = {}
    if all_jira:
        from src.clients import feishu_client
        cfg = load_config().get("feishu_bitable", {})
        app_token, table_id = cfg.get("app_token", ""), cfg.get("table_id", "")
        bugid_field = cfg.get("bugid_field", "jira号")
        report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
        if app_token and table_id:
            try:
                records = feishu_client.list_bitable_records(app_token, table_id)
                for rec in records:
                    fields = rec.get("fields", {})
                    jira_key = _bitable_text(fields.get(bugid_field, ""))
                    if jira_key and jira_key in all_jira:
                        bt_map.setdefault(jira_key, []).append(
                            _flatten_bitable_record_all(fields, report_field))
                logger.info("时间段汇总: 多维表格查询完成, %d 条记录匹配", len(bt_map))
            except Exception as e:
                logger.warning("时间段汇总: 多维表格查询失败: %s", e)
    # 逐日生成报告
    daily_breakdown = []
    all_rows = []
    all_failures = {}
    all_failure_jiras = {}
    all_todo = []
    total = success = fail = pending = dedup = regression = too_long = 0
    pc_count = online_count = 0
    for day in working_days:
        if chat_id and _is_cancelled(chat_id):
            break
        preloaded = day_batch_data.get(day)
        if preloaded and not preloaded[0]:
            daily_breakdown.append({"date": day, "total": 0, "success": 0, "fail": 0,
                                    "pending": 0, "dedup": 0, "rate": "-", "avg_analysis": "-"})
            continue
        try:
            day_report = _generate_daily_report(day, bt_map=bt_map, preloaded_batch=preloaded)
        except Exception as e:
            logger.error("时间段汇总: %s 日报生成失败: %s", day, e)
            day_report = {"total": 0, "success": 0, "fail": 0, "pending": 0,
                          "dedup": 0, "regression": 0, "too_long": 0, "failures": {},
                          "todo_items": [], "rows": [], "avg_analysis_duration": "-"}
        dt = day_report.get("total", 0)
        ds = day_report.get("success", 0)
        df = day_report.get("fail", 0)
        dp = day_report.get("pending", 0)
        dd = day_report.get("dedup", 0)
        dr = day_report.get("regression", 0)
        dtl = day_report.get("too_long", 0)
        rate = f"{ds / dt * 100:.0f}%" if dt else "-"
        daily_breakdown.append({
            "date": day, "total": dt, "success": ds, "fail": df,
            "pending": dp, "dedup": dd, "rate": rate,
            "avg_analysis": day_report.get("avg_analysis_duration", "-"),
        })
        total += dt; success += ds; fail += df; pending += dp
        dedup += dd; regression += dr; too_long += dtl
        pc_count += day_report.get("pc_count", 0)
        online_count += day_report.get("online_count", 0)
        for cat, cnt in day_report.get("failures", {}).items():
            all_failures[cat] = all_failures.get(cat, 0) + cnt
        for cat, jlist in day_report.get("failure_jiras", {}).items():
            all_failure_jiras.setdefault(cat, []).extend(jlist)
        for item in day_report.get("todo_items", []):
            item["日期"] = day
            all_todo.append(item)
        for r in day_report.get("rows", []):
            r["日期"] = day
            all_rows.append(r)
    all_rows.sort(key=lambda x: (x.get("日期", ""), x.get("jira号", "")))
    weekly_rate = f"{success / total * 100:.1f}%" if total else "0%"
    return {"total": total, "success": success, "fail": fail, "pending": pending,
            "dedup": dedup, "regression": regression, "too_long": too_long,
            "failures": all_failures, "failure_jiras": all_failure_jiras, "todo_items": all_todo,
            "daily_breakdown": daily_breakdown, "rows": all_rows,
            "range_info": range_info, "weekly_rate": weekly_rate,
            "pc_count": pc_count, "online_count": online_count}


def _format_weekly_report_msg(report: dict, date_str: str, cloud_url: str = "") -> str:
    """将每周汇总格式化为飞书消息"""
    wi = report["week_info"]
    days = wi["working_days"]
    day_range = f"{days[0][5:]}~{days[-1][5:]}" if days else ""
    total = report["total"]
    if total == 0:
        return f"📊 每周汇总 {wi['week_label']} ({day_range})\n\n本周无批量执行记录"
    success = report["success"]
    msg = f"📊 每周汇总 {wi['week_label']} ({day_range})\n\n"
    msg += f"执行总数：{total}\n"
    pc = report.get("pc_count", 0)
    ol = report.get("online_count", 0)
    if pc or ol:
        msg += f"💻 PC：{pc}\n"
        msg += f"🌐 线上：{ol}\n"
    msg += f"🔁 回归：{report.get('regression', 0)}\n"
    msg += f"✅ 成功：{success}\n"
    msg += f"❌ 失败：{report['fail']}\n"
    if report.get("pending"):
        msg += f"⏳ 待分析：{report['pending']}\n"
    if report.get("dedup"):
        msg += f"🔀 去重：{report['dedup']}\n"
    msg += f"成功率：{report.get('weekly_rate', '0%')}\n"
    # 每日统计
    msg += "\n每日统计：\n"
    for db in report.get("daily_breakdown", []):
        d = db["date"][5:]  # MM-DD
        msg += f"  {d}：{db['total']}条 成功{db['success']} 失败{db['fail']} {db['rate']}\n"
    # 失败分类
    failures = report.get("failures", {})
    if failures:
        msg += "\n失败分析：\n"
        for cat, cnt in failures.items():
            msg += f"  · {cat}：{cnt}\n"
    todo = report.get("todo_items", [])
    if todo:
        msg += f"\n📝 待办跟进：{len(todo)} 项（详见文档）\n"
    msg += "\n"
    detail_url = cloud_url or get_daily_report_url()
    msg += detail_url
    return msg


def _upload_weekly_report_to_cloud(report: dict, date_str: str) -> str:
    """将每周汇总上传到云端文件夹（原地覆盖）"""
    from src.clients import feishu_client
    wi = report["week_info"]
    doc_title = f"每周汇总_{wi['week_id']}"
    # 查找同名文档
    existing_docs = []
    try:
        existing = feishu_client.list_folder_files(_DAILY_BROADCAST_FOLDER)
        for f in existing:
            if f.get("name") == doc_title and f.get("type") == "docx":
                existing_docs.append((f["token"], f.get("url", "")))
    except Exception as e:
        logger.warning("查找每周汇总文档失败: %s", e)
    # 生成 Markdown
    total = report["total"]
    success = report["success"]
    fail = report["fail"]
    rate = report.get("weekly_rate", "0%")
    days = wi["working_days"]
    day_range = f"{days[0][5:]}~{days[-1][5:]}" if days else ""
    lines = [f"# {doc_title}", "",
             f"## {wi['week_label']} ({day_range})", "",
             "## 结论", "",
             f"- 执行总数：{total}",
             f"- 💻 PC：{report.get('pc_count', 0)}",
             f"- 🌐 线上：{report.get('online_count', 0)}",
             f"- 回归：{report.get('regression', 0)}",
             f"- 成功：{success}",
             f"- 失败：{fail}",
             f"- 待分析：{report.get('pending', 0)}",
             f"- 去重：{report.get('dedup', 0)}",
             f"- 成功率：{rate}", ""]
    # 每日统计表
    lines.append("## 每日统计")
    lines.append("")
    lines.append("| 日期 | 总数 | 成功 | 失败 | 去重 | 成功率 | 平均分析耗时 |")
    lines.append("|------|------|------|------|------|--------|------------|")
    for db in report.get("daily_breakdown", []):
        lines.append(f"| {db['date']} | {db['total']} | {db['success']} | {db['fail']} | {db.get('dedup', 0)} | {db['rate']} | {db.get('avg_analysis', '-')} |")
    lines.append("")
    # 失败分析
    failures = report.get("failures", {})
    if failures:
        lines.append("## 失败分析")
        lines.append("")
        for cat, cnt in sorted(failures.items(), key=lambda x: -x[1]):
            lines.append(f"- {cat}：{cnt} 条")
        lines.append("")
    # 待办跟进
    todo = report.get("todo_items", [])
    if todo:
        lines.append("## 待办跟进")
        lines.append("")
        lines.append(f"共 {len(todo)} 项待处理：")
        lines.append("")
        lines.append("| 日期 | Jira号 | 原因 |")
        lines.append("|------|--------|------|")
        for item in todo:
            lines.append(f"| {item.get('日期', '')} | {item['jira号']} | {item['reason']} |")
        lines.append("")
    # 执行详情（合并所有天，按日期分组）
    lines.append("## 执行详情")
    lines.append("")
    rows = report.get("rows", [])
    too_long_threshold = 900
    failed_rows, pending_rows, too_long_rows, normal_rows = [], [], [], []
    for r in rows:
        ar = r.get("分析结果", "") or ""
        asec = _parse_dur_sec(r.get("分析耗时", ""))
        is_tl = asec > too_long_threshold if asec > 0 else False
        if ar == "失败":
            failed_rows.append(r)
        elif not ar or ar == "分析中":
            pending_rows.append(r)
        elif is_tl:
            too_long_rows.append(r)
        else:
            normal_rows.append(r)
    detail_header = ["| 日期 | Jira号 | 执行时间 | 分析耗时 | 分析结果 |",
                     "|------|--------|----------|----------|----------|"]
    def _detail_row(r):
        return (f"| {r.get('日期', '')} | {r.get('jira号', '')} | "
                f"{r.get('执行时间', '')} | {r.get('分析耗时', '')} | "
                f"{r.get('分析结果', '') or r.get('备注', '')[:50]} |")
    for label, group in [(f"分析失败（{len(failed_rows)}条）", failed_rows),
                         (f"待开发排查（{len(pending_rows)}条）", pending_rows),
                         (f"耗时过长（{len(too_long_rows)}条）", too_long_rows),
                         (f"分析成功（{len(normal_rows)}条）", normal_rows)]:
        lines.append(f"### {label}")
        lines.append("")
        if group:
            lines.extend(detail_header)
            for r in group:
                lines.append(_detail_row(r))
        else:
            lines.append("无")
        lines.append("")
    md_content = "\n".join(lines)
    # 上传：原地覆盖
    try:
        if existing_docs:
            main_token, main_url = existing_docs[0]
            ok = feishu_client.update_docx_content(main_token, md_content)
            if ok:
                logger.info("每周汇总文档已原地覆盖: %s", main_url)
                for dup_token, _ in existing_docs[1:]:
                    feishu_client.delete_drive_file(dup_token, "docx")
                return main_url
            for old_token, _ in existing_docs:
                feishu_client.delete_drive_file(old_token, "docx")
        doc_result = feishu_client.create_docx_document(
            doc_title, md_content, folder_token=_DAILY_BROADCAST_FOLDER)
        url = doc_result.get("url", "")
        if url:
            logger.info("每周汇总文档已上传云端: %s", url)
        return url
    except Exception as e:
        logger.warning("每周汇总文档上传失败: %s", e)
        return ""


def _bot_weekly_broadcast(chat_id: str, date_str: str):
    """每周汇总播报执行函数"""
    from src.clients import feishu_client
    _reset_cancel_event(chat_id)
    try:
        week_info = _get_week_dates(date_str)
        feishu_client.send_bot_message(chat_id,
            f"正在生成 {week_info['week_label']} 每周汇总...")
        report = _generate_weekly_report(date_str, chat_id=chat_id)
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        cloud_url = _upload_weekly_report_to_cloud(report, date_str)
        if cloud_url:
            logger.info("每周汇总已上传: %s", cloud_url)
        msg = _format_weekly_report_msg(report, date_str, cloud_url=cloud_url)
        feishu_client.send_bot_message(chat_id, msg)
    except Exception as e:
        logger.error("每周汇总播报失败: %s", e)
        try:
            feishu_client.send_bot_message(chat_id, f"每周汇总失败: {str(e)[:200]}")
        except Exception:
            pass
    finally:
        _clear_running_task(chat_id)


def _is_chinese_workday(dt) -> bool:
    """判断是否为中国法定工作日（含调休补班），无法判断时回退到周一~周五"""
    try:
        from chinese_calendar import is_workday
        return is_workday(dt.date() if hasattr(dt, 'date') else dt)
    except Exception:
        # 回退到普通工作日判断
        return dt.weekday() < 5


def _get_prev_chinese_workday(dt) -> str:
    """获取指定日期之前的最近一个中国法定工作日（含调休补班）

    :param dt: 当前日期（datetime 或 date）
    :return: 前一工作日字符串 YYYY-MM-DD
    """
    from datetime import timedelta
    current = dt.date() if hasattr(dt, 'date') and callable(dt.date) else dt
    for i in range(1, 31):  # 最多回朔 30 天
        prev = current - timedelta(days=i)
        try:
            from chinese_calendar import is_workday
            if is_workday(prev):
                return prev.strftime("%Y-%m-%d")
        except Exception:
            if prev.weekday() < 5:
                return prev.strftime("%Y-%m-%d")
    # 回退到前一天
    prev = current - timedelta(days=1)
    return prev.strftime("%Y-%m-%d")


def _get_report_date_range(date_str: str) -> list:
    """根据指定工作日计算播报应覆盖的日期范围（包含当天及之后所有非工作日，直到下一个工作日之前）

    场景：
    - 周五 → [周五, 周六, 周日]
    - 春节前最后一个工作日 → [工作日, 假1, 假2, ..., 下一工作日前一天]
    - 普通工作日且次日也是工作日 → [当天]
    """
    from datetime import timedelta
    base = datetime.strptime(date_str, "%Y-%m-%d").date()
    dates = [date_str]
    for i in range(1, 31):  # 最多往后看 30 天
        next_day = base + timedelta(days=i)
        if _is_chinese_workday(next_day):
            break  # 遇到下一个工作日就停止
        dates.append(next_day.strftime("%Y-%m-%d"))
    return dates


def _daily_scheduler_loop():
    """定时调度器：每30秒检查是否有群聊需要播报（使用中国法定工作日，播报前一工作日数据）"""
    logger.info("昨日播报调度器已启动")
    last_executed = {}  # {chat_id_date_time: True}
    while not _daily_scheduler_stop.is_set():
        try:
            cfg = _load_daily_broadcast_config()
            now = datetime.now()
            cur_time = now.strftime("%H:%M")
            cur_date = now.strftime("%Y-%m-%d")
            if _is_chinese_workday(now):
                for chat_id, chat_cfg in cfg.items():
                    if not chat_cfg.get("enabled"):
                        continue
                    report_time = chat_cfg.get("report_time", "17:50")
                    if cur_time == report_time:
                        # 避免同一天同一时间重复执行
                        key = f"{chat_id}_{cur_date}_{cur_time}"
                        if key not in last_executed:
                            last_executed[key] = True
                            # 播报前一工作日的数据
                            prev_workday = _get_prev_chinese_workday(now)
                            logger.info("触发昨日播报: chat=%s, 当前=%s, 播报日期=%s, time=%s",
                                       chat_id[:12], cur_date, prev_workday, cur_time)
                            try:
                                _bot_daily_broadcast(chat_id, prev_workday, True)
                            except Exception as e:
                                logger.error("定时播报执行失败: %s", e)
            # 清理过期的执行记录（只保留当天的）
            expired = [k for k in last_executed if cur_date not in k]
            for k in expired:
                del last_executed[k]
        except Exception as e:
            logger.warning("昨日播报调度器异常: %s", e)
        _daily_scheduler_stop.wait(30)  # 每30秒检查一次，确保不错过整分钟
    logger.info("昨日播报调度器已停止")


def _restart_daily_scheduler():
    """重启每日播报调度器线程（等待旧线程退出后再启新线程，防止重复触发）"""
    global _daily_scheduler_thread, _daily_scheduler_stop
    import threading
    # 停止旧的并等待退出
    old_thread = _daily_scheduler_thread
    if _daily_scheduler_stop:
        _daily_scheduler_stop.set()
    if old_thread and old_thread.is_alive():
        old_thread.join(timeout=5)  # 最多等待 5 秒
    _daily_scheduler_stop = threading.Event()
    _daily_scheduler_thread = threading.Thread(
        target=_daily_scheduler_loop, name="daily-broadcast-scheduler", daemon=True)
    _daily_scheduler_thread.start()


# 服务启动时自动启动调度器（如果有已开启的群聊）
def _init_daily_scheduler():
    """服务启动时初始化每日播报调度器"""
    cfg = _load_daily_broadcast_config()
    has_enabled = any(v.get("enabled") for v in cfg.values())
    if has_enabled:
        _restart_daily_scheduler()
        logger.info("昨日播报调度器已初始化（%d 个群聊已开启）",
                   sum(1 for v in cfg.values() if v.get("enabled")))

def _bot_run_single_execute(chat_id: str, bugids: list, exec_mode: str = "pc"):
    """功能6.2后台执行：提取触发时间→根据执行模式调用对应接口

    exec_mode: 'pc' 调用PC接口，'online' 调用线上接口。
    支持「退出」中断。
    """
    from src.clients import feishu_client
    from src.clients.base import http_post
    _reset_cancel_event(chat_id)
    try:
        mode_label = "线上" if exec_mode == "online" else "PC"
        # 步骤1：提取触发时间
        feishu_client.send_bot_message(chat_id, f"步骤1/2：提取触发时间（{len(bugids)} 个）...")
        trigger_times = _bot_get_trigger_times(bugids)
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        has_time = sum(1 for b in bugids if b in trigger_times)
        feishu_client.send_bot_message(chat_id, f"提取完成: {has_time}/{len(bugids)} 有触发时间")
        # 仅执行有触发时间的记录
        run_bugids = [b for b in bugids if b in trigger_times]
        if not run_bugids:
            feishu_client.send_bot_message(chat_id, "所有 Jira 号均无触发时间，无法执行")
            return
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        # 步骤2：执行
        feishu_client.send_bot_message(chat_id, f"步骤2/2：{mode_label}执行 {len(run_bugids)} 条...")
        success = 0
        lines = []
        results = []
        batch_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for bugid in run_bugids:
            if _is_cancelled(chat_id):
                lines.append(f"⊘ 任务已被用户取消，剩余 {len(run_bugids) - run_bugids.index(bugid)} 条未执行")
                break
            exec_time = trigger_times.get(bugid)
            try:
                if exec_mode == "online":
                    payload = {"jiraNumber": bugid, "questionTimes": [exec_time]}
                    resp = http_post(_PROD_AI_URL, payload, timeout=30)
                else:
                    cfg = load_config()["ai_log_api"]
                    payload = {cfg["bugid_field"]: bugid}
                    if cfg.get("trigger_time_field"):
                        payload[cfg["trigger_time_field"]] = exec_time
                    resp = http_post(cfg["url"], payload, timeout=int(cfg.get("timeout", 60)))
                resp_code = resp.get("code") if isinstance(resp, dict) else None
                resp_msg = str(resp.get("msg", "")) if isinstance(resp, dict) else str(resp)[:200]
                is_ok = (resp_code == 200 or resp_code == 0 or resp_code == "200")
                if is_ok:
                    success += 1
                    line = f"✓ {bugid} 执行成功（{exec_time}）"
                else:
                    line = f"✗ {bugid} 执行失败（{resp_msg[:100]}）"
                results.append({"jira号": bugid, "执行结果": "成功" if is_ok else "失败", "报告长度": 0,
                                "备注": resp_msg[:200], "触发时间": exec_time, "执行时间": batch_start,
                                "分析执行时间": batch_start})
            except Exception as e:
                line = f"✗ {bugid} 执行异常：{str(e)[:100]}"
                results.append({"jira号": bugid, "执行结果": "失败", "报告长度": 0,
                                "备注": str(e)[:200], "触发时间": exec_time, "执行时间": batch_start,
                                "分析执行时间": batch_start})
            lines.append(line)
        if _is_cancelled(chat_id):
            return
        # 保存执行记录
        try:
            _save_bot_execution_results(results, batch_name=f"single_{exec_mode}_{datetime.now().strftime('%H%M%S')}")
        except Exception as e:
            logger.warning("机器人单个执行结果保存失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"批量执行{len(run_bugids)}个，成功{success}个，失败{len(run_bugids)-success}个，均在分析中。")
    finally:
        _clear_running_task(chat_id)


def _bot_run_ai_analysis(chat_id: str, bugids: list):
    """功能6.1后台执行：获取触发时间后用 Jira 号逐个触发 AI 分析并即时回复结果"""
    from src.clients import feishu_client
    _reset_cancel_event(chat_id)  # 重置取消标记
    trigger_times = _bot_get_trigger_times(bugids)
    if _is_cancelled(chat_id):
        feishu_client.send_bot_message(chat_id, "任务已被用户取消")
        return
    success, _, results = _bot_trigger_and_reply(chat_id, bugids, trigger_times)
    if _is_cancelled(chat_id):
        return  # 已被取消，不再发送结果
    # 保存本地记录
    try:
        _save_bot_execution_results(results, batch_name=f"bot_{datetime.now().strftime('%H%M%S')}")
    except Exception as e:
        logger.warning("机器人执行结果保存本地失败: %s", e)
    feishu_client.send_bot_message(chat_id, f"全部执行完成：成功 {success}/{len(bugids)}")


def _bot_run_batch_ai(chat_id: str, jql_key: str, count: int, exec_mode: str = "pc",
                      filters: dict = None, batch_meta: dict = None):
    """功能6.1.1后台执行：JQL搜索→过滤→随机抽样→提取时间→执行"""
    import random
    from src.clients import feishu_client
    from src.clients import jira_client as _jc
    from src.clients.base import http_post
    _reset_cancel_event(chat_id)
    try:
        jql_presets = _get_jql_presets()
        preset = jql_presets.get(jql_key)
        if not preset:
            feishu_client.send_bot_message(chat_id, f"未找到 JQL 编号 {jql_key}")
            return
        label, jql = preset
        mode_label = "线上" if exec_mode == "online" else "PC"
        # 步骤1：JQL搜索
        feishu_client.send_bot_message(chat_id, f"步骤1/5：JQL搜索 [{jql_key}({label})]...")
        try:
            issues = _jc.search_issues(jql, max_results=2000)
            candidates = [(i.get("key") or "").strip() for i in issues if "VCU" in (i.get("key") or "").upper()]
        except Exception as e:
            logger.warning("机器人 JQL 搜索失败: %s", e)
            feishu_client.send_bot_message(chat_id, f"JQL 搜索失败：{str(e)[:150]}")
            return
        if not candidates:
            feishu_client.send_bot_message(chat_id, "JQL 搜索无 VCU 结果，请检查 JQL 条件")
            return
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        # 步骤2：多维表格去重过滤
        feishu_client.send_bot_message(chat_id, f"搜索完成 {len(candidates)} 条，步骤2/5：过滤记录...")
        filtered = _bot_apply_bitable_filter(candidates, filters)
        logger.info("机器人JQL过滤: 搜索%d→剩余%d", len(candidates), len(filtered))
        if not filtered:
            feishu_client.send_bot_message(chat_id, f"搜索 {len(candidates)} 条均已被过滤，无需执行")
            return
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        # 步骤3+4：增量抽样+提取触发时间（凑够 count 个有触发时间的才停止）
        tested = _load_all_doc_jira_keys()
        remaining = [k for k in filtered if k not in tested]
        if not remaining:
            feishu_client.send_bot_message(chat_id, f"过滤后 {len(filtered)} 条均已测试过，无可抽取")
            return
        selected = []
        trigger_times = {}
        batch_num = 0
        while len(trigger_times) < count and remaining:
            batch_num += 1
            need = count - len(trigger_times)
            batch_size = min(need, len(remaining))
            batch = random.sample(remaining, batch_size)
            remaining = [k for k in remaining if k not in batch]
            feishu_client.send_bot_message(chat_id,
                f"步骤3/5：第{batch_num}批抽取 {len(batch)} 条，已收集 {len(trigger_times)}/{count} 条触发时间...")
            batch_times = _bot_get_trigger_times(batch)
            trigger_times.update(batch_times)
            selected.extend(b for b in batch if b in batch_times)
            if _is_cancelled(chat_id):
                feishu_client.send_bot_message(chat_id, "任务已被用户取消")
                return
        selected = selected[:count]
        feishu_client.send_bot_message(chat_id,
            f"提取完成: 收集到 {len(selected)} 条触发时间（共提取 {batch_num} 批）")
        # 步骤5：执行（PC或线上）
        run_bugids = [b for b in selected if b in trigger_times]
        if not run_bugids:
            feishu_client.send_bot_message(chat_id, "抽取的记录均无触发时间，无法执行")
            return
        feishu_client.send_bot_message(chat_id, f"步骤5/5：{mode_label}执行 {len(run_bugids)} 条...")
        success = 0
        lines = []
        results = []
        batch_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for bugid in run_bugids:
            if _is_cancelled(chat_id):
                lines.append(f"⊘ 任务已被用户取消，剩余 {len(run_bugids) - run_bugids.index(bugid)} 条未执行")
                break
            exec_time = trigger_times.get(bugid)
            try:
                # 使用较短超时以实现快速中断
                _exec_timeout = 15
                if exec_mode == "online":
                    payload = {"jiraNumber": bugid, "questionTimes": [exec_time]}
                    resp = http_post(_PROD_AI_URL, payload, timeout=_exec_timeout)
                else:
                    cfg = load_config()["ai_log_api"]
                    payload = {cfg["bugid_field"]: bugid}
                    if cfg.get("trigger_time_field"):
                        payload[cfg["trigger_time_field"]] = exec_time
                    resp = http_post(cfg["url"], payload, timeout=_exec_timeout)
                # HTTP 完成后再次检查取消
                if _is_cancelled(chat_id):
                    results.append({"jira号": bugid, "执行结果": "成功", "报告长度": 0,
                                    "备注": "", "触发时间": exec_time, "执行时间": batch_start,
                                    "分析执行时间": batch_start})
                    success += 1
                    lines.append(f"⊘ 任务已被用户取消，剩余 {len(run_bugids) - run_bugids.index(bugid) - 1} 条未执行")
                    break
                resp_code = resp.get("code") if isinstance(resp, dict) else None
                resp_msg = str(resp.get("msg", "")) if isinstance(resp, dict) else str(resp)[:200]
                is_ok = (resp_code == 200 or resp_code == 0 or resp_code == "200")
                if is_ok:
                    success += 1
                    line = f"✓ {bugid} 执行成功（{exec_time}）"
                else:
                    line = f"✗ {bugid} 执行失败（{resp_msg[:100]}）"
                results.append({"jira号": bugid, "执行结果": "成功" if is_ok else "失败", "报告长度": 0,
                                "备注": resp_msg[:200], "触发时间": exec_time, "执行时间": batch_start,
                                "分析执行时间": batch_start})
            except Exception as e:
                line = f"✗ {bugid} 执行异常：{str(e)[:100]}"
                results.append({"jira号": bugid, "执行结果": "失败", "报告长度": 0,
                                "备注": str(e)[:200], "触发时间": exec_time, "执行时间": batch_start,
                                "分析执行时间": batch_start})
            lines.append(line)
        if _is_cancelled(chat_id):
            return
        # 保存执行记录
        try:
            _save_bot_execution_results(results, batch_name=f"bot_{exec_mode}_{datetime.now().strftime('%H%M%S')}", batch_meta=batch_meta)
        except Exception as e:
            logger.warning("机器人批量结果保存失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"批量执行{len(run_bugids)}个，成功{success}个，失败{len(run_bugids)-success}个，均在分析中。")
    finally:
        _clear_running_task(chat_id)


def _bot_run_csv_batch_ai(chat_id: str, bugids: list, csv_name: str = "",
                         exec_mode: str = "pc", filters: dict = None, batch_meta: dict = None):
    """功能6.1.2后台执行：CSV导入→过滤→随机抽样→提取时间→执行"""
    import random as _rand
    from src.clients import feishu_client
    from src.clients.base import http_post
    _reset_cancel_event(chat_id)
    try:
        mode_label = "线上" if exec_mode == "online" else "PC"
        feishu_client.send_bot_message(chat_id, f"CSV导入 {len(bugids)} 条 [{csv_name}]\n步骤1/4：过滤记录...")
        # 步骤1：多维表格去重过滤
        filtered = _bot_apply_bitable_filter(bugids, filters)
        logger.info("CSV过滤: 导入%d→剩余%d", len(bugids), len(filtered))
        if not filtered:
            feishu_client.send_bot_message(chat_id, f"CSV {len(bugids)} 条均已被过滤，无需执行")
            return
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        # 步骤2：随机抽样
        tested = _load_all_doc_jira_keys()
        available = [k for k in filtered if k not in tested]
        if not available:
            feishu_client.send_bot_message(chat_id, f"过滤后 {len(filtered)} 条均已测试过，无可抽取")
            return
        selected = list(available)
        feishu_client.send_bot_message(chat_id,
            f"过滤后 {len(filtered)} 条，步骤2/4：抽取 {len(selected)} 条")
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        # 步骤3：仅对抽样结果提取触发时间
        feishu_client.send_bot_message(chat_id, f"步骤3/4：提取触发时间（{len(selected)} 条）...")
        trigger_times = _bot_get_trigger_times(selected)
        has_time = sum(1 for b in selected if b in trigger_times)
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        feishu_client.send_bot_message(chat_id, f"提取完成: {has_time}/{len(selected)} 有触发时间")
        # 步骤4：执行（PC或线上）
        run_bugids = [b for b in selected if b in trigger_times]
        if not run_bugids:
            feishu_client.send_bot_message(chat_id, "抽取的记录均无触发时间，无法执行")
            return
        feishu_client.send_bot_message(chat_id, f"步骤4/4：{mode_label}执行 {len(run_bugids)} 条...")
        success, lines, results = _bot_trigger_and_reply(chat_id, run_bugids, trigger_times,
                                                         realtime=False, exec_mode=exec_mode)
        if _is_cancelled(chat_id):
            return
        try:
            _save_bot_execution_results(results, batch_name=f"csv_{datetime.now().strftime('%H%M%S')}", batch_meta=batch_meta)
        except Exception as e:
            logger.warning("CSV批量结果保存失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"批量执行{len(run_bugids)}个，成功{success}个，失败{len(run_bugids)-success}个，均在分析中。")
    finally:
        _clear_running_task(chat_id)


def _get_unanalyzed_jql_presets() -> dict:
    """Bug未分析提取的 JQL 预设（与测试页同步），返回 {编号: (标签, JQL)} 字典"""
    return {
        "JQL1": ("以往已关闭Bug", 'issuetype = bug AND created >= "2026/08/25" AND status = closed'),
        "JQL2": ("昨日新增Bug", "issuetype = bug AND created >= startOfDay('-1d') AND created <= endOfDay('-1d')"),
        "JQL3": ("昨日coreservice", 'issuetype = bug AND text ~ "coreservice" AND text ~ "VCU" AND created >= startOfDay(\'-1d\') AND created <= endOfDay(\'-1d\')'),
        "JQL4": ("昨日远控", 'issuetype = bug AND text ~ "远控" AND text ~ "VCU" AND created >= startOfDay(\'-1d\') AND created <= endOfDay(\'-1d\')'),
        "JQL5": ("昨日导航", 'issuetype = bug AND text ~ "SGM_Navigation750" AND text ~ "VCU" AND created >= startOfDay(\'-1d\') AND created <= endOfDay(\'-1d\')'),
    }


def _bot_confidence_batch(chat_id: str, after_time: str, only_empty: bool):
    """功能4.1后台执行：置信度批量写入（根因语义对比）"""
    from src.clients import feishu_client
    _reset_cancel_event(chat_id)
    try:
        import httpx as _httpx
        params = {"after_time": after_time, "only_empty": "true" if only_empty else ""}
        with _httpx.stream("GET", "http://127.0.0.1:8060/api/test/confidence_batch_write",
                           params=params, timeout=600) as resp:
            buffer = ""
            total = 0
            passed = 0
            low = 0
            failed = 0
            last_msg = ""
            for chunk in resp.iter_text():
                if _is_cancelled(chat_id):
                    feishu_client.send_bot_message(chat_id, "任务已被用户取消")
                    return
                buffer += chunk
                lines_buf = buffer.split("\n")
                buffer = lines_buf.pop() or ""
                for line in lines_buf:
                    if not line.startswith("data: "):
                        continue
                    try:
                        evt = json.loads(line[6:])
                        etype = evt.get("type", "")
                        if etype == "start":
                            total = evt.get("total", 0)
                            feishu_client.send_bot_message(chat_id, f"置信度写入开始：共 {total} 条待处理")
                        elif etype == "progress":
                            idx = evt.get("index", 0)
                            status = evt.get("status", "")
                            if status == "pass":
                                passed += 1
                            elif status == "low":
                                low += 1
                            else:
                                failed += 1
                            # 每 10 条汇报一次进度
                            if idx % 10 == 0:
                                feishu_client.send_bot_message(
                                    chat_id, f"进度: {idx}/{total}\n达标: {passed} | 未达标: {low} | 跳过: {failed}")
                        elif etype == "done":
                            last_msg = evt.get("msg", "")
                        elif etype == "error":
                            feishu_client.send_bot_message(chat_id, f"置信度写入失败: {evt.get('msg', '')}")
                            return
                    except Exception:
                        pass
        # 汇总报告
        summary = f"置信度批量写入完成\n总计: {total} 条\n达标: {passed} | 未达标: {low} | 跳过/失败: {failed}"
        if last_msg:
            summary += f"\n{last_msg}"
        feishu_client.send_bot_message(chat_id, summary)
    except Exception as e:
        logger.error("机器人功能4.1执行失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"置信度批量写入失败: {str(e)[:200]}")
    finally:
        _clear_running_task(chat_id)


def _bot_unanalyzed_bugs(chat_id: str, jql: str):
    """功能9.1后台执行：Bug未分析提取（JQL搜索 + 筛选未分析 + 保存CSV）"""
    from src.clients import feishu_client
    _reset_cancel_event(chat_id)
    try:
        import httpx as _httpx
        body = {"jql": jql, "filter_ai_init": True}
        results = []
        csv_paths = []
        with _httpx.stream("POST", "http://127.0.0.1:8060/api/test/unanalyzed_bugs",
                           json=body, timeout=600) as resp:
            buffer = ""
            for chunk in resp.iter_text():
                if _is_cancelled(chat_id):
                    feishu_client.send_bot_message(chat_id, "任务已被用户取消")
                    return
                buffer += chunk
                lines_buf = buffer.split("\n")
                buffer = lines_buf.pop() or ""
                for line in lines_buf:
                    if not line.startswith("data: "):
                        continue
                    try:
                        evt = json.loads(line[6:])
                        etype = evt.get("type", "")
                        if etype == "progress":
                            results.append(evt.get("bugid", ""))
                            if len(results) % 20 == 0:
                                feishu_client.send_bot_message(chat_id, f"已发现 {len(results)} 个未分析Bug...")
                        elif etype == "csv_saved":
                            csv_paths.append(evt.get("path", ""))
                        elif etype == "done":
                            pass
                        elif etype == "error":
                            feishu_client.send_bot_message(chat_id, f"未分析提取失败: {evt.get('msg', '')}")
                            return
                    except Exception:
                        pass
        # 汇总报告
        summary_lines = [f"Bug未分析提取完成", f"未分析: {len(results)} 个"]
        if results:
            summary_lines.append(f"前20个: {', '.join(results[:20])}")
            if len(results) > 20:
                summary_lines.append(f"...等共 {len(results)} 个")
        if csv_paths:
            for p in csv_paths:
                summary_lines.append(f"已保存: {p.split(chr(92))[-1] if chr(92) in p else p}")
        feishu_client.send_bot_message(chat_id, "\n".join(summary_lines))
    except Exception as e:
        logger.error("机器人功能9.1执行失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"未分析提取失败: {str(e)[:200]}")
    finally:
        _clear_running_task(chat_id)


def _bot_prod_batch_run(chat_id: str, bugids: list, filters: dict = None,
                       batch_meta: dict = None, exec_mode: str = "online", count: int = 0):
    """功能10.1后台执行：批量执行（提取触发时间→过滤→调用接口）"""
    from src.clients import feishu_client
    _reset_cancel_event(chat_id)
    mode_label = "线上" if exec_mode == "online" else "PC"
    try:
        # 步骤1：提取触发时间
        feishu_client.send_bot_message(chat_id, f"步骤1/3：提取触发时间（{len(bugids)} 个）...")
        trigger_times = _bot_get_trigger_times(bugids)
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        has_time = sum(1 for b in bugids if b in trigger_times)
        feishu_client.send_bot_message(chat_id, f"提取完成: {has_time}/{len(bugids)} 有触发时间")
        # 步骤2：多维表格去重过滤
        feishu_client.send_bot_message(chat_id, "步骤2/3：多维表格去重...")
        remaining = _bot_apply_bitable_filter(bugids, filters)
        # 仅保留有触发时间的记录
        remaining = [b for b in remaining if b in trigger_times]
        if count and count > 0:
            remaining = remaining[:count]
        feishu_client.send_bot_message(chat_id, f"过滤后剩余 {len(remaining)} 个")
        if not remaining:
            feishu_client.send_bot_message(chat_id, "所有 Jira 号均已被过滤，无需执行")
            return
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        # 步骤3：调用接口执行
        feishu_client.send_bot_message(chat_id, f"步骤3/3：{mode_label}执行 {len(remaining)} 个...")
        success, lines, results = _bot_trigger_and_reply(chat_id, remaining, trigger_times,
                                                         realtime=False, exec_mode=exec_mode)
        if _is_cancelled(chat_id):
            return
        # 保存执行记录
        try:
            _save_bot_execution_results(results, batch_name=f"prod_{datetime.now().strftime('%H%M%S')}", batch_meta=batch_meta)
        except Exception as e:
            logger.warning("机器人线上批量结果保存失败: %s", e)
        _bot_send_batch_results(chat_id, success, len(remaining), lines)
    except Exception as e:
        logger.error("机器人功能10.1执行失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"批量执行失败: {str(e)[:200]}")
    finally:
        _clear_running_task(chat_id)


@app.post("/api/feishu/event")
async def feishu_event(request: Request):
    """飞书事件订阅回调（HTTP回调模式，长连接模式下不经过此端点）"""
    data = await request.json() or {}
    if data.get("type") == "url_verification":
        challenge = data.get("challenge", "")
        logger.info("飞书事件订阅验证: challenge=%s", challenge[:20])
        return JSONResponse(content={"challenge": challenge})
    header = data.get("header", {})
    event = data.get("event", {})
    if header.get("event_type") == "im.message.receive_v1":
        _process_feishu_message_event(event)
    return JSONResponse(content={"code": 0})


@app.get("/api/feishu/events")
async def get_feishu_events():
    """查看已存储的飞书事件推送 + 卡片事件 + 最近消息（调试用）"""
    from src.clients import feishu_client as _fc
    events = dict(_fc._feishu_events)
    card_events = list(_fc._feishu_card_events[-20:][::-1])
    recent = list(_feishu_recent_messages[-20:][::-1])
    return _ok({
        "events": events, "count": len(events),
        "card_events": card_events, "card_count": len(card_events),
        "recent_messages": recent, "recent_count": len(recent)
    }, f"事件{len(events)}个 / 卡片{len(card_events)}条 / 消息{len(recent)}条")


@app.post("/api/test/feishu_msg_debug")
async def test_feishu_msg_debug(request: Request):
    """调试用：尝试所有认证方式读取指定群聊的消息"""
    import httpx as _httpx
    from src.clients import feishu_client as _fc
    body = await request.json() or {}
    chat_id = body.get("chat_id", "").strip() or "oc_2f087e0e79118bbfcd9a56841d2e2b7a"
    results = []
    url = f"https://open.feishu.cn/open-apis/im/v1/messages"
    params = {"container_id_type": "chat", "container_id": chat_id, "page_size": 5, "sort_type": "ByCreateTimeDesc"}
    # 方式1: tenant_access_token
    try:
        t_token = _fc.get_tenant_access_token()
        r1 = _httpx.get(url, headers={"Authorization": f"Bearer {t_token}"}, params=params, timeout=15, verify=False)
        d1 = r1.json()
        results.append({"method": "tenant_access_token", "status": r1.status_code,
                        "code": d1.get("code"), "msg": d1.get("msg", ""),
                        "items_count": len(d1.get("data", {}).get("items", [])),
                        "items": d1.get("data", {}).get("items", [])[:3]})
    except Exception as e:
        results.append({"method": "tenant_access_token", "error": str(e)})
    # 方式2: user_access_token
    cfg = _fc._get_bitable_cfg()
    u_token = cfg.get("user_access_token", "").strip()
    if u_token:
        try:
            r2 = _httpx.get(url, headers={"Authorization": f"Bearer {u_token}"}, params=params, timeout=15, verify=False)
            d2 = r2.json()
            results.append({"method": "user_access_token", "status": r2.status_code,
                            "code": d2.get("code"), "msg": d2.get("msg", ""),
                            "items_count": len(d2.get("data", {}).get("items", [])),
                            "items": d2.get("data", {}).get("items", [])[:3]})
        except Exception as e:
            results.append({"method": "user_access_token", "error": str(e)})
    else:
        results.append({"method": "user_access_token", "error": "无 user_access_token"})
    # 方式3: Cookie 认证（飞书内部 API）
    cookie = cfg.get("cookie", "").strip()
    if cookie:
        try:
            internal_url = f"https://internal-api-lark-api.feishu.cn/mercury/im/messages"
            r3 = _httpx.get(internal_url, headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"},
                            params={"chat_id": chat_id, "count": 5}, timeout=15, verify=False, follow_redirects=True)
            results.append({"method": "cookie_internal_api", "status": r3.status_code,
                            "body_preview": r3.text[:500]})
        except Exception as e:
            results.append({"method": "cookie_internal_api", "error": str(e)})
    else:
        results.append({"method": "cookie_internal_api", "error": "无 cookie 配置"})
    return _ok({"chat_id": chat_id, "results": results}, f"测试完成，chat_id={chat_id}")


def _read_csv_rows(path: str) -> list:
    """读取 CSV 报表为字典行列表，文件不存在返回空列表，自动过滤批次分隔空行"""
    if not os.path.exists(path):
        return []
    df = pd.read_csv(path, encoding="utf-8-sig")
    # 过滤批次分隔空行（jira号 为空或 NaN 的行）
    first_col = df.columns[0] if len(df.columns) else "jira号"
    df = df[df[first_col].notna() & (df[first_col].astype(str).str.strip() != "")]
    return df.fillna("").astype(str).to_dict(orient="records")


# 云端批次记录缓存：避免同一日期重复读取云端
_cloud_batch_cache = {}  # {date_str: {"ts": float, "data": {jira_no: exec_info}}}
_CLOUD_CACHE_TTL = 300  # 5分钟缓存


def _read_today_batch_records(date_str: str) -> tuple:
    """读取今日所有批量执行记录，兼容 docs + data/unanalyzed + 云端 三个路径

    规则：
    1. 整个批次CSV全部失败 → 跳过
    2. 仅返回执行成功的记录

    :return: (dict, int) - {jira_no: {...}}, dedup_count
    """
    jira_exec = {}
    dedup_count = 0  # 去重数量

    def _process_batch(rows: list) -> dict:
        """处理一批CSV行，返回成功记录"""
        # 整个批次全部失败则跳过
        has_success = any((r.get("执行结果") or "").strip() == "成功" for r in rows)
        if not has_success:
            return {}
        result = {}
        for r in rows:
            # 兼容 jira号 / Jira号 两种字段名
            jira_no = (r.get("jira号") or r.get("Jira号") or "").strip()
            if not jira_no:
                continue
            exec_result = (r.get("执行结果") or "").strip()
            if exec_result != "成功":
                continue
            exec_time = (r.get("执行时间") or "").strip()
            trigger_time = (r.get("触发时间") or "").strip()
            if jira_no in result:
                # 同一Jira重复执行，去重保留执行时间最晚的
                dedup_count += 1
                if exec_time > result[jira_no].get("执行时间", ""):
                    result[jira_no] = {
                        "执行结果": exec_result,
                        "触发时间": trigger_time,
                        "执行时间": exec_time,
                        "分析并发数": (r.get("分析并发数") or "").strip(),
                        "下载并发数": (r.get("下载并发数") or "").strip(),
                        "模型": (r.get("模型") or "").strip(),
                        "触发来源": (r.get("触发来源") or "").strip(),
                    }
            else:
                result[jira_no] = {
                    "执行结果": exec_result,
                    "触发时间": trigger_time,
                    "执行时间": exec_time,
                    "分析并发数": (r.get("分析并发数") or "").strip(),
                    "下载并发数": (r.get("下载并发数") or "").strip(),
                    "模型": (r.get("模型") or "").strip(),
                    "触发来源": (r.get("触发来源") or "").strip(),
                }
        return result

    # 路径1：docs/日期/batch_*.csv（PC侧批量执行 + 机器人批量执行）
    doc_dir = get_path("doc_dir")
    day_dir = os.path.join(doc_dir, date_str)
    if os.path.isdir(day_dir):
        for fname in sorted(os.listdir(day_dir)):
            if not fname.lower().startswith("batch_") or not fname.lower().endswith(".csv"):
                continue
            rows = _read_csv_rows(os.path.join(day_dir, fname))
            jira_exec.update(_process_batch(rows))

    # 路径2：data/unanalyzed/prod_batch_{日期}_*.csv（线上批量执行）
    unanalyzed_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "unanalyzed")
    if os.path.isdir(unanalyzed_dir):
        prefix = f"prod_batch_{date_str}_"
        for fname in sorted(os.listdir(unanalyzed_dir)):
            if not fname.startswith(prefix) or not fname.endswith(".csv"):
                continue
            rows = _read_csv_rows(os.path.join(unanalyzed_dir, fname))
            jira_exec.update(_process_batch(rows))

    # 路径3：云端批次执行记录（其他机器/飞书机器人执行的记录）
    import time as _time
    cached = _cloud_batch_cache.get(date_str)
    if cached and (_time.time() - cached["ts"]) < _CLOUD_CACHE_TTL:
        jira_exec.update(cached["data"])
        return jira_exec, dedup_count
    try:
        from src.clients import feishu_client
        folder_token = load_config().get("feishu_bitable", {}).get("batch_folder_token", "")
        if folder_token:
            all_files = feishu_client.list_folder_files(folder_token, recursive=True)
            cloud_docs = [f for f in all_files
                         if f.get("folder", "") == date_str and f.get("type") == "docx"
                         and (f.get("name", "").startswith("批量执行")
                              or f.get("name", "").startswith("线上批量执行"))]
            cloud_data = {}
            for doc in cloud_docs:
                doc_token = doc.get("token", "")
                if not doc_token:
                    continue
                try:
                    md = feishu_client.fetch_docx_as_markdown(doc_token)
                    batch_rows = _parse_markdown_batch_table(md)
                    if batch_rows:
                        cloud_data.update(_process_batch(batch_rows))
                except Exception as e:
                    logger.warning("云端批次记录读取失败 %s: %s", doc.get("name", ""), e)
            if cloud_data:
                _cloud_batch_cache[date_str] = {"ts": _time.time(), "data": cloud_data}
                jira_exec.update(cloud_data)
                logger.info("云端批次记录: %s 读取到 %d 条成功记录", date_str, len(cloud_data))
    except Exception as e:
        logger.warning("读取云端批次记录失败: %s", e)

    return jira_exec, dedup_count


def _read_multi_day_batch_records(dates: list) -> tuple:
    """读取多天的批量执行记录，合并去重（同一 Jira 取执行时间最晚的）

    :return: (dict, int) - {jira_no: {...}}, total_dedup_count
    """
    merged = {}
    total_dedup = 0
    for d in dates:
        day_records, day_dedup = _read_today_batch_records(d)
        total_dedup += day_dedup
        for jira_no, info in day_records.items():
            exec_time = info.get("执行时间", "")
            if jira_no in merged:
                total_dedup += 1
                if exec_time > merged[jira_no].get("执行时间", ""):
                    merged[jira_no] = info
            else:
                merged[jira_no] = info
    return merged, total_dedup


def _daily_csv_path(date_str: str = None) -> str:
    """每日分析结论报表路径：docs/日期/YYYY-MM-DD_daily.csv"""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    return os.path.join(get_path("doc_dir"), date_str, f"{date_str}_daily.csv")


def _load_all_doc_jira_keys() -> set:
    """扫描 docs/ 下所有 CSV 文件，收集已测试的 jira 号集合"""
    tested = set()
    doc_dir = get_path("doc_dir")
    if not os.path.isdir(doc_dir):
        return tested
    for root, _dirs, files in os.walk(doc_dir):
        for fname in files:
            if not fname.lower().endswith(".csv"):
                continue
            fpath = os.path.join(root, fname)
            for r in _read_csv_rows(fpath):
                jira_no = (r.get("jira号") or "").strip()
                if jira_no:
                    tested.add(jira_no)
    return tested


def _spotcheck_csv_path(filename: str, date_str: str = None) -> str:
    """抽查报表路径：spotcheck/日期/filename"""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    return os.path.join(get_path("report_dir"), "..", "spotcheck", date_str, filename)


def _save_trigger_time_to_csv(bugid: str, trigger_time: str):
    """将提取到的触发时间记录到 data/日期/ 目录"""
    import csv as _csv
    date_str = datetime.now().strftime("%Y-%m-%d")
    tt_dir = os.path.join(PROJECT_ROOT, "data", date_str)
    os.makedirs(tt_dir, exist_ok=True)
    csv_path = os.path.join(tt_dir, f"trigger_times_{date_str}.csv")
    file_exists = os.path.exists(csv_path)
    try:
        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
            writer = _csv.writer(f)
            if not file_exists:
                writer.writerow(["jira号", "触发时间", "提取时间"])
            writer.writerow([bugid, trigger_time, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    except Exception as e:
        logger.warning("触发时间保存失败: %s", e)


def _load_trigger_times_from_local() -> dict:
    """从 data/ 目录加载所有已提取的触发时间，返回 {jira号: 触发时间}"""
    import csv as _csv
    data_dir = os.path.join(PROJECT_ROOT, "data")
    result = {}
    if not os.path.isdir(data_dir):
        return result
    for root, _dirs, files in os.walk(data_dir):
        for filename in files:
            if not filename.startswith("trigger_times_") or not filename.endswith(".csv"):
                continue
            csv_path = os.path.join(root, filename)
            try:
                with open(csv_path, "r", encoding="utf-8-sig") as f:
                    reader = _csv.DictReader(f)
                    for row in reader:
                        jira_no = (row.get("jira号") or "").strip()
                        tt = (row.get("触发时间") or "").strip()
                        if jira_no and tt:
                            result[jira_no] = tt
            except Exception as e:
                logger.warning("加载触发时间文件失败 %s: %s", filename, e)
    return result


def _delete_default_bitable_table(app_token: str, keep_table_id: str, keep_table_ids: set = None):
    """删除飞书创建 bitable 时自动生成的默认空数据表（保留我们自己创建的表）

    :param keep_table_ids: 额外的合法表 ID 集合，这些表也会被保留
    """
    import httpx as _httpx
    from src.clients.feishu_client import _bitable_headers, _FEISHU_API
    all_keep = {keep_table_id}
    if keep_table_ids:
        all_keep.update(keep_table_ids)
    try:
        headers = _bitable_headers()
        url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables"
        resp = _httpx.get(url, headers=headers, timeout=15, verify=False)
        tables = resp.json().get("data", {}).get("items", [])
        for t in tables:
            tid = t.get("table_id", "")
            if tid and tid not in all_keep:
                del_url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables/{tid}"
                _httpx.delete(del_url, headers=headers, timeout=15, verify=False)
                logger.info("已删除默认数据表: %s", tid)
    except Exception as e:
        logger.warning("删除默认数据表失败: %s", e)


# 触发时间云端 bitable 配置缓存，避免每次重新创建
# 触发时间云端表格缓存（支持多表）
_trigger_time_table_cache = {"app_token": "", "table_ids": [], "inited": False}

# 单条记录缓存：bugid -> (table_id, record_id, trigger_time)
_trigger_time_bugid_cache = {}

# 批量加载缓存（避免短时间内重复拉取相同数据）
_bitable_bulk_cache = {}  # key -> (timestamp, data)
_BITABLE_CACHE_TTL = 300  # 5分钟

def _invalidate_bitable_cache():
    """清除批量加载缓存，在数据写入时调用"""
    global _bitable_bulk_cache
    _bitable_bulk_cache = {}

# 单表记录上限
_TRIGGER_TIME_TABLE_LIMIT = 500


def _get_trigger_time_table_cfg() -> tuple:
    """获取触发时间云端多维表格配置，首次调用时自动创建并回填

    :return: (app_token, table_ids_list)
    """
    from src.clients import feishu_client
    cache = _trigger_time_table_cache
    if cache["inited"] and cache["app_token"] and cache["table_ids"]:
        return cache["app_token"], cache["table_ids"]
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("trigger_time_app_token", "")
    # 优先读 table_ids 列表，兼容旧版 table_id 单值
    table_ids = cfg.get("trigger_time_table_ids", [])
    if not table_ids:
        old_id = cfg.get("trigger_time_table_id", "")
        if old_id:
            table_ids = [old_id]
    folder = cfg.get("trigger_time_folder", "NgdFfKVhtlg3RPdPiqAcUStNnop")
    if app_token and table_ids:
        cache["app_token"], cache["table_ids"], cache["inited"] = app_token, list(table_ids), True
        return app_token, list(table_ids)
    # 首次运行：自动创建多维表格
    logger.info("触发时间云端表格未配置，自动创建中...")
    result = feishu_client.create_bitable("触发时间记录", folder)
    app_token = result["app_token"]
    fields = [
        {"field_name": "jira号", "type": 1},
        {"field_name": "触发时间", "type": 1},
        {"field_name": "提取时间", "type": 1},
    ]
    table_id = feishu_client.create_bitable_table(app_token, "触发时间", fields)
    _delete_default_bitable_table(app_token, table_id)
    # 写回 config.yaml
    import yaml
    from src.config import CONFIG_PATH
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    config.setdefault("feishu_bitable", {})["trigger_time_app_token"] = app_token
    config["feishu_bitable"]["trigger_time_table_ids"] = [table_id]
    config["feishu_bitable"].pop("trigger_time_table_id", None)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    import src.config as _cfg_module
    _cfg_module._CONFIG = None
    cache["app_token"], cache["table_ids"], cache["inited"] = app_token, [table_id], True
    logger.info("触发时间云端表格已创建并回填: app_token=%s, table_ids=%s", app_token, [table_id])
    _migrate_local_trigger_times_to_cloud(app_token, table_id)
    return app_token, [table_id]


def _migrate_local_trigger_times_to_cloud(app_token: str, table_id: str):
    """一次性迁移：将本地 CSV 中的触发时间批量写入云端 bitable"""
    from src.clients import feishu_client
    local_times = _load_trigger_times_from_local()
    if not local_times:
        return
    records = [{"fields": {
        "jira号": bugid, "触发时间": tt
    }} for bugid, tt in local_times.items()]
    try:
        feishu_client.batch_create_records(app_token, table_id, records)
        logger.info("本地触发时间已迁移到云端: %d 条", len(records))
    except Exception as e:
        logger.warning("本地触发时间迁移失败: %s", e)


def _load_cloud_trigger_cache() -> tuple:
    """一次加载云端触发时间缓存，返回 (times_dict, keys_set)

    合并加载有触发时间的记录和已标记空的记录，避免两次 API 调用。
    云端不可用时降级读本地 CSV。

    :return: ({jira号: 触发时间}, {已记录的jira号})
    """
    import time
    _ck = "cloud_trigger_cache"
    cached = _bitable_bulk_cache.get(_ck)
    if cached and time.time() - cached[0] < _BITABLE_CACHE_TTL:
        logger.info("云端触发时间缓存命中（TTL内）: %d 条有触发时间", len(cached[1][0]))
        return cached[1]
    from src.clients import feishu_client
    try:
        app_token, table_ids = _get_trigger_time_table_cfg()
        times = {}
        keys = set()
        for tid in table_ids:
            try:
                records = feishu_client.list_bitable_records(app_token, tid)
                for rec in records:
                    fields = rec.get("fields", {})
                    jira_no = _bitable_text(fields.get("jira号", ""))
                    if not jira_no:
                        continue
                    keys.add(jira_no)
                    tt = _bitable_text(fields.get("触发时间", ""))
                    if tt:
                        times[jira_no] = tt
                    # 同时填充 bugid 缓存，避免后续 _ensure_trigger_time_bugid_cache 重复加载
                    if not _trigger_time_bugid_cache or jira_no not in _trigger_time_bugid_cache:
                        _trigger_time_bugid_cache[jira_no] = (tid, rec.get("record_id", ""), tt)
            except Exception as e:
                logger.warning("加载触发时间表 %s 失败，已跳过: %s", tid, e)
        logger.info("云端触发时间缓存加载完成: %d 条有触发时间, %d 条已记录", len(times), len(keys))
        _bitable_bulk_cache[_ck] = (time.time(), (times, keys))
        return times, keys
    except Exception as e:
        logger.warning("云端触发时间缓存加载失败，降级读本地 CSV: %s", e)
        return _load_trigger_times_from_local(), set()


def _load_bitable_success_jiras() -> set:
    """从多维表格加载分析结果为“成功”的 jira 号集合，用于缓存过期判断"""
    import time
    _ck = "success_jiras"
    cached = _bitable_bulk_cache.get(_ck)
    if cached and time.time() - cached[0] < _BITABLE_CACHE_TTL:
        logger.info("多维表格成功记录缓存命中（TTL内）: %d 条", len(cached[1]))
        return cached[1]
    try:
        from src.clients import feishu_client
        cfg = load_config().get("feishu_bitable", {})
        app_token = cfg.get("app_token", "")
        table_id = cfg.get("table_id", "")
        bugid_field = cfg.get("bugid_field", "jira号")
        if not app_token or not table_id:
            return set()
        records = feishu_client.list_bitable_records(app_token, table_id)
        success_set = set()
        for rec in records:
            fields = rec.get("fields", {})
            result = _bitable_text(fields.get("分析结果", ""))
            if result == "成功":
                jk = _bitable_text(fields.get(bugid_field, ""))
                if jk:
                    success_set.add(jk)
        logger.info("多维表格成功记录加载完成: %d 条", len(success_set))
        _bitable_bulk_cache[_ck] = (time.time(), success_set)
        return success_set
    except Exception as e:
        logger.warning("加载多维表格成功记录失败: %s", e)
        return set()


def _load_trigger_times_from_cloud() -> dict:
    """从云端多维表格加载所有触发时间（支持多表），云端不可用时降级读本地 CSV

    :return: {jira号: 触发时间}
    """
    import time
    _ck = "trigger_times_cloud"
    cached = _bitable_bulk_cache.get(_ck)
    if cached and time.time() - cached[0] < _BITABLE_CACHE_TTL:
        logger.info("云端触发时间加载缓存命中（TTL内）: %d 条", len(cached[1]))
        return cached[1]
    from src.clients import feishu_client
    try:
        app_token, table_ids = _get_trigger_time_table_cfg()
        result = {}
        for tid in table_ids:
            try:
                records = feishu_client.list_bitable_records(app_token, tid)
                for rec in records:
                    fields = rec.get("fields", {})
                    jira_no = _bitable_text(fields.get("jira号", ""))
                    tt = _bitable_text(fields.get("触发时间", ""))
                    if jira_no and tt:
                        result[jira_no] = tt
            except Exception as e:
                logger.warning("加载触发时间表 %s 失败，已跳过: %s", tid, e)
        logger.info("云端触发时间加载完成: %d 条", len(result))
        _bitable_bulk_cache[_ck] = (time.time(), result)
        return result
    except Exception as e:
        logger.warning("云端触发时间加载失败，降级读本地 CSV: %s", e)
        return _load_trigger_times_from_local()


def _load_cloud_trigger_keys() -> set:
    """加载云端所有已记录的 jira 号（含空触发时间标记），用于跳过已处理记录

    :return: {jira号}
    """
    from src.clients import feishu_client
    try:
        app_token, table_ids = _get_trigger_time_table_cfg()
        keys = set()
        for tid in table_ids:
            try:
                records = feishu_client.list_bitable_records(app_token, tid)
                for rec in records:
                    jira_no = _bitable_text((rec.get("fields") or {}).get("jira号", ""))
                    if jira_no:
                        keys.add(jira_no)
            except Exception as e:
                logger.warning("加载触发时间表keys %s 失败，已跳过: %s", tid, e)
        logger.info("云端触发时间keys加载完成: %d 个", len(keys))
        return keys
    except Exception as e:
        logger.warning("云端触发时间keys加载失败: %s", e)
        return set()


def _load_all_cloud_trigger_records() -> list:
    """加载云端全量触发时间记录（含空触发时间），用于重新提取扫描

    :return: [{jira_no, trigger_time, table_id, record_id}]
    """
    from src.clients import feishu_client
    app_token, table_ids = _get_trigger_time_table_cfg()
    all_records = []
    valid_tables = 0
    for tid in table_ids:
        try:
            records = feishu_client.list_bitable_records(app_token, tid)
            valid_tables += 1
            for rec in records:
                fields = rec.get("fields", {})
                jira_no = _bitable_text(fields.get("jira号", ""))
                tt = _bitable_text(fields.get("触发时间", ""))
                if jira_no:
                    all_records.append({
                        "jira_no": jira_no,
                        "trigger_time": tt,
                        "table_id": tid,
                        "record_id": rec["record_id"],
                    })
        except Exception as e:
            logger.warning("加载触发时间表 %s 失败，已跳过: %s", tid, e)
    logger.info("云端全量触发时间加载完成: %d 条（%d/%d 个表成功）", len(all_records), valid_tables, len(table_ids))
    return all_records


def _ensure_trigger_time_bugid_cache():
    """懒加载触发时间缓存：首次访问时从云端加载所有表的 jira号 索引"""
    if _trigger_time_bugid_cache:
        return  # 缓存已填充
    from src.clients import feishu_client
    app_token, table_ids = _get_trigger_time_table_cfg()
    for tid in table_ids:
        try:
            records = feishu_client.list_bitable_records(app_token, tid)
            for rec in records:
                fields = rec.get("fields", {})
                jira_no = _bitable_text(fields.get("jira号", ""))
                trigger_time = _bitable_text(fields.get("触发时间", ""))
                if jira_no:
                    _trigger_time_bugid_cache[jira_no] = (tid, rec["record_id"], trigger_time)
        except Exception as e:
            logger.warning("初始化触发时间缓存失败(表 %s): %s", tid, e)
    logger.info("触发时间缓存已加载: %d 条记录", len(_trigger_time_bugid_cache))


def _save_trigger_time_to_cloud(bugid: str, trigger_time: str):
    """将单条触发时间写入云端 bitable（有则更新，无则新建），云端成功后再写本地 CSV"""
    # 懒加载缓存
    _ensure_trigger_time_bugid_cache()
    # 单条更新：优先用缓存直接定位，避免全表扫描
    cached = _trigger_time_bugid_cache.get(bugid)
    cloud_ok = False
    if cached and isinstance(cached, tuple) and len(cached) >= 3:
        tid, rec_id, _ = cached
        try:
            app_token, _ = _get_trigger_time_table_cfg()
            from src.clients import feishu_client
            feishu_client.update_bitable_records(app_token, tid, [
                {"record_id": rec_id, "fields": {"触发时间": trigger_time}}
            ])
            # 更新缓存时间戳
            _trigger_time_bugid_cache[bugid] = (tid, rec_id, trigger_time)
            logger.info("云端触发时间单条更新(缓存命中): %s -> %s", bugid, trigger_time)
            cloud_ok = True
        except Exception as e:
            logger.warning("缓存更新失败 %s，回退批量模式: %s", bugid, e)
            _trigger_time_bugid_cache.pop(bugid, None)
    if not cloud_ok:
        # 缓存未命中或更新失败：走批量模式
        cloud_ok = _batch_save_trigger_times_to_cloud({bugid: trigger_time})
    # 云端成功后才写本地 CSV，避免云端失败时本地多余
    if cloud_ok:
        _save_trigger_time_to_csv(bugid, trigger_time)
    else:
        logger.warning("云端写入失败，跳过本地 CSV 保存: %s", bugid)


def _batch_save_trigger_times_to_cloud(items: dict) -> bool:
    """批量将触发时间写入云端 bitable，只加载一次表数据。items: {bugid: trigger_time}

    :return: 云端写入是否成功
    """
    from src.clients import feishu_client
    if not items:
        return True
    try:
        app_token, table_ids = _get_trigger_time_table_cfg()
        # 一次性加载所有表数据
        all_records = {}  # {table_id: [records]}
        table_counts = {}
        valid_tids = []
        jira_index = {}  # {bugid: (table_id, record)} 用于快速查找已有记录
        for tid in table_ids:
            try:
                records = feishu_client.list_bitable_records(app_token, tid)
                all_records[tid] = records
                table_counts[tid] = len(records)
                valid_tids.append(tid)
                for rec in records:
                    fields = rec.get("fields", {})
                    jira_no = _bitable_text(fields.get("jira号", ""))
                    if jira_no:
                        jira_index[jira_no] = (tid, rec)
            except Exception as e:
                if "TableIdNotFound" in str(e) or "1254041" in str(e):
                    logger.warning("触发时间子表已不存在，已跳过: %s", tid)
                else:
                    logger.warning("加载触发时间表 %s 失败，已跳过: %s", tid, e)
        # 清理无效 table_id
        invalid_tids = [tid for tid in table_ids if tid not in valid_tids]
        if invalid_tids and valid_tids:
            _trigger_time_table_cache["table_ids"] = valid_tids
            _update_config_table_ids(app_token, valid_tids)
        table_ids = valid_tids
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 按表分组：更新 vs 新建
        updates_by_table = {}  # {tid: [{"record_id":..., "fields":...}]}
        new_items = []  # [(bugid, trigger_time)] 需要新建的
        for bugid, trigger_time in items.items():
            if bugid in jira_index:
                tid, rec = jira_index[bugid]
                updates_by_table.setdefault(tid, []).append({
                    "record_id": rec["record_id"],
                    "fields": {"触发时间": trigger_time}
                })
            else:
                new_items.append((bugid, trigger_time))
        # 批量更新
        for tid, recs in updates_by_table.items():
            feishu_client.update_bitable_records(app_token, tid, recs)
            logger.info("云端触发时间批量更新: %d 条 (表 %s)", len(recs), tid)
            # 更新本地缓存（从已加载的 jira_index 反向查找）
            for item in recs:
                rec_id = item.get("record_id")
                if rec_id:
                    for b, (t, r) in jira_index.items():
                        if r.get("record_id") == rec_id:
                            tt = item["fields"].get("触发时间", "")
                            _trigger_time_bugid_cache[b] = (t, rec_id, tt)
                            break
        # 批量新建：选未满的表或创建新表
        if new_items:
            target_tid = None
            for tid in table_ids:
                if table_counts.get(tid, 0) < _TRIGGER_TIME_TABLE_LIMIT:
                    target_tid = tid
                    break
            if not target_tid:
                target_tid = _create_trigger_time_subtable(app_token, len(table_ids) + 1, set(table_ids))
                table_ids.append(target_tid)
                _trigger_time_table_cache["table_ids"] = list(table_ids)
                _update_config_table_ids(app_token, table_ids)
            create_records = [{"fields": {"jira号": bid, "触发时间": tt, "提取时间": now_str}} for bid, tt in new_items]
            feishu_client.batch_create_records(app_token, target_tid, create_records)
            logger.info("云端触发时间批量新建: %d 条 (表 %s)", len(create_records), target_tid)
            # 更新本地缓存（新建的 record_id 需要从 API 返回获取，这里先标记为未知）
            for bid, tt in new_items:
                _trigger_time_bugid_cache.pop(bid, None)  # 清除旧缓存，下次会从云端加载
    except Exception as e:
        logger.warning("云端触发时间批量写入失败: %s", e)
        # 云端写入失败时保留本地缓存，避免下次重复提取（本地与云端短暂不一致可接受）
        return False
    return True


def _remove_local_trigger_entries(jira_keys: set):
    """从本地 CSV 中删除指定的 jira 号条目，保持与云端一致"""
    import csv as _csv
    if not jira_keys:
        return
    data_dir = os.path.join(PROJECT_ROOT, "data")
    removed = 0
    for root, _dirs, files in os.walk(data_dir):
        for filename in files:
            if not filename.startswith("trigger_times_") or not filename.endswith(".csv"):
                continue
            path = os.path.join(root, filename)
            try:
                rows = []
                with open(path, "r", encoding="utf-8-sig") as f:
                    for row in _csv.DictReader(f):
                        rows.append(row)
                keep = [r for r in rows if (r.get("jira号") or "").strip() not in jira_keys]
                if len(keep) < len(rows):
                    removed += len(rows) - len(keep)
                    with open(path, "w", encoding="utf-8-sig", newline="") as f:
                        writer = _csv.DictWriter(f, fieldnames=["jira号", "触发时间", "提取时间"])
                        writer.writeheader()
                        writer.writerows(keep)
            except Exception:
                pass
    if removed:
        logger.info("已从本地 CSV 清理 %d 条未同步到云端的记录", removed)


def _refresh_trigger_time_bugid_cache(app_token: str, table_ids: list):
    """刷新 bugid 缓存，从所有表中重建索引"""
    from src.clients import feishu_client
    _trigger_time_bugid_cache.clear()
    for tid in table_ids:
        try:
            records = feishu_client.list_bitable_records(app_token, tid)
            for rec in records:
                fields = rec.get("fields", {})
                jira_no = _bitable_text(fields.get("jira号", ""))
                trigger_time = _bitable_text(fields.get("触发时间", ""))
                if jira_no:
                    _trigger_time_bugid_cache[jira_no] = (tid, rec["record_id"], trigger_time)
        except Exception as e:
            logger.warning("刷新 bugid 缓存失败(表 %s): %s", tid, e)


def _create_trigger_time_subtable(app_token: str, index: int, existing_table_ids: set = None) -> str:
    """创建触发时间子表（触发时间_N），返回 table_id

    遇到重名则跳过，继续创建下一个编号，直到成功。
    """
    from src.clients import feishu_client
    fields = [
        {"field_name": "jira号", "type": 1},
        {"field_name": "触发时间", "type": 1},
        {"field_name": "提取时间", "type": 1},
    ]
    for i in range(10):  # 最多尝试10次避免死循环
        name = f"触发时间_{index + i}"
        try:
            table_id = feishu_client.create_bitable_table(app_token, name, fields)
            _delete_default_bitable_table(app_token, table_id, keep_table_ids=existing_table_ids)
            logger.info("触发时间子表已创建: %s -> %s", name, table_id)
            return table_id
        except ValueError as e:
            if "TableNameDuplicated" in str(e):
                logger.info("子表 %s 已存在，跳过尝试下一个...", name)
                continue
            raise
    raise RuntimeError(f"连续创建 10 个子表均重名，请检查云端多维表格")


def _update_config_table_ids(app_token: str, table_ids: list):
    """更新 config.yaml 中的 table_ids 列表"""
    import yaml
    from src.config import CONFIG_PATH
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        config.setdefault("feishu_bitable", {})["trigger_time_table_ids"] = list(table_ids)
        config["feishu_bitable"].pop("trigger_time_table_id", None)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        import src.config as _cfg_module
        _cfg_module._CONFIG = None
    except Exception as e:
        logger.warning("更新 config table_ids 失败: %s", e)


@app.get("/favicon.ico")
def favicon():
    """返回空图标避免 404 报错"""
    from fastapi.responses import Response
    return Response(status_code=204)


@app.get("/")
def index():
    """前端单页应用入口（禁用缓存确保页面始终最新）"""
    return FileResponse(
        os.path.join(WEB_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/api/config")
def get_config():
    """读取当前全局配置"""
    return _ok(load_config())


@app.post("/api/config")
async def save_config(request: Request):
    """更新配置：按配置段合并前端提交项并写回 config.yaml"""
    try:
        updates = await request.json() or {}
        cfg = load_config()
        for section, values in updates.items():
            if isinstance(values, dict) and isinstance(cfg.get(section), dict):
                cfg[section].update(values)
        with open(cfg_module.CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        # 重新加载配置缓存，使新配置立即生效
        load_config(cfg_module.CONFIG_PATH)
        logger.info("配置已由页面更新: %s", list(updates.keys()))
        return _ok(message="配置保存成功")
    except Exception as e:
        logger.error("配置保存失败: %s", e)
        return _fail(str(e))


@app.post("/api/analyze")
async def run_analyze(request: Request):
    """执行内容补充流程，接收表格行数据，返回补充后的完整数据"""
    body = await request.json() or {}
    rows = body.get("rows", [])
    # 兼容旧格式：支持仅传 bugids 列表
    if not rows and body.get("bugids"):
        bugids = [b.strip() for b in str(body.get("bugids", "")).replace("，", ",").split(",") if b.strip()]
        trigger_times = body.get("trigger_times") or {}
        rows = [{"jira号": b, "分析问题时间": trigger_times.get(b, ""),
                 "AI分析结果(飞书链接)": "", "AI评论总结": "", "rootcause": "", "结果置信度": ""} for b in bugids]
    if not rows:
        return _fail("表格数据不能为空")
    try:
        result = pipeline.run_pipeline(rows)
        return _ok({"rows": result["rows"], "stats": result["stats"]},
                   f"补充完成：总 {result['stats']['total']} 条，已完整 {result['stats']['complete']} 条")
    except Exception as e:
        logger.error("analyze 执行失败: %s", e)
        return _fail(str(e))


@app.post("/api/flow/extract_time")
async def flow_extract_time(request: Request):
    """提取单个 Jira 号的触发时间：优先本地缓存，否则从 Jira 提取"""
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("bugid 不能为空")
    # 优先查本地缓存
    local_times = _load_trigger_times_from_cloud()
    if bugid in local_times:
        return _ok({"trigger_time": local_times[bugid], "source": "local"}, f"本地缓存命中: {local_times[bugid]}")
    # 从 Jira 提取
    try:
        from src.clients import jira_client as _jc
        loop = asyncio.get_event_loop()
        issue = await loop.run_in_executor(None, _jc.fetch_issue, bugid)
        tt = await loop.run_in_executor(None, _jc.extract_trigger_time_from_issue, issue)
        if tt:
            _save_trigger_time_to_cloud(bugid, tt)
            return _ok({"trigger_time": tt, "source": "jira"}, f"提取成功: {tt}")
        return _fail(f"{bugid} 未提取到触发时间（评论中未找到有效时间戳）")
    except Exception as e:
        logger.warning("单Jira时间提取失败 %s: %s", bugid, e)
        return _fail(f"提取失败: {e}")


@app.post("/api/flow/single")
async def flow_single(request: Request):
    """单 bugid 流程执行：SSE 实时推送每步结果"""
    import asyncio
    import queue
    import json as _json
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    trigger_time = str(body.get("trigger_time") or "").strip()
    if not bugid:
        return _fail("bugid 不能为空")
    # 初始化取消标志
    _flow_cancel[bugid] = False

    async def event_generator():
        # 线程安全队列：后端线程推送步骤结果，异步生成器读取并发送 SSE
        step_queue = queue.Queue()
        yield f"data: {_json.dumps({'step': 0, 'name': 'start', 'ok': True, 'summary': bugid}, ensure_ascii=False)}\n\n"
        loop = asyncio.get_event_loop()
        cancel_check = lambda: _flow_cancel.get(bugid, False)

        def _run_flow():
            try:
                def on_step(step_result):
                    """每步完成后立即推入队列，实现实时推送"""
                    step_queue.put(step_result)
                result = pipeline.execute_single_flow(
                    bugid, trigger_time, cancel_check=cancel_check, step_callback=on_step)
                step_queue.put({"_done": True, "all_ok": result["all_ok"],
                                "cancelled": result.get("cancelled", False), "row": result["row"]})
            except Exception as e:
                logger.error("flow/single 执行失败: %s", e)
                step_queue.put({"_done": True, "all_ok": False, "error": str(e)})

        # 在线程池中启动流程
        loop.run_in_executor(None, _run_flow)
        # 异步轮询队列，实时推送步骤事件
        try:
            while True:
                if await request.is_disconnected():
                    logger.info("flow/single: 客户端已断开 bugid=%s", bugid)
                    break
                try:
                    item = step_queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.3)
                    continue
                if item.get("_done"):
                    yield f"data: {_json.dumps({'done': True, 'all_ok': item['all_ok'], 'cancelled': item.get('cancelled', False), 'row': item.get('row')}, ensure_ascii=False)}\n\n"
                    break
                yield f"data: {_json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            _flow_cancel.pop(bugid, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/flow/stop/{bugid}")
async def flow_stop(bugid: str):
    """通知后端停止执行指定 bugid 的流程"""
    if bugid in _flow_cancel:
        _flow_cancel[bugid] = True
        return _ok({"bugid": bugid}, "已发送停止信号")
    return _fail("未找到正在执行的流程")


@app.get("/api/flow/check/{bugid}")
async def flow_check(bugid: str):
    """快速检查 bugid 的 6 字段状态（不执行补充）"""
    csv_path = _daily_csv_path()
    rows = _read_csv_rows(csv_path)
    target = None
    for r in rows:
        if (r.get("jira号") or "").strip() == bugid.strip():
            target = r
            break
    if not target:
        fields = {f: {"value": "", "missing": True} for f in pipeline.SUPPLEMENT_FIELDS}
        return _ok({"found": False, "fields": fields, "missing_count": len(pipeline.SUPPLEMENT_FIELDS)},
                   f"今日报表中未找到 {bugid}")
    fields = {}
    missing_count = 0
    for f in pipeline.SUPPLEMENT_FIELDS:
        val = (target.get(f) or "").strip()
        is_missing = val in ("", "-", "None")
        fields[f] = {"value": val, "missing": is_missing}
        if is_missing:
            missing_count += 1
    return _ok({"found": True, "fields": fields, "missing_count": missing_count},
               f"{bugid}: {len(pipeline.SUPPLEMENT_FIELDS) - missing_count}/{len(pipeline.SUPPLEMENT_FIELDS)} 字段已有值")


@app.post("/api/retry")
async def run_retry(request: Request):
    """失败 bug 重新补充"""
    body = await request.json() or {}
    bugid = body.get("bugid", "").strip()
    if not bugid:
        return _fail("bugid 不能为空")
    try:
        result = pipeline.retry_bug(bugid)
        return _ok({"rows": result["rows"]}, f"bugid={bugid} 重新补充完成")
    except Exception as e:
        logger.error("retry 执行失败: %s", e)
        return _fail(str(e))


@app.post("/api/store")
async def run_store(request: Request):
    """手工将分析文档推入知识库"""
    body = await request.json() or {}
    bugid = body.get("bugid", "").strip()
    if not bugid:
        return _fail("bugid 不能为空")
    try:
        pipeline.store_bug(bugid)
        return _ok(message=f"bugid={bugid} 分析文档已推入知识库")
    except Exception as e:
        logger.error("store 执行失败: %s", e)
        return _fail(str(e))


@app.post("/api/audit")
async def run_audit(request: Request):
    """随机抽查复核，返回人工审核表格数据（含达标/不达标判定）"""
    body = await request.json() or {}
    count = body.get("count")
    try:
        audit_module.sample_and_audit(int(count) if count else None)
        cfg = load_config()["audit"]
        rows = _read_csv_rows(_spotcheck_csv_path(cfg["report_file"]))
        # 统计达标/不达标数量
        passed = sum(1 for r in rows if r.get("判定结果") == "达标")
        failed = len(rows) - passed
        msg = f"抽查完成：共 {len(rows)} 条，达标 {passed} 条，不达标 {failed} 条"
        return _ok({"rows": rows, "passed": passed, "failed": failed}, msg)
    except Exception as e:
        logger.error("audit 执行失败: %s", e)
        return _fail(str(e))


@app.get("/api/report/audit_failed")
def report_audit_failed():
    """读取当日不达标抽查报表"""
    today = datetime.now().strftime("%Y-%m-%d")
    path = _spotcheck_csv_path(f"audit_failed_{today}.csv", today)
    if not os.path.exists(path):
        return _ok([], "今日无不达标数据")
    rows = _read_csv_rows(path)
    return _ok(rows, f"不达标数据 {len(rows)} 条")


def _today_rows() -> list:
    """读取当日结论报表数据"""
    return _read_csv_rows(_daily_csv_path())


@app.post("/api/report/classify_docs")
async def classify_comment_docs_api(request: Request):
    """根据执行记录对当天评论分析文档进行分类（未分类的移动到 True/False 子文件夹）"""
    from src.core import report as report_module
    body = await request.json() or {}
    date_str = (body.get("date") or "").strip() or None
    try:
        result = report_module.classify_comment_docs(date_str)
        return _ok(result, f"分类完成: 达标{result['moved_true']}个, 不达标{result['moved_false']}个, 跳过{result['skipped']}个")
    except Exception as e:
        logger.error("文档分类失败: %s", e, exc_info=True)
        return _fail(f"文档分类失败: {e}")


@app.get("/api/report/daily")
def report_daily(date: str = None):
    """按日期查询结论报表（读取本地 CSV）"""
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    return _ok(_read_csv_rows(_daily_csv_path(date_str)))


@app.get("/api/report/daily_refresh")
def report_daily_refresh(date: str = None):
    """刷新今日结论报表：从今日所有批次执行记录中收集 Jira 号，
    然后查多维表格找每个 Jira 最接近执行时间的分析完成记录，拼接成报表。
    """
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    # 步骤1：读取执行成功的记录（自动扩展到后续非工作日）
    report_dates = _get_report_date_range(date_str)
    jira_exec, dedup_count = _read_multi_day_batch_records(report_dates)
    # 补充备注字段
    if not jira_exec:
        return _ok([])
    # 步骤2：查询多维表格，收集所有匹配记录
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
    jira_set = set(jira_exec.keys())
    # jira号 -> [多维表格记录列表]（全字段）
    bt_map = {}
    if app_token and table_id:
        try:
            records = feishu_client.list_bitable_records(app_token, table_id)
            for rec in records:
                fields = rec.get("fields", {})
                jira_key = _bitable_text(fields.get(bugid_field, ""))
                if jira_key and jira_key in jira_set:
                    bt_map.setdefault(jira_key, []).append(
                        _flatten_bitable_record_all(fields, report_field))
        except Exception as e:
            logger.warning("今日报表刷新：多维表格查询失败: %s", e)
    # 步骤3：每个 Jira 找分析完成时间最接近执行时间的记录，始终包含批量执行列
    BATCH_COLS = ["jira号", "执行结果", "触发时间", "执行时间", "备注"]
    rows = []
    for jira_no, exec_info in jira_exec.items():
        bt_records = bt_map.get(jira_no, [])
        row = {"jira号": jira_no}
        # 始终填充批量执行表格列（保证列名一致）
        row.update(exec_info)
        if bt_records:
            # 仅保留分析完成时间 >= 执行时间的记录，取最接近的
            exec_time = exec_info.get("执行时间", "")
            candidates = [r for r in bt_records
                         if r.get("分析完成时间", "") and r["分析完成时间"] >= exec_time]
            if not candidates:
                candidates = bt_records  # 兆底：用全部记录
            # 按分析完成时间升序，取最接近执行时间的（第一条）
            candidates.sort(key=lambda x: x.get("分析完成时间", ""))
            bf = candidates[0]
            row.update(bf)
        else:
            # 执行成功但多维表格无记录 → 标记为"分析中"
            row["分析结果"] = "分析中"
        rows.append(row)
    # 按业务优先级排序：失败 → 待分析 → 耗时过长(成功但慢) → 成功且耗时达标
    too_long_threshold = 900
    failed_rows, pending_rows, too_long_success_rows, normal_success_rows = [], [], [], []
    for r in rows:
        analysis_result = r.get("分析结果", "") or ""
        analysis_sec = _parse_dur_sec(r.get("分析耗时", ""))
        is_too_long = analysis_sec > too_long_threshold if analysis_sec > 0 else False
        if analysis_result == "失败":
            cat = _classify_failure(r.get("jira号", ""), r)
            failed_rows.append({**r, "_both": is_too_long, "失败分类": cat})
        elif not analysis_result or analysis_result == "分析中":
            pending_rows.append(r)
        elif is_too_long:
            too_long_success_rows.append(r)
        else:
            normal_success_rows.append(r)
    # 失败排序：同时耗时过长的优先，然后按失败分类归类，待审核最后
    def _fail_sort_key(r):
        both = r.get("_both", False)
        cat = r.get("失败分类", "")
        is_pending = cat == "待开发排查"
        return (0 if both else 1, 1 if is_pending else 0, cat, r.get("jira号", ""))
    failed_rows.sort(key=_fail_sort_key)
    # 待分析排序：按 jira号
    pending_rows.sort(key=lambda r: r.get("jira号", ""))
    # 耗时过长的成功记录按分析耗时降序（最慢的在前）
    too_long_success_rows.sort(key=lambda r: -_parse_dur_sec(r.get("分析耗时", "")))
    rows = failed_rows + pending_rows + too_long_success_rows + normal_success_rows
    # 确保所有行拥有相同的列（前端表格依赖第一行的 keys 渲染列）
    all_keys = list(BATCH_COLS)
    for r in rows:
        for k in r:
            if k not in all_keys and not k.startswith("_"):
                all_keys.append(k)
    # 将“失败分类”列插入到“分析结果”后面，便于归类展示
    if "失败分类" in all_keys and "分析结果" in all_keys:
        all_keys.remove("失败分类")
        idx = all_keys.index("分析结果") + 1
        all_keys.insert(idx, "失败分类")
    for r in rows:
        for k in all_keys:
            r.setdefault(k, "")
    # 清理内部排序标记字段（不展示给前端）
    for r in rows:
        for k in list(r.keys()):
            if k.startswith("_"):
                del r[k]
    logger.info("今日结论报表刷新: %s, %d 个 Jira, 多维表格命中 %d, %d 列",
               date_str, len(jira_exec),
               len(jira_exec) - sum(1 for j in jira_exec if j not in bt_map),
               len(all_keys))
    # 同步生成并覆盖云端结论文档（前端触发与飞书机器人触发共享同一覆盖逻辑）
    try:
        report = _generate_daily_report(date_str)
        if report.get("total", 0) > 0:
            cloud_url = _upload_daily_report_to_cloud(report, date_str)
            if cloud_url:
                logger.info("前端刷新触发云端文档覆盖: %s", cloud_url)
            # 同步到数据沉淀统计表
            _sync_daily_stats_to_bitable(report, date_str)
    except Exception as e:
        logger.warning("前端刷新时云端文档覆盖失败: %s", e)
    return _ok(rows)


@app.get("/api/report/daily_summary")
def report_daily_summary(date: str = None):
    """根据今日结论报表生成汇总统计：执行总数、成功率、平均耗时、失败分类"""
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    # 步骤1：读取执行成功的记录（自动扩展到后续非工作日）
    report_dates = _get_report_date_range(date_str)
    jira_exec_all, dedup_count = _read_multi_day_batch_records(report_dates)
    # 转换为 {jira_no: exec_time} 格式供本函数使用
    jira_exec = {jno: info.get("执行时间", "") for jno, info in jira_exec_all.items()}
    if not jira_exec:
        return _ok({"total": 0, "regression": 0, "success": 0, "fail": 0, "success_rate": "0%",
                     "avg_total_duration": "-", "avg_analysis_duration": "-",
                     "too_long": 0, "failures": {}, "pending": 0, "report_dates": report_dates, "dedup": 0})
    # 步骤2：查多维表格
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
    jira_set = set(jira_exec.keys())
    bt_map = {}
    if app_token and table_id:
        try:
            records = feishu_client.list_bitable_records(app_token, table_id)
            for rec in records:
                fields = rec.get("fields", {})
                jira_key = _bitable_text(fields.get(bugid_field, ""))
                if jira_key and jira_key in jira_set:
                    bt_map.setdefault(jira_key, []).append(
                        _flatten_bitable_record_all(fields, report_field))
        except Exception as e:
            logger.warning("今日汇总：多维表格查询失败: %s", e)
    # 步骤3：匹配记录并计算统计（仅计入有多维表格记录的）
    success_count = 0
    fail_count = 0
    pending_count = 0
    durations = []  # 总耗时秒数
    analysis_durations = []  # 分析耗时秒数
    too_long_count = 0
    fail_cats = {}  # {分类: 数量}
    fail_jiras = {}  # {分类: [{jira号, 错误信息}]}
    pc_count = 0
    online_count = 0
    too_long_threshold = 900  # 15分钟
    for jira_no, exec_time in jira_exec.items():
        # 从 CSV 数据统计触发来源（确保无多维表格记录的也纳入）
        csv_source = jira_exec_all.get(jira_no, {}).get("触发来源", "")
        if csv_source == "jira_analyze":
            pc_count += 1
        elif csv_source == "parseFullTicket":
            online_count += 1
        bt_records = bt_map.get(jira_no, [])
        if not bt_records:
            # 无多维表格记录 → 计入统计，标记为"分析中"
            pending_count += 1
            continue
        # 找最接近执行时间的记录
        candidates = [r for r in bt_records
                     if r.get("分析完成时间", "") and r["分析完成时间"] >= exec_time]
        if not candidates:
            candidates = bt_records
        candidates.sort(key=lambda x: x.get("分析完成时间", ""))
        bf = candidates[0]
        result = bf.get("分析结果", "")
        if result == "成功":
            success_count += 1
        else:
            fail_count += 1
            # 失败分类：统一使用 _classify_failure
            cat = _classify_failure(jira_no, bf)
            fail_cats[cat] = fail_cats.get(cat, 0) + 1
            if cat not in fail_jiras:
                fail_jiras[cat] = []
            err_short = (bf.get("错误信息", "") or "")[:80]
            fail_jiras[cat].append({"jira号": jira_no, "错误信息": err_short})
        # 解析总耗时
        dur = _parse_dur_sec(bf.get("总耗时", ""))
        if dur > 0:
            durations.append(dur)
        # 解析分析耗时
        analysis_dur = _parse_dur_sec(bf.get("分析耗时", ""))
        if analysis_dur > 0:
            analysis_durations.append(analysis_dur)
            if analysis_dur > too_long_threshold:
                too_long_count += 1
    # 汇总（pending_count 为执行成功但尚未出分析结果的记录）
    total = success_count + fail_count + pending_count
    regression_count = total
    success_rate = f"{success_count / total * 100:.1f}%" if total else "0%"
    if durations:
        avg_total_duration = _format_dur(sum(durations) / total)
    else:
        avg_total_duration = "-"
    if analysis_durations:
        avg_analysis_duration = _format_dur(sum(analysis_durations) / total)
    else:
        avg_analysis_duration = "-"
    summary = {
        "total": total,
        "regression": regression_count,
        "success": success_count,
        "fail": fail_count,
        "pending": pending_count,
        "success_rate": success_rate,
        "avg_total_duration": avg_total_duration,
        "avg_analysis_duration": avg_analysis_duration,
        "too_long": too_long_count,
        "too_long_threshold": too_long_threshold,
        "failures": fail_cats,
        "failure_jiras": fail_jiras,
        "pc_count": pc_count,
        "online_count": online_count,
        "report_dates": report_dates,
        "dedup": dedup_count,
    }
    logger.info("今日汇总: %s, 总 %d, 回归 %d, 成功 %d, 失败 %d, 分析中 %d, 去重 %d",
               date_str, total, regression_count, success_count, fail_count, pending_count, dedup_count)
    return _ok(summary)


@app.get("/api/report/weekly_summary")
def report_weekly_summary(date: str = None):
    """每周汇总：聚合本周所有工作日的每日播报数据"""
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    try:
        report = _generate_weekly_report(date_str)
        return _ok(report)
    except Exception as e:
        logger.error("每周汇总生成失败: %s", e, exc_info=True)
        return _fail(f"每周汇总生成失败: {e}")


@app.get("/api/report/range_summary")
def report_range_summary(start_date: str, end_date: str):
    """时间段汇总：聚合自定义日期范围内所有工作日的每日播报数据"""
    try:
        report = _generate_range_report(start_date, end_date)
        return _ok(report)
    except Exception as e:
        logger.error("时间段汇总生成失败: %s", e, exc_info=True)
        return _fail(f"时间段汇总生成失败: {e}")


@app.get("/api/report/audit")
def report_audit():
    """查询抽查审核表格"""
    cfg = load_config()["audit"]
    return _ok(_read_csv_rows(_spotcheck_csv_path(cfg["report_file"])))


@app.get("/api/report/audited")
def report_audited():
    """查询已抽查记录"""
    cfg = load_config()["audit"]
    return _ok(_read_csv_rows(os.path.join(get_path("report_dir"), cfg["audited_file"])))


@app.get("/api/report/batch")
def report_batch(date: str = None):
    """按日期查询批量执行记录（docs/日期/batch_*.csv）"""
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    doc_dir = get_path("doc_dir")
    day_dir = os.path.join(doc_dir, date_str)
    if not os.path.isdir(day_dir):
        return _ok([])
    all_rows = []
    for fname in sorted(os.listdir(day_dir), reverse=True):
        if not fname.lower().startswith("batch_") or not fname.lower().endswith(".csv"):
            continue
        rows = _read_csv_rows(os.path.join(day_dir, fname))
        for r in rows:
            r["来源文件"] = fname
        all_rows.extend(rows)
    return _ok(all_rows)


@app.get("/api/report/verify")
def report_verify(date: str = None):
    """按日期查询结果验证记录（docs/日期/*_compare_log.csv 和 data/日期/*_compare_log.csv）"""
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    # compare_log 可能存在于 docs/日期/ 和 data/日期/ 两个位置
    scan_dirs = [
        os.path.join(get_path("doc_dir"), date_str),
        os.path.join(PROJECT_ROOT, "data", date_str),
    ]
    all_rows = []
    seen_files = set()
    for day_dir in scan_dirs:
        if not os.path.isdir(day_dir):
            continue
        for fname in sorted(os.listdir(day_dir), reverse=True):
            if "_compare_log" not in fname.lower() or not fname.lower().endswith(".csv"):
                continue
            if fname in seen_files:
                continue
            seen_files.add(fname)
            rows = _read_csv_rows(os.path.join(day_dir, fname))
            for r in rows:
                r["来源文件"] = fname
            all_rows.extend(rows)
    return _ok(all_rows)


def _bitable_text(val) -> str:
    """多维表格字段值归一化为纯文本（兼容 list/dict/url/普通类型）"""
    if val is None:
        return ""
    if isinstance(val, list):
        return "".join(_bitable_text(item) for item in val)
    if isinstance(val, dict):
        return str(val.get("text", "") or val.get("name", "") or "").strip()
    return str(val).strip()


def _flatten_bitable_record(fields: dict, report_field: str) -> dict:
    """提取多维表格单条记录的关键展示字段，飞书报告链接取真实 URL"""
    def pick(*names):
        for n in names:
            if n in fields:
                return fields[n]
        return ""
    # 飞书报告链接：URL 字段取 link，文本字段直接取值
    report_val = fields.get(report_field, "")
    report_link = ""
    if isinstance(report_val, dict):
        report_link = str(report_val.get("link", "") or "").strip()
    elif isinstance(report_val, str):
        report_link = report_val.strip()
    return {
        "分析结果": _bitable_text(pick("分析结果")),
        "错误信息": _bitable_text(pick("错误信息")),
        "分析问题时间": _bitable_text(pick("分析问题时间")),
        "分析完成时间": _bitable_text(pick("分析完成时间")),
        "飞书报告链接": report_link,
        "人工审核结果": _bitable_text(pick("人工审核结果")),
        "触发来源": _bitable_text(pick("触发来源")),
        "rootcause": _bitable_text(pick("rootcause")),
        "AI评论总结": _bitable_text(pick("AI评论总结")),
        "结果置信度": _bitable_text(pick("结果置信度")),
    }


def _flatten_bitable_record_all(fields: dict, report_field: str) -> dict:
    """提取多维表格单条记录的所有字段，URL 字段取 link"""
    result = {}
    for key, val in fields.items():
        if isinstance(val, dict) and "link" in val:
            # URL 字段取 link
            result[key] = str(val.get("link", "") or "").strip()
        else:
            result[key] = _bitable_text(val)
    # 飞书报告链接字段单独处理（可能是配置的字段名）
    if report_field and report_field in fields:
        report_val = fields[report_field]
        if isinstance(report_val, dict):
            result["飞书报告链接"] = str(report_val.get("link", "") or "").strip()
    return result


@app.get("/api/data/history_batches")
def data_history_batches():
    """数据面板：从飞书云端文件夹列出所有历史批量执行批次"""
    from src.clients import feishu_client
    folder_token = load_config().get("feishu_bitable", {}).get("batch_folder_token", "")
    if not folder_token:
        return _fail("未配置 batch_folder_token，无法读取云端历史")
    try:
        files = feishu_client.list_folder_files(folder_token, recursive=True)
    except Exception as e:
        logger.warning("读取云端批次列表失败: %s", e)
        return _fail(f"读取云端批次列表失败: {e}")
    batches = []
    for f in files:
        f_name = f.get("name", "")
        f_token = f.get("token", "")
        f_type = f.get("type", "")
        f_url = f.get("url", "")
        created = f.get("created_time", "")
        f_folder = f.get("folder", "")
        if not f_token:
            continue
        # 仅保留 docx 类型的文档
        if f_type and f_type != "docx":
            continue
        # 解析创建时间戳为可读日期
        date_label = created[:10] if len(created) >= 10 else created
        # label 包含文件夹路径（日期）和文档名
        prefix = f"{f_folder} / " if f_folder else ""
        batches.append({
            "token": f_token,
            "name": f_name,
            "label": f"{prefix}{f_name} ({date_label})",
            "value": f_token,
            "url": f_url,
            "created_time": created,
            "folder": f_folder,
        })
    # 按创建时间倒序（最新在前）
    batches.sort(key=lambda b: b.get("created_time", ""), reverse=True)
    return _ok({"batches": batches, "count": len(batches)},
               f"共找到 {len(batches)} 个云端批次")


def _parse_markdown_batch_table(md: str) -> list:
    """解析飞书文档 Markdown 中的批量执行表格，返回字典行列表

    飞书文档读取时每个 block 之间用 \n\n 分隔，表格行之间有空行，
    需要动态定位分隔行并跳过。
    """
    import re as _re
    rows = []
    lines = md.splitlines()
    # 找到表格起始行（包含 jira 的表头，不区分大小写）
    header_idx = -1
    headers = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and "jira" in stripped.lower():
            header_idx = i
            headers = [h.strip() for h in stripped.strip("|").split("|")]
            break
    if header_idx < 0:
        return rows
    # 从表头后扫描，找到分隔行（|---|---|...|）并跳过，兼容行间空行
    data_start = header_idx + 1
    for i in range(header_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue  # 跳过空行
        if _re.match(r'^\|[-|:\s]+\|$', stripped):
            data_start = i + 1  # 数据从分隔行之后开始
            break
        # 不是分隔行也不是空行，说明没有分隔行，直接从下一行开始
        data_start = i
        break
    for line in lines[data_start:]:
        line = line.strip()
        if not line or not line.startswith("|"):
            continue
        # 跳过残留的分隔行
        if _re.match(r'^\|[-|:\s]+\|$', line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < len(headers):
            cells.extend([""] * (len(headers) - len(cells)))
        row = {}
        for idx, h in enumerate(headers):
            row[h] = cells[idx] if idx < len(cells) else ""
        # 统一字段名：Jira号 / jira号
        jira_val = ""
        for key in ("Jira号", "jira号"):
            if key in row:
                jira_val = row[key].strip()
                break
        if jira_val:
            row["jira号"] = jira_val
            rows.append(row)
    return rows


@app.get("/api/data/history_batch_preview")
def data_history_batch_preview(batch_token: str = ""):
    """预览指定云端批次文档内容（从飞书文档读取）"""
    if not batch_token:
        return _fail("缺少 batch_token 参数")
    from src.clients import feishu_client
    try:
        md = feishu_client.fetch_docx_as_markdown(batch_token)
    except Exception as e:
        logger.warning("读取云端批次文档失败: %s", e)
        return _fail(f"读取云端文档失败: {e}")
    batch_rows = _parse_markdown_batch_table(md)
    rows = []
    for r in batch_rows:
        jira_no = (r.get("jira号") or "").strip()
        if not jira_no:
            continue
        # 兼容新旧格式：新格式有“触发时间”列，旧格式“执行时间”=触发时间
        trigger_time = (r.get("触发时间") or "").strip()
        exec_time = (r.get("执行时间") or "").strip()
        if not trigger_time and exec_time and "分析执行时间" not in r:
            # 旧格式：执行时间实际是触发时间
            trigger_time = exec_time
            exec_time = (r.get("分析执行时间") or "").strip()
        rows.append({
            "jira号": jira_no,
            "执行结果": (r.get("执行结果") or "").strip(),
            "报告长度": "",
            "触发时间": trigger_time,
            "执行时间": exec_time,
            "备注": (r.get("备注") or "").strip(),
        })
    return _ok({"rows": rows, "count": len(rows), "batch_token": batch_token},
               f"云端批次预览: {len(rows)} 条")


@app.post("/api/data/sync_cloud_batches")
async def sync_cloud_batches(request: Request):
    """从云端同步批量执行记录到本地CSV：按日期同步云端文档到 docs/日期/batch_*.csv

    用于将机器人触发但仅存在于云端的执行记录同步到本地，使Web面板可查看。
    """
    import csv as _csv
    from src.clients import feishu_client
    body = await request.json() or {}
    dates = body.get("dates") or []  # ["2026-09-18", "2026-09-19"]
    if not dates:
        return _fail("请指定要同步的日期列表，如 {\"dates\": [\"2026-09-18\"]}")
    folder_token = load_config().get("feishu_bitable", {}).get("batch_folder_token", "")
    if not folder_token:
        return _fail("未配置 batch_folder_token")
    doc_dir = get_path("doc_dir")
    synced_total = 0
    skipped_total = 0
    errors = []
    for date_str in dates:
        day_dir = os.path.join(doc_dir, date_str)
        os.makedirs(day_dir, exist_ok=True)
        # 收集本地已有的 jira 号集合（避免重复写入）
        existing_jiras = set()
        for fname in os.listdir(day_dir):
            if fname.startswith("batch_") and fname.endswith(".csv"):
                for r in _read_csv_rows(os.path.join(day_dir, fname)):
                    j = r.get("jira号", "").strip()
                    if j:
                        existing_jiras.add(j)
        # 列出云端日期子文件夹中的文件
        try:
            all_files = feishu_client.list_folder_files(folder_token, recursive=True)
        except Exception as e:
            errors.append(f"{date_str}: 列出云端文件失败 - {e}")
            continue
        cloud_docs = [f for f in all_files
                      if f.get("folder", "") == date_str and f.get("type") == "docx"
                      and f.get("name", "").startswith("批量执行")]
        if not cloud_docs:
            continue
        for doc in cloud_docs:
            doc_token = doc.get("token", "")
            doc_name = doc.get("name", "")
            if not doc_token:
                continue
            # 生成本地文件名：从文档标题中提取批次名
            safe_name = doc_name.replace("批量执行 ", "batch_cloud_").replace(" ", "_").replace(":", "")
            if not safe_name.endswith(".csv"):
                safe_name += ".csv"
            local_path = os.path.join(day_dir, safe_name)
            # 已存在则跳过
            if os.path.exists(local_path):
                skipped_total += 1
                continue
            # 读取云端文档并解析表格
            try:
                md = feishu_client.fetch_docx_as_markdown(doc_token)
                batch_rows = _parse_markdown_batch_table(md)
                if not batch_rows:
                    skipped_total += 1
                    continue
                # 过滤本地已有的 jira 号，只写入新记录
                new_rows = []
                for r in batch_rows:
                    jira_no = (r.get("jira号") or "").strip()
                    if jira_no and jira_no not in existing_jiras:
                        new_rows.append(r)
                        existing_jiras.add(jira_no)
                if not new_rows:
                    skipped_total += 1
                    continue
                # 写入本地 CSV（与 batch_execution 列名一致）
                fieldnames = ["jira号", "执行结果", "报告长度", "备注", "触发时间", "执行时间",
                              "分析并发数", "下载并发数", "模型", "触发来源"]
                with open(local_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = _csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for r in new_rows:
                        writer.writerow({
                            "jira号": (r.get("jira号") or "").strip(),
                            "执行结果": (r.get("执行结果") or "").strip(),
                            "报告长度": "",
                            "备注": (r.get("备注") or "").strip(),
                            "触发时间": (r.get("触发时间") or "").strip(),
                            "执行时间": (r.get("执行时间") or "").strip(),
                            "分析并发数": (r.get("分析并发数") or "").strip(),
                            "下载并发数": (r.get("下载并发数") or "").strip(),
                            "模型": (r.get("模型") or "").strip(),
                            "触发来源": (r.get("触发来源") or "").strip(),
                        })
                synced_total += 1
                logger.info("云端同步成功: %s → %s (%d条新记录)", doc_name, local_path, len(new_rows))
            except Exception as e:
                errors.append(f"{date_str}/{doc_name}: {e}")
                logger.warning("云端同步失败 %s/%s: %s", date_str, doc_name, e)
    msg = f"同步完成：新增 {synced_total} 个文件"
    if skipped_total:
        msg += f"，跳过 {skipped_total} 个已存在"
    if errors:
        msg += f"，失败 {len(errors)} 个"
    return _ok({"synced": synced_total, "skipped": skipped_total, "errors": errors}, msg)


@app.get("/api/data/history_jira")
def data_history_jira(batch_token: str = "", batch_name: str = "", batch_created: str = ""):
    """数据面板：从云端文档读取批次 Jira 列表并聚合多维表格匹配记录

    :param batch_token: 云端批次文档 token
    :param batch_name: 批次文档名称（用于解析执行时间过滤历史记录）
    :param batch_created: 批次文档创建时间（Unix 时间戳或 ISO 格式，作为兜底过滤）
    仅保留分析完成时间晚于批量执行时间的记录；命中多少展示多少，无命中则展示空行。
    """
    if not batch_token:
        return _fail("缺少 batch_token 参数")
    # 解析批量执行时间（兼容多种文档名格式）
    # 格式1: "批量执行 2026-09-07_104937"（下划线分隔）
    # 格式2: "线上批量执行 2026-09-15 150627 (10/10)"（空格分隔）
    # 格式3: "批量执行 2026-09-07_104937_extra"（带额外后缀）
    batch_exec_time = ""
    m = re.search(r"(\d{4}-\d{2}-\d{2})[_\s](\d{6})", batch_name or "")
    if m:
        batch_exec_time = f"{m.group(1)} {m.group(2)[:2]}:{m.group(2)[2:4]}:{m.group(2)[4:]}"
    # 兜底：从文档创建时间解析（飞书 API 返回 Unix 时间戳秒或 ISO 格式）
    if not batch_exec_time and batch_created:
        try:
            ts = int(batch_created)
            batch_exec_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError, OSError):
            # 尝试 ISO 格式 2026-09-15T15:06:27+08:00
            iso_m = re.search(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", batch_created)
            if iso_m:
                batch_exec_time = f"{iso_m.group(1)} {iso_m.group(2)}"
    if batch_exec_time:
        logger.info("批次过滤时间: %s（来源: %s）", batch_exec_time, "文档名" if m else "created_time")
    # —— 第1步：从云端文档读取 Jira 列表 ——
    from src.clients import feishu_client
    try:
        md = feishu_client.fetch_docx_as_markdown(batch_token)
    except Exception as e:
        logger.warning("读取云端批次文档失败: %s", e)
        return _fail(f"读取云端文档失败: {e}")
    batch_rows = _parse_markdown_batch_table(md)
    jira_list = []
    for r in batch_rows:
        jira_no = (r.get("jira号") or "").strip()
        if jira_no:
            jira_list.append({
                "jira号": jira_no,
                "执行结果": (r.get("执行结果") or "").strip(),
                "执行时间": (r.get("执行时间") or "").strip(),
                "备注": (r.get("备注") or "").strip(),
            })
    if not jira_list:
        return _ok({"rows": [], "count": 0}, "该批次无有效 Jira 记录")
    jira_set = set(item["jira号"] for item in jira_list)
    # —— 第2步：拉取多维表格全量记录，筛选当前批次相关的全部匹配记录 ——
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
    # jira号 -> [多条多维表格记录]，仅保留分析完成时间 >= 批次执行时间的记录
    bitable_records_map = {}
    if app_token and table_id:
        try:
            records = feishu_client.list_bitable_records(app_token, table_id)
            for rec in records:
                fields = rec.get("fields", {})
                jira_key = _bitable_text(fields.get(bugid_field, ""))
                if jira_key and jira_key in jira_set:
                    rec_done = _bitable_text(fields.get("分析完成时间", ""))
                    # 过滤：仅保留分析完成时间 >= 批量执行时间的记录（严格排除旧记录）
                    if batch_exec_time and (not rec_done or rec_done < batch_exec_time):
                        continue
                    bitable_records_map.setdefault(jira_key, []).append(
                        _flatten_bitable_record(fields, report_field))
        except Exception as e:
            logger.warning("批次聚合：多维表格查询失败（仅返回本地数据）: %s", e)
    # —— 第3步：合并——同一 Jira 仅保留最新一条分析记录 ——
    rows = []
    for item in jira_list:
        jira_no = item["jira号"]
        bt_records = bitable_records_map.get(jira_no, [])
        if bt_records:
            # 按分析完成时间倒序，取最新一条（本批次产生的最新分析记录）
            bt_records.sort(key=lambda x: x.get("分析完成时间", ""), reverse=True)
            bf = bt_records[0]
            rows.append({
                "jira号": jira_no,
                "执行结果": item["执行结果"],
                "执行时间": item["执行时间"],
                "分析结果": bf.get("分析结果", ""),
                "错误信息": bf.get("错误信息", ""),
                "飞书报告链接": bf.get("飞书报告链接", ""),
                "分析问题时间": bf.get("分析问题时间", ""),
                "分析完成时间": bf.get("分析完成时间", ""),
                "人工审核结果": bf.get("人工审核结果", ""),
                "触发来源": bf.get("触发来源", ""),
                "rootcause": bf.get("rootcause", ""),
                "AI评论总结": bf.get("AI评论总结", ""),
                "结果置信度": bf.get("结果置信度", ""),
            })
        else:
            # 无多维表格匹配，仅展示本地批量执行信息
            rows.append({
                "jira号": jira_no,
                "执行结果": item["执行结果"],
                "执行时间": item["执行时间"],
                "分析结果": "", "错误信息": "", "飞书报告链接": "", "分析问题时间": "", "分析完成时间": "",
                "触发来源": "", "rootcause": "", "AI评论总结": "", "结果置信度": "",
            })
    matched = len(jira_set & set(bitable_records_map.keys()))
    return _ok({"rows": rows, "count": len(rows), "matched": matched,
               "batch_token": batch_token},
               f"云端批次: {len(jira_list)} 个 Jira，多维表格命中 {matched} 个，展开 {len(rows)} 行")


@app.post("/api/audit/clear")
def clear_audited():
    """清空已抽查记录，允许重新抽查"""
    cfg = load_config()["audit"]
    audited_path = os.path.join(get_path("report_dir"), cfg["audited_file"])
    try:
        if os.path.exists(audited_path):
            os.remove(audited_path)
            logger.info("已抽查记录已清空: %s", audited_path)
            return _ok(None, "已抽查记录已清空")
        return _ok(None, "无已抽查记录")
    except Exception as e:
        logger.error("清空已抽查记录失败: %s", e)
        return _fail(str(e))


@app.get("/api/overview")
def overview():
    """首页概览：统计指标与接口模式状态，供流程可视化展示"""
    cfg = load_config()
    daily = _today_rows()
    audited = _read_csv_rows(os.path.join(get_path("report_dir"), cfg["audit"]["audited_file"]))
    # 统计字段完整数（5个补充字段均有值的行数）
    supplement_fields = ["分析问题时间", "AI分析结果(飞书链接)", "AI评论总结", "rootcause", "结果置信度"]
    complete_count = sum(1 for r in daily if all((r.get(f) or "").strip() not in ("", "-", "None") for f in supplement_fields))
    data = {
        "today": datetime.now().strftime("%Y-%m-%d"),
        "mock": {
            "ai_log": bool(cfg["ai_log_api"].get("mock")),
            "jira": bool(cfg["jira_api"].get("mock")),
            "kb": bool(cfg["knowledge_base_api"].get("mock")),
        },
        "daily_total": len(daily),
        "daily_complete": complete_count,
        "daily_incomplete": len(daily) - complete_count,
        "audited_total": len(audited),
    }
    return _ok(data)


@app.post("/api/test/ai_analyze")
async def test_ai_analyze(request: Request):
    """AI 日志分析功能测试：阶段1-调接口验证字段（15s）；阶段2-异步监听飞书通知下载文档"""
    import asyncio
    import time
    import httpx as _httpx
    from src.clients import feishu_client
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("bugid 不能为空")
    try:
        cfg = load_config()["ai_log_api"]
        # ── 阶段 1：调用 AI 接口，验证返回字段（15s 内完成）──
        payload = {cfg.get("bugid_field") or "issue_key": bugid}
        trigger_time = body.get("trigger_time") or None
        if trigger_time and cfg.get("trigger_time_field"):
            payload[cfg["trigger_time_field"]] = trigger_time
        api_timeout = int(cfg.get("timeout", 15))
        call_time = time.time()
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, lambda: _httpx.post(cfg["url"], json=payload,
                                      timeout=_httpx.Timeout(api_timeout, connect=8),
                                      headers={"Content-Type": "application/json"},
                                      verify=False)
        )
        api_elapsed = round(time.time() - call_time, 2)
        api_response = resp.json()
        # 验证字段：code=200 + issue_key 一致 + msg 含"已启动"
        resp_code = api_response.get("code")
        resp_msg = str(api_response.get("msg", ""))
        resp_key = (api_response.get("data") or {}).get("issue_key", "")
        api_success = (resp_code == 200 and resp_key == bugid and "已启动" in resp_msg)
        result = {"api_response": api_response, "api_elapsed": api_elapsed, "api_success": api_success}
        if not api_success:
            return _ok(result, f"接口返回不符合预期: code={resp_code}, key={resp_key}")
        # ── 阶段 2：异步监听与“王源泉”的对话，获取「分析完成通知」卡片 ──
        chat_name = cfg.get("chat_name") or "王源泉"
        chat_id = await loop.run_in_executor(None, feishu_client.find_chat_by_name, chat_name)
        if not chat_id:
            return _ok(result, f"接口调用成功，但未找到与 '{chat_name}' 的对话，无法监听完成通知")
        after_ts = str(int(call_time))
        report_link = await loop.run_in_executor(
            None, lambda: feishu_client.poll_message_for_report(
                chat_id, after_ts, poll_interval=15, max_wait=180)
        )
        result["report_link"] = report_link
        if not report_link:
            return _ok(result, "接口调用成功，但未在 180s 内收到飞书完成通知")
        # 下载报告文档
        doc_id = feishu_client.extract_doc_id_from_url(report_link)
        feishu_domain = feishu_client.extract_domain_from_url(report_link)
        if doc_id:
            try:
                md_content = await loop.run_in_executor(
                    None, lambda: feishu_client.fetch_docx_as_markdown(
                        doc_id, bugid=bugid, feishu_domain=feishu_domain)
                )
                doc_path = doc_generator.save_document(bugid, md_content)
                result.update(doc_path=doc_path, content_length=len(md_content),
                              conclusion=doc_generator.parse_conclusion(md_content))
                return _ok(result, f"全流程完成，文档已生成（{len(md_content)} 字）")
            except Exception as e:
                logger.error("飞书文档下载失败: %s", e)
                result["doc_error"] = str(e)
                return _ok(result, f"接口成功+通知已收到，但文档下载失败: {e}")
        return _ok(result, "接口成功+通知已收到，但无法提取文档 ID")
    except Exception as e:
        err_name = type(e).__name__
        if "Connect" in err_name or "10060" in str(e):
            msg = "AI 分析服务连接超时（目标地址不可达），请检查网络或服务状态"
        elif "Timeout" in err_name:
            msg = "AI 分析接口响应超时，请稍后重试或增大超时时间"
        else:
            msg = str(e)
        logger.error("AI 分析功能测试失败: [%s] %s", err_name, e)
        return _fail(msg)


@app.get("/api/test/batch_ai_csv_files")
async def test_batch_ai_csv_files():
    """列出 data/unanalyzed/ 下可用于功能7批量执行的 CSV 文件"""
    import csv as _csv
    files = []
    if os.path.isdir(_UNANALYZED_DIR):
        for fname in sorted(os.listdir(_UNANALYZED_DIR), reverse=True):
            if not fname.endswith(".csv"):
                continue
            fpath = os.path.join(_UNANALYZED_DIR, fname)
            count = 0
            try:
                with open(fpath, "r", encoding="utf-8-sig") as f:
                    reader = _csv.reader(f)
                    next(reader, None)
                    count = sum(1 for _ in reader)
            except Exception:
                pass
            files.append({"name": fname, "path": fpath, "count": count})
    return _ok(files, f"找到 {len(files)} 个 CSV 文件")


@app.post("/api/test/batch_ai_csv_import")
async def test_batch_ai_csv_import(request: Request):
    """从 CSV 文件导入 Jira 号及触发时间，去重后返回"""
    import csv as _csv
    body = await request.json() or {}
    csv_path = body.get("path", "").strip()
    if not csv_path or not os.path.isfile(csv_path):
        return _fail("CSV 文件不存在")
    rows = []
    csv_trigger_times = {}  # {jira号: 触发时间}，CSV 中已有的触发时间
    seen = set()
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                # 支持多种 Jira 号列名
                jira = (row.get("Jira号") or row.get("jira号") or row.get("JIRA号") or "").strip()
                if not jira or jira in seen:
                    continue
                seen.add(jira)
                # 读取触发时间列（多种列名兼容）
                tt = (row.get("触发时间") or row.get("创建时间") or row.get("执行时间") or row.get("分析执行时间") or "").strip()
                if tt:
                    csv_trigger_times[jira] = tt
                rows.append({"key": jira, "summary": "", "status": "", "created": ""})
    except Exception as e:
        return _fail(f"读取 CSV 失败: {e}")
    if not rows:
        return _fail("CSV 文件中无 Jira 号")
    dup_count = sum(1 for _ in open(csv_path, encoding="utf-8-sig").readlines()) - 1 - len(rows)
    msg = f"导入 {len(rows)} 条 Jira 号（去重后）"
    if csv_trigger_times:
        msg += f"，其中 {len(csv_trigger_times)} 条有触发时间"
    if dup_count > 0:
        msg += f"，去除重复 {dup_count} 条"
    return _ok({"rows": rows, "csv_trigger_times": csv_trigger_times}, msg)


@app.post("/api/test/batch_ai_search")
async def test_batch_ai_search(request: Request):
    """步骤1：搜索 Jira JQL 候选 bug，仅保留 key 含 VCU 的，展示完整表格"""
    body = await request.json() or {}
    jql = str(body.get("jql", "")).strip()
    if not jql:
        return _fail("JQL 查询语句不能为空")
    try:
        from src.clients import jira_client
        issues = jira_client.search_issues(jql, max_results=2000)
        vcu_issues = [i for i in issues if "VCU" in (i.get("key") or "").upper()]
        rows = []
        for i in vcu_issues:
            fields = i.get("fields") or {}
            rows.append({
                "key": (i.get("key") or "").strip(),
                "summary": (fields.get("summary") or "")[:120],
                "status": ((fields.get("status") or {}).get("name") or ""),
                "created": (fields.get("created") or "")[:10],
            })
        return _ok({"total": len(issues), "vcu_count": len(rows), "rows": rows},
                    f"搜索到 {len(issues)} 条，其中 VCU {len(rows)} 条")
    except Exception as e:
        logger.error("批量搜索失败: %s", e)
        return _fail(str(e))


@app.post("/api/test/batch_ai_extract_times/stop")
async def stop_batch_ai_extract_times():
    """触发批量提取停止信号（优雅停止：当前条目完成后停止后续）"""
    _batch_extract_stop_event.set()
    logger.info("收到批量提取停止信号，当前条目完成后将停止后续处理")
    return {"status": "ok", "message": "停止信号已发送，当前条目完成后停止"}


@app.post("/api/test/filter_success_jiras")
async def filter_success_jiras(request: Request):
    """查询多维表格中已分析成功的 Jira 号（分PC/线上），用于前端过滤"""
    import asyncio
    body = await request.json() or {}
    bugids = body.get("bugids") or []
    if not bugids:
        return _ok({"pc_success": [], "online_success": []})
    loop = asyncio.get_event_loop()
    try:
        from src.clients import feishu_client
        cfg = load_config().get("feishu_bitable", {})
        app_token = cfg.get("app_token", "")
        table_id = cfg.get("table_id", "")
        bugid_field = cfg.get("bugid_field", "jira号")
        if not app_token or not table_id:
            return _ok({"pc_success": [], "online_success": []})
        records = await loop.run_in_executor(
            None, feishu_client.list_bitable_records, app_token, table_id)
        bugid_set = set(bugids)
        pc_success, online_success = set(), set()
        for rec in records:
            fields = rec.get("fields", {})
            jk = _bitable_text(fields.get(bugid_field, ""))
            if not jk or jk not in bugid_set:
                continue
            result = _bitable_text(fields.get("分析结果", ""))
            if result != "成功":
                continue
            source = _bitable_text(fields.get("触发来源", ""))
            if source == "jira_analyze":
                pc_success.add(jk)
            else:
                online_success.add(jk)
        logger.info("过滤已成功: PC %d, 线上 %d (查询 %d 个 Jira)",
                   len(pc_success), len(online_success), len(bugids))
        return _ok({"pc_success": list(pc_success), "online_success": list(online_success)})
    except Exception as e:
        logger.warning("查询已成功 Jira 失败: %s", e)
        return _ok({"pc_success": [], "online_success": []})


@app.post("/api/test/batch_ai_extract_times")
async def test_batch_ai_extract_times(request: Request):
    """步骤2：批量提取所有候选的触发时间，SSE 实时推送进度"""
    import asyncio
    import json as _json
    body = await request.json() or {}
    keys = body.get("keys") or []
    filter_existing = body.get("filter_existing", False)  # 过滤多维表格中已有数据
    video_fallback = body.get("video_fallback", False)    # 用视频提取兜底
    refresh_cache = body.get("refresh_cache", False)      # 云端缓存更新：有缓存也重新提取
    re_extract_empty = body.get("re_extract_empty", False) # 空标记重新提取
    if not keys:
        return _fail("候选列表为空，请先执行步骤1")

    async def event_generator():
        import signal
        import threading
        import concurrent.futures
        loop = asyncio.get_event_loop()
        stop_event = threading.Event()
        _prev_handler = signal.getsignal(signal.SIGINT)

        def _on_sigint(sig, frame):
            logger.info("收到 Ctrl+C，正在停止时间提取...")
            stop_event.set()

        signal.signal(signal.SIGINT, _on_sigint)
        try:
            _batch_extract_stop_event.clear()  # 新批次开始时清除停止标志
            # 加载云端已有时间 + 所有已处理的 jira 号 + 成功分析记录（用于缓存过期判断，合并加载避免两次全量拉取）
            (cloud_times, cloud_keys), success_jiras = await asyncio.gather(
                loop.run_in_executor(None, _load_cloud_trigger_cache),
                loop.run_in_executor(None, _load_bitable_success_jiras),
            )
            # 过滤多维表格中已有数据（不论成功/失败，只要出现过就排除）
            bitable_exclude = set()
            if filter_existing:
                try:
                    from src.clients import feishu_client
                    bitable_records = await loop.run_in_executor(
                        None, feishu_client.list_bitable_records,
                        load_config().get("feishu_bitable", {}).get("app_token", ""),
                        load_config().get("feishu_bitable", {}).get("table_id", ""))
                    bf = load_config().get("feishu_bitable", {}).get("bugid_field", "jira号")
                    for rec in bitable_records:
                        fields = rec.get("fields", {})
                        fv = fields.get(bf, "")
                        if isinstance(fv, list):
                            fv = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in fv)
                        elif isinstance(fv, dict):
                            fv = fv.get("text", str(fv))
                        jk = str(fv).strip()
                        if jk:
                            bitable_exclude.add(jk)
                    logger.info("多维表格过滤: 排除 %d 个已有Jira号", len(bitable_exclude))
                except Exception as e:
                    logger.warning("多维表格过滤查询失败（跳过）: %s", e)
            # 加载已修正/已确认的诊断缓存记录（缓存更新时跳过这些）
            corrected_jiras = set()
            _cache_dir = os.path.join(PROJECT_ROOT, "data", "troubleshoot")
            if os.path.isdir(_cache_dir):
                for _fname in os.listdir(_cache_dir):
                    if not _fname.endswith(".json"):
                        continue
                    try:
                        with open(os.path.join(_cache_dir, _fname), "r", encoding="utf-8") as _f:
                            _c = _json.load(_f)
                        if _c.get("verify_status") in ("corrected", "success"):
                            corrected_jiras.add(_c.get("bugid", _fname[:-5]))
                    except Exception:
                        pass
            trigger_times = {}
            sources = {}
            need_fetch = []
            skip_empty = 0
            skip_bitable = 0
            skip_corrected = 0
            old_cache = {}  # refresh_cache 时保存旧缓存，提取失败时回退
            for key in keys:
                if key in bitable_exclude:
                    # 多维表格中已有，直接跳过
                    sources[key] = "已存在(多维表)"
                    skip_bitable += 1
                    continue
                if refresh_cache:
                    # 已修正/已确认的记录跳过重新提取
                    if key in corrected_jiras:
                        trigger_times[key] = cloud_times.get(key, "")
                        sources[key] = "已修正(跳过)"
                        skip_corrected += 1
                        continue
                    # 强制重新提取：记录旧缓存值，放入 need_fetch
                    if key in cloud_times:
                        old_cache[key] = cloud_times[key]
                    need_fetch.append(key)
                elif key in cloud_times:
                    # 云端有触发时间，直接使用（包含用户手动修正的值）
                    trigger_times[key] = cloud_times[key]
                    sources[key] = "云端缓存"
                elif key in cloud_keys and not re_extract_empty:
                    # 云端已记录但无触发时间（之前提取为空），跳过
                    sources[key] = "已标记空"
                    skip_empty += 1
                else:
                    need_fetch.append(key)
            cloud_hit = len(trigger_times)
            total = len(keys)
            yield f"data: {_json.dumps({'type': 'start', 'total': total, 'local_hit': cloud_hit, 'need_fetch': len(need_fetch), 'skip_empty': skip_empty, 'skip_bitable': skip_bitable, 'skip_corrected': skip_corrected, 'refresh_cache': refresh_cache, 're_extract_empty': re_extract_empty}, ensure_ascii=False)}\n\n"
            # 对未处理过的走接口提取
            done_count = cloud_hit + skip_empty
            empty_count = 0
            interrupted = False
            if need_fetch:
                from src.clients import jira_client as _jc
                for i, key in enumerate(need_fetch):
                    if _batch_extract_stop_event.is_set():
                        logger.info("前端停止信号触发，优雅中断（已完成 %d/%d）", i, len(need_fetch))
                        interrupted = True
                        break
                    if stop_event.is_set():
                        logger.info("Ctrl+C 中断提取（已完成 %d/%d）", i, len(need_fetch))
                        interrupted = True
                        break
                    if await request.is_disconnected():
                        logger.info("客户端已断开，提取中断（已完成 %d/%d）", i, len(need_fetch))
                        interrupted = True
                        break
                    await asyncio.sleep(0)
                    status = "success"
                    tt_val = ""
                    try:
                        issue = await asyncio.wait_for(
                            loop.run_in_executor(None, _jc.fetch_issue, key),
                            timeout=30)
                        # 视频 OCR 优先级最高（当启用视频兜底时）
                        tt = ""
                        if video_fallback:
                            video_tt = await loop.run_in_executor(
                                None, _diag_extract_time_from_video_simple, issue)
                            if video_tt:
                                tt = video_tt
                                sources[key] = "视频提取"
                        # 视频未提取到 → 正常提取流程（标题→评论→描述→自定义字段）
                        if not tt:
                            tt = _jc.extract_trigger_time_from_issue(issue)
                            if tt:
                                sources[key] = "新提取"
                        if tt:
                            trigger_times[key] = tt
                            tt_val = tt
                            await loop.run_in_executor(None, _save_trigger_time_to_cloud, key, tt)
                        else:
                            # 提取为空：检查是否有旧缓存可回退
                            if key in old_cache:
                                trigger_times[key] = old_cache[key]
                                sources[key] = "旧缓存"
                                tt_val = old_cache[key]
                            else:
                                status = "empty"
                                empty_count += 1
                                sources[key] = "空标记"
                                await loop.run_in_executor(None, _save_trigger_time_to_cloud, key, "")
                    except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
                        status = "error"
                        logger.warning("提取触发时间超时 %s", key)
                    except Exception as e:
                        if stop_event.is_set():
                            interrupted = True
                            break
                        status = "error"
                        logger.warning("提取触发时间失败 %s: %s", key, e)
                    done_count += 1
                    yield f"data: {_json.dumps({'type': 'progress', 'index': done_count, 'total': total, 'key': key, 'status': status, 'time': tt_val}, ensure_ascii=False)}\n\n"
            new_count = len(trigger_times) - cloud_hit
            if interrupted:
                logger.info("提取被 Ctrl+C 中断: 已完成 %d 条（云端命中 %d, 新提取 %d）",
                            done_count, cloud_hit, new_count)
            else:
                logger.info("批量提取触发时间: 云端命中 %d, 跳过空 %d, 新提取 %d, 本次空 %d, 共 %d/%d",
                            cloud_hit, skip_empty, new_count, empty_count, len(trigger_times), total)
            yield f"data: {_json.dumps({'type': 'done', 'time_count': len(trigger_times), 'total': total, 'local_hit': cloud_hit, 'new_count': new_count, 'empty_count': empty_count, 'skip_empty': skip_empty, 'skip_bitable': skip_bitable, 'skip_corrected': skip_corrected, 'interrupted': interrupted, 'trigger_times': trigger_times, 'sources': sources}, ensure_ascii=False)}\n\n"
        finally:
            signal.signal(signal.SIGINT, _prev_handler)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/test/batch_ai_filter")
async def test_batch_ai_filter(request: Request):
    """步骤3：查询多维表格，过滤掉已存在的记录。支持多种过滤模式组合"""
    body = await request.json() or {}
    keys = body.get("keys") or []
    filter_all = body.get("filter_all", False)
    filter_pc_only = body.get("filter_pc_only", False)  # 仅过滤触发来源为PC的记录
    filter_online_only = body.get("filter_online_only", False)  # 仅过滤线上的记录
    filter_ai_preliminary = body.get("filter_ai_preliminary", False)  # 过滤AI初步分析结果
    if not keys:
        return _fail("候选列表为空，请先执行步骤1")
    # 查询多维表格，获取应排除的 jira 号
    exclude_keys = set()
    try:
        import asyncio
        from src.clients import feishu_client
        loop = asyncio.get_event_loop()
        records = await loop.run_in_executor(None, feishu_client.list_bitable_records,
                                             load_config().get("feishu_bitable", {}).get("app_token", ""),
                                             load_config().get("feishu_bitable", {}).get("table_id", ""))
        bugid_field = load_config().get("feishu_bitable", {}).get("bugid_field", "jira号")
        for rec in records:
            fields = rec.get("fields", {})
            field_value = fields.get(bugid_field, "")
            if isinstance(field_value, list):
                field_value = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in field_value)
            elif isinstance(field_value, dict):
                field_value = field_value.get("text", str(field_value))
            jira_key = str(field_value).strip()
            if not jira_key:
                continue
            # 按来源过滤：PC/线上分别判断是否排除（正确+通用失败）
            trigger_source = _bitable_text(fields.get("触发来源", ""))
            is_pc = trigger_source == "jira_analyze"
            if filter_pc_only and filter_online_only:
                # 两个都勾选：排除PC和线上中的正确+通用失败记录
                if not _is_bitable_excluded(fields, bugid_field):
                    continue
            elif filter_pc_only:
                # 仅PC：只处理PC来源记录，排除其中的正确+通用失败
                if not is_pc:
                    continue
                if not _is_bitable_excluded(fields, bugid_field):
                    continue
            elif filter_online_only:
                # 仅线上：只处理线上来源记录，排除其中的正确+通用失败
                if is_pc:
                    continue
                if not _is_bitable_excluded(fields, bugid_field):
                    continue
            # 过滤AI初步分析结果：强制使用智能过滤（排除已成功+无效审核），覆盖filter_all
            use_smart = filter_ai_preliminary or (not filter_all)
            if use_smart:
                if _is_bitable_excluded(fields, bugid_field):
                    exclude_keys.add(jira_key)
            else:
                exclude_keys.add(jira_key)
        mode_parts = []
        if filter_all and not filter_ai_preliminary:
            mode_parts.append("所有已存在")
        if not filter_pc_only and not filter_online_only and not filter_all and not filter_ai_preliminary:
            mode_parts.append("成功+无需重试")
        if filter_pc_only and filter_online_only:
            mode_parts.append("PC+线上正确和通用失败")
        else:
            if filter_pc_only:
                mode_parts.append("PC正确+通用失败")
            if filter_online_only:
                mode_parts.append("线上正确+通用失败")
        if filter_ai_preliminary:
            mode_parts.append("AI初步分析")
        mode_desc = "+".join(mode_parts)
        logger.info("多维表格重复过滤(%s): 排除记录 %d 条", mode_desc, len(exclude_keys))
    except Exception as e:
        logger.warning("多维表格重复过滤查询失败（跳过此检查）: %s", e)
    # 过滤候选列表
    filtered = [k for k in keys if k not in exclude_keys]
    removed = len(keys) - len(filtered)
    if not filtered:
        return _fail(f"所有候选均已存在于多维表格中（共过滤 {removed} 条）")
    return _ok({"filtered": filtered, "removed": removed, "total": len(keys),
                 "exclude_keys": list(exclude_keys)[:20]},
                f"候选 {len(keys)} 条，过滤 {removed} 条，剩余 {len(filtered)} 条")


@app.post("/api/test/batch_ai_sample")
async def test_batch_ai_sample(request: Request):
    """步骤4：从候选列表中随机抽取，优先云端已有时间，不够则逐批提取，提取失败跳过继续补充

    去重规则：docs/ 全量 CSV 已测试 排除，候选 keys 已由步骤3过滤
    """
    import random
    body = await request.json() or {}
    keys = body.get("keys") or []
    count = int(body.get("count", 0))
    csv_trigger_times = body.get("csv_trigger_times") or {}  # CSV 导入时携带的触发时间
    if not keys:
        return _fail("候选列表为空，请先执行步骤1")
    if count <= 0:
        return _fail("抽取数量必须大于 0")
    # 去重 keys（CSV 可能包含重复）
    seen_keys = set()
    unique_keys = []
    for k in keys:
        if k not in seen_keys:
            seen_keys.add(k)
            unique_keys.append(k)
    keys = unique_keys
    # 扫描 docs/ 下所有 CSV 已测试的 jira 号（含历史批量文件）
    tested = _load_all_doc_jira_keys()
    # 排除 docs/ 已测试记录（步骤3已过滤多维表格成功记录）
    available = [k for k in keys if k not in tested]
    if not available:
        return _fail(f"所有候选 bug 均已测试过（已测试 {len(tested)} 条）")
    # 从云端加载触发时间 + 空标记（支持多表，合并加载避免两次全量拉取）
    local_times, cloud_keys = _load_cloud_trigger_cache()
    # 始终信任云端缓存，无缓存的才重新提取
    trigger_times = {}
    for k in available:
        if k in local_times and local_times[k]:
            trigger_times[k] = local_times[k]
    # 合并 CSV 携带的触发时间（云端优先，CSV 补充）
    csv_hit = 0
    for k in available:
        if k not in trigger_times and k in csv_trigger_times and csv_trigger_times[k]:
            trigger_times[k] = csv_trigger_times[k]
            csv_hit += 1
    # 分类：有时间的 / 待提取池（云端已记录的空标记也跳过，不重复提取）
    with_time = [k for k in available if k in trigger_times]
    pending_pool = [k for k in available if k not in trigger_times and k not in cloud_keys]
    random.shuffle(pending_pool)
    # 先从有时间的中抽取
    sample_size = min(count, len(available))
    selected = []
    cloud_picked = 0
    new_extracted = 0
    extract_failed = 0
    new_to_cloud = {}  # 循环内收集待上传云端的数据，循环后批量上传
    if with_time:
        pick_with = min(sample_size, len(with_time))
        selected.extend(random.sample(with_time, pick_with))
        cloud_picked = pick_with
    # 云端已足够，不再提取
    if len(selected) >= sample_size:
        selected = selected[:sample_size]
    else:
        # 云端不够，从待提取池逐批提取，提取失败跳过继续下一个，直到凑够或池子耗尽
        extract_batch = 20
        _cloud_flush_interval = 2  # 每提取 2 个增量保存一次云端，防止请求超时丢失
        _cloud_flush_counter = 0
        while len(selected) < sample_size and pending_pool:
            batch = pending_pool[:extract_batch]
            pending_pool = pending_pool[extract_batch:]
            for k in batch:
                if len(selected) >= sample_size:
                    break
                try:
                    from src.clients import jira_client as _jc
                    issue = _jc.fetch_issue(k)
                    # 视频 OCR 提取优先级最高
                    tt = _diag_extract_time_from_video_simple(issue)
                    if not tt:
                        tt = _jc.extract_trigger_time_from_issue(issue)
                    # 防御性处理：确保 tt 是字符串
                    if tt and not isinstance(tt, str):
                        if hasattr(tt, 'strftime'):
                            tt = tt.strftime("%Y-%m-%d %H:%M:%S")
                        elif isinstance(tt, (tuple, list)) and len(tt) >= 1:
                            tt = str(tt[0])
                        else:
                            tt = str(tt)
                    if tt:
                        trigger_times[k] = tt
                        _save_trigger_time_to_csv(k, tt)
                        new_to_cloud[k] = tt
                        selected.append(k)
                        new_extracted += 1
                    else:
                        _save_trigger_time_to_csv(k, "")
                        new_to_cloud[k] = ""
                        extract_failed += 1
                except Exception as e:
                    logger.warning("抽样按需提取触发时间失败 %s: %s", k, e)
                    # 失败也保存空标记，防止下次重复提取
                    _save_trigger_time_to_csv(k, "")
                    new_to_cloud[k] = ""
                    extract_failed += 1
                # 增量保存云端：每 N 个刷新一次，防止请求超时导致已提取数据全部丢失
                _cloud_flush_counter += 1
                if _cloud_flush_counter >= _cloud_flush_interval and new_to_cloud:
                    _batch_save_trigger_times_to_cloud(new_to_cloud)
                    new_to_cloud.clear()
                    _cloud_flush_counter = 0
    # 循环结束后保存剩余未上传的到云端
    if new_to_cloud:
        _batch_save_trigger_times_to_cloud(new_to_cloud)
    # 统计
    with_time_count = len([k for k in selected if k in trigger_times])
    time_info = f"，{with_time_count} 条有触发时间（云端 {cloud_picked} + CSV {csv_hit} + 新提取 {new_extracted}）"
    if extract_failed:
        time_info += f"，提取失败跳过 {extract_failed} 条"
    return _ok({"available_count": len(available), "tested_count": len(tested),
                 "selected": selected, "selected_count": len(selected),
                 "trigger_times": trigger_times, "time_count": len(trigger_times),
                 "cloud_picked": cloud_picked, "csv_hit": csv_hit,
                 "new_extracted": new_extracted,
                 "extract_failed": extract_failed, "pending_scanned": len(pending_pool)},
                f"可用 {len(available)} 条，抽取 {len(selected)} 条{time_info}")


@app.post("/api/test/batch_ai_run")
async def test_batch_ai_run(request: Request):
    """步骤5：并行批量执行 AI 日志分析，SSE 实时推送每个完成结果，完成后写入本次批量执行表格"""
    import asyncio
    import json as _json
    import csv as _csv
    import queue
    from src.clients import ai_log_client
    body = await request.json() or {}
    bugids = body.get("bugids") or []
    trigger_times = body.get("trigger_times") or {}
    # 批量执行元数据（分析并发数、下载并发数、模型、触发来源）
    _batch_meta = {
        "分析并发数": str(body.get("analysis_concurrency", "10")),
        "下载并发数": str(body.get("download_concurrency", "4")),
        "模型": str(body.get("model", "deepseek-v-pro")),
        "触发来源": str(body.get("trigger_source", "PC")),
    }
    if not bugids:
        return _fail("待执行列表为空，请先执行步骤2")
    # 从云端补全缺失的触发时间（用户可能跳过步骤2直接执行）
    missing = [b for b in bugids if b not in trigger_times]
    if missing:
        try:
            cloud_times = await asyncio.get_event_loop().run_in_executor(None, _load_trigger_times_from_cloud)
            filled = 0
            for b in missing:
                if b in cloud_times and cloud_times[b]:
                    trigger_times[b] = cloud_times[b]
                    filled += 1
            if filled:
                logger.info("从云端补全 %d/%d 个缺失触发时间", filled, len(missing))
        except Exception as e:
            logger.warning("云端触发时间加载失败: %s", e)
    # 步骤3已过滤多维表格成功记录，此处不再重复去重
    skipped_jiras = []
    
    async def event_generator():
        import threading
        stop_event = threading.Event()
        batch_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        yield f"data: {_json.dumps({'type': 'start', 'total': len(bugids)}, ensure_ascii=False)}\n\n"
        result_queue = queue.Queue()
        loop = asyncio.get_event_loop()

        def _run_one(bugid):
            """在线程池中执行单个 AI 分析：支持 stop_event 中断"""
            if stop_event.is_set():
                return
            from src.clients.base import http_post
            # 无触发时间的 Jira 号跳过执行
            exec_time = trigger_times.get(bugid)
            if not exec_time:
                result_queue.put({"jira号": bugid, "执行结果": "失败",
                                  "报告长度": 0, "备注": "无触发时间", "触发时间": "", "执行时间": batch_start_time,
                                  "分析执行时间": batch_start_time,
                                  "status": "fail", "report_len": 0, "msg": "无触发时间"})
                return
            try:
                cfg = load_config()["ai_log_api"]
                payload = {cfg["bugid_field"]: bugid}
                if cfg.get("trigger_time_field"):
                    payload[cfg["trigger_time_field"]] = exec_time
                resp = http_post(cfg["url"], payload, timeout=min(int(cfg.get("timeout", 60)), 30))
                if stop_event.is_set():
                    return
                # 判断是否异步启动成功：code=200 且 msg 包含异步关键词
                resp_code = resp.get("code") if isinstance(resp, dict) else None
                resp_msg = str(resp.get("msg", "")) if isinstance(resp, dict) else ""
                is_async_ok = (resp_code == 200 or resp_code == 0) and any(
                    kw in resp_msg for kw in ["分析任务已启动", "后台处理", "正在分析"])
                if is_async_ok:
                    result_queue.put({"jira号": bugid, "执行结果": "成功",
                                      "报告长度": 0, "备注": resp_msg[:200], "触发时间": exec_time, "执行时间": batch_start_time,
                                      "分析执行时间": batch_start_time,
                                      "status": "success", "report_len": 0, "msg": resp_msg[:100]})
                else:
                    result_queue.put({"jira号": bugid, "执行结果": "失败",
                                      "报告长度": 0, "备注": f"返回异常: {resp_msg[:150]}", "触发时间": exec_time, "执行时间": batch_start_time,
                                      "分析执行时间": batch_start_time,
                                      "status": "fail", "report_len": 0, "msg": resp_msg[:100]})
            except Exception as e:
                result_queue.put({"jira号": bugid, "执行结果": "失败", "报告长度": 0,
                                  "备注": str(e)[:200], "status": "fail",
                                  "report_len": 0, "msg": str(e)[:100],
                                  "触发时间": exec_time,
                                  "执行时间": batch_start_time,
                                  "分析执行时间": batch_start_time})

        # 并行启动所有任务
        for bugid in bugids:
            loop.run_in_executor(None, _run_one, bugid)

        # 轮询队列，实时推送完成事件
        results = []
        while len(results) < len(bugids):
            if await request.is_disconnected():
                stop_event.set()
                logger.info("客户端已断开，停止批量执行（已完成 %d/%d）", len(results), len(bugids))
                break
            try:
                item = result_queue.get_nowait()
                results.append(item)
                yield f"data: {_json.dumps({'type': 'progress', 'index': len(results), 'total': len(bugids), 'bugid': item['jira号'], 'status': item['status'], 'report_len': item.get('report_len', 0), 'msg': item.get('msg', ''), 'exec_time': item.get('触发时间', ''), 'analysis_time': item.get('执行时间', '')}, ensure_ascii=False)}\n\n"
            except queue.Empty:
                await asyncio.sleep(1)

        # 写入本次批量执行表格：docs/日期/batch_HHMMSS.csv
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        batch_csv = os.path.join(get_path("doc_dir"), date_str, f"batch_{time_str}.csv")
        os.makedirs(os.path.dirname(batch_csv), exist_ok=True)
        fieldnames = ["jira号", "执行结果", "报告长度", "备注", "触发时间", "执行时间",
                      "分析并发数", "下载并发数", "模型", "触发来源"]
        with open(batch_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow({"jira号": r["jira号"], "执行结果": r["执行结果"],
                                 "报告长度": r["报告长度"], "备注": r["备注"],
                                 "触发时间": r.get("触发时间", ""),
                                 "执行时间": r.get("执行时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                                 **_batch_meta})
        success_count = sum(1 for r in results if r["执行结果"] == "成功")
        fail_count = len(results) - success_count
        # 将结果写入每日结论报表（仅含已知字段，后续单Jira流程会补全其余字段）
        try:
            from src.core import report as report_module
            daily_rows = [{"jira号": r["jira号"],
                           "分析问题时间": r.get("触发时间", ""),
                           "AI分析结果(飞书链接)": "", "AI评论总结": "",
                           "rootcause": "", "结果置信度": ""} for r in results]
            report_module.generate_daily_csv(daily_rows, date_str=date_str)
        except Exception as e:
            logger.warning("批量执行写入每日报表失败（不影响主流程）: %s", e)
        # 上传到飞书云端文件夹
        cloud_url = ""
        try:
            doc_title = f"批量执行 {date_str}_{time_str} ({success_count}/{len(results)})"
            cloud_url = _upload_batch_to_cloud(batch_csv, doc_title)
        except Exception as e:
            logger.warning("批量执行上传云端失败（不影响主流程）: %s", e)
        done_msg = f"执行完成：成功 {success_count} 条，失败 {fail_count} 条"
        if skipped_jiras:
            done_msg += f"，已跳过 {len(skipped_jiras)} 条（多维表格已成功）"
        yield f"data: {_json.dumps({'type': 'done', 'total': len(results), 'success': success_count, 'fail': fail_count, 'skipped': len(skipped_jiras), 'message': done_msg, 'csv_path': batch_csv, 'cloud_url': cloud_url}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/test/batch_quality_assess")
async def test_batch_quality_assess(request: Request):
    """本批次质量评估：统计成功率/耗时，扫描多维表格补写缺失的执行时间"""
    from src.clients import feishu_client
    body = await request.json() or {}
    bugids = body.get("bugids") or []
    doc_created_time = str(body.get("doc_created_time", "")).strip()
    if not bugids:
        return _fail("请先执行批量分析")
    cfg = load_config().get("feishu_bitable", {})
    app_token, table_id = cfg.get("app_token", ""), cfg.get("table_id", "")
    if not app_token or not table_id:
        return _fail("多维表格未配置")
    bitable = feishu_client.list_bitable_records(app_token, table_id)
    jira_set = set(bugids)
    latest_done, missing_exec = "", []
    for rec in bitable:
        fields = rec.get("fields", {})
        jid = _bitable_text(fields.get("jira号", ""))
        if jid not in jira_set:
            continue
        dt = _bitable_text(fields.get("分析完成时间", ""))
        if dt > latest_done:
            latest_done = dt
        if not _bitable_text(fields.get("分析问题时间", "")).strip():
            missing_exec.append({"record_id": rec["record_id"], "jira_no": jid})
    # 优先使用云端文档创建时间，否则回退到本地 CSV 创建时间
    csv_ctime = doc_created_time if doc_created_time else ""
    if not csv_ctime:
        doc_dir = get_path("doc_dir")
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_dir = os.path.join(doc_dir, today_str)
        if os.path.isdir(today_dir):
            csvs = sorted([f for f in os.listdir(today_dir) if f.startswith("batch_") and f.endswith(".csv")], reverse=True)
            if csvs:
                csv_ctime = datetime.fromtimestamp(
                    os.path.getctime(os.path.join(today_dir, csvs[0]))).strftime("%Y-%m-%d %H:%M:%S")
    # 批量补写缺失的执行时间
    backfilled = 0
    if missing_exec and csv_ctime:
        updates = [{"record_id": m["record_id"], "fields": {"分析问题时间": csv_ctime}} for m in missing_exec]
        for i in range(0, len(updates), 100):
            feishu_client.update_bitable_records(app_token, table_id, updates[i:i + 100])
        backfilled = len(missing_exec)
    return _ok({"assessment": {
        "total": len(bugids), "backfilled": backfilled,
        "missing_count": len(missing_exec), "latest_done": latest_done, "backfill_time": csv_ctime,
    }}, "质量评估完成")


@app.get("/api/docs/files")
async def list_docs_files():
    """列出 docs/ 目录下所有 CSV 文件，按日期分组倒序"""
    doc_dir = get_path("doc_dir")
    files = []
    if not os.path.isdir(doc_dir):
        return _ok(files)
    for day in sorted(os.listdir(doc_dir), reverse=True):
        day_dir = os.path.join(doc_dir, day)
        if not os.path.isdir(day_dir):
            continue
        for fname in sorted(os.listdir(day_dir), reverse=True):
            if not fname.lower().endswith(".csv"):
                continue
            full_path = os.path.join(day_dir, fname)
            size_kb = round(os.path.getsize(full_path) / 1024, 1)
            files.append({"name": fname, "day": day, "path": full_path,
                          "size_kb": size_kb, "date": day})
    return _ok(files)


@app.get("/api/docs/preview")
async def preview_docs_file(path: str = ""):
    """预览指定 CSV 文件内容（前 50 行）"""
    if not path or not os.path.isfile(path):
        return _fail(f"文件不存在: {path}")
    rows = _read_csv_rows(path)
    return _ok({"rows": rows[:50], "total": len(rows)})


@app.get("/api/verify/history_files")
async def list_verify_history_files():
    """列出 data/ 和 docs/ 目录下所有 compare_log CSV 文件，按日期分组倒序"""
    files = []
    scan_dirs = [
        os.path.join(PROJECT_ROOT, "data"),
        get_path("doc_dir"),
    ]
    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for day in sorted(os.listdir(scan_dir), reverse=True):
            day_dir = os.path.join(scan_dir, day)
            if not os.path.isdir(day_dir):
                continue
            for fname in sorted(os.listdir(day_dir), reverse=True):
                if "_compare_log" not in fname.lower() or not fname.lower().endswith(".csv"):
                    continue
                full_path = os.path.join(day_dir, fname)
                size_kb = round(os.path.getsize(full_path) / 1024, 1)
                rows = _read_csv_rows(full_path)
                low_conf_count = sum(1 for r in rows if _parse_conf(r.get("结果置信度", "")) < 0.7)
                files.append({"name": fname, "day": day, "path": full_path,
                              "size_kb": size_kb, "total": len(rows),
                              "low_conf": low_conf_count})
    return _ok(files)


@app.get("/api/verify/history_load")
async def load_verify_history(path: str = ""):
    """加载指定 compare_log CSV 文件的全部记录"""
    if not path or not os.path.isfile(path):
        return _fail(f"文件不存在: {path}")
    rows = _read_csv_rows(path)
    return _ok({"rows": rows, "total": len(rows), "path": path})


@app.post("/api/verify_and_fill")
async def verify_and_fill(request: Request):
    """结果验证与填入：支持多文件，读取 CSV 提取 bugid，计算并填入三个字段"""
    import asyncio
    import json as _json
    import csv as _csv
    body = await request.json() or {}
    # 兼容单路径和多路径
    csv_paths = body.get("csv_paths") or []
    if not csv_paths and body.get("csv_path"):
        csv_paths = [body["csv_path"]]
    csv_paths = [p.strip() for p in csv_paths if p.strip() and os.path.isfile(p.strip())]
    # 支持直接传入 jira 号列表
    bugids = body.get("bugids") or []
    bugids = [b.strip() for b in bugids if b.strip()]
    if not csv_paths and not bugids:
        return _fail("无有效文件路径或 jira 号")

    async def event_generator():
        from src import pipeline
        from src.clients import feishu_client
        loop = asyncio.get_event_loop()
        # 预加载多维表格记录，构建成功集合 + 飞书链接映射（只处理成功的记录）
        bitable_success = set()
        bitable_links = {}  # bugid → 飞书报告链接
        bitable_available = False
        report_field_name = load_config().get("feishu_bitable", {}).get("report_field", "AI分析结果(飞书链接)")
        try:
            records = await loop.run_in_executor(
                None, feishu_client.list_bitable_records,
                load_config().get("feishu_bitable", {}).get("app_token", ""),
                load_config().get("feishu_bitable", {}).get("table_id", ""))
            bitable_available = True
            bugid_field = load_config().get("feishu_bitable", {}).get("bugid_field", "jira号")
            for rec in records:
                fields = rec.get("fields", {})
                field_value = fields.get(bugid_field, "")
                if isinstance(field_value, list):
                    field_value = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in field_value)
                elif isinstance(field_value, dict):
                    field_value = field_value.get("text", str(field_value))
                jira_key = str(field_value).strip()
                if not jira_key:
                    continue
                result_status = str(fields.get("分析结果", "")).strip()
                if result_status == "成功":
                    bitable_success.add(jira_key)
                    # 提取飞书报告链接
                    link_val = fields.get(report_field_name, "")
                    if isinstance(link_val, dict) and "link" in link_val:
                        bitable_links[jira_key] = link_val["link"]
                    elif isinstance(link_val, str) and link_val.startswith("http"):
                        bitable_links[jira_key] = link_val
            logger.info("验证过滤: 多维表格成功记录 %d 条，含飞书链接 %d 条", len(bitable_success), len(bitable_links))
        except Exception as e:
            logger.warning("多维表格查询失败（跳过过滤）: %s", e)

        for file_idx, csv_path in enumerate(csv_paths):
            file_name = os.path.basename(csv_path)
            yield f"data: {_json.dumps({'type': 'file_start', 'file_index': file_idx,
                                        'file_name': file_name, 'file_total': len(csv_paths)}, ensure_ascii=False)}\n\n"
            rows = _read_csv_rows(csv_path)
            if not rows:
                yield f"data: {_json.dumps({'type': 'file_error', 'file_index': file_idx,
                                            'msg': f'{file_name}: CSV 为空'}, ensure_ascii=False)}\n\n"
                continue
            # 识别 bugid 列
            bugid_col = None
            for col in ["jira号", "bugid", "key", "issue_key", "Bug ID"]:
                if col in rows[0]:
                    bugid_col = col
                    break
            if not bugid_col:
                for c in rows[0].keys():
                    if "jira" in c.lower() or "bug" in c.lower():
                        bugid_col = c
                        break
            if not bugid_col:
                bugid_col = list(rows[0].keys())[0]
            # 置信度阈值：从配置读取，默认 0.7
            confidence_threshold = float(load_config().get("similarity", {}).get("threshold", 0.7))
            # 对比记录文件：原文件名 + _compare_log
            base, ext = os.path.splitext(csv_path)
            compare_log_path = f"{base}_compare_log{ext}"
            total = len(rows)
            yield f"data: {_json.dumps({'type': 'start', 'file_index': file_idx,
                                        'total': total, 'file_name': file_name}, ensure_ascii=False)}\n\n"
            ready_count = 0
            low_conf_count = 0
            with open(compare_log_path, "w", newline="", encoding="utf-8-sig") as flog:
                log_fields = ["jira号", "rootcause", "AI评论总结", "结果置信度", "达标", "原因"]
                log_writer = _csv.DictWriter(flog, fieldnames=log_fields, extrasaction="ignore")
                log_writer.writeheader()
                for idx, row in enumerate(rows):
                    # 客户端断开时停止验证
                    if await request.is_disconnected():
                        logger.info("verify: 客户端已断开，停止验证 bugid=%s", row.get(bugid_col, ""))
                        yield f"data: {_json.dumps({'type': 'cancelled', 'file_index': file_idx}, ensure_ascii=False)}\n\n"
                        return
                    bugid = str(row.get(bugid_col, "")).strip()
                    if not bugid:
                        continue
                    # 多维表格中未成功（不存在或失败）的记录跳过验证
                    if bitable_available and bugid not in bitable_success:
                        log_writer.writerow({"jira号": bugid, "达标": "否", "原因": "多维表格中未成功"})
                        yield f"data: {_json.dumps({'type': 'progress', 'file_index': file_idx,
                                                    'index': idx + 1, 'total': total, 'bugid': bugid,
                                                    'status': 'skipped', 'rootcause': '', 'confidence': '',
                                                    'comment_summary': '', 'msg': '多维表格中未成功，已跳过'}, ensure_ascii=False)}\n\n"
                        continue
                    # 从多维表格注入飞书报告链接（若CSV行中缺失）
                    if not row.get("AI分析结果(飞书链接)") and bugid in bitable_links:
                        row["AI分析结果(飞书链接)"] = bitable_links[bugid]
                    try:
                        result = await loop.run_in_executor(None, pipeline.verify_and_fill_row, bugid, row)
                        if result["success"]:
                            conf_val = float(row.get("结果置信度", "0") or "0")
                            calc_rootcause = row.get("rootcause", "") or ""
                            calc_comment = row.get("AI评论总结", "") or ""
                            calc_doc_url = row.get("doc_url", "") or ""
                            calc_doc_path = row.get("doc_path", "") or ""
                            is_ready = conf_val >= confidence_threshold
                            extra_sim = result.get("extra_similarity", 0)
                            reason = ""
                            if not is_ready:
                                if extra_sim >= confidence_threshold:
                                    is_ready = True
                                    reason = f"置信度{conf_val}<阈值，语义相似度{extra_sim}≥{confidence_threshold}，视为通过"
                                else:
                                    reason = f"置信度{conf_val}<{confidence_threshold}，语义相似度{extra_sim}<{confidence_threshold}"
                            if is_ready:
                                ready_count += 1
                            else:
                                low_conf_count += 1
                            log_writer.writerow({"jira号": bugid, "rootcause": calc_rootcause[:200],
                                                 "AI评论总结": calc_comment[:200],
                                                 "结果置信度": str(conf_val),
                                                 "达标": "是" if is_ready else "否",
                                                 "原因": "" if is_ready else reason})
                            yield f"data: {_json.dumps({'type': 'progress', 'file_index': file_idx,
                                                        'index': idx + 1, 'total': total, 'bugid': bugid,
                                                        'status': 'success' if is_ready else 'low_confidence',
                                                        'rootcause': calc_rootcause[:80],
                                                        'confidence': str(conf_val),
                                                        'comment_summary': calc_comment,
                                                        'doc_url': calc_doc_url,
                                                        'doc_path': calc_doc_path,
                                                        'msg': '' if is_ready else reason}, ensure_ascii=False)}\n\n"
                        else:
                            err_msg = result.get('error', '')
                            is_skip = '根因分析内容为空' in err_msg
                            log_writer.writerow({"jira号": bugid, "达标": "否", "原因": err_msg[:200]})
                            yield f"data: {_json.dumps({'type': 'progress', 'file_index': file_idx,
                                                        'index': idx + 1, 'total': total, 'bugid': bugid,
                                                        'status': 'skipped' if is_skip else 'fail',
                                                        'rootcause': '', 'confidence': '',
                                                        'comment_summary': '',
                                                        'msg': err_msg}, ensure_ascii=False)}\n\n"
                    except Exception as e:
                        log_writer.writerow({"jira号": bugid, "达标": "否", "原因": str(e)[:200]})
                        yield f"data: {_json.dumps({'type': 'progress', 'file_index': file_idx,
                                                    'index': idx + 1, 'total': total, 'bugid': bugid,
                                                    'status': 'fail', 'rootcause': '', 'confidence': '',
                                                    'comment_summary': '',
                                                    'msg': str(e)[:200]}, ensure_ascii=False)}\n\n"
            yield f"data: {_json.dumps({'type': 'file_done', 'file_index': file_idx,
                                        'file_name': file_name, 'total': total,
                                        'ready': ready_count, 'low_conf': low_conf_count,
                                        'compare_log': compare_log_path, 'csv_path': csv_path}, ensure_ascii=False)}\n\n"
        # 处理直接传入的 jira 号列表
        if bugids:
            file_idx = len(csv_paths)
            file_name = f"jira输入({len(bugids)}个)"
            yield f"data: {_json.dumps({'type': 'file_start', 'file_index': file_idx,
                                        'file_name': file_name, 'file_total': len(csv_paths) + 1}, ensure_ascii=False)}\n\n"
            rows = [{"jira号": b} for b in bugids]
            bugid_col = "jira号"
            confidence_threshold = float(load_config().get("similarity", {}).get("threshold", 0.7))
            # 对比记录文件：docs/日期/jira_input_compare_log.csv
            date_str = datetime.now().strftime("%Y-%m-%d")
            compare_log_dir = os.path.join(get_path("doc_dir"), date_str)
            os.makedirs(compare_log_dir, exist_ok=True)
            compare_log_path = os.path.join(compare_log_dir, "jira_input_compare_log.csv")
            total = len(rows)
            yield f"data: {_json.dumps({'type': 'start', 'file_index': file_idx,
                                        'total': total, 'file_name': file_name}, ensure_ascii=False)}\n\n"
            ready_count = 0
            low_conf_count = 0
            with open(compare_log_path, "w", newline="", encoding="utf-8-sig") as flog:
                log_fields = ["jira号", "rootcause", "AI评论总结", "结果置信度", "达标", "原因"]
                log_writer = _csv.DictWriter(flog, fieldnames=log_fields, extrasaction="ignore")
                log_writer.writeheader()
                for idx, row in enumerate(rows):
                    # 客户端断开时停止验证
                    if await request.is_disconnected():
                        logger.info("verify: 客户端已断开，停止验证 bugid=%s", row.get("jira号", ""))
                        yield f"data: {_json.dumps({'type': 'cancelled', 'file_index': file_idx}, ensure_ascii=False)}\n\n"
                        return
                    bugid = row["jira号"]
                    if bitable_available and bugid not in bitable_success:
                        log_writer.writerow({"jira号": bugid, "达标": "否", "原因": "多维表格中未成功"})
                        yield f"data: {_json.dumps({'type': 'progress', 'file_index': file_idx,
                                                    'index': idx + 1, 'total': total, 'bugid': bugid,
                                                    'status': 'skipped', 'rootcause': '', 'confidence': '',
                                                    'comment_summary': '', 'msg': '多维表格中未成功，已跳过'}, ensure_ascii=False)}\n\n"
                        continue
                    # 从多维表格注入飞书报告链接（jira输入模式无此字段）
                    if not row.get("AI分析结果(飞书链接)") and bugid in bitable_links:
                        row["AI分析结果(飞书链接)"] = bitable_links[bugid]
                    try:
                        result = await loop.run_in_executor(None, pipeline.verify_and_fill_row, bugid, row)
                        if result["success"]:
                            conf_val = float(row.get("结果置信度", "0") or "0")
                            calc_rootcause = row.get("rootcause", "") or ""
                            calc_comment = row.get("AI评论总结", "") or ""
                            calc_doc_url = row.get("doc_url", "") or ""
                            calc_doc_path = row.get("doc_path", "") or ""
                            is_ready = conf_val >= confidence_threshold
                            extra_sim = result.get("extra_similarity", 0)
                            reason = ""
                            if not is_ready:
                                if extra_sim >= confidence_threshold:
                                    is_ready = True
                                    reason = f"置信度{conf_val}<阈值，语义相似度{extra_sim}≥{confidence_threshold}，视为通过"
                                else:
                                    reason = f"置信度{conf_val}<{confidence_threshold}，语义相似度{extra_sim}<{confidence_threshold}"
                            if is_ready:
                                ready_count += 1
                            else:
                                low_conf_count += 1
                            log_writer.writerow({"jira号": bugid, "rootcause": calc_rootcause[:200],
                                                 "AI评论总结": calc_comment[:200],
                                                 "结果置信度": str(conf_val),
                                                 "达标": "是" if is_ready else "否",
                                                 "原因": "" if is_ready else reason})
                            yield f"data: {_json.dumps({'type': 'progress', 'file_index': file_idx,
                                                        'index': idx + 1, 'total': total, 'bugid': bugid,
                                                        'status': 'success' if is_ready else 'low_confidence',
                                                        'rootcause': calc_rootcause[:80],
                                                        'confidence': str(conf_val),
                                                        'comment_summary': calc_comment,
                                                        'doc_url': calc_doc_url,
                                                        'doc_path': calc_doc_path,
                                                        'msg': '' if is_ready else reason}, ensure_ascii=False)}\n\n"
                        else:
                            err_msg = result.get('error', '')
                            is_skip = '根因分析内容为空' in err_msg
                            log_writer.writerow({"jira号": bugid, "达标": "否", "原因": err_msg[:200]})
                            yield f"data: {_json.dumps({'type': 'progress', 'file_index': file_idx,
                                                        'index': idx + 1, 'total': total, 'bugid': bugid,
                                                        'status': 'skipped' if is_skip else 'fail',
                                                        'rootcause': '', 'confidence': '',
                                                        'comment_summary': '',
                                                        'msg': err_msg}, ensure_ascii=False)}\n\n"
                    except Exception as e:
                        log_writer.writerow({"jira号": bugid, "达标": "否", "原因": str(e)[:200]})
                        yield f"data: {_json.dumps({'type': 'progress', 'file_index': file_idx,
                                                    'index': idx + 1, 'total': total, 'bugid': bugid,
                                                    'status': 'fail', 'rootcause': '', 'confidence': '',
                                                    'comment_summary': '',
                                                    'msg': str(e)[:200]}, ensure_ascii=False)}\n\n"
            yield f"data: {_json.dumps({'type': 'file_done', 'file_index': file_idx,
                                        'file_name': file_name, 'total': total,
                                        'ready': ready_count, 'low_conf': low_conf_count,
                                        'compare_log': compare_log_path, 'csv_path': ''}, ensure_ascii=False)}\n\n"
        yield f"data: {_json.dumps({'type': 'all_done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/verify_write")
async def verify_write(request: Request):
    """将验证通过的记录写入指定 CSV 文件的三个字段（AI评论总结、rootcause、结果置信度）"""
    import csv as _csv
    body = await request.json() or {}
    csv_path = str(body.get("csv_path", "")).strip()
    items = body.get("items") or []  # [{"bugid": str, "rootcause": str, "comment_summary": str, "confidence": str}]
    if not csv_path or not os.path.isfile(csv_path):
        return _fail(f"文件不存在: {csv_path}")
    if not items:
        return _fail("无待写入的记录")
    # 读取原始 CSV
    rows = _read_csv_rows(csv_path)
    if not rows:
        return _fail("CSV 为空")
    # 识别 bugid 列
    bugid_col = None
    for col in ["jira号", "bugid", "key", "issue_key", "Bug ID"]:
        if col in rows[0]:
            bugid_col = col
            break
    if not bugid_col:
        for c in rows[0].keys():
            if "jira" in c.lower() or "bug" in c.lower():
                bugid_col = c
                break
    if not bugid_col:
        return _fail("无法识别 bugid 列")
    # 构建待写入映射
    write_map = {}
    for item in items:
        bugid = str(item.get("bugid", "")).strip()
        if bugid:
            write_map[bugid] = item
    # 更新匹配行
    written = []
    for row in rows:
        row_bugid = str(row.get(bugid_col, "")).strip()
        if row_bugid in write_map:
            item = write_map[row_bugid]
            row["rootcause"] = item.get("rootcause", "")
            row["AI评论总结"] = item.get("comment_summary", "")
            row["结果置信度"] = item.get("confidence", "")
            written.append(row_bugid)
    # 写回 CSV
    fieldnames = list(rows[0].keys())
    for f in ["AI评论总结", "rootcause", "结果置信度"]:
        if f not in fieldnames:
            fieldnames.append(f)
    try:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fout:
            writer = _csv.DictWriter(fout, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    except Exception as e:
        return _fail(f"写入失败: {e}")
    return _ok({"written": written, "count": len(written)}, f"已写入 {len(written)} 条记录")


def _find_comment_doc(bugid: str) -> str:
    """在 docs/日期/ 中查找最新的 {bugid}_comments.md，返回内容；未找到返回空串"""
    try:
        doc_dir = get_path("doc_dir")
        for day in sorted(os.listdir(doc_dir), reverse=True):
            path = os.path.join(doc_dir, day, f"{bugid}_comments.md")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
    except Exception:
        pass
    return ""


@app.get("/api/verify_bitable_eligible")
async def verify_bitable_eligible():
    """查询多维表格中“分析结果=成功”且“结果置信度”为空的 jira 号集合"""
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
        eligible = set()  # 分析结果=成功 且 结果置信度为空
        for rec in records:
            fields = rec.get("fields", {})
            jira_key = fields.get(bugid_field, "")
            if isinstance(jira_key, list):
                jira_key = "".join(str(v) for v in jira_key)
            jira_key = str(jira_key).strip()
            if not jira_key:
                continue
            result_status = str(fields.get("分析结果", "")).strip()
            conf_val = fields.get("结果置信度", "")
            # 数字字段可能是 0 或 None
            conf_empty = (conf_val is None or conf_val == "" or conf_val == 0 or str(conf_val).strip() in ("", "0", "0.0"))
            if result_status == "成功" and conf_empty:
                eligible.add(jira_key)
        logger.info("多维表格可写入置信度的记录: %d 条", len(eligible))
        return _ok({"eligible": list(eligible), "count": len(eligible)}, f"可写入 {len(eligible)} 条")
    except Exception as e:
        return _fail(f"查询多维表格失败: {e}")


@app.post("/api/verify_write_bitable")
async def verify_write_bitable(request: Request):
    """将验证通过的记录写入多维表格的三个字段（AI评论总结、rootcause、结果置信度）"""
    from src.clients import feishu_client
    body = await request.json() or {}
    items = body.get("items") or []  # [{"bugid": str, "rootcause": str, "comment_summary": str, "confidence": str}]
    if not items:
        return _fail("无待写入的记录")
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    # Wiki 模式：通过 wiki_token 获取实际 app_token
    if not app_token and cfg.get("wiki_token"):
        try:
            if feishu_client._is_cookie_mode():
                app_token = feishu_client.cookie_get_app_token_from_wiki(cfg["wiki_token"])
            else:
                app_token = feishu_client.get_wiki_node_app_token(cfg["wiki_token"])
        except Exception as e:
            return _fail(f"Wiki token 转换失败: {e}")
    try:
        # 获取多维表格字段定义，构建中文名 → 字段名映射和字段类型映射
        field_defs = feishu_client.list_bitable_fields(app_token, table_id)
        field_name_map = {fd.get("field_name", ""): fd.get("field_name", "") for fd in field_defs}
        field_type_map = {fd.get("field_name", ""): fd.get("type", 0) for fd in field_defs}
        logger.info("多维表格字段列表: %s", [(fd.get("field_name"), fd.get("type")) for fd in field_defs])
        # 构建待写入字段名（优先精确匹配，回退常见别名，字段不存在则跳过）
        rc_field = field_name_map.get("rootcause") or field_name_map.get("Rootcause") or field_name_map.get("RootCause") or ""
        cs_field = field_name_map.get("AI评论总结") or field_name_map.get("评论总结") or ""
        cf_field = field_name_map.get("结果置信度") or field_name_map.get("置信度") or ""
        hr_field = field_name_map.get("人工审核结果") or field_name_map.get("人工审核") or ""
        if not rc_field and not cs_field and not cf_field and not hr_field:
            logger.error("多维表格未找到任何目标字段，实际字段: %s", list(field_name_map.keys()))
            return _fail("多维表格中未找到 rootcause/AI评论总结/结果置信度/人工审核结果 字段")
        # 获取多维表格所有记录，构建 bugid → record_id 映射
        records = feishu_client.list_bitable_records(app_token, table_id)
        bugid_to_record = {}
        for rec in records:
            fields = rec.get("fields", {})
            field_value = fields.get(bugid_field, "")
            if isinstance(field_value, list):
                field_value = "".join(str(v) for v in field_value)
            field_value = str(field_value).strip()
            if field_value:
                bugid_to_record[field_value] = rec.get("record_id", "")
        # 构建待更新记录
        update_records = []
        not_found = []
        for item in items:
            bugid = str(item.get("bugid", "")).strip()
            record_id = bugid_to_record.get(bugid)
            if not record_id:
                not_found.append(bugid)
                continue
            # 清理 markdown 格式符号后再写入表格
            from src.core import filter as comment_filter
            cleaned_comment = comment_filter._clean_table_text(item.get("comment_summary", ""))
            # 去掉文本中已嵌入的 [详情: xxx] 链接（避免与 doc_url 重复）
            cleaned_comment = re.sub(r'\s*\[详情:\s*[^\]]+\]', '', cleaned_comment).strip()
            doc_url = item.get("doc_url", "")
            doc_path = item.get("doc_path", "")
            # AI评论总结：检查字段类型，URL字段(type=15)必须用dict格式
            cs_field_type = field_type_map.get(cs_field, 0)
            if cs_field_type == 15:
                # URL字段：无doc_url时优先上传本地md文件到云盘，回退创建飞书在线文档
                if not doc_url:
                    # 优先上传本地评论分析文档到云盘
                    if doc_path and os.path.isfile(doc_path):
                        try:
                            upload_result = feishu_client.upload_md_to_drive(doc_path, title=f"{bugid} 评论分析总结")
                            doc_url = upload_result.get("url", "")
                            if doc_url:
                                logger.info("%s 写入时上传本地文档到云盘: %s", bugid, doc_url)
                        except Exception as e:
                            logger.warning("%s 上传本地文档到云盘失败: %s", bugid, e)
                    # 回退：创建飞书在线文档
                    if not doc_url and cleaned_comment:
                        try:
                            doc_title = f"{bugid} AI评论总结"
                            doc_content = _find_comment_doc(bugid) or cleaned_comment
                            doc_result = feishu_client.create_docx_document(doc_title, doc_content)
                            doc_url = doc_result.get("url", "")
                            if doc_url:
                                logger.info("%s 自动创建在线文档: %s", bugid, doc_url)
                        except Exception as e:
                            logger.warning("%s 创建在线文档失败: %s", bugid, e)
                if doc_url:
                    cs_value = {"link": doc_url, "text": cleaned_comment}
                elif cleaned_comment:
                    # URL字段必须用dict格式，无链接时跳过该字段写入
                    cs_value = None
                else:
                    cs_value = None
            elif doc_url:
                cs_value = f"{cleaned_comment} {doc_url}" if cleaned_comment else doc_url
            else:
                # 非URL字段：无doc_url时也尝试上传本地文件获取链接
                if not doc_url and doc_path and os.path.isfile(doc_path):
                    try:
                        upload_result = feishu_client.upload_md_to_drive(doc_path, title=f"{bugid} 评论分析总结")
                        doc_url = upload_result.get("url", "")
                    except Exception:
                        pass
                cs_value = f"{cleaned_comment} {doc_url}" if (cleaned_comment and doc_url) else (doc_url or cleaned_comment)
            # 只写入多维表格中实际存在的字段
            fields_to_write = {}
            if rc_field:
                fields_to_write[rc_field] = comment_filter._clean_table_text(item.get("rootcause", ""))
            if cs_field:
                if cs_value is not None:
                    fields_to_write[cs_field] = cs_value
            if cf_field:
                # 结果置信度：数字字段(type=2)转为 float，文本字段保持字符串
                conf_raw = item.get("confidence", "")
                cf_field_type = field_type_map.get(cf_field, 0)
                if cf_field_type == 2:  # 数字类型
                    try:
                        fields_to_write[cf_field] = float(conf_raw) if conf_raw else 0
                    except (ValueError, TypeError):
                        fields_to_write[cf_field] = 0
                else:
                    fields_to_write[cf_field] = str(conf_raw)
            # 人工审核结果：仅当传入 human_reason 且非空时写入
            if hr_field:
                hr_value = item.get("human_reason", "")
                if hr_value:
                    fields_to_write[hr_field] = str(hr_value)
            update_records.append({
                "record_id": record_id,
                "fields": fields_to_write
            })
        if update_records:
            logger.info("待写入 bitable 首条记录: %s", update_records[0] if update_records else "")
            feishu_client.update_bitable_records(app_token, table_id, update_records)
        result = {"written": [r["record_id"] for r in update_records],
                  "count": len(update_records), "not_found": not_found}
        msg = f"已写入 {len(update_records)} 条记录"
        if not_found:
            msg += f"，{len(not_found)} 条未找到"
        return _ok(result, msg)
    except Exception as e:
        logger.error("写入多维表格失败: %s", e, exc_info=True)
        return _fail(f"写入多维表格失败: {e}")


@app.post("/api/test/bitable_write")
async def test_bitable_write(request: Request):
    """测试接口：多维表格模拟写入（支持dry-run预览），不传bugid时返回全量记录"""
    from src.clients import feishu_client
    from src.core import filter as comment_filter
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    dry_run = bool(body.get("dry_run", False))

    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")

    try:
        # 获取字段定义
        field_defs = feishu_client.list_bitable_fields(app_token, table_id)
        field_name_map = {fd.get("field_name", ""): fd.get("field_name", "") for fd in field_defs}
        field_type_map = {fd.get("field_name", ""): fd.get("type", 0) for fd in field_defs}

        # 无 bugid 时：返回全量记录（供数据看板展示）
        if not bugid:
            records = feishu_client.list_bitable_records(app_token, table_id)
            result_rows = []
            for rec in records:
                fields = rec.get("fields", {})
                flat = {"record_id": rec.get("record_id", "")}
                for key, val in fields.items():
                    if isinstance(val, dict) and "link" in val:
                        flat[key] = val.get("text", "")
                    elif isinstance(val, list):
                        flat[key] = " ".join(str(v) for v in val)
                    else:
                        flat[key] = str(val) if val is not None else ""
                result_rows.append(flat)
            field_names = [fd.get("field_name", "") for fd in field_defs]
            return _ok({
                "records": result_rows,
                "field_names": field_names,
                "field_types": field_type_map,
                "count": len(result_rows)
            })

        rc_field = field_name_map.get("rootcause") or field_name_map.get("Rootcause") or ""
        cs_field = field_name_map.get("AI评论总结") or field_name_map.get("评论总结") or ""
        cf_field = field_name_map.get("结果置信度") or field_name_map.get("置信度") or ""

        # 获取记录
        records = feishu_client.list_bitable_records(app_token, table_id)
        bugid_to_record = {}
        for rec in records:
            fields = rec.get("fields", {})
            field_value = fields.get(bugid_field, "")
            if isinstance(field_value, list):
                field_value = "".join(str(v) for v in field_value)
            field_value = str(field_value).strip()
            if field_value:
                bugid_to_record[field_value] = rec.get("record_id", "")

        record_id = bugid_to_record.get(bugid)
        if not record_id:
            return _fail(f"未找到 bugid={bugid} 对应的记录")

        # 构建写入值
        rootcause = str(body.get("rootcause", ""))
        comment_summary = str(body.get("comment_summary", ""))
        confidence = body.get("confidence", "")
        doc_url = str(body.get("doc_url", ""))

        cleaned_comment = comment_filter._clean_table_text(comment_summary)
        cleaned_comment = re.sub(r'\s*\[详情:\s*[^\]]+\]', '', cleaned_comment).strip()

        fields_to_write = {}
        field_types = {}
        if rc_field:
            fields_to_write[rc_field] = comment_filter._clean_table_text(rootcause)
            field_types[rc_field] = field_type_map.get(rc_field, 0)
        if cs_field:
            cs_field_type = field_type_map.get(cs_field, 0)
            field_types[cs_field] = cs_field_type
            if cs_field_type == 15:
                # URL字段：无doc_url时自动创建飞书在线文档并获取链接
                if not doc_url and cleaned_comment:
                    try:
                        doc_title = f"{bugid} AI评论总结"
                        doc_content = _find_comment_doc(bugid) or cleaned_comment
                        doc_result = feishu_client.create_docx_document(doc_title, doc_content)
                        doc_url = doc_result.get("url", "")
                    except Exception as e:
                        logger.warning("创建在线文档失败: %s", e)
                if doc_url:
                    fields_to_write[cs_field] = {"link": doc_url, "text": cleaned_comment}
                # 无链接时跳过该字段，避免 URLFieldConvFail
            elif doc_url:
                fields_to_write[cs_field] = f"{cleaned_comment} {doc_url}" if cleaned_comment else doc_url
            else:
                fields_to_write[cs_field] = cleaned_comment
        if cf_field:
            cf_field_type = field_type_map.get(cf_field, 0)
            field_types[cf_field] = cf_field_type
            if cf_field_type == 2:
                try:
                    fields_to_write[cf_field] = float(confidence) if confidence else 0
                except (ValueError, TypeError):
                    fields_to_write[cf_field] = 0
            else:
                fields_to_write[cf_field] = str(confidence)

        update_records = [{"record_id": record_id, "fields": fields_to_write}]

        if dry_run:
            return _ok({
                "record_id": record_id,
                "fields": fields_to_write,
                "field_types": field_types,
                "dry_run": True
            }, "模拟写入成功，未实际发送")

        feishu_client.update_bitable_records(app_token, table_id, update_records)
        return _ok({
            "record_id": record_id,
            "fields": fields_to_write,
            "field_types": field_types,
            "dry_run": False
        }, f"写入成功: bugid={bugid}")
    except Exception as e:
        logger.error("多维表格模拟写入失败: %s", e, exc_info=True)
        return _fail(f"写入失败: {e}")


@app.post("/api/test/jira_raw")
async def test_jira_raw(request: Request):
    """功能测试5：Jira 接口原始返回字段验证，调用 Jira API 并返回完整响应内容"""
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("请输入 bugid")
    try:
        cfg = load_config()["jira_api"]
        is_mock = cfg.get("mock", False)
        # 调用 Jira 接口获取完整响应
        raw_response = jira_client.fetch_issue(bugid)
        # 提取当前已使用的字段值，便于对比
        extracted = {
            "description": jira_client.extract_error_cause(raw_response),
            "rootcause": jira_client.extract_rootcause(raw_response),
            "comments": jira_client.extract_comments(raw_response),
        }
        # 列出 fields 下所有可用字段名及其值类型，帮助判断哪些字段有用
        fields_keys = []
        fields = raw_response.get("fields") or {}
        for k, v in fields.items():
            val_type = type(v).__name__
            preview = str(v)[:100] if v is not None else "null"
            fields_keys.append({"key": k, "type": val_type, "preview": preview})
        return _ok({
            "raw_response": raw_response,
            "extracted": extracted,
            "fields_keys": fields_keys,
            "is_mock": is_mock,
            "api_url": cfg.get("url", ""),
        }, f"Jira 接口返回成功（{'mock' if is_mock else '真实'}模式），fields 共 {len(fields_keys)} 个字段")
    except Exception as e:
        logger.error("Jira 接口测试失败: %s", e)
        return _fail(str(e))


@app.post("/api/test/trigger_time")
async def test_trigger_time(request: Request):
    """功能测试：触发时间提取，优先读云端已有数据，无记录再从 Jira 提取"""
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("请输入 bugid")
    try:
        # 优先从云端读取已有触发时间
        cloud_times = _load_trigger_times_from_cloud()
        cached_time = cloud_times.get(bugid, "")
        if cached_time:
            return _ok({
                "trigger_time": cached_time,
                "comment_count": 0,
                "source": "cloud",
            }, f"云端已有触发时间: {cached_time}")
        # 云端无记录，从 Jira 提取
        issue = jira_client.fetch_issue(bugid)
        trigger_time = jira_client.extract_trigger_time_from_issue(issue)
        if not trigger_time:
            return _fail("提取失败，评论区未获取到时间内容")
        # 提取成功后保存到云端+本地
        _save_trigger_time_to_cloud(bugid, trigger_time)
        comments = jira_client.extract_comments(issue)
        return _ok({
            "trigger_time": trigger_time,
            "comment_count": len(comments),
            "source": "jira",
        }, f"Jira提取成功，从 {len(comments)} 条评论中提取到触发时间")
    except Exception as e:
        logger.error("触发时间提取失败: %s", e)
        return _fail(str(e))


@app.post("/api/trigger_time/batch_read")
async def batch_read_trigger_times(request: Request):
    """批量读取指定 jira 号的当前触发时间：优先本地缓存，无记录则从 Jira 提取并保存"""
    body = await request.json() or {}
    bugids = body.get("bugids") or []
    if not bugids:
        return _fail("请输入 jira 号列表")
    local_times = _load_trigger_times_from_cloud()
    result = []
    extracted_count = 0
    batch_to_cloud = {}  # 循环后批量上传
    for bugid in bugids:
        bugid = bugid.strip()
        if not bugid:
            continue
        current_time = local_times.get(bugid, "")
        if not current_time:
            # 本地无记录，从 Jira 提取
            try:
                from src.clients import jira_client as _jc
                loop = asyncio.get_event_loop()
                issue = await loop.run_in_executor(None, _jc.fetch_issue, bugid)
                tt = await loop.run_in_executor(None, _jc.extract_trigger_time_from_issue, issue)
                if tt:
                    current_time = tt
                    _save_trigger_time_to_csv(bugid, tt)
                    batch_to_cloud[bugid] = tt
                    extracted_count += 1
            except Exception as e:
                logger.warning("批量读取触发时间-提取失败 %s: %s", bugid, e)
        result.append({
            "bugid": bugid,
            "current_time": current_time
        })
    # 一次性批量上传到云端
    if batch_to_cloud:
        _batch_save_trigger_times_to_cloud(batch_to_cloud)
    hit_count = sum(1 for r in result if r["current_time"])
    return _ok({"rows": result, "total": len(result), "hit": hit_count},
               f"查询完成：{len(result)} 个 Jira 号，{hit_count} 个有记录（本地命中 {hit_count - extracted_count}，新提取 {extracted_count}）")


@app.post("/api/trigger_time/update")
async def update_trigger_time(request: Request):
    """修改指定bugid的触发时间，直接更新云端 bitable"""
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    new_time = str(body.get("new_time", "")).strip()
    if not bugid:
        return _fail("请输入 bugid/jira号")
    if not new_time:
        return _fail("请输入新的触发时间")
    try:
        _save_trigger_time_to_cloud(bugid, new_time)
        # 同步更新诊断缓存的 verify_status，避免被重新扫描为待提取
        cached = _load_diagnose_cache(bugid)
        if cached:
            cached["verify_status"] = "corrected"
            cached["suggested_time"] = new_time
            _save_diagnose_cache(bugid, cached)
        msg = f"已更新 {bugid} 的触发时间为 {new_time}（云端+本地+诊断缓存）"
        return _ok({"bugid": bugid, "new_time": new_time, "updated": True}, msg)
    except Exception as e:
        logger.warning("更新触发时间失败 %s: %s", bugid, e)
        return _fail(f"更新失败: {e}")


@app.post("/api/trigger_time/batch_update")
async def batch_update_trigger_time(request: Request):
    """批量应用修正时间：一次性写入云端+一次性更新诊断缓存"""
    body = await request.json() or {}
    items = body.get("items") or []  # [{bugid, new_time}]
    if not items:
        return _fail("待应用列表为空")
    # 过滤有效项，排除已修正的记录
    valid_items = {}  # {bugid: new_time}
    skip_corrected = 0
    for item in items:
        bugid = str(item.get("bugid", "")).strip()
        new_time = str(item.get("new_time", "")).strip()
        if not bugid or not new_time:
            continue
        # 检查诊断缓存，跳过已修正的
        cached = _load_diagnose_cache(bugid)
        if cached and cached.get("verify_status") == "corrected":
            skip_corrected += 1
            continue
        valid_items[bugid] = new_time
    if not valid_items:
        msg = "无待应用记录"
        if skip_corrected:
            msg += f"（已修正跳过 {skip_corrected} 条）"
        return _fail(msg)
    # 一次性批量写入云端（只加载一次表数据）
    cloud_ok = _batch_save_trigger_times_to_cloud(valid_items)
    if not cloud_ok:
        return _fail("云端写入失败")
    # 一次性更新所有诊断缓存
    cache_updated = 0
    for bugid, new_time in valid_items.items():
        cached = _load_diagnose_cache(bugid)
        if cached:
            cached["verify_status"] = "corrected"
            cached["suggested_time"] = new_time
            _save_diagnose_cache(bugid, cached)
            cache_updated += 1
    success = len(valid_items)
    msg = f"批量应用完成：成功 {success} 条"
    if skip_corrected:
        msg += f"，已修正跳过 {skip_corrected} 条"
    return _ok({"success": success, "failed": 0, "skip_corrected": skip_corrected}, msg)


@app.post("/api/trigger_time/re_extract_scan")
async def re_extract_scan(request: Request):
    """扫描云端触发时间记录，找出触发时间为空的候选项

    :param cache_only: True=仅查看缓存（不查询Jira状态），False=查询Jira状态过滤非Closed
    """
    body = await request.json() or {}
    cache_only = body.get("cache_only", False)
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        all_records = await loop.run_in_executor(None, _load_all_cloud_trigger_records)
        # 筛选触发时间为空的记录
        empty_records = [r for r in all_records if not r["trigger_time"]]
        if not empty_records:
            return _ok({"candidates": [], "total_empty": 0, "total_cloud": len(all_records)},
                       "云端所有记录均已提取到触发时间")
        if cache_only:
            # 仅查看缓存：不查询Jira，直接返回所有空记录
            candidates = [{"bugid": r["jira_no"], "jira_status": "", "table_id": r["table_id"], "record_id": r["record_id"]} for r in empty_records]
            return _ok({"candidates": candidates, "total_empty": len(empty_records), "total_cloud": len(all_records)},
                       f"缓存扫描完成: 云端共 {len(all_records)} 条，触发时间为空 {len(candidates)} 条")
        # 查询 Jira 状态，筛选非 Closed 的
        from src.clients import jira_client as _jc
        candidates = []
        for i, rec in enumerate(empty_records):
            if await request.is_disconnected():
                logger.info("客户端已断开，扫描中断（已完成 %d/%d）", i, len(empty_records))
                break
            await asyncio.sleep(0)
            try:
                issue = await loop.run_in_executor(None, _jc.fetch_issue, rec["jira_no"])
                status = ((issue.get("fields") or {}).get("status") or {}).get("name", "")
                if status.lower() != "closed":
                    candidates.append({"bugid": rec["jira_no"], "jira_status": status, "table_id": rec["table_id"], "record_id": rec["record_id"]})
            except Exception as e:
                logger.warning("扫描 Jira 状态失败 %s: %s", rec["jira_no"], e)
                candidates.append({"bugid": rec["jira_no"], "jira_status": f"查询失败: {e}", "table_id": rec["table_id"], "record_id": rec["record_id"]})
        return _ok({"candidates": candidates, "total_empty": len(empty_records), "total_cloud": len(all_records)},
                    f"扫描完成: 云端共 {len(all_records)} 条，空触发时间 {len(empty_records)} 条，可重新提取（非 Closed）{len(candidates)} 条")
    except Exception as e:
        logger.error("重新提取扫描失败: %s", e)
        return _fail(f"扫描失败: {e}")


@app.post("/api/trigger_time/re_extract")
async def re_extract(request: Request):
    """对指定的 bugid 列表重新提取触发时间（视频优先）并更新云端，失败不变更"""
    body = await request.json() or {}
    bugids = body.get("bugids") or []
    if not bugids:
        return _fail("待重新提取列表为空")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        from src.clients import jira_client as _jc
        results = []
        for i, bugid in enumerate(bugids):
            if await request.is_disconnected():
                logger.info("客户端已断开，重新提取中断（已完成 %d/%d）", i, len(bugids))
                break
            await asyncio.sleep(0)
            try:
                issue = await loop.run_in_executor(None, _jc.fetch_issue, bugid)
                # 视频优先提取
                tt = await loop.run_in_executor(None, _diag_extract_time_from_video_simple, issue)
                if not tt:
                    tt = await loop.run_in_executor(None, _jc.extract_trigger_time_from_issue, issue)
                status = ((issue.get("fields") or {}).get("status") or {}).get("name", "")
                if tt:
                    # 成功：更新云端，去掉空标记
                    await loop.run_in_executor(None, _save_trigger_time_to_cloud, bugid, tt)
                    results.append({"bugid": bugid, "trigger_time": tt, "status": status, "success": True})
                else:
                    # 失败：不变更云端空标记
                    results.append({"bugid": bugid, "trigger_time": "", "status": status, "success": False, "error": "未提取到时间"})
            except Exception as e:
                results.append({"bugid": bugid, "trigger_time": "", "success": False, "error": str(e)})
                logger.warning("重新提取失败 %s: %s", bugid, e)
        success_count = sum(1 for r in results if r["success"])
        return _ok({"results": results, "success_count": success_count, "total": len(bugids)},
                    f"重新提取完成: {success_count}/{len(bugids)} 成功")
    except Exception as e:
        logger.error("重新提取失败: %s", e)
        return _fail(f"重新提取失败: {e}")


@app.post("/api/trigger_time/cache_batch_scan")
async def cache_batch_scan(request: Request):
    """云端缓存批量更新：扫描需要重新提取触发时间的候选记录

    过滤逻辑：
    1. exclude_bitable_success: 排除多维表格中分析结果=成功的记录
    2. exclude_corrected: 排除报错分析中触发时间问题已修正的记录
    最终结果 = 云端有时间的记录 - 已成功 - 已修正
    """
    body = await request.json() or {}
    exclude_bitable_success = body.get("exclude_bitable_success", False)
    exclude_corrected = body.get("exclude_corrected", False)
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        # 加载云端全量触发时间记录
        all_records = await loop.run_in_executor(None, _load_all_cloud_trigger_records)
        total_cloud = len(all_records)
        # 只保留有触发时间的记录（这些是已缓存的）
        cached_records = [r for r in all_records if r["trigger_time"]]
        total_cached = len(cached_records)
        # 构建 jira 号到记录的映射（去重，保留最新的）
        jira_map = {}
        for r in cached_records:
            jira_map[r["jira_no"]] = r
        # 排除集合
        bitable_success_keys = set()
        corrected_keys = set()
        # 过滤1：排除多维表格中分析结果=成功的
        if exclude_bitable_success:
            try:
                from src.clients import feishu_client
                cfg = load_config().get("feishu_bitable", {})
                records = await loop.run_in_executor(
                    None, feishu_client.list_bitable_records,
                    cfg.get("app_token", ""), cfg.get("table_id", ""))
                bf = cfg.get("bugid_field", "jira号")
                for rec in records:
                    fields = rec.get("fields", {})
                    jk = _bitable_text(fields.get(bf, ""))
                    result_status = str(fields.get("分析结果", "")).strip()
                    if jk and result_status == "成功":
                        bitable_success_keys.add(jk)
                logger.info("云端缓存批量扫描: 多维表格已成功 %d 条", len(bitable_success_keys))
            except Exception as e:
                logger.warning("云端缓存批量扫描: 多维表格查询失败: %s", e)
        # 回溯标记：之前点击“应用”但未标记 verify_status 的记录
        applied_tagged = 0
        # 方式1：从多维表格中查找“时间添加为”的人工审核记录
        time_corrected_jiras = set()
        try:
            from src.clients import feishu_client
            cfg = load_config().get("feishu_bitable", {})
            if cfg.get("app_token") and cfg.get("table_id"):
                bt_records = await loop.run_in_executor(
                    None, feishu_client.list_bitable_records,
                    cfg["app_token"], cfg["table_id"])
                bf = cfg.get("bugid_field", "jira号")
                for rec in bt_records:
                    fields = rec.get("fields", {})
                    review = _bitable_text(fields.get("人工审核结果", ""))
                    if "时间添加为" in review or "时间异常" in review:
                        jk = _bitable_text(fields.get(bf, ""))
                        if jk:
                            time_corrected_jiras.add(jk)
                if time_corrected_jiras:
                    logger.info("回溯标记: 多维表格中“时间添加为/时间异常” %d 条", len(time_corrected_jiras))
        except Exception as e:
            logger.warning("回溯标记: 多维表格查询失败: %s", e)
        # 方式2：遍历诊断缓存，匹配云端时间=建议时间 或 多维表格“时间添加为”
        cache_dir = os.path.join(PROJECT_ROOT, "data", "troubleshoot")
        if os.path.isdir(cache_dir):
            for fname in os.listdir(cache_dir):
                if not fname.endswith(".json"):
                    continue
                try:
                    fpath = os.path.join(cache_dir, fname)
                    with open(fpath, "r", encoding="utf-8") as f:
                        cached = _json.load(f)
                    vs = cached.get("verify_status", "")
                    if vs in ("corrected", "success"):
                        continue  # 已标记，跳过
                    bugid = cached.get("bugid", fname[:-5])
                    should_tag = False
                    # 条件1：云端时间已等于建议时间（之前点过应用）
                    st = cached.get("suggested_time", "")
                    if st and bugid in jira_map and jira_map[bugid]["trigger_time"] == st:
                        should_tag = True
                    # 条件2：多维表格中人工审核为“时间添加为”或“时间异常”
                    if not should_tag and bugid in time_corrected_jiras:
                        should_tag = True
                    if should_tag:
                        cached["verify_status"] = "corrected"
                        with open(fpath, "w", encoding="utf-8") as f:
                            _json.dump(cached, f, ensure_ascii=False, indent=2)
                        corrected_keys.add(bugid)
                        applied_tagged += 1
                except Exception:
                    pass
            if applied_tagged:
                logger.info("云端缓存批量扫描: 回溯标记已应用记录 %d 条", applied_tagged)
        # 过滤2：排除报错分析中触发时间问题已修正/已确认的记录
        # verify_status=corrected: 用户手动修正了时间
        # verify_status=success: 系统建议时间被确认为正确
        # 这两种都说明时间已经过人工确认，无需重新提取
        if exclude_corrected:
            cache_dir = os.path.join(PROJECT_ROOT, "data", "troubleshoot")
            if os.path.isdir(cache_dir):
                for fname in os.listdir(cache_dir):
                    if not fname.endswith(".json"):
                        continue
                    try:
                        fpath = os.path.join(cache_dir, fname)
                        with open(fpath, "r", encoding="utf-8") as f:
                            cached = _json.load(f)
                        vs = cached.get("verify_status", "")
                        if vs in ("corrected", "success"):
                            corrected_keys.add(cached.get("bugid", fname[:-5]))
                    except Exception:
                        pass
            logger.info("云端缓存批量扫描: 已修正/已确认 %d 条", len(corrected_keys))
        # 过滤：云端有缓存 - 多维表格已成功 - 本地已修正
        exclude_all = bitable_success_keys | corrected_keys
        candidates = []
        for jira_no, rec in jira_map.items():
            if jira_no not in exclude_all:
                candidates.append({
                    "bugid": jira_no,
                    "current_time": rec["trigger_time"],
                    "table_id": rec["table_id"],
                    "record_id": rec["record_id"],
                })
        msg_parts = [f"云端有缓存: {total_cached}"]
        if exclude_bitable_success:
            msg_parts.append(f"多维表格已成功排除: {len(bitable_success_keys)}")
        if exclude_corrected:
            msg_parts.append(f"已修正排除: {len(corrected_keys)}" + (f"（含回溯标记 {applied_tagged}）" if applied_tagged else ""))
        msg_parts.append(f"待重新提取: {len(candidates)}")
        return _ok({
            "candidates": candidates,
            "total_cloud": total_cloud,
            "total_cached": total_cached,
            "bitable_success_count": len(bitable_success_keys),
            "corrected_count": len(corrected_keys),
        }, "、".join(msg_parts))
    except Exception as e:
        logger.error("云端缓存批量扫描失败: %s", e)
        return _fail(f"扫描失败: {e}")


@app.post("/api/trigger_time/cache_batch_extract/stop")
async def stop_cache_batch_extract():
    """触发云端缓存批量提取停止信号（当前条目完成后停止后续）"""
    _cache_batch_stop_event.set()
    logger.info("收到云端缓存批量提取停止信号，当前条目完成后将停止后续处理")
    return {"status": "ok", "message": "停止信号已发送，当前条目完成后停止"}


# 云端缓存批量提取本地进度文件路径
_CACHE_BATCH_PROGRESS_FILE = os.path.join(PROJECT_ROOT, "data", "cache_batch_progress.json")


def _load_cache_batch_progress() -> dict:
    """加载本地缓存批量提取进度，返回 {bugid: {time, source, status}}"""
    try:
        if os.path.exists(_CACHE_BATCH_PROGRESS_FILE):
            with open(_CACHE_BATCH_PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = _json.load(f)
            logger.info("加载本地缓存批量进度: %d 条记录", len(data))
            return data
    except Exception as e:
        logger.warning("加载本地缓存批量进度失败: %s", e)
    return {}


def _save_cache_batch_progress(progress: dict):
    """保存缓存批量提取进度到本地文件"""
    try:
        os.makedirs(os.path.dirname(_CACHE_BATCH_PROGRESS_FILE), exist_ok=True)
        with open(_CACHE_BATCH_PROGRESS_FILE, "w", encoding="utf-8") as f:
            _json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("保存本地缓存批量进度失败: %s", e)


@app.post("/api/trigger_time/cache_batch_load_progress")
def cache_batch_load_progress():
    """加载本地缓存批量提取进度"""
    data = _load_cache_batch_progress()
    return _ok({"progress": data}, f"本地进度: {len(data)} 条记录")


@app.post("/api/trigger_time/cache_batch_clear_progress")
def cache_batch_clear_progress():
    """清除本地缓存批量提取进度"""
    try:
        if os.path.exists(_CACHE_BATCH_PROGRESS_FILE):
            os.remove(_CACHE_BATCH_PROGRESS_FILE)
        return _ok({}, "本地进度已清除")
    except Exception as e:
        return _fail(f"清除失败: {e}")


@app.post("/api/trigger_time/cache_batch_extract")
async def cache_batch_extract(request: Request):
    """云端缓存批量更新：SSE 流式推送进度，重新提取触发时间

    :param video_first: True=视频优先，False=标准提取优先
    :param old_times: {bugid: current_time} 用于对比
    提取后与缓存对比，误差 1 分钟内视为未变化。每条结果存入本地进度文件。
    """
    import asyncio
    import json as _json
    body = await request.json() or {}
    bugids = body.get("bugids") or []
    old_times = body.get("old_times") or {}  # {bugid: current_time} 用于对比
    video_first = body.get("video_first", True)  # 视频提取优先
    if not bugids:
        return _fail("待提取列表为空")

    async def event_generator():
        loop = asyncio.get_event_loop()
        from src.clients import jira_client as _jc
        _cache_batch_stop_event.clear()  # 新批次开始时清除停止标志
        # 加载本地进度缓存，已处理过的直接跳过
        local_progress = _load_cache_batch_progress()
        # 将所有候选 bugid 预先写入进度文件（status=pending）
        # 这样即使中断/崩溃，pending 项下次会被重新提取，已完成项被跳过
        new_items = 0
        for bugid in bugids:
            if bugid not in local_progress:
                local_progress[bugid] = {"time": "", "source": "", "status": "pending"}
                new_items += 1
            elif local_progress[bugid].get("status") == "pending":
                # 上次中断的 pending 项，继续提取
                new_items += 1
        if new_items:
            _save_cache_batch_progress(local_progress)
        # 统计已完成的项（非 pending）
        completed_count = sum(1 for b in bugids if b in local_progress and local_progress[b].get("status") != "pending")
        total = len(bugids)
        yield f"data: {_json.dumps({'type': 'start', 'total': total, 'cached': completed_count, 'pending': new_items}, ensure_ascii=False)}\n\n"
        done_count = 0
        updated = 0
        unchanged = 0
        empty = 0
        error_count = 0
        results = []
        interrupted = False
        for i, bugid in enumerate(bugids):
            if _cache_batch_stop_event.is_set():
                logger.info("缓存批量提取收到停止信号，优雅中断（已完成 %d/%d）", i, total)
                interrupted = True
                break
            if await request.is_disconnected():
                logger.info("客户端已断开，缓存批量提取中断（已完成 %d/%d）", i, total)
                interrupted = True
                break
            await asyncio.sleep(0)
            # 检查本地进度缓存，已完成的直接跳过（pending 的继续提取）
            if bugid in local_progress and local_progress[bugid].get("status") != "pending":
                cached = local_progress[bugid]
                status = cached.get("status", "success")
                tt_val = cached.get("time", "")
                source = cached.get("source", "本地缓存")
                # 统计到对应类别
                if status == "success" or status == "unchanged":
                    unchanged += 1
                elif status == "empty":
                    empty += 1
                elif status == "error":
                    error_count += 1
                done_count += 1
                results.append({"bugid": bugid, "trigger_time": tt_val, "source": source, "status": status})
                yield f"data: {_json.dumps({'type': 'progress', 'index': done_count, 'total': total, 'key': bugid, 'status': status, 'time': tt_val, 'source': '本地缓存'}, ensure_ascii=False)}\n\n"
                continue
            status = "success"
            tt_val = ""
            source = ""
            try:
                issue = await asyncio.wait_for(
                    loop.run_in_executor(None, _jc.fetch_issue, bugid),
                    timeout=30)
                # 根据 video_first 参数决定提取顺序
                fields = issue.get("fields") or {}
                attachments = fields.get("attachment") or []
                has_video = any(
                    (a.get("filename", "") or "").lower().endswith(_VIDEO_SUFFIXES)
                    for a in attachments
                )
                tt = ""
                source = ""
                if video_first and has_video:
                    # 视频优先：先视频前6帧+gmlogger名称补全
                    tt = await loop.run_in_executor(
                        None, _diag_extract_time_from_video_simple, issue)
                    source = "视频+gmlogger"
                if not tt:
                    # 标准提取链路
                    tt = _jc.extract_trigger_time_from_issue(issue)
                    source = "标准提取"
                if not tt and not video_first and has_video:
                    # 标准提取优先模式下，标准提取为空再尝试视频
                    tt = await loop.run_in_executor(
                        None, _diag_extract_time_from_video_simple, issue)
                    source = "视频兜底"
                if tt:
                    old = old_times.get(bugid, "")
                    # 时间对比：完全相同 或 误差在 1 分钟内视为未变化
                    is_same = (tt == old)
                    if not is_same and old:
                        try:
                            from datetime import datetime as _dt
                            fmt_list = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")
                            t_new = t_old = None
                            for fmt in fmt_list:
                                try:
                                    t_new = _dt.strptime(tt, fmt)
                                    break
                                except ValueError:
                                    continue
                            for fmt in fmt_list:
                                try:
                                    t_old = _dt.strptime(old, fmt)
                                    break
                                except ValueError:
                                    continue
                            if t_new and t_old and abs((t_new - t_old).total_seconds()) <= 60:
                                is_same = True
                        except Exception:
                            pass
                    if is_same:
                        # 时间与缓存相同或误差≦1分钟，跳过更新
                        status = "unchanged"
                        unchanged += 1
                        tt_val = old or tt  # 保留旧时间
                    else:
                        await loop.run_in_executor(None, _save_trigger_time_to_cloud, bugid, tt)
                        updated += 1
                        tt_val = tt
                else:
                    status = "empty"
                    empty += 1
            except (asyncio.TimeoutError,):
                status = "error"
                error_count += 1
            except Exception as e:
                status = "error"
                error_count += 1
                logger.warning("缓存批量提取失败 %s: %s", bugid, e)
            done_count += 1
            results.append({"bugid": bugid, "trigger_time": tt_val, "source": source, "status": status})
            # 保存到本地进度缓存
            local_progress[bugid] = {"time": tt_val, "source": source, "status": status}
            _save_cache_batch_progress(local_progress)
            yield f"data: {_json.dumps({'type': 'progress', 'index': done_count, 'total': total, 'key': bugid, 'status': status, 'time': tt_val, 'source': source}, ensure_ascii=False)}\n\n"
        yield f"data: {_json.dumps({'type': 'done', 'total': total, 'updated': updated, 'unchanged': unchanged, 'empty': empty, 'error': error_count, 'interrupted': interrupted, 'results': results}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/test/create_docx")
async def test_create_docx(request: Request):
    """测试接口：创建飞书在线文档，返回文档 URL 和详细调试信息"""
    from src.clients import feishu_client
    body = await request.json() or {}
    title = str(body.get("title", "测试文档")).strip()
    content = str(body.get("content", "# 测试文档\n\n这是一段测试内容。")).strip()

    # 获取当前 token 信息
    cfg = load_config().get("feishu_bitable", {})
    user_token = cfg.get("user_access_token", "")
    token_type = "user" if user_token else "tenant"
    token_preview = (user_token or "")[:30] + "..." if (user_token or "") else "empty"

    try:
        doc_result = feishu_client.create_docx_document(title, content)
        return _ok({
            "document_id": doc_result.get("document_id"),
            "url": doc_result.get("url"),
            "token_type": token_type,
            "token_preview": token_preview,
        }, f"文档创建成功: {doc_result.get('url', '')}")
    except Exception as e:
        logger.error("测试创建文档失败: %s", e)
        return _fail(f"创建失败: {e}", extra={
            "token_type": token_type,
            "token_preview": token_preview,
            "error": str(e),
        })


@app.post("/api/test/bitable_failed_jiras")
async def test_bitable_failed_jiras(request: Request):
    """从多维表格提取分析失败的 jira 号，支持时间/通用失败/已成功过滤"""
    body = await request.json() or {}
    after_time = str(body.get("after_time", "") or "").strip()  # 分析完成时间起点过滤
    exclude_common = body.get("exclude_common", False)  # 是否排除通用失败原因
    exclude_success = body.get("exclude_success", False)  # 是否排除已成功的 Jira
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
        # 第一遍：收集所有已成功的 Jira 号
        success_jiras = set()
        if exclude_success:
            for rec in records:
                fields = rec.get("fields", {})
                if _bitable_text(fields.get("分析结果", "")) == "成功":
                    fv = fields.get(bugid_field, "")
                    if isinstance(fv, list):
                        fv = " ".join(str(v) for v in fv)
                    fv = str(fv).strip()
                    if fv:
                        success_jiras.add(fv)
        # 第二遍：提取失败记录
        failed_jiras = set()
        skipped_common = 0
        skipped_time = 0
        skipped_success = 0
        for rec in records:
            fields = rec.get("fields", {})
            result_status = _bitable_text(fields.get("分析结果", ""))
            if result_status != "失败":
                continue
            # 排除人工审核确认无需重试的记录
            human_review = _bitable_text(fields.get("人工审核结果", ""))
            if human_review in _EXCLUDE_REASONS or any(
                    human_review.lower() == r.lower() for r in _EXCLUDE_REASONS):
                skipped_common += 1
                continue
            # 通用失败原因过滤
            if exclude_common:
                err_info = _bitable_text(fields.get("错误信息", ""))
                rootcause = _bitable_text(fields.get("rootcause", ""))
                combined = f"{err_info} {rootcause} {human_review}".strip()
                if any(reason in combined for reason in _EXCLUDE_REASONS):
                    skipped_common += 1
                    continue
            # 分析完成时间过滤
            if after_time:
                done_time = _bitable_text(fields.get("分析完成时间", ""))
                if done_time and done_time < after_time:
                    skipped_time += 1
                    continue
            field_value = fields.get(bugid_field, "")
            if isinstance(field_value, list):
                field_value = " ".join(str(v) for v in field_value)
            field_value = str(field_value).strip()
            if field_value:
                # 已成功过滤
                if exclude_success and field_value in success_jiras:
                    skipped_success += 1
                    continue
                failed_jiras.add(field_value)
        jira_list = sorted(failed_jiras)
        msg = f"提取到 {len(jira_list)} 个分析失败的 Jira 号（已去重）"
        if skipped_common:
            msg += f"，跳过通用原因 {skipped_common} 条"
        if skipped_time:
            msg += f"，跳过时间过滤 {skipped_time} 条"
        if skipped_success:
            msg += f"，跳过已成功 {skipped_success} 条"
        return _ok({"jiras": jira_list, "count": len(jira_list)}, msg)
    except Exception as e:
        logger.error("提取失败Jira号失败: %s", e, exc_info=True)
        return _fail(f"提取失败: {e}")


# ========== AI日志分析失败问题排查工具 ==========

def _ts_parse_datetime(val) -> datetime:
    """多维表格/Jira时间字段归一化为 datetime（兼容毫秒时间戳/字符串/ISO 8601）"""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        # 毫秒时间戳（飞书日期字段默认格式）
        try:
            return datetime.fromtimestamp(val / 1000)
        except (ValueError, OSError, OverflowError):
            return None
    s = str(val).strip()
    # 先尝试 ISO 8601 格式（Jira 附件 created 字段等）
    # 2026-07-17T10:51:00.000+0800 → 截取到秒
    iso_m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})", s)
    if iso_m:
        try:
            return datetime.strptime(f"{iso_m.group(1)} {iso_m.group(2)}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _diag_pick_error_info(fields: dict) -> str:
    """从多维表格记录中提取失败/错误原因文本（多字段候选）"""
    for name in ("错误信息", "失败原因", "分析失败原因", "备注"):
        v = _bitable_text(fields.get(name, ""))
        if v:
            return v
    return ""


def _diag_extract_problem_time(err_msg: str) -> str:
    """从失败原因文本中提取问题时间（如：问题时间（2025-12-18 11:11:23））"""
    m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)", err_msg or "")
    return m.group(1) if m else ""


def _diag_parse_entry_time(filename: str):
    """解析文件名中的时间（依次尝试 gmlogger/美式/紧凑三种格式），返回 (时间字符串, datetime) 或 None"""
    from src.clients.jira_client import _parse_filename_time
    for ftype in ("gmlogger", "archive", "media"):
        t = _parse_filename_time(filename, ftype)
        if t:
            return t
    return None


def _diag_match_time_window(filename: str, target_time: str, minutes: int = 5):
    """判断文件名中的时间是否在目标时间前后 N 分钟窗口内，返回 (是否命中, 文件时间字符串)"""
    target_dt = _ts_parse_datetime(target_time)
    if not target_dt:
        return False, ""
    parsed = _diag_parse_entry_time(filename)
    if not parsed:
        return False, ""
    file_str, file_dt = parsed
    if abs((file_dt - target_dt).total_seconds()) <= minutes * 60:
        return True, file_str
    return False, file_str


def _diag_list_archive_entries(att_url: str, headers: dict, timeout: int) -> dict:
    """下载压缩包附件并列出解压后的文件名（支持 zip/tar 系，其余标记不支持）"""
    import tarfile
    import tempfile
    import zipfile
    import httpx as _httpx
    resp = _httpx.get(att_url, headers=headers, timeout=timeout, verify=False, follow_redirects=True)
    resp.raise_for_status()
    data = resp.content
    entries = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src_path = os.path.join(tmp, "att.bin")
            with open(src_path, "wb") as f:
                f.write(data)
            ok, names = _diag_archive_names(src_path)
            if not ok:
                return {"ok": False, "entries": [], "reason": names, "size": len(data)}
            entries = names
        return {"ok": True, "entries": entries, "reason": "", "size": len(data)}
    except Exception as e:
        return {"ok": False, "entries": [], "reason": f"解压异常: {e}", "size": len(data)}


def _diag_archive_names(path: str) -> tuple:
    """列出压缩包内条目名称（支持 zip/7z/tar），返回 (ok, 名称列表或失败原因)"""
    import tarfile
    import zipfile
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                return True, [n for n in zf.namelist() if not n.endswith("/")]
    except Exception as e:
        return False, f"zip 打开失败: {e}"
    try:
        import py7zr
        if py7zr.is_7zfile(path):
            with py7zr.SevenZipFile(path, "r") as zf:
                return True, [n for n in zf.getnames() if not n.endswith("/")]
    except ImportError:
        pass
    except Exception as e:
        return False, f"7z 打开失败: {e}"
    try:
        with tarfile.open(path) as tf:
            return True, [m.name for m in tf.getmembers() if m.isfile()]
    except Exception:
        return False, "非 zip/7z/tar 格式，无法解压（如 rar）"


def _diag_archive_read_heads(path: str, names: list, size: int = 65536) -> dict:
    """批量读取压缩包内多个文件的头部内容（支持 zip/7z/tar），返回 {name: 头部文本}

    7z 一次性 extract 全部目标，避免 solid 归档重复解压。
    """
    import zipfile
    import tarfile
    result = {}
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                for n in names:
                    try:
                        with zf.open(n) as f:
                            result[n] = f.read(size).decode("utf-8", errors="ignore")
                    except Exception:
                        continue
            return result
        if tarfile.is_tarfile(path):
            with tarfile.open(path) as tf:
                name_set = set(names)
                for member in tf.getmembers():
                    if not member.isfile() or member.name not in name_set:
                        continue
                    try:
                        f = tf.extractfile(member)
                        if f:
                            result[member.name] = f.read(size).decode("utf-8", errors="ignore")
                            f.close()
                    except Exception:
                        continue
            return result
        import py7zr
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with py7zr.SevenZipFile(path, "r") as zf:
                zf.extract(tmp, targets=names)  # 一次解压全部目标文件（兼容新版签名）
            for n in names:
                fp = os.path.join(tmp, n)
                if os.path.exists(fp):
                    try:
                        with open(fp, "rb") as f:
                            result[n] = f.read(size).decode("utf-8", errors="ignore")
                    except Exception:
                        continue
    except Exception as e:
        logger.warning("批量读取压缩包内文件失败 %s: %s", os.path.basename(path), e)
    return result


def _diag_gmlogger_times(attachments: list) -> list:
    """识别 gmlogger 附件（文件名含 gmlogger 即算）并解析文件名时间，返回 [(时间字符串, datetime)]"""
    from src.clients.jira_client import _parse_filename_time
    times = []
    for att in attachments:
        fname = att.get("filename", "") or ""
        if fname and "gmlogger" in fname.lower():
            t = _parse_filename_time(fname, "gmlogger")
            if t:
                times.append(t)
    return times


def _diag_7z_tool_path() -> str:
    """定位本机 7z 可执行文件（用于 rar 解压），未找到返回空串"""
    import shutil
    for p in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if os.path.exists(p):
            return p
    return shutil.which("7z") or ""


def _diag_parse_main_time(bname: str, head: str = ""):
    """从 main 文件名或文件头内容提取时间，返回 (时间字符串, datetime) 或 None

    依次尝试：常规附件名格式 → 下划线分隔格式（月日时允许一位数） → 文件头首条日志时间戳。
    """
    parsed = _diag_parse_entry_time(bname)
    if parsed:
        return parsed
    mu = re.search(r"(20\d{2})[-_](\d{1,2})[-_](\d{1,2})[-_ ](\d{1,2})[-_](\d{1,2})(?:[-_](\d{1,2}))?", bname)
    if mu:
        try:
            ts = datetime(int(mu.group(1)), int(mu.group(2)), int(mu.group(3)),
                          int(mu.group(4)), int(mu.group(5)), int(mu.group(6) or 0))
            return (ts.strftime("%Y-%m-%d %H:%M:%S"), ts)
        except ValueError:
            pass
    if head:
        mh = re.search(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})", head)
        if mh:
            ts = _ts_parse_datetime(mh.group(1).replace("T", " "))
            if ts:
                return (ts.strftime("%Y-%m-%d %H:%M:%S"), ts)
    return None


def _diag_scan_entry_times(names: list) -> list:
    """扫描压缩包内 main.log 条目文件名中的时间戳（去重），返回 [(时间字符串, datetime)]

    只筛选文件名包含 main.log 的条目（如 main.log_2022_9_16_9_37.gz），
    这些文件的时间戳是日志记录的权威时间戳，任一命中目标时间窗口即可验证通过。
    """
    times = []
    seen = set()
    for n in names:
        bname = os.path.basename(n).lower()
        if "main.log" not in bname:
            continue
        parsed = _diag_parse_main_time(os.path.basename(n), "")
        if parsed and parsed[0] not in seen:
            seen.add(parsed[0])
            times.append(parsed)
    return times


def _diag_rar_main_times(rar_first: str, work_dir: str) -> dict:
    """用本机 7z 解压 rar（多分卷从首卷自动续读）提取包内 main 相关文件的时间，返回结构与 _diag_gmlogger_main_times 一致"""
    import subprocess
    tool = _diag_7z_tool_path()
    if not tool:
        return {"status": "failed", "reason": "本机未找到 7-Zip（7z.exe），无法解压 rar，请安装 7-Zip", "main_entries": [], "main_times": []}
    main_dir = os.path.join(work_dir, "rar_main")
    try:
        # 仅提取文件名含 main 的条目，避免解压全部日志（可能数百分兆）
        subprocess.run([tool, "x", rar_first, f"-o{main_dir}", "*main*", "-y"],
                       capture_output=True, timeout=300, check=False)
    except Exception as e:
        return {"status": "failed", "reason": f"rar 解压异常: {e}", "main_entries": [], "main_times": []}
    # 扫描解出的 main 文件（优先 .log/.txt）
    main_files = []
    for root, _d, files in os.walk(main_dir):
        for f in files:
            main_files.append(os.path.join(root, f))
    main_files.sort(key=lambda p: (not p.lower().endswith((".log", ".txt")), p))
    main_files = main_files[:5]
    main_times = []
    for fp in main_files:
        head = ""
        try:
            with open(fp, "rb") as f:
                head = f.read(65536).decode("utf-8", errors="ignore")
        except Exception:
            pass
        parsed = _diag_parse_main_time(os.path.basename(fp), head)
        if parsed:
            main_times.append(parsed)
    logger.info("rar 内包探测: %s, main 文件 %d 个, 提取时间 %d 个",
                os.path.basename(rar_first), len(main_files), len(main_times))
    # 全量条目清单（7z l 仅读归档头，快）：扫描全部文件名时间，任一命中窗口即验证通过
    all_names = []
    try:
        lr = subprocess.run([tool, "l", "-ba", rar_first], capture_output=True, timeout=120, check=False)
        all_names = [ln.split()[-1] for ln in lr.stdout.decode("utf-8", errors="ignore").splitlines() if ln.strip()]
    except Exception as e:
        logger.warning("rar 条目清单获取失败: %s", e)
    all_times = _diag_scan_entry_times(all_names)
    return {"status": "ok", "reason": "",
            "main_entries": [os.path.basename(p) for p in main_files],
            "main_times": main_times, "all_times": all_times}


def _diag_download_archives(attachments: list, headers: dict, timeout: int, problem_time: str, bugid: str = "") -> tuple:
    """逐个下载压缩包附件并解压，比对解压文件名与错误时间（前后5分钟），返回 (archive_results, matched_any)"""
    from src.clients.jira_client import _ARCHIVE_SUFFIXES
    archive_results = []
    matched_any = False
    for att in attachments:
        if bugid:
            _check_diag_cancel(bugid)
        fname = att.get("filename", "")
        if not fname or not any(fname.lower().endswith(s) for s in _ARCHIVE_SUFFIXES):
            continue
        info = {"filename": fname, "size": att.get("size", 0), "entries": [],
                "matched_entries": [], "status": "", "reason": ""}
        try:
            res = _diag_list_archive_entries(att.get("content", ""), headers, timeout)
        except Exception as e:
            info["status"], info["reason"] = "下载失败", str(e)
            archive_results.append(info)
            continue
        if not res["ok"]:
            info["status"], info["reason"] = "无法解压", res["reason"]
            archive_results.append(info)
            continue
        info["entries"] = res["entries"]
        # 只筛选文件名包含 main.log 的条目做时间比对（如 main.log_2022_9_16_9_37.gz）
        main_log_entries = [n for n in res["entries"] if "main.log" in os.path.basename(n).lower()]
        matched = [n for n in main_log_entries
                   if _diag_match_time_window(os.path.basename(n), problem_time, 5)[0]]
        info["matched_entries"] = matched
        info["status"] = "已解压"
        if matched:
            matched_any = True
        archive_results.append(info)
    return archive_results, matched_any


def _diag_gmlogger_main_times(attachments: list, headers: dict, timeout: int, bugid: str = "") -> dict:
    """下载 gmlogger 压缩包（支持 .001/.002 分卷合并），查找包内 main 相关 log 文件并提取时间

    外侧文件名时间可能不准，包内 main log 的时间才是日志记录的权威时间戳。
    时间提取：先解析 main 文件名，无时间则读取文件头部内容提取首条日志时间。
    :return: {"status": "ok"/"failed", "reason": 失败原因, "main_entries": [文件名], "main_times": [(时间字符串, datetime)]}
    """
    import re as _re
    import tempfile
    import httpx as _httpx
    # 按基础名分组收集分卷：支持 .zip.001 后缀式与 .part1.rar 嵌入式命名，后缀数字为分卷号（单卷为0）
    groups = {}
    for att in attachments:
        fname = att.get("filename", "") or ""
        if "gmlogger" not in fname.lower():
            continue
        m = _re.search(r"(?:\.part(\d+))?\.(zip|7z|rar|tar|gz)(\.(\d{2,3}))?$", fname, _re.I)
        if not m:
            continue
        part = int(m.group(1) or m.group(4) or 0)
        base = fname[:m.start()] + "." + m.group(2).lower()
        groups.setdefault(base, []).append((part, att))
    if not groups:
        return {"status": "failed", "reason": "无 gmlogger 压缩包附件", "main_entries": [], "main_times": []}
    # 超大包上限：避免数百分兆下载阻塞诊断太久，超限跳过内包探测走兆底链路
    total_size = sum(a.get("size", 0) for ps in groups.values() for _p, a in ps)
    if total_size > 500 * 1024 * 1024:
        logger.info("gmlogger 内包探测：跳过（压缩包过大 %dMB > 500MB）", total_size // 1024 // 1024)
        return {"status": "failed", "reason": f"gmlogger 压缩包过大（{total_size // 1024 // 1024}MB>500MB），已跳过内包探测",
                "main_entries": [], "main_times": [], "all_times": []}
    logger.info("gmlogger 内包探测：开始下载（%dMB）", total_size // 1024 // 1024)
    last_reason = "无有效 gmlogger 压缩包"
    with tempfile.TemporaryDirectory() as tmp:
        for base, parts in groups.items():
            if bugid:
                _check_diag_cancel(bugid)
            parts.sort(key=lambda x: x[0])
            if base.lower().endswith(".rar"):
                # rar 分卷：7z 需原始文件名同目录自动续卷，从首卷打开，仅提取 main 文件
                rar_dir = os.path.join(tmp, os.path.basename(base) + "_rar")
                os.makedirs(rar_dir, exist_ok=True)
                try:
                    for _p, att in parts:
                        dst = os.path.join(rar_dir, att.get("filename", "") or f"part{_p}.rar")
                        with open(dst, "wb") as out:
                            with _httpx.stream("GET", att.get("content", ""), headers=headers,
                                               timeout=timeout, verify=False, follow_redirects=True) as r:
                                r.raise_for_status()
                                for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                                    out.write(chunk)
                except Exception as e:
                    logger.warning("gmlogger rar 下载失败 %s: %s", base, e)
                    last_reason = f"gmlogger 下载失败: {e}"
                    continue
                probe = _diag_rar_main_times(os.path.join(rar_dir, parts[0][1].get("filename", "") or "part0.rar"), rar_dir)
                if probe["status"] == "ok":
                    return probe
                last_reason = probe["reason"] or last_reason
                continue
            merged = os.path.join(tmp, os.path.basename(base))
            try:
                # 分卷按序流式下载拼接为完整压缩包，避免大文件占用内存
                with open(merged, "wb") as out:
                    for _p, att in parts:
                        with _httpx.stream("GET", att.get("content", ""), headers=headers,
                                           timeout=timeout, verify=False, follow_redirects=True) as r:
                            r.raise_for_status()
                            for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                                out.write(chunk)
            except Exception as e:
                logger.warning("gmlogger 分卷下载失败 %s: %s", base, e)
                return {"status": "failed", "reason": f"gmlogger 下载失败: {e}", "main_entries": [], "main_times": []}
            # 打开压缩包（支持 zip/7z/tar），查找 main 相关文件并提取时间
            ok, names = _diag_archive_names(merged)
            if not ok:
                logger.warning("gmlogger 解压失败 %s: %s", base, names)
                return {"status": "failed", "reason": f"gmlogger 解压失败: {names}", "main_entries": [], "main_times": []}
            main_names = [n for n in names if "main" in os.path.basename(n).lower()
                          and os.path.basename(n).lower().endswith((".log", ".txt"))]
            if not main_names:
                main_names = [n for n in names if "main" in os.path.basename(n).lower()]
            main_times = []
            need_head = []  # 文件名无时间的 main 文件，待批量读头部提取首条日志时间戳
            for n in main_names[:5]:
                bname = os.path.basename(n)
                parsed = _diag_parse_entry_time(bname)
                if parsed:
                    main_times.append(parsed)
                    continue
                # 文件名下划线分隔日期时间（如 main_2026_08_30_10_39.log）
                mu = _re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})[-_ ]?(\d{2})[-_](\d{2})(?:[-_](\d{2}))?", bname)
                if mu:
                    try:
                        ts = datetime(int(mu.group(1)), int(mu.group(2)), int(mu.group(3)),
                                      int(mu.group(4)), int(mu.group(5)), int(mu.group(6) or 0))
                        main_times.append((ts.strftime("%Y-%m-%d %H:%M:%S"), ts))
                        continue
                    except ValueError:
                        pass
                need_head.append(n)
            # 批量读文件头部提取首条日志时间戳（7z 一次解压，读 64KB 提升命中率）
            if need_head:
                heads = _diag_archive_read_heads(merged, need_head, 65536)
                for n in need_head:
                    mh = _re.search(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})", heads.get(n, ""))
                    if mh:
                        ts = _ts_parse_datetime(mh.group(1).replace("T", " "))
                        if ts:
                            main_times.append((ts.strftime("%Y-%m-%d %H:%M:%S"), ts))
            logger.info("gmlogger 内包探测: base=%s, 文件 %d 个, main 文件 %d 个, 提取时间 %d 个",
                        base, len(names), len(main_names), len(main_times))
            # 全部条目文件名时间戳（任一命中目标窗口即验证通过）
            all_times = _diag_scan_entry_times(names)
            return {"status": "ok", "reason": "",
                    "main_entries": [os.path.basename(n) for n in main_names],
                    "main_times": main_times, "all_times": all_times}
    return {"status": "failed", "reason": last_reason, "main_entries": [], "main_times": []}


# ---- 视频帧 OCR 提取触发时间（兜底机制）----
_VIDEO_SUFFIXES = (".mp4", ".avi", ".mov", ".mkv")
_easyocr_reader = None
_easyocr_lock = __import__('threading').Lock()  # 防止并发初始化


_OCR_UNAVAILABLE = object()  # OCR 不可用哨兵值


def _get_ocr_reader():
    """获取 easyocr Reader 实例（懒加载+缓存，线程安全，内网不可用时优雅降级）"""
    global _easyocr_reader
    if _easyocr_reader is not None and _easyocr_reader is not _OCR_UNAVAILABLE:
        return _easyocr_reader
    if _easyocr_reader is _OCR_UNAVAILABLE:
        return None
    with _easyocr_lock:
        # 双重检查：另一个线程可能已完成初始化
        if _easyocr_reader is not None:
            return None if _easyocr_reader is _OCR_UNAVAILABLE else _easyocr_reader
        try:
            import warnings
            warnings.filterwarnings('ignore', message='.*pin_memory.*', module='torch')
            warnings.filterwarnings('ignore', message='.*quantize_per_tensor.*', module='torch')
            import easyocr
            _easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            logger.info("easyocr Reader 初始化完成")
        except Exception as e:
            logger.warning("easyocr 初始化失败（模型下载超时或网络不可用），视频 OCR 功能已禁用: %s", e)
            _easyocr_reader = _OCR_UNAVAILABLE
            return None
    return _easyocr_reader


# OCR 结果中匹配时间的正则（视频屏幕时间常用点号分隔如 10.26.39）
_OCR_TIME_FULL_RE = re.compile(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2}\s+\d{1,2}[.:]\d{2}(?:[.:]\d{2})?)')
_OCR_TIME_ONLY_RE = re.compile(r'(?<!\d)(\d{1,2}[.:]\d{2}(?:[.:]\d{2})?)(?!\d)')


def _normalize_ocr_time(text: str) -> str:
    """将 OCR 时间中的点号分隔符替换为冒号（10.26.39 → 10:26:39）"""
    return re.sub(r'(\d{1,2})\.(\d{2})(?:\.(\d{2}))?', lambda m: f"{m.group(1)}:{m.group(2)}" + (f":{m.group(3)}" if m.group(3) else ""), text)


# OCR 漏识别冒号的修复：1433 → 14:33（仅处理前后无字母数字的孤立 4 位数字）
_OCR_BARE_TIME_RE = re.compile(r'(?<![a-zA-Z0-9\-/.])(\d{2})(\d{2})(?![a-zA-Z0-9\-/.])')

def _fix_ocr_missing_colon(text: str) -> str:
    """修复 OCR 漏识别冒号的问题：将孤立的 4 位有效时间数字补上冒号
    仅处理前后无字母/数字/分隔符的孤立 4 位数字，避免误修改年份或日期
    如 1433 → 14:33，但不会修改 2014、2026-09-01 等
    """
    def _try_insert_colon(m):
        hh, mm = int(m.group(1)), int(m.group(2))
        # 排除年份范围（1900-2099）
        full = int(m.group(0))
        if 1900 <= full <= 2099:
            return m.group(0)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{m.group(1)}:{m.group(2)}"
        return m.group(0)
    return _OCR_BARE_TIME_RE.sub(_try_insert_colon, text)


def _resolve_12h_ambiguity(time_str: str, date_tuple: tuple, ref_pool: list,
                            gm_ref_dt=None, parse_fn=None) -> tuple:
    """解决 OCR 时间的 12/24 小时制歧义，返回 (时间字符串, datetime) 或 None

    判断顺序：gmlogger 文件名时间参考 → ref_pool 包内时间戳命中 → 默认原始值
    """
    from datetime import timedelta
    y, mo, d = date_tuple
    full_time = f"{y:04d}-{mo:02d}-{d:02d} {time_str}"
    parsed = parse_fn(full_time)
    if not parsed:
        return None
    ts, dt = parsed
    hour = dt.hour
    # 小时 >= 12 无歧义，直接返回
    if hour >= 12:
        return parsed
    # 尝试 +12h 版本
    dt_plus12 = dt + timedelta(hours=12)
    ts_plus12 = dt_plus12.strftime("%Y-%m-%d %H:%M:%S")
    # 1. gmlogger 文件名时间作为参考锚点：如果某个版本与文件名时间接近（±30分钟），优先取
    if gm_ref_dt:
        diff_orig = abs((dt - gm_ref_dt).total_seconds())
        diff_plus12 = abs((dt_plus12 - gm_ref_dt).total_seconds())
        close_threshold = 1800  # 30分钟
        orig_close = diff_orig <= close_threshold
        plus12_close = diff_plus12 <= close_threshold
        if plus12_close and not orig_close:
            logger.info("视频时间 12h 转换：%s → %s（与 gmlogger 文件名时间 %s 接近）",
                        ts, ts_plus12, gm_ref_dt.strftime("%H:%M:%S"))
            return ts_plus12, dt_plus12
        if orig_close and not plus12_close:
            return parsed
        # 两个都接近或都不接近，继续看 ref_pool
        if orig_close and plus12_close:
            # 两个都接近 gmlogger，取更近的那个
            if diff_plus12 < diff_orig:
                return ts_plus12, dt_plus12
            return parsed
    # 2. 与 ref_pool 对比（±5分钟命中），兼容纯 datetime 和 (字符串, datetime) 元组
    hit_orig = any(abs(((ref[1] if isinstance(ref, tuple) else ref) - dt).total_seconds()) <= 300 for ref in ref_pool) if ref_pool else False
    hit_plus12 = any(abs(((ref[1] if isinstance(ref, tuple) else ref) - dt_plus12).total_seconds()) <= 300 for ref in ref_pool) if ref_pool else False
    if hit_plus12 and not hit_orig:
        logger.info("视频时间 12h 转换：%s → %s（与包内时间戳命中）", ts, ts_plus12)
        return ts_plus12, dt_plus12
    if hit_orig:
        return parsed
    # 3. 都没命中，有 gmlogger 参考就取更近的，否则默认原始值
    if gm_ref_dt:
        diff_orig = abs((dt - gm_ref_dt).total_seconds())
        diff_plus12 = abs((dt_plus12 - gm_ref_dt).total_seconds())
        if diff_plus12 < diff_orig:
            logger.info("视频时间 12h 转换：%s → %s（与 gmlogger 文件名时间更接近）", ts, ts_plus12)
            return ts_plus12, dt_plus12
    return parsed

def _pick_best_video(videos: list, attachments: list) -> dict:
    """从多个视频附件中选取与 gmlogger 最相关的一个

    选取策略（按优先级）：
    1. 视频文件名含日期时间且gmlogger文件名有时间 → 选与 gmlogger 文件名时间最接近的
    2. gmlogger文件名无时间 → 用gmlogger上传时间与视频上传时间对比取最接近的
    3. 完全无 gmlogger 参考 → 按视频上传时间取最早的

    :param videos: 视频附件列表（已过滤仅视频）
    :param attachments: 全部附件列表（用于提取 gmlogger 时间）
    :return: 选中的视频附件 dict
    """
    if len(videos) == 1:
        return videos[0]
    # 解析 gmlogger 文件名时间和上传时间
    gm_times = _diag_gmlogger_times(attachments)
    gm_ref_dt = gm_times[0][1] if gm_times else None
    gm_upload_dt = None
    for att in attachments:
        fname = att.get("filename", "") or ""
        if fname and "gmlogger" in fname.lower():
            gm_upload_dt = _ts_parse_datetime(att.get("created", ""))
            break
    # 为每个视频计算排序权重
    def _sort_key(v):
        fname = v.get("filename", "") or ""
        # 策略1：视频文件名中的日期时间与 gmlogger 文件名时间对比
        parsed = _diag_parse_entry_time(fname)
        if parsed and gm_ref_dt:
            diff = abs((parsed[1] - gm_ref_dt).total_seconds())
            return (0, diff, "")
        # 策略2：gmlogger文件名无时间时，用gmlogger上传时间与视频上传时间对比取最接近
        v_upload_dt = _ts_parse_datetime(v.get("created", ""))
        if v_upload_dt and gm_upload_dt:
            diff = abs((v_upload_dt - gm_upload_dt).total_seconds())
            return (1, diff, v.get("created", ""))
        # 策略3：完全无参考，按上传时间取最早
        return (2, 0, v.get("created", ""))
    videos.sort(key=_sort_key)
    selected = videos[0]
    parsed = _diag_parse_entry_time(selected.get("filename", ""))
    if parsed and gm_ref_dt:
        logger.info("视频选取：文件名时间 %s 最接近 gmlogger 时间 %s", parsed[0], gm_times[0][0])
    elif gm_upload_dt:
        logger.info("视频选取：上传时间 %s 最接近 gmlogger 上传时间", selected.get("created", ""))
    else:
        logger.info("视频选取：按上传时间取最早 %s", selected.get("filename", ""))
    return selected


def _ocr_extract_time_from_video_data(video_data: bytes, video_name: str,
                                      gm_dates: list, ref_pool: list,
                                      cv2, reader, parse_fn, gm_ref_dt=None) -> str:
    """从视频二进制数据截帧 + OCR 提取时间，返回时间字符串或空串"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "video.bin")
        with open(video_path, "wb") as f:
            f.write(video_data)
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.warning("视频兜底提取：无法打开视频 %s", video_name)
            return ""
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frames = []
        for sec in range(6):
            frame_pos = int(sec * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = cap.read()
            if not ret:
                break
            frames.append((sec, frame))
        cap.release()
        logger.info("视频兜底提取：截取 %d 帧（视频 %s）", len(frames), video_name)
        full_candidates = []     # [(时间字符串, datetime, 秒数)] — 完整日期+时间
        partial_candidates = []  # [(时间字符串, datetime, 秒数)] — 仅时间+gmlogger日期补充
        for sec, frame in frames:
            img_path = os.path.join(tmp, f"frame_{sec}.png")
            cv2.imwrite(img_path, frame)
            try:
                results = reader.readtext(img_path)
            except Exception as e:
                logger.warning("视频兜底提取：OCR 第%d秒失败: %s", sec, e)
                continue
            all_text = " ".join(r[1] for r in results)
            # 1. 匹配完整日期+时间（先修复 OCR 漏识别冒号）
            all_text = _fix_ocr_missing_colon(all_text)
            m = _OCR_TIME_FULL_RE.search(all_text)
            if m:
                parsed = parse_fn(_normalize_ocr_time(m.group(1)))
                if parsed:
                    full_candidates.append((parsed[0], parsed[1], sec))
                    continue
            # 2. 仅时间（无日期），用 gmlogger 文件名日期补充 + 12h 歧义解决
            m = _OCR_TIME_ONLY_RE.search(all_text)
            if m and gm_dates:
                time_str = _normalize_ocr_time(m.group(1))
                resolved = _resolve_12h_ambiguity(time_str, gm_dates[0], ref_pool, gm_ref_dt, parse_fn)
                if resolved:
                    partial_candidates.append((resolved[0], resolved[1], sec))
        # 选择最优结果：优先取视频时间与 gmlogger 时间重合（前后10分钟）
        for candidates, tag in [(full_candidates, "完整"), (partial_candidates, "日期补充")]:
            if not candidates:
                continue
            if ref_pool:
                for ts, dt, sec in candidates:
                    if any(abs((ref_dt - dt).total_seconds()) <= 600 for ref_dt in ref_pool):
                        logger.info("视频兜底提取成功(%s, gmlogger重合): %s (视频第%d秒)", tag, ts, sec + 1)
                        return ts
            # 无 gmlogger 或无重合，取第一个候选
            ts, _, sec = candidates[0]
            logger.info("视频兜底提取成功(%s): %s (视频第%d秒)", tag, ts, sec + 1)
            return ts
    return ""


def _diag_extract_time_from_video_simple(issue: dict) -> str:
    """视频帧 OCR 提取触发时间。

    单视频或单gmlogger：走原来的 _pick_best_video 选取逻辑。
    多视频+多gmlogger：按gmlogger从新到旧逐个匹配同日期视频，
    OCR 验证时间是否接近（5分钟容差），都不匹配则回退正常逻辑。
    """
    import httpx as _httpx
    fields = issue.get("fields") or {}
    attachments = fields.get("attachment") or []
    videos = [a for a in attachments if (a.get("filename", "") or "").lower().endswith(_VIDEO_SUFFIXES)]
    if not videos:
        return ""
    # 预检查 cv2 和 OCR
    try:
        import cv2
    except ImportError:
        logger.warning("视频兜底提取：缺少 opencv-python-headless，跳过")
        return ""
    reader = _get_ocr_reader()
    if reader is None:
        logger.warning("视频兜底提取：OCR 不可用，跳过")
        return ""
    from src.clients.jira_client import _parse_datetime_string
    # 解析 gmlogger 文件名时间，按时间倒序（最新的优先）
    gm_times = _diag_gmlogger_times(attachments)
    gm_times.sort(key=lambda x: x[1], reverse=True)
    # 构建所有 gmlogger 日期集合（用于 OCR 日期补充）
    gm_dates = [(dt.year, dt.month, dt.day) for _, dt in gm_times]
    ref_pool = [dt for _, dt in gm_times]
    gm_ref_dt = gm_times[0][1] if gm_times else None
    # 仅多视频+多gmlogger才走逐个匹配逻辑，否则走原来的选取逻辑
    if len(videos) < 2 or len(gm_times) < 2:
        video_att = _pick_best_video(videos, attachments)
        return _download_and_ocr_video(video_att, gm_dates, ref_pool,
                                       cv2, reader, _parse_datetime_string, gm_ref_dt)
    # 逐个 gmlogger 尝试匹配同日期视频（按上传时间最近选取）
    cfg = load_config().get("jira_api", {})
    headers = {}
    token = cfg.get("token", "")
    if token:
        auth_type = cfg.get("auth_type", "bearer").lower()
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {token}"
    used_videos = set()  # 已匹配过的视频，避免重复使用
    for gm_str, gm_dt in gm_times:
        gm_date_tuple = (gm_dt.year, gm_dt.month, gm_dt.day)
        # 文件配对：同日期 + 时间差最小（无窗口限制）
        candidates = []  # (时间差秒, 视频附件)
        for v in videos:
            v_key = v.get("content", "") or v.get("filename", "")
            if v_key in used_videos:
                continue
            v_fname = v.get("filename", "") or ""
            # 策略1：视频文件名中包含同日日期
            v_parsed = _diag_parse_entry_time(v_fname)
            if v_parsed:
                v_dt = v_parsed[1]
                if (v_dt.year, v_dt.month, v_dt.day) == gm_date_tuple:
                    diff = abs((v_dt - gm_dt).total_seconds())
                    candidates.append((diff, v))
                    continue
            # 策略2：视频上传时间与 gmlogger 同天
            v_upload_dt = _ts_parse_datetime(v.get("created", ""))
            if v_upload_dt and (v_upload_dt.year, v_upload_dt.month, v_upload_dt.day) == gm_date_tuple:
                diff = abs((v_upload_dt - gm_dt).total_seconds())
                candidates.append((diff, v))
        if not candidates:
            logger.info("视频兆底：gmlogger %s 未找到同日期视频，跳过", gm_str)
            continue
        # 选取时间差最小的视频
        candidates.sort(key=lambda x: x[0])
        matched_video = candidates[0][1]
        used_videos.add(matched_video.get("content", "") or matched_video.get("filename", ""))
        v_name = matched_video.get("filename", "")
        v_url = matched_video.get("content", "")
        if not v_url:
            continue
        logger.info("视频兆底：gmlogger %s 匹配视频 %s，开始 OCR", gm_str, v_name)
        # 下载 + OCR
        result = _download_and_ocr_video(matched_video, gm_dates, ref_pool,
                                         cv2, reader, _parse_datetime_string, gm_dt)
        if not result:
            continue
        # OCR 提取时间验证：与 gmlogger 文件名时间差 ≤ 15分钟且最接近
        result_dt = _ts_parse_datetime(result)
        if result_dt:
            diff_sec = abs((result_dt - gm_dt).total_seconds())
            if diff_sec <= 1800:
                logger.info("视频兜底成功：OCR %s 与 gmlogger %s 差 %.0f 秒，匹配", result, gm_str, diff_sec)
                return result
            else:
                logger.info("视频兜底：OCR %s 与 gmlogger %s 差 %.0f 秒，超30分钟，继续下一个",
                           result, gm_str, diff_sec)
        else:
            logger.info("视频兜底：OCR 结果 %s 无法解析，跳过", result)
    # 所有 gmlogger 均未匹配到接近的视频，回退正常提取逻辑
    logger.info("视频兜底：所有 gmlogger 均未匹配到接近视频，回退正常选取逻辑")
    video_att = _pick_best_video(videos, attachments)
    return _download_and_ocr_video(video_att, gm_dates, ref_pool,
                                   cv2, reader, _parse_datetime_string, gm_times[0][1] if gm_times else None)


def _download_and_ocr_video(video_att: dict, gm_dates: list, ref_pool: list,
                             cv2, reader, parse_fn, gm_ref_dt) -> str:
    """下载单个视频并截帧 OCR 提取时间，返回时间字符串或空串"""
    import httpx as _httpx
    v_url = video_att.get("content", "")
    v_name = video_att.get("filename", "")
    if not v_url:
        return ""
    cfg = load_config().get("jira_api", {})
    headers = {}
    token = cfg.get("token", "")
    if token:
        auth_type = cfg.get("auth_type", "bearer").lower()
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {token}"
    try:
        logger.info("视频兜底提取：下载视频 %s", v_name)
        resp = _httpx.get(v_url, headers=headers, timeout=120, verify=False, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("视频兜底提取：下载失败 %s: %s", v_name, e)
        return ""
    return _ocr_extract_time_from_video_data(
        resp.content, v_name, gm_dates, ref_pool, cv2, reader, parse_fn, gm_ref_dt)


def _diag_extract_time_from_video(issue: dict, headers: dict, timeout: int,
                                   gmlogger_dates: list, ref_pool: list,
                                   gm_ref_dt=None) -> tuple:
    """从视频附件前6秒截帧，OCR 识别时间，验证后返回 (extracted_time, detail) 或 ("", "")"""
    import tempfile
    import httpx as _httpx
    fields = issue.get("fields") or {}
    attachments = fields.get("attachment") or []
    # 筛选视频附件，用智能选取策略选与 gmlogger 最相关的视频
    videos = [a for a in attachments if (a.get("filename", "") or "").lower().endswith(_VIDEO_SUFFIXES)]
    if not videos:
        return "", ""
    single_video = len(videos) == 1
    video_att = _pick_best_video(videos, attachments)
    video_url = video_att.get("content", "")
    video_name = video_att.get("filename", "")
    if not video_url:
        return "", ""
    # 下载视频
    try:
        logger.info("视频帧提取：下载视频 %s%s", video_name, "（单视频直接提取）" if single_video else "")
        resp = _httpx.get(video_url, headers=headers, timeout=timeout, verify=False, follow_redirects=True)
        resp.raise_for_status()
        video_data = resp.content
    except Exception as e:
        logger.warning("视频帧提取：下载失败 %s: %s", video_name, e)
        return "", ""
    # 截帧 + OCR
    try:
        import cv2
    except ImportError:
        logger.warning("视频帧提取：缺少 opencv-python-headless，跳过")
        return "", ""
    reader = _get_ocr_reader()
    if reader is None:
        logger.warning("视频帧提取：OCR 不可用，跳过视频时间提取 %s", video_name)
        return "", ""
    from src.clients.jira_client import _parse_datetime_string
    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "video.bin")
        with open(video_path, "wb") as f:
            f.write(video_data)
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.warning("视频帧提取：无法打开视频 %s", video_name)
            return "", ""
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        # 前6秒每秒截1帧，最多6帧
        frames = []
        for sec in range(6):
            frame_pos = int(sec * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = cap.read()
            if not ret:
                break
            frames.append((sec, frame))
        cap.release()
        logger.info("视频帧提取：截取 %d 帧（视频 %s）", len(frames), video_name)
        first_full = ""   # 单视频兜底：第一个完整时间
        first_partial = "" # 单视频兜底：第一个部分时间
        first_detail = ""
        # 对每帧做 OCR
        for sec, frame in frames:
            img_path = os.path.join(tmp, f"frame_{sec}.png")
            cv2.imwrite(img_path, frame)
            try:
                results = reader.readtext(img_path)
            except Exception as e:
                logger.warning("视频帧提取：OCR 第%d秒失败: %s", sec, e)
                continue
            # 拼接所有识别文本
            all_text = " ".join(r[1] for r in results)
            logger.info("视频帧提取：第%d秒 OCR 原始文本: %s", sec + 1, all_text[:200] if all_text else "(空)")
            # 修复 OCR 漏识别冒号（1433 → 14:33）
            all_text = _fix_ocr_missing_colon(all_text)
            # 先尝试完整日期+时间
            m = _OCR_TIME_FULL_RE.search(all_text)
            if m:
                normalized = _normalize_ocr_time(m.group(1))
                parsed = _parse_datetime_string(normalized)
                if parsed:
                    extracted_time, ext_dt = parsed
                    if any(abs((dt - ext_dt).total_seconds()) <= 300 for _, dt in ref_pool):
                        detail = f"从视频第{sec+1}秒截帧 OCR 识别到时间 {extracted_time}，与 gmlogger 包内时间戳前后5分钟命中"
                        logger.info("视频帧提取成功: %s", extracted_time)
                        return extracted_time, detail
                    if not first_full:
                        first_full = extracted_time
                        first_detail = f"从视频第{sec+1}秒截帧 OCR 识别到完整日期时间 {extracted_time}"
            # 仅时间（无日期），用 gmlogger 文件名日期补充 + 12h 歧义解决
            m = _OCR_TIME_ONLY_RE.search(all_text)
            if m and gmlogger_dates:
                time_str = _normalize_ocr_time(m.group(1))
                resolved = _resolve_12h_ambiguity(time_str, gmlogger_dates[0], ref_pool, gm_ref_dt, _parse_datetime_string)
                if resolved:
                    extracted_time, ext_dt = resolved
                    if any(abs((dt - ext_dt).total_seconds()) <= 300 for _, dt in ref_pool):
                        detail = (f"从视频第{sec+1}秒截帧 OCR 识别到时间 {time_str}，"
                                  f"用 gmlogger 日期补充为 {extracted_time}，与包内时间戳前后5分钟命中")
                        logger.info("视频帧提取成功(日期补充): %s", extracted_time)
                        return extracted_time, detail
                    # ref_pool 未命中但与 gmlogger 文件名时间接近（±5分钟）也采纳
                    if gm_ref_dt and abs((gm_ref_dt - ext_dt).total_seconds()) <= 300:
                        detail = (f"从视频第{sec+1}秒截帧 OCR 识别到时间 {time_str}，"
                                  f"用 gmlogger 日期补充为 {extracted_time}，与 gmlogger 文件名时间前后5分钟命中")
                        logger.info("视频帧提取成功(日期补充+文件名命中): %s", extracted_time)
                        return extracted_time, detail
                    if not first_partial:
                        first_partial = extracted_time
                        first_detail = (f"从视频第{sec+1}秒截帧 OCR 识别到时间 {time_str}，"
                                        f"用 gmlogger 日期补充为 {extracted_time}（单视频直接提取）")
        # 有完整日期时间（年月日时分秒）→ 直接返回，无需 ref_pool 验证
        if first_full:
            logger.info("视频帧提取(完整日期时间): %s", first_full)
            return first_full, first_detail
        # 单视频兆底：提取到什么就用什么，不做严格验证
        if single_video and first_partial:
            logger.info("视频帧提取(单视频直接提取): %s", first_partial)
            return first_partial, first_detail
    return "", ""


def _diag_verify_suggestion(issue: dict, gm_times: list, archive_results: list, main_times: list = None,
                            all_times: list = None, headers: dict = None, att_timeout: int = 60) -> tuple:
    """触发时间修正链路：先用已有时间提取工具提取新时间（评论区优先），再用 gmlogger 包内时间戳验证，返回 (verify_status, suggested_time, verify_detail)

    验证池：包内全部时间戳（main 文件 + 全部条目文件名），任一与提取时间前后5分钟命中即验证通过。
    gmlogger 外侧文件名时间不准，不参与权威判定，仅作备注参考。
    """
    from src.clients import jira_client
    extracted = ""
    try:
        extracted = jira_client.extract_trigger_time_from_issue(issue)
    except Exception as e:
        logger.warning("排查诊断：触发时间提取失败: %s", e)
    ext_dt = _ts_parse_datetime(extracted) if extracted else None
    gm_note = f"（注：gmlogger 外侧文件名时间 {gm_times[0][0]} 仅供参考，可能不准）" if gm_times else ""
    # —— gmlogger 场景：以包内时间戳为验证依据（只要有一个文件满足条件即通过）——
    ref_pool = (main_times or []) + (all_times or [])
    if ref_pool:
        if ext_dt:
            for s, dt in ref_pool:
                if abs((dt - ext_dt).total_seconds()) <= 300:
                    return "success", extracted, f"提取时间 {extracted}（评论区优先）在 gmlogger 包内前后5分钟有对应时间戳({s})，可用该时间作为替换"
        # 包内时间戳存在但提取时间未命中：尝试视频帧 OCR 兜底
        if headers:
            gm_dates = [(dt.year, dt.month, dt.day) for _, dt in (gm_times or [])]
            gm_ref_dt = gm_times[0][1] if gm_times else None
            vid_time, vid_detail = _diag_extract_time_from_video(issue, headers, att_timeout, gm_dates, ref_pool, gm_ref_dt)
            if vid_time:
                return "success", vid_time, f"视频帧 OCR 兜底: {vid_detail}"
        # 视频兜底未命中：不采纳包内时间戳，直接待人工审核
        return "manual", "", (f"提取时间 {extracted or '(未提取到)'} 与包内时间戳前后5分钟均未命中，"
                              f"待人工审核正确的时间{gm_note}")
    # —— 无 gmlogger 包内时间戳（文件过大/解压失败等）：多源交叉验证 ——
    if gm_times:
        gm_ref_dt = gm_times[0][1]
        gm_date_tuple = (gm_ref_dt.year, gm_ref_dt.month, gm_ref_dt.day)
        # 尝试视频提取，与 gmlogger 文件名时间交叉印证
        if headers:
            gm_dates = [(dt.year, dt.month, dt.day) for _, dt in gm_times]
            vid_time, vid_detail = _diag_extract_time_from_video(
                issue, headers, att_timeout, gm_dates, [], gm_ref_dt)
            vid_dt = _ts_parse_datetime(vid_time) if vid_time else None
            # 视频时间与 gmlogger 文件名时间接近（±30分钟）→ 强印证
            if vid_dt and abs((gm_ref_dt - vid_dt).total_seconds()) <= 1800:
                return "success", vid_time, (
                    f"gmlogger 包内无法解析（文件过大/解压失败），"
                    f"视频提取时间 {vid_time} 与 gmlogger 文件名时间 {gm_times[0][0]} 接近，交叉印证可用")
            # 评论区提取时间与 gmlogger 文件名时间接近 → 可用
            if ext_dt and abs((gm_ref_dt - ext_dt).total_seconds()) <= 300:
                return "success", extracted, (
                    f"gmlogger 包内无法解析，提取时间 {extracted}（来自评论区/标题/描述/字段）"
                    f"与 gmlogger 文件名时间 {gm_times[0][0]} 前后5分钟命中，可用该时间作为替换")
            # 视频时间与提取时间接近 → 互相印证（用视频时间，因为有 12h 转换）
            if vid_dt and ext_dt and abs((vid_dt - ext_dt).total_seconds()) <= 300:
                return "success", vid_time, (
                    f"gmlogger 包内无法解析，视频时间 {vid_time} 与提取时间 {extracted}（来自评论区/标题/描述/字段）接近，交叉印证可用")
            # 视频时间存在但与任何源都不接近 → 参考建议
            if vid_time:
                return "manual", vid_time, (
                    f"gmlogger 包内无法解析（文件过大/解压失败），"
                    f"视频提取时间 {vid_time}，gmlogger 文件名时间 {gm_times[0][0]}，"
                    f"提取时间 {extracted or '(无)'}（来自评论区/标题/描述/字段），三者未命中，待人工审核{gm_note}")
        # 无视频或视频提取失败：仅用提取时间与 gmlogger 文件名时间对比
        if ext_dt and abs((gm_ref_dt - ext_dt).total_seconds()) <= 1800:
            return "success", extracted, (
                f"gmlogger 包内无法解析，提取时间 {extracted}（来自评论区/标题/描述/字段）"
                f"与 gmlogger 文件名时间 {gm_times[0][0]} 前后30分钟内接近，可用该时间作为替换{gm_note}")
        return "manual", "", (
            f"gmlogger 包内无法解析（文件过大/解压失败），"
            f"提取时间 {extracted or '(未提取到)'}（来自评论区/标题/描述/字段），gmlogger 文件名时间 {gm_times[0][0]}，"
            f"未能交叉印证，待人工审核正确的时间{gm_note}")
    if ext_dt:
        for arc in archive_results:
            for n in arc.get("entries", []):
                if "main.log" not in os.path.basename(n).lower():
                    continue
                if _diag_match_time_window(os.path.basename(n), extracted, 5)[0]:
                    return "success", extracted, f"提取时间 {extracted} 在解压文件[{os.path.basename(n)}]前后5分钟内有对应文件，可用该时间作为替换"
        total_main_log = sum(1 for a in archive_results for n in a.get("entries", []) if "main.log" in os.path.basename(n).lower())
        if total_main_log == 0:
            return "success", extracted, f"无可用 main.log 文件时间戳验证，直接采纳评论区/描述提取的时间 {extracted}（建议应用后重新分析验证）{gm_note}"
        return "manual", "", f"提取时间 {extracted} 在 main.log 文件中前后5分钟内无对应文件，待人工审核正确的时间{gm_note}"
    return "manual", "", f"未能提取到新触发时间（评论区/描述/视频均无时间），待人工审核正确的时间{gm_note}"


@app.post("/api/troubleshoot/records")
async def troubleshoot_records(request: Request):
    """排查工具第1步：按分析完成时间筛选多维表格记录（可筛选成功/失败、触发来源、按 jira号 去重）"""
    body = await request.json() or {}
    after_time = str(body.get("after_time", "")).strip()
    result_filter = str(body.get("result_filter", "")).strip()  # 空=全部 / 成功 / 失败
    source_filter = str(body.get("source_filter", "")).strip()  # 空=全部 / parseFullTicket / feishu_bot / jira_analyze
    dedup = bool(body.get("dedup", True))
    no_manual_review = bool(body.get("no_manual_review", False))
    cutoff = _ts_parse_datetime(after_time)
    if not cutoff:
        return _fail("请选择有效的排查时间（分析完成时间起点）")
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
    except Exception as e:
        logger.error("排查工具：多维表格查询失败: %s", e)
        return _fail(f"多维表格查询失败: {e}")
    picked = {}
    for rec in records:
        fields = rec.get("fields", {})
        done_dt = _ts_parse_datetime(fields.get("分析完成时间", ""))
        if not done_dt or done_dt <= cutoff:
            continue
        result_status = _bitable_text(fields.get("分析结果", ""))
        if result_filter and result_status != result_filter:
            continue
        # 触发来源筛选
        if source_filter:
            trigger_source = _bitable_text(fields.get("触发来源", ""))
            if trigger_source != source_filter:
                continue
        jira_no = _bitable_text(fields.get(bugid_field, ""))
        if not jira_no:
            continue
        row = {
            "jira号": jira_no,
            "分析结果": result_status,
            "触发来源": _bitable_text(fields.get("触发来源", "")),
            "分析完成时间": done_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "分析问题时间": _bitable_text(fields.get("分析问题时间", "")),
            "错误信息": _diag_pick_error_info(fields),
            "人工审核结果": _bitable_text(fields.get("人工审核结果", "")),
            "飞书报告链接": (fields.get(cfg.get("report_field", "AI分析结果(飞书链接)"), {}) or {}).get("link", "")
            if isinstance(fields.get(cfg.get("report_field", "AI分析结果(飞书链接)"), ""), dict) else "",
        }
        # 人工审核结果为空筛选
        if no_manual_review and row["人工审核结果"]:
            continue
        prev = picked.get(jira_no)
        if not dedup or prev is None or row["分析完成时间"] > prev["分析完成时间"]:
            picked[jira_no] = row
    rows = sorted(picked.values(), key=lambda r: r["分析完成时间"])
    source_label = {"parseFullTicket": "线上", "feishu_bot": "飞书机器人", "jira_analyze": "PC"}.get(source_filter, "全部")
    return _ok({"rows": rows, "count": len(rows)},
               f"{after_time} 之后执行完成 {len(rows)} 条（结果：{result_filter or '全部'}，来源：{source_label}，去重：{'是' if dedup else '否'}）")


@app.post("/api/troubleshoot/direct")
async def troubleshoot_direct(request: Request):
    """直接输入Jira号查询多维表格记录，返回匹配记录供批量诊断"""
    body = await request.json() or {}
    bugids = [b.strip().upper() for b in (body.get("bugids") or []) if b.strip()]
    if not bugids:
        return _fail("请输入Jira号")
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
    except Exception as e:
        logger.error("排查工具：多维表格查询失败: %s", e)
        return _fail(f"多维表格查询失败: {e}")
    target_set = set(bugids)
    picked = {}
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(bugid_field, ""))
        if not jira_no or jira_no not in target_set:
            continue
        done_time = _bitable_text(fields.get("分析完成时间", ""))
        row = {
            "jira号": jira_no,
            "分析结果": _bitable_text(fields.get("分析结果", "")),
            "分析完成时间": done_time,
            "分析问题时间": _bitable_text(fields.get("分析问题时间", "")),
            "错误信息": _diag_pick_error_info(fields),
            "人工审核结果": _bitable_text(fields.get("人工审核结果", "")),
            "飞书报告链接": (fields.get(cfg.get("report_field", "AI分析结果(飞书链接)"), {}) or {}).get("link", "")
            if isinstance(fields.get(cfg.get("report_field", "AI分析结果(飞书链接)"), ""), dict) else "",
        }
        prev = picked.get(jira_no)
        if prev is None or done_time > prev["分析完成时间"]:
            picked[jira_no] = row
    rows = sorted(picked.values(), key=lambda r: r["分析完成时间"])
    not_found = target_set - set(picked.keys())
    msg = f"查询到 {len(rows)} 条匹配记录"
    if not_found:
        msg += f"，未找到: {', '.join(sorted(not_found)[:5])}{'...' if len(not_found) > 5 else ''}"
    return _ok({"rows": rows, "count": len(rows), "not_found": sorted(not_found)}, msg)


@app.post("/api/troubleshoot/search_jira")
async def troubleshoot_search_jira(request: Request):
    """按 Jira 号模糊/精确查询多维表格记录，供单个失败排查使用"""
    body = await request.json() or {}
    keyword = str(body.get("keyword", "")).strip().upper()
    if not keyword:
        return _fail("请输入 Jira 号")
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
    except Exception as e:
        logger.error("排查工具：多维表格查询失败: %s", e)
        return _fail(f"多维表格查询失败: {e}")
    rows = []
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(bugid_field, "")).upper()
        if not jira_no or keyword not in jira_no:
            continue
        done_dt = _ts_parse_datetime(fields.get("分析完成时间", ""))
        rows.append({
            "jira号": _bitable_text(fields.get(bugid_field, "")),
            "分析结果": _bitable_text(fields.get("分析结果", "")),
            "分析完成时间": done_dt.strftime("%Y-%m-%d %H:%M:%S") if done_dt else "",
            "分析问题时间": _bitable_text(fields.get("分析问题时间", "")),
            "错误信息": _diag_pick_error_info(fields),
            "人工审核结果": _bitable_text(fields.get("人工审核结果", "")),
        })
    # 按分析完成时间倒序（最新的在前）
    rows.sort(key=lambda r: r["分析完成时间"] or "", reverse=True)
    return _ok({"rows": rows, "count": len(rows)}, f"找到 {len(rows)} 条匹配记录")


def _diag_pre_classify(err_msg: str) -> str:
    """根据失败原因文本预归类（对应问题排查文档的归类方式），无法判定时返回空串"""
    import re
    msg = err_msg or ""
    if "未找到问题时间" in msg:
        return "触发时间问题"
    if "没有可下载的日志附件" in msg:
        return "正常处理机制，无需分析"
    if "分析任务执行超时" in msg or "分析任务被取消" in msg:
        return "分析任务执行超时，跳过排查"
    # 模型调用失败：第x轮LLM调用失败 / 第x轮调用失败，无需分析直接给结论
    if re.search(r"第\d+轮.*调用失败", msg):
        return "模型调用失败"
    if "adjudication" in msg or "未获取有效响应" in msg or "LLM 调用失败" in msg or "调用失败" in msg:
        return "接口拥堵手动中断"
    # 服务端运行异常类报错：与触发时间/日志过滤无关，直接归类避免无效下载比对
    if "server disconnected" in msg.lower() or "disconnected without sending" in msg.lower():
        return "服务运行问题"
    # 接口/网络连接失败类报错：与触发时间/日志过滤无关，直接归类避免无效下载比对
    low = msg.lower()
    if ("all connection attempts failed" in low or "connecterror" in low
            or "连接失败" in msg or "无法连接" in msg or "connection refused" in low):
        return "接口连接问题"
    if "时间过滤后日志为空" in msg:
        return ""  # 需下载附件比对时间后才能判定
    return ""


def _generate_troubleshoot_report(bugid: str, category: str, err_msg: str, detail: str,
                                   problem_time: str = "", verify_status: str = "",
                                   suggested_time: str = "", archive_files: list = None) -> dict:
    """根据诊断归类生成问题排查报告内容（对应截图中的飞书文档格式）

    返回结构化报告字段，前端按统一格式渲染。
    """
    msg = err_msg or ""
    low = msg.lower()

    # 默认模板
    ai_reason = msg or "无"
    human_reason = ""
    retry_result = ""
    final_category = category

    if category == "接口连接问题" or "all connection attempts failed" in low:
        ai_reason = msg or "All connection attempts failed"
        human_reason = "接口无响应，待源泉排查"
        retry_result = ""
        final_category = "接口响应问题"
    elif category == "模型调用失败":
        ai_reason = msg or "LLM 调用失败"
        human_reason = "模型调用失败"
        retry_result = ""
        final_category = "模型调用失败"
    elif category == "接口拥堵手动中断" or "adjudication" in low or "llm 调用失败" in low:
        ai_reason = msg or "分析报告生成失败: LLM 调用失败或 adjudication 失败"
        human_reason = "疑似接口拥堵导致的手动中断"
        retry_result = ""
        final_category = "接口并发响应问题"
    elif category == "服务运行问题" or "server disconnected" in low:
        ai_reason = msg or "Server disconnected without sending a response."
        human_reason = "服务有报错"
        retry_result = ""
        final_category = "服务运行问题"
    elif category == "无gmlogger文件":
        ai_reason = msg or "处理后未找到有效的日志文件（可能所有文件都不时间范围内，或文件格式不支持）"
        human_reason = "无gmlogger文件"
        retry_result = "失败，事实证明当前验证逻辑无法读取非gmlogger相关名称文件进行识别。"
        final_category = "日志过滤逻辑"
    elif category == "日志过滤逻辑":
        ai_reason = msg or "时间过滤后日志为空（0行），无法进行分析"
        if "压缩文件包已损坏" in detail or "损坏" in detail:
            human_reason = "经过排查当前压缩文件包已损坏，当前数据不做分析验证"
            retry_result = "经过排查当前压缩文件包已损坏，当前数据不做分析验证"
        else:
            human_reason = "日志里无对应触发时间相关文件，但是标题里明确说了触发时间，这种暂定为无效bug，信息不全不进行分析"
        final_category = "日志过滤逻辑"
    elif category == "解压问题":
        ai_reason = msg or "gmlogger 包内时间戳与错误时间匹配，但日志为空无法解析"
        human_reason = "解压问题，待排查"
        retry_result = ""
        final_category = "解压问题"
    elif category == "触发时间问题":
        ai_reason = msg or "未找到问题时间: JIRA 自定义字段、标题、description、LLM 及评论区均未能提取到问题发生时间，请在请求中显式传入 problem_time 参数（格式: YYYY-MM-DD HH:MM:SS）"
        if suggested_time:
            human_reason = f"时间添加为{suggested_time}"
        else:
            human_reason = "时间异常无对应日志，应该添加为正确的触发时间"
        retry_result = ""
        final_category = "触发时间问题"
    elif category == "正常处理机制，无需分析":
        ai_reason = msg or "没有可下载的日志附件"
        human_reason = "该Jira无日志附件，属于正常处理机制"
        retry_result = ""
        final_category = "正常处理机制，无需分析"
    elif category == "无报错信息，跳过排查":
        ai_reason = "无"
        human_reason = "服务有报错"
        retry_result = ""
        final_category = "服务运行问题"
    elif category == "分析任务执行超时，跳过排查":
        ai_reason = msg or "JIRA 分析任务执行超时或被取消"
        human_reason = "JIRA 分析任务执行超时"
        retry_result = ""
        final_category = "分析任务执行超时，跳过排查"
    elif category == "待人工排查":
        ai_reason = msg or "未知错误"
        human_reason = "无法自动归类，待人工排查"
        retry_result = ""
        final_category = "待人工排查"
    elif category == "问题重复":
        ai_reason = "评论区存在“问题重复”标记"
        human_reason = "问题重复，无需排查"
        retry_result = ""
        final_category = "问题重复"
    elif category == "问题未复现":
        ai_reason = msg or "重新触发分析后未复现该问题"
        human_reason = "问题未复现"
        retry_result = ""
        final_category = "问题未复现"

    return {
        "ai_reason": ai_reason,
        "human_reason": human_reason,
        "retry_result": retry_result,
        "final_category": final_category,
    }


import json as _json

def _troubleshoot_cache_dir() -> str:
    """获取诊断结果本地缓存目录"""
    cache_dir = os.path.join(PROJECT_ROOT, "data", "troubleshoot")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _save_diagnose_cache(bugid: str, result: dict):
    """将诊断结果保存到本地缓存"""
    cache_dir = _troubleshoot_cache_dir()
    cache_path = os.path.join(cache_dir, f"{bugid}.json")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            _json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info("诊断结果已缓存: %s", cache_path)
    except Exception as e:
        logger.warning("诊断结果缓存失败 %s: %s", bugid, e)


def _load_diagnose_cache(bugid: str) -> dict:
    """从本地缓存读取诊断结果，未命中返回 None"""
    cache_dir = _troubleshoot_cache_dir()
    cache_path = os.path.join(cache_dir, f"{bugid}.json")
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        logger.info("诊断结果本地缓存命中: %s", bugid)
        return data
    except Exception as e:
        logger.warning("读取诊断缓存失败 %s: %s", bugid, e)
        return None


@app.post("/api/troubleshoot/cancel_diag")
async def troubleshoot_cancel_diag(body: dict = Body(default={})):
    """取消正在进行中的诊断任务（前端停止按钮调用）"""
    body = body or {}
    bugids = body.get("bugids", [])
    if bugids:
        for bugid in bugids:
            _diag_cancel[bugid] = True
        return _ok(None, f"已发送取消信号: {', '.join(bugids)}")
    # 无指定 bugid 时取消所有正在进行的诊断
    for bugid in list(_diag_cancel):
        _diag_cancel[bugid] = True
    return _ok(None, f"已发送全部取消信号: {len(_diag_cancel)} 个")


@app.post("/api/troubleshoot/diagnose")
def troubleshoot_diagnose(body: dict = Body(default={})):
    """排查工具第2步：单 Jira 自动诊断归类（同步端点：FastAPI 自动走线程池，避免下载阻塞事件循环，支持前端真并发）

    规则（学习自问题排查.md）：
    - 失败原因可预归类（未找到时间/无附件/接口无响应）直接给出结论；
    - "时间过滤后日志为空"/"未找到有效的日志文件"等未命中已知模式的，
      均下载日志压缩包附件解压，比对解压文件名时间与错误时间（前后5分钟窗口）：
      有对应时间文件 -> 日志过滤逻辑；无对应时间 -> 触发时间问题（附解压文件名清单）；
    - 归类为触发时间问题时自动查验：用触发时间提取接口重新提取时间，
      与解压文件名时间做前后5分钟比对，命中则提供替换时间，未命中提示待人工审核。
    """
    body = body or {}
    bugid = str(body.get("bugid", "")).strip()
    err_msg = str(body.get("err_msg", "")).strip()
    problem_time = str(body.get("problem_time", "")).strip()
    done_time = str(body.get("done_time", "")).strip()
    force = bool(body.get("force", False))  # 强制重新执行，跳过缓存
    if not bugid:
        return _fail("bugid 不能为空")
    # —— 注册诊断取消标志，完成时清理 ——
    _diag_cancel[bugid] = False
    try:
        return _troubleshoot_diagnose_impl(bugid, err_msg, problem_time, done_time, force=force)
    finally:
        _diag_cancel.pop(bugid, None)


def _troubleshoot_diagnose_impl(bugid, err_msg, problem_time, done_time, force=False):
    """诊断实现（从 troubleshoot_diagnose 抽取，便于统一 try/finally 管理取消标志）"""
    logger.info("诊断开始: %s%s", bugid, "（强制重新执行）" if force else "")
    # —— 优先读取本地缓存 ——
    if not force:
        cached = _load_diagnose_cache(bugid)
        if cached is not None:
            # 用当前请求的 done_time 覆盖缓存旧值，确保批量写入匹配到用户正在查看的记录
            if done_time:
                cached["done_time"] = done_time
            return _ok(cached, f"{bugid} 诊断结果（本地缓存）")
    # —— 无报错信息或“服务有报错”的记录不进行排查，直接跳过 ——
    if not err_msg or err_msg == "服务有报错":
        skip_category = "服务有报错，跳过排查" if err_msg else "无报错信息，跳过排查"
        report = _generate_troubleshoot_report(bugid, skip_category, err_msg, "")
        result = {"bugid": bugid, "category": skip_category, "problem_time": problem_time,
                  "archive_files": [], "detail": "多维表格记录无错误信息字段，无排查依据，已跳过",
                  "verify_status": "", "suggested_time": "", "report": report, "done_time": done_time}
        # 跳过的记录不缓存，因为后续状态可能变化
        return _ok(result)
    # —— 预归类：无需附件比对即可判定的场景 ——
    pre = _diag_pre_classify(err_msg)
    if pre:
        conn_tip = "（建议：确认 AI 日志分析接口内外网可达性后重试，与触发时间/日志过滤无关）" if pre == "接口连接问题" else ""
        report = _generate_troubleshoot_report(bugid, pre, err_msg, conn_tip)
        result = {"bugid": bugid, "category": pre, "problem_time": problem_time,
                    "archive_files": [], "detail": f"根据失败原因预归类：{pre}{conn_tip}",
                    "verify_status": "", "suggested_time": "", "report": report, "done_time": done_time}
        # 跳过的记录不缓存，因为后续状态可能变化
        return _ok(result)
    # —— 触发时间排查模式：日志为空 / 未找到有效日志文件 / 其他未命中模式均进入附件比对 ——
    # —— 提取错误时间（优先前端传入，其次从失败原因文本提取）——
    problem_time = problem_time or _diag_extract_problem_time(err_msg)
    if not problem_time:
        report = _generate_troubleshoot_report(bugid, "待人工排查", err_msg, "失败原因中未提取到问题时间，无法比对")
        result = {"bugid": bugid, "category": "待人工排查", "problem_time": "",
                    "archive_files": [], "detail": "失败原因中未提取到问题时间，无法比对",
                    "verify_status": "", "suggested_time": "", "report": report, "done_time": done_time}
        _save_diagnose_cache(bugid, result)
        return _ok(result)
    # —— 调 Jira RESTAPI 获取 issue 与附件 ——
    from src.clients import jira_client
    try:
        _check_diag_cancel(bugid)
        issue = jira_client.fetch_issue(bugid)
        logger.info("诊断 Jira 查询完成: %s", bugid)
    except InterruptedError:
        return _fail(f"{bugid} 诊断已中断")
    except Exception as e:
        logger.error("排查诊断：Jira 查询失败 bugid=%s: %s", bugid, e)
        report = _generate_troubleshoot_report(bugid, "待人工排查", err_msg, f"Jira 查询失败：{e}")
        result = {"bugid": bugid, "category": "待人工排查", "problem_time": problem_time,
                    "archive_files": [], "detail": f"Jira 查询失败：{e}",
                    "verify_status": "", "suggested_time": "", "report": report, "done_time": done_time}
        _save_diagnose_cache(bugid, result)
        return _ok(result)
    attachments = (issue.get("fields") or {}).get("attachment") or []
    # 构造附件下载认证头（与 fetch_issue 一致的 Bearer/Basic）
    jcfg = load_config()["jira_api"]
    headers = {}
    auth = None
    if jcfg.get("token"):
        if jcfg.get("auth_type", "bearer").lower() == "bearer":
            headers["Authorization"] = f"Bearer {jcfg['token']}"
        elif jcfg.get("username"):
            auth = (jcfg["username"], jcfg["token"])
    if auth:
        import base64
        headers["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    att_timeout = max(int(jcfg.get("timeout", 30)), 120)  # 大压缩包下载需要更长超时
    try:
        return _diag_run_core(bugid, err_msg, problem_time, done_time, issue, attachments,
                              headers, att_timeout)
    except InterruptedError:
        logger.info("诊断已中断: %s", bugid)
        return _fail(f"{bugid} 诊断已中断")


def _diag_run_core(bugid, err_msg, problem_time, done_time, issue, attachments,
                   headers, att_timeout):
    """诊断核心逻辑（从 attachments 比对开始，支持 InterruptedError 中断）"""
    from src.clients import jira_client
    # —— 时间过滤为空时先检查评论区是否有“问题重复”，有则直接跳过后续链路 ——
    if "时间过滤后日志为空" in err_msg:
        _comments = jira_client.extract_comments(issue)
        if any("问题重复" in str(c) for c in _comments):
            category = "问题重复"
            detail = "评论区存在“问题重复”标记，无需排查，跳过后续链路"
            report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time)
            result = {"bugid": bugid, "category": category, "problem_time": problem_time,
                       "archive_files": [], "detail": detail,
                       "verify_status": "", "suggested_time": "", "report": report, "done_time": done_time}
            _save_diagnose_cache(bugid, result)
            return _ok(result, f"{bugid} 诊断完成：{category}")
    # —— 识别 gmlogger 附件（文件名含 gmlogger 即算）——
    gm_atts = [a for a in attachments if "gmlogger" in (a.get("filename", "") or "").lower()]
    if not gm_atts:
        # 归类：无gmlogger文件；其他压缩包兆底下载解压比对错误时间（前后5分钟）
        _check_diag_cancel(bugid)
        archive_results, matched_any = _diag_download_archives(attachments, headers, att_timeout, problem_time, bugid)
        if matched_any:
            category = "日志过滤逻辑"
            detail = f"无gmlogger文件，但解压文件中存在错误时间({problem_time})前后5分钟内对应文件，疑似日志过滤机制问题"
            verify_status, suggested_time = "", ""
        else:
            category = "无gmlogger文件"
            detail = f"该 Issue 共 {len(attachments)} 个附件中未找到 gmlogger 日志文件，无需提取时间"
            verify_status, suggested_time = "", ""
        report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time, verify_status, suggested_time, archive_results)
        result = {"bugid": bugid, "category": category, "problem_time": problem_time,
                   "archive_files": archive_results, "detail": detail,
                   "verify_status": verify_status, "suggested_time": suggested_time, "report": report, "done_time": done_time}
        _save_diagnose_cache(bugid, result)
        return _ok(result, f"{bugid} 诊断完成：{category}")
    # —— 有 gmlogger：视频优先级最高，先做视频 OCR + 文件名交叉验证，最后才下载压缩包 ——
    _check_diag_cancel(bugid)
    gm_times = _diag_gmlogger_times(attachments)
    err_dt = _ts_parse_datetime(problem_time)
    archive_results = []
    # 1. 视频 OCR + 文件名交叉验证（最高优先级）
    _check_diag_cancel(bugid)
    verify_status, suggested_time, vdetail = _diag_verify_suggestion(
        issue, gm_times, [], main_times=[], all_times=[],
        headers=headers, att_timeout=att_timeout)
    if verify_status == "success":
        category = "触发时间问题"
        detail = f"视频 OCR 与 gmlogger 文件名交叉印证成功（{vdetail}），已跳过压缩包下载"
        report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time, verify_status, suggested_time)
        result = {"bugid": bugid, "category": category, "problem_time": problem_time,
                   "archive_files": [], "detail": detail,
                   "verify_status": verify_status, "suggested_time": suggested_time, "report": report, "done_time": done_time}
        _save_diagnose_cache(bugid, result)
        return _ok(result, f"{bugid} 诊断完成：{category}（视频印证）")
    # 2. 视频未确认 → 下载压缩包做权威比对
    _check_diag_cancel(bugid)
    gm_probe = _diag_gmlogger_main_times(attachments, headers, att_timeout, bugid)
    main_times = gm_probe.get("main_times", [])
    all_times = gm_probe.get("all_times", [])
    main_entries = gm_probe.get("main_entries", [])
    hit = [t for t in (main_times + all_times) if err_dt and abs((t[1] - err_dt).total_seconds()) <= 300]
    if hit:
        category = "解压问题"
        detail = (f"gmlogger 包内时间戳 {hit[0][0]} 与错误时间({problem_time})前后5分钟内一致，"
                  f"但实际日志为空无法解析，疑似解压问题")
        verify_status, suggested_time = "", ""
    else:
        # —— 时间不匹配时先检查评论区是否有“问题重复”，有则直接跳过后续链路 ——
        _comments = jira_client.extract_comments(issue)
        _has_dup = any("问题重复" in str(c) for c in _comments)
        if _has_dup:
            category = "问题重复"
            detail = f"评论区存在“问题重复”标记，无需排查，跳过后续链路"
            report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time)
            result = {"bugid": bugid, "category": category, "problem_time": problem_time,
                       "archive_files": [], "detail": detail,
                       "verify_status": "", "suggested_time": "", "report": report, "done_time": done_time}
            _save_diagnose_cache(bugid, result)
            return _ok(result, f"{bugid} 诊断完成：{category}")
        category = "触发时间问题"
        if main_times:
            ref_desc = ", ".join(t[0] for t in main_times)
            detail = f"gmlogger 包内内容时间戳({ref_desc})与错误时间({problem_time})不匹配（超出前后5分钟），疑似触发时间错误"
        elif all_times:
            ref_desc = ", ".join(t[0] for t in all_times[:5])
            detail = f"gmlogger 包内文件时间戳({ref_desc} 等)与错误时间({problem_time})不匹配（超出前后5分钟），疑似触发时间错误"
        else:
            gm_desc = ", ".join(t[0] for t in gm_times) or "无"
            detail = (f"gmlogger 包内未提取到内容时间戳（外侧文件名时间 {gm_desc} 仅供参考，可能不准），"
                      f"错误时间({problem_time})无可验证日志时间，疑似触发时间错误")
        if gm_probe.get("status") == "failed":
            detail += f"（注：{gm_probe.get('reason', '内包探测失败')}）"
        elif main_entries:
            detail += f"（包内 main 文件：{', '.join(main_entries[:5])}）"
        # —— 包内时间戳也未命中：用包内时间戳重新验证修正建议 ——
        _check_diag_cancel(bugid)
        verify_status, suggested_time, vdetail = _diag_verify_suggestion(issue, gm_times, [],
                                                                         main_times=main_times, all_times=all_times,
                                                                         headers=headers, att_timeout=att_timeout)
        detail += "；查验：" + vdetail
    report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time, verify_status, suggested_time, archive_results)
    result = {"bugid": bugid, "category": category, "problem_time": problem_time,
               "archive_files": archive_results, "detail": detail,
               "verify_status": verify_status, "suggested_time": suggested_time, "report": report, "done_time": done_time}
    _save_diagnose_cache(bugid, result)
    return _ok(result, f"{bugid} 诊断完成：{category}")


@app.post("/api/troubleshoot/update_cache")
def troubleshoot_update_cache(body: dict = Body(default={})):
    """更新本地诊断缓存（用户编辑修正建议后回写）"""
    body = body or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("bugid 不能为空")
    cached = _load_diagnose_cache(bugid) or {}
    if "correction_time" in body:
        cached["correction_time"] = body["correction_time"]
        cached["verify_status"] = "corrected"
        cached["suggested_time"] = body["correction_time"]
    if "correction_note" in body:
        cached["correction_note"] = body["correction_note"]
    if "human_reason" in body and isinstance(cached.get("report"), dict):
        cached["report"]["human_reason"] = body["human_reason"]
    # 同步更新问题类型
    if "category" in body:
        new_category = body["category"]
        cached["category"] = new_category
        if isinstance(cached.get("report"), dict):
            cached["report"]["final_category"] = new_category
    _save_diagnose_cache(bugid, cached)
    return _ok(None, f"{bugid} 诊断缓存已更新")


@app.post("/api/troubleshoot/batch_write_review")
async def troubleshoot_batch_write_review(request: Request):
    """批量写入人工审核结果到多维表格（匹配 jira号 + 分析完成时间）"""
    from src.clients import feishu_client
    body = await request.json() or {}
    items = body.get("items") or []
    only_empty_review = bool(body.get("only_empty_review", False))
    if not items:
        return _fail("待写入列表为空")
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    review_field = cfg.get("review_field", "人工审核结果")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    # 加载多维表格全量记录
    records = feishu_client.list_bitable_records(app_token, table_id)
    # 构建索引：(jira号, 分析完成时间) -> record_id
    index = {}
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(bugid_field, ""))
        done_time = _bitable_text(fields.get("分析完成时间", ""))
        if jira_no and done_time:
            index[(jira_no, done_time)] = rec["record_id"]
    # 匹配并构建更新列表
    updates = []
    matched, unmatched, skipped = 0, 0, 0
    for item in items:
        bugid = item.get("bugid", "")
        done_time = item.get("done_time", "")
        human_reason = item.get("human_reason", "")
        if not bugid or not human_reason:
            continue
        rid = index.get((bugid, done_time))
        if rid:
            # 仅写入人工审核结果为空时，检查当前值
            if only_empty_review:
                cur = next((r for r in records if r["record_id"] == rid), None)
                if cur:
                    existing = _bitable_text(cur.get("fields", {}).get(review_field, ""))
                    if existing:
                        skipped += 1
                        continue
            updates.append({"record_id": rid, "fields": {review_field: human_reason}})
            matched += 1
        else:
            unmatched += 1
    if not updates:
        hint = f"（跳过 {skipped} 条已有审核结果）" if skipped else ""
        return _fail(f"未匹配到任何记录（共 {len(items)} 条待写入，0 条匹配{hint}）")
    # 批量更新（单次上限 500）
    for i in range(0, len(updates), 500):
        batch = updates[i:i + 500]
        feishu_client.update_bitable_records(app_token, table_id, batch)
    return _ok({"matched": matched, "unmatched": unmatched, "skipped": skipped, "updated": len(updates)},
               f"批量写入完成: {matched}/{len(items)} 条匹配并写入" +
               (f"，{unmatched} 条未匹配" if unmatched else "") +
               (f"，{skipped} 条已有审核结果已跳过" if skipped else ""))


# 触发时间问题表格生成：云端文件夹 token
_TRIGGER_ISSUE_FOLDER_TOKEN = "VmEcfznPUlV72VdUoPYc8rF0nBd"


@app.post("/api/troubleshoot/export_trigger_time_issues")
async def troubleshoot_export_trigger_time_issues(request: Request):
    """将诊断归类结果中的触发时间问题生成表格，保存本地 CSV + 云端多维表格"""
    from src.clients import feishu_client
    body = await request.json() or {}
    items = body.get("items") or []  # [{bugid, category, done_time, problem_time, detail, suggested_time, human_reason}]
    if not items:
        return _fail("无触发时间问题记录")
    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M%S")
    # 1. 保存本地 CSV
    local_dir = os.path.join(PROJECT_ROOT, "data", "troubleshoot", "trigger_time_issues")
    os.makedirs(local_dir, exist_ok=True)
    csv_path = os.path.join(local_dir, f"trigger_time_issues_{date_str}_{time_str}.csv")
    fieldnames = ["jira号", "问题归类", "分析完成时间", "错误时间", "诊断详情", "修正建议", "人工审核结果"]
    import csv as _csv
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = _csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for it in items:
            writer.writerow({k: it.get(k, "") for k in fieldnames})
    logger.info("触发时间问题表格已保存本地: %s (%d 条)", csv_path, len(items))
    # 2. 创建云端多维表格
    cloud_url = ""
    try:
        bitable_name = f"触发时间问题_{date_str}_{time_str}"
        result = feishu_client.create_bitable(bitable_name, _TRIGGER_ISSUE_FOLDER_TOKEN)
        app_token = result.get("app_token", "")
        if app_token:
            # 创建数据表
            fields = [
                {"field_name": "jira号", "type": 1},
                {"field_name": "问题归类", "type": 1},
                {"field_name": "分析完成时间", "type": 1},
                {"field_name": "错误时间", "type": 1},
                {"field_name": "诊断详情", "type": 1},
                {"field_name": "修正建议", "type": 1},
                {"field_name": "人工审核结果", "type": 1},
            ]
            table_id = feishu_client.create_bitable_table(app_token, "触发时间问题", fields)
            # 批量写入记录
            records = [{"fields": {k: it.get(k, "") for k in fieldnames}} for it in items]
            feishu_client.batch_create_records(app_token, table_id, records)
            cloud_url = result.get("url", "")
            logger.info("触发时间问题表格已上传云端: %s (%d 条)", cloud_url, len(items))
    except Exception as e:
        logger.warning("触发时间问题表格上传云端失败（本地已保存）: %s", e)
    return _ok({"count": len(items), "csv_path": csv_path, "cloud_url": cloud_url},
               f"已生成触发时间问题表格: {len(items)} 条" +
               (f"，云端: {cloud_url}" if cloud_url else "，云端上传失败"))



@app.post("/api/bitable/unverified_jiras")
async def bitable_unverified_jiras(request: Request):
    """从多维表格提取所有“分析结果=成功”且置信度为空的记录，用于批量验证预览"""
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    conf_field = cfg.get("confidence_field", "结果置信度")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
        result = []
        seen = set()
        for rec in records:
            fields = rec.get("fields", {})
            result_status = str(fields.get("分析结果", "")).strip()
            if result_status != "成功":
                continue
            conf_val = fields.get(conf_field, "")
            if isinstance(conf_val, list):
                conf_val = " ".join(str(v) for v in conf_val)
            conf_str = str(conf_val).strip()
            if not conf_str or conf_str == "0" or conf_str == "0.0":
                fv = fields.get(bugid_field, "")
                if isinstance(fv, list):
                    fv = " ".join(str(v) for v in fv)
                fv = str(fv).strip()
                if fv and fv not in seen:
                    seen.add(fv)
                    result.append({
                        "jira号": fv,
                        "分析问题时间": str(fields.get("分析问题时间", "")).strip(),
                        "分析结果": "成功",
                        "rootcause": str(fields.get("rootcause", "")).strip()[:100],
                        "AI评论总结": str(fields.get("AI评论总结", "")).strip()[:100],
                    })
        result.sort(key=lambda r: r["jira号"])
        jira_list = [r["jira号"] for r in result]
        return _ok({"jiras": jira_list, "records": result, "count": len(result)}, f"提取到 {len(result)} 个置信度为空的 Jira 号")
    except Exception as e:
        logger.error("提取未验证Jira号失败: %s", e, exc_info=True)
        return _fail(f"提取失败: {e}")


@app.get("/api/test/confidence_batch_write")
async def test_confidence_batch_write(request: Request, after_time: str = "", only_empty: str = "", jira_ids: str = ""):
    """置信度批量写入：填充 rootcause + AI问题分析根因，对比语义相似度写回置信度

    :param after_time: 可选时间筛选，仅处理分析完成时间在此时间之后的记录
    :param jira_ids: 可选 Jira 号列表（逗号分隔），指定时仅处理这些记录，忽略 after_time 和 only_empty
    """
    from src.clients import feishu_client
    from src.core import semantic as semantic_module
    import json as _json

    async def generate():
        cfg = load_config().get("feishu_bitable", {})
        app_token = cfg.get("app_token", "")
        table_id = cfg.get("table_id", "")
        bugid_field = cfg.get("bugid_field", "jira号")
        conf_field_name = cfg.get("confidence_field", "结果置信度")
        threshold = float(load_config().get("similarity", {}).get("threshold", 0.7))
        if not app_token or not table_id:
            yield f"data: {_json.dumps({'type': 'error', 'msg': '多维表格 app_token/table_id 未配置'}, ensure_ascii=False)}\n\n"
            return

        # 加载字段定义，确定字段名和类型
        try:
            field_defs = feishu_client.list_bitable_fields(app_token, table_id)
            field_type_map = {fd.get("field_name", ""): fd.get("type", 0) for fd in field_defs}
            field_names = list(field_type_map.keys())
            # 置信度字段
            cf_field = conf_field_name if conf_field_name in field_type_map else ""
            if not cf_field:
                for fn in field_names:
                    if "置信度" in fn:
                        cf_field = fn
                        break
            # rootcause 字段
            rc_field = next((fn for fn in field_names if fn.lower() == "rootcause"), "")
            # AI问题分析根因字段
            ai_rc_field = next((fn for fn in field_names if "AI问题分析根因" in fn or "问题分析根因" in fn), "")
            if not ai_rc_field:
                ai_rc_field = next((fn for fn in field_names if "AI" in fn and "根因" in fn), "")
            logger.info("置信度批量写入字段映射: cf=%s, rc=%s, ai_rc=%s", cf_field, rc_field, ai_rc_field)
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'msg': f'获取字段定义失败: {e}'}, ensure_ascii=False)}\n\n"
            return

        # 加载多维表格记录，筛选分析结果=成功 且 置信度为空/0
        try:
            records = feishu_client.list_bitable_records(app_token, table_id)
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'msg': f'加载多维表格记录失败: {e}'}, ensure_ascii=False)}\n\n"
            return

        # 当指定 jira_ids 时，仅处理这些 Jira 号，忽略 after_time 和 only_empty
        _jira_id_set = set(x.strip().upper() for x in jira_ids.split(",") if x.strip()) if jira_ids else None
        targets = []
        for rec in records:
            fields = rec.get("fields", {})
            if str(fields.get("分析结果", "")).strip() != "成功":
                continue
            if _jira_id_set:
                # 按指定 Jira ID 过滤（大小写不敏感）
                fv_check = fields.get(bugid_field, "")
                if isinstance(fv_check, list):
                    fv_check = " ".join(str(v) for v in fv_check)
                if str(fv_check).strip().upper() not in _jira_id_set:
                    continue
            if not _jira_id_set and after_time:
                done_str = _bitable_text(fields.get("分析完成时间", ""))
                if not done_str or done_str < after_time:
                    continue
            conf_val = fields.get(conf_field_name, "")
            if isinstance(conf_val, list):
                conf_val = " ".join(str(v) for v in conf_val)
            conf_str = str(conf_val).strip()
            # only_empty=True 时仅处理置信度为空的记录，jira_ids 模式忽略此筛选
            if not _jira_id_set and only_empty and conf_str and conf_str not in ("0", "0.0"):
                continue
            fv = fields.get(bugid_field, "")
            if isinstance(fv, list):
                fv = " ".join(str(v) for v in fv)
            fv = str(fv).strip()
            if not fv:
                continue
            # 提取已有字段值
            existing_rc = _bitable_text(fields.get(rc_field, "")) if rc_field else ""
            existing_ai_rc = _bitable_text(fields.get(ai_rc_field, "")) if ai_rc_field else ""
            feishu_link = fields.get("AI分析结果(飞书链接)", "")
            if isinstance(feishu_link, dict):
                feishu_link = feishu_link.get("link", "") or feishu_link.get("text", "")
            feishu_link = str(feishu_link).strip() if feishu_link else ""
            targets.append({
                "jira号": fv, "record_id": rec["record_id"],
                "rootcause": existing_rc, "ai_rootcause": existing_ai_rc,
                "feishu_link": feishu_link,
                "conf_empty": not conf_str or conf_str in ("0", "0.0"),
            })

        total = len(targets)
        yield f"data: {_json.dumps({'type': 'start', 'total': total, 'threshold': threshold, 'after_time': after_time or ''}, ensure_ascii=False)}\n\n"
        if not total:
            yield f"data: {_json.dumps({'type': 'done', 'updated': 0, 'total': 0, 'msg': '无需处理的记录'}, ensure_ascii=False)}\n\n"
            return

        # 逐条处理：填充字段 + 对比 + 立即写回
        loop = asyncio.get_event_loop()
        success_count = 0
        fail_count = 0
        written = 0

        def _extract_core_rootcause(text: str) -> str:
            """从根因文本中提取核心语义用于 Diana LLM 对比

            支持两种格式：
            1. 结构化标记：【根本原因】/【直接原因】 段落
            2. 自然语言：提取结论句+前文上下文，拼成完整因果链
            无标记时返回全文。
            """
            if not text:
                return ""
            import re as _re
            # 1. 结构化标记：【根本原因】/【直接原因】
            m = _re.search(r'[\[\u3010\(（]\s*(?:根本原因|直接原因)\s*[\]\u3011\)）]\s*(.*?)(?=[\[\u3010\(（]|$)', text, _re.DOTALL)
            if m:
                return m.group(1).strip()
            # 2. 自然语言结论句提取
            # 优先匹配结论句（“因此”），带上前一句上下文拼成完整因果链
            for pattern in [
                r'(?:因此[，,]?\s*)([\u4e00-\u9fff].{10,})',
                r'(?:核心原因[是为]|直接原因[是为]|根因[是为])([\u4e00-\u9fff].{10,})',
            ]:
                m = _re.search(pattern, text)
                if m:
                    conclusion = m.group(1).strip()
                    # 取到第一个句号/感叹号为止的核心句
                    end = _re.search(r'[。！]', conclusion)
                    if end and end.start() > 6:
                        conclusion = conclusion[:end.end()]
                    else:
                        conclusion = conclusion[:200]
                    # 去除尾部噪声从句：“由于…”“这是…”“但无法…”
                    conclusion = _re.sub(r'[，,]\s*(?:由于|这是|但无法|但目前|无法确认|无法读取).*$', '', conclusion)
                    # 去除模糊词：“很可能”“可能”“大概率”
                    conclusion = _re.sub(r'(?:很可能|很可能是|大概率|可能)', '', conclusion)
                    # 提取前一句上下文（原因/背景），拼成完整因果链
                    before = text[:m.start()].strip()
                    if before:
                        prev_sents = _re.split(r'[。！？]', before)
                        prev_sents = [s.strip() for s in prev_sents if len(s.strip()) >= 8]
                        if prev_sents:
                            context = prev_sents[-1]
                            # 前句过长时从句子边界截取尾部，避免截断单词
                            if len(context) > 100:
                                sub = _re.split(r'[，,、]', context)
                                context = '，'.join(sub[-2:]) if len(sub) > 1 else context[-60:]
                            return (context + '，' + conclusion).strip()
                    return conclusion.strip()
            # 3. 回退：返回全文
            return text.strip()

        def _split_semantic_sentences(text: str) -> list:
            """将长文本按句子拆分，用于逐句语义兆底对比"""
            import re as _re
            parts = _re.split(r'([。！？；;!?])', text)
            sentences, cur = [], ""
            for i in range(len(parts)):
                cur += parts[i]
                if i % 2 == 1:  # 标点符号
                    s = cur.strip()
                    if len(s) >= 6:
                        sentences.append(s)
                    cur = ""
            if cur.strip() and len(cur.strip()) >= 6:
                sentences.append(cur.strip())
            return sentences
        
        def _extract_conclusion_only(text: str) -> str:
            """提取最干净的结论句（避免负面句子拉低对比分）"""
            import re as _re
            m = _re.search(r'(?:因此[，,]?\s*)([\u4e00-\u9fff].{10,})', text)
            if m:
                conclusion = m.group(1).strip()
                end = _re.search(r'[。！]', conclusion)
                if end and end.start() > 6:
                    conclusion = conclusion[:end.end()]
                else:
                    conclusion = conclusion[:200]
                conclusion = _re.sub(r'[，,]\s*(?:由于|这是|但无法|但目前|无法确认|无法读取).*$', '', conclusion)
                conclusion = _re.sub(r'(?:很可能|很可能是|大概率|可能)', '', conclusion)
                return conclusion.strip()
            return ""

        def _extract_entity_sentence(text: str, keywords: list) -> str:
            """从文本中提取同时包含最多关键词的句子，用于更精准的语义对比"""
            import re as _re
            parts = _re.split(r'[。！？]', text)
            best_sent = ""
            best_count = 0
            for part in parts:
                s = part.strip()
                if len(s) < 8:
                    continue
                count = sum(1 for kw in keywords if kw in s)
                if count > best_count:
                    best_count = count
                    best_sent = s
            return best_sent if best_count >= 2 else ""

        def _write_one(record_id, fields_to_write):
            """单条写入，失败时返回错误信息，不中断流程"""
            try:
                feishu_client.update_bitable_records(app_token, table_id,
                                                     [{"record_id": record_id, "fields": fields_to_write}])
                return ""
            except Exception as e:
                return str(e)[:120]
        
        for idx, t in enumerate(targets):
            if await request.is_disconnected():
                yield f"data: {_json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
                return
            bugid = t["jira号"]
            conf_empty = t.get("conf_empty", False)
            fields_to_write = {}
            jira_rc = t["rootcause"]
            ai_rc = t["ai_rootcause"]
            try:
                # 1. rootcause：始终从 Jira API 取最新值，覆盖表格旧数据
                if rc_field:
                    try:
                        issue = await loop.run_in_executor(None, jira_client.fetch_issue, bugid)
                        fresh_rc = jira_client.extract_rootcause(issue) or ""
                        if fresh_rc:
                            jira_rc = fresh_rc
                            fields_to_write[rc_field] = fresh_rc
                    except Exception as e:
                        logger.warning("bugid=%s Jira rootcause获取失败，回退表格值: %s", bugid, e)
                # 2. AI问题分析根因：表格已有数据则直接用，否则从飞书文档提取
                if not ai_rc and ai_rc_field and t["feishu_link"]:
                    try:
                        ai_content = await loop.run_in_executor(
                            None, pipeline._get_ai_report_content, bugid, t["feishu_link"])
                        ai_rc = doc_generator.parse_root_cause_section(ai_content) or ""
                        if ai_rc:
                            fields_to_write[ai_rc_field] = ai_rc
                    except Exception as e:
                        logger.warning("bugid=%s AI文档根因获取失败: %s", bugid, e)
                # 3. 两个根因都为空则跳过
                if not jira_rc and not ai_rc:
                    yield f"data: {_json.dumps({'type': 'progress', 'index': idx + 1, 'total': total,
                                                'bugid': bugid, 'status': 'skipped', 'score': 0,
                                                'record_id': t['record_id'], 'write_fields': fields_to_write,
                                                'conf_empty': conf_empty,
                                                'msg': '两个根因字段均为空'}, ensure_ascii=False)}\n\n"
                    fail_count += 1
                    continue
                if not jira_rc or not ai_rc:
                    missing = 'Jira根因' if not jira_rc else 'AI根因'
                    yield f"data: {_json.dumps({'type': 'progress', 'index': idx + 1, 'total': total,
                                                'bugid': bugid, 'status': 'skipped', 'score': 0,
                                                'jira_rootcause': jira_rc, 'ai_rootcause': ai_rc,
                                                'record_id': t['record_id'], 'write_fields': fields_to_write,
                                                'conf_empty': conf_empty,
                                                'msg': f'{missing}为空，无法对比'}, ensure_ascii=False)}\n\n"
                    fail_count += 1
                    continue
                # 4. 通用/无效/重复根因：置信度写"无法判断"
                _SKIP_ROOTCAUSE_KEYWORDS = ("同根因重复", "重复BUG", "重复问题", "重复缺陷", "根因一致")
                _INVALID_AI_RC_KEYWORDS = ("无法复现", "日志无法", "无法定位", "暂无分析", "无法获取日志")
                skip_reason = ""
                if pipeline._is_generic_rootcause(jira_rc):
                    skip_reason = f"Jira根因为通用表述: {jira_rc[:60]}"
                elif any(kw in jira_rc for kw in _SKIP_ROOTCAUSE_KEYWORDS):
                    hit = next(kw for kw in _SKIP_ROOTCAUSE_KEYWORDS if kw in jira_rc)
                    skip_reason = f"Jira根因含重复标记关键词[{hit}]: {jira_rc[:60]}"
                elif any(kw in ai_rc for kw in _INVALID_AI_RC_KEYWORDS):
                    hit = next(kw for kw in _INVALID_AI_RC_KEYWORDS if kw in ai_rc)
                    skip_reason = f"AI根因含无效关键词[{hit}]: {ai_rc[:60]}"
                if skip_reason:
                    cf_type = field_type_map.get(cf_field, 0)
                    write_val = "无法判断" if cf_type != 2 else 0
                    fields_to_write[cf_field] = write_val
                    success_count += 1
                    logger.info("置信度跳过 bugid=%s reason=%s", bugid, skip_reason)
                    yield f"data: {_json.dumps({'type': 'progress', 'index': idx + 1, 'total': total,
                                                'bugid': bugid, 'status': 'invalid', 'score': '无法判断',
                                                'jira_rootcause': jira_rc, 'ai_rootcause': ai_rc,
                                                'record_id': t['record_id'], 'write_fields': fields_to_write,
                                                'conf_empty': conf_empty,
                                                'msg': skip_reason}, ensure_ascii=False)}\n\n"
                    continue
                # 5. 多路语义对比：取最高分
                jira_core = _extract_core_rootcause(jira_rc)
                ai_core = _extract_core_rootcause(ai_rc)
                logger.info("置信度对比 bugid=%s | jira_core=[%s] | ai_core=[%s]", bugid, jira_core[:80], ai_core[:80])
                # 路1: 核心语义对比（可能带上下文）
                score = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_core, ai_core)
                score = round(score, 3)
                is_pass = score >= threshold
                logger.info("置信度核心对比 bugid=%s score=%.3f pass=%s", bugid, score, is_pass)
                ai_conclusion = ""
                # 路2: 仅结论句对比（避免负面上下文拉低分数）
                if not is_pass:
                    ai_conclusion = _extract_conclusion_only(ai_rc)
                    if ai_conclusion and ai_conclusion != ai_core:
                        sc2 = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_core, ai_conclusion)
                        sc2 = round(sc2, 3)
                        logger.info("置信度结论对比 bugid=%s score=%.3f conclusion=[%s]", bugid, sc2, ai_conclusion[:80])
                        if sc2 > score:
                            score = sc2
                            is_pass = score >= threshold
                # 路3: 实体句匹配（从AI根因中提取同时含Jira关键实体的句子对比）
                if not is_pass:
                    import re as _re2
                    # 提取Jira根因中的有意义短关键词（2-3字），过滤噪声词
                    _noise_kw = {"这个", "问题", "符合", "设计", "导致", "因为", "所以", "因此", "但是", "然后"}
                    # 先用标点拆分，再对每个子串提取2-3字关键词
                    _jira_parts = _re2.split(r'[^\u4e00-\u9fff]+', jira_rc)
                    jira_keywords = []
                    for p in _jira_parts:
                        for kw_len in (3, 2):
                            for i in range(len(p) - kw_len + 1):
                                kw = p[i:i+kw_len]
                                if kw not in _noise_kw and kw not in jira_keywords:
                                    jira_keywords.append(kw)
                    if jira_keywords:
                        entity_sent = _extract_entity_sentence(ai_rc, jira_keywords)
                        if entity_sent and entity_sent != ai_core:
                            sc3 = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_core, entity_sent)
                            sc3 = round(sc3, 3)
                            logger.info("置信度实体句对比 bugid=%s score=%.3f entity_sent=[%s] keywords=%s", bugid, sc3, entity_sent[:80], jira_keywords[:8])
                            if sc3 > score:
                                score = sc3
                                is_pass = score >= threshold
                # 路4: 逐句兆底对比
                if not is_pass and len(ai_rc) > 80:
                    ai_sents = _split_semantic_sentences(ai_rc)
                    if len(ai_sents) > 1:
                        sent_max = 0.0
                        sent_best = ""
                        for s in ai_sents:
                            sc = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_core, s)
                            if sc > sent_max:
                                sent_max = sc
                                sent_best = s[:60]
                        sent_max = round(sent_max, 3)
                        logger.info("置信度逐句兆底 bugid=%s sent_max=%.3f best=[%s] sents=%d", bugid, sent_max, sent_best, len(ai_sents))
                        if sent_max >= threshold:
                            score = sent_max
                            is_pass = True
                # 路5: 全文原始对比（用原始Jira根因与原始AI根因，让模型看完整上下文）
                if not is_pass and len(ai_rc) > 50:
                    sc5 = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_rc[:300], ai_rc[:500])
                    sc5 = round(sc5, 3)
                    logger.info("置信度全文对比 bugid=%s score=%.3f", bugid, sc5)
                    if sc5 > score:
                        score = sc5
                        is_pass = score >= threshold
                cf_type = field_type_map.get(cf_field, 0)
                write_val = float(score) if cf_type == 2 else str(score)
                fields_to_write[cf_field] = write_val
                if is_pass:
                    success_count += 1
                yield f"data: {_json.dumps({'type': 'progress', 'index': idx + 1, 'total': total,
                                            'bugid': bugid, 'status': 'pass' if is_pass else 'low',
                                            'score': score,
                                            'jira_rootcause': jira_rc, 'ai_rootcause': ai_rc,
                                            'record_id': t['record_id'], 'write_fields': fields_to_write,
                                            'conf_empty': conf_empty,
                                            'msg': '' if is_pass else f'相似度{score}<{threshold}'}, ensure_ascii=False)}\n\n"
            except Exception as e:
                fail_count += 1
                yield f"data: {_json.dumps({'type': 'progress', 'index': idx + 1, 'total': total,
                                            'bugid': bugid, 'status': 'fail', 'score': 0,
                                            'conf_empty': conf_empty,
                                            'msg': str(e)[:120]}, ensure_ascii=False)}\n\n"
        
        yield f"data: {_json.dumps({'type': 'done', 'total': total, 'updated': 0,
                                    'passed': success_count, 'failed': fail_count,
                                    'msg': f'分析完成: {total}条, 达标{success_count}条, 未达标{total - success_count - fail_count}条, 跳过/失败{fail_count}条'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/test/confidence_batch_commit")
async def test_confidence_batch_commit(request: Request):
    """置信度批量写入提交：接收前端筛选后的记录列表，批量写入多维表格"""
    from src.clients import feishu_client
    body = await request.json() or {}
    items = body.get("items") or []
    if not items:
        return _fail("待写入列表为空")
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    # 逐条写入，跳过 record_id 为空的
    written = 0
    errors = []
    for item in items:
        record_id = item.get("record_id", "")
        fields = item.get("write_fields") or {}
        if not record_id or not fields:
            continue
        try:
            feishu_client.update_bitable_records(app_token, table_id,
                                                 [{"record_id": record_id, "fields": fields}])
            written += 1
        except Exception as e:
            errors.append(f"{item.get('bugid', '?')}: {str(e)[:80]}")
    msg = f"写入完成: {written}/{len(items)} 条"
    if errors:
        msg += f"，{len(errors)} 条失败"
    return _ok({"written": written, "errors": errors}, msg)


# ---- 未分析 Bug 提取（以往/新增）----
_UNANALYZED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "unanalyzed")
_AI_INIT_FIELD_ID = "customfield_13714"  # AI Init Analysis Result


@app.post("/api/test/unanalyzed_bugs")
async def test_unanalyzed_bugs(request: Request):
    """提取未分析的 Bug：JQL 搜索时直接带 customfield_13714，筛选该字段不存在或为空的记录"""
    import asyncio
    import csv as _csv
    import json as _json
    body = await request.json() or {}
    jql = body.get("jql", "").strip()
    filter_ai_init = body.get("filter_ai_init", True)
    if not jql:
        return _fail("JQL 不能为空")

    async def event_generator():
        from src.clients import jira_client as _jc
        loop = asyncio.get_event_loop()
        yield f"data: {_json.dumps({'type': 'start', 'jql': jql}, ensure_ascii=False)}\n\n"
        # 搜索时直接带上 customfield_13714 字段，无需逐个 fetch
        def _search():
            cfg = load_config()["jira_api"]
            headers, auth = {}, None
            token = cfg.get("token", "")
            if token:
                auth_type = cfg.get("auth_type", "bearer").lower()
                if auth_type == "bearer":
                    headers["Authorization"] = f"Bearer {token}"
                elif cfg.get("username"):
                    auth = (cfg["username"], token)
            search_url = cfg["url"].rsplit("/issue", 1)[0] + "/search"
            fields = "summary,status,created," + _AI_INIT_FIELD_ID
            all_issues, start_at, page_size = [], 0, 1000
            while len(all_issues) < 25000:
                result = _jc.http_get(search_url, params={"jql": jql, "maxResults": page_size,
                                                          "startAt": start_at, "fields": fields},
                                      timeout=cfg.get("timeout", 30), auth=auth, headers=headers)
                issues = result.get("issues", [])
                if not issues:
                    break
                all_issues.extend(issues)
                total = result.get("total", 0)
                if len(all_issues) >= total or len(issues) < page_size:
                    break
                start_at += len(issues)
            return all_issues[:25000]
        try:
            issues = await loop.run_in_executor(None, _search)
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'message': f'JQL 搜索失败: {e}'}, ensure_ascii=False)}\n\n"
            return
        yield f"data: {_json.dumps({'type': 'searched', 'total': len(issues)}, ensure_ascii=False)}\n\n"
        if not issues:
            yield f"data: {_json.dumps({'type': 'done', 'results': [], 'message': '搜索无结果'}, ensure_ascii=False)}\n\n"
            return
        # 筛选未分析记录：filter_ai_init=True时过滤已有AI初步分析的，False时保留全部
        unanalyzed = []
        for iss in issues:
            f = iss.get("fields") or {}
            if filter_ai_init:
                val = f.get(_AI_INIT_FIELD_ID)
                has_val = bool(val and str(val).strip() and str(val).strip().lower() not in ("none", "null"))
                if has_val:
                    continue
            unanalyzed.append({
                "bugid": iss.get("key", ""),
                "created": (f.get("created") or "")[:19].replace("T", " "),
                "status": ((f.get("status") or {}).get("name") or ""),
                "summary": (f.get("summary") or "")[:80],
            })
        unanalyzed.sort(key=lambda x: x["created"])
        # 保存 CSV（每个文件最多 2000 条，超出自动拆分）
        os.makedirs(_UNANALYZED_DIR, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        csv_paths = []
        chunk_size = 2000
        for i in range(0, max(len(unanalyzed), 1), chunk_size):
            chunk = unanalyzed[i:i + chunk_size]
            if not chunk:
                break
            idx = i // chunk_size + 1
            fname = f"unanalyzed_{date_str}_{idx}.csv" if len(unanalyzed) > chunk_size else f"unanalyzed_{date_str}.csv"
            csv_path = os.path.join(_UNANALYZED_DIR, fname)
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as cf:
                writer = _csv.writer(cf)
                writer.writerow(["Jira号", "创建时间", "状态", "摘要"])
                for r in chunk:
                    writer.writerow([r["bugid"], r["created"], r["status"], r["summary"]])
            csv_paths.append(csv_path)
        paths_str = ", ".join(os.path.basename(p) for p in csv_paths)
        logger.info("未分析 Bug 提取完成: %d/%d 未分析, 已保存 %d 个文件: %s",
                    len(unanalyzed), len(issues), len(csv_paths), paths_str)
        yield f"data: {_json.dumps({'type': 'done', 'results': unanalyzed, 'csv_paths': csv_paths, 'total': len(issues), 'message': f'提取完成: {len(unanalyzed)}/{len(issues)} 未分析，已保存 {len(csv_paths)} 个文件'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- 线上AI日志分析批量执行 ----
_PROD_AI_URL = "https://dpportal.apps.saic-gm.com/api/logAnalysis/parseFullTicket"


@app.get("/api/test/prod_csv_files")
async def test_prod_csv_files():
    """列出 data/unanalyzed/ 下所有 CSV 文件，分为未分析文件和执行结果文件（含成功/失败统计）"""
    import csv as _csv
    unanalyzed, prod_results = [], []
    if os.path.isdir(_UNANALYZED_DIR):
        for fname in sorted(os.listdir(_UNANALYZED_DIR), reverse=True):
            if not fname.endswith(".csv"):
                continue
            fpath = os.path.join(_UNANALYZED_DIR, fname)
            count = 0
            success = 0
            fail = 0
            try:
                with open(fpath, "r", encoding="utf-8-sig") as f:
                    reader = _csv.DictReader(f)
                    for row in reader:
                        count += 1
                        result_val = (row.get("执行结果") or "").strip()
                        if result_val == "成功":
                            success += 1
                        elif result_val == "失败":
                            fail += 1
            except Exception:
                pass
            info = {"name": fname, "path": fpath, "count": count, "total": count, "success": success, "fail": fail}
            if fname.startswith("prod_batch_"):
                prod_results.append(info)
            else:
                unanalyzed.append(info)
    return _ok({"unanalyzed": unanalyzed, "prod_results": prod_results},
               f"未分析文件 {len(unanalyzed)} 个，结果文件 {len(prod_results)} 个")


@app.post("/api/test/prod_csv_read")
async def test_prod_csv_read(request: Request):
    """读取指定 CSV 文件并返回全部记录，用于流程二的历史记录加载"""
    import csv as _csv
    body = await request.json() or {}
    fpath = str(body.get("path", "")).strip()
    if not fpath or not os.path.isfile(fpath):
        return _fail("文件不存在")
    records = []
    try:
        with open(fpath, "r", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                records.append(dict(row))
    except Exception as e:
        return _fail(f"读取 CSV 失败: {e}")
    return _ok({"records": records, "total": len(records)},
               f"已读取 {len(records)} 条记录")


@app.post("/api/test/prod_csv_bitable")
async def test_prod_csv_bitable(request: Request):
    """读取批量执行 CSV 的 Jira 号，聚合多维表格分析数据（分析结果/触发来源/置信度/rootcause 等）"""
    import csv as _csv
    body = await request.json() or {}
    fpath = str(body.get("path", "")).strip()
    if not fpath or not os.path.isfile(fpath):
        return _fail("文件不存在")
    # 读取 CSV 获取 Jira 号和执行结果（兼容不同大小写列名）
    csv_items = []
    try:
        with open(fpath, "r", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                # 兼容 Jira号 / jira号 两种列名
                jira = (row.get("Jira号") or row.get("jira号") or "").strip()
                if jira:
                    csv_items.append({
                        "jira号": jira,
                        "执行结果": (row.get("执行结果") or "").strip(),
                        "备注": (row.get("备注") or "").strip(),
                        "执行时间": (row.get("执行时间") or "").strip(),
                    })
    except Exception as e:
        return _fail(f"读取 CSV 失败: {e}")
    if not csv_items:
        return _fail("CSV 中无有效 Jira 号")
    jira_set = set(item["jira号"] for item in csv_items)
    # 从文件名解析执行时间，用于过滤多维表格历史记录
    fname = os.path.basename(fpath)
    batch_exec_time = ""
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{6})", fname)
    if m:
        batch_exec_time = f"{m.group(1)} {m.group(2)[:2]}:{m.group(2)[2:4]}:{m.group(2)[4:]}"
    # 查询多维表格匹配记录
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
    bitable_map = {}
    if app_token and table_id:
        try:
            records = feishu_client.list_bitable_records(app_token, table_id)
            for rec in records:
                fields = rec.get("fields", {})
                jira_key = _bitable_text(fields.get(bugid_field, ""))
                if not jira_key or jira_key not in jira_set:
                    continue
                rec_done = _bitable_text(fields.get("分析完成时间", ""))
                if batch_exec_time and rec_done and rec_done < batch_exec_time:
                    continue
                flat = _flatten_bitable_record(fields, report_field)
                flat["rootcause"] = _bitable_text(fields.get("rootcause", ""))
                flat["AI评论总结"] = _bitable_text(fields.get("AI评论总结", ""))
                flat["结果置信度"] = _bitable_text(fields.get("结果置信度", ""))
                bitable_map.setdefault(jira_key, []).append(flat)
        except Exception as e:
            logger.warning("聚合多维表格失败: %s", e)
    # 合并 CSV + 多维表格数据
    results = []
    for item in csv_items:
        jira_no = item["jira号"]
        bt_list = bitable_map.get(jira_no, [])
        if bt_list:
            bt_list.sort(key=lambda x: x.get("分析完成时间", ""))
            bf = bt_list[0]
            results.append({
                "jira号": jira_no,
                "执行结果": item["执行结果"],
                "分析结果": bf.get("分析结果", ""),
                "触发来源": bf.get("触发来源", ""),
                "结果置信度": bf.get("结果置信度", ""),
                "rootcause": bf.get("rootcause", ""),
                "AI评论总结": bf.get("AI评论总结", ""),
                "飞书报告链接": bf.get("飞书报告链接", ""),
                "错误信息": bf.get("错误信息", ""),
                "分析问题时间": bf.get("分析问题时间", ""),
                "分析完成时间": bf.get("分析完成时间", ""),
                "人工审核结果": bf.get("人工审核结果", ""),
                "备注": item["备注"],
            })
        else:
            results.append({
                "jira号": jira_no,
                "执行结果": item["执行结果"],
                "分析结果": "", "触发来源": "", "结果置信度": "",
                "rootcause": "", "AI评论总结": "", "飞书报告链接": "",
                "错误信息": "", "分析问题时间": "", "分析完成时间": "",
                "人工审核结果": "", "备注": item["备注"],
            })
    matched = len(jira_set & set(bitable_map.keys()))
    success_cnt = sum(1 for r in results if r["分析结果"] == "成功")
    fail_cnt = sum(1 for r in results if r["分析结果"] == "失败")
    return _ok({"records": results, "total": len(results), "matched": matched,
                "success_count": success_cnt, "fail_count": fail_cnt},
               f"已加载 {len(results)} 条记录，多维表格命中 {matched} 个")


@app.post("/api/test/prod_batch_run")
async def test_prod_batch_run(request: Request):
    """线上AI日志分析批量执行：读取CSV → 提取触发时间(优先云端) → 去重 → 批量调用线上接口"""
    import asyncio
    import json as _json
    import csv as _csv
    import queue
    body = await request.json() or {}
    csv_files = body.get("csv_files") or []
    direct_bugids = body.get("bugids") or []
    skip_existing = body.get("skip_existing", True)  # 是否过滤已执行成功的 Jira 号
    filter_pc_only = body.get("filter_pc_only", False)  # 仅过滤PC来源的正确+通用失败
    filter_online_only = body.get("filter_online_only", False)  # 仅过滤线上来源的正确+通用失败
    max_count = int(body.get("max_count") or 0)  # 抽取数量上限，0 表示不限制
    # 批量执行元数据（默认线上值）
    _batch_meta = {
        "分析并发数": str(body.get("analysis_concurrency", "5")),
        "下载并发数": str(body.get("download_concurrency", "2")),
        "模型": str(body.get("model", "deepseek-v-pro")),
        "触发来源": str(body.get("trigger_source", "线上")),
    }
    # 从 CSV 和直接输入两种来源收集 Jira 号
    all_bugids = list(direct_bugids)
    for fpath in csv_files:
        try:
            with open(fpath, "r", encoding="utf-8-sig") as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    jira = row.get("Jira号", "").strip()
                    if jira:
                        all_bugids.append(jira)
        except Exception as e:
            logger.warning("读取 CSV 失败 %s: %s", fpath, e)
    if not all_bugids:
        return _fail("无 Jira 号，请选择 CSV 文件或输入 Jira 号")
    # 去重
    seen = set()
    bugids = []
    for b in all_bugids:
        if b not in seen:
            seen.add(b)
            bugids.append(b)
    dedup_count = len(all_bugids) - len(bugids)
    # 重复过滤：查询多维表格，跳过已执行成功或人工审核确认为无效bug的 Jira 号
    # 支持 skip_existing（全量过滤）和 filter_pc_only/filter_online_only（按来源过滤）
    any_filter = skip_existing or filter_pc_only or filter_online_only
    skipped_count = 0
    if any_filter:
        try:
            from src.clients import feishu_client
            cfg_fb = load_config().get("feishu_bitable", {})
            bt_records = feishu_client.list_bitable_records(
                cfg_fb.get("app_token", ""), cfg_fb.get("table_id", ""))
            bugid_field = cfg_fb.get("bugid_field", "jira号")
            existing_exclude = set()
            for rec in bt_records:
                fields = rec.get("fields", {})
                fv = fields.get(bugid_field, "")
                if isinstance(fv, list):
                    fv = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in fv)
                elif isinstance(fv, dict):
                    fv = fv.get("text", str(fv))
                jira_key = str(fv).strip()
                if not jira_key:
                    continue
                if not _is_bitable_excluded(fields, bugid_field):
                    continue
                # 按来源过滤：PC/线上分别判断
                trigger_source = _bitable_text(fields.get("触发来源", ""))
                is_pc = trigger_source == "jira_analyze"
                if filter_pc_only and filter_online_only:
                    existing_exclude.add(jira_key)
                elif filter_pc_only:
                    if is_pc:
                        existing_exclude.add(jira_key)
                elif filter_online_only:
                    if not is_pc:
                        existing_exclude.add(jira_key)
                else:
                    existing_exclude.add(jira_key)
            if existing_exclude:
                before = len(bugids)
                bugids = [b for b in bugids if b not in existing_exclude]
                skipped_count = before - len(bugids)
                logger.info("多维表格过滤: 跳过 %d 个 Jira 号 (skip=%s, pc=%s, online=%s)",
                            skipped_count, skip_existing, filter_pc_only, filter_online_only)
        except Exception as e:
            logger.warning("多维表格重复过滤查询失败（跳过此检查）: %s", e)

    async def event_generator():
        import threading
        stop_event = threading.Event()
        batch_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        loop = asyncio.get_event_loop()
        run_bugids = list(bugids)  # 局部副本，避免闭包变量赋值冲突
        yield f"data: {_json.dumps({'type': 'start', 'total': len(run_bugids), 'dedup': dedup_count, 'skipped': skipped_count, 'raw': len(all_bugids), 'max_count': max_count}, ensure_ascii=False)}\n\n"
        # 提取触发时间（优先云端缓存，无缓存的才重新提取）
        trigger_times = {}  # bugid -> time（只包含已成功获取的时间）
        try:
            cloud_times = await loop.run_in_executor(None, _load_trigger_times_from_cloud)
            for b in run_bugids:
                if b in cloud_times and cloud_times[b]:
                    trigger_times[b] = cloud_times[b]
        except Exception as e:
            logger.warning("云端触发时间加载失败: %s", e)
        cloud_hit_count = len(trigger_times)
        # 未命中云端的进入待提取池
        pending_pool = [b for b in run_bugids if b not in trigger_times]
        logger.info("云端命中 %d 条，待提取池 %d 条", cloud_hit_count, len(pending_pool))
        # 逐批从待提取池提取，提取失败跳过继续下一个，直到凑够 max_count 或池子耗尽
        extract_batch_size = 50
        while pending_pool:
            need = (max_count - len(trigger_times)) if max_count > 0 else len(pending_pool)
            if need <= 0:
                break
            # 取一批
            batch = pending_pool[:extract_batch_size]
            pending_pool = pending_pool[extract_batch_size:]
            if not batch:
                break
            from src.clients import jira_client as _jc
            def _extract_one(bugid):
                try:
                    issue = _jc.fetch_issue(bugid)
                    # 视频 OCR 提取优先级最高
                    tt = _diag_extract_time_from_video_simple(issue)
                    if tt:
                        # 防御性处理：确保 tt 是字符串
                        if not isinstance(tt, str):
                            tt = tt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(tt, 'strftime') else str(tt)
                        return bugid, tt
                    # 视频无结果，走标准提取（标题→评论→描述→自定义字段）
                    tt = _jc.extract_trigger_time_from_issue(issue)
                    if tt:
                        if not isinstance(tt, str):
                            tt = tt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(tt, 'strftime') else str(tt)
                        return bugid, tt
                except Exception:
                    pass
                return bugid, ""
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                futures = {pool.submit(_extract_one, b): b for b in batch}
                done_count = 0
                for future in concurrent.futures.as_completed(futures):
                    done_count += 1
                    try:
                        bugid, tt = future.result()
                        if tt:
                            trigger_times[bugid] = tt
                            # 提取成功（含视频兜底）存入云端
                            _save_trigger_time_to_cloud(bugid, tt)
                        else:
                            # 提取为空，标记空值避免下次重复提取
                            _save_trigger_time_to_cloud(bugid, "")
                    except Exception:
                        pass
                    if done_count % 20 == 0 or done_count == len(batch):
                        yield f"data: {_json.dumps({'type': 'extract_progress', 'current': done_count, 'total': len(batch), 'hit': len(trigger_times)}, ensure_ascii=False)}\n\n"
        # 最终执行列表：只包含有触发时间的 Jira 号
        if max_count > 0:
            # 按原始顺序保留有时间的，最多 max_count 条
            run_bugids = [b for b in run_bugids if b in trigger_times][:max_count]
        else:
            run_bugids = [b for b in run_bugids if b in trigger_times]
        skipped_no_time = len(bugids) - len(run_bugids)
        yield f"data: {_json.dumps({'type': 'extract_done', 'total': len(run_bugids), 'with_time': len(trigger_times), 'without_time': skipped_no_time}, ensure_ascii=False)}\n\n"
        # 批量执行线上接口
        result_queue = queue.Queue()

        def _run_one(bugid):
            if stop_event.is_set():
                return
            from src.clients.base import http_post
            # 无触发时间的 Jira 号跳过执行，不使用当前时间回退
            exec_time = trigger_times.get(bugid)
            if not exec_time:
                result_queue.put({"Jira号": bugid, "执行结果": "失败",
                                  "备注": "无触发时间", "触发时间": "",
                                  "执行时间": batch_start_time,
                                  "status": "fail", "msg": "无触发时间"})
                return
            try:
                payload = {"jiraNumber": bugid, "questionTimes": [exec_time]}
                resp = http_post(_PROD_AI_URL, payload, timeout=30)
                if stop_event.is_set():
                    return
                resp_code = resp.get("code") if isinstance(resp, dict) else None
                resp_msg = str(resp.get("msg", "")) if isinstance(resp, dict) else str(resp)[:200]
                is_ok = (resp_code == 200 or resp_code == 0 or resp_code == "200")
                result_queue.put({"Jira号": bugid, "执行结果": "成功" if is_ok else "失败",
                                  "备注": resp_msg[:200], "触发时间": exec_time,
                                  "执行时间": batch_start_time,
                                  "status": "success" if is_ok else "fail", "msg": resp_msg[:100]})
            except Exception as e:
                result_queue.put({"Jira号": bugid, "执行结果": "失败",
                                  "备注": str(e)[:200], "触发时间": trigger_times.get(bugid, ""),
                                  "执行时间": batch_start_time,
                                  "status": "fail", "msg": str(e)[:100]})

        for bugid in run_bugids:
            loop.run_in_executor(None, _run_one, bugid)

        results = []
        while len(results) < len(run_bugids):
            if await request.is_disconnected():
                stop_event.set()
                break
            try:
                item = result_queue.get_nowait()
                results.append(item)
                yield f"data: {_json.dumps({'type': 'progress', 'index': len(results), 'total': len(run_bugids), 'bugid': item['Jira号'], 'status': item['status'], 'msg': item.get('msg', ''), 'exec_time': item.get('触发时间', ''), 'analysis_time': item.get('执行时间', '')}, ensure_ascii=False)}\n\n"
            except queue.Empty:
                await asyncio.sleep(1)
        # 保存结果 CSV（同时写入 docs 目录供每日播报统计）
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        batch_csv = os.path.join(_UNANALYZED_DIR, f"prod_batch_{date_str}_{time_str}.csv")
        with open(batch_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = _csv.writer(f)
            writer.writerow(["Jira号", "执行结果", "触发时间", "执行时间", "备注",
                             "分析并发数", "下载并发数", "模型", "触发来源"])
            for r in results:
                writer.writerow([r["Jira号"], r["执行结果"], r.get("触发时间", ""), r.get("执行时间", ""), r.get("备注", ""),
                                 _batch_meta["分析并发数"], _batch_meta["下载并发数"],
                                 _batch_meta["模型"], _batch_meta["触发来源"]])
        success_count = sum(1 for r in results if r["执行结果"] == "成功")
        fail_count = len(results) - success_count
        done_msg = f"执行完成：成功 {success_count}，失败 {fail_count}，去重 {dedup_count}，重复跳过 {skipped_count}，无触发时间 {len(run_bugids) - len(trigger_times)}"
        logger.info("线上批量执行完成: %s", done_msg)
        # 上传执行记录到云端
        cloud_url = ""
        try:
            doc_title = f"线上批量执行 {date_str} {time_str} ({success_count}/{len(results)})"
            cloud_url = _upload_batch_to_cloud(batch_csv, doc_title)
        except Exception as e:
            logger.warning("线上批量执行记录上传云端失败: %s", e)
        yield f"data: {_json.dumps({'type': 'done', 'total': len(results), 'success': success_count, 'fail': fail_count, 'dedup': dedup_count, 'skipped': skipped_count, 'csv_path': batch_csv, 'cloud_url': cloud_url, 'message': done_msg}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _parse_bugids(raw: str) -> list:
    """解析 bugid 输入：支持分号、逗号、中英文逗号分隔，最多 30 个"""
    raw = raw.replace("，", ",").replace(";", ",")
    return [b.strip() for b in raw.split(",") if b.strip()][:30]


def _compare_single_bug(bugid: str, trigger_time: str = None, uploaded_rows: list = None) -> dict:
    """对单个 bug 执行完整对比，复用 pipeline.compare_bug_analysis 并补充结论与兼容字段"""
    result = pipeline.compare_bug_analysis(bugid, trigger_time, uploaded_rows)
    # 生成结论描述
    if result.get("skipped"):
        conclusion = f"已跳过：{result.get('skip_reason', '未知原因')}"
    elif result["all_ok"]:
        conclusion = "分析正确：根因与评论对比均通过"
    elif result["root_cause_ok"]:
        conclusion = "需人工复核：根因匹配但评论对比不通过"
    elif result["comment_compare_ok"]:
        conclusion = "需人工复核：评论对比通过但根因不匹配"
    else:
        conclusion = "分析不一致：根因与评论对比均不通过，需人工复核"
    return {
        **result, "conclusion": conclusion, "error": None,
        "comments_total": len(result["comments"]),
        "comments_used": len(result["valid_comments"]),
        "truncated": len(result["valid_comments"]) < len(result["comments"]),
        "error_cause": result["bug_root_cause"],  # 兼容前端原有字段名
    }


@app.post("/api/test/comment_compare")
async def test_comment_compare(request: Request):
    """功能测试2：评论提取与对比（单条），返回评论原文、提取步骤及双重比对结果"""
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("bugid 不能为空")
    try:
        result = _compare_single_bug(bugid, body.get("trigger_time") or None)
        return _ok(result, "评论提取与对比完成")
    except Exception as e:
        logger.error("评论对比功能测试失败: %s", e)
        return _fail(str(e))


@app.post("/api/test/comment_compare_strategies")
async def comment_compare_strategies(request: Request):
    """评论分析侧重点对比：对同一 Jira 用多种 prompt 策略各跑一次评论分析，并列展示"""
    from src.core.filter import COMMENT_ANALYSIS_STRATEGIES, summarize_comments, generate_comment_analysis
    from src.clients import jira_client, diana_client as _dc
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("bugid 不能为空")
    try:
        # 获取评论和 AI 结论（只执行一次，所有策略共用）
        issue = jira_client.fetch_issue(bugid)
        comments = jira_client.extract_comments(issue)
        summaries = summarize_comments(comments)
        # 获取 AI 日志分析结论（优先本地文档，回退从多维表格查飞书链接再下载）
        ai_conclusion = ""
        try:
            ai_content = pipeline._get_ai_report_content(bugid, "")
            ai_conclusion = doc_generator.parse_conclusion(ai_content) or ""
        except Exception:
            # 本地无文档，从多维表格查找飞书链接
            feishu_link = ""
            try:
                from src.clients import feishu_client
                cfg_bitable = load_config().get("feishu_bitable", {})
                at = cfg_bitable.get("app_token", "")
                tid = cfg_bitable.get("table_id", "")
                bf = cfg_bitable.get("bugid_field", "jira号")
                lf = "AI分析结果(飞书链接)"
                if at and tid:
                    records = feishu_client.list_bitable_records(at, tid)
                    for rec in records:
                        fields = rec.get("fields", {})
                        bid_val = str(fields.get(bf, ""))
                        if bid_val == bugid:
                            link_val = fields.get(lf, "")
                            if isinstance(link_val, dict):
                                link_val = link_val.get("link", "") or link_val.get("text", "")
                            feishu_link = str(link_val).strip() if link_val else ""
                            break
            except Exception as e:
                logger.warning("从多维表格查找飞书链接失败: %s", e)
            if feishu_link:
                try:
                    ai_content = pipeline._get_ai_report_content(bugid, feishu_link)
                    ai_conclusion = doc_generator.parse_conclusion(ai_content) or ""
                except Exception as e:
                    logger.warning("bugid=%s 通过飞书链接下载AI报告失败: %s", bugid, e)
        # 提取 Jira 根因
        bug_rootcause = ""
        try:
            bug_rootcause = jira_client.extract_rootcause(issue) or ""
        except Exception:
            pass
        # 对每种策略各跑一次评论分析
        results = []
        for key, strategy in COMMENT_ANALYSIS_STRATEGIES.items():
            try:
                analysis = generate_comment_analysis(
                    summaries, ai_conclusion, style_instruction=strategy["instruction"])
                # 从分析结果提取排查结论段落
                conclusion_text = ""
                if analysis:
                    in_section = False
                    for line in analysis.split("\n"):
                        if "## 排查结论" in line or "### 排查结论" in line:
                            in_section = True
                            continue
                        if in_section and line.startswith("##"):
                            break
                        if in_section and line.strip():
                            conclusion_text += line.strip() + " "
                    conclusion_text = conclusion_text.strip()[:120]
                # 用 Diana 生成 8-20 字的表格结论
                table_conclusion = ""
                if conclusion_text:
                    try:
                        simplify_prompt = (
                            f"用一句话（8到20字）概括以下排查结论，偏bug分析方向，必须是完整语义，只输出概括本身：\n"
                            f"{conclusion_text}\n概括："
                        )
                        tc = _dc._llm_chat(simplify_prompt, max_tokens=50, timeout=15)
                        if tc:
                            from src.pipeline import _strip_conclusion_prefix
                            table_conclusion = _strip_conclusion_prefix(tc.strip().rstrip('。.'))
                    except Exception:
                        pass
                results.append({
                    "key": key, "label": strategy["label"],
                    "instruction": strategy["instruction"],
                    "analysis": analysis or "（生成失败）",
                    "bugid": bugid,
                    "root_cause": bug_rootcause[:100] if bug_rootcause else "（未提取）",
                    "table_conclusion": table_conclusion or conclusion_text[:40] or "（无）",
                    "has_ai_conclusion": bool(ai_conclusion),
                    "confidence_assessment": (
                        "高" if (analysis and ai_conclusion and conclusion_text)
                        else "中" if analysis and not analysis.startswith("（")
                        else "低"
                    ),
                })
            except Exception as e:
                results.append({
                    "key": key, "label": strategy["label"],
                    "instruction": strategy["instruction"],
                    "analysis": f"（异常: {str(e)[:60]}）",
                    "bugid": bugid, "root_cause": "（异常）",
                    "table_conclusion": "（异常）", "has_ai_conclusion": False,
                    "confidence_assessment": "低",
                })
        # 读取当前已保存的风格偏好
        cfg = load_config()
        current_style = cfg.get("comment_analysis", {}).get("style_keywords", "")
        return _ok({"strategies": results, "current_style": current_style,
                    "comments_count": len(comments), "summaries_count": len(summaries)},
                   f"对比完成: {len(results)} 种策略, {len(comments)} 条评论")
    except Exception as e:
        logger.error("评论分析侧重点对比失败: %s", e, exc_info=True)
        return _fail(f"对比失败: {e}")


@app.post("/api/test/save_style_preference")
async def save_style_preference(request: Request):
    """保存评论分析风格偏好到配置"""
    body = await request.json() or {}
    strategy_key = str(body.get("strategy_key", "")).strip()
    instruction = str(body.get("instruction", "")).strip()
    if not instruction:
        return _fail("instruction 不能为空")
    try:
        cfg = load_config()
        if "comment_analysis" not in cfg:
            cfg["comment_analysis"] = {}
        cfg["comment_analysis"]["style_keywords"] = instruction
        cfg["comment_analysis"]["strategy_key"] = strategy_key
        with open(cfg_module.CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        load_config(cfg_module.CONFIG_PATH)
        logger.info("评论分析风格偏好已保存: key=%s, keywords=%s", strategy_key, instruction[:40])
        return _ok({"strategy_key": strategy_key, "style_keywords": instruction},
                   f"风格偏好已保存: {instruction[:40]}")
    except Exception as e:
        logger.error("保存风格偏好失败: %s", e)
        return _fail(f"保存失败: {e}")


@app.post("/api/test/upload_bug_file")
async def upload_bug_file(file: UploadFile = File(None)):
    """上传 bug 单数据文件（CSV/Excel），解析后缓存，返回 file_id 供批量对比引用"""
    if not file or not file.filename:
        return _fail("未找到上传文件或文件名为空")
    try:
        content = await file.read()
        rows = bug_source.parse_uploaded_file(content, file.filename)
        if not rows:
            return _fail("文件中未找到有效数据或缺少 bugid 列")
        file_id = f"file_{len(_uploaded_files) + 1}"
        _uploaded_files[file_id] = rows
        logger.info("上传文件解析完成: file_id=%s, %d 行", file_id, len(rows))
        return _ok({"file_id": file_id, "row_count": len(rows)}, f"文件解析完成，共 {len(rows)} 条数据")
    except Exception as e:
        logger.error("文件上传解析失败: %s", e)
        return _fail(str(e))


@app.post("/api/test/batch_compare")
async def batch_compare(request: Request):
    """批量评论对比：支持分号/逗号分隔的 bugid 列表（最多 30 个），返回汇总表格"""
    body = await request.json() or {}
    raw_bugids = str(body.get("bugids", "")).strip()
    if not raw_bugids:
        return _fail("bugid 列表不能为空")
    bugids = _parse_bugids(raw_bugids)
    if not bugids:
        return _fail("未解析到有效 bugid")
    trigger_times = body.get("trigger_times") or {}
    # 获取上传文件数据（可选）
    file_id = body.get("file_id")
    uploaded_rows = _uploaded_files.get(file_id) if file_id else None
    try:
        results = []
        for bugid in bugids:
            try:
                result = _compare_single_bug(bugid, trigger_times.get(bugid), uploaded_rows)
                results.append(result)
            except Exception as e:
                logger.error("批量对比中 bugid=%s 失败: %s", bugid, e)
                results.append({
                    "bugid": bugid, "error": str(e)[:200],
                    "root_cause_ok": False, "comment_compare_ok": False, "all_ok": False,
                    "root_cause_score": 0.0, "layer1_score": 0.0, "layer2_score": 0.0,
                    "conclusion": f"分析异常: {str(e)[:80]}",
                })
        summary = {
            "total": len(results),
            "all_match_count": sum(1 for r in results if r.get("all_ok")),
            "root_cause_match_count": sum(1 for r in results if r.get("root_cause_ok")),
            "comment_match_count": sum(1 for r in results if r.get("comment_compare_ok")),
            "skipped_count": sum(1 for r in results if r.get("skipped")),
            "results": results,
        }
        return _ok(summary, f"批量对比完成: {len(results)} 个 bug")
    except Exception as e:
        logger.error("批量对比失败: %s", e)
        return _fail(str(e))


@app.post("/api/test/check_endpoints")
async def check_endpoints(request: Request):
    """接口连通性检测：逐个测试所有已配置 API 的可达性与响应"""
    import time as _time
    import httpx as _httpx
    cfg = load_config()
    results = []

    def _test(name, url, method, timeout=10, headers=None, json_body=None, data_body=None,
              truncate=True):
        t0 = _time.time()
        try:
            ht = _httpx.Timeout(timeout, connect=5)
            if method == "GET":
                r = _httpx.get(url, headers=headers, timeout=ht, follow_redirects=True)
            elif data_body:
                r = _httpx.post(url, data=data_body, headers=headers, timeout=ht)
            else:
                r = _httpx.post(url, json=json_body or {}, headers=headers, timeout=ht)
            elapsed = round(_time.time() - t0, 2)
            # 只要有 HTTP 响应（任何状态码），即认为可达
            ok = True
            try:
                raw = r.json()
                detail = raw if not truncate else str(raw)[:300]
            except Exception:
                detail = r.text if not truncate else r.text[:300]
            return {"name": name, "url": url, "ok": ok, "elapsed": elapsed,
                    "status_code": r.status_code, "detail": detail}
        except _httpx.ConnectTimeout:
            return {"name": name, "url": url, "ok": False,
                    "elapsed": round(_time.time() - t0, 2), "detail": "ConnectTimeout - 连接超时，服务不可达"}
        except _httpx.ReadTimeout:
            return {"name": name, "url": url, "ok": True,
                    "elapsed": round(_time.time() - t0, 2),
                    "detail": "ReadTimeout - 接口可达但响应超时（异步任务可能仍在执行）"}
        except _httpx.ConnectError as e:
            msg = str(e)
            if "10061" in msg:
                detail = "连接被拒绝，端口未开放"
            elif "getaddrinfo" in msg:
                detail = "DNS 解析失败"
            else:
                detail = f"ConnectError: {msg[:80]}"
            return {"name": name, "url": url, "ok": False,
                    "elapsed": round(_time.time() - t0, 2), "detail": detail}
        except Exception as e:
            return {"name": name, "url": url, "ok": False,
                    "elapsed": round(_time.time() - t0, 2),
                    "detail": f"{type(e).__name__}: {str(e)[:80]}"}

    # 1. AI 日志分析接口（异步接口，返回 200 即表示可达，不截断响应内容）
    ai_cfg = cfg.get("ai_log_api", {})
    if not ai_cfg.get("mock") and ai_cfg.get("url"):
        # 按实际 API 规格发送 issue_key + problem_time
        ai_body = {ai_cfg.get("bugid_field") or "issue_key": "VCU-501224"}
        time_field = ai_cfg.get("trigger_time_field") or ""
        if time_field:
            ai_body[time_field] = "2026-08-19 10:00:00"
        results.append(_test("AI 日志分析接口", ai_cfg["url"], "POST",
                             timeout=float(ai_cfg.get("timeout", 15)),
                             headers={"Content-Type": "application/json"},
                             json_body=ai_body,
                             truncate=False))

    # 2. Jira REST API
    jira_cfg = cfg.get("jira_api", {})
    if not jira_cfg.get("mock") and jira_cfg.get("url"):
        jira_url = jira_cfg["url"]
        if not jira_url.endswith("/issue"):
            jira_url = jira_url.rstrip("/") + "/issue"
        headers = {}
        if jira_cfg.get("auth_type") == "bearer" and jira_cfg.get("token"):
            headers["Authorization"] = f"Bearer {jira_cfg['token']}"
        results.append(_test("Jira REST API", f"{jira_url}/VCU-501224", "GET", headers=headers))

    ok_count = sum(1 for r in results if r["ok"])
    return _ok(results, f"检测完成：{ok_count}/{len(results)} 个接口可用")


@app.post("/api/test/internal_api")
async def test_internal_api(request: Request):
    """单独测试内网接口（AI日志/Diana/Token），返回完整原始响应"""
    import time as _time
    import httpx as _httpx
    body = await request.json() or {}
    which = body.get("which", "")
    cfg = body.get("config", {})
    t0 = _time.time()
    try:
        timeout = float(cfg.get("timeout", 15))
        ht = _httpx.Timeout(timeout, connect=8)
        if which == "ai_log":
            url = cfg.get("url", "")
            # bugid_field 是 API 参数名（如 issue_key），"VCU-501224" 为测试值
            param_name = cfg.get("bugid_field") or "issue_key"
            payload = {param_name: "VCU-501224"}
            # 排除 meta 配置字段，避免误发送给 API
            meta_keys = ("url", "timeout", "bugid_field", "trigger_time_field",
                         "mock", "custom_header")
            for k, v in cfg.items():
                if k not in meta_keys and v:
                    try:
                        payload[k] = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        payload[k] = v
            r = _httpx.post(url, json=payload, timeout=ht,
                            headers={"Content-Type": "application/json"})
        elif which == "feishu_bitable":
            # 飞书多维表格连通性测试：支持 Token/Cookie 两种模式
            from src.clients import feishu_client
            wiki_token = cfg.get("wiki_token", "")
            table_id = cfg.get("table_id", "")
            view_id = cfg.get("view_id", "")
            app_token = ""
            # 临时更新配置以便 feishu_client 使用
            import src.config as cfg_module
            original_cfg = cfg_module.load_config()
            merged = dict(original_cfg.get("feishu_bitable", {}))
            merged.update({k: v for k, v in cfg.items() if v})
            original_cfg["feishu_bitable"] = merged
            # 根据模式获取 app_token
            if feishu_client._is_cookie_mode():
                # Cookie 模式：从 wiki 页面提取
                if wiki_token:
                    app_token = feishu_client.cookie_get_app_token_from_wiki(wiki_token)
            else:
                # Token 模式：通过 Open API
                app_id = cfg.get("app_id", "")
                app_secret = cfg.get("app_secret", "")
                feishu_client.get_tenant_access_token(app_id, app_secret)
                if wiki_token:
                    try:
                        app_token = feishu_client.get_wiki_node_app_token(wiki_token)
                    except Exception:
                        app_token = wiki_token
            # 查询表格记录
            records = feishu_client.list_bitable_records(app_token, table_id, view_id)
            elapsed = round(_time.time() - t0, 2)
            mode = "Cookie" if feishu_client._is_cookie_mode() else "Token"
            return _ok({"ok": True, "elapsed": elapsed, "status_code": 200,
                         "response": {"record_count": len(records), "app_token": app_token,
                                      "mode": mode,
                                      "sample_fields": list(records[0].get("fields", {}).keys()) if records else []}})
        else:
            return _fail(f"未知接口类型: {which}")
        elapsed = round(_time.time() - t0, 2)
        # 完整原始响应，不做任何提取或截断
        try:
            raw = r.json()
        except Exception:
            raw = r.text
        # 内网接口连通性测试：只要服务器有 HTTP 响应（任何状态码），即认为可用。
        # HTTP 4xx/5xx 表示参数或服务端业务问题，不代表接口不可达。
        return _ok({"status_code": r.status_code, "response": raw,
                     "elapsed": elapsed, "ok": True})
    except _httpx.ConnectTimeout:
        return _ok({"ok": False, "elapsed": round(_time.time() - t0, 2),
                     "status_code": 0, "response": "ConnectTimeout - 连接超时，服务不可达"})
    except _httpx.ReadTimeout:
        return _ok({"ok": True, "elapsed": round(_time.time() - t0, 2),
                     "status_code": 0, "response": "ReadTimeout - 接口可达但响应超时（异步分析任务可能仍在后台执行）"})
    except _httpx.ConnectError as e:
        msg = str(e)
        detail = "连接被拒绝，端口未开放" if "10061" in msg else (
            "DNS 解析失败" if "getaddrinfo" in msg else f"ConnectError: {msg[:100]}")
        return _ok({"ok": False, "elapsed": round(_time.time() - t0, 2),
                     "status_code": 0, "response": detail})
    except Exception as e:
        return _ok({"ok": False, "elapsed": round(_time.time() - t0, 2),
                     "status_code": 0, "response": f"{type(e).__name__}: {str(e)}"})


@app.post("/api/test/diana_flow")
async def test_diana_flow(request: Request):
    """Diana 接口自动化流程：分步执行 Token 获取 → 对话接口调用 → 返回值提取，每步展示完整结果"""
    import time as _time
    import httpx as _httpx
    body = await request.json() or {}
    content = body.get("content", "回复OK").strip() or "回复OK"
    steps = []
    active = _diana_client._get_active_cfg()
    env = active.get("env", "test")
    # ── 步骤1：获取 Token ──
    t0 = _time.time()
    try:
        token_url = active["token_url"]
        token_data = {
            "scope": "ALL", "grant_type": "client_credentials",
            "client_id": active["client_id"],
            "client_secret": active["client_secret"],
        }
        ht = _httpx.Timeout(30, connect=8)
        r = _httpx.post(token_url, data=token_data, timeout=ht,
                        headers={"Content-Type": "application/x-www-form-urlencoded", "Connection": "close"})
        elapsed = round(_time.time() - t0, 2)
        try:
            token_resp = r.json()
        except Exception:
            token_resp = r.text
        token = token_resp.get("access_token", "") if isinstance(token_resp, dict) else ""
        expires_in = token_resp.get("expires_in", "-") if isinstance(token_resp, dict) else "-"
        steps.append({"step": "步骤1：获取 Token", "ok": r.status_code == 200 and bool(token),
                      "status_code": r.status_code, "elapsed": elapsed,
                      "request_url": token_url, "request_data": token_data,
                      "response": token_resp,
                      "summary": f"token 长度: {len(token)}, 有效期: {expires_in}s" if token else "Token 获取失败"})
        if not token:
            return _ok({"steps": steps, "env": env, "ok": False}, "Token 获取失败，流程终止")
    except _httpx.ConnectTimeout:
        steps.append({"step": "步骤1：获取 Token", "ok": False, "elapsed": round(_time.time() - t0, 2),
                      "response": "ConnectTimeout - 连接超时", "summary": "Token 服务不可达"})
        return _ok({"steps": steps, "env": env, "ok": False}, "Token 接口连接超时")
    except _httpx.ConnectError as e:
        msg = str(e)
        detail = "连接被拒绝，端口未开放" if "10061" in msg else ("DNS 解析失败" if "getaddrinfo" in msg else f"ConnectError: {msg[:100]}")
        steps.append({"step": "步骤1：获取 Token", "ok": False, "elapsed": round(_time.time() - t0, 2),
                      "response": detail, "summary": "Token 服务不可达"})
        return _ok({"steps": steps, "env": env, "ok": False}, "Token 接口不可达")
    except Exception as e:
        steps.append({"step": "步骤1：获取 Token", "ok": False, "elapsed": round(_time.time() - t0, 2),
                      "response": f"{type(e).__name__}: {str(e)}", "summary": "Token 获取异常"})
        return _ok({"steps": steps, "env": env, "ok": False}, f"Token 获取异常: {e}")
    # ── 步骤2：调用 Diana 对话接口 ──
    t1 = _time.time()
    try:
        api_url = active["url"]
        if active.get("api_key"):
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}", "x-api-key": active["api_key"]}
        else:
            headers = {"access_token": token, "Content-Type": "application/json",
                       "apiTag": "V1", "clientRequestId": "01", "client_id": active.get("client_id", "")}
        model = active.get("model", "deepseek-v-flash")
        payload = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 500, "temperature": 0}
        ht2 = _httpx.Timeout(60, connect=10)
        r2 = _httpx.post(api_url, json=payload, timeout=ht2, headers=headers)
        elapsed2 = round(_time.time() - t1, 2)
        try:
            api_resp = r2.json()
        except Exception:
            api_resp = r2.text
        extracted = ""
        if isinstance(api_resp, dict):
            extracted = api_resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        steps.append({"step": "步骤2：调用 Diana 对话接口", "ok": r2.status_code == 200,
                      "status_code": r2.status_code, "elapsed": elapsed2,
                      "request_url": api_url, "request_headers": {k: (v[:50] + "..." if len(str(v)) > 50 else v) for k, v in headers.items()},
                      "request_payload": payload, "response": api_resp,
                      "summary": f"HTTP {r2.status_code}, 提取内容长度: {len(extracted)}"})
    except _httpx.ConnectTimeout:
        steps.append({"step": "步骤2：调用 Diana 对话接口", "ok": False, "elapsed": round(_time.time() - t1, 2),
                      "response": "ConnectTimeout - 连接超时", "summary": "Diana API 不可达"})
        return _ok({"steps": steps, "env": env, "ok": False}, "Diana API 连接超时")
    except _httpx.ConnectError as e:
        msg = str(e)
        detail = "连接被拒绝" if "10061" in msg else ("DNS 解析失败" if "getaddrinfo" in msg else f"ConnectError: {msg[:100]}")
        steps.append({"step": "步骤2：调用 Diana 对话接口", "ok": False, "elapsed": round(_time.time() - t1, 2),
                      "response": detail, "summary": "Diana API 不可达"})
        return _ok({"steps": steps, "env": env, "ok": False}, "Diana API 不可达")
    except Exception as e:
        steps.append({"step": "步骤2：调用 Diana 对话接口", "ok": False, "elapsed": round(_time.time() - t1, 2),
                      "response": f"{type(e).__name__}: {str(e)}", "summary": "API 调用异常"})
        return _ok({"steps": steps, "env": env, "ok": False}, f"API 调用异常: {e}")
    # ── 步骤3：提取返回值 content ──
    steps.append({"step": "步骤3：提取返回值 content", "ok": bool(extracted),
                  "elapsed": 0, "extracted_content": extracted,
                  "extract_path": "choices[0].message.content",
                  "summary": f"提取成功，内容长度: {len(extracted)}" if extracted else "未提取到 content 内容"})
    return _ok({"steps": steps, "env": env, "ok": True,
                "config": {"env": env, "token_url": active["token_url"], "url": active["url"],
                           "model": model, "client_id": active.get("client_id", "")}},
               f"Diana 自动化流程执行完成（{env} 环境）")


@app.post("/api/test/feishu_im_query")
async def test_feishu_im_query(request: Request):
    """查询飞书 IM 对话消息：支持按群名查找或直接传 chat_id，返回最近消息"""
    import asyncio
    import traceback
    from src.clients import feishu_client
    body = await request.json() or {}
    chat_name = str(body.get("chat_name", "")).strip()
    chat_id = str(body.get("chat_id", "")).strip()
    start_time = str(body.get("start_time", "")).strip()
    page_size = int(body.get("page_size", 20))
    list_only = body.get("list_chats", False)  # 仅列出聊天，不查询消息
    loop = asyncio.get_event_loop()
    try:
        # 步骤1: 获取 chat_id
        step1 = {}
        if list_only or (not chat_id and not chat_name):
            # 列出所有聊天（群聊+单聊）
            all_chats = await loop.run_in_executor(None, feishu_client.list_chats, 100)
            chat_list = [{"chat_id": c.get("chat_id", ""), "name": c.get("name", ""),
                          "chat_type": c.get("chat_type", "")} for c in all_chats]
            return _ok({"chats": chat_list, "total": len(chat_list)},
                        f"共 {len(chat_list)} 个聊天")
        if not chat_id and chat_name:
            try:
                # 先查群聊，再查单聊
                chat_id = await loop.run_in_executor(None, feishu_client.find_chat_by_name, chat_name)
                step1 = {"action": "按名称查找", "chat_name": chat_name, "chat_id": chat_id or "未找到"}
            except Exception as e:
                step1 = {"action": "按名称查找", "chat_name": chat_name, "error": str(e)}
                return _fail(f"查找聊天失败: {e}", {"step1": step1})
        elif chat_id:
            step1 = {"action": "直接使用 chat_id", "chat_id": chat_id}
        if not chat_id:
            return _ok({"step1": step1}, f"未找到聊天 '{chat_name}'")
        # 步骤2: 拉取消息
        try:
            messages = await loop.run_in_executor(
                None, lambda: feishu_client.list_messages(chat_id, start_time=start_time or None, page_size=page_size))
        except Exception as e:
            return _fail(f"拉取消息失败: {e}", {"step1": step1})
        # 步骤3: 解析每条消息
        parsed = []
        for msg in messages:
            item = {"msg_type": msg.get("msg_type", ""), "create_time": msg.get("create_time", ""),
                    "sender": (msg.get("sender") or {}).get("sender_type", "")}
            body_content = msg.get("body", {}).get("content", "")
            if msg.get("msg_type") == "interactive" and body_content:
                import json as _json
                try:
                    card = _json.loads(body_content)
                    header = card.get("header", {})
                    title = (header.get("title", {}) or {}).get("content", "") if isinstance(header, dict) else ""
                    link = feishu_client.extract_report_link_from_card(msg)
                    item["card_title"] = title
                    item["report_link"] = link
                except Exception:
                    item["raw"] = body_content[:200]
            elif body_content:
                item["content"] = body_content[:300]
            parsed.append(item)
        return _ok({"step1": step1, "message_count": len(messages), "messages": parsed},
                    f"获取到 {len(messages)} 条消息")
    except Exception as e:
        logger.error("飞书 IM 查询失败: %s\n%s", e, traceback.format_exc())
        return _fail(str(e))


@app.post("/api/test/feishu_doc")
async def test_feishu_doc(request: Request):
    """飞书文档下载：支持直接传入链接或从表格查找，内网兼容"""
    import asyncio
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    feishu_link = str(body.get("feishu_link") or "").strip()
    if not bugid and not feishu_link:
        return _fail("bugid 或 feishu_link 至少提供一个")
    try:
        from src.clients import feishu_client
        loop = asyncio.get_event_loop()
        # 如果直接传入了飞书链接，跳过表格查找
        if feishu_link and feishu_link.startswith("http"):
            logger.info("使用直接传入的飞书链接: %s", feishu_link)
        else:
            # 从飞书表格查找记录
            record = await loop.run_in_executor(
                None, lambda: __import__("src.clients.feishu_client", fromlist=["find_record_by_bugid"]).find_record_by_bugid(bugid)
            )
            if not record:
                return _fail(f"飞书表格中未找到 bugid={bugid} 的记录")
            fields = record.get("fields", {})
            feishu_link = feishu_client.extract_report_from_bitable(fields)
            if not feishu_link or not feishu_link.startswith("http"):
                return _fail(f"未找到有效飞书链接，提取值: {feishu_link}")
        # 提取 doc_id 并下载文档
        doc_id = feishu_client.extract_doc_id_from_url(feishu_link)
        if not doc_id:
            return _fail(f"无法从链接提取文档 ID: {feishu_link}")
        feishu_domain = feishu_client.extract_domain_from_url(feishu_link)
        md_content = await loop.run_in_executor(
            None, lambda: feishu_client.fetch_docx_as_markdown(doc_id, bugid=bugid, feishu_domain=feishu_domain)
        )
        doc_path = doc_generator.save_document(bugid, md_content)
        return _ok({
            "doc_path": doc_path,
            "feishu_link": feishu_link,
            "doc_id": doc_id,
            "content_length": len(md_content),
            "content": md_content,
        }, f"飞书文档下载成功，内容长度 {len(md_content)} 字")
    except Exception as e:
        logger.error("飞书文档下载失败: %s", e)
        return _fail(f"{type(e).__name__}: {e}")


# ==================== 功能11：线上正确执行跟进 ====================

@app.post("/api/test/online_followup_compare")
async def online_followup_compare(request: Request):
    """对比 PC 执行成功 vs 线上执行成功，找出线上缺失/失败的 Jira"""
    import json as _json
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
    except Exception as e:
        return _fail(f"多维表格查询失败: {e}")
    # 分类收集 PC 和线上执行成功的记录
    pc_success = {}   # jira号 -> {记录摘要}
    online_success = {}  # jira号 -> {记录摘要}
    online_all = {}   # jira号 -> [{记录摘要}]（包含失败的）
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(cfg.get("bugid_field", "jira号"), ""))
        if not jira_no:
            continue
        result_status = _bitable_text(fields.get("分析结果", ""))
        source = _bitable_text(fields.get("触发来源", ""))
        done_time = _bitable_text(fields.get("分析完成时间", ""))
        entry = {
            "jira号": jira_no, "分析结果": result_status, "触发来源": source,
            "分析完成时间": done_time,
            "错误信息": _bitable_text(fields.get("错误信息", "")),
        }
        if result_status == "成功":
            if source == "jira_analyze":
                pc_success[jira_no] = entry
            elif source in ("parseFullTicket", "feishu_bot"):
                online_success[jira_no] = entry
        # 收集线上所有记录（含失败）
        if source in ("parseFullTicket", "feishu_bot"):
            online_all.setdefault(jira_no, []).append(entry)
    # 计算差集：PC 成功但线上未成功
    pc_keys = set(pc_success.keys())
    online_ok_keys = set(online_success.keys())
    overlap_keys = pc_keys & online_ok_keys  # PC 成功中线上也成功的
    diff_keys = pc_keys - online_ok_keys
    diff_records = []
    for k in sorted(diff_keys):
        pc_entry = pc_success[k]
        online_recs = online_all.get(k, [])
        online_failed = [r for r in online_recs if r["分析结果"] != "成功"]
        if online_failed:
            status = "线上失败"
            err = online_failed[-1]["错误信息"][:100]
        else:
            status = "线上未执行"
            err = ""
        diff_records.append({
            "jira号": k, "pc分析完成时间": pc_entry["分析完成时间"],
            "线上状态": status, "线上错误信息": err,
        })
    # 保存到本地 data/online_followup/
    date_str = datetime.now().strftime("%Y-%m-%d")
    save_dir = os.path.join(PROJECT_ROOT, "data", "online_followup")
    os.makedirs(save_dir, exist_ok=True)
    result_data = {
        "date": date_str,
        "pc_success_count": len(pc_success),
        "online_success_count": len(online_success),  # 触发来源为线上且分析结果为成功的总数
        "diff_count": len(diff_records),
        "diff_records": diff_records,
        "pc_success_jiras": sorted(pc_keys),
        "online_success_jiras": sorted(online_ok_keys),
    }
    save_path = os.path.join(save_dir, f"{date_str}_diff.json")
    latest_path = os.path.join(save_dir, "latest.json")
    with open(save_path, "w", encoding="utf-8") as f:
        _json.dump(result_data, f, ensure_ascii=False, indent=2)
    with open(latest_path, "w", encoding="utf-8") as f:
        _json.dump(result_data, f, ensure_ascii=False, indent=2)
    return _ok(result_data,
               f"PC成功 {len(pc_success)} 条，线上成功 {len(online_success)} 条，差集 {len(diff_records)} 条")


@app.get("/api/test/online_followup_load")
def online_followup_load(date: str = None):
    """加载已保存的线上跟进对比结果"""
    import json as _json
    save_dir = os.path.join(PROJECT_ROOT, "data", "online_followup")
    if date:
        path = os.path.join(save_dir, f"{date}_diff.json")
    else:
        path = os.path.join(save_dir, "latest.json")
    if not os.path.exists(path):
        return _ok(None, "无历史对比数据")
    with open(path, "r", encoding="utf-8") as f:
        data = _json.load(f)
    return _ok(data, f"已加载 {data.get('date', '')} 对比数据")


# ==================== 冒烟测试：多维表格查询 ====================

@app.post("/api/test/smoke_test_query")
async def smoke_test_query(request: Request):
    """冒烟测试：查询指定 Jira 号在多维表格中 exec_time 之后最接近的分析记录"""
    body = await request.json() or {}
    jira_ids = [b.strip().upper() for b in (body.get("jira_ids") or []) if b.strip()]
    if not jira_ids:
        return _fail("请输入 Jira 号")
    exec_time = (body.get("exec_time") or "").strip()  # 执行时间，过滤分析完成时间 >= 此时间的记录
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
    except Exception as e:
        logger.error("冒烟测试查询：多维表格查询失败: %s", e)
        return _fail(f"多维表格查询失败: {e}")
    target_set = set(jira_ids)
    picked = {}  # jira号 -> exec_time 之后最接近的记录
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(bugid_field, ""))
        if not jira_no or jira_no not in target_set:
            continue
        done_time = _bitable_text(fields.get("分析完成时间", ""))
        # 有执行时间时，仅保留分析完成时间 >= 执行时间的记录
        if exec_time and done_time and done_time < exec_time:
            continue
        prev = picked.get(jira_no)
        if prev is None or done_time < prev.get("分析完成时间", ""):
            # 取 exec_time 之后最早的一条（最接近执行时间的）
            row = _flatten_bitable_record(fields, report_field)
            row["jira号"] = jira_no
            picked[jira_no] = row
    rows = sorted(picked.values(), key=lambda r: r.get("分析完成时间", ""))
    return _ok({"rows": rows, "count": len(rows)},
               f"查询到 {len(rows)} 条记录（共 {len(jira_ids)} 个 Jira 号）")


@app.post("/api/test/smoke_test_save_record")
async def smoke_test_save_record(request: Request):
    """冒烟测试：生成执行记录文档，保存本地并上传云端"""
    body = await request.json() or {}
    version = (body.get("version") or "-").strip() or "-"
    exec_time = (body.get("exec_time") or "").strip()
    results = body.get("results") or []  # [{case_name, jira_id, bitable_record}]
    basic_fields = body.get("basic_fields") or {}  # {分析并发数, 下载并发数, 模型, 触发来源}
    if not exec_time:
        return _fail("缺少执行时间")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y-%m-%d")
    # 构建 Markdown 内容
    lines = [
        f"# 冒烟测试执行记录 - {date_str}", "",
        f"## 基本信息", "",
        f"- **版本号**：{version}",
        f"- **执行时间**：{exec_time}",
        f"- **记录生成时间**：{now_str}", "",
        f"## 接口配置", "",
        f"- 分析并发数：{basic_fields.get('analysis_concurrency', '-')}",
        f"- 下载并发数：{basic_fields.get('download_concurrency', '-')}",
        f"- 模型：{basic_fields.get('model', '-')}",
        f"- 触发来源：{basic_fields.get('trigger_source', '-')}", "",
        f"## 用例配置", "",
    ]
    for r in results:
        lines.append(f"- {r.get('case_name', '?')}：{r.get('jira_id', '-')}")
    lines.append("")
    lines.append("## 执行结果")
    lines.append("")
    lines.append("| 用例 | Jira号 | 是否成功 | 分析耗时 | 总耗时 | 错误原因 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for r in results:
        rec = r.get("bitable_record") or {}
        case_name = r.get("case_name", "?")
        jira_id = r.get("jira_id", "-")
        result_status = rec.get("分析结果", "-") or "-"
        is_success = "是" if result_status == "成功" else "否"
        # 分析耗时：从分析问题时间和分析完成时间计算
        start_t = rec.get("分析问题时间", "")
        end_t = rec.get("分析完成时间", "")
        analysis_dur = _calc_smoke_duration(start_t, end_t)
        # 总耗时：同上（冒烟测试场景下二者等价）
        total_dur = analysis_dur
        # 错误原因
        error_reason = ""
        if result_status != "成功":
            error_reason = rec.get("错误信息", "") or rec.get("rootcause", "") or "-"
        else:
            error_reason = "-"
        lines.append(f"| {case_name} | {jira_id} | {is_success} | {analysis_dur} | {total_dur} | {error_reason} |")
    md_content = "\n".join(lines)
    # 本地保存
    local_dir = os.path.join(PROJECT_ROOT, "data", "smoke_test")
    os.makedirs(local_dir, exist_ok=True)
    time_suffix = datetime.now().strftime("%H%M%S")
    local_path = os.path.join(local_dir, f"冒烟测试_{date_str}_{time_suffix}.md")
    try:
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(md_content)
    except Exception as e:
        logger.warning("冒烟测试记录本地保存失败: %s", e)
        local_path = ""
    # 云端上传
    cloud_url = ""
    try:
        from src.clients import feishu_client
        cfg = load_config().get("feishu_bitable", {})
        folder_token = cfg.get("smoke_test_folder", "") or cfg.get("drive_folder", "")
        doc_title = f"冒烟测试_{date_str}_{time_suffix}"
        result = feishu_client.create_docx_document(doc_title, md_content, folder_token)
        cloud_url = result.get("url", "")
    except Exception as e:
        logger.warning("冒烟测试记录云端上传失败: %s", e)
    return _ok({"local_path": local_path, "cloud_url": cloud_url}, "冒烟测试记录已保存")


def _calc_smoke_duration(start: str, end: str) -> str:
    """计算冒烟测试耗时：分析问题时间 ~ 分析完成时间"""
    if not start or not end:
        return "-"
    try:
        from datetime import datetime as _dt
        s = _dt.strptime(start.strip()[:19], "%Y-%m-%d %H:%M:%S")
        e = _dt.strptime(end.strip()[:19], "%Y-%m-%d %H:%M:%S")
        sec = max(0, int((e - s).total_seconds()))
        if sec < 60:
            return f"{sec}秒"
        return f"{sec // 60}分{sec % 60}秒"
    except Exception:
        return "-"


# ==================== 功能11扩展：错误统计查询 ====================

@app.post("/api/test/error_stats")
async def error_stats_query(request: Request):
    """错误统计：查询多维表格中分析失败的 Jira 号，聚合失败次数/最新人工审核原因/是否有成功记录"""
    body = await request.json() or {}
    after_time = str(body.get("after_time", "")).strip()
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
    except Exception as e:
        logger.error("错误统计查询：多维表格查询失败: %s", e)
        return _fail(f"多维表格查询失败: {e}")
    cutoff = _ts_parse_datetime(after_time) if after_time else None
    # 按 Jira 号聚合
    stats = {}  # jira号 -> entry
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(bugid_field, ""))
        if not jira_no:
            continue
        result_status = _bitable_text(fields.get("分析结果", ""))
        done_time = _bitable_text(fields.get("分析完成时间", ""))
        # 时间过滤
        if cutoff and done_time:
            done_dt = _ts_parse_datetime(done_time)
            if not done_dt or done_dt <= cutoff:
                continue
        entry = stats.setdefault(jira_no, {
            "jira号": jira_no, "失败次数": 0,
            "最新人工审核原因": "", "有成功记录": False,
            "最新失败时间": "", "_review_done": "", "_review_result": "",
        })
        if result_status == "成功":
            entry["有成功记录"] = True
        elif result_status == "失败":
            entry["失败次数"] += 1
            if done_time > entry["最新失败时间"]:
                entry["最新失败时间"] = done_time
        # 跟踪有人工审核结果的最新记录
        review = _bitable_text(fields.get("人工审核结果", ""))
        if review and done_time > entry["_review_done"]:
            entry["_review_done"] = done_time
            entry["_review_result"] = result_status
            entry["最新人工审核原因"] = review
    # 过滤：有人工审核结果 且 该条记录分析结果为失败
    rows = [v for v in stats.values()
            if v["_review_result"] == "失败" and v["最新人工审核原因"]]
    rows.sort(key=lambda r: -r["失败次数"])
    # 并发从 Jira 获取每个 Jira 号附件中的 gmlogger 文件名
    import asyncio
    from src.clients import jira_client as _jc
    loop = asyncio.get_event_loop()
    async def _fetch_gmlogger(jira_id):
        try:
            issue = await asyncio.wait_for(
                loop.run_in_executor(None, _jc.fetch_issue, jira_id), timeout=15)
            atts = ((issue.get("fields") or {}).get("attachment") or [])
            names = [a.get("filename", "") for a in atts
                     if a.get("filename", "") and "gmlogger" in a.get("filename", "").lower()]
            return ", ".join(names) if names else ""
        except Exception:
            return ""
    jira_ids = list({r["jira号"] for r in rows})
    if jira_ids:
        results = await asyncio.gather(*[_fetch_gmlogger(j) for j in jira_ids])
        gm_map = dict(zip(jira_ids, results))
        for r in rows:
            r["gmlogger文件"] = gm_map.get(r["jira号"], "")
    # 清理内部字段
    for r in rows:
        r.pop("_review_done", None)
        r.pop("_review_result", None)
    return _ok({"rows": rows, "count": len(rows)},
               f"统计到 {len(rows)} 个 Jira 号存在失败记录")


# ==================== 功能12：AI日志分析自学习内容可视化 ====================

# AI日志分析服务的接口地址
_AI_LOG_SERVICE_URL = "http://10.22.126.133:8001"


def _fetch_ai_logs(name: str = "all", limit: int = 5000) -> list:
    """从AI日志分析服务读取日志内容"""
    import urllib.request
    url = f"{_AI_LOG_SERVICE_URL}/api/logs?name={name}&start_line=1&limit={min(limit, 5000)}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            data = _json.loads(raw)
            # 兼容多种返回格式
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("logs") or data.get("data") or data.get("lines") or []
            return []
    except Exception as e:
        logger.error("读取AI日志失败: %s", e)
        raise


def _parse_ai_log_lines(lines: list, jira_id: str) -> dict:
    """解析日志行，按 Jira 号过滤并按分析轮次分组

    返回结构:
    {
      "rounds": [
        {"round": 1, "entries": [{"line_no": int, "time": str, "type": str, "content": str}, ...]},
        ...
      ],
      "total_lines": int,
      "matched_lines": int
    }
    """
    jira_upper = jira_id.upper().strip()
    matched = []
    for i, line in enumerate(lines):
        line_str = str(line).strip() if not isinstance(line, str) else line.strip()
        if not line_str:
            continue
        if jira_upper and jira_upper not in line_str.upper():
            continue
        matched.append({"line_no": i + 1, "raw": line_str})
    # 按分析轮次分组：识别"轮"、"round"、"第.*次"等关键词
    rounds = []
    current_round = {"round": 1, "entries": []}
    round_counter = 1
    for item in matched:
        raw = item["raw"]
        # 检测是否是新轮次的开始
        new_round = False
        if re.search(r'第\s*\d+\s*轮', raw) or re.search(r'round\s*\d+', raw, re.I):
            round_counter += 1
            new_round = True
        elif re.search(r'分析开始|开始分析|start.*analy', raw, re.I):
            round_counter += 1
            new_round = True
        elif re.search(r'={5,}|-{5,}|\*{5,}', raw) and len(current_round["entries"]) > 0:
            round_counter += 1
            new_round = True
        if new_round and current_round["entries"]:
            rounds.append(current_round)
            current_round = {"round": round_counter, "entries": []}
        # 识别条目类型
        entry_type = "其他"
        if re.search(r'知识库|knowledge|\.md|\.txt|文件', raw, re.I):
            entry_type = "知识库调用"
        elif re.search(r'结果|result|成功|失败|rootcause|根因|结论', raw, re.I):
            entry_type = "分析结果"
        elif re.search(r'评论|comment|jira.*评论', raw, re.I):
            entry_type = "评论分析"
        elif re.search(r'触发时间|trigger.*time', raw, re.I):
            entry_type = "触发时间"
        elif re.search(r'视频|video|ocr', raw, re.I):
            entry_type = "视频/OCR"
        elif re.search(r'置信度|confidence', raw, re.I):
            entry_type = "置信度"
        elif re.search(r'提取|extract', raw, re.I):
            entry_type = "提取"
        # 提取时间戳
        time_str = ""
        tm = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2})', raw)
        if tm:
            time_str = tm.group(1)
        current_round["entries"].append({
            "line_no": item["line_no"],
            "time": time_str,
            "type": entry_type,
            "content": raw[:500],  # 截断过长内容
        })
    if current_round["entries"]:
        rounds.append(current_round)
    return {
        "rounds": rounds,
        "total_lines": len(lines),
        "matched_lines": len(matched),
    }


@app.post("/api/test/ai_log_visual")
async def ai_log_visual(request: Request):
    """读取AI日志分析服务的日志，按 Jira 号过滤并分组展示"""
    body = await request.json() or {}
    jira_id = str(body.get("jira_id", "")).strip()
    log_name = str(body.get("log_name", "all")).strip()
    limit = int(body.get("limit", 5000))
    if not jira_id:
        return _fail("请输入 Jira 号")
    if log_name not in ("all", "app", "perf"):
        log_name = "all"
    try:
        lines = _fetch_ai_logs(name=log_name, limit=limit)
        result = _parse_ai_log_lines(lines, jira_id)
        result["jira_id"] = jira_id
        result["log_name"] = log_name
        return _ok(result, f"读取 {len(lines)} 行日志，匹配 {result['matched_lines']} 行，{len(result['rounds'])} 轮分析")
    except Exception as e:
        return _fail(f"读取日志失败: {e}")


# ==================== 本地文档分析（study目录） ====================

_STUDY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "study")


def _scan_study_folders(jira_id: str = "") -> list:
    """扫描 study 目录，找到包含推理轮次文件的文件夹。jira_id 为空时列出全部"""
    results = []
    if not os.path.isdir(_STUDY_DIR):
        return results
    for entry in os.listdir(_STUDY_DIR):
        if jira_id and not entry.upper().startswith(jira_id.upper()):
            continue
        top_dir = os.path.join(_STUDY_DIR, entry)
        if not os.path.isdir(top_dir):
            continue
        for root, dirs, files in os.walk(top_dir):
            if "02_reasoning_rounds.md" in files:
                results.append({
                    "name": os.path.relpath(root, _STUDY_DIR),
                    "path": root,
                })
    return results


def _parse_reasoning_rounds(folder_path: str) -> dict:
    """解析 02_reasoning_rounds.md，提取每轮的推理、工具结果、知识库、耗时"""
    rounds_path = os.path.join(folder_path, "02_reasoning_rounds.md")
    if not os.path.isfile(rounds_path):
        return {"rounds": [], "total_rounds": 0, "elapsed_seconds": 0}
    with open(rounds_path, "r", encoding="utf-8") as f:
        content = f.read()
    # 读取总耗时
    elapsed = 0
    budget_path = os.path.join(folder_path, "05_budget_observation.json")
    if os.path.isfile(budget_path):
        try:
            with open(budget_path, "r", encoding="utf-8") as f:
                budget = json.loads(f.read())
            elapsed = budget.get("elapsed_seconds", 0)
        except Exception:
            pass
    # 读取结论
    conclusions = []
    adj_path = os.path.join(folder_path, "03_adjudication_result.json")
    if os.path.isfile(adj_path):
        try:
            with open(adj_path, "r", encoding="utf-8") as f:
                adj = json.loads(f.read())
            for c in adj.get("conclusions", []):
                conclusions.append({
                    "statement": c.get("statement", ""),
                    "confidence": c.get("confidence", ""),
                    "severity": c.get("severity", ""),
                    "category": c.get("category", ""),
                })
        except Exception:
            pass
    # 按 ## 分割轮次
    import re as _re
    sections = _re.split(r'^## ', content, flags=_re.MULTILINE)
    rounds_map = {}  # {round_num: {"llm": "", "tools": "", "knowledge": []}}
    for sec in sections:
        m = _re.match(r'第\s*(\d+)\s*轮\s*—\s*(.*)', sec)
        if not m:
            continue
        rn = int(m.group(1))
        sec_type = m.group(2).strip()
        sec_body = sec[m.end():].strip()
        if rn not in rounds_map:
            rounds_map[rn] = {"llm": "", "tools": [], "knowledge": []}
        if "LLM" in sec_type or "响应" in sec_type:
            # 截取前500字符作为摘要，去除尾部空白和分隔线 ---
            raw = sec_body[:500]
            # 循环去除尾部的 --- 分隔线和空白行
            while _re.search(r'\n\s*[-–—]{2,}\s*$', raw):
                raw = _re.sub(r'\n\s*[-–—]{2,}\s*$', '', raw)
            raw = raw.rstrip()  # 去除最后一个文字后的所有空白
            rounds_map[rn]["llm"] = raw
        elif "工具" in sec_type or "执行" in sec_type:
            # 解析工具结果
            tool_results = _re.findall(r'\[结果\s*\d+\]\s*(.+?)(?:\n|$)', sec_body)
            rounds_map[rn]["tools"] = [t.strip()[:100] for t in tool_results]
            # 解析知识库
            wiki_matches = _re.findall(r'WIKI.*?\[knowledge_list\]:\s*\n(.*?)(?:\n---|\Z)', sec_body, _re.DOTALL)
            for wiki_block in wiki_matches:
                kb_items = _re.findall(r'-\s*(.+?)(?:\n|$)', wiki_block)
                rounds_map[rn]["knowledge"].extend([k.strip() for k in kb_items if k.strip()])
    # 组装结果
    total_rounds = len(rounds_map)
    avg_time = round(elapsed / total_rounds, 1) if total_rounds else 0
    rounds_list = []
    for rn in sorted(rounds_map.keys()):
        r = rounds_map[rn]
        rounds_list.append({
            "round": rn,
            "llm_summary": r["llm"],
            "tool_count": len(r["tools"]),
            "tools": r["tools"],
            "knowledge": r["knowledge"],
            "knowledge_count": len(r["knowledge"]),
            "avg_time": avg_time,
        })
    return {
        "rounds": rounds_list,
        "total_rounds": total_rounds,
        "elapsed_seconds": round(elapsed, 1),
        "conclusions": conclusions,
    }


@app.post("/api/test/study_analysis")
async def study_analysis(request: Request):
    """本地文档分析：扫描study目录或解析指定文件夹的推理轮次"""
    body = await request.json() or {}
    folder_path = str(body.get("folder_path", "")).strip()
    try:
        if folder_path:
            # 解析指定文件夹
            if not os.path.isdir(folder_path):
                return _fail(f"文件夹不存在: {folder_path}")
            result = _parse_reasoning_rounds(folder_path)
            result["folder_name"] = os.path.relpath(folder_path, _STUDY_DIR)
            return _ok(result, f"解析完成，共 {result['total_rounds']} 轮分析，总耗时 {result['elapsed_seconds']}秒")
        else:
            # 扫描全部文件夹
            folders = _scan_study_folders()
            if not folders:
                return _fail("study 目录下未找到任何分析文档")
            return _ok({"folders": folders}, f"找到 {len(folders)} 个分析文件夹")
    except Exception as e:
        return _fail(f"分析失败: {e}")


# ========== 功能13：配置参数调优 ==========


def _scan_all_batch_records() -> list:
    """扫描所有批量执行记录（本地 + 云端），返回批次列表

    :return: [{batch_id, date, name, source, total, success, fail, base_info, jira_list}]
    """
    batches = []
    doc_dir = get_path("doc_dir")

    def _process_csv(path: str, date_str: str, name: str) -> dict:
        """处理单个 CSV 文件，返回批次信息"""
        rows = _read_csv_rows(path)
        if not rows:
            return None
        jira_list = []
        success = 0
        source = ""
        base_info = {"分析并发数": "", "下载并发数": "", "模型": ""}
        for r in rows:
            jira_no = (r.get("jira号") or r.get("Jira号") or "").strip()
            if jira_no:
                jira_list.append(jira_no)
            if (r.get("执行结果") or "").strip() == "成功":
                success += 1
            src = (r.get("触发来源") or "").strip()
            if src:
                source = src
            # 取第一条的基础信息
            if not base_info["分析并发数"]:
                base_info["分析并发数"] = (r.get("分析并发数") or "").strip()
                base_info["下载并发数"] = (r.get("下载并发数") or "").strip()
                base_info["模型"] = (r.get("模型") or "").strip()
        return {
            "date": date_str, "name": name, "source": source,
            "total": len(rows), "success": success, "fail": len(rows) - success,
            "base_info": base_info, "jira_list": jira_list,
        }

    # 路径1：本地 docs/日期/batch_*.csv
    if os.path.isdir(doc_dir):
        for date_folder in sorted(os.listdir(doc_dir), reverse=True):
            day_dir = os.path.join(doc_dir, date_folder)
            if not os.path.isdir(day_dir):
                continue
            for fname in sorted(os.listdir(day_dir)):
                if not fname.lower().startswith("batch_") or not fname.endswith(".csv"):
                    continue
                info = _process_csv(os.path.join(day_dir, fname), date_folder, fname.replace(".csv", ""))
                if info:
                    info["batch_id"] = f"{date_folder}/{fname.replace('.csv', '')}"
                    batches.append(info)

    # 路径2：本地 data/unanalyzed/prod_batch_*.csv
    unanalyzed_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "unanalyzed")
    if os.path.isdir(unanalyzed_dir):
        for fname in sorted(os.listdir(unanalyzed_dir)):
            if not fname.startswith("prod_batch_") or not fname.endswith(".csv"):
                continue
            parts = fname.replace(".csv", "").split("_")
            date_str = f"{parts[2]}-{parts[3]}-{parts[4]}" if len(parts) >= 5 else ""
            info = _process_csv(os.path.join(unanalyzed_dir, fname), date_str, fname.replace(".csv", ""))
            if info:
                info["batch_id"] = f"unanalyzed/{fname.replace('.csv', '')}"
                batches.append(info)

    # 路径3：云端批次记录
    try:
        from src.clients import feishu_client
        folder_token = load_config().get("feishu_bitable", {}).get("batch_folder_token", "")
        if folder_token:
            all_files = feishu_client.list_folder_files(folder_token, recursive=True)
            seen_ids = {b["batch_id"] for b in batches}
            for f in all_files:
                if f.get("type") != "docx":
                    continue
                fname = f.get("name", "")
                f_folder = f.get("folder", "")
                doc_token = f.get("token", "")
                if not doc_token or not fname.startswith(("批量执行", "线上批量执行")):
                    continue
                bid = f"cloud/{f_folder}/{fname}"
                if bid in seen_ids:
                    continue
                try:
                    md = feishu_client.fetch_docx_as_markdown(doc_token)
                    batch_rows = _parse_markdown_batch_table(md)
                    if not batch_rows:
                        continue
                    jira_list = []
                    success = 0
                    source = ""
                    base_info = {"分析并发数": "", "下载并发数": "", "模型": ""}
                    for r in batch_rows:
                        jira_no = (r.get("jira号") or r.get("Jira号") or "").strip()
                        if jira_no:
                            jira_list.append(jira_no)
                        if (r.get("执行结果") or "").strip() == "成功":
                            success += 1
                        src = (r.get("触发来源") or "").strip()
                        if src:
                            source = src
                        if not base_info["分析并发数"]:
                            base_info["分析并发数"] = (r.get("分析并发数") or "").strip()
                            base_info["下载并发数"] = (r.get("下载并发数") or "").strip()
                            base_info["模型"] = (r.get("模型") or "").strip()
                    # 云端批次 source 推断：优先从 CSV 字段读取，否则从文档名推断
                    if not source:
                        if fname.startswith("线上批量执行"):
                            source = "parseFullTicket"
                        elif fname.startswith("批量执行") and "_bot_online_" in fname:
                            source = "parseFullTicket"
                        elif fname.startswith("批量执行"):
                            source = "jira_analyze"
                    batches.append({
                        "batch_id": bid, "date": f_folder, "name": fname,
                        "source": source,
                        "total": len(batch_rows), "success": success,
                        "fail": len(batch_rows) - success,
                        "base_info": base_info, "jira_list": jira_list,
                    })
                    seen_ids.add(bid)
                except Exception as e:
                    logger.warning("读取云端批次 %s 失败: %s", fname, e)
    except Exception as e:
        logger.warning("扫描云端批次记录失败: %s", e)

    # 按日期倒序
    batches.sort(key=lambda x: x.get("date", ""), reverse=True)
    return batches


@app.get("/api/tuning/batch_list")
def tuning_batch_list(source: str = ""):
    """配置参数调优：列出所有批量执行批次，按 source 过滤（pc/online/空=全部）"""
    all_batches = _scan_all_batch_records()
    if source:
        # PC = jira_analyze, 线上 = parseFullTicket
        src_filter = "jira_analyze" if source == "pc" else "parseFullTicket" if source == "online" else ""
        if src_filter:
            all_batches = [b for b in all_batches if b.get("source", "") == src_filter]
    # 不返回完整 jira_list 给前端（太大），只返回数量
    result = []
    for b in all_batches:
        item = {k: v for k, v in b.items() if k != "jira_list"}
        item["jira_count"] = len(b.get("jira_list", []))
        result.append(item)
    return _ok(result, f"找到 {len(result)} 个批次")


@app.post("/api/tuning/analyze")
async def tuning_analyze(request: Request):
    """配置参数调优：对选中的批次查多维表格，计算成功率/分析耗时等指标"""
    body = await request.json() or {}
    batch_ids = body.get("batch_ids") or []
    if not batch_ids:
        return _fail("请选择至少一个批次")
    all_batches = _scan_all_batch_records()
    id_map = {b["batch_id"]: b for b in all_batches}
    # 收集所有 jira 号
    all_jiras = set()
    selected_batches = []
    for bid in batch_ids:
        b = id_map.get(bid)
        if b:
            selected_batches.append(b)
            all_jiras.update(b.get("jira_list", []))
    if not selected_batches:
        return _fail("未找到匹配的批次")
    # 查多维表格
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token, table_id = cfg.get("app_token", ""), cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    bt_map = {}  # {jira_no: [records]}
    if app_token and table_id:
        try:
            records = feishu_client.list_bitable_records(app_token, table_id)
            for rec in records:
                fields = rec.get("fields", {})
                jira_key = _bitable_text(fields.get(bugid_field, ""))
                if jira_key and jira_key in all_jiras:
                    bt_map.setdefault(jira_key, []).append(
                        _flatten_bitable_record_all(fields, cfg.get("report_field", "")))
        except Exception as e:
            logger.warning("调优分析：多维表格查询失败: %s", e)
            return _fail(f"多维表格查询失败: {e}")
    # 对每个批次计算指标
    results = []
    for b in selected_batches:
        jira_list = b.get("jira_list", [])
        success = 0
        fail = 0
        analysis_times = []  # 分析耗时（秒）
        version = "-"
        for jira_no in jira_list:
            bt_records = bt_map.get(jira_no, [])
            if not bt_records:
                continue
            # 取最新记录
            bt_records.sort(key=lambda x: x.get("分析完成时间", ""))
            bf = bt_records[-1]
            result_status = bf.get("分析结果", "")
            if result_status == "成功":
                success += 1
            elif result_status == "失败":
                fail += 1
            # 版本号：取第一个非空值
            if version == "-":
                v = (bf.get("版本号") or "").strip()
                if v:
                    version = v
            # 解析分析耗时
            dur_sec = _parse_dur_sec(bf.get("分析耗时", ""))
            if dur_sec > 0:
                analysis_times.append(dur_sec)
        total = success + fail
        rate = f"{success / total * 100:.1f}%" if total else "0%"
        avg_time = _format_dur(sum(analysis_times) / len(analysis_times)) if analysis_times else "-"
        sorted_times = sorted(analysis_times)
        median_time = _format_dur(sorted_times[len(sorted_times) // 2]) if sorted_times else "-"
        results.append({
            "batch_id": b["batch_id"],
            "date": b["date"],
            "name": b["name"],
            "version": version,
            "base_info": b.get("base_info", {}),
            "total": b.get("total", 0),
            "matched": total,
            "success": success,
            "fail": fail,
            "success_rate": rate,
            "avg_analysis_time": avg_time,
            "median_analysis_time": median_time,
            "analysis_times": analysis_times,
        })
    return _ok({"batches": results}, f"分析完成，{len(results)} 个批次")
