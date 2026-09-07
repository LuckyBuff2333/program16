"""Web 后端服务：基于 FastAPI 提供配置管理、流程执行、报表查询等 REST API"""
import asyncio
import json
import os
import re
import signal
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

app = FastAPI(title="Bug 文档沉淀工具", docs_url="/api/docs")


@app.on_event("startup")
async def _on_startup():
    """服务启动初始化：过滤 favicon 日志 + 就绪后打开浏览器"""
    import logging
    import tempfile

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


def _feishu_ws_event_handler(data):
    """长连接统一事件回调：文本消息→机器人命令；卡片消息→复用现有报告链接解析"""
    try:
        msg = data.event.message
        msg_type = msg.message_type
        if msg_type == "text":
            content = json.loads(msg.content or "{}")
            # 去除群聊 @机器人 的 mention 占位符与首尾标点，保留纯命令文本（兼容 "@机器人，1" 等输入）
            text = re.sub(r"@_user_\d+", "", content.get("text", "")).strip().strip(" \t,，.。!！")
            if text:
                _process_bot_command(msg.chat_id, text)
        elif msg_type == "interactive":
            # 卡片事件（AI分析完成通知）走现有解析链路，兼容 dict 结构
            _process_feishu_message_event({
                "message": {"chat_id": msg.chat_id, "message_type": msg_type,
                            "content": msg.content, "create_time": msg.create_time},
                "sender": {},
            })
    except Exception as e:
        logger.warning("处理飞书长连接事件失败: %s", e)


# 机器人会话超时时间（秒）
_BOT_SESSION_TIMEOUT = 120


def _set_bot_session(chat_id: str, state: str):
    """设置机器人会话状态并启动 2 分钟自动超时定时器"""
    import threading
    # 取消旧的定时器
    old = _bot_sessions.get(chat_id)
    if old and old.get("timer"):
        old["timer"].cancel()
    # 设置新会话
    _bot_sessions[chat_id] = {"state": state, "created_at": datetime.now(), "timer": None}
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
    """机器人命令状态机：输入 1 进入 AI 分析菜单，随后输入 Jira 号触发执行"""
    import threading
    from src.clients import feishu_client
    session = _bot_sessions.get(chat_id)
    logger.info("机器人收到命令: chat=%s, text=%s", chat_id[:12], text[:60])
    # 帮助/功能菜单：显示菜单并等待数字输入
    if any(kw in text for kw in ("功能", "帮助", "菜单", "help")):
        _set_bot_session(chat_id, "wait_menu")
        feishu_client.send_bot_message(chat_id,
            "当前可用功能：\n"
            "1. AI日志分析具体jira号执行\n"
            "7. AI日志分析批量执行\n"
            "13. AI日志分析失败问题排查\n\n"
            "请输入想要的功能数字唤醒对应功能（2分钟内有效）")
        return
    if session and session.get("state") == "wait_menu":
        # 菜单等待状态下，数字输入直接跳转到对应功能
        stripped = text.strip()
        if stripped in ("1", "7", "13"):
            _clear_bot_session(chat_id)  # 清除 wait_menu
            # 继续往下执行，让 text == "1"/"7"/"13" 的处理逻辑接管
        else:
            return  # 非数字输入，忽略并保持等待
    if text == "1":
        _set_bot_session(chat_id, "wait_jira")
        feishu_client.send_bot_message(
            chat_id, "1.1 AI日志分析与结论文档生成\n请输入 Jira 号，多个用逗号隔开\n示例：VCU-538942,VCU-200273")
        return
    if session and session.get("state") == "wait_jira":
        bugids = []
        for b in re.split(r"[\s,，;；]+", text):
            b = b.strip().upper()
            if b and b not in bugids:
                bugids.append(b)
        if not bugids:
            feishu_client.send_bot_message(chat_id, "未解析到 Jira 号，请重新输入（多个用逗号隔开）")
            return
        _clear_bot_session(chat_id)
        feishu_client.send_bot_message(chat_id, f"已收到 {len(bugids)} 个 Jira 号：{','.join(bugids)}\n执行中，请稍候...")
        threading.Thread(target=_bot_run_ai_analysis, args=(chat_id, bugids),
                         name=f"bot-ai-{bugids[0]}", daemon=True).start()
        return
    if text == "7":
        jqls = load_config().get("feishu_bot", {}).get("jqls", {}) or {}
        jql_labels = {"JQL1": "远控", "JQL2": "coreservice", "JQL3": "Navigation750", "JQL4": "VCU近期未关闭"}
        jql_desc = "\n".join(f"{k}({jql_labels.get(k, '')}): {v}" for k, v in jqls.items()) or "（feishu_bot.jqls 未配置）"
        _set_bot_session(chat_id, "wait_batch")
        feishu_client.send_bot_message(
            chat_id, f"7. AI日志分析批量执行\n请输入：JQL编号,抽取数量\n{jql_desc}\n\n默认推荐: JQL3,50\n示例: JQL3,50")
        return
    if session and session.get("state") == "wait_batch":
        m = re.match(r"(jql\s*\d+)\s*[,，]\s*(\d+)$", text, re.I)
        if not m:
            feishu_client.send_bot_message(chat_id, "格式错误，请输入「JQL编号,抽取数量」\n示例: JQL3,50")
            return
        jql_key = m.group(1).replace(" ", "").upper()
        count = int(m.group(2))
        if count <= 0:
            feishu_client.send_bot_message(chat_id, "抽取数量必须大于 0")
            return
        _clear_bot_session(chat_id)
        threading.Thread(target=_bot_run_batch_ai, args=(chat_id, jql_key, count),
                         name=f"bot-batch-{jql_key}", daemon=True).start()
        return
    if text == "13":
        _set_bot_session(chat_id, "wait_troubleshoot")
        feishu_client.send_bot_message(
            chat_id, "13. AI日志分析失败问题排查\n请输入排查时间（如 2026-09-03 19:00:00）\n\n默认提取分析失败结果且自动jira去重")
        return
    if session and session.get("state") == "wait_troubleshoot":
        # 解析时间输入
        time_str = text.strip()
        # 尝试多种格式
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                _ts = datetime.strptime(time_str, fmt)
                time_str = _ts.strftime("%Y-%m-%d %H:%M:%S")
                break
            except ValueError:
                continue
        else:
            feishu_client.send_bot_message(chat_id, "时间格式错误，请输入如 2026-09-03 19:00:00")
            return
        _clear_bot_session(chat_id)
        feishu_client.send_bot_message(chat_id, f"已收到排查时间: {time_str}\n执行中，请稍候（查询+诊断可能需要几分钟）...")
        threading.Thread(target=_bot_run_troubleshoot, args=(chat_id, time_str),
                         name="bot-troubleshoot", daemon=True).start()
        return
    # 未识别命令：返回功能菜单（后续可扩展更多功能）
    feishu_client.send_bot_message(chat_id, "可用命令：\n1. AI日志分析与结论文档生成（发送 1）\n7. AI日志分析批量执行（发送 7）\n13. AI日志分析失败问题排查（发送 13）")


