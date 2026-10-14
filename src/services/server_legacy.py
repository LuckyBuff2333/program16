"""server.py 遗留函数：从 server.py 提取的全部业务逻辑

此模块包含原 server.py 中除信号处理和 app 装配之外的所有函数和全局变量。
server.py 通过 import alias 从本模块获取这些名称，保持向后兼容。

后续应逐步将本模块中的函数迁移到对应的 service 模块：
- 诊断相关 → src/services/diag_service.py
- 飞书机器人 → src/services/feishu_bot_service.py
- 报表相关 → src/services/report_ops.py（已部分迁移）
- 触发时间 → src/services/trigger_ops.py（已部分迁移）

迁移完成后删除本模块和 server.py。
"""
import asyncio
import json
import os
import re
import signal
import sys
import threading
from datetime import datetime

import pandas as pd
import yaml
import concurrent.futures as _futures
from fastapi import Request

from src import config as cfg_module
from src import pipeline
from src.clients import ai_log_client, bug_source, jira_client
from src.clients import diana_client as _diana_client
from src.config import get_path, load_config, setup_logger, PROJECT_ROOT
from src.core import audit as audit_module
from src.core import doc_generator

# 从共享模块导入公共工具和状态
from src.api.routes.shared import (
    bitable_text as _bitable_text,
    is_bitable_excluded as _is_bitable_excluded,
    flatten_bitable_record as _flatten_bitable_record,
    get_prod_ai_url as _get_prod_ai_url,
    get_prod_ai_cfg as _get_prod_ai_cfg,
    build_prod_ai_payload as _build_prod_ai_payload,
    ts_parse_datetime as _ts_parse_datetime,
    read_csv_rows as _read_csv_rows,
    parse_conf as _parse_conf,
    ok as _ok,
    fail as _fail,
    check_interrupt as _check_interrupt,
    check_diag_cancel as _check_diag_cancel,
    get_diag_executor as _get_diag_executor,
    flow_cancel as _flow_cancel,
    diag_cancel as _diag_cancel,
    batch_extract_stop_event as _batch_extract_stop_event,
    cache_batch_stop_event as _cache_batch_stop_event,
    uploaded_files as _uploaded_files,
    oauth_cache as _oauth_cache,
    bot_cancel_events as _bot_cancel_events,
    bot_running_tasks as _bot_running_tasks,
    get_cancel_event as _get_cancel_event,
    reset_cancel_event as _reset_cancel_event,
    set_running_task as _set_running_task,
    clear_running_task as _clear_running_task,
    is_cancelled as _is_cancelled,
)

# 从已迁移的 service 模块导入
from src.services.trigger_ops import (
    _timestudy_init_ctx, _timestudy_trace, _timestudy_update_ctx,
    _timestudy_get_ctx, _timestudy_record,
    _save_trigger_time_to_csv, _load_trigger_times_from_local,
    _get_trigger_time_table_cfg, _migrate_local_trigger_times_to_cloud,
    _load_cloud_trigger_cache, _load_trigger_times_from_cloud,
    _load_cloud_trigger_keys, _load_all_cloud_trigger_records,
    _ensure_trigger_time_bugid_cache, _save_trigger_time_to_cloud,
    _batch_save_trigger_times_to_cloud,
    _remove_local_trigger_entries, _refresh_trigger_time_bugid_cache,
    _create_trigger_time_subtable, _update_config_table_ids,
    _load_cache_batch_progress, _save_cache_batch_progress,
    _invalidate_bitable_cache,
)
from src.services.report_ops import (
    _batch_csv_to_markdown, _upload_batch_to_cloud,
    _get_or_create_date_folder, _save_bot_execution_results,
    _bot_send_batch_results,
    _load_daily_broadcast_config, _save_daily_broadcast_config,
    _auto_disable_daily_broadcast, get_daily_report_url,
    _parse_dur_sec, _format_dur,
    _generate_daily_report, _classify_failure,
    _format_daily_report_msg, _upload_daily_report_to_cloud,
    _sync_daily_stats_to_bitable,
    _get_week_dates, _generate_weekly_report, _generate_range_report,
    _format_weekly_report_msg, _upload_weekly_report_to_cloud,
    _is_chinese_workday, _get_prev_chinese_workday,
    _get_report_date_range,
    _read_today_batch_records, _read_multi_day_batch_records,
    _daily_csv_path, _spotcheck_csv_path,
    _load_all_doc_jira_keys,
    _flatten_bitable_record_all,
    _load_bitable_success_jiras,
    _generate_troubleshoot_report,
    _troubleshoot_cache_dir, _load_diagnose_cache, _save_diagnose_cache,
    _delete_default_bitable_table,
    _verify_write_bitable_impl,
    _scan_all_batch_records,
)
from src.services.troubleshoot_service import (
    _SKIP_ANALYSIS_CATEGORIES,
    _diag_pre_classify,
)

logger = setup_logger("server_legacy")

# 文档图片资源目录
_DOC_IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "docs", "assets")

_feishu_recent_messages: list = []

_TRIGGER_ISSUE_FOLDER_TOKEN = "VmEcfznPUlV72VdUoPYc8rF0nBd"


_bot_silent_mode = False

_BOT_SESSION_TIMEOUT = 120

_bot_sessions: dict = {}

_timestudy_ctx: dict = {}

_EXCLUDE_REASONS = {"无gmlogger", "无gmlogger文件", "无gmlogger日志文件", "日志文件已损坏", "问题重复", "问题重复，无需排查", "问题未复现", "触发时间无日志", "无日志附件", "该jira无日志附件，属于正常处理机制", "该Jira无日志附件，属于正常处理机制", "该jira无日志附件", "该Jira无日志附件", "日志里无对应触发时间相关文件，但是标题里明确说了触发时间", "解压问题，待排查", "解压问题"}

_TIMESTUDY_DIR = os.path.join(PROJECT_ROOT, "data", "timestudy")
_TIMESTUDY_REPORT_DIR = os.path.join(PROJECT_ROOT, "reports", "timestudy")

_TIMESTUDY_RECORDS = os.path.join(_TIMESTUDY_DIR, "records.csv")

_TIMESTUDY_CSV_HEADERS = [
    "jira号", "记录时间", "提取来源", "提取结果", "是否正确",
    "错误类型", "错误详情", "修正后时间",
    "视频数量", "gmlogger数量", "参考时间",
    "OCR原文", "匹配差秒", "12h转换", "jira创建时间",
    "trace_steps"
]

_timestudy_lock = threading.Lock()

_record_write_lock = threading.Lock()

_DAILY_BROADCAST_CONFIG_PATH = os.path.join(PROJECT_ROOT, "data", "daily_broadcast_config.json")

_DAILY_BROADCAST_FOLDER = "I8Bwf17aAl9LR1dazOic7Q70nic"  # 云端每日结论文件夹

_daily_scheduler_thread = None

_daily_scheduler_stop = None

_cloud_batch_cache = {}  # {date_str: {"ts": float, "data": {jira_no: exec_info}}}

_CLOUD_CACHE_TTL = 300  # 5分钟缓存

_DEFAULT_TABLE_NAMES = {"数据表", "表格", "Table", "Sheet", "数据表1"}

_trigger_time_table_cache = {"app_token": "", "table_ids": [], "inited": False}

_trigger_time_bugid_cache = {}

_bitable_bulk_cache = {}  # key -> (timestamp, data)

_BITABLE_CACHE_TTL = 300  # 5分钟

_last_cache_load_partial = False

_TRIGGER_TIME_TABLE_LIMIT = 500

_GMLOGGER_REVIEW_KEYWORDS = {"无gmlogger", "无gmlogger文件", "无gmlogger日志文件", "无日志附件",
                              "该jira无日志附件", "该Jira无日志附件", "该jira无日志附件，属于正常处理机制",
                              "该Jira无日志附件，属于正常处理机制"}

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")

_easyocr_reader = None

_easyocr_lock = __import__('threading').Lock()  # 防止并发初始化

_video_time_cache_lock = threading.Lock()

_OCR_UNAVAILABLE = object()  # OCR 不可用哨兵值

_OCR_TIME_FULL_RE = re.compile(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2}[\s.,\-]?\d{1,2}[.:,]\d{2}(?:[.:,]\d{2})?)')

_OCR_TIME_ONLY_RE = re.compile(r'(?<!\d)(\d{1,2}[.:,]\d{2}(?:[.:,]\d{2})?)(?!\d)')

_OCR_BARE_TIME_RE = re.compile(r'(?<![a-zA-Z0-9\-/.])(\d{2})(\d{2})(?![a-zA-Z0-9\-/.])')

_OCR_COMMA_TIME_RE = re.compile(r'(?<!\d)(\d{1,2}),(\d{2})(?![\d,.])')

_OCR_CHAR_MAP = {
    'O': '0', 'o': '0',  # O → 0
    'I': '1', 'l': '1', 'L': '1',  # I/l/L → 1
    'Z': '2', 'z': '2',  # Z → 2
    'S': '5', 's': '5',  # S → 5
    'B': '8',            # B → 8
}

_VIDEO_TIME_CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "video_time_cache.json")

_video_time_cache = {}  # {cache_key: {"time": "...", "extracted_at": "..."}}

_VIDEO_CACHE_MAX_SIZE = 50000  # 最大缓存条目数

_VIDEO_CACHE_MAX_AGE_DAYS = 90  # 缓存过期天数

_UNANALYZED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "unanalyzed")

_AI_INIT_FIELD_ID = "customfield_13714"  # AI Init Analysis Result

_PROD_AI_URL_DEFAULT = "https://dpportal.apps.saic-gm.com/api/logAnalysis/parseFullTicket"

_auto_detect_stop = False

_AI_LOG_SERVICE_URL = "http://10.22.126.133:8001"

_STUDY_DIR = os.path.join(get_path("doc_dir"), "study")


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


async def _feishu_msg_debug_impl(request):
    """调试用：尝试所有认证方式读取指定群聊的消息（供 feishu_router 调用）"""


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

    # 更新服务：远程拉取最新代码并重启
    if text.strip() in ("更新服务", "更新代码", "拉取代码", "git pull"):
        import subprocess as _sp
        feishu_client.send_bot_message(chat_id, "正在拉取最新代码...")
        try:
            result = _sp.run(
                ["git", "pull", "origin", "master"],
                capture_output=True, text=True, timeout=60,
                cwd=PROJECT_ROOT
            )
            output = result.stdout.strip()
            if result.returncode == 0:
                already_up = "Already up to date" in output or "already up to date" in output
                if already_up:
                    feishu_client.send_bot_message(chat_id, "代码已是最新，无需更新")
                else:
                    feishu_client.send_bot_message(chat_id, f"代码更新成功，正在重启服务...\n{output[:200]}")
                    import sys as _sys
                    import asyncio as _aio
                    loop = _aio.get_event_loop()
                    loop.call_later(1.0, lambda: _sys.exit(0))
            else:
                feishu_client.send_bot_message(chat_id, f"拉取失败:\n{result.stderr[:300]}")
        except Exception as e:
            feishu_client.send_bot_message(chat_id, f"更新异常: {str(e)[:200]}")
        return

    # 触发时间自学习：发送 timestudy 触发分析
    if text.strip().lower() in ("timestudy", "自学习", "触发时间学习"):
        feishu_client.send_bot_message(chat_id, "正在分析触发时间提取记录...")
        try:
            patterns = _timestudy_analyze()
            total = patterns.get("total_records", 0)
            rate = patterns.get("success_rate", 0)
            err_dist = patterns.get("error_distribution", {})
            src_dist = patterns.get("source_distribution", {})
            # 构建摘要消息
            lines = [f"触发时间自学习分析完成",
                     f"总记录: {total} 条",
                     f"成功率: {rate}%",
                     f"用户修正: {patterns.get('corrected_count', 0)} 条",
                     f"12h转换: {patterns.get('h12_count', 0)} 条", ""]
            if src_dist:
                lines.append("提取来源分布:")
                for src, cnt in list(src_dist.items())[:5]:
                    lines.append(f"  {src}: {cnt}次")
                lines.append("")
            if err_dist:
                lines.append("错误类型Top5:")
                for err, cnt in list(err_dist.items())[:5]:
                    lines.append(f"  {err}: {cnt}次")
            else:
                lines.append("无错误记录")
            feishu_client.send_bot_message(chat_id, "\n".join(lines))
        except Exception as e:
            feishu_client.send_bot_message(chat_id, f"自学习分析失败: {e}")
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
            "6.2 单个执行（Jira号,PC/线上）\n"
            "9.1 Bug未分析提取（JQL）\n"
            "10.1 线上批量执行（输入Jira号）\n"
            "11.1 PC成功复制到线上\n\n"
            "发送「退出」可取消当前任务\n"
            "请输入子功能编号（如 0/6.1.1）唤醒对应功能（2分钟内有效）")
        return

    if session and session.get("state") == "wait_menu":
        stripped = text.strip()
        # 支持子功能编号直接跳转（0/4/5/6/9/10，支持6.1.1等三级编号）
        if re.match(r'^(0|4|5|6|9|10|11)\.\d(\.\d)?$', stripped):
            _clear_bot_session(chat_id)
            text = stripped  # 继续往下执行，让子功能处理逻辑接管
        elif stripped in ("0", "4", "5", "6", "9", "10", "11"):
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
            "6.2 单个执行（Jira号,PC/线上）\n\n"
            "请输入子功能编号")
        return

    # 6.1.1 JQL批量执行 → 子菜单
    if text == "6.1.1":
        _set_bot_session(chat_id, "wait_sub_menu", cmd="6.1.1")
        feishu_client.send_bot_message(chat_id,
            "6.1.1 JQL批量执行\n请输入功能：\n1: 基础信息修改\n2: 单次执行\n3: 持续执行")
        return

    # 6.1.2 已移除
    if text == "6.1.2":
        feishu_client.send_bot_message(chat_id, "6.1.2 CSV批量执行功能已移除，请使用 6.1.1")
        return

    # ========== 共享状态处理器：子菜单/基础信息修改/过滤选项 ==========

    # 子菜单选择（6.1.1/10.1共用）
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
            # 单次执行
            if cmd == "6.1.1":
                _set_bot_session(chat_id, "wait_filter_options", cmd=cmd, batch_meta=session.get("batch_meta", {}))
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
        elif choice == "3":
            # 持续执行：先配置每批数量、间隔和轮数
            _set_bot_session(chat_id, "wait_continuous_config", cmd=cmd, batch_meta=session.get("batch_meta", {}))
            feishu_client.send_bot_message(chat_id,
                "持续执行配置\n请输入：每批数量,间隔分钟,执行轮数\n示例: 50,10,5（每批50条，每10分钟一轮，共5轮）")
            return
        else:
            feishu_client.send_bot_message(chat_id, "请输入 1（基础信息修改）、2（单次执行）或 3（持续执行）")
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
                f"触发来源: {meta.get('trigger_source')}\n\n请输入功能：\n1: 基础信息修改\n2: 单次执行\n3: 持续执行")
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

    # 持续执行配置（6.1.1/10.1共用）
    if session and session.get("state") == "wait_continuous_config":
        cmd = session.get("cmd", "")
        meta = session.get("batch_meta", {})
        m = re.match(r'(\d+)\s*[,，]\s*(\d+)\s*[,，]\s*(\d+)', text.strip())
        if not m:
            feishu_client.send_bot_message(chat_id, "格式错误，请输入「每批数量,间隔分钟,执行轮数」\n示例: 50,10,5（每批50条，每10分钟一轮，共5轮）")
            return
        batch_count = int(m.group(1))
        interval_min = int(m.group(2))
        total_rounds = int(m.group(3))
        if batch_count <= 0:
            feishu_client.send_bot_message(chat_id, "每批数量必须大于 0")
            return
        if interval_min < 1 or interval_min > 120:
            feishu_client.send_bot_message(chat_id, "间隔时间必须在 1~120 分钟之间")
            return
        if total_rounds < 1 or total_rounds > 100:
            feishu_client.send_bot_message(chat_id, "执行轮数必须在 1~100 之间")
            return
        # 保存持续执行参数，进入过滤选项流程
        cont_params = {"continuous": True, "batch_count": batch_count, "interval_min": interval_min, "total_rounds": total_rounds}
        summary = f"持续执行：每批 {batch_count} 条，每 {interval_min} 分钟一轮，共 {total_rounds} 轮\n\n"
        if cmd == "6.1.1":
            _set_bot_session(chat_id, "wait_filter_options", cmd=cmd, batch_meta=meta, **cont_params)
            feishu_client.send_bot_message(chat_id,
                summary + "请选择过滤（多个用逗号分隔，如A1,A3）：\n"
                "☑ A0: 过滤表中所有记录\n☐ A1: 过滤PC正确和通用失败的\n"
                "☐ A2: 过滤线上正确和通用失败的\n☐ A3: 过滤AI初步分析结果\n\n"
                "默认勾选A0，输入「默认」使用默认勾选")
        elif cmd == "10.1":
            _set_bot_session(chat_id, "wait_prod_filter_options",
                             batch_meta=meta, cmd=cmd, **cont_params, skip_duplicates=True)
            feishu_client.send_bot_message(chat_id,
                summary + "请选择过滤（多个用逗号分隔，如A1,A3）：\n"
                "☐ A0: 过滤表中所有记录\n☐ A1: 过滤PC正确和通用失败的\n"
                "☐ A2: 过滤线上正确和通用失败的\n☑ A3: 过滤AI初步分析结果\n\n"
                "默认勾选A3，输入「默认」使用默认勾选")
        else:
            feishu_client.send_bot_message(chat_id, "未知功能，请重新输入")
            _clear_bot_session(chat_id)
        return

    # 6.1.1 过滤选项处理
    if session and session.get("state") == "wait_filter_options":
        filters = _parse_filter_input(text)
        meta = session.get("batch_meta", {})
        jql_presets = _get_jql_presets()
        jql_desc = "\n".join(f"{i+1}. {v[0]}({k})" for i, (k, v) in enumerate(jql_presets.items()))
        # 传递持续执行参数（如有）
        cont_kwargs = {}
        if session.get("continuous"):
            cont_kwargs = {"continuous": True, "batch_count": session.get("batch_count"),
                           "interval_min": session.get("interval_min"), "total_rounds": session.get("total_rounds")}
        _set_bot_session(chat_id, "wait_batch_jql_filter", filters=filters, batch_meta=meta, **cont_kwargs)
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
        is_continuous = session.get("continuous", False)
        interval_min = session.get("interval_min", 10)
        total_rounds = session.get("total_rounds", 5)
        # 持续模式下用 batch_count 替代输入的数量
        if is_continuous:
            count = session.get("batch_count", count)
        _clear_bot_session(chat_id)
        mode_label = "线上" if exec_mode == "online" else "PC"
        label = jql_presets[jql_key][0]
        if is_continuous:
            feishu_client.send_bot_message(chat_id,
                f"{jql_key}({label}) 持续执行\n每轮 {count} 条，{mode_label}模式\n"
                f"每 {interval_min} 分钟一轮，共 {total_rounds} 轮\n"
                f"过滤：{filters.get('desc', '默认')}\n发送「退出」可中断任务")
            _set_running_task(chat_id, f"JQL持续执行({jql_key},{count}条,{mode_label},{total_rounds}轮)")
            threading.Thread(target=_bot_run_batch_ai_continuous,
                             args=(chat_id, jql_key, count, exec_mode, filters, meta, interval_min, total_rounds),
                             name=f"bot-batch-cont-{jql_key}", daemon=True).start()
        else:
            feishu_client.send_bot_message(chat_id,
                f"{jql_key}({label}) 开始执行\n抽取 {count} 条，{mode_label}模式\n"
                f"过滤：{filters.get('desc', '默认')}\n发送「退出」可中断任务")
            _set_running_task(chat_id, f"JQL批量执行({jql_key},{count}条,{mode_label})")
            threading.Thread(target=_bot_run_batch_ai, args=(chat_id, jql_key, count, exec_mode, filters, meta),
                             name=f"bot-batch-{jql_key}", daemon=True).start()
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
            "10.1 线上批量执行\n请输入功能：\n1: 基础信息修改\n2: 单次执行\n3: 持续执行")
        return

    # 10.1 线上过滤选项处理
    if session and session.get("state") == "wait_prod_filter_options":
        filters = _parse_filter_input(text, default_skip=True)
        meta = session.get("batch_meta", {})
        # 传递持续执行参数（如有）
        cont_kwargs = {}
        if session.get("continuous"):
            cont_kwargs = {"continuous": True, "batch_count": session.get("batch_count"),
                           "interval_min": session.get("interval_min"), "total_rounds": session.get("total_rounds")}
        _set_bot_session(chat_id, "wait_prod_input", filters=filters, batch_meta=meta, **cont_kwargs)
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
        # 传递持续执行参数（如有）
        cont_kwargs = {}
        if session.get("continuous"):
            cont_kwargs = {"continuous": True, "batch_count": session.get("batch_count"),
                           "interval_min": session.get("interval_min"), "total_rounds": session.get("total_rounds")}
        _set_bot_session(chat_id, "wait_prod_execute", bugids=bugids, filters=filters, batch_meta=meta, **cont_kwargs)
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
        is_continuous = session.get("continuous", False)
        interval_min = session.get("interval_min", 10)
        total_rounds = session.get("total_rounds", 5)
        # 持续模式下用 batch_count 替代输入的数量
        if is_continuous:
            count = session.get("batch_count", count)
        _clear_bot_session(chat_id)
        mode_label = "线上" if exec_mode == "online" else "PC"
        if is_continuous:
            feishu_client.send_bot_message(chat_id,
                f"线上持续执行 {min(count, len(bugids))}/{len(bugids)} 条\n"
                f"{mode_label}模式，每轮 {count} 条，每 {interval_min} 分钟一轮，共 {total_rounds} 轮\n"
                f"过滤：{filters.get('desc', '默认')}\n发送「退出」可中断任务")
            _set_running_task(chat_id, f"线上持续执行({min(count, len(bugids))}条,{total_rounds}轮)")
            threading.Thread(target=_bot_prod_batch_run_continuous,
                             args=(chat_id, bugids, filters, meta, exec_mode, count, interval_min, total_rounds),
                             name="bot-prod-batch-cont", daemon=True).start()
        else:
            feishu_client.send_bot_message(chat_id,
                f"开始执行 {min(count, len(bugids))}/{len(bugids)} 条\n"
                f"{mode_label}模式，过滤：{filters.get('desc', '默认')}\n发送「退出」可中断任务")
            _set_running_task(chat_id, f"线上批量执行({min(count, len(bugids))}条)")
            threading.Thread(target=_bot_prod_batch_run, args=(chat_id, bugids, filters, meta, exec_mode, count),
                             name="bot-prod-batch", daemon=True).start()
        return

    # ==================== 功能11：线上正确执行跟进 ====================

    # 功能11主菜单
    if text == "11":
        feishu_client.send_bot_message(chat_id,
            "线上正确执行跟进\n子功能：\n"
            "11.1 PC成功复制到线上\n\n请输入子功能编号")
        return

    # 11.1 PC成功复制到线上 → 等待对比触发
    if text == "11.1":
        _set_bot_session(chat_id, "wait_11_1_compare")
        feishu_client.send_bot_message(chat_id,
            "11.1 PC成功批量复制到线上\n输入 0 开始对比")
        return

    # 11.2 已移除
    if text == "11.2":
        feishu_client.send_bot_message(chat_id, "11.2 失败重跑功能已移除，请使用 10.1 线上批量执行")
        return

    # 11.1 对比触发处理
    if session and session.get("state") == "wait_11_1_compare":
        if text.strip() != "0":
            feishu_client.send_bot_message(chat_id, "请输入 0 开始对比")
            return
        feishu_client.send_bot_message(chat_id, "正在对比 PC成功 vs 线上成功，请稍候...")
        try:
            result = _bot_compare_pc_online()
            diff_records = result.get("diff_records", [])
            pc_count = result.get("pc_success_count", 0)
            online_count = result.get("online_success_count", 0)
            diff_count = len(diff_records)
            if diff_count == 0:
                feishu_client.send_bot_message(chat_id,
                    f"对比完成：PC成功 {pc_count}，线上成功 {online_count}，差集 {diff_count}\n无差集，无需执行")
                _clear_bot_session(chat_id)
                return
            # 保存差集到session，进入执行配置
            _set_bot_session(chat_id, "wait_11_1_execute_config", diff_records=diff_records,
                             pc_count=pc_count, online_count=online_count)
            feishu_client.send_bot_message(chat_id,
                f"对比完成：PC成功 {pc_count}，线上成功 {online_count}，差集 {diff_count}\n\n"
                f"请输入：每批数量,间隔分钟,执行轮数\n示例: 50,10,3（每批50条，每10分钟一轮，共3轮，默认线上执行）")
        except Exception as e:
            logger.error("11.1 对比失败: %s", e)
            feishu_client.send_bot_message(chat_id, f"对比失败: {str(e)[:200]}")
            _clear_bot_session(chat_id)
        return

    # 11.1 执行配置处理
    if session and session.get("state") == "wait_11_1_execute_config":
        m = re.match(r'(\d+)\s*[,，]\s*(\d+)\s*[,，]\s*(\d+)', text.strip())
        if not m:
            feishu_client.send_bot_message(chat_id, "格式错误，请输入「每批数量,间隔分钟,执行轮数」\n示例: 50,10,3")
            return
        batch_size = int(m.group(1))
        interval_min = int(m.group(2))
        total_rounds = int(m.group(3))
        if batch_size <= 0 or interval_min < 1 or total_rounds < 1:
            feishu_client.send_bot_message(chat_id, "参数无效：每批数量>0，间隔≥1分钟，轮数≥1")
            return
        diff_records = session.get("diff_records", [])
        _clear_bot_session(chat_id)
        feishu_client.send_bot_message(chat_id,
            f"开始执行 {len(diff_records)} 条差集\n"
            f"每批 {batch_size} 条，每 {interval_min} 分钟一轮，共 {total_rounds} 轮（线上执行）\n"
            f"发送「退出」可中断任务")
        _set_running_task(chat_id, f"PC复制到线上({len(diff_records)}条,{total_rounds}轮)")
        threading.Thread(target=_bot_run_11_1_continuous,
                         args=(chat_id, diff_records, batch_size, interval_min, total_rounds),
                         name="bot-11-1-cont", daemon=True).start()
        return

    # 未识别命令：返回功能菜单
    feishu_client.send_bot_message(chat_id,
        "可用子功能：\n"
        "4.1 置信度批量写入（发送 4.1）\n"
        "5.1 失败批量排查（发送 5.1）\n"
        "5.2 单个Jira诊断（发送 5.2）\n"
        "6.1.1 JQL批量执行（发送 6.1.1）\n"
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
            # 修正触发时间的记录应重新纳入（对比 bitable 中的分析问题时间与云端/诊断缓存的触发时间）
            if exclude_keys:
                corrected_keys = set()
                try:
                    cloud_times, _ = _load_cloud_trigger_cache()
                    for rec in records:
                        fields = rec.get("fields", {})
                        fv = fields.get(bugid_field, "")
                        if isinstance(fv, list):
                            fv = "".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in fv)
                        elif isinstance(fv, dict):
                            fv = fv.get("text", str(fv))
                        jk = str(fv).strip()
                        if jk not in exclude_keys:
                            continue
                        old_time = _bitable_text(fields.get("分析问题时间", "")).strip()
                        # 检查云端触发时间表是否有不同的值
                        if jk in cloud_times and old_time and cloud_times[jk].strip() != old_time:
                            corrected_keys.add(jk)
                            logger.info("触发时间已修正(云端): %s %s→%s", jk, old_time, cloud_times[jk])
                            continue
                        # 检查诊断缓存是否有修正值
                        diag = _load_diagnose_cache(jk)
                        if diag and diag.get("correction_time") and old_time and diag["correction_time"].strip() != old_time:
                            corrected_keys.add(jk)
                            logger.info("触发时间已修正(诊断缓存): %s %s→%s", jk, old_time, diag["correction_time"])
                except Exception as e:
                    logger.warning("检查触发时间修正失败: %s", e)
                if corrected_keys:
                    exclude_keys -= corrected_keys
                    logger.info("触发时间修正重新纳入 %d 条", len(corrected_keys))
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
        main_cats = ["触发时间问题", "无gmlogger文件", "无报错信息，跳过排查", "分析任务执行超时，跳过排查"]
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