def _bot_run_troubleshoot(chat_id: str, after_time: str):
    """机器人功能13后台执行：查询失败记录 → 逐个诊断 → 缓存结果 → 汇总回复"""
    from src.clients import feishu_client
    from src.clients import jira_client as _jc
    from collections import Counter
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
        for idx, rec in enumerate(failed_records):
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
        # 步骤3：汇总回复
        lines = [f"AI日志分析失败问题排查完成",
                 f"排查时间: {after_time}",
                 f"失败记录: {total} 条（其中缓存命中: {cached_count} 条）",
                 ""]
        # 按用户要求的 4 类展示，其余合并到“其他”
        main_cats = ["触发时间问题", "无gmlogger文件", "正常处理机制无需分析", "无报错信息，跳过排查"]
        for cat in main_cats:
            if cat in categories:
                lines.append(f"{cat}: {categories[cat]}/{total}")
        other_total = sum(v for k, v in categories.items() if k not in main_cats)
        if other_total:
            other_names = [f"{k}({v})" for k, v in categories.items() if k not in main_cats]
            lines.append(f"其他: {other_total}/{total} [{', '.join(other_names)}]")
        feishu_client.send_bot_message(chat_id, "\n".join(lines))
    except Exception as e:
        logger.error("机器人功能13执行失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"执行失败: {str(e)[:200]}")


def _bot_get_trigger_times(bugids: list) -> dict:
    """批量获取触发时间（优先本地缓存，本地无则从 Jira 提取并持久化），机器人功能 1/7 共用"""
    from src.clients import jira_client as _jc
    local_times = _load_trigger_times_from_cloud()
    trigger_times = {}
    for bugid in bugids:
        if bugid in local_times:
            trigger_times[bugid] = local_times[bugid]
            continue
        try:
            tt = _jc.extract_trigger_time_from_issue(_jc.fetch_issue(bugid))
            if tt:
                trigger_times[bugid] = tt
                _save_trigger_time_to_cloud(bugid, tt)
        except Exception as e:
            logger.warning("机器人提取触发时间失败 %s: %s", bugid, e)
    return trigger_times


def _bot_trigger_and_reply(chat_id: str, bugids: list, trigger_times: dict, realtime: bool = True) -> tuple:
    """逐个触发 AI 日志分析（验证逻辑与批量执行一致），返回 (成功数, 结果行列表, 结构化结果列表)

    realtime=True 每条即时回复（功能1）；False 收集结果行由调用方完成后统一发送（功能7）。
    """
    from src.clients import feishu_client
    from src.clients.base import http_post
    cfg = load_config()["ai_log_api"]
    success = 0
    lines = []
    results = []
    for bugid in bugids:
        exec_time = trigger_times.get(bugid) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        analysis_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            payload = {cfg["bugid_field"]: bugid}
            if cfg.get("trigger_time_field"):
                payload[cfg["trigger_time_field"]] = exec_time
            resp = http_post(cfg["url"], payload, timeout=int(cfg.get("timeout", 60)))
            resp_code = resp.get("code") if isinstance(resp, dict) else None
            resp_msg = str(resp.get("msg", "")) if isinstance(resp, dict) else ""
            ok = (resp_code == 200 or resp_code == 0) and any(
                kw in resp_msg for kw in ["分析任务已启动", "后台处理", "正在分析"])
            if ok:
                success += 1
                line = f"✓ Jira号 {bugid} 执行成功（触发时间：{exec_time}）"
                results.append({"jira号": bugid, "执行结果": "成功", "报告长度": 0, "备注": resp_msg[:200], "执行时间": exec_time, "分析执行时间": analysis_time})
            else:
                line = f"✗ Jira号 {bugid} 执行失败（接口返回：{resp_msg[:100]}）"
                results.append({"jira号": bugid, "执行结果": "失败", "报告长度": 0, "备注": resp_msg[:150], "执行时间": exec_time, "分析执行时间": analysis_time})
        except Exception as e:
            logger.warning("机器人触发 AI 分析失败 %s: %s", bugid, e)
            line = f"✗ Jira号 {bugid} 执行失败（异常：{str(e)[:100]}）"
            results.append({"jira号": bugid, "执行结果": "失败", "报告长度": 0, "备注": str(e)[:200], "执行时间": exec_time, "分析执行时间": analysis_time})
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
        jira = r.get("jira号", "").strip()
        result = r.get("执行结果", "").strip()
        trigger_time = r.get("执行时间", "").strip()
        analysis_time = r.get("分析执行时间", "").strip()
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


def _save_bot_execution_results(results: list, batch_name: str = None):
    """将机器人执行结果保存到本地 CSV（batch + daily）并上传云端"""
    import csv as _csv
    from src.core import report as report_module

    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M%S")
    # 保存 batch CSV: docs/日期/batch_*.csv
    batch_csv = os.path.join(get_path("doc_dir"), date_str, f"batch_{batch_name or time_str}.csv")
    os.makedirs(os.path.dirname(batch_csv), exist_ok=True)
    fieldnames = ["jira号", "执行结果", "报告长度", "备注", "执行时间", "分析执行时间"]
    with open(batch_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = _csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "jira号": r["jira号"],
                "执行结果": r["执行结果"],
                "报告长度": r["报告长度"],
                "备注": r["备注"],
                "执行时间": r.get("执行时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                "分析执行时间": r.get("分析执行时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            })
    # 写入每日结论报表
    try:
        daily_rows = [
            {"jira号": r["jira号"],
             "分析问题时间": r.get("执行时间", ""),
             "AI分析结果(飞书链接)": "", "AI评论总结": "",
             "rootcause": "", "结果置信度": ""} for r in results]
        report_module.generate_daily_csv(daily_rows, date_str=date_str)
    except Exception as e:
        logger.warning("机器人执行结果写入每日报表失败: %s", e)
    # 上传到飞书云端文件夹
    try:
        doc_title = f"批量执行 {date_str}_{batch_name or time_str}"
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


def _bot_run_ai_analysis(chat_id: str, bugids: list):
    """功能1后台执行：获取触发时间后用 Jira 号逐个触发 AI 分析并即时回复结果"""
    from src.clients import feishu_client
    trigger_times = _bot_get_trigger_times(bugids)
    success, _, results = _bot_trigger_and_reply(chat_id, bugids, trigger_times)
    # 保存本地记录
    try:
        _save_bot_execution_results(results, batch_name=f"bot_{datetime.now().strftime('%H%M%S')}")
    except Exception as e:
        logger.warning("机器人执行结果保存本地失败: %s", e)
    feishu_client.send_bot_message(chat_id, f"全部执行完成：成功 {success}/{len(bugids)}")


def _bot_run_batch_ai(chat_id: str, jql_key: str, count: int):
    """功能7后台执行：一键批量 AI 日志分析（JQL搜索→多维表格去重→提取时间→随机抽样→触发执行）

    与测试页“7. AI日志分析批量执行”一键执行逻辑一致。
    """
    import random
    from src.clients import feishu_client
    from src.clients import jira_client as _jc
    jqls = load_config().get("feishu_bot", {}).get("jqls", {}) or {}
    jql = jqls.get(jql_key)
    if not jql:
        feishu_client.send_bot_message(chat_id, f"未找到 JQL 编号 {jql_key}，可用：{','.join(jqls.keys()) or '未配置'}")
        return
    # 步骤1：JQL 搜索（仅保留 VCU）
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
    # 步骤2：多维表格去重过滤（排除已分析成功，失败不阻断）
    filtered = candidates
    try:
        cfg_b = load_config().get("feishu_bitable", {})
        if cfg_b.get("app_token") and cfg_b.get("table_id"):
            records = feishu_client.list_bitable_records(cfg_b["app_token"], cfg_b["table_id"])
            bugid_field = cfg_b.get("bugid_field", "jira号")
            success_keys = set()
            for rec in records:
                fields = rec.get("fields", {})
                fv = fields.get(bugid_field, "")
                if isinstance(fv, list):
                    fv = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in fv)
                elif isinstance(fv, dict):
                    fv = fv.get("text", str(fv))
                if str(fv).strip() and str(fields.get("分析结果", "")).strip() == "成功":
                    success_keys.add(str(fv).strip())
            filtered = [k for k in candidates if k not in success_keys]
    except Exception as e:
        logger.warning("机器人多维表格去重过滤失败（不过滤继续）: %s", e)
    if not filtered:
        feishu_client.send_bot_message(chat_id, f"候选 {len(candidates)} 条均已在多维表格分析成功，无需执行")
        return
    # 步骤3：批量提取触发时间（优先本地）
    trigger_times = _bot_get_trigger_times(filtered)
    # 步骤4：随机抽样（排除 docs/ 已测试，优先抽有时间的）
    tested = _load_all_doc_jira_keys()
    available = [k for k in filtered if k not in tested]
    if not available:
        feishu_client.send_bot_message(chat_id, "候选均已测试过，无可抽取记录")
        return
    with_time = [k for k in available if k in trigger_times]
    without_time = [k for k in available if k not in trigger_times]
    sample_size = min(count, len(available))
    selected = random.sample(with_time, min(sample_size, len(with_time)))
    if len(selected) < sample_size and without_time:
        selected.extend(random.sample(without_time, min(sample_size - len(selected), len(without_time))))
    feishu_client.send_bot_message(
        chat_id, f"任务执行中，请等待\n搜索 {len(candidates)} 条 → 去重后 {len(filtered)} 条 → 抽取 {len(selected)} 条\n"
                 f"抽取的 Jira 号：{';'.join(selected)}")
    # 步骤5：逐个触发执行，收集结果，完成后统一反馈
    success, lines, results = _bot_trigger_and_reply(chat_id, selected, trigger_times, realtime=False)
    # 保存本地记录
    try:
        _save_bot_execution_results(results, batch_name=f"bot_batch_{datetime.now().strftime('%H%M%S')}")
    except Exception as e:
        logger.warning("机器人批量执行结果保存本地失败: %s", e)
    _bot_send_batch_results(chat_id, success, len(selected), lines)


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