def _timestudy_analyze(after_time: str = "") -> dict:
    """深度分析 records.csv，生成 error_patterns.json 和 optimization_log.md

    Args:
        after_time: 可选，只分析该时间之后的记录（格式: YYYY-MM-DD HH:MM:SS）
    """
    import csv as _csv
    if not os.path.exists(_TIMESTUDY_RECORDS):
        return {"total_records": 0, "error_patterns": {}}
    # 读取所有记录
    records = []
    with open(_TIMESTUDY_RECORDS, "r", encoding="utf-8-sig") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            records.append(row)
    # 按时间过滤（记录时间字段）
    if after_time:
        after_time = after_time.strip()
        filtered = []
        for rec in records:
            rec_time = (rec.get("记录时间", "") or "").strip()
            if rec_time and rec_time >= after_time:
                filtered.append(rec)
        records = filtered
    if not records:
        return {"total_records": 0, "error_patterns": {}}
    total = len(records)
    # ===== 基础统计 =====
    error_counts = {}
    source_counts = {}
    success_count = 0
    fail_count = 0
    skip_count = 0  # 前置过滤跳过（无gmlogger等）
    corrected_count = 0
    h12_count = 0
    for rec in records:
        err = rec.get("错误类型", "").strip()
        src = rec.get("提取来源", "").strip()
        result = rec.get("提取结果", "").strip()
        h12 = rec.get("12h转换", "").strip()
        # 前置过滤跳过的记录不参与错误分析
        if src == "skipped":
            skip_count += 1
            if src:
                source_counts[src] = source_counts.get(src, 0) + 1
            continue
        if err:
            error_counts[err] = error_counts.get(err, 0) + 1
        if src:
            source_counts[src] = source_counts.get(src, 0) + 1
        if result:
            success_count += 1
        else:
            fail_count += 1
        if rec.get("是否正确", "").strip() == "corrected":
            corrected_count += 1
        if h12 == "yes":
            h12_count += 1
    sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
    # ===== 重复错误检测：同一 Jira 多次失败（排除前置跳过的记录）=====
    from collections import defaultdict
    jira_errors = defaultdict(list)  # {jira号: [record, ...]}
    for rec in records:
        src = rec.get("提取来源", "").strip()
        if src == "skipped":
            continue  # 前置跳过的不参与顽固检测
        err = rec.get("错误类型", "").strip()
        bugid = rec.get("jira号", "").strip()
        if err and bugid:
            jira_errors[bugid].append(rec)
    # 分类：顽固 Jira（2+次失败）
    stubborn_jiras = {bid: recs for bid, recs in jira_errors.items() if len(recs) >= 2}
    # ===== 共性特征分析：每种错误类型的失败记录是否共享特征 =====
    error_records_by_type = defaultdict(list)
    for rec in records:
        src = rec.get("提取来源", "").strip()
        if src == "skipped":
            continue  # 前置跳过的不参与错误分析
        err = rec.get("错误类型", "").strip()
        if err:
            error_records_by_type[err].append(rec)
    # 对每种错误类型分析共性
    error_analysis = {}
    for err_type, err_recs in error_records_by_type.items():
        n = len(err_recs)
        # 统计特征
        no_video = sum(1 for r in err_recs if r.get("视频数量", "0").strip() == "0")
        no_gm = sum(1 for r in err_recs if r.get("gmlogger数量", "0").strip() == "0")
        has_h12 = sum(1 for r in err_recs if r.get("12h转换", "").strip() == "yes")
        # 涉及的独立 Jira 数
        unique_jiras = len(set(r.get("jira号", "").strip() for r in err_recs if r.get("jira号", "").strip()))
        # 时间范围分析
        dates = sorted(set(r.get("jira创建时间", "")[:10] for r in err_recs if r.get("jira创建时间", "")))
        # 共性特征判定
        features = []
        if no_video / n > 0.7:
            features.append(f"{round(no_video/n*100)}%无视频附件")
        if no_gm / n > 0.7:
            features.append(f"{round(no_gm/n*100)}%无gmlogger")
        if has_h12 / n > 0.5:
            features.append(f"{round(has_h12/n*100)}%使用12h转换")
        if len(dates) >= 2 and dates[0] != dates[-1]:
            features.append(f"时间范围: {dates[0]}~{dates[-1]}")
        # 分类判定
        if unique_jiras >= 3 and len(features) >= 1:
            classification = "系统性问题"
        elif unique_jiras == 1 and n >= 3:
            classification = "顽固问题"
        else:
            classification = "偶发问题"
        error_analysis[err_type] = {
            "count": n,
            "unique_jiras": unique_jiras,
            "stubborn_jiras": [bid for bid in stubborn_jiras if any(r.get("错误类型", "").strip() == err_type for r in stubborn_jiras[bid])],
            "no_video_pct": round(no_video / n * 100, 1) if n else 0,
            "no_gm_pct": round(no_gm / n * 100, 1) if n else 0,
            "h12_pct": round(has_h12 / n * 100, 1) if n else 0,
            "date_range": f"{dates[0]}~{dates[-1]}" if dates else "",
            "common_features": features,
            "classification": classification,
            "example_jiras": list(set(r.get("jira号", "").strip() for r in err_recs[:5] if r.get("jira号", "").strip()))[:3],
        }
    # ===== 流水线断点分析：解析 trace_steps 找出常见断点 =====
    # 定义完整流水线的标准顺序
    _TRACE_STAGE_ORDER = [
        "cloud", "diag", "video", "gm", "dl", "frame", "ocr", "full",
        "12h", "cache", "fn", "partial", "text", "result", "fetch"
    ]
    # 每个步骤的中文描述
    _TRACE_STAGE_DESC = {
        "cloud": "云端缓存检查", "diag": "诊断缓存检查", "video": "视频附件检查",
        "gm": "gmlogger解析", "dl": "视频下载", "frame": "帧提取",
        "ocr": "OCR识别", "full": "完整时间匹配", "12h": "12h转换",
        "cache": "缓存命中", "fn": "文件名回退", "partial": "部分结果兜底",
        "text": "文本提取回退", "result": "最终结果", "fetch": "Jira获取"
    }
    # 统计断点：每个失败记录的最后一步
    breakpoint_counts = {}  # {step_code: count}
    # 统计每个错误类型的最常见断点
    error_type_breakpoints = defaultdict(lambda: defaultdict(int))
    # 统计完整流水线路径
    trace_pattern_counts = defaultdict(int)
    for rec in records:
        src = rec.get("提取来源", "").strip()
        if src == "skipped":
            continue  # 前置跳过的不参与断点分析
        trace_str = rec.get("trace_steps", "").strip()
        if not trace_str:
            continue
        steps = [s.strip() for s in trace_str.split("→") if s.strip()]
        if not steps:
            continue
        # 完整路径统计
        trace_pattern_counts[trace_str] += 1
        # 提取步骤代码（去掉参数部分）
        step_codes = []
        for s in steps:
            code = s.split(":")[0] if ":" in s else s
            step_codes.append(code)
        # 失败记录的断点分析
        err = rec.get("错误类型", "").strip()
        result = rec.get("提取结果", "").strip()
        if err and not result and step_codes:
            # 最后一个步骤就是断点
            last_step = step_codes[-1]
            breakpoint_counts[last_step] = breakpoint_counts.get(last_step, 0) + 1
            error_type_breakpoints[err][last_step] += 1
    # 排序断点
    sorted_breakpoints = sorted(breakpoint_counts.items(), key=lambda x: x[1], reverse=True)
    # 常见路径（Top 5）
    sorted_patterns = sorted(trace_pattern_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    # 将断点分析加入 error_analysis
    for err_type in error_analysis:
        bp = error_type_breakpoints.get(err_type, {})
        sorted_bp = sorted(bp.items(), key=lambda x: x[1], reverse=True)
        error_analysis[err_type]["breakpoints"] = [
            {"step": code,
             "desc": _TRACE_STAGE_DESC.get(code, code),
             "count": cnt,
             "pct": round(cnt / error_analysis[err_type]["count"] * 100, 1)}
            for code, cnt in sorted_bp
        ]
        # 主断点：最常见的断点
        if sorted_bp:
            main_bp = sorted_bp[0]
            desc = _TRACE_STAGE_DESC.get(main_bp[0], main_bp[0])
            pct = round(main_bp[1] / error_analysis[err_type]["count"] * 100, 1)
            error_analysis[err_type]["main_breakpoint"] = f"{desc} ({pct}%)"
        else:
            error_analysis[err_type]["main_breakpoint"] = "无trace数据"
    # 生成 error_patterns.json
    patterns = {
        "total_records": total,
        "skip_count": skip_count,
        "effective_total": total - skip_count,
        "success_count": success_count,
        "fail_count": fail_count,
        "corrected_count": corrected_count,
        "h12_count": h12_count,
        "success_rate": round(success_count / max(total - skip_count, 1) * 100, 1),
        "error_distribution": dict(sorted_errors),
        "source_distribution": dict(sorted(source_counts.items(), key=lambda x: x[1], reverse=True)),
        "stubborn_jiras": {bid: len(recs) for bid, recs in stubborn_jiras.items()},
        "error_analysis": error_analysis,
        "breakpoint_summary": [
            {"step": code, "desc": _TRACE_STAGE_DESC.get(code, code), "count": cnt}
            for code, cnt in sorted_breakpoints[:5]
        ],
        "common_trace_patterns": [
            {"trace": trace, "count": cnt} for trace, cnt in sorted_patterns
        ],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    patterns_path = os.path.join(_TIMESTUDY_DIR, "error_patterns.json")
    os.makedirs(_TIMESTUDY_DIR, exist_ok=True)
    with open(patterns_path, "w", encoding="utf-8") as f:
        import json as _json2
        _json2.dump(patterns, f, ensure_ascii=False, indent=2)
    # ===== 生成 optimization_log.md =====
    log_lines = [
        f"# 触发时间提取优化日志",
        f"",
        f"生成时间: {patterns['generated_at']}",
        f"",
        f"## 统计概览",
        f"",
        f"| 指标 | 值 |",
        f"|------|------|",
        f"| 总记录数 | {total} |",
        f"| 前置跳过(无gmlogger) | {skip_count} |",
        f"| 有效提取 | {total - skip_count} |",
        f"| 提取成功 | {success_count} ({patterns['success_rate']}%) |",
        f"| 提取失败 | {fail_count} |",
        f"| 用户修正 | {corrected_count} |",
        f"| 12h转换使用 | {h12_count} |",
        f"| 顽固Jira(2+次失败) | {len(stubborn_jiras)} 个 |",
        f"",
        f"## 提取来源分布",
        f"",
        f"| 来源 | 次数 | 占比 |",
        f"|------|------|------|",
    ]
    for src, cnt in patterns["source_distribution"].items():
        pct = round(cnt / total * 100, 1) if total else 0
        log_lines.append(f"| {src} | {cnt} | {pct}% |")
    # ===== 错误深度分析（核心部分）=====
    log_lines.extend(["", f"## 错误深度分析", ""])
    # 按分类分组
    systematic_errors = {k: v for k, v in error_analysis.items() if v["classification"] == "系统性问题"}
    stubborn_errors = {k: v for k, v in error_analysis.items() if v["classification"] == "顽固问题"}
    sporadic_errors = {k: v for k, v in error_analysis.items() if v["classification"] == "偶发问题"}
    if systematic_errors:
        log_lines.extend([f"### 系统性逻辑缺陷（需优先修复）", ""])
        for err_type, info in sorted(systematic_errors.items(), key=lambda x: x[1]["count"], reverse=True):
            log_lines.extend([
                f"#### {err_type} ({info['count']}次, {info['unique_jiras']}个Jira)",
                f"",
                f"- **分类**: 系统性问题 — 多个Jira共享相同失败特征",
                f"- **共性特征**: {', '.join(info['common_features']) or '无明显共性'}",
                f"- **断点分析**: {info.get('main_breakpoint', '无trace数据')}",
                f"- **无视频占比**: {info['no_video_pct']}% | **无gmlogger占比**: {info['no_gm_pct']}% | **12h转换占比**: {info['h12_pct']}%",
                f"- **时间范围**: {info['date_range'] or '无'}",
                f"- **示例Jira**: {', '.join(info['example_jiras'])}",
                "",
            ])
    if stubborn_errors:
        log_lines.extend([f"### 顽固问题（同一Jira反复失败）", ""])
        for err_type, info in sorted(stubborn_errors.items(), key=lambda x: x[1]["count"], reverse=True):
            stubborn_list = ', '.join(info['stubborn_jiras'][:5])
            log_lines.extend([
                f"#### {err_type} ({info['count']}次, {info['unique_jiras']}个Jira)",
                f"",
                f"- **分类**: 顽固问题 — 同一Jira多次提取均失败",
                f"- **顽固Jira**: {stubborn_list or '无'}",
                f"- **共性特征**: {', '.join(info['common_features']) or '无明显共性'}",
                f"- **断点分析**: {info.get('main_breakpoint', '无trace数据')}",
                f"- **示例Jira**: {', '.join(info['example_jiras'])}",
                "",
            ])
    if sporadic_errors:
        log_lines.extend([f"### 偶发问题（个别失败，无需优先处理）", ""])
        for err_type, info in sorted(sporadic_errors.items(), key=lambda x: x[1]["count"], reverse=True):
            log_lines.append(f"- **{err_type}** ({info['count']}次, {info['unique_jiras']}个Jira): {', '.join(info['common_features']) or '无明显特征'}")
        log_lines.append("")
    # ===== 流水线断点分析 =====
    if sorted_breakpoints:
        log_lines.extend([
            "## 流水线断点分析",
            "",
            "解析每条记录的 trace_steps 字段，找出失败时流水线断在哪一步：",
            "",
            "| 断点步骤 | 含义 | 失败次数 |",
            "|----------|------|----------|",
        ])
        for code, cnt in sorted_breakpoints[:8]:
            desc = _TRACE_STAGE_DESC.get(code, code)
            log_lines.append(f"| {code} | {desc} | {cnt} |")
        log_lines.append("")
        # 常见流水线路径
        if sorted_patterns:
            log_lines.extend([
                "### 常见提取路径",
                "",
                "| 路径 | 次数 |",
                "|------|------|",
            ])
            for trace, cnt in sorted_patterns:
                log_lines.append(f"| {trace} | {cnt} |")
            log_lines.append("")
        # 断点溯源建议
        log_lines.extend(["### 断点溯源", ""])
        for err_type, info in sorted(error_analysis.items(), key=lambda x: x[1]["count"], reverse=True):
            bp_list = info.get("breakpoints", [])
            if not bp_list:
                continue
            bp_str = "; ".join(f"{bp['desc']}({bp['count']}次,{bp['pct']}%)" for bp in bp_list[:3])
            log_lines.append(f"- **{err_type}** → 断在: {bp_str}")
        log_lines.append("")
    # ===== 优化建议（基于分析结果）=====
    log_lines.extend([f"## 优化建议", f""])
    suggestions = []
    # 系统性问题优先建议
    for err_type, info in systematic_errors.items():
        features_str = ", ".join(info["common_features"])
        if err_type == "video_download_failed":
            suggestions.append(f"- **视频下载失败** ({info['count']}次): 建议增大 httpx 超时时间或增加重试机制")
        elif err_type == "ocr_no_time_pattern":
            suggestions.append(f"- **OCR无时间模式** ({info['count']}次, {info['unique_jiras']}个Jira): 建议优化 OCR 正则或增加新的时间匹配模式，共性: {features_str}")
        elif err_type == "12h_ambiguity":
            suggestions.append(f"- **12h歧义** ({info['count']}次): 建议引入 Jira 创建时间等上下文判断 AM/PM")
        elif err_type == "time_no_match_gmlogger":
            suggestions.append(f"- **时间不匹配gmlogger** ({info['count']}次): 建议调整匹配阈值或改进 gmlogger 解析，共性: {features_str}")
        elif err_type == "no_video":
            suggestions.append(f"- **无视频附件** ({info['count']}次): 建议优化标题/评论/描述的文本提取逻辑")
        elif err_type == "gmlogger_missing":
            suggestions.append(f"- **无gmlogger参考** ({info['count']}次): 建议增强无 gmlogger 场景的时间验证")
        elif err_type == "all_sources_empty":
            suggestions.append(f"- **全部来源失败** ({info['count']}次): 需分析这些Jira的附件类型，考虑新增提取来源")
        elif err_type == "user_corrected":
            suggestions.append(f"- **用户修正** ({info['count']}次): 分析修正前后规律，自动调整提取策略")
        else:
            suggestions.append(f"- **{err_type}** ({info['count']}次, 系统性): {features_str}")
    # 顽固问题建议
    if stubborn_errors:
        stubborn_list = ', '.join(list(stubborn_errors.keys())[:3])
        suggestions.append(f"- **顽固失败** ({len(stubborn_errors)}种类型): {stubborn_list}，建议人工检查这些Jira的附件内容")
    if not suggestions:
        suggestions.append("暂无明显优化方向，建议积累更多数据后再分析")
    log_lines.extend(suggestions)
    log_lines.append("")
    os.makedirs(_TIMESTUDY_REPORT_DIR, exist_ok=True)
    log_path = os.path.join(_TIMESTUDY_REPORT_DIR, "optimization_log.md")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    logger.info("自学习分析完成: %d 条记录, %d 种错误类型, 系统性问题 %d 种, 顽固问题 %d 种",
                total, len(error_counts), len(systematic_errors), len(stubborn_errors))
    return patterns


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
            _timestudy_record(bugid, cloud_times[bugid], "cloud_cache",
                              ctx={"trace": ["cloud:hit"]})
            continue
        if bugid in cloud_keys:
            # 云端已标记无触发时间（空值），跳过
            continue
        need_fetch.append(bugid)
    if need_fetch:
        logger.info("触发时间: %d 个云端已有, %d 个需新提取", len(bugids) - len(need_fetch), len(need_fetch))
    # 检查诊断缓存：用户在诊断界面修正的触发时间优先使用，避免重新提取
    still_need = []
    for bugid in need_fetch:
        diag = _load_diagnose_cache(bugid)
        if diag and diag.get("correction_time"):
            trigger_times[bugid] = diag["correction_time"]
            logger.info("触发时间: %s 使用诊断缓存修正值 %s", bugid, diag["correction_time"])
            _timestudy_record(bugid, diag["correction_time"], "diag_cache",
                              error_detail="使用用户修正值",
                              ctx={"trace": ["diag:correction"]})
        elif diag and diag.get("suggested_time") and diag.get("verify_status") == "success":
            trigger_times[bugid] = diag["suggested_time"]
            logger.info("触发时间: %s 使用诊断缓存建议值 %s", bugid, diag["suggested_time"])
            _timestudy_record(bugid, diag["suggested_time"], "diag_cache",
                              ctx={"trace": ["diag:suggested"]})
        else:
            still_need.append(bugid)
    if len(still_need) < len(need_fetch):
        logger.info("诊断缓存命中 %d 个，剩余 %d 个需新提取", len(need_fetch) - len(still_need), len(still_need))
    need_fetch = still_need
    for bugid in need_fetch:
        try:
            issue = _jc.fetch_issue(bugid)
            # gmlogger 前置检查：无 gmlogger 附件的 Jira 直接跳过（与批量提取保持一致）
            attachments = (issue.get("fields") or {}).get("attachment") or []
            has_gmlogger = any("gmlogger" in (att.get("filename", "") or "").lower() for att in attachments)
            if not has_gmlogger:
                logger.info("触发时间: %s 无gmlogger附件，跳过", bugid)
                _timestudy_record(bugid, "", "skipped", error_type="no_gmlogger",
                                  error_detail="无gmlogger附件，前置过滤跳过",
                                  ctx={"trace": ["gm:0", "skip:no_gmlogger"]})
                continue
            # 初始化自学习上下文（视频提取前）
            _timestudy_init_ctx(bugid)
            # 提取 jira 创建时间用于自学习分析
            jira_created = (issue.get("fields") or {}).get("created", "") or ""
            _timestudy_update_ctx(bugid, jira_created=jira_created[:19])
            # 视频 OCR 优先级最高
            tt = _diag_extract_time_from_video_simple(issue)
            if tt:
                # 视频提取成功
                _timestudy_trace(bugid, "result:video_hit")
                ctx = _timestudy_get_ctx(bugid)
                source = ctx.get("source", "") or "video_ocr"
                _timestudy_record(bugid, str(tt), source, ctx=ctx)
            else:
                # 视频未提取到，回退到标题/评论/描述/自定义字段
                _timestudy_trace(bugid, "text:try")
                tt = _jc.extract_trigger_time_from_issue(issue)
                ctx = _timestudy_get_ctx(bugid)
                if tt:
                    _timestudy_trace(bugid, "text:hit")
                    _timestudy_record(bugid, str(tt), "text_fallback",
                                      error_type="no_video" if ctx.get("error_type") == "no_video" else "video_failed_text_fallback",
                                      error_detail=f"视频提取失败({ctx.get('error_type','')})→文本回退成功",
                                      ctx=ctx)
                else:
                    _timestudy_trace(bugid, "text:empty")
                    _timestudy_record(bugid, "", "empty",
                                      error_type=ctx.get("error_type") or "all_sources_empty",
                                      error_detail=ctx.get("error_detail") or "所有来源均未提取到触发时间",
                                      ctx=ctx)
            if tt:
                trigger_times[bugid] = str(tt)
            try:
                _save_trigger_time_to_cloud(bugid, str(tt) if tt else "")
            except Exception as save_e:
                logger.warning("云端保存触发时间失败 %s（不影响流程）: %s", bugid, save_e)
        except Exception as e:
            logger.warning("机器人提取触发时间失败 %s: %s", bugid, e)
            _timestudy_record(bugid, "", "error", error_type="fetch_failed", error_detail=str(e)[:200],
                              ctx={"trace": ["fetch:fail"]})
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
                payload = _build_prod_ai_payload(bugid, exec_time)
                resp = http_post(_get_prod_ai_url(), payload, timeout=_get_prod_ai_cfg()["timeout"])
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
                    payload = _build_prod_ai_payload(bugid, exec_time)
                    resp = http_post(_get_prod_ai_url(), payload, timeout=_get_prod_ai_cfg()["timeout"])
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
    """功能6.1.1后台执行：JQL搜索→过滤→优先缓存抽样→提取时间→执行"""
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
        # 步骤3+4：优先缓存抽样+提取触发时间
        remaining = list(filtered)
        # 先查缓存，将候选分为「有缓存」和「无缓存」两组
        cloud_times, cloud_keys = _load_cloud_trigger_cache()
        cached_candidates = [k for k in remaining if k in cloud_times]
        uncached_candidates = [k for k in remaining if k not in cloud_times]
        logger.info("抽样分组: 有缓存 %d, 无缓存 %d, 总计 %d",
                    len(cached_candidates), len(uncached_candidates), len(remaining))
        # 优先从有缓存的候选中随机抽取，不够再从无缓存中抽取
        import random as _rand
        selected = []
        trigger_times = {}
        if cached_candidates:
            _rand.shuffle(cached_candidates)
            take_cached = min(count, len(cached_candidates))
            selected = cached_candidates[:take_cached]
            trigger_times = {b: cloud_times[b] for b in selected}
            feishu_client.send_bot_message(chat_id,
                f"步骤3/5：缓存命中 {len(trigger_times)}/{count} 条触发时间")
        # 缓存不够时，从无缓存候选中提取
        if len(trigger_times) < count and uncached_candidates:
            _rand.shuffle(uncached_candidates)
            need = count - len(trigger_times)
            batch_size = min(need, len(uncached_candidates))
            batch = uncached_candidates[:batch_size]
            feishu_client.send_bot_message(chat_id,
                f"步骤4/5：缓存不足，新提取 {len(batch)} 条...")
            batch_times = _bot_get_trigger_times(batch)
            trigger_times.update(batch_times)
            selected.extend(b for b in batch if b in batch_times)
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        selected = selected[:count]
        has_cached = sum(1 for b in selected if b in cloud_times)
        feishu_client.send_bot_message(chat_id,
            f"提取完成: {len(selected)} 条有触发时间（缓存 {has_cached} + 新提取 {len(selected) - has_cached}）")
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
                    payload = _build_prod_ai_payload(bugid, exec_time)
                    resp = http_post(_get_prod_ai_url(), payload, timeout=_exec_timeout)
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


def _bot_run_batch_ai_continuous(chat_id: str, jql_key: str, count: int, exec_mode: str = "pc",
                                 filters: dict = None, batch_meta: dict = None,
                                 interval_min: int = 10, total_rounds: int = 5):
    """6.1.1 持续执行：循环执行 N 轮，每轮间隔 interval_min 分钟"""
    import time as _time
    from src.clients import feishu_client
    _reset_cancel_event(chat_id)
    mode_label = "线上" if exec_mode == "online" else "PC"
    total_success = 0
    total_fail = 0
    executed_set = set()  # 跨轮已执行 Jira 号跟踪，避免重复执行
    try:
        for round_num in range(1, total_rounds + 1):
            if _is_cancelled(chat_id):
                feishu_client.send_bot_message(chat_id, f"任务已被用户取消（完成 {round_num - 1}/{total_rounds} 轮）")
                break
            feishu_client.send_bot_message(chat_id,
                f"=== 第 {round_num}/{total_rounds} 轮 [{mode_label}] ===")
            # 复用单次执行的核心逻辑，但不清除 running task
            round_executed = _bot_run_batch_ai_single_round(
                chat_id, jql_key, count, exec_mode, filters, batch_meta,
                round_num, total_rounds, executed_set)
            if round_executed:
                executed_set.update(round_executed)
            if _is_cancelled(chat_id):
                break
            if round_num < total_rounds:
                feishu_client.send_bot_message(chat_id,
                    f"第 {round_num} 轮完成（累计已执行 {len(executed_set)} 条），"
                    f"等待 {interval_min} 分钟后开始下一轮...\n发送「退出」可中断")
                # 可中断的等待（每秒检查取消标记）
                for _ in range(interval_min * 60):
                    if _is_cancelled(chat_id):
                        break
                    _time.sleep(1)
        if not _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id,
                f"持续执行完成（共 {total_rounds} 轮，累计执行 {len(executed_set)} 条不重复）")
    except Exception as e:
        logger.error("6.1.1 持续执行失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"持续执行异常中断: {str(e)[:200]}")
    finally:
        _clear_running_task(chat_id)


def _bot_run_batch_ai_single_round(chat_id: str, jql_key: str, count: int, exec_mode: str,
                                   filters: dict, batch_meta: dict, round_num: int, total_rounds: int,
                                   executed_set: set = None) -> set:
    """6.1.1 持续执行的单轮逻辑（复用 _bot_run_batch_ai 的核心流程，但不操作 running task）

    :param executed_set: 跨轮已执行的 Jira 号集合，本轮会从中排除并在完成后返回新增的
    :return: 本轮实际执行的 Jira 号集合
    """
    from src.clients import feishu_client
    from src.clients import jira_client as _jc
    from src.clients.base import http_post
    executed_set = executed_set if executed_set is not None else set()
    this_round_executed = set()
    try:
        jql_presets = _get_jql_presets()
        preset = jql_presets.get(jql_key)
        if not preset:
            feishu_client.send_bot_message(chat_id, f"未找到 JQL 编号 {jql_key}")
            return this_round_executed
        label, jql = preset
        mode_label = "线上" if exec_mode == "online" else "PC"
        # 步骤1：JQL搜索
        feishu_client.send_bot_message(chat_id, f"[{round_num}/{total_rounds}] 步骤1/5：JQL搜索 [{jql_key}({label})]...")
        try:
            issues = _jc.search_issues(jql, max_results=2000)
            candidates = [(i.get("key") or "").strip() for i in issues if "VCU" in (i.get("key") or "").upper()]
        except Exception as e:
            logger.warning("机器人 JQL 搜索失败: %s", e)
            feishu_client.send_bot_message(chat_id, f"JQL 搜索失败：{str(e)[:150]}")
            return this_round_executed
        if not candidates:
            feishu_client.send_bot_message(chat_id, "JQL 搜索无 VCU 结果，请检查 JQL 条件")
            return this_round_executed
        if _is_cancelled(chat_id):
            return this_round_executed
        # 步骤2：多维表格去重过滤
        feishu_client.send_bot_message(chat_id, f"搜索完成 {len(candidates)} 条，步骤2/5：过滤记录...")
        filtered = _bot_apply_bitable_filter(candidates, filters)
        if not filtered:
            feishu_client.send_bot_message(chat_id, f"搜索 {len(candidates)} 条均已被过滤，无需执行")
            return this_round_executed
        # 跨轮去重：排除前几轮已执行的 Jira 号
        if executed_set:
            before = len(filtered)
            filtered = [b for b in filtered if b not in executed_set]
            skipped = before - len(filtered)
            if skipped:
                feishu_client.send_bot_message(chat_id,
                    f"跨轮去重：排除前几轮已执行的 {skipped} 条")
        if not filtered:
            feishu_client.send_bot_message(chat_id, f"所有候选均已在前几轮执行过，本轮跳过")
            return this_round_executed
        if _is_cancelled(chat_id):
            return this_round_executed
        # 步骤3+4：优先缓存抽样+提取触发时间
        remaining = list(filtered)
        # 先查缓存，将候选分为「有缓存」和「无缓存」两组
        cloud_times, cloud_keys = _load_cloud_trigger_cache()
        cached_candidates = [k for k in remaining if k in cloud_times]
        uncached_candidates = [k for k in remaining if k not in cloud_times]
        import random as _rand
        selected = []
        trigger_times = {}
        if cached_candidates:
            _rand.shuffle(cached_candidates)
            take_cached = min(count, len(cached_candidates))
            selected = cached_candidates[:take_cached]
            trigger_times = {b: cloud_times[b] for b in selected}
            feishu_client.send_bot_message(chat_id,
                f"[{round_num}/{total_rounds}] 步骤3/5：缓存命中 {len(trigger_times)}/{count} 条触发时间")
        if len(trigger_times) < count and uncached_candidates:
            _rand.shuffle(uncached_candidates)
            need = count - len(trigger_times)
            batch_size = min(need, len(uncached_candidates))
            batch = uncached_candidates[:batch_size]
            feishu_client.send_bot_message(chat_id,
                f"[{round_num}/{total_rounds}] 步骤4/5：缓存不足，新提取 {len(batch)} 条...")
            batch_times = _bot_get_trigger_times(batch)
            trigger_times.update(batch_times)
            selected.extend(b for b in batch if b in batch_times)
        if _is_cancelled(chat_id):
            return this_round_executed
        selected = selected[:count]
        has_cached = sum(1 for b in selected if b in cloud_times)
        feishu_client.send_bot_message(chat_id,
            f"提取完成: {len(selected)} 条（缓存 {has_cached} + 新提取 {len(selected) - has_cached}）")
        # 步骤5：执行
        run_bugids = [b for b in selected if b in trigger_times]
        if not run_bugids:
            feishu_client.send_bot_message(chat_id, "抽取的记录均无触发时间，无法执行")
            return this_round_executed
        feishu_client.send_bot_message(chat_id, f"[{round_num}/{total_rounds}] 步骤5/5：{mode_label}执行 {len(run_bugids)} 条...")
        success, lines, results = _bot_trigger_and_reply(chat_id, run_bugids, trigger_times,
                                                         realtime=False, exec_mode=exec_mode)
        this_round_executed = set(run_bugids)
        if not _is_cancelled(chat_id):
            try:
                _save_bot_execution_results(results, batch_name=f"bot_{exec_mode}_r{round_num}_{datetime.now().strftime('%H%M%S')}",
                                            batch_meta=batch_meta)
            except Exception as e:
                logger.warning("机器人批量结果保存失败: %s", e)
            feishu_client.send_bot_message(chat_id,
                f"[{round_num}/{total_rounds}] 执行完成: {success}/{len(run_bugids)} 成功")
    except Exception as e:
        logger.error("6.1.1 第 %d 轮执行异常: %s", round_num, e)
        feishu_client.send_bot_message(chat_id, f"[{round_num}/{total_rounds}] 执行异常: {str(e)[:200]}")
    return this_round_executed


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
    """功能10.1后台执行：批量执行（过滤→提取触发时间→调用接口）"""
    from src.clients import feishu_client
    _reset_cancel_event(chat_id)
    mode_label = "线上" if exec_mode == "online" else "PC"
    try:
        # 步骤1：多维表格去重过滤
        feishu_client.send_bot_message(chat_id, f"步骤1/3：过滤记录（{len(bugids)} 个）...")
        remaining = _bot_apply_bitable_filter(bugids, filters)
        if count and count > 0:
            remaining = remaining[:count]
        feishu_client.send_bot_message(chat_id, f"过滤后剩余 {len(remaining)} 个")
        if not remaining:
            feishu_client.send_bot_message(chat_id, "所有 Jira 号均已被过滤，无需执行")
            return
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        # 步骤2：提取触发时间（仅对过滤后的）
        feishu_client.send_bot_message(chat_id, f"步骤2/3：提取触发时间（{len(remaining)} 个）...")
        trigger_times = _bot_get_trigger_times(remaining)
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        has_time = sum(1 for b in remaining if b in trigger_times)
        feishu_client.send_bot_message(chat_id, f"提取完成: {has_time}/{len(remaining)} 有触发时间")
        # 仅保留有触发时间的记录
        remaining = [b for b in remaining if b in trigger_times]
        if not remaining:
            feishu_client.send_bot_message(chat_id, "抽取的记录均无触发时间，无法执行")
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


def _bot_prod_batch_run_continuous(chat_id: str, bugids: list, filters: dict = None,
                                   batch_meta: dict = None, exec_mode: str = "online",
                                   count: int = 0, interval_min: int = 10, total_rounds: int = 5):
    """10.1 持续执行：循环执行 N 轮，每轮间隔 interval_min 分钟"""
    import time as _time
    from src.clients import feishu_client
    _reset_cancel_event(chat_id)
    mode_label = "线上" if exec_mode == "online" else "PC"
    try:
        # 步骤1：多维表格去重过滤（只做一次）
        feishu_client.send_bot_message(chat_id, f"步骤1/3：过滤记录（{len(bugids)} 个）...")
        remaining = _bot_apply_bitable_filter(bugids, filters)
        if count and count > 0:
            remaining = remaining[:count]
        feishu_client.send_bot_message(chat_id, f"过滤后剩余 {len(remaining)} 个")
        if not remaining:
            feishu_client.send_bot_message(chat_id, "所有 Jira 号均已被过滤，无需执行")
            return
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        # 步骤2：提取触发时间（仅对过滤后的）
        feishu_client.send_bot_message(chat_id, f"步骤2/3：提取触发时间（{len(remaining)} 个）...")
        trigger_times = _bot_get_trigger_times(remaining)
        if _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, "任务已被用户取消")
            return
        has_time = sum(1 for b in remaining if b in trigger_times)
        feishu_client.send_bot_message(chat_id, f"提取完成: {has_time}/{len(remaining)} 有触发时间")
        # 仅保留有触发时间的记录
        remaining = [b for b in remaining if b in trigger_times]
        if not remaining:
            feishu_client.send_bot_message(chat_id, "抽取的记录均无触发时间，无法执行")
            return
        # 循环执行 N 轮
        done_total = 0
        for round_num in range(1, total_rounds + 1):
            if _is_cancelled(chat_id):
                feishu_client.send_bot_message(chat_id, f"任务已被用户取消（完成 {round_num - 1}/{total_rounds} 轮）")
                break
            # 每轮从未执行的记录中取一批
            undone = remaining[done_total:]
            if not undone:
                feishu_client.send_bot_message(chat_id, f"所有 {len(remaining)} 条已执行完毕，提前结束")
                break
            batch_size = min(len(undone), max(1, len(remaining) // total_rounds))
            batch = undone[:batch_size]
            feishu_client.send_bot_message(chat_id,
                f"=== 第 {round_num}/{total_rounds} 轮 [{mode_label}] ===\n执行 {len(batch)} 个...")
            success, lines, results = _bot_trigger_and_reply(chat_id, batch, trigger_times,
                                                             realtime=False, exec_mode=exec_mode)
            done_total += len(batch)
            if _is_cancelled(chat_id):
                break
            try:
                _save_bot_execution_results(results, batch_name=f"prod_r{round_num}_{datetime.now().strftime('%H%M%S')}",
                                            batch_meta=batch_meta)
            except Exception as e:
                logger.warning("机器人线上批量结果保存失败: %s", e)
            feishu_client.send_bot_message(chat_id,
                f"[{round_num}/{total_rounds}] 执行完成: {success}/{len(batch)} 成功（累计 {done_total}/{len(remaining)}）")
            if round_num < total_rounds and done_total < len(remaining):
                feishu_client.send_bot_message(chat_id,
                    f"等待 {interval_min} 分钟后开始下一轮...\n发送「退出」可中断")
                for _ in range(interval_min * 60):
                    if _is_cancelled(chat_id):
                        break
                    _time.sleep(1)
        if not _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id, f"持续执行完成（共 {total_rounds} 轮，累计执行 {done_total} 条）")
    except Exception as e:
        logger.error("10.1 持续执行失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"持续执行异常中断: {str(e)[:200]}")
    finally:
        _clear_running_task(chat_id)


def _clear_audited_impl():
    """清空已抽查记录（供 audit_router 调用）"""
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


async def _verify_and_fill_impl(request: Request):
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
            _sse_d = {'type': 'file_start', 'file_index': file_idx,
                                        'file_name': file_name, 'file_total': len(csv_paths)}
            yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
            rows = _read_csv_rows(csv_path)
            if not rows:
                _sse_d = {'type': 'file_error', 'file_index': file_idx,
                                            'msg': f'{file_name}: CSV 为空'}
                yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
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
            _sse_d = {'type': 'start', 'file_index': file_idx,
                                        'total': total, 'file_name': file_name}
            yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
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
                        _sse_d = {'type': 'progress', 'file_index': file_idx,
                                                    'index': idx + 1, 'total': total, 'bugid': bugid,
                                                    'status': 'skipped', 'rootcause': '', 'confidence': '',
                                                    'comment_summary': '', 'msg': '多维表格中未成功，已跳过'}
                        yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
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
                            _sse_d = {'type': 'progress', 'file_index': file_idx,
                                                        'index': idx + 1, 'total': total, 'bugid': bugid,
                                                        'status': 'success' if is_ready else 'low_confidence',
                                                        'rootcause': calc_rootcause[:80],
                                                        'confidence': str(conf_val),
                                                        'comment_summary': calc_comment,
                                                        'doc_url': calc_doc_url,
                                                        'doc_path': calc_doc_path,
                                                        'msg': '' if is_ready else reason}
                            yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
                        else:
                            err_msg = result.get('error', '')
                            is_skip = '根因分析内容为空' in err_msg
                            log_writer.writerow({"jira号": bugid, "达标": "否", "原因": err_msg[:200]})
                            _sse_d = {'type': 'progress', 'file_index': file_idx,
                                                        'index': idx + 1, 'total': total, 'bugid': bugid,
                                                        'status': 'skipped' if is_skip else 'fail',
                                                        'rootcause': '', 'confidence': '',
                                                        'comment_summary': '',
                                                        'msg': err_msg}
                            yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
                    except Exception as e:
                        log_writer.writerow({"jira号": bugid, "达标": "否", "原因": str(e)[:200]})
                        _sse_d = {'type': 'progress', 'file_index': file_idx,
                                                    'index': idx + 1, 'total': total, 'bugid': bugid,
                                                    'status': 'fail', 'rootcause': '', 'confidence': '',
                                                    'comment_summary': '',
                                                    'msg': str(e)[:200]}
                        yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
            _sse_d = {'type': 'file_done', 'file_index': file_idx,
                                        'file_name': file_name, 'total': total,
                                        'ready': ready_count, 'low_conf': low_conf_count,
                                        'compare_log': compare_log_path, 'csv_path': csv_path}
            yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
        # 处理直接传入的 jira 号列表
        if bugids:
            file_idx = len(csv_paths)
            file_name = f"jira输入({len(bugids)}个)"
            _sse_d = {'type': 'file_start', 'file_index': file_idx,
                                        'file_name': file_name, 'file_total': len(csv_paths) + 1}
            yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
            rows = [{"jira号": b} for b in bugids]
            bugid_col = "jira号"
            confidence_threshold = float(load_config().get("similarity", {}).get("threshold", 0.7))
            # 对比记录文件：docs/日期/jira_input_compare_log.csv
            date_str = datetime.now().strftime("%Y-%m-%d")
            compare_log_dir = os.path.join(get_path("doc_dir"), date_str)
            os.makedirs(compare_log_dir, exist_ok=True)
            compare_log_path = os.path.join(compare_log_dir, "jira_input_compare_log.csv")
            total = len(rows)
            _sse_d = {'type': 'start', 'file_index': file_idx,
                                        'total': total, 'file_name': file_name}
            yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
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
                        _sse_d = {'type': 'progress', 'file_index': file_idx,
                                                    'index': idx + 1, 'total': total, 'bugid': bugid,
                                                    'status': 'skipped', 'rootcause': '', 'confidence': '',
                                                    'comment_summary': '', 'msg': '多维表格中未成功，已跳过'}
                        yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
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
                            _sse_d = {'type': 'progress', 'file_index': file_idx,
                                                        'index': idx + 1, 'total': total, 'bugid': bugid,
                                                        'status': 'success' if is_ready else 'low_confidence',
                                                        'rootcause': calc_rootcause[:80],
                                                        'confidence': str(conf_val),
                                                        'comment_summary': calc_comment,
                                                        'doc_url': calc_doc_url,
                                                        'doc_path': calc_doc_path,
                                                        'msg': '' if is_ready else reason}
                            yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
                        else:
                            err_msg = result.get('error', '')
                            is_skip = '根因分析内容为空' in err_msg
                            log_writer.writerow({"jira号": bugid, "达标": "否", "原因": err_msg[:200]})
                            _sse_d = {'type': 'progress', 'file_index': file_idx,
                                                        'index': idx + 1, 'total': total, 'bugid': bugid,
                                                        'status': 'skipped' if is_skip else 'fail',
                                                        'rootcause': '', 'confidence': '',
                                                        'comment_summary': '',
                                                        'msg': err_msg}
                            yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
                    except Exception as e:
                        log_writer.writerow({"jira号": bugid, "达标": "否", "原因": str(e)[:200]})
                        _sse_d = {'type': 'progress', 'file_index': file_idx,
                                                    'index': idx + 1, 'total': total, 'bugid': bugid,
                                                    'status': 'fail', 'rootcause': '', 'confidence': '',
                                                    'comment_summary': '',
                                                    'msg': str(e)[:200]}
                        yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
            _sse_d = {'type': 'file_done', 'file_index': file_idx,
                                        'file_name': file_name, 'total': total,
                                        'ready': ready_count, 'low_conf': low_conf_count,
                                        'compare_log': compare_log_path, 'csv_path': ''}
            yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
        yield f"data: {_json.dumps({'type': 'all_done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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


def _diag_list_archive_entries(att_url: str, headers: dict, timeout: int, bugid: str = "") -> dict:
    """下载压缩包附件并列出解压后的文件名（支持 zip/tar 系，其余标记不支持）"""
    import tarfile
    import tempfile
    import zipfile
    import httpx as _httpx
    _label = f"{bugid} " if bugid else ""
    logger.info("%s开始下载附件: %s", _label, att_url[:120])
    entries = []
    total_size = 0
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src_path = os.path.join(tmp, "att.bin")
            # 流式下载，避免一次性加载到内存
            with _httpx.stream("GET", att_url, headers=headers, timeout=timeout, verify=False, follow_redirects=True) as resp:
                resp.raise_for_status()
                with open(src_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
                        total_size += len(chunk)
            logger.info("%s附件下载完成: size=%d bytes", _label, total_size)
            ok, names = _diag_archive_names(src_path)
            if not ok:
                return {"ok": False, "entries": [], "reason": names, "size": total_size}
            entries = names
        return {"ok": True, "entries": entries, "reason": "", "size": total_size}
    except Exception as e:
        return {"ok": False, "entries": [], "reason": f"下载/解压异常: {e}", "size": total_size}


def _diag_list_rar_multi_entries(parts: list, headers: dict, timeout: int, bugid: str = "") -> dict:
    """将 rar 分卷附件全部下载到同一目录，用 7z/UnRAR 列出条目名称

    :param parts: [(part_num, att), ...] 已按 part_num 排序
    :return: {"ok": bool, "entries": [str], "reason": str, "size": int}
    """
    import tempfile
    import httpx as _httpx
    _label = f"{bugid} " if bugid else ""
    total_size = 0
    try:
        with tempfile.TemporaryDirectory() as tmp:
            rar_dir = os.path.join(tmp, "rar_parts")
            os.makedirs(rar_dir, exist_ok=True)
            # 流式下载所有分卷到同一目录（保持原始文件名，7z 需要自动续卷）
            for _p, att in parts:
                fname = att.get("filename", "") or f"part{_p}.rar"
                dst = os.path.join(rar_dir, fname)
                logger.info("%s下载 rar 分卷: %s", _label, fname)
                with open(dst, "wb") as out:
                    with _httpx.stream("GET", att.get("content", ""), headers=headers,
                                       timeout=timeout, verify=False, follow_redirects=True) as r:
                        r.raise_for_status()
                        for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                            out.write(chunk)
                            total_size += len(chunk)
            logger.info("%srar 分卷下载完成: %d bytes, %d 个卷", _label, total_size, len(parts))
            # 用第一卷的路径调用 7z/UnRAR 列出条目
            first_fname = parts[0][1].get("filename", "") or f"part{parts[0][0]}.rar"
            first_path = os.path.join(rar_dir, first_fname)
            ok, names = _diag_archive_names(first_path)
            if not ok:
                # 回退到 7z 命令行
                names = _diag_7z_list_entries(first_path, rar_dir)
                if not names:
                    return {"ok": False, "entries": [], "reason": f"7z 列出条目失败", "size": total_size}
            return {"ok": True, "entries": names if isinstance(names, list) else [], "reason": "", "size": total_size}
    except Exception as e:
        return {"ok": False, "entries": [], "reason": f"rar 分卷下载/解压异常: {e}", "size": total_size}


def _diag_7z_list_entries(archive_path: str, work_dir: str) -> list:
    """用 7z 命令行列出压缩包内条目名称，返回文件名列表或空列表"""
    import subprocess
    tool = _diag_7z_tool_path()
    if not tool:
        return []
    try:
        result = subprocess.run([tool, "l", archive_path], capture_output=True, timeout=120, check=False,
                                cwd=work_dir)
        output = result.stdout.decode("utf-8", errors="ignore")
        entries = []
        # 7z l 输出格式：每行一个文件，跳过头部信息
        in_file_list = False
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("---"):
                in_file_list = not in_file_list
                continue
            if in_file_list and line:
                # 7z 输出格式：日期 时间 属性 大小 压缩后 文件名
                parts = line.split()
                if len(parts) >= 6:
                    fname = " ".join(parts[5:])
                    if not fname.endswith("/"):
                        entries.append(fname)
        return entries
    except Exception as e:
        logger.warning("7z 列出条目失败: %s", e)
        return []


def _diag_archive_names(path: str) -> tuple:
    """列出压缩包内条目名称（支持 zip/7z/tar/rar），返回 (ok, 名称列表或失败原因)"""
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
        pass
    # rar 支持
    try:
        import rarfile
        if _setup_rarfile() and rarfile.is_rarfile(path):
            with rarfile.RarFile(path) as rf:
                return True, [n for n in rf.namelist() if not n.endswith("/")]
    except ImportError:
        pass
    except rarfile.NeedFirstVolume:
        return False, "rar 分卷压缩包，需要第一卷"
    except Exception as e:
        return False, f"rar 打开失败: {e}"
    return False, "非 zip/7z/tar/rar 格式，无法解压"


def _diag_archive_read_heads(path: str, names: list, size: int = 65536) -> dict:
    """批量读取压缩包内多个文件的头部内容（支持 zip/7z/tar/rar），返回 {name: 头部文本}

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
        # 7z 格式
        import py7zr
        if py7zr.is_7zfile(path):
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                with py7zr.SevenZipFile(path, "r") as zf:
                    zf.extract(tmp, targets=names)
                for n in names:
                    fp = os.path.join(tmp, n)
                    if os.path.exists(fp):
                        try:
                            with open(fp, "rb") as f:
                                result[n] = f.read(size).decode("utf-8", errors="ignore")
                        except Exception:
                            continue
            return result
        # rar 格式
        import rarfile
        if _setup_rarfile() and rarfile.is_rarfile(path):
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                with rarfile.RarFile(path) as rf:
                    for n in names:
                        try:
                            rf.extract(n, tmp)
                        except Exception:
                            continue
                for n in names:
                    fp = os.path.join(tmp, n)
                    if os.path.exists(fp):
                        try:
                            with open(fp, "rb") as f:
                                result[n] = f.read(size).decode("utf-8", errors="ignore")
                        except Exception:
                            continue
            return result
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
    """定位本机 7z 可执行文件（用于 rar 解压），未找到返回空串

    搜索顺序：项目 tools 目录 → 系统安装路径 → PATH
    """
    import shutil
    # 优先查找项目内工具目录
    project_tools = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools", "7-Zip")
    candidates = [
        os.path.join(project_tools, "7z.exe"),
        os.path.join(project_tools, "7za.exe"),
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return shutil.which("7z") or shutil.which("7za") or ""


def _setup_rarfile() -> bool:
    """配置 rarfile 使用可用的解压工具（UnRAR.exe / 7z.exe），返回是否配置成功"""
    try:
        import rarfile
    except ImportError:
        return False
    # 搜索可用工具
    tools_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools", "7-Zip")
    unrar_path = os.path.join(tools_dir, "UnRAR.exe")
    sevenz_path = _diag_7z_tool_path()
    # 优先使用 UnRAR.exe
    if os.path.exists(unrar_path):
        rarfile.UNRAR_TOOL = unrar_path
        return True
    # 回退到 7z.exe
    if sevenz_path:
        rarfile.SEVENZIP_TOOL = sevenz_path
        return True
    # 检查 PATH 中的 unrar / 7z
    import shutil
    for tool in ("unrar", "7z", "7za"):
        found = shutil.which(tool)
        if found:
            rarfile.UNRAR_TOOL = found
            return True
    return False


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
    """解压 rar 提取包内 main 相关文件的时间，返回结构与 _diag_gmlogger_main_times 一致

    优先使用 rarfile + UnRAR.exe，回退到 7z.exe
    """
    import subprocess
    main_dir = os.path.join(work_dir, "rar_main")
    os.makedirs(main_dir, exist_ok=True)
    tool = _diag_7z_tool_path()
    use_rarfile = _setup_rarfile()
    if not tool and not use_rarfile:
        return {"status": "failed", "reason": "未找到 rar 解压工具（请安装 7-Zip 或 UnRAR）", "main_entries": [], "main_times": []}
    # 提取 main 相关文件
    extracted = False
    if use_rarfile:
        try:
            import rarfile
            with rarfile.RarFile(rar_first) as rf:
                # 筛选 main 相关条目
                main_targets = [n for n in rf.namelist() if "main" in os.path.basename(n).lower()]
                if main_targets:
                    for n in main_targets:
                        rf.extract(n, main_dir)
                    extracted = True
                else:
                    # 未找到 main，解压全部前5个文件用于时间探测
                    all_names = [n for n in rf.namelist() if not n.endswith("/")][:5]
                    if all_names:
                        for n in all_names:
                            rf.extract(n, main_dir)
                        extracted = True
        except Exception as e:
            logger.warning("rarfile 解压失败: %s", e)
    # 回退到 7z.exe
    if not extracted and tool:
        try:
            subprocess.run([tool, "x", rar_first, f"-o{main_dir}", "*main*", "-y"],
                           capture_output=True, timeout=300, check=False)
            extracted = True
        except Exception as e:
            return {"status": "failed", "reason": f"rar 解压异常: {e}", "main_entries": [], "main_times": []}
    if not extracted:
        return {"status": "failed", "reason": "rar 解压失败（无可用工具）", "main_entries": [], "main_times": []}
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
    # 全量条目清单：扫描全部文件名时间，任一命中窗口即验证通过
    all_names = []
    if tool:
        try:
            lr = subprocess.run([tool, "l", "-ba", rar_first], capture_output=True, timeout=120, check=False)
            all_names = [ln.split()[-1] for ln in lr.stdout.decode("utf-8", errors="ignore").splitlines() if ln.strip()]
        except Exception as e:
            logger.warning("rar 条目清单获取失败: %s", e)
    elif use_rarfile:
        try:
            import rarfile
            with rarfile.RarFile(rar_first) as rf:
                all_names = [n for n in rf.namelist() if not n.endswith("/")]
        except Exception as e:
            logger.warning("rar 条目清单获取失败: %s", e)
    all_times = _diag_scan_entry_times(all_names)
    return {"status": "ok", "reason": "",
            "main_entries": [os.path.basename(p) for p in main_files],
            "main_times": main_times, "all_times": all_times}


def _diag_download_archives(attachments: list, headers: dict, timeout: int, problem_time: str, bugid: str = "") -> tuple:
    """逐个下载压缩包附件并解压，比对解压文件名与错误时间（前后5分钟），返回 (archive_results, matched_any)

    支持 rar 分卷（part1.rar, part2.rar 等）统一处理。
    """
    import re as _re
    import tempfile
    import httpx as _httpx
    from src.clients.jira_client import _ARCHIVE_SUFFIXES
    archive_results = []
    matched_any = False
    _label = f"{bugid} " if bugid else ""
    # 连续解压失败计数器：超过阈值时停止下载（避免无意义的附件下载浪费时间和带宽）
    consecutive_fail_count = 0
    MAX_CONSECUTIVE_FAILS = 3  # 连续失败3次后停止下载

    # 预处理：对 rar 分卷附件按基础名分组
    rar_groups = {}  # base_name -> [(part_num, att), ...]
    processed_fnames = set()
    for att in attachments:
        fname = att.get("filename", "") or ""
        if not fname or not any(fname.lower().endswith(s) for s in _ARCHIVE_SUFFIXES):
            continue
        # 匹配 rar 分卷模式：filename.part1.rar, filename.part01.rar 等
        m = _re.match(r"^(.+)\.part(\d+)\.rar$", fname, _re.I)
        if m:
            base = m.group(1)
            part = int(m.group(2))
            rar_groups.setdefault(base, []).append((part, att))
        else:
            # 非分卷附件，单独处理
            rar_groups[fname] = [(0, att)]

    # 对每个分组统一处理
    for base, parts in rar_groups.items():
        if bugid:
            _check_diag_cancel(bugid)
        # 检查连续解压失败次数，超过阈值时停止下载
        if consecutive_fail_count >= MAX_CONSECUTIVE_FAILS:
            logger.warning("%s连续 %d 个附件解压失败，停止下载剩余附件", _label, consecutive_fail_count)
            break
        parts.sort(key=lambda x: x[0])
        is_multi_part_rar = len(parts) > 1 and base.lower().endswith(".rar")

        if is_multi_part_rar:
            # rar 分卷：将所有卷下载到同一目录，用 7z 列出条目
            info = {"filename": f"{base} (分卷{len(parts)}个)", "size": sum(a.get("size", 0) for _, a in parts),
                    "entries": [], "matched_entries": [], "status": "", "reason": ""}
            logger.info("%s处理 rar 分卷: %s (%d 个卷)", _label, base, len(parts))
            try:
                res = _diag_list_rar_multi_entries(parts, headers, timeout, bugid)
            except Exception as e:
                logger.warning("%srar 分卷处理异常 %s: %s", _label, base, e)
                info["status"], info["reason"] = "下载失败", str(e)
                archive_results.append(info)
                consecutive_fail_count += 1
                continue
            if not res["ok"]:
                logger.warning("%srar 分卷解压失败 %s: %s", _label, base, res["reason"])
                info["status"], info["reason"] = "无法解压", res["reason"]
                archive_results.append(info)
                consecutive_fail_count += 1
                continue
            consecutive_fail_count = 0
            info["entries"] = res["entries"]
            main_log_entries = [n for n in res["entries"] if "main.log" in os.path.basename(n).lower()]
            matched = [n for n in main_log_entries
                       if _diag_match_time_window(os.path.basename(n), problem_time, 5)[0]]
            info["matched_entries"] = matched
            info["status"] = "已解压"
            if matched:
                matched_any = True
            logger.info("%srar 分卷处理完成: %s, 条目数=%d, 匹配=%d", _label, base, len(res["entries"]), len(matched))
            archive_results.append(info)
        else:
            # 非分卷附件：单独处理
            _p, att = parts[0]
            fname = att.get("filename", "")
            logger.info("%s开始处理附件: %s (size=%s)", _label, fname, att.get("size", "unknown"))
            info = {"filename": fname, "size": att.get("size", 0), "entries": [],
                    "matched_entries": [], "status": "", "reason": ""}
            try:
                res = _diag_list_archive_entries(att.get("content", ""), headers, timeout, bugid)
            except Exception as e:
                logger.warning("%s附件处理异常 %s: %s", _label, fname, e)
                info["status"], info["reason"] = "下载失败", str(e)
                archive_results.append(info)
                consecutive_fail_count += 1
                continue
            if not res["ok"]:
                logger.warning("%s附件解压失败 %s: %s", _label, fname, res["reason"])
                info["status"], info["reason"] = "无法解压", res["reason"]
                archive_results.append(info)
                consecutive_fail_count += 1
                continue
            # 解压成功，重置计数器
            consecutive_fail_count = 0
            info["entries"] = res["entries"]
            # 只筛选文件名包含 main.log 的条目做时间比对（如 main.log_2022_9_16_9_37.gz）
            main_log_entries = [n for n in res["entries"] if "main.log" in os.path.basename(n).lower()]
            matched = [n for n in main_log_entries
                       if _diag_match_time_window(os.path.basename(n), problem_time, 5)[0]]
            info["matched_entries"] = matched
            info["status"] = "已解压"
            if matched:
                matched_any = True
            logger.info("%s附件处理完成: %s, 条目数=%d, 匹配=%d", _label, fname, len(res["entries"]), len(matched))
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
            _easyocr_reader = easyocr.Reader(['en'], gpu=True, verbose=False)
            logger.info("easyocr Reader 初始化完成")
        except Exception as e:
            logger.warning("easyocr 初始化失败（模型下载超时或网络不可用），视频 OCR 功能已禁用: %s", e)
            _easyocr_reader = _OCR_UNAVAILABLE
            return None
    return _easyocr_reader


def _normalize_ocr_time(text: str) -> str:
    """将 OCR 时间中的点号/逗号分隔符替换为冒号（10.26.39 → 10:26:39），并规范化日期时间分隔"""
    # 0. 修正年份 OCR 误识别：首位 3-9 大概率是 2 被误识别（如 6024 → 2024）
    def _fix_year(m):
        y = int(m.group(0))
        if 3000 <= y <= 9999:
            return str(2000 + y % 1000)
        return m.group(0)
    text = re.sub(r'\b(\d{4})(?=[/-])', _fix_year, text)
    # 1. 日期与无分隔符时间拆分（如 2024-01-22172440 → 2024-01-22 17:24:40）
    def _split_date_digits(m):
        date_part, digits = m.group(1), m.group(2)
        # 验证日期合理性
        parts = re.split(r'[/-]', date_part)
        if len(parts) == 3:
            try:
                mo, day = int(parts[1]), int(parts[2])
                if not (1 <= mo <= 12 and 1 <= day <= 31):
                    return m.group(0)
            except ValueError:
                return m.group(0)
        if len(digits) >= 6:
            hh, mm, ss = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
            if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
                return f"{date_part} {hh:02d}:{mm:02d}:{ss:02d}"
        if len(digits) >= 4:
            hh, mm = int(digits[0:2]), int(digits[2:4])
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return f"{date_part} {hh:02d}:{mm:02d}"
        return m.group(0)
    text = re.sub(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})(\d{4,6})(?!\d)', _split_date_digits, text)
    # 2. 日期和时间之间的点号/逗号分隔符（如 2026-01-09.14:02 → 2026-01-09 14:02）
    text = re.sub(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})[.,](\d{1,2}[.:,]\d{2})', r'\1 \2', text)
    # 3. 日期和时间无分隔符（如 2026-01-0914:02 → 2026-01-09 14:02）
    text = re.sub(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})(\d{1,2}[.:,]\d{2})', r'\1 \2', text)
    # 4. 将时间点号和逗号替换为冒号
    text = re.sub(r'(\d{1,2})[.,](\d{2})(?:[.,](\d{2}))?',
                  lambda m: f"{m.group(1)}:{m.group(2)}" + (f":{m.group(3)}" if m.group(3) else ""), text)
    # 5. 处理独立 6 位数字时间 HHMMSS（如 172440 → 17:24:40）
    def _fix_6digit_time(m):
        hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
            return f"{m.group(1)}:{m.group(2)}:{m.group(3)}"
        return m.group(0)
    text = re.sub(r'(?<![\d.:,])(\d{2})(\d{2})(\d{2})(?![\d.:,])', _fix_6digit_time, text)
    return text


def _fix_ocr_missing_colon(text: str) -> str:
    """修复 OCR 漏识别冒号/逗号分隔符的问题
    - 逗号作为冒号：10,12 → 10:12（EasyOCR 常见误识别）
    - 孤立 4 位数字补冒号：1433 → 14:33
    """
    # 先处理逗号作为冒号的情况（如 10,12 → 10:12）
    def _fix_comma(m):
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{m.group(1)}:{m.group(2)}"
        return m.group(0)
    text = _OCR_COMMA_TIME_RE.sub(_fix_comma, text)
    # 处理孤立 4 位数字（如 1433 → 14:33）
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


def _preprocess_ocr_datetime(text: str) -> str:
    """OCR 日期时间预处理：修正年份、拆分日期与无分隔符时间
    用于正则匹配前的文本预处理，解决 6024-01-22172440 等极端 OCR 误识别
    """
    # 修正年份（如 6024 → 2024）
    def _fix_year(m):
        y = int(m.group(0))
        if 3000 <= y <= 9999:
            return str(2000 + y % 1000)
        return m.group(0)
    text = re.sub(r'\b(\d{4})(?=[/-])', _fix_year, text)
    # 拆分日期与无分隔符时间（如 2024-01-22172440 → 2024-01-22 17:24:40）
    def _split_date_digits(m):
        date_part, digits = m.group(1), m.group(2)
        parts = re.split(r'[/-]', date_part)
        if len(parts) == 3:
            try:
                mo, day = int(parts[1]), int(parts[2])
                if not (1 <= mo <= 12 and 1 <= day <= 31):
                    return m.group(0)
            except ValueError:
                return m.group(0)
        if len(digits) >= 6:
            hh, mm, ss = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
            if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
                return f"{date_part} {hh:02d}:{mm:02d}:{ss:02d}"
        if len(digits) >= 4:
            hh, mm = int(digits[0:2]), int(digits[2:4])
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return f"{date_part} {hh:02d}:{mm:02d}"
        return m.group(0)
    text = re.sub(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})(\d{4,6})(?!\d)', _split_date_digits, text)
    return text


def _fix_ocr_char_confusion(text: str) -> str:
    """修夌 OCR 常见字符混淆：O→0, I/l/L→1, Z→2, S→5, B→8
    仅对匹配时间模式的片段进行替换，避免误修改其他文本
    """
    # 匹配类似时间的模式（含字母混淆），如 ZO:LI → 20:11
    def _fix_time_like(m):
        result = []
        for ch in m.group(0):
            result.append(_OCR_CHAR_MAP.get(ch, ch))
        return ''.join(result)
    # 匹配 HH:MM 模式（允许字母混入）
    text = re.sub(r'[OoIlLZzSB0-9]{1,2}[.:,][OoIlLZzSB0-9]{2}(?:[.:,][OoIlLZzSB0-9]{2})?', _fix_time_like, text)
    return text


def _parse_video_filename_time(filename: str) -> str:
    """从视频文件名提取时间（回退方案，当 OCR 失败时使用）
    支持格式：
    - 中文计时：14点02.mp4 → 14:02
    - 紧凑时间：140230 → 14:02:30
    - 文件名内嵌时间：20260928-163807.mp4 → 16:38:07
    自动跳过 hash 文件名（如 08aa2049aa5ae952...mp4）
    """
    name = filename.rsplit('.', 1)[0] if '.' in filename else filename
    # 跳过 hash 文件名（32位以上十六进制字符）
    if re.match(r'^[0-9a-fA-F]{20,}$', name):
        return ""
    # 1. 中文计时：X点Y分 或 X点Y
    m = re.search(r'(\d{1,2})[点時时](\d{1,2})(?:[分]?)(\d{1,2})?', name)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        ss = int(m.group(3)) if m.group(3) else 0
        if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
    # 2. 紧凑时间 HHMMSS
    m = re.search(r'(?<!\d)([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?!\d)', name)
    if m:
        return f"{m.group(1)}:{m.group(2)}:{m.group(3)}"
    # 3. 紧凑时间 HHMM
    m = re.search(r'(?<!\d)([01]\d|2[0-3])([0-5]\d)(?!\d)', name)
    if m:
        return f"{m.group(1)}:{m.group(2)}:00"
    # 4. 带分隔符时间 HH-MM-SS 或 HH_MM_SS
    m = re.search(r'(?<!\d)([01]\d|2[0-3])[-_]([0-5]\d)(?:[-_]([0-5]\d))?(?!\d)', name)
    if m:
        ss = m.group(3) or "00"
        return f"{m.group(1)}:{m.group(2)}:{ss}"
    return ""


def _correct_ocr_by_reference(time_str: str, ref_dt) -> str:
    """参照 gmlogger 时间纠正 OCR 数字混淆（如 07:10 被识别为 19:19）
    在参考时间±5分钟范围内生成候选，选择与 OCR 结果数字差异最少的候选。
    普通场景最多允许1位差异；12h偏移场景（AM/PM混淆）允许3位差异。
    """
    m = re.match(r'(\d{2}):(\d{2})(?::(\d{2}))?', time_str)
    if not m or ref_dt is None:
        return time_str
    hh_str, mm_str = m.group(1), m.group(2)
    ss = m.group(3) or "00"
    ocr_digits = [int(hh_str[0]), int(hh_str[1]), int(mm_str[0]), int(mm_str[1])]
    ocr_hh = ocr_digits[0] * 10 + ocr_digits[1]
    ref_minutes = ref_dt.hour * 60 + ref_dt.minute
    # 如果已经足够接近，无需纠正
    ocr_minutes = ocr_digits[0] * 600 + ocr_digits[1] * 60 + ocr_digits[2] * 10 + ocr_digits[3]
    if abs(ocr_minutes - ref_minutes) <= 5:
        return time_str
    best = None
    best_diff_count = 5
    best_time_diff = 9999
    for offset in range(-5, 6):
        cand_min = (ref_minutes + offset) % 1440
        ch, cm = divmod(cand_min, 60)
        if ch > 23:
            continue
        cand_digits = [ch // 10, ch % 10, cm // 10, cm % 10]
        diff_count = sum(1 for i in range(4) if cand_digits[i] != ocr_digits[i])
        if diff_count == 0:
            continue
        # 普通场景最多1位差异；12h偏移(AM/PM混淆)允许3位
        hour_diff = abs(ch - ocr_hh)
        is_12h_confusion = 10 <= hour_diff <= 14
        max_diff = 3 if is_12h_confusion else 1
        if diff_count > max_diff:
            continue
        time_diff = abs(offset)
        if diff_count < best_diff_count or (diff_count == best_diff_count and time_diff < best_time_diff):
            best = f"{ch:02d}:{cm:02d}:{ss}"
            best_diff_count = diff_count
            best_time_diff = time_diff
    if best and best != time_str:
        logger.info("OCR数字混淆纠正: %s -> %s (参考: %02d:%02d, 差异%d位)", time_str, best, ref_dt.hour, ref_dt.minute, best_diff_count)
    return best or time_str


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
    # 小时 < 12：尝试 +12h 转换
    # 小时 >= 12：尝试 -12h 转换（gmlogger 包内时间戳可能有时区偏移）
    if hour < 12:
        dt_alt = dt + timedelta(hours=12)
        ts_alt = dt_alt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        dt_alt = dt - timedelta(hours=12)
        ts_alt = dt_alt.strftime("%Y-%m-%d %H:%M:%S")
    # 1. gmlogger 文件名时间作为参考锚点：如果某个版本与文件名时间接近（±30分钟），优先取
    if gm_ref_dt:
        diff_orig = abs((dt - gm_ref_dt).total_seconds())
        diff_alt = abs((dt_alt - gm_ref_dt).total_seconds())
        close_threshold = 1800  # 30分钟
        orig_close = diff_orig <= close_threshold
        alt_close = diff_alt <= close_threshold
        if alt_close and not orig_close:
            logger.info("视频时间 12h 转换：%s → %s（与 gmlogger 文件名时间 %s 接近）",
                        ts, ts_alt, gm_ref_dt.strftime("%H:%M:%S"))
            return ts_alt, dt_alt
        if orig_close and not alt_close:
            return parsed
        # 两个都接近或都不接近，继续看 ref_pool
        if orig_close and alt_close:
            # 两个都接近 gmlogger，取更近的那个
            if diff_alt < diff_orig:
                return ts_alt, dt_alt
            return parsed
    # 2. 与 ref_pool 对比（±5分钟命中），兼容纯 datetime 和 (字符串, datetime) 元组
    hit_orig = any(abs(((ref[1] if isinstance(ref, tuple) else ref) - dt).total_seconds()) <= 300 for ref in ref_pool) if ref_pool else False
    hit_alt = any(abs(((ref[1] if isinstance(ref, tuple) else ref) - dt_alt).total_seconds()) <= 300 for ref in ref_pool) if ref_pool else False
    if hit_alt and not hit_orig:
        logger.info("视频时间 12h 转换：%s → %s（与包内时间戳命中）", ts, ts_alt)
        return ts_alt, dt_alt
    if hit_orig:
        return parsed
    # 3. 都没命中，有 gmlogger 参考就取更近的，否则默认原始值
    if gm_ref_dt:
        diff_orig = abs((dt - gm_ref_dt).total_seconds())
        diff_alt = abs((dt_alt - gm_ref_dt).total_seconds())
        if diff_alt < diff_orig:
            logger.info("视频时间 12h 转换：%s → %s（与 gmlogger 文件名时间更接近）", ts, ts_alt)
            return ts_alt, dt_alt
    return parsed


def _rank_videos(videos: list, attachments: list) -> list:
    """按与 gmlogger 相关性对视频排序，返回排序后的列表（最相关的在前）。

    排序策略（按优先级）：
    1. 视频文件名含日期时间且gmlogger文件名有时间 → 按与 gmlogger 时间差升序
    2. gmlogger文件名无时间 → 按与gmlogger上传时间差升序
    3. 完全无 gmlogger 参考 → 按视频上传时间升序
    """
    if len(videos) <= 1:
        return list(videos)
    gm_times = _diag_gmlogger_times(attachments)
    gm_ref_dt = gm_times[0][1] if gm_times else None
    gm_upload_dt = None
    for att in attachments:
        fname = att.get("filename", "") or ""
        if fname and "gmlogger" in fname.lower():
            gm_upload_dt = _ts_parse_datetime(att.get("created", ""))
            break
    def _sort_key(v):
        fname = v.get("filename", "") or ""
        parsed = _diag_parse_entry_time(fname)
        if parsed and gm_ref_dt:
            return (0, abs((parsed[1] - gm_ref_dt).total_seconds()), "")
        v_upload_dt = _ts_parse_datetime(v.get("created", ""))
        if v_upload_dt and gm_upload_dt:
            return (1, abs((v_upload_dt - gm_upload_dt).total_seconds()), v.get("created", ""))
        return (2, 0, v.get("created", ""))
    ranked = sorted(videos, key=_sort_key)
    return ranked


def _pick_best_video(videos: list, attachments: list) -> dict:
    """从多个视频附件中选取与 gmlogger 最相关的一个"""
    ranked = _rank_videos(videos, attachments)
    selected = ranked[0]
    gm_times = _diag_gmlogger_times(attachments)
    gm_ref_dt = gm_times[0][1] if gm_times else None
    parsed = _diag_parse_entry_time(selected.get("filename", ""))
    if parsed and gm_ref_dt:
        logger.info("视频选取：文件名时间 %s 最接近 gmlogger 时间 %s", parsed[0], gm_times[0][0])
    elif len(videos) > 1:
        gm_upload_dt = None
        for att in attachments:
            fname = att.get("filename", "") or ""
            if fname and "gmlogger" in fname.lower():
                gm_upload_dt = _ts_parse_datetime(att.get("created", ""))
                break
        if gm_upload_dt:
            logger.info("视频选取：上传时间 %s 最接近 gmlogger 上传时间", selected.get("created", ""))
        else:
            logger.info("视频选取：按上传时间取最早 %s", selected.get("filename", ""))
    return selected


def _extract_video_frames_gpu(video_path: str, positions: list = None, num_frames: int = 6, use_gpu: bool = True) -> list:
    """从视频文件中提取指定位置的帧，优先使用 GPU 硬件加速解码。

    参数:
        positions: 要提取的秒数位置列表，如 [0, 1, 3, 6]。若为 None，则提取前 num_frames 秒的帧。
        num_frames: 当 positions 为 None 时，提取前 N 秒的帧
    返回: [(秒数, numpy_bgr_array), ...] 列表。
    GPU 不可用或解码失败时自动回退到 CPU。"""
    import numpy as np
    if positions is None:
        positions = list(range(num_frames))
    if not positions:
        return []
    positions = sorted(set(positions))  # 去重排序
    frames = []
    # 优先尝试 PyAV + GPU 解码
    if use_gpu:
        try:
            import av
            container = av.open(video_path)
            stream = container.streams.video[0]
            stream.thread_type = 'AUTO'
            fps = float(stream.average_rate or stream.base_rate or 30)
            logger.info("视频帧提取：使用 PyAV (GPU优先) FPS=%.1f", fps)
            for sec in positions:
                try:
                    if sec == 0:
                        # 第一帧：直接解码，避免 seek 到错误位置
                        for frame in container.decode(video=0):
                            img = frame.to_ndarray(format='bgr24')
                            frames.append((sec, img))
                            break
                    else:
                        target_ts = int(sec * stream.time_base.denominator / (stream.time_base.numerator * fps))
                        container.seek(target_ts, any_frame=False, backward=True, stream=stream)
                        for frame in container.decode(video=0):
                            frame_sec = float(frame.pts * stream.time_base) if frame.pts is not None else sec
                            if frame_sec >= sec - 0.5:  # 允许 0.5秒误差
                                img = frame.to_ndarray(format='bgr24')
                                frames.append((sec, img))
                                break
                except Exception as e:
                    logger.warning("视频帧提取：PyAV 第%d秒提取失败: %s", sec, e)
            container.close()
            if frames:
                logger.info("视频帧提取：PyAV GPU 解码成功，截取 %d 帧", len(frames))
                return frames
            logger.warning("视频帧提取：PyAV GPU 解码未获取到帧，回退 CPU")
        except ImportError:
            logger.info("视频帧提取：PyAV 未安装，回退 OpenCV")
        except Exception as e:
            logger.warning("视频帧提取：PyAV GPU 解码异常: %s，回退 CPU", e)
    # 回退: OpenCV CPU 解码
    try:
        import cv2
    except ImportError:
        logger.warning("视频帧提取：缺少 opencv-python-headless")
        return []
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning("视频帧提取：无法打开视频 %s", os.path.basename(video_path))
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    for sec in positions:
        try:
            if sec == 0:
                # 第一帧：确保回到视频开头后读取
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
                if ret:
                    frames.append((sec, frame))
                continue
            frame_pos = int(sec * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = cap.read()
            if ret:
                frames.append((sec, frame))
        except Exception as e:
            logger.warning("视频帧提取：OpenCV 第%d秒提取失败: %s", sec, e)
    cap.release()
    logger.info("视频帧提取：OpenCV CPU 解码，截取 %d 帧", len(frames))
    return frames


def _clean_video_time_cache_locked():
    """清理过期和超出上限的缓存条目（内部实现，调用方须已持有 _video_time_cache_lock）"""
    global _video_time_cache
    if not _video_time_cache:
        return
    from datetime import datetime, timedelta
    now = datetime.now()
    cutoff = now - timedelta(days=_VIDEO_CACHE_MAX_AGE_DAYS)
    expired_keys = []
    for k, v in _video_time_cache.items():
        extracted_at = v.get("extracted_at", "")
        if extracted_at:
            try:
                dt = datetime.strptime(extracted_at, "%Y-%m-%d %H:%M:%S")
                if dt < cutoff:
                    expired_keys.append(k)
            except (ValueError, TypeError):
                pass
    if expired_keys:
        for k in expired_keys:
            del _video_time_cache[k]
        logger.info("视频时间缓存清理：已清理 %d 条过期条目", len(expired_keys))
    # 超出上限时按时间排序清理最早的
    if len(_video_time_cache) > _VIDEO_CACHE_MAX_SIZE:
        sorted_items = sorted(
            _video_time_cache.items(),
            key=lambda x: x[1].get("extracted_at", "1970-01-01 00:00:00")
        )
        overflow = len(sorted_items) - _VIDEO_CACHE_MAX_SIZE
        for k, _ in sorted_items[:overflow]:
            del _video_time_cache[k]
        logger.info("视频时间缓存清理：已清理 %d 条超出上限的最早条目", overflow)


def _clean_video_time_cache():
    """清理过期和超出上限的缓存条目（线程安全）"""
    with _video_time_cache_lock:
        _clean_video_time_cache_locked()


def _load_video_time_cache() -> dict:
    """加载视频提取时间缓存，自动清理旧的空时间缓存条目"""
    global _video_time_cache
    if _video_time_cache:
        return _video_time_cache
    if os.path.exists(_VIDEO_TIME_CACHE_FILE):
        try:
            import json
            with open(_VIDEO_TIME_CACHE_FILE, "r", encoding="utf-8") as f:
                _video_time_cache = json.load(f)
            # 清理旧的空时间缓存条目（之前版本缓存的失败结果）
            empty_keys = [k for k, v in _video_time_cache.items() if not v.get("time")]
            if empty_keys:
                for k in empty_keys:
                    del _video_time_cache[k]
                logger.info("已清理 %d 条空时间缓存", len(empty_keys))
            # 清理过期和超出上限的条目
            _clean_video_time_cache()
            _save_video_time_cache()
            logger.info("视频时间缓存已加载: %d 条", len(_video_time_cache))
        except Exception as e:
            logger.warning("视频时间缓存加载失败: %s", e)
            _video_time_cache = {}
    return _video_time_cache


def _save_video_time_cache():
    """保存视频提取时间缓存到本地文件（线程安全，原子写入）"""
    import json
    with _video_time_cache_lock:
        cache_path = _VIDEO_TIME_CACHE_FILE
        tmp_path = cache_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            # 写入前先清理过期/超限条目（调用内部方法，避免重复加锁导致死锁）
            _clean_video_time_cache_locked()
            # 先写同目录临时文件，再原子替换，避免并发/中断产生半截文件
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(_video_time_cache, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, cache_path)
        except Exception as e:
            logger.warning("视频时间缓存保存失败: %s", e)
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _get_video_cache_key(bugid: str, video_filename: str) -> str:
    """生成视频缓存键: bugid:video_filename"""
    return f"{bugid}:{video_filename}"


def _build_gmlogger_info(attachments: list) -> list:
    """构建 gmlogger 附件详细信息列表，用于智能匹配视频

    :return: [{"filename": str, "filename_time": datetime|None, "upload_time": datetime|None, "time_str": str}]
    """
    info_list = []
    for att in attachments:
        fname = att.get("filename", "") or ""
        if not fname or "gmlogger" not in fname.lower():
            continue
        parsed = _diag_parse_entry_time(fname)
        filename_time = parsed[1] if parsed else None
        upload_time = _ts_parse_datetime(att.get("created", ""))
        info_list.append({
            "filename": fname,
            "filename_time": filename_time,
            "upload_time": upload_time,
            "time_str": parsed[0] if parsed else "",
        })
    return info_list


def _find_closest_gmlogger(video_att: dict, gm_info_list: list) -> list:
    """根据视频与 gmlogger 的接近程度排序，返回按接近度排序的 gmlogger 列表

    接近度判断优先级：
    1. 视频文件名时间与 gmlogger 文件名时间接近（优先，当视频文件名有时间时）
    2. 视频上传时间与 gmlogger 上传时间接近（视频无文件名时间时作为首要依据）
    3. 视频上传时间与 gmlogger 文件名时间接近
    """
    video_upload = _ts_parse_datetime(video_att.get("created", ""))
    video_name = video_att.get("filename", "") or ""
    video_fn_parsed = _diag_parse_entry_time(video_name)
    video_fn_time = video_fn_parsed[1] if video_fn_parsed else None
    scored = []
    for gm in gm_info_list:
        upload_delta = float("inf")
        fn_delta = float("inf")
        # 上传时间对比
        if video_upload and gm["upload_time"]:
            upload_delta = abs((video_upload - gm["upload_time"]).total_seconds())
        # 文件名时间对比
        if video_fn_time and gm["filename_time"]:
            fn_delta = abs((video_fn_time - gm["filename_time"]).total_seconds())

        if video_fn_time:
            # 视频有文件名时间：优先按文件名时间差异排序，其次按上传时间
            scored.append((fn_delta, upload_delta, gm))
        else:
            # 视频无文件名时间：按上传时间排序
            scored.append((upload_delta, fn_delta, gm))

    scored.sort(key=lambda x: x[0:2])
    return [gm for _, _, gm in scored]


def _diag_extract_time_from_video_simple(issue: dict) -> str:
    """视频帧 OCR 提取触发时间，多视频按优先级逐个尝试，命中即停。

    支持本地缓存：每个视频提取结果保存到 data/video_time_cache.json，
    避免重复下载和 OCR。缓存命中时直接使用已提取时间进行匹配。
    """
    import tempfile
    import shutil
    import httpx as _httpx
    from datetime import datetime as _dt, timedelta
    fields = issue.get("fields") or {}
    attachments = fields.get("attachment") or []
    videos = [a for a in attachments if (a.get("filename", "") or "").lower().endswith(_VIDEO_SUFFIXES)]
    if not videos:
        _timestudy_update_ctx(issue.get("key", ""), error_type="no_video", error_detail="Jira无视频附件")
        _timestudy_trace(issue.get("key", ""), "video:0")
        return ""
    # 获取 bugid 用于缓存键
    bugid = issue.get("key") or (issue.get("fields") or {}).get("summary", "")[:20]
    # 初始化自学习上下文
    _timestudy_init_ctx(bugid)
    _timestudy_update_ctx(bugid, video_count=len(videos))
    _timestudy_trace(bugid, f"video:{len(videos)}")
    # 加载视频缓存
    cache = _load_video_time_cache()
    cache_updated = False
    from src.clients.jira_client import _parse_datetime_string
    # 解析 gmlogger 文件名时间
    gm_times = _diag_gmlogger_times(attachments)
    gm_dates = [(dt.year, dt.month, dt.day) for _, dt in gm_times]
    ref_pool = [dt for _, dt in gm_times]
    _timestudy_update_ctx(bugid, gm_count=len(gm_times),
                          ref_times="|".join(str(dt) for _, dt in gm_times[:3]))
    _timestudy_trace(bugid, f"gm:{len(gm_times)}")
    # 构建 gmlogger 详细信息（用于智能匹配视频）
    gm_info_list = _build_gmlogger_info(attachments)
    gm_ref_dt = None
    for att in attachments:
        fname = att.get("filename", "") or ""
        if fname and "gmlogger" in fname.lower():
            gm_ref_dt = _ts_parse_datetime(att.get("created", ""))
            break
    # 按优先级排序视频
    ranked_videos = _rank_videos(videos, attachments)
    single_video = len(ranked_videos) == 1
    # 认证头
    cfg = load_config().get("jira_api", {})
    headers = {}
    token = cfg.get("token", "")
    if token:
        auth_type = cfg.get("auth_type", "bearer").lower()
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {token}"
    best_partial = ""
    # 12h 制兜底候选（延迟决策）
    best_12h_cand = None  # (time_str, ext_dt)
    best_12h_diff = float("inf")
    for vi, video_att in enumerate(ranked_videos):
        video_url = video_att.get("content", "")
        video_name = video_att.get("filename", "")
        if not video_url:
            continue
        video_label = f"[{vi+1}/{len(ranked_videos)}] {video_name}"
        # 为当前视频找到最接近的 gmlogger（按接近度排序 ref_pool）
        closest_gm = _find_closest_gmlogger(video_att, gm_info_list)
        # 按接近度构建 ref_pool：最近的排前面
        if closest_gm:
            close_refs = []
            for gm in closest_gm:
                if gm["filename_time"]:
                    close_refs.append(gm["filename_time"])
                if gm["upload_time"] and gm["upload_time"] not in close_refs:
                    close_refs.append(gm["upload_time"])
            # 最近的在前 + 其余补充
            video_ref_pool = close_refs + [dt for dt in ref_pool if dt not in close_refs]
            closest_name = closest_gm[0]["filename"]
            logger.info("视频 %s 最近 gmlogger: %s", video_label, closest_name)
        else:
            video_ref_pool = ref_pool
        cache_key = _get_video_cache_key(bugid, video_name)
        # 检查缓存：缓存命中则跳过下载+OCR
        cached_entry = cache.get(cache_key)
        if cached_entry:
            cached_time = cached_entry.get("time", "")
            logger.info("视频兜底提取：缓存命中 %s -> %s", video_label, cached_time or "(无时间)")
            if cached_time:
                parsed = _parse_datetime_string(cached_time)
                if parsed:
                    ts, ext_dt = parsed
                    if any(abs((dt - ext_dt).total_seconds()) <= 300 for dt in video_ref_pool):
                        logger.info("视频兜底命中(%s, 缓存+包内重合): %s", video_label, ts)
                        _timestudy_update_ctx(bugid, source="video_ocr")
                        _timestudy_trace(bugid, "cache:hit")
                        return ts
                    if not best_partial:
                        best_partial = ts
                continue  # 缓存无时间，也跳过处理
        # 需要 OCR：先确保 reader 可用
        reader = _get_ocr_reader()
        if reader is None:
            logger.warning("视频兜底提取：OCR 不可用，跳过")
            return ""
        # 下载视频（流式下载，避免一次性加载到内存）
        video_path = None
        tmp_dir = None
        try:
            logger.info("视频兜底提取：开始下载视频 %s%s", video_label,
                        "（单视频）" if single_video else "")
            tmp_dir = tempfile.mkdtemp()
            video_path = os.path.join(tmp_dir, "video.bin")
            with _httpx.stream("GET", video_url, headers=headers, timeout=120, verify=False, follow_redirects=True) as resp:
                resp.raise_for_status()
                with open(video_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
            logger.info("视频兜底提取：下载完成 %s", video_label)
            _timestudy_trace(bugid, "dl:ok")
        except Exception as e:
            logger.warning("视频兜底提取：下载失败 %s: %s", video_name, e)
            _timestudy_update_ctx(bugid, error_type="video_download_failed",
                                  error_detail=f"{video_name}: {e}")
            _timestudy_trace(bugid, "dl:fail")
            continue
        if not video_path or not os.path.exists(video_path):
            logger.warning("视频兜底提取：视频文件不存在 %s", video_label)
            continue
        try:
            # 步骤1：提取封面帧
            cover_frames = _extract_video_frames_gpu(video_path, positions=[0], use_gpu=True) or []
            if not cover_frames:
                logger.warning("视频兜底提取：无法提取封面帧 %s，尝试下一个", video_label)
                _timestudy_trace(bugid, "frame:fail")
                continue
            
            # 步骤2：OCR封面帧，如未识别到时间再提取第1/3/6秒
            first_full = ""
            first_partial = ""
            for _phase in [0, 1]:
                if _phase == 0:
                    frames = cover_frames
                    logger.info("视频兜底提取：截取 1 帧（封面）")
                else:
                    if first_full or first_partial:
                        break
                    other_frames = _extract_video_frames_gpu(video_path, positions=[1, 3, 6], use_gpu=True) or []
                    if not other_frames:
                        break
                    frames = other_frames
                    logger.info("视频兜底提取：封面未识别到时间，继续截取第1/3/6秒")
                
                for sec, frame in frames:
                    try:
                        results = reader.readtext(frame)
                    except Exception as e:
                        logger.warning("视频兜底提取：OCR 第%d秒失败: %s", sec, e)
                        continue
                    all_text = " ".join(r[1] for r in results)
                    if all_text.strip():
                        _timestudy_trace(bugid, "ocr:text")
                    else:
                        _timestudy_trace(bugid, "ocr:empty")
                    _timestudy_update_ctx(bugid, ocr_text=all_text[:200])
                    all_text = _fix_ocr_missing_colon(all_text)
                    all_text = _fix_ocr_char_confusion(all_text)
                    all_text = _preprocess_ocr_datetime(all_text)
                    # 完整日期+时间
                    m = _OCR_TIME_FULL_RE.search(all_text)
                    if m:
                        parsed = _parse_datetime_string(_normalize_ocr_time(m.group(1)))
                        if parsed:
                            ts, ext_dt = parsed
                            if any(abs((dt - ext_dt).total_seconds()) <= 300 for dt in video_ref_pool):
                                logger.info("视频兜底命中(%s, 包内时间戳重合): %s (第%d秒)",
                                            video_label, ts, sec + 1)
                                # 缓存命中结果
                                cache[cache_key] = {"time": ts, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                _save_video_time_cache()
                                _diff = min(abs((dt - ext_dt).total_seconds()) for dt in video_ref_pool) if video_ref_pool else 0
                                _timestudy_update_ctx(bugid, source="video_ocr", match_diff=str(int(_diff)))
                                _timestudy_trace(bugid, "full:hit")
                                return ts
                            # 完整日期时间未通过验证，尝试数字混淆纠正
                            _cr = (closest_gm[0]["filename_time"] if closest_gm and closest_gm[0]["filename_time"] else gm_ref_dt)
                            if _cr and len(ts) > 11:
                                corrected_t = _correct_ocr_by_reference(ts[11:], _cr)
                                if corrected_t != ts[11:]:
                                    ts2 = ts[:11] + corrected_t
                                    parsed2 = _parse_datetime_string(ts2)
                                    if parsed2 and any(abs((dt - parsed2[1]).total_seconds()) <= 300 for dt in video_ref_pool):
                                        logger.info("视频兜底命中(%s, 纠正+包内重合): %s -> %s", video_label, ts, ts2)
                                        cache[cache_key] = {"time": ts2, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                        _save_video_time_cache()
                                        return ts2
                                    ts = ts2  # 用纠正后的时间
                            # 12h 制候选（完整日期+时间）
                            if ext_dt.hour < 12:
                                dt_alt = ext_dt + timedelta(hours=12)
                            else:
                                dt_alt = ext_dt - timedelta(hours=12)
                            ts_alt = dt_alt.strftime("%Y-%m-%d %H:%M:%S")
                            orig_match = any(abs((dt - ext_dt).total_seconds()) <= 300 for dt in video_ref_pool)
                            alt_match = any(abs((dt - dt_alt).total_seconds()) <= 300 for dt in video_ref_pool)
                            if alt_match and not orig_match:
                                logger.info("视频兜底命中(%s, 12h转换): %s -> %s (第%d秒)", video_label, ts, ts_alt, sec + 1)
                                cache[cache_key] = {"time": ts_alt, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                _save_video_time_cache()
                                _timestudy_update_ctx(bugid, source="video_ocr", h12="yes")
                                _timestudy_trace(bugid, "12h:hit")
                                return ts_alt
                            if not orig_match and not alt_match:
                                d_orig = min(abs((dt - ext_dt).total_seconds()) for dt in video_ref_pool) if video_ref_pool else float("inf")
                                d_alt = min(abs((dt - dt_alt).total_seconds()) for dt in video_ref_pool) if video_ref_pool else float("inf")
                                if d_alt < d_orig and d_alt < best_12h_diff:
                                    best_12h_diff = d_alt
                                    best_12h_cand = (ts_alt, dt_alt)
                                elif d_orig < best_12h_diff:
                                    best_12h_diff = d_orig
                                    best_12h_cand = (ts, ext_dt)
                            if not first_full:
                                first_full = ts
                    # 仅时间+gmlogger日期补充，延迟 12h 决策（优先使用最近 gmlogger 的日期）
                    m = _OCR_TIME_ONLY_RE.search(all_text)
                    closest_date = gm_dates[0] if gm_dates else None
                    if closest_gm and closest_gm[0]["filename_time"]:
                        closest_date = (closest_gm[0]["filename_time"].year,
                                        closest_gm[0]["filename_time"].month,
                                        closest_gm[0]["filename_time"].day)
                    if m and closest_date:
                        time_str = _normalize_ocr_time(m.group(1))
                        # 参照 gmlogger 时间纠正数字混淆
                        _corr_ref = (closest_gm[0]["filename_time"] if closest_gm and closest_gm[0]["filename_time"] else gm_ref_dt)
                        if _corr_ref:
                            time_str = _correct_ocr_by_reference(time_str, _corr_ref)
                        # 用 gmlogger 日期补充，延迟 12h 决策
                        y, mo, d = closest_date
                        full_orig = f"{y:04d}-{mo:02d}-{d:02d} {time_str}"
                        parsed_orig = _parse_datetime_string(full_orig)
                        if parsed_orig:
                            ts, ext_dt = parsed_orig
                            if ext_dt.hour < 12:
                                dt_alt = ext_dt + timedelta(hours=12)
                            else:
                                dt_alt = ext_dt - timedelta(hours=12)
                            ts_alt = dt_alt.strftime("%Y-%m-%d %H:%M:%S")
                            orig_match = any(abs((dt - ext_dt).total_seconds()) <= 300 for dt in video_ref_pool)
                            alt_match = any(abs((dt - dt_alt).total_seconds()) <= 300 for dt in video_ref_pool)
                            gm_orig = gm_ref_dt and abs((gm_ref_dt - ext_dt).total_seconds()) <= 300
                            gm_alt = gm_ref_dt and abs((gm_ref_dt - dt_alt).total_seconds()) <= 300
                            if (orig_match or gm_orig) and not (alt_match or gm_alt):
                                logger.info("视频兜底命中(%s, 日期补充+包内重合): %s (第%d秒)", video_label, ts, sec + 1)
                                cache[cache_key] = {"time": ts, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                _save_video_time_cache()
                                return ts
                            if (alt_match or gm_alt) and not (orig_match or gm_orig):
                                logger.info("视频兜底命中(%s, 日期补充+12h): %s (第%d秒)", video_label, ts_alt, sec + 1)
                                cache[cache_key] = {"time": ts_alt, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                _save_video_time_cache()
                                return ts_alt
                            # 均未严格命中，记录 12h 候选（仅时间差）
                            if not (orig_match or gm_orig) and not (alt_match or gm_alt) and video_ref_pool:
                                d_orig = min(abs((dt.hour * 3600 + dt.minute * 60 + dt.second) - (ext_dt.hour * 3600 + ext_dt.minute * 60 + ext_dt.second)) for dt in video_ref_pool)
                                d_alt = min(abs((dt.hour * 3600 + dt.minute * 60 + dt.second) - (dt_alt.hour * 3600 + dt_alt.minute * 60 + dt_alt.second)) for dt in video_ref_pool)
                                if d_alt < d_orig and d_alt < best_12h_diff:
                                    best_12h_diff = d_alt
                                    best_12h_cand = (ts_alt, dt_alt)
                                elif d_orig < best_12h_diff:
                                    best_12h_diff = d_orig
                                    best_12h_cand = (ts, ext_dt)
                        if not first_partial:
                            first_partial = ts
            # OCR 完全失败时，尝试从视频文件名提取时间（回退方案）
            if not first_full and not first_partial:
                _timestudy_trace(bugid, "fn:try")
                fn_time = _parse_video_filename_time(video_name)
                if fn_time:
                    closest_date = gm_dates[0] if gm_dates else None
                    if closest_gm and closest_gm[0]["filename_time"]:
                        closest_date = (closest_gm[0]["filename_time"].year,
                                        closest_gm[0]["filename_time"].month,
                                        closest_gm[0]["filename_time"].day)
                    if closest_date:
                        y, mo, d = closest_date
                        full_orig = f"{y:04d}-{mo:02d}-{d:02d} {fn_time}"
                        parsed_orig = _parse_datetime_string(full_orig)
                        if parsed_orig:
                            ts, ext_dt = parsed_orig
                            if ext_dt.hour < 12:
                                dt_alt = ext_dt + timedelta(hours=12)
                            else:
                                dt_alt = ext_dt - timedelta(hours=12)
                            ts_alt = dt_alt.strftime("%Y-%m-%d %H:%M:%S")
                            orig_match = any(abs((dt - ext_dt).total_seconds()) <= 300 for dt in video_ref_pool)
                            alt_match = any(abs((dt - dt_alt).total_seconds()) <= 300 for dt in video_ref_pool)
                            if alt_match and not orig_match:
                                logger.info("视频兜底提取(%s, 文件名回退+12h): %s", video_label, ts_alt)
                                first_partial = ts_alt
                            elif not orig_match and not alt_match and video_ref_pool:
                                d_orig = min(abs((dt.hour * 3600 + dt.minute * 60 + dt.second) - (ext_dt.hour * 3600 + ext_dt.minute * 60 + ext_dt.second)) for dt in video_ref_pool)
                                d_alt = min(abs((dt.hour * 3600 + dt.minute * 60 + dt.second) - (dt_alt.hour * 3600 + dt_alt.minute * 60 + dt_alt.second)) for dt in video_ref_pool)
                                if d_alt < d_orig and d_alt < best_12h_diff:
                                    best_12h_diff = d_alt
                                    best_12h_cand = (ts_alt, dt_alt)
                                elif d_orig < best_12h_diff:
                                    best_12h_diff = d_orig
                                    best_12h_cand = (ts, ext_dt)
                                logger.info("视频兜底提取(%s, 文件名回退): %s", video_label, ts)
                                first_partial = ts
                            else:
                                logger.info("视频兜底提取(%s, 文件名回退): %s", video_label, ts)
                                first_partial = ts
            # 缓存当前视频的提取结果（仅成功时缓存）
            extracted_time = first_full or first_partial or ""
            if extracted_time:
                cache[cache_key] = {"time": extracted_time, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                cache_updated = True
            # 完整日期时间 → 直接返回
            if first_full:
                logger.info("视频兜底提取(完整日期时间, %s): %s", video_label, first_full)
                _save_video_time_cache()
                return first_full
            # 部分时间但未命中 → 保存兜底，尝试下一个
            if first_partial:
                if not best_partial:
                    best_partial = first_partial
                logger.info("视频兜底提取(%s)：提取到 %s 但未命中 gmlogger，尝试下一个视频",
                            video_label, first_partial)
            else:
                logger.info("视频兜底提取(%s)：未识别到时间，尝试下一个视频", video_label)
        except Exception as e:
            logger.warning("视频兜底提取：处理视频 %s 时异常: %s", video_label, e)
        finally:
            # 统一清理临时目录：无论成功、失败、命中返回还是 continue，都删除下载的视频文件
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
    # 保存缓存（所有视频处理完后统一保存）
    if cache_updated:
        _save_video_time_cache()
    # 12h 制兜底：所有视频原始时间均未命中，尝试 12h 转换取差值最小的
    if best_12h_cand:
        cand_time, cand_dt = best_12h_cand
        logger.info("视频兜底提取(12h兜底): 使用 12h 候选 %s（差值 %.0f 秒）", cand_time, best_12h_diff)
        _timestudy_update_ctx(bugid, source="video_ocr", h12="yes", match_diff=str(int(best_12h_diff)))
        _timestudy_trace(bugid, "12h:fallback")
        return cand_time
    # 单视频兜底
    if single_video and best_partial:
        logger.info("视频兜底提取(单视频兜底): %s", best_partial)
        _timestudy_update_ctx(bugid, source="video_ocr", error_type="time_no_match_gmlogger",
                              error_detail=f"单视频兜底: {best_partial}")
        _timestudy_trace(bugid, "partial:single")
        return best_partial
    if best_partial:
        logger.info("视频兜底提取(多视频均未命中，返回第一个部分结果): %s", best_partial)
        _timestudy_update_ctx(bugid, source="video_ocr", error_type="time_no_match_gmlogger",
                              error_detail=f"多视频均未命中兜底: {best_partial}")
        _timestudy_trace(bugid, "partial:multi")
        return best_partial
    _timestudy_update_ctx(bugid, error_type="ocr_no_time_pattern", error_detail="所有视频OCR均未识别到时间")
    _timestudy_trace(bugid, "ocr:no_pattern")
    return ""


def _diag_extract_time_from_video(issue: dict, headers: dict, timeout: int,
                                   gmlogger_dates: list, ref_pool: list,
                                   gm_ref_dt=None, gm_times: list = None) -> tuple:
    """从视频附件前6秒截帧，OCR 识别时间，多视频按优先级逐个尝试，命中即停。
    返回 (extracted_time, detail) 或 ("", "")。支持本地缓存避免重复下载+OCR。

    当 ref_pool 为空（未解压 gmlogger）时，使用 gm_times 作为验证池：
    - ±15分钟（900秒）内命中 → 直接返回
    - 15分钟~1小时（3600秒）内 → 记录为候选，所有视频处理完后取最接近的
    - 超过1小时 → 返回空，触发解压
    """
    import tempfile
    import shutil
    import httpx as _httpx
    from datetime import datetime as _dt, timedelta
    fields = issue.get("fields") or {}
    attachments = fields.get("attachment") or []
    videos = [a for a in attachments if (a.get("filename", "") or "").lower().endswith(_VIDEO_SUFFIXES)]
    if not videos:
        return "", ""
    # 确定验证池和容忍度
    if ref_pool:
        # 已解压：使用包内时间戳，±5分钟严格匹配
        validation_pool = ref_pool
        strict_tol = 300
        fallback_tol = None  # 无 fallback
    else:
        # 未解压：使用文件名时间，±15分钟严格，±1小时 fallback
        validation_pool = [dt for _, dt in (gm_times or [])]
        strict_tol = 900
        fallback_tol = 3600
    # 获取 bugid 用于缓存键
    bugid = issue.get("key") or ""
    cache = _load_video_time_cache()
    cache_updated = False
    # 按优先级排序，逐个尝试
    ranked_videos = _rank_videos(videos, attachments)
    single_video = len(ranked_videos) == 1
    # 初始化 OCR reader（只初始化一次）
    reader = _get_ocr_reader()
    if reader is None:
        logger.warning("视频帧提取：OCR 不可用，跳过")
        return "", ""
    from src.clients.jira_client import _parse_datetime_string
    best_full = ""      # 全局兜底：第一个完整日期时间
    best_full_detail = ""
    best_partial = ""    # 全局兜底：第一个部分时间
    best_partial_detail = ""
    # fallback 候选（用于未解压场景）
    fallback_candidate = None
    fallback_diff = float("inf")
    # 12h 制兜底候选（延迟决策：所有视频处理完后统一判定）
    best_12h_cand = None   # (extracted_time, ext_dt, is_time_only)
    best_12h_diff = float("inf")
    for vi, video_att in enumerate(ranked_videos):
        video_url = video_att.get("content", "")
        video_name = video_att.get("filename", "")
        if not video_url:
            continue
        video_label = f"[{vi+1}/{len(ranked_videos)}] {video_name}"
        cache_key = _get_video_cache_key(bugid, video_name)
        # 检查缓存：命中则跳过下载+OCR
        cached_entry = cache.get(cache_key)
        if cached_entry:
            cached_time = cached_entry.get("time", "")
            logger.info("视频帧提取：缓存命中 %s -> %s", video_label, cached_time or "(无时间)")
            if cached_time:
                parsed = _parse_datetime_string(cached_time)
                if parsed:
                    ts, ext_dt = parsed
                    if validation_pool and any(abs((dt - ext_dt).total_seconds()) <= strict_tol for dt in validation_pool):
                        detail = f"从视频{video_label}缓存命中 {ts}，与 gmlogger 时间前后{strict_tol//60}分钟命中"
                        return ts, detail
                    if not best_full:
                        best_full = ts
                        best_full_detail = f"从视频{video_label}缓存命中完整日期时间 {ts}"
                    if not best_partial:
                        best_partial = ts
                        best_partial_detail = f"从视频{video_label}缓存命中 {ts}"
            continue  # 缓存无时间，也跳过处理
        # 下载视频（流式下载，避免一次性加载到内存）
        video_path = None
        tmp_dir = None
        try:
            # 下载子块：单独捕获下载异常，失败则跳过当前视频（临时目录由外层 finally 统一清理）
            try:
                logger.info("视频帧提取：开始下载视频 %s%s", video_label,
                            "（单视频）" if single_video else "")
                tmp_dir = tempfile.mkdtemp()
                video_path = os.path.join(tmp_dir, "video.bin")
                with _httpx.stream("GET", video_url, headers=headers, timeout=timeout, verify=False, follow_redirects=True) as resp:
                    resp.raise_for_status()
                    with open(video_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                            f.write(chunk)
                logger.info("视频帧提取：下载完成 %s", video_label)
            except Exception as e:
                logger.warning("视频帧提取：下载失败 %s: %s", video_name, e)
                continue  # 下载失败，尝试下一个视频
            if not video_path or not os.path.exists(video_path):
                logger.warning("视频帧提取：视频文件不存在 %s", video_label)
                continue
            # 截帧 + OCR：先封面，再第1/3/6秒
            cover_frames = _extract_video_frames_gpu(video_path, positions=[0], use_gpu=True) or []
            if not cover_frames:
                logger.warning("视频帧提取：无法提取封面帧 %s，尝试下一个", video_label)
                continue
            first_full = ""
            first_partial = ""
            first_detail = ""
            for _phase in [0, 1]:
                if _phase == 0:
                    frames = cover_frames
                    logger.info("视频帧提取：截取 %d 帧（封面）", len(frames))
                else:
                    if first_full or first_partial:
                        break
                    other_frames = _extract_video_frames_gpu(video_path, positions=[1, 3, 6], use_gpu=True) or []
                    if not other_frames:
                        break
                    frames = other_frames
                    logger.info("视频帧提取：封面未识别到时间，继续截取第1/3/6秒")
                
                for sec, frame in frames:
                    try:
                        results = reader.readtext(frame)
                    except Exception as e:
                        logger.warning("视频帧提取：OCR 第%d秒失败: %s", sec, e)
                        continue
                    all_text = " ".join(r[1] for r in results)
                    logger.info("视频帧提取(%s)：第%d秒 OCR: %s", video_label, sec + 1,
                                all_text[:200] if all_text else "(空)")
                    all_text = _fix_ocr_missing_colon(all_text)
                    all_text = _fix_ocr_char_confusion(all_text)
                    all_text = _preprocess_ocr_datetime(all_text)
                    # 完整日期+时间
                    m = _OCR_TIME_FULL_RE.search(all_text)
                    if m:
                        normalized = _normalize_ocr_time(m.group(1))
                        parsed = _parse_datetime_string(normalized)
                        if parsed:
                            extracted_time, ext_dt = parsed
                            # 严格匹配
                            if validation_pool and any(abs((dt - ext_dt).total_seconds()) <= strict_tol for dt in validation_pool):
                                detail = f"从视频{video_label}第{sec+1}秒 OCR 识别到 {extracted_time}，与 gmlogger 时间前后{strict_tol//60}分钟命中"
                                logger.info("视频帧提取命中: %s", extracted_time)
                                cache[cache_key] = {"time": extracted_time, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                _save_video_time_cache()
                                return extracted_time, detail
                            # fallback 候选记录（仅未解压场景）
                            if fallback_tol and validation_pool:
                                diffs = [abs((dt - ext_dt).total_seconds()) for dt in validation_pool]
                                min_diff = min(diffs)
                                if min_diff < fallback_tol and min_diff < fallback_diff:
                                    fallback_diff = min_diff
                                    fallback_candidate = extracted_time
                                    logger.info("视频帧提取(%s)：%s 作为 fallback 候选（差值 %.0f 秒）", video_label, extracted_time, min_diff)
                            # 完整日期时间未通过验证，尝试数字混淆纠正
                            if gm_ref_dt and len(extracted_time) > 11:
                                corrected_t = _correct_ocr_by_reference(extracted_time[11:], gm_ref_dt)
                                if corrected_t != extracted_time[11:]:
                                    corrected_full = extracted_time[:11] + corrected_t
                                    parsed2 = _parse_datetime_string(corrected_full)
                                    if parsed2 and validation_pool and any(abs((dt - parsed2[1]).total_seconds()) <= strict_tol for dt in validation_pool):
                                        detail = f"从视频{video_label}第{sec+1}秒 OCR 纠正后识别到 {corrected_full}，与 gmlogger 时间前后{strict_tol//60}分钟命中"
                                        logger.info("视频帧提取命中(纠正): %s -> %s", extracted_time, corrected_full)
                                        cache[cache_key] = {"time": corrected_full, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                        _save_video_time_cache()
                                        return corrected_full, detail
                                    extracted_time = corrected_full
                            # 12h 制候选（完整日期+时间，差值计算完整日期时间差）
                            if ext_dt.hour < 12:
                                dt_alt = ext_dt + timedelta(hours=12)
                            else:
                                dt_alt = ext_dt - timedelta(hours=12)
                            ts_alt = dt_alt.strftime("%Y-%m-%d %H:%M:%S")
                            orig_match = validation_pool and any(abs((dt - ext_dt).total_seconds()) <= strict_tol for dt in validation_pool)
                            alt_match = validation_pool and any(abs((dt - dt_alt).total_seconds()) <= strict_tol for dt in validation_pool)
                            if alt_match and not orig_match:
                                detail = f"从视频{video_label}第{sec+1}秒 OCR 识别到 {extracted_time}，12h制转换为 {ts_alt}，与 gmlogger 时间前后{strict_tol//60}分钟命中"
                                logger.info("视频帧提取命中(12h转换): %s -> %s", extracted_time, ts_alt)
                                cache[cache_key] = {"time": ts_alt, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                _save_video_time_cache()
                                return ts_alt, detail
                            if not orig_match and not alt_match and validation_pool:
                                d_orig = min(abs((dt - ext_dt).total_seconds()) for dt in validation_pool)
                                d_alt = min(abs((dt - dt_alt).total_seconds()) for dt in validation_pool)
                                if d_alt < d_orig and d_alt < best_12h_diff:
                                    best_12h_diff = d_alt
                                    best_12h_cand = (ts_alt, dt_alt, False)
                                    logger.info("视频帧提取(%s)：%s 作为 12h 候选（差值 %.0f 秒）", video_label, ts_alt, d_alt)
                                elif d_orig < best_12h_diff:
                                    best_12h_diff = d_orig
                                    best_12h_cand = (extracted_time, ext_dt, False)
                                    logger.info("视频帧提取(%s)：%s 作为 12h 原始候选（差值 %.0f 秒）", video_label, extracted_time, d_orig)
                            if not first_full:
                                first_full = extracted_time
                                first_detail = f"从视频{video_label}第{sec+1}秒 OCR 识别到完整日期时间 {extracted_time}"
                    # 仅时间（无日期），用 gmlogger 文件名日期补充，延迟 12h 决策
                    m = _OCR_TIME_ONLY_RE.search(all_text)
                    if m and gmlogger_dates:
                        time_str = _normalize_ocr_time(m.group(1))
                        # 参照 gmlogger 时间纠正数字混淆
                        if gm_ref_dt:
                            time_str = _correct_ocr_by_reference(time_str, gm_ref_dt)
                        # 用 gmlogger 日期补充，延迟 12h 决策
                        y, mo, d = gmlogger_dates[0]
                        full_orig = f"{y:04d}-{mo:02d}-{d:02d} {time_str}"
                        parsed_orig = _parse_datetime_string(full_orig)
                        if parsed_orig:
                            _, ext_dt = parsed_orig
                            extracted_time = parsed_orig[0]
                            if ext_dt.hour < 12:
                                dt_alt = ext_dt + timedelta(hours=12)
                            else:
                                dt_alt = ext_dt - timedelta(hours=12)
                            ts_alt = dt_alt.strftime("%Y-%m-%d %H:%M:%S")
                            orig_match = validation_pool and any(abs((dt - ext_dt).total_seconds()) <= strict_tol for dt in validation_pool)
                            alt_match = validation_pool and any(abs((dt - dt_alt).total_seconds()) <= strict_tol for dt in validation_pool)
                            if orig_match and not alt_match:
                                detail = (f"从视频{video_label}第{sec+1}秒 OCR 识别到 {time_str}，"
                                          f"用 gmlogger 日期补充为 {extracted_time}，与 gmlogger 时间前后{strict_tol//60}分钟命中")
                                logger.info("视频帧提取命中(日期补充): %s", extracted_time)
                                cache[cache_key] = {"time": extracted_time, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                _save_video_time_cache()
                                return extracted_time, detail
                            if alt_match and not orig_match:
                                detail = (f"从视频{video_label}第{sec+1}秒 OCR 识别到 {time_str}，"
                                          f"12h制转换为 {ts_alt}，与 gmlogger 时间前后{strict_tol//60}分钟命中")
                                logger.info("视频帧提取命中(日期补充+12h): %s", ts_alt)
                                cache[cache_key] = {"time": ts_alt, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                _save_video_time_cache()
                                return ts_alt, detail
                            # 两个均未严格命中，记录 12h 候选（仅时间差 = HH:MM:SS 差值）
                            if not orig_match and not alt_match and validation_pool:
                                d_orig = min(abs((dt.hour * 3600 + dt.minute * 60 + dt.second) - (ext_dt.hour * 3600 + ext_dt.minute * 60 + ext_dt.second)) for dt in validation_pool)
                                d_alt = min(abs((dt.hour * 3600 + dt.minute * 60 + dt.second) - (dt_alt.hour * 3600 + dt_alt.minute * 60 + dt_alt.second)) for dt in validation_pool)
                                if d_alt < d_orig and d_alt < best_12h_diff:
                                    best_12h_diff = d_alt
                                    best_12h_cand = (ts_alt, dt_alt, True)
                                    logger.info("视频帧提取(%s)：%s 作为 12h 候选（时间差 %.0f 秒）", video_label, ts_alt, d_alt)
                                elif d_orig < best_12h_diff:
                                    best_12h_diff = d_orig
                                    best_12h_cand = (extracted_time, ext_dt, True)
                                    logger.info("视频帧提取(%s)：%s 作为 12h 原始候选（时间差 %.0f 秒）", video_label, extracted_time, d_orig)
                            # fallback 候选记录（仅未解压场景）
                            if fallback_tol and validation_pool:
                                diffs = [abs((dt - ext_dt).total_seconds()) for dt in validation_pool]
                                min_diff = min(diffs)
                                if min_diff < fallback_tol and min_diff < fallback_diff:
                                    fallback_diff = min_diff
                                    fallback_candidate = extracted_time
                                    logger.info("视频帧提取(%s)：%s 作为 fallback 候选（差值 %.0f 秒）", video_label, extracted_time, min_diff)
                        if not first_partial:
                            first_partial = extracted_time
                            first_detail = (f"从视频{video_label}第{sec+1}秒 OCR 识别到 {time_str}，"
                                            f"用 gmlogger 日期补充为 {extracted_time}（未命中验证池）")
            # OCR 完全失败时，尝试从视频文件名提取时间（回退方案）
            if not first_full and not first_partial:
                fn_time = _parse_video_filename_time(video_name)
                if fn_time and gmlogger_dates:
                    y, mo, d = gmlogger_dates[0]
                    full_orig = f"{y:04d}-{mo:02d}-{d:02d} {fn_time}"
                    parsed_orig = _parse_datetime_string(full_orig)
                    if parsed_orig:
                        extracted_time, ext_dt = parsed_orig
                        if ext_dt.hour < 12:
                            dt_alt = ext_dt + timedelta(hours=12)
                        else:
                            dt_alt = ext_dt - timedelta(hours=12)
                        ts_alt = dt_alt.strftime("%Y-%m-%d %H:%M:%S")
                        orig_match = validation_pool and any(abs((dt - ext_dt).total_seconds()) <= strict_tol for dt in validation_pool)
                        alt_match = validation_pool and any(abs((dt - dt_alt).total_seconds()) <= strict_tol for dt in validation_pool)
                        if orig_match and not alt_match:
                            detail = f"从视频{video_label}文件名提取到时间 {fn_time}，用 gmlogger 日期补充为 {extracted_time}，与 gmlogger 时间前后{strict_tol//60}分钟命中"
                            logger.info("视频帧提取(%s, 文件名回退+命中): %s", video_label, extracted_time)
                            cache[cache_key] = {"time": extracted_time, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                            _save_video_time_cache()
                            return extracted_time, detail
                        if alt_match and not orig_match:
                            detail = f"从视频{video_label}文件名提取到时间 {fn_time}，12h制转换为 {ts_alt}，与 gmlogger 时间前后{strict_tol//60}分钟命中"
                            logger.info("视频帧提取(%s, 文件名回退+12h): %s", video_label, ts_alt)
                            cache[cache_key] = {"time": ts_alt, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                            _save_video_time_cache()
                            return ts_alt, detail
                        # 均未严格命中，记录 12h 候选（仅时间差）
                        if not orig_match and not alt_match and validation_pool:
                            d_orig = min(abs((dt.hour * 3600 + dt.minute * 60 + dt.second) - (ext_dt.hour * 3600 + ext_dt.minute * 60 + ext_dt.second)) for dt in validation_pool)
                            d_alt = min(abs((dt.hour * 3600 + dt.minute * 60 + dt.second) - (dt_alt.hour * 3600 + dt_alt.minute * 60 + dt_alt.second)) for dt in validation_pool)
                            if d_alt < d_orig and d_alt < best_12h_diff:
                                best_12h_diff = d_alt
                                best_12h_cand = (ts_alt, dt_alt, True)
                            elif d_orig < best_12h_diff:
                                best_12h_diff = d_orig
                                best_12h_cand = (extracted_time, ext_dt, True)
                        # fallback 候选记录（仅未解压场景）
                        if fallback_tol and validation_pool:
                            diffs = [abs((dt - ext_dt).total_seconds()) for dt in validation_pool]
                            min_diff = min(diffs)
                            if min_diff < fallback_tol and min_diff < fallback_diff:
                                fallback_diff = min_diff
                                fallback_candidate = extracted_time
                                logger.info("视频帧提取(%s)：%s 作为 fallback 候选（差值 %.0f 秒）", video_label, extracted_time, min_diff)
                        first_partial = extracted_time
                        first_detail = f"从视频{video_label}文件名提取到时间 {fn_time}，用 gmlogger 日期补充为 {extracted_time}"
            # 缓存当前视频提取结果（仅成功时缓存）
            extracted_time = first_full or first_partial or ""
            if extracted_time:
                cache[cache_key] = {"time": extracted_time, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                cache_updated = True
            # 当前视频有完整日期时间 → 直接返回，无需验证
            if first_full:
                logger.info("视频帧提取(完整日期时间): %s", first_full)
                _save_video_time_cache()
                return first_full, first_detail
            # 当前视频有部分时间但未命中验证 → 保存为全局兜底，尝试下一个视频
            if first_partial:
                if not best_partial:
                    best_partial = first_partial
                    best_partial_detail = first_detail
                logger.info("视频帧提取(%s)：提取到 %s 但未命中 gmlogger，尝试下一个视频", video_label, first_partial)
            else:
                logger.info("视频帧提取(%s)：未识别到时间，尝试下一个视频", video_label)
        except Exception as e:
            logger.warning("视频帧提取：处理视频 %s 时异常: %s", video_label, e)
        finally:
            # 统一清理临时目录：无论成功、失败、命中返回还是 continue，都删除下载的视频文件
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
    if cache_updated:
        _save_video_time_cache()
    # fallback 机制：所有视频都未严格命中，但存在 fallback 候选（15分钟~1小时）
    if fallback_candidate:
        logger.info("视频帧提取(fallback): 所有视频均未在±15分钟内命中，使用最接近候选 %s（差值 %.0f 秒）", fallback_candidate, fallback_diff)
        return fallback_candidate, f"所有视频均未在±15分钟内命中，使用最接近候选 {fallback_candidate}（差值 {fallback_diff:.0f} 秒）"
    # 12h 制兜底：所有视频原始时间均未严格命中，尝试 12h 转换取差值最小的
    if best_12h_cand:
        cand_time, cand_dt, is_time_only = best_12h_cand
        logger.info("视频帧提取(12h兜底): 所有视频原始时间均未命中，使用 12h 候选 %s（差值 %.0f 秒，%s）", cand_time, best_12h_diff, "仅时间差" if is_time_only else "完整差值")
        cache_key_12h = _get_video_cache_key(bugid, ranked_videos[0].get("filename", "") if ranked_videos else "")
        if cache_key_12h:
            cache[cache_key_12h] = {"time": cand_time, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
            _save_video_time_cache()
        return cand_time, f"所有视频原始时间均未命中，12h制转换为 {cand_time}（差值 {best_12h_diff:.0f} 秒）"
    if best_full:
        return best_full, best_full_detail
    if single_video and best_partial:
        logger.info("视频帧提取(单视频兜底): %s", best_partial)
        return best_partial, best_partial_detail
    if best_partial:
        logger.info("视频帧提取(多视频均未命中，返回第一个部分结果): %s", best_partial)
        return best_partial, best_partial_detail
    return "", ""


def _diag_extract_time_from_images(issue: dict, headers: dict, timeout: int, bugid: str = "") -> tuple:
    """从图片附件 OCR 提取触发时间，返回 (time_str, detail) 或 ("", "")

    优先级：
    1. 标记检测：某时间戳文字颜色与周围文字显著不同（红/绿色调）或位置独立（大字号/独立区域）
    2. 频率兆底：统计所有图片提取的时间，取出现次数最多的
    图片数量上限 5 张，按创建时间倒序取最新。
    """
    import tempfile
    import httpx as _httpx
    from datetime import datetime as _dt
    fields = issue.get("fields") or {}
    attachments = fields.get("attachment") or []
    # 筛选图片附件（排除视频）
    images = [a for a in attachments
              if (a.get("filename", "") or "").lower().endswith(_IMAGE_SUFFIXES)
              and not (a.get("filename", "") or "").lower().endswith(_VIDEO_SUFFIXES)]
    if not images:
        return "", ""
    # 按创建时间倒序取最新 5 张
    images = sorted(images, key=lambda a: a.get("created", "") or "", reverse=True)[:5]
    logger.info("%s图片 OCR: 开始处理 %d 张图片", f"{bugid} " if bugid else "", len(images))
    # 获取 OCR reader
    reader = _get_ocr_reader()
    if reader is None:
        logger.warning("%s图片 OCR: easyocr 不可用，跳过", f"{bugid} " if bugid else "")
        return "", ""
    # 收集所有提取的时间
    all_times = []       # [(time_str, datetime, is_marked, image_name)]
    marked_time = None   # 标记检测命中的时间
    with tempfile.TemporaryDirectory() as tmp:
        for att in images:
            fname = att.get("filename", "") or ""
            img_path = os.path.join(tmp, fname)
            logger.info("%s图片 OCR: 处理 %s", f"{bugid} " if bugid else "", fname)
            try:
                # 下载图片
                with _httpx.stream("GET", att.get("content", ""), headers=headers,
                                   timeout=timeout, verify=False, follow_redirects=True) as resp:
                    resp.raise_for_status()
                    with open(img_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                            f.write(chunk)
                # OCR 识别（返回 bbox + 文字 + 置信度）
                results = reader.readtext(img_path)
                if not results:
                    continue
                # 收集完整文本用于时间正则匹配
                full_text = " ".join(r[1] for r in results)
                preprocessed = _normalize_ocr_time(full_text)
                preprocessed = _fix_ocr_missing_colon(preprocessed)
                # 提取完整时间戳
                times_found = []
                for m in _OCR_TIME_FULL_RE.finditer(preprocessed):
                    ts = _normalize_ocr_time(m.group(0))
                    parsed = _ts_parse_datetime(ts)
                    if parsed:
                        times_found.append((ts, parsed))
                # 提取仅时间（无日期）尝试补 gmlogger 日期
                for m in _OCR_TIME_ONLY_RE.finditer(preprocessed):
                    ts = m.group(0)
                    # 仅时间无日期，记录为 HH:MM:SS 待后续补日期
                    times_found.append((ts, None))
                if not times_found:
                    continue
                logger.info("%s图片 OCR %s 提取到 %d 个时间", f"{bugid} " if bugid else "", fname, len(times_found))
                # 标记检测：分析每个时间戳的 bbox 位置和颜色特征
                for ts, parsed_dt in times_found:
                    is_marked = False
                    # 在 OCR 结果中查找该时间戳对应的 bbox
                    for bbox, text, conf in results:
                        if ts in text or ts.replace(":", ".") in text or ts.replace(":", ",") in text:
                            # 检测标记特征：
                            # 1. bbox 面积较大（字号大）
                            # 2. 周围像素颜色异常（红/绿）
                            try:
                                is_marked = _check_time_marked(img_path, bbox, results)
                            except Exception:
                                pass
                            break
                    all_times.append((ts, parsed_dt, is_marked, fname))
                    if is_marked and not marked_time:
                        marked_time = (ts, parsed_dt)
                        logger.info("%s图片 OCR 标记检测命中: %s (%s)", f"{bugid} " if bugid else "", ts, fname)
            except Exception as e:
                logger.warning("%s图片 OCR 处理 %s 异常: %s", f"{bugid} " if bugid else "", fname, e)
                continue
    if not all_times:
        return "", ""
    # 优先级选择
    if marked_time:
        ts, dt = marked_time
        # 如果是仅时间（无日期），尝试用 gmlogger 文件名日期补充
        if dt is None:
            gm_times = _diag_gmlogger_times(attachments)
            if gm_times:
                ref_date = gm_times[0][1]
                dt = ref_date.replace(hour=int(ts[:2]), minute=int(ts[3:5]),
                                      second=int(ts[6:8]) if len(ts) >= 8 else 0)
                ts = dt.strftime("%Y-%m-%d %H:%M:%S")
        if dt:
            return ts, f"图片 OCR 标记时间（{dt.strftime('%Y-%m-%d %H:%M:%S')}）"
    # 频率兆底：统计出现次数最多的时间
    from collections import Counter
    # 只统计有完整日期的时间
    valid_times = [(ts, dt) for ts, dt, _, _ in all_times if dt is not None]
    if valid_times:
        # 按时间字符串规范化后统计频率
        time_counter = Counter(ts for ts, _ in valid_times)
        most_common_ts, count = time_counter.most_common(1)[0]
        # 获取对应的 datetime
        most_common_dt = next(dt for ts, dt in valid_times if ts == most_common_ts)
        logger.info("%s图片 OCR 频率兆底: %s (出现 %d 次)", f"{bugid} " if bugid else "", most_common_ts, count)
        return most_common_ts, f"图片 OCR 频率最高时间（{most_common_dt.strftime('%Y-%m-%d %H:%M:%S')}，出现{count}次）"
    # 无完整时间，尝试用仅时间 + gmlogger 日期
    partial_times = [(ts, dt) for ts, dt, _, _ in all_times if dt is None]
    if partial_times:
        gm_times = _diag_gmlogger_times(attachments)
        if gm_times:
            ref_date = gm_times[0][1]
            ts = partial_times[0][0]
            try:
                hh, mm = int(ts[:2]), int(ts[3:5])
                ss = int(ts[6:8]) if len(ts) >= 8 else 0
                dt = ref_date.replace(hour=hh, minute=mm, second=ss)
                return dt.strftime("%Y-%m-%d %H:%M:%S"), f"图片 OCR 时间（无日期，补 gmlogger 日期 {dt.strftime('%Y-%m-%d %H:%M:%S')}）"
            except Exception:
                pass
    return "", ""


def _check_time_marked(img_path: str, bbox: list, all_results: list) -> bool:
    """检测时间戳是否被标记（红/绿色圈出或位置独立突出）

    启发式规则：
    1. 颜色检测：bbox 内像素是否有明显的红/绿色调（饱和度>阈值）
    2. 位置独立性：该 bbox 与其他文本的距离是否较远（独立区域）
    3. 字号突出：该 bbox 的高度是否明显大于其他文本的平均高度
    """
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        img = Image.open(img_path).convert("RGB")
        # 获取 bbox 范围（easyocr 返回 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]）
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        x_min, x_max = max(0, int(min(xs))), min(img.width, int(max(xs)))
        y_min, y_max = max(0, int(min(ys))), min(img.height, int(max(ys)))
        if x_max <= x_min or y_max <= y_min:
            return False
        # 扩展 bbox 周围 10px 用于检测圈线
        pad = 10
        x_min_ext = max(0, x_min - pad)
        y_min_ext = max(0, y_min - pad)
        x_max_ext = min(img.width, x_max + pad)
        y_max_ext = min(img.height, y_max + pad)
        region = img.crop((x_min_ext, y_min_ext, x_max_ext, y_max_ext))
        # 检测红/绿色像素比例
        pixels = list(region.getdata())
        if not pixels:
            return False
        red_count = sum(1 for r, g, b in pixels if r > 180 and g < 100 and b < 100)
        green_count = sum(1 for r, g, b in pixels if r < 100 and g > 150 and b < 100)
        total = len(pixels)
        # 红/绿色像素占比超过 5% 视为标记
        if (red_count + green_count) / total > 0.05:
            return True
        # 字号检测：该 bbox 高度是否明显大于其他文本平均高度
        this_height = y_max - y_min
        other_heights = []
        for other_bbox, _, _ in all_results:
            if other_bbox == bbox:
                continue
            oys = [p[1] for p in other_bbox]
            h = int(max(oys)) - int(min(oys))
            if h > 0:
                other_heights.append(h)
        if other_heights:
            avg_height = sum(other_heights) / len(other_heights)
            if this_height > avg_height * 1.5:
                return True
    except Exception:
        pass
    return False


def _group_gmlogger_attachments(gm_atts: list) -> dict:
    """对 gmlogger 附件按基础名分组（识别 rar 分卷），返回 {base_name: [att, ...]}"""
    import re as _re
    groups = {}
    for att in gm_atts:
        fname = att.get("filename", "") or ""
        m = _re.match(r"^(.+)\.part(\d+)\.rar$", fname, _re.I)
        if m:
            base = m.group(1)
        else:
            base = fname
        groups.setdefault(base, []).append(att)
    return groups


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
            vid_time, vid_detail = _diag_extract_time_from_video(issue, headers, att_timeout, gm_dates, ref_pool, gm_ref_dt, gm_times)
            if vid_time:
                return "success", vid_time, f"视频帧 OCR 兜底: {vid_detail}"
        # 视频兜底未命中：用包内时间戳中最近的作为建议
        if ref_pool and ext_dt:
            # 找与提取时间最近的包内时间戳
            closest_entry = min(ref_pool, key=lambda e: abs((e[1] - ext_dt).total_seconds()))
            closest_s, closest_dt = closest_entry
            # 也找最新的时间戳作为备选
            latest_entry = max(ref_pool, key=lambda e: e[1])
            latest_s, latest_dt = latest_entry
            # 取最接近提取时间的那个
            if abs((closest_dt - ext_dt).total_seconds()) <= abs((latest_dt - ext_dt).total_seconds()):
                best_s, best_dt = closest_s, closest_dt
            else:
                best_s, best_dt = latest_s, latest_dt
            return "manual", best_s, (f"提取时间 {extracted} 与包内时间戳前后5分钟均未命中，"
                                      f"视频提取也未命中。包内最近时间戳为 {best_s}，请人工确认是否正确{gm_note}")
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
                issue, headers, att_timeout, gm_dates, [], gm_ref_dt, gm_times)
            vid_dt = _ts_parse_datetime(vid_time) if vid_time else None
            if vid_time:
                return "success", vid_time, (
                    f"gmlogger 包内无法解析（文件过大/解压失败），"
                    f"视频提取时间 {vid_time}，{vid_detail}")
            # 评论区提取时间与 gmlogger 文件名时间接近 → 可用
            if ext_dt and abs((gm_ref_dt - ext_dt).total_seconds()) <= 900:
                return "success", extracted, (
                    f"gmlogger 包内无法解析，提取时间 {extracted}（来自评论区/标题/描述/字段）"
                    f"与 gmlogger 文件名时间 {gm_times[0][0]} 前后15分钟内命中，可用该时间作为替换")
            # 视频时间与提取时间接近 → 互相印证（用视频时间，因为有 12h 转换）
            if vid_dt and ext_dt and abs((vid_dt - ext_dt).total_seconds()) <= 900:
                return "success", vid_time, (
                    f"gmlogger 包内无法解析，视频时间 {vid_time} 与提取时间 {extracted}（来自评论区/标题/描述/字段）接近，交叉印证可用")
            # 视频时间存在但与任何源都不接近 → 参考建议
            if vid_time:
                return "manual", vid_time, (
                    f"gmlogger 包内无法解析（文件过大/解压失败），"
                    f"视频提取时间 {vid_time}，gmlogger 文件名时间 {gm_times[0][0]}，"
                    f"提取时间 {extracted or '(无)'}（来自评论区/标题/描述/字段），三者未命中，待人工审核{gm_note}")
        # 无视频或视频提取失败：仅用提取时间与 gmlogger 文件名时间对比
        if ext_dt and abs((gm_ref_dt - ext_dt).total_seconds()) <= 3600:
            return "success", extracted, (
                f"gmlogger 包内无法解析，提取时间 {extracted}（来自评论区/标题/描述/字段）"
                f"与 gmlogger 文件名时间 {gm_times[0][0]} 前后60分钟内接近，可用该时间作为替换{gm_note}")
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


def _troubleshoot_diagnose_impl(bugid, err_msg, problem_time, done_time, force=False):
    """诊断实现（从 troubleshoot_diagnose 抽取，便于统一 try/finally 管理取消标志）"""
    logger.info("诊断开始: %s%s", bugid, "（强制重新执行）" if force else "")
    try:
        result = _troubleshoot_diagnose_inner(bugid, err_msg, problem_time, done_time, force)
        # 统一注入 needs_analysis 标识（供前端拆分两张表）
        data = result.get("data") if isinstance(result, dict) else None
        if isinstance(data, dict) and "category" in data:
            data["needs_analysis"] = data["category"] not in _SKIP_ANALYSIS_CATEGORIES
        return result
    finally:
        # 线程完成时清除取消标志（无论是正常完成还是被中断）
        _diag_cancel.pop(bugid, None)


def _troubleshoot_diagnose_inner(bugid, err_msg, problem_time, done_time, force=False):
    """诊断内部实现（实际逻辑）"""
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
    logger.info("诊断核心逻辑开始: %s, 附件数=%d", bugid, len(attachments))
    # —— 时间过滤为空时先检查评论区是否有“问题重复”，有则直接跳过后续链路 ——
    if "时间过滤后日志为空" in err_msg:
        _comments = jira_client.extract_comments(issue)
        if any("问题重复" in str(c) for c in _comments):
            category = "问题重复"
            detail = "评论区存在“问题重复”标记，无需排查，跳过后续链路"
            report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time)
            result = {"bugid": bugid, "category": category, "problem_time": problem_time,
                       "archive_files": [], "detail": detail, "main_entries": [],
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
            category = "解压问题"
            detail = f"无gmlogger文件，但解压文件中存在错误时间({problem_time})前后5分钟内对应文件，解压问题，待排查"
            verify_status, suggested_time = "", ""
        else:
            category = "无gmlogger文件"
            detail = f"该 Issue 共 {len(attachments)} 个附件中未找到 gmlogger 日志文件，无需提取时间"
            verify_status, suggested_time = "", ""
        report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time, verify_status, suggested_time, archive_results)
        result = {"bugid": bugid, "category": category, "problem_time": problem_time,
                   "archive_files": archive_results, "detail": detail, "main_entries": [],
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
    logger.info("诊断 %s: 开始视频 OCR + 文件名交叉验证", bugid)
    verify_status, suggested_time, vdetail = _diag_verify_suggestion(
        issue, gm_times, [], main_times=[], all_times=[],
        headers=headers, att_timeout=att_timeout)
    logger.info("诊断 %s: 视频验证结果=%s, suggested_time=%s", bugid, verify_status, suggested_time or "N/A")
    if verify_status == "success":
        category = "触发时间问题"
        detail = f"视频 OCR 与 gmlogger 文件名交叉印证成功（{vdetail}），已跳过压缩包下载"
        report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time, verify_status, suggested_time)
        result = {"bugid": bugid, "category": category, "problem_time": problem_time,
                   "archive_files": [], "detail": detail, "main_entries": [],
                   "verify_status": verify_status, "suggested_time": suggested_time, "report": report, "done_time": done_time}
        _save_diagnose_cache(bugid, result)
        return _ok(result, f"{bugid} 诊断完成：{category}（视频印证）")
    # 2. 视频未确认 → 图片 OCR + 智能筛选（新增步骤）
    _check_diag_cancel(bugid)
    img_time_str, img_detail = "", ""
    # 按分卷分组统计 gmlogger 组数
    gm_groups = _group_gmlogger_attachments(gm_atts)
    num_groups = len(gm_groups)
    logger.info("诊断 %s: gmlogger 共 %d 组", bugid, num_groups)
    filtered_attachments = None  # None 表示使用全量附件
    if num_groups > 10:
        logger.info("诊断 %s: gmlogger 组数>10，尝试图片 OCR 提取触发时间", bugid)
        img_time_str, img_detail = _diag_extract_time_from_images(issue, headers, att_timeout, bugid)
        if img_time_str:
            logger.info("诊断 %s: 图片 OCR 提取到触发时间 %s (%s)", bugid, img_time_str, img_detail)
            # 筛选图片时间 ±15 分钟内的 gmlogger 组
            from src.clients.jira_client import _parse_filename_time
            img_dt = _ts_parse_datetime(img_time_str)
            if img_dt:
                matched_bases = set()
                for base, atts in gm_groups.items():
                    parsed = _parse_filename_time(base, "gmlogger")
                    if parsed and abs((parsed[1] - img_dt).total_seconds()) <= 900:  # 15分钟
                        matched_bases.add(base)
                if matched_bases:
                    logger.info("诊断 %s: 图片时间 ±15min 筛选后剩余 %d 组（原有 %d 组）", bugid, len(matched_bases), num_groups)
                    # 构建筛选后的附件列表（仅包含命中的 gmlogger 附件 + 其他附件）
                    matched_fnames = set()
                    for base in matched_bases:
                        for att in gm_groups[base]:
                            matched_fnames.add(att.get("filename", ""))
                    filtered_attachments = [a for a in attachments
                                            if a.get("filename", "") not in {att.get("filename", "") for att in gm_atts}
                                            or a.get("filename", "") in matched_fnames]
                else:
                    logger.info("诊断 %s: 图片时间 ±15min 未匹配任何 gmlogger 组，走全量解压", bugid)
        else:
            logger.info("诊断 %s: 图片 OCR 未提取到触发时间，走全量解压", bugid)
    # 3. 下载压缩包做权威比对（智能筛选或全量）
    _check_diag_cancel(bugid)
    probe_attachments = filtered_attachments if filtered_attachments is not None else attachments
    probe_label = f"仅 {len([a for a in probe_attachments if 'gmlogger' in (a.get('filename', '') or '').lower()])} 个 gmlogger 附件" if filtered_attachments else "全部"
    logger.info("诊断 %s: 开始下载 gmlogger 压缩包做权威比对（%s）", bugid, probe_label)
    gm_probe = _diag_gmlogger_main_times(probe_attachments, headers, att_timeout, bugid)
    logger.info("诊断 %s: gmlogger 内包探测结果=%s, main_times=%d", bugid, gm_probe.get("status"), len(gm_probe.get("main_times", [])))
    main_times = gm_probe.get("main_times", [])
    all_times = gm_probe.get("all_times", [])
    main_entries = gm_probe.get("main_entries", [])
    hit = [t for t in (main_times + all_times) if err_dt and abs((t[1] - err_dt).total_seconds()) <= 300]
    # 智能筛选未命中且非全量解压：回退到全量解压
    if not hit and filtered_attachments is not None:
        _check_diag_cancel(bugid)
        logger.info("诊断 %s: 智能筛选未命中，回退到全量 gmlogger 解压", bugid)
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
                       "archive_files": [], "detail": detail, "main_entries": [],
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
        if img_time_str:
            detail += f"（图片 OCR 提取时间: {img_time_str}，{img_detail}）"
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
               "archive_files": archive_results, "detail": detail, "main_entries": main_entries,
               "verify_status": verify_status, "suggested_time": suggested_time, "report": report, "done_time": done_time}
    _save_diagnose_cache(bugid, result)
    logger.info("诊断 %s: 最终分类=%s, verify_status=%s", bugid, category, verify_status or "N/A")
    return _ok(result, f"{bugid} 诊断完成：{category}")


def _parse_bugids(raw: str) -> list:
    """解析 bugid 输入：支持分号、逗号、中英文逗号分隔，最多 30 个"""
    raw = raw.replace("，", ",").replace(";", ",")
    return [b.strip() for b in raw.split(",") if b.strip()][:30]


def _bot_compare_pc_online() -> dict:
    """机器人用：对比PC成功 vs 线上成功，返回差集结果（复用 online_followup_compare 核心逻辑）"""
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    if not app_token or not table_id:
        raise ValueError("多维表格 app_token/table_id 未配置")
    records = feishu_client.list_bitable_records(app_token, table_id)
    pc_success = {}
    online_success = {}
    online_all = {}
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(cfg.get("bugid_field", "jira号"), ""))
        if not jira_no:
            continue
        result_status = _bitable_text(fields.get("分析结果", ""))
        source = _bitable_text(fields.get("触发来源", ""))
        entry = {
            "jira号": jira_no, "分析结果": result_status, "触发来源": source,
            "分析完成时间": _bitable_text(fields.get("分析完成时间", "")),
            "触发时间": _bitable_text(fields.get("分析问题时间", "")),
            "错误信息": _bitable_text(fields.get("错误信息", "")),
        }
        if result_status == "成功":
            if source == "jira_analyze":
                pc_success[jira_no] = entry
            elif source in ("parseFullTicket", "feishu_bot"):
                online_success[jira_no] = entry
        if source in ("parseFullTicket", "feishu_bot"):
            online_all.setdefault(jira_no, []).append(entry)
    pc_keys = set(pc_success.keys())
    online_ok_keys = set(online_success.keys())
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
            "触发时间": pc_entry["触发时间"],
            "线上状态": status, "线上错误信息": err,
        })
    return {
        "pc_success_count": len(pc_success),
        "online_success_count": len(online_success),
        "diff_count": len(diff_records),
        "diff_records": diff_records,
    }


def _bot_run_11_1_continuous(chat_id: str, diff_records: list, batch_size: int,
                             interval_min: int, total_rounds: int):
    """11.1 持续执行：将差集记录分批在线上执行，第一轮输出结论，后续轮次静默"""
    import time as _time
    from src.clients import feishu_client
    from src.clients.base import http_post
    _reset_cancel_event(chat_id)
    try:
        all_bugids = [r["jira号"] for r in diff_records if r.get("jira号")]
        if not all_bugids:
            feishu_client.send_bot_message(chat_id, "差集无可执行的 Jira 号")
            return
        # 提取触发时间（从差集记录中获取）
        trigger_times = {}
        for r in diff_records:
            tt = r.get("触发时间", "").strip()
            if tt:
                trigger_times[r["jira号"]] = tt
        # 缺少触发时间的，尝试从云端缓存获取
        missing = [b for b in all_bugids if b not in trigger_times]
        if missing:
            cloud_times, _ = _load_cloud_trigger_cache()
            for b in missing:
                if b in cloud_times:
                    trigger_times[b] = cloud_times[b]
        run_bugids = [b for b in all_bugids if b in trigger_times]
        feishu_client.send_bot_message(chat_id,
            f"差集 {len(all_bugids)} 条，{len(run_bugids)} 条有触发时间")
        done_total = 0
        total_success = 0
        total_fail = 0
        for round_num in range(1, total_rounds + 1):
            if _is_cancelled(chat_id):
                break
            undone = run_bugids[done_total:]
            if not undone:
                break
            batch = undone[:batch_size]
            # 执行本轮
            success = 0
            for bugid in batch:
                if _is_cancelled(chat_id):
                    break
                exec_time = trigger_times.get(bugid, "")
                try:
                    payload = _build_prod_ai_payload(bugid, exec_time)
                    resp = http_post(_get_prod_ai_url(), payload, timeout=15)
                    resp_code = resp.get("code") if isinstance(resp, dict) else None
                    if resp_code in (200, 0, "200"):
                        success += 1
                except Exception:
                    pass
            done_total += len(batch)
            total_success += success
            total_fail += len(batch) - success
            # 第一轮输出结论，后续轮次静默
            if round_num == 1:
                feishu_client.send_bot_message(chat_id,
                    f"[1/{total_rounds}] 第一轮执行完成: 成功 {success}/{len(batch)}\n"
                    f"累计: 成功 {total_success}，失败 {total_fail}")
            if round_num < total_rounds and done_total < len(run_bugids):
                if not _is_cancelled(chat_id):
                    for _ in range(interval_min * 60):
                        if _is_cancelled(chat_id):
                            break
                        _time.sleep(1)
        # 最终输出总结
        if not _is_cancelled(chat_id):
            feishu_client.send_bot_message(chat_id,
                f"11.1 执行完成\n总计执行 {done_total} 条\n成功 {total_success}，失败 {total_fail}")
        else:
            feishu_client.send_bot_message(chat_id,
                f"11.1 已中断（完成 {done_total} 条，成功 {total_success}）")
    except Exception as e:
        logger.error("11.1 持续执行失败: %s", e)
        feishu_client.send_bot_message(chat_id, f"11.1 执行异常: {str(e)[:200]}")
    finally:
        _clear_running_task(chat_id)


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