def _delete_default_bitable_table(app_token: str, keep_table_id: str):
    """删除飞书创建 bitable 时自动生成的默认空数据表（保留我们自己创建的表）"""
    import httpx as _httpx
    from src.clients.feishu_client import _bitable_headers, _FEISHU_API
    try:
        headers = _bitable_headers()
        url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables"
        resp = _httpx.get(url, headers=headers, timeout=15, verify=False)
        tables = resp.json().get("data", {}).get("items", [])
        for t in tables:
            tid = t.get("table_id", "")
            if tid and tid != keep_table_id:
                del_url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables/{tid}"
                _httpx.delete(del_url, headers=headers, timeout=15, verify=False)
                logger.info("已删除默认数据表: %s", tid)
    except Exception as e:
        logger.warning("删除默认数据表失败: %s", e)


# 触发时间云端 bitable 配置缓存，避免每次重新创建
# 触发时间云端表格缓存（支持多表）
_trigger_time_table_cache = {"app_token": "", "table_ids": [], "inited": False}

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


def _load_trigger_times_from_cloud() -> dict:
    """从云端多维表格加载所有触发时间（支持多表），云端不可用时降级读本地 CSV

    :return: {jira号: 触发时间}
    """
    from src.clients import feishu_client
    try:
        app_token, table_ids = _get_trigger_time_table_cfg()
        result = {}
        for tid in table_ids:
            records = feishu_client.list_bitable_records(app_token, tid)
            for rec in records:
                fields = rec.get("fields", {})
                jira_no = _bitable_text(fields.get("jira号", ""))
                tt = _bitable_text(fields.get("触发时间", ""))
                if jira_no and tt:
                    result[jira_no] = tt
        logger.info("云端触发时间加载完成: %d 条（%d 个表）", len(result), len(table_ids))
        return result
    except Exception as e:
        logger.warning("云端触发时间加载失败，降级读本地 CSV: %s", e)
        return _load_trigger_times_from_local()


def _save_trigger_time_to_cloud(bugid: str, trigger_time: str):
    """将触发时间写入云端 bitable（有则更新，无则新建），支持多表自动拆分"""
    from src.clients import feishu_client
    # 始终写本地 CSV 作为降级缓存
    _save_trigger_time_to_csv(bugid, trigger_time)
    try:
        app_token, table_ids = _get_trigger_time_table_cfg()
        # 在所有表中查找已有记录
        existing = None
        found_tid = None
        table_counts = {}  # {table_id: record_count}
        for tid in table_ids:
            records = feishu_client.list_bitable_records(app_token, tid)
            table_counts[tid] = len(records)
            if not existing:
                for rec in records:
                    fields = rec.get("fields", {})
                    jira_no = _bitable_text(fields.get("jira号", ""))
                    if jira_no == bugid:
                        existing = rec
                        found_tid = tid
                        break
        if existing:
            # 更新已有记录
            feishu_client.update_bitable_records(app_token, found_tid, [{
                "record_id": existing["record_id"],
                "fields": {"触发时间": trigger_time}
            }])
            logger.info("云端触发时间已更新: %s -> %s (表 %s)", bugid, trigger_time, found_tid)
        else:
            # 新建：选未满的表，或创建新表
            target_tid = None
            for tid in table_ids:
                if table_counts.get(tid, 0) < _TRIGGER_TIME_TABLE_LIMIT:
                    target_tid = tid
                    break
            if not target_tid:
                target_tid = _create_trigger_time_subtable(app_token, len(table_ids) + 1)
                table_ids.append(target_tid)
                _trigger_time_table_cache["table_ids"] = list(table_ids)
                _update_config_table_ids(app_token, table_ids)
            feishu_client.batch_create_records(app_token, target_tid, [{
                "fields": {"jira号": bugid, "触发时间": trigger_time, "提取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            }])
            logger.info("云端触发时间已新建: %s -> %s (表 %s)", bugid, trigger_time, target_tid)
    except Exception as e:
        logger.warning("云端触发时间写入失败（已写本地 CSV）: %s", e)


def _create_trigger_time_subtable(app_token: str, index: int) -> str:
    """创建触发时间子表（触发时间_N），返回 table_id"""
    from src.clients import feishu_client
    fields = [
        {"field_name": "jira号", "type": 1},
        {"field_name": "触发时间", "type": 1},
        {"field_name": "提取时间", "type": 1},
    ]
    table_id = feishu_client.create_bitable_table(app_token, f"触发时间_{index}", fields)
    _delete_default_bitable_table(app_token, table_id)
    logger.info("触发时间子表已创建: 触发时间_%d -> %s", index, table_id)
    return table_id


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
    """按日期查询结论报表"""
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    return _ok(_read_csv_rows(_daily_csv_path(date_str)))


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
    }


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
        rows.append({
            "jira号": jira_no,
            "执行结果": (r.get("执行结果") or "").strip(),
            "报告长度": "",
            "触发时间": (r.get("触发时间") or r.get("执行时间") or "").strip(),
            "执行时间": (r.get("执行时间") or "").strip() if "触发时间" in r else "",
            "备注": (r.get("备注") or "").strip(),
        })
    return _ok({"rows": rows, "count": len(rows), "batch_token": batch_token},
               f"云端批次预览: {len(rows)} 条")


@app.get("/api/data/history_jira")
def data_history_jira(batch_token: str = ""):
    """数据面板：从云端文档读取批次 Jira 列表并聚合多维表格全部匹配记录

    :param batch_token: 云端批次文档 token
    同一 Jira 在多维表格中有多条记录时全部展示。
    """
    if not batch_token:
        return _fail("缺少 batch_token 参数")
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
    # jira号 -> [多条多维表格记录]，全部保留不去重
    bitable_records_map = {}
    if app_token and table_id:
        try:
            records = feishu_client.list_bitable_records(app_token, table_id)
            for rec in records:
                fields = rec.get("fields", {})
                jira_key = _bitable_text(fields.get(bugid_field, ""))
                if jira_key and jira_key in jira_set:
                    bitable_records_map.setdefault(jira_key, []).append(
                        _flatten_bitable_record(fields, report_field))
        except Exception as e:
            logger.warning("批次聚合：多维表格查询失败（仅返回本地数据）: %s", e)
    # —— 第3步：合并——同一 Jira 的多维表格多条记录全部展开 ——
    rows = []
    for item in jira_list:
        jira_no = item["jira号"]
        bt_records = bitable_records_map.get(jira_no, [])
        if bt_records:
            # 多维表格有多条记录，每条生成一行（按分析完成时间倒序）
            bt_records.sort(key=lambda x: x.get("分析完成时间", ""), reverse=True)
            for bf in bt_records:
                rows.append({
                    "jira号": jira_no,
                    "执行结果": item["执行结果"],
                    "执行时间": item["执行时间"],
                    "分析结果": bf.get("分析结果", ""),
                    "错误信息": bf.get("错误信息", ""),
                    "飞书报告链接": bf.get("飞书报告链接", ""),
                    "分析问题时间": bf.get("分析问题时间", ""),
                    "分析完成时间": bf.get("分析完成时间", ""),
                })
        else:
            # 无多维表格匹配，仅展示本地批量执行信息
            rows.append({
                "jira号": jira_no,
                "执行结果": item["执行结果"],
                "执行时间": item["执行时间"],
                "分析结果": "", "错误信息": "", "飞书报告链接": "", "分析问题时间": "", "分析完成时间": "",
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


@app.post("/api/test/batch_ai_extract_times")
async def test_batch_ai_extract_times(request: Request):
    """步骤2：批量提取所有候选的触发时间，存入本地CSV"""
    body = await request.json() or {}
    keys = body.get("keys") or []
    if not keys:
        return _fail("候选列表为空，请先执行步骤1")
    # 加载本地已有时间（本地优先）
    local_times = _load_trigger_times_from_cloud()
    trigger_times = {}
    sources = {}  # 每个 key 的时间来源：本地缓存/新提取，供前端展示
    need_fetch = []
    for key in keys:
        if key in local_times:
            trigger_times[key] = local_times[key]
            sources[key] = "本地"
        else:
            need_fetch.append(key)
    local_hit = len(trigger_times)
    # 对本地没有的走接口提取
    if need_fetch:
        from src.clients import jira_client as _jc
        for key in need_fetch:
            try:
                issue = _jc.fetch_issue(key)
                tt = _jc.extract_trigger_time_from_issue(issue)
                if tt:
                    trigger_times[key] = tt
                    sources[key] = "新提取"
                    _save_trigger_time_to_cloud(key, tt)
            except Exception as e:
                logger.warning("提取触发时间失败 %s: %s", key, e)
    new_count = len(trigger_times) - local_hit
    logger.info("批量提取触发时间: 本地命中 %d, 新提取 %d, 共 %d/%d",
                local_hit, new_count, len(trigger_times), len(keys))
    return _ok({"trigger_times": trigger_times, "sources": sources, "total": len(keys),
                "time_count": len(trigger_times), "local_hit": local_hit, "new_count": new_count},
               f"提取完成: {len(trigger_times)}/{len(keys)} 有触发时间（本地命中 {local_hit}，新提取 {new_count}）")


@app.post("/api/test/batch_ai_filter")
async def test_batch_ai_filter(request: Request):
    """步骤2.5：查询多维表格，过滤掉分析结果为成功的记录，生成新的候选列表"""
    body = await request.json() or {}
    keys = body.get("keys") or []
    if not keys:
        return _fail("候选列表为空，请先执行步骤1")
    # 查询多维表格，获取已成功的 jira 号
    success_keys = set()
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
            result_status = str(fields.get("分析结果", "")).strip()
            # 分析结果为"成功"的记录，视为已存在，需要过滤掉
            if result_status == "成功":
                success_keys.add(jira_key)
        logger.info("多维表格重复过滤: 成功记录 %d 条", len(success_keys))
    except Exception as e:
        logger.warning("多维表格重复过滤查询失败（跳过此检查）: %s", e)
    # 过滤候选列表：排除多维表格中分析结果为成功的
    filtered = [k for k in keys if k not in success_keys]
    removed = len(keys) - len(filtered)
    if not filtered:
        return _fail(f"所有候选 bug 在多维表格中均为成功状态（共过滤 {removed} 条）")
    return _ok({"filtered": filtered, "removed": removed, "total": len(keys),
                 "success_keys": list(success_keys)[:20]},
                f"候选 {len(keys)} 条，过滤成功 {removed} 条，剩余 {len(filtered)} 条")


@app.post("/api/test/batch_ai_sample")
async def test_batch_ai_sample(request: Request):
    """步骤4：从候选列表中随机抽取，从本地已存储的时间中查询，优先抽取有时间的

    去重规则：docs/ 全量 CSV 已测试 排除，候选 keys 已由步骤3过滤
    """
    import random
    body = await request.json() or {}
    keys = body.get("keys") or []
    count = int(body.get("count", 0))
    if not keys:
        return _fail("候选列表为空，请先执行步骤1")
    if count <= 0:
        return _fail("抽取数量必须大于 0")
    # 扫描 docs/ 下所有 CSV 已测试的 jira 号（含历史批量文件）
    tested = _load_all_doc_jira_keys()
    # 排除 docs/ 已测试记录（步骤3已过滤多维表格成功记录）
    available = [k for k in keys if k not in tested]
    if not available:
        return _fail(f"所有候选 bug 均已测试过（已测试 {len(tested)} 条）")
    # 从本地已存储的时间中查询（不重复提取）
    local_times = _load_trigger_times_from_cloud()
    trigger_times = {k: local_times[k] for k in available if k in local_times}
    # 优先抽取有触发时间的
    with_time = [k for k in available if k in trigger_times]
    without_time = [k for k in available if k not in trigger_times]
    sample_size = min(count, len(available))
    selected = []
    if with_time:
        pick_with = min(sample_size, len(with_time))
        selected.extend(random.sample(with_time, pick_with))
    if len(selected) < sample_size:
        remaining = sample_size - len(selected)
        if without_time:
            selected.extend(random.sample(without_time, min(remaining, len(without_time))))
    time_info = f"，{len(trigger_times)} 条有触发时间" if trigger_times else ""
    return _ok({"available_count": len(available), "tested_count": len(tested),
                 "selected": selected, "selected_count": len(selected),
                 "trigger_times": trigger_times, "time_count": len(trigger_times)},
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
    if not bugids:
        return _fail("待执行列表为空，请先执行步骤2")
    # 步骤3已过滤多维表格成功记录，此处不再重复去重
    skipped_jiras = []
    
    async def event_generator():
        yield f"data: {_json.dumps({'type': 'start', 'total': len(bugids)}, ensure_ascii=False)}\n\n"
        result_queue = queue.Queue()
        loop = asyncio.get_event_loop()

        def _run_one(bugid):
            """在线程池中执行单个 AI 分析：使用提取的触发时间或当前时间"""
            from src.clients.base import http_post
            try:
                cfg = load_config()["ai_log_api"]
                payload = {cfg["bugid_field"]: bugid}
                # 触发时间：优先用传入的触发时间，否则用当前时间
                exec_time = trigger_times.get(bugid) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                analysis_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if cfg.get("trigger_time_field"):
                    payload[cfg["trigger_time_field"]] = exec_time
                resp = http_post(cfg["url"], payload, timeout=int(cfg.get("timeout", 60)))
                # 判断是否异步启动成功：code=200 且 msg 包含异步关键词
                resp_code = resp.get("code") if isinstance(resp, dict) else None
                resp_msg = str(resp.get("msg", "")) if isinstance(resp, dict) else ""
                is_async_ok = (resp_code == 200 or resp_code == 0) and any(
                    kw in resp_msg for kw in ["分析任务已启动", "后台处理", "正在分析"])
                if is_async_ok:
                    result_queue.put({"jira号": bugid, "执行结果": "成功",
                                      "报告长度": 0, "备注": resp_msg[:200], "执行时间": exec_time,
                                      "分析执行时间": analysis_time,
                                      "status": "success", "report_len": 0, "msg": resp_msg[:100]})
                else:
                    result_queue.put({"jira号": bugid, "执行结果": "失败",
                                      "报告长度": 0, "备注": f"返回异常: {resp_msg[:150]}", "执行时间": exec_time,
                                      "分析执行时间": analysis_time,
                                      "status": "fail", "report_len": 0, "msg": resp_msg[:100]})
            except Exception as e:
                result_queue.put({"jira号": bugid, "执行结果": "失败", "报告长度": 0,
                                  "备注": str(e)[:200], "status": "fail",
                                  "report_len": 0, "msg": str(e)[:100],
                                  "执行时间": trigger_times.get(bugid) or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                  "分析执行时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

        # 并行启动所有任务
        for bugid in bugids:
            loop.run_in_executor(None, _run_one, bugid)

        # 轮询队列，实时推送完成事件
        results = []
        while len(results) < len(bugids):
            if await request.is_disconnected():
                break
            try:
                item = result_queue.get_nowait()
                results.append(item)
                yield f"data: {_json.dumps({'type': 'progress', 'index': len(results), 'total': len(bugids), 'bugid': item['jira号'], 'status': item['status'], 'report_len': item.get('report_len', 0), 'msg': item.get('msg', ''), 'exec_time': item.get('执行时间', ''), 'analysis_time': item.get('分析执行时间', '')}, ensure_ascii=False)}\n\n"
            except queue.Empty:
                await asyncio.sleep(1)

        # 写入本次批量执行表格：docs/日期/batch_HHMMSS.csv
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        batch_csv = os.path.join(get_path("doc_dir"), date_str, f"batch_{time_str}.csv")
        os.makedirs(os.path.dirname(batch_csv), exist_ok=True)
        fieldnames = ["jira号", "执行结果", "报告长度", "备注", "执行时间"]
        with open(batch_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow({"jira号": r["jira号"], "执行结果": r["执行结果"],
                                 "报告长度": r["报告长度"], "备注": r["备注"],
                                 "执行时间": r.get("执行时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))})
        success_count = sum(1 for r in results if r["执行结果"] == "成功")
        fail_count = len(results) - success_count
        # 将结果写入每日结论报表（仅含已知字段，后续单Jira流程会补全其余字段）
        try:
            from src.core import report as report_module
            daily_rows = [{"jira号": r["jira号"],
                           "分析问题时间": r.get("执行时间", ""),
                           "AI分析结果(飞书链接)": "", "AI评论总结": "",
                           "rootcause": "", "结果置信度": ""} for r in results]
            report_module.generate_daily_csv(daily_rows, date_str=date_str)
        except Exception as e:
            logger.warning("批量执行写入每日报表失败（不影响主流程）: %s", e)
        # 上传到飞书云端文件夹
        cloud_url = ""
        try:
            doc_title = f"批量执行 {date_str}_{time_str}"
            cloud_url = _upload_batch_to_cloud(batch_csv, doc_title)
        except Exception as e:
            logger.warning("批量执行上传云端失败（不影响主流程）: %s", e)
        done_msg = f"执行完成：成功 {success_count} 条，失败 {fail_count} 条"
        if skipped_jiras:
            done_msg += f"，已跳过 {len(skipped_jiras)} 条（多维表格已成功）"
        yield f"data: {_json.dumps({'type': 'done', 'total': len(results), 'success': success_count, 'fail': fail_count, 'skipped': len(skipped_jiras), 'message': done_msg, 'csv_path': batch_csv, 'cloud_url': cloud_url}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
        if not rc_field and not cs_field and not cf_field:
            logger.error("多维表格未找到任何目标字段，实际字段: %s", list(field_name_map.keys()))
            return _fail("多维表格中未找到 rootcause/AI评论总结/结果置信度 字段")
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
                    _save_trigger_time_to_cloud(bugid, tt)
                    extracted_count += 1
            except Exception as e:
                logger.warning("批量读取触发时间-提取失败 %s: %s", bugid, e)
        result.append({
            "bugid": bugid,
            "current_time": current_time
        })
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
        msg = f"已更新 {bugid} 的触发时间为 {new_time}（云端+本地）"
        return _ok({"bugid": bugid, "new_time": new_time, "updated": True}, msg)
    except Exception as e:
        logger.warning("更新触发时间失败 %s: %s", bugid, e)
        return _fail(f"更新失败: {e}")


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
    """从多维表格提取所有分析失败的 jira 号，去重返回"""
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
        failed_jiras = set()
        for rec in records:
            fields = rec.get("fields", {})
            result_status = str(fields.get("分析结果", "")).strip()
            if result_status == "失败":
                field_value = fields.get(bugid_field, "")
                if isinstance(field_value, list):
                    field_value = " ".join(str(v) for v in field_value)
                field_value = str(field_value).strip()
                if field_value:
                    failed_jiras.add(field_value)
        jira_list = sorted(failed_jiras)
        return _ok({"jiras": jira_list, "count": len(jira_list)}, f"提取到 {len(jira_list)} 个分析失败的 Jira 号（已去重）")
    except Exception as e:
        logger.error("提取失败Jira号失败: %s", e, exc_info=True)
        return _fail(f"提取失败: {e}")


# ========== AI日志分析失败问题排查工具 ==========

def _ts_parse_datetime(val) -> datetime:
    """多维表格时间字段归一化为 datetime（兼容毫秒时间戳/字符串）"""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        # 毫秒时间戳（飞书日期字段默认格式）
        try:
            return datetime.fromtimestamp(val / 1000)
        except (ValueError, OSError, OverflowError):
            return None
    s = str(val).strip()
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
    """批量读取压缩包内多个文件的头部内容（支持 zip/7z），返回 {name: 头部文本}

    7z 一次性 extract 全部目标，避免 solid 归档重复解压。
    """
    import zipfile
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


def _diag_download_archives(attachments: list, headers: dict, timeout: int, problem_time: str) -> tuple:
    """逐个下载压缩包附件并解压，比对解压文件名与错误时间（前后5分钟），返回 (archive_results, matched_any)"""
    from src.clients.jira_client import _ARCHIVE_SUFFIXES
    archive_results = []
    matched_any = False
    for att in attachments:
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


def _diag_gmlogger_main_times(attachments: list, headers: dict, timeout: int) -> dict:
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
    # 超大包上限：避免数百分兆下载阻塞诊断太久，超限跳过内包探测走兜底链路
    total_size = sum(a.get("size", 0) for ps in groups.values() for _p, a in ps)
    if total_size > 500 * 1024 * 1024:
        return {"status": "failed", "reason": f"gmlogger 压缩包过大（{total_size // 1024 // 1024}MB>500MB），已跳过内包探测",
                "main_entries": [], "main_times": []}
    last_reason = "无有效 gmlogger 压缩包"
    with tempfile.TemporaryDirectory() as tmp:
        for base, parts in groups.items():
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


def _diag_verify_suggestion(issue: dict, gm_times: list, archive_results: list, main_times: list = None,
                            all_times: list = None) -> tuple:
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
        # 包内时间戳存在但提取时间未命中：优先采纳 main 文件实际日志时间戳（真实记录时间）
        if main_times:
            return "success", main_times[0][0], (f"提取时间 {extracted or '(未提取到)'} 与包内时间戳前后5分钟未命中，"
                                                  f"采纳 gmlogger 包内实际日志时间戳 {main_times[0][0]} 作为建议{gm_note}")
        return "manual", "", (f"提取时间 {extracted or '(未提取到)'} 与包内全部文件时间戳前后5分钟均未命中，"
                              f"待人工审核正确的时间{gm_note}")
    # —— 无 gmlogger 包内时间戳：与解压文件比对（只检查 main.log 文件名）——
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
    return "manual", "", f"未能提取到新触发时间（评论区/描述均无时间），待人工审核正确的时间{gm_note}"


@app.post("/api/troubleshoot/records")
async def troubleshoot_records(request: Request):
    """排查工具第1步：按分析完成时间筛选多维表格记录（可筛选成功/失败、按 jira号 去重）"""
    body = await request.json() or {}
    after_time = str(body.get("after_time", "")).strip()
    result_filter = str(body.get("result_filter", "")).strip()  # 空=全部 / 成功 / 失败
    dedup = bool(body.get("dedup", True))
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
        jira_no = _bitable_text(fields.get(bugid_field, ""))
        if not jira_no:
            continue
        row = {
            "jira号": jira_no,
            "分析结果": result_status,
            "分析完成时间": done_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "分析问题时间": _bitable_text(fields.get("分析问题时间", "")),
            "错误信息": _diag_pick_error_info(fields),
            "飞书报告链接": (fields.get(cfg.get("report_field", "AI分析结果(飞书链接)"), {}) or {}).get("link", "")
            if isinstance(fields.get(cfg.get("report_field", "AI分析结果(飞书链接)"), ""), dict) else "",
        }
        prev = picked.get(jira_no)
        if not dedup or prev is None or row["分析完成时间"] > prev["分析完成时间"]:
            picked[jira_no] = row
    rows = sorted(picked.values(), key=lambda r: r["分析完成时间"])
    return _ok({"rows": rows, "count": len(rows)},
               f"{after_time} 之后执行完成 {len(rows)} 条（筛选：{result_filter or '全部'}，去重：{'是' if dedup else '否'}）")


def _diag_pre_classify(err_msg: str) -> str:
    """根据失败原因文本预归类（对应问题排查文档的归类方式），无法判定时返回空串"""
    msg = err_msg or ""
    if "未找到问题时间" in msg:
        return "触发时间问题"
    if "没有可下载的日志附件" in msg:
        return "正常处理机制，无需分析"
    if "adjudication" in msg or "未获取有效响应" in msg:
        return "接口并发响应问题"
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
    elif category == "接口并发响应问题" or "adjudication" in low:
        ai_reason = msg or "分析报告生成失败: adjudication 失败"
        human_reason = "疑似接口拥堵导致的接口无响应，待源泉排查"
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
    elif category == "待人工排查":
        ai_reason = msg or "未知错误"
        human_reason = "无法自动归类，待人工排查"
        retry_result = ""
        final_category = "待人工排查"

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
    if not bugid:
        return _fail("bugid 不能为空")
    # —— 优先读取本地缓存 ——
    cached = _load_diagnose_cache(bugid)
    if cached is not None:
        return _ok(cached, f"{bugid} 诊断结果（本地缓存）")
    # —— 无报错信息的记录不进行排查，直接跳过 ——
    if not err_msg:
        report = _generate_troubleshoot_report(bugid, "无报错信息，跳过排查", err_msg, "")
        result = {"bugid": bugid, "category": "无报错信息，跳过排查", "problem_time": problem_time,
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
        issue = jira_client.fetch_issue(bugid)
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
    # —— 识别 gmlogger 附件（文件名含 gmlogger 即算）——
    gm_atts = [a for a in attachments if "gmlogger" in (a.get("filename", "") or "").lower()]
    if not gm_atts:
        # 归类：无gmlogger文件；其他压缩包兜底下载解压比对错误时间（前后5分钟）
        archive_results, matched_any = _diag_download_archives(attachments, headers, att_timeout, problem_time)
        if matched_any:
            category = "日志过滤逻辑"
            detail = f"无gmlogger文件，但解压文件中存在错误时间({problem_time})前后5分钟内对应文件，疑似日志过滤机制问题"
            verify_status, suggested_time = "", ""
        else:
            category = "无gmlogger文件"
            detail = f"该 Issue 共 {len(attachments)} 个附件中未找到 gmlogger 日志文件"
            verify_status, suggested_time, vdetail = _diag_verify_suggestion(issue, [], archive_results)
            detail += "；查验：" + vdetail
        report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time, verify_status, suggested_time, archive_results)
        result = {"bugid": bugid, "category": category, "problem_time": problem_time,
                   "archive_files": archive_results, "detail": detail,
                   "verify_status": verify_status, "suggested_time": suggested_time, "report": report, "done_time": done_time}
        _save_diagnose_cache(bugid, result)
        return _ok(result, f"{bugid} 诊断完成：{category}")
    # —— 有 gmlogger：外侧文件名时间不准不参与判定，仅用包内内容时间戳比对 ——
    gm_times = _diag_gmlogger_times(attachments)
    gm_probe = _diag_gmlogger_main_times(attachments, headers, att_timeout)
    main_times = gm_probe.get("main_times", [])
    all_times = gm_probe.get("all_times", [])  # 包内 main.log 条目文件名时间戳（任一命中窗口即通过）
    main_entries = gm_probe.get("main_entries", [])
    err_dt = _ts_parse_datetime(problem_time)
    hit = [t for t in (main_times + all_times) if err_dt and abs((t[1] - err_dt).total_seconds()) <= 300]
    archive_results = []
    if hit:
        category = "日志过滤逻辑"
        detail = (f"gmlogger 包内内容时间戳 {hit[0][0]} 与错误时间({problem_time})前后5分钟内一致，"
                  f"日志存在但解析失败，疑似日志过滤机制问题")
        verify_status, suggested_time = "", ""
    else:
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
        # —— 触发时间修正链路：先提取（评论区优先）再用包内时间戳验证，给出替换建议 ——
        verify_status, suggested_time, vdetail = _diag_verify_suggestion(issue, gm_times, [],
                                                                         main_times=main_times, all_times=all_times)
        detail += "；查验：" + vdetail
    report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time, verify_status, suggested_time, archive_results)
    result = {"bugid": bugid, "category": category, "problem_time": problem_time,
               "archive_files": archive_results, "detail": detail,
               "verify_status": verify_status, "suggested_time": suggested_time, "report": report, "done_time": done_time}
    _save_diagnose_cache(bugid, result)
    return _ok(result, f"{bugid} 诊断完成：{category}")




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
