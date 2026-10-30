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
from src.core.attachment_guard import (
    BUDGET as _ATTACH_BUDGET,
    AttachmentLimitError as _AttachmentLimitError,
    MAX_ATTACHMENT_BYTES as _MAX_ATTACHMENT_BYTES,
    MAX_MEDIA_BYTES as _MAX_MEDIA_BYTES,
    MAX_RAR_VOLUME_BYTES as _MAX_RAR_VOLUME_BYTES,
    MAX_SINGLE_ENTRY_BYTES as _MAX_SINGLE_ENTRY_BYTES,
    filter_large_entries as _filter_large_entries,
    stream_download as _stream_download,
)

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

_rapid_ocr_engine = None

_rapid_ocr_lock = threading.Lock()  # 防止 RapidOCR 并发初始化

_OCR_TIME_FULL_RE = re.compile(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2}[\s.,\-]?\d{1,2}[.:,;]\d{2}(?:[.:,;]\d{2})?)')

_OCR_TIME_ONLY_RE = re.compile(r'(?<!\d)(\d{1,2}[.:,;]\d{2}(?:[.:,;]\d{2})?)(?!\d)')

# 中文相对日期 + 时间：昨天/今天/前天/大前天 + HH:MM 或 HH:MM:SS
_OCR_RELATIVE_DATE_TIME_RE = re.compile(r'(昨天|今天|前天|大前天)[\s\-]*?(\d{1,2}[.:,;]\d{2}(?:[.:,;]\d{2})?)')

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

_ARCHIVE_NAME_RE = re.compile(r"\.(zip|7z|rar|tar|gz|bz2|xz)(\.\d{2,3})?$", re.I)

_SPLIT_ARCHIVE_RE = re.compile(r"\.\d{2,3}$")

_ARCHIVE_PROBE_MAX_BYTES = 500 * 1024 * 1024

# 视频文件后缀
_VIDEO_SUFFIXES = (".mp4", ".avi", ".mov", ".mkv")

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
                # 静默用线程本地标记实现，多个群并发时互不影响
                parts = [p.strip() for p in re.split(r'[;；]', text) if p.strip()]
                if len(parts) > 1:
                    from src.clients import feishu_client as _fc
                    try:
                        for i, part in enumerate(parts):
                            _fc.set_bot_silent(i < len(parts) - 1)
                            _process_bot_command(msg.chat_id, part)
                    finally:
                        _fc.set_bot_silent(False)
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
        from src.clients import feishu_client as _fc_reset
        _fc_reset.set_bot_silent(False)
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


# ── 机器人功能范围（2026-10 收敛）────────────────────────────────
# 只保留「工作日结论播报」：0（含 1 单次 / 2 定时 / 3 状态 / 4 每周汇总）、0.4、
# 快捷日期、退出/取消、分号链式命令。历史命令（4.x/5.x/6.x/9.x/10.x/11.x）已下线。
_RETIRED_BOT_COMMAND_RE = re.compile(r"^(?:4|5|6|9|10|11)(?:\.\d(?:\.\d)?)?$")
_RETIRED_BOT_HINT = (
    "该功能已下线。当前仅支持：\n"
    "0 工作日结论播报（单次 / 定时 / 状态 / 每周汇总）\n"
    "直接发送日期查看当天结论（如 2026-09-21）\n"
    "发送「退出」取消当前操作"
)


def _is_retired_bot_command(text: str) -> bool:
    """是否为已下线的历史命令（4.x / 5.x / 6.x / 9.x / 10.x / 11.x）"""
    return bool(_RETIRED_BOT_COMMAND_RE.match((text or "").strip()))


def _process_bot_command(chat_id: str, text: str):
    """机器人命令状态机：当前只保留「工作日结论播报」相关命令"""
    import threading
    from src.clients import feishu_client
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
            "0. 工作日结论播报（单次 / 定时 / 状态 / 每周汇总）\n\n"
            "直接发送日期可查看当天结论（如 2026-09-21）\n"
            "支持分号链式：0;1;2026-09-21\n"
            "发送「退出」可取消当前任务\n\n"
            "请输入子功能编号（如 0）唤醒对应功能（2分钟内有效）")
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

    # ==================== 已下线功能拦截 ====================
    # 机器人只保留「工作日结论播报」，历史命令一律回提示，避免被误触发写表/跑批
    if _is_retired_bot_command(text):
        _clear_bot_session(chat_id)
        feishu_client.send_bot_message(chat_id, _RETIRED_BOT_HINT)
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
        "未识别的指令。当前只支持：\n"
        "0 工作日结论播报（单次 / 定时 / 状态 / 每周汇总）\n"
        "直接发送日期查看当天结论（如 2026-09-21）\n"
        "发送「退出」取消当前操作")


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
            # 同来源云端批量记录去重：只排除同来源已执行的Jira，PC和线上允许重复
            try:
                from src.api.routes.testing import _get_same_source_executed_keys
                # 机器人默认按线上来源去重
                bot_source = "parseFullTicket"
                cloud_executed = _get_same_source_executed_keys(bot_source)
                if cloud_executed:
                    before_cloud = len(exclude_keys)
                    exclude_keys |= cloud_executed
                    added_cloud = len(exclude_keys) - before_cloud
                    if added_cloud:
                        logger.info("云端同来源去重(%s): 额外排除 %d 条", bot_source, added_cloud)
            except Exception as e:
                logger.warning("云端同来源去重失败: %s", e)
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
        main_cats = ["触发时间问题", "无gmlogger", "服务关闭", "分析任务执行超时，跳过排查", "并发过多", "IT侧服务停止"]
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
                _save_trigger_time_to_cloud(bugid, str(tt) if tt else "", source="机器人提取")
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


def _bot_daily_broadcast(chat_id: str, date_str: str, is_scheduled: bool) -> bool:
    """昨日结论播报执行函数（单次和定时共用），自动扩展到后续非工作日

    :return: 是否成功发出播报（用于写跨机器播报状态）
    """
    from src.clients import feishu_client
    from src.services import broadcast_state
    sent_ok = False
    try:
        # 计算日期范围用于展示
        report_dates = _get_report_date_range(date_str)
        date_label = f"{report_dates[0]} ~ {report_dates[-1]}" if len(report_dates) > 1 else date_str
        if not is_scheduled:
            ok = feishu_client.send_bot_message(chat_id, f"正在生成 {date_label} 每日结论...")
            if not ok:
                _auto_disable_daily_broadcast(chat_id)
                return False
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
            return False
        sent_ok = True
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
        # 跨机器播报状态：成功/失败都落一条，其他机器据此跳过同一天
        try:
            broadcast_state.record_result(chat_id, date_str, sent_ok,
                                          "定时" if is_scheduled else "手动")
        except Exception as e:
            logger.warning("写入播报状态失败: %s", e)
        _clear_running_task(chat_id)
    return sent_ok


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


def _try_acquire_broadcast_lock(chat_id: str, date_str: str, time_str: str) -> bool:
    """文件锁：确保多进程/多实例下同一播报只执行一次"""
    lock_dir = os.path.join(PROJECT_ROOT, "data", "broadcast_locks")
    os.makedirs(lock_dir, exist_ok=True)
    lock_file = os.path.join(lock_dir, f"{chat_id}_{date_str}_{time_str}.lock")
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _cleanup_broadcast_locks():
    """清理 7 天前的播报锁文件"""
    lock_dir = os.path.join(PROJECT_ROOT, "data", "broadcast_locks")
    if not os.path.isdir(lock_dir):
        return
    cutoff = datetime.now().timestamp() - 7 * 86400
    for f in os.listdir(lock_dir):
        fp = os.path.join(lock_dir, f)
        try:
            if os.path.getmtime(fp) < cutoff:
                os.remove(fp)
        except Exception:
            pass


def _hhmm_to_minutes(value: str) -> int:
    """把 'H:MM'/'HH:MM' 转成一天中的分钟数，非法返回 -1（用于避免字符串比较的坑）"""
    try:
        hh, mm = str(value).strip().replace("：", ":").split(":")
        minutes = int(hh) * 60 + int(mm)
        return minutes if 0 <= minutes < 24 * 60 else -1
    except (ValueError, AttributeError):
        return -1


def _daily_scheduler_loop():
    """定时调度器：每30秒检查是否有群聊需要播报（使用中国法定工作日，播报前一工作日数据）

    触发条件改为「当前时间 ≥ 设定时间 且 今天还没播过」：
    - 进程被长任务卡住几十秒、或某次 30 秒轮询恰好错过整分钟，都能在下一个周期补上
    - 服务重启后如果当天还没播过，会立即补播（不会重复播）
    """
    from src.services import broadcast_state
    logger.info("昨日播报调度器已启动")
    while not _daily_scheduler_stop.is_set():
        try:
            cfg = _load_daily_broadcast_config()
            now = datetime.now()
            cur_time = now.strftime("%H:%M")
            cur_date = now.strftime("%Y-%m-%d")
            if _is_chinese_workday(now):
                now_min = now.hour * 60 + now.minute
                for chat_id, chat_cfg in cfg.items():
                    if not chat_cfg.get("enabled"):
                        continue
                    report_time = chat_cfg.get("report_time", "17:50")
                    target_min = _hhmm_to_minutes(report_time)
                    if target_min < 0 or now_min < target_min:
                        continue
                    if chat_cfg.get("last_run_date") == cur_date:
                        continue  # 今天已播过
                    # 播报前一工作日的数据
                    prev_workday = _get_prev_chinese_workday(now)
                    # 跨机器共享状态：别的机器已播过这个报告日期就跳过，避免重复播报
                    claim_state, claim_rec = broadcast_state.claim(chat_id, prev_workday, cur_time)
                    if claim_state == "exists":
                        chat_cfg["last_run_date"] = cur_date  # 本地记账，避免每 30 秒反复查云端
                        try:
                            _save_daily_broadcast_config(cfg)
                        except Exception:
                            pass
                        logger.info("跳过昨日播报(%s): chat=%s 已由其他机器播报",
                                    prev_workday, chat_id[:12])
                        continue
                    if claim_state == "unavailable":
                        # 云端不可用：回退本地文件锁，仍能防同机多进程重复播报
                        if not _try_acquire_broadcast_lock(chat_id, cur_date, cur_time):
                            continue
                    logger.info("触发昨日播报(%s): chat=%s, 当前=%s, 播报日期=%s, 设定=%s, 状态=%s",
                                "准点" if now_min == target_min else "补播",
                                chat_id[:12], cur_date, prev_workday, report_time, claim_state)
                    chat_cfg["last_run_date"] = cur_date  # 先记账，避免失败后每 30 秒重试造成刷屏
                    try:
                        _bot_daily_broadcast(chat_id, prev_workday, True)
                    except Exception as e:
                        logger.error("定时播报执行失败: %s", e)
                    try:
                        _save_daily_broadcast_config(cfg)
                    except Exception as e:
                        logger.warning("记录播报日期失败: %s", e)
            # 定期清理旧锁文件
            if cur_time == "00:00":
                _cleanup_broadcast_locks()
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
            # 数据不足：本轮执行数少于目标数量，停止后续轮次
            if len(round_executed) < count:
                feishu_client.send_bot_message(chat_id,
                    f"数据不足（本轮仅执行 {len(round_executed)}/{count} 条），停止后续执行。"
                    f"累计已执行 {len(executed_set)} 条不重复")
                break
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
        # 检查是否凑不够数量：展示未执行的候选及原因
        not_enough = len(run_bugids) < count
        if not_enough:
            no_time_list = [b for b in filtered if b not in trigger_times]
            if no_time_list:
                # 区分无gmlogger和提取失败
                no_gmlogger = []
                extract_fail = []
                for b in no_time_list[:10]:  # 最多展示10条
                    try:
                        issue = _jc.fetch_issue(b)
                        atts = (issue.get("fields") or {}).get("attachment") or []
                        if not _has_gmlogger_logs(atts, b):
                            no_gmlogger.append(b)
                        else:
                            extract_fail.append(b)
                    except Exception:
                        extract_fail.append(b)
                msg_parts = [f"数据不足：仅 {len(run_bugids)}/{count} 条有触发时间"]
                if no_gmlogger:
                    msg_parts.append(f"无gmlogger({len([b for b in no_time_list if b not in trigger_times])}条): {', '.join(no_gmlogger[:5])}")
                if extract_fail:
                    msg_parts.append(f"提取失败({len(extract_fail)}条): {', '.join(extract_fail[:5])}")
                msg_parts.append("本轮执行后将停止后续轮次")
                feishu_client.send_bot_message(chat_id, "\n".join(msg_parts))
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
        "JQL6": ("本周新增Bug", 'created >= startOfWeek() AND issuetype = "bug" AND status != "closed"'),
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


def _jira_att_auth() -> tuple:
    """构造下载 Jira 压缩包附件的认证头与超时，返回 (headers, timeout)"""
    jcfg = load_config().get("jira_api", {})
    headers = {}
    token = jcfg.get("token", "")
    if token:
        if jcfg.get("auth_type", "bearer").lower() == "bearer":
            headers["Authorization"] = f"Bearer {token}"
        elif jcfg.get("username"):
            import base64
            headers["Authorization"] = "Basic " + base64.b64encode(
                f"{jcfg['username']}:{token}".encode()).decode()
    timeout = max(int(jcfg.get("timeout", 30)), 120)
    return headers, timeout


def _has_gmlogger_logs(attachments: list, bugid: str = "") -> bool:
    """判断 Jira 是否含可用日志（gmlogger）。智能回退：
    
    1) 附件文件名含 gmlogger/gmlog/main.log/.log/.txt → 直接判定有（快，不下载）；
    2) 否则仅对≤ 500MB 的单卷压缩包下载探测包内是否有 main/.log/.txt 文件；
       分卷压缩包(.001/.002 等)或超大包一律跳过（避免 GB 级下载拖慢）。
    """
    names = [(a.get("filename", "") or "").lower() for a in attachments]
    # 有直接的 gmlogger/gmlog 文件、main.log 或任意 .log/.txt 文件就算有，不需要解压
    if any("gmlogger" in n or "gmlog" in n or "logcat" in n or "dltlog" in n or "bllog" in n
           or "logger" in n or "main.log" in n or n.endswith(".log") or n.endswith(".txt") for n in names):
        return True
    headers, timeout = _jira_att_auth()
    for att in attachments:
        fn = (att.get("filename", "") or "").lower()
        if not _ARCHIVE_NAME_RE.search(fn):
            continue
        # 跳过：分卷压缩包（如 xxx.7z.001），多卷无法只读目录且体积极大
        if _SPLIT_ARCHIVE_RE.search(fn):
            continue
        # 跳过：超过探测上限的包，避免整包下载
        if att.get("size", 0) and att["size"] > _ARCHIVE_PROBE_MAX_BYTES:
            continue
        res = _diag_list_archive_entries(att.get("content", ""), headers, timeout, bugid, filename=att.get("filename", ""))
        if res.get("ok") and any(
            "main" in os.path.basename(e).lower() or e.lower().endswith(".log") or e.lower().endswith(".txt")
            for e in res.get("entries", [])
        ):
            logger.info("无gmlogger文件名，但压缩包 %s 内含 main/.log/.txt 文件，判定有日志 (%s)", fn, bugid)
            return True
    return False


def _diag_list_archive_entries(att_url: str, headers: dict, timeout: int, bugid: str = "", filename: str = "") -> dict:
    """下载压缩包附件并列出解压后的文件名（支持 zip/tar 系，其余标记不支持）

    :param filename: 原始附件文件名，用于分卷 zip 等格式的正确识别
    """
    import tarfile
    import tempfile
    import zipfile
    import httpx as _httpx
    import re as _re
    _label = f"{bugid} " if bugid else ""
    logger.info("%s开始下载附件: %s", _label, att_url[:120])
    entries = []
    total_size = 0
    try:
        with tempfile.TemporaryDirectory() as tmp:
            # 保留原始文件名（清理路径分隔符），以便分卷 zip 等格式正确识别
            safe_name = _re.sub(r'[/\\]', '_', filename) if filename else "att.bin"
            src_path = os.path.join(tmp, safe_name)
            # 流式下载：体积上限 / 磁盘水位 / 单bug预算 / 附件缓存由 attachment_guard 统一负责
            total_size = _stream_download(
                att_url, headers, src_path, timeout=timeout, bugid=bugid,
                filename=safe_name, max_bytes=_MAX_ATTACHMENT_BYTES)
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
            # 分卷总量单独设 2GB 上限，避免多卷累计把磁盘写满
            for _p, att in parts:
                fname = att.get("filename", "") or f"part{_p}.rar"
                dst = os.path.join(rar_dir, fname)
                logger.info("%s下载 rar 分卷: %s", _label, fname)
                remaining = _MAX_RAR_VOLUME_BYTES - total_size
                if remaining <= 0:
                    return {"ok": False, "entries": [],
                            "reason": f"rar 分卷总量超过 {_MAX_RAR_VOLUME_BYTES // 1024 // 1024 // 1024}GB 上限",
                            "size": total_size}
                total_size += _stream_download(
                    att.get("content", ""), headers, dst, timeout=timeout, bugid=bugid,
                    filename=fname, max_bytes=remaining)
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
        # 7z 格式（解压前按条目大小过滤：7z 需整块落盘，超大条目先剔除）
        import py7zr
        if py7zr.is_7zfile(path):
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                with py7zr.SevenZipFile(path, "r") as zf:
                    _size_map = {getattr(i, "filename", ""): getattr(i, "uncompressed", 0) or 0
                                 for i in zf.list()}
                    names, _skipped = _filter_large_entries(names, _size_map, label="7z 压缩包")
                    if names:
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
        # rar 格式（解压前按条目大小过滤：rarfile 只能整条目解压）
        import rarfile
        if _setup_rarfile() and rarfile.is_rarfile(path):
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                with rarfile.RarFile(path) as rf:
                    try:
                        _size_map = {m.filename: m.file_size for m in rf.infolist()}
                    except Exception:
                        _size_map = {}
                    names, _skipped = _filter_large_entries(names, _size_map, label="rar 压缩包")
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


_LOG_NAME_HINTS = ("gmlog", "logcat", "dltlog", "bllog", "logger", "pataclogger", "log_")
_LOG_ARCHIVE_SUFFIXES = (".7z", ".rar", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst")
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif")


def _parse_any_log_filename_time(fname: str):
    """从日志包文件名解析抓包时间（复用 jira_client 的实现）"""
    from src.clients.jira_client import parse_log_filename_time
    return parse_log_filename_time(fname)


def _diag_gmlogger_times(attachments: list) -> list:
    """识别日志附件并解析文件名时间，返回 [(时间字符串, datetime)]

    之前只认文件名含 "gmlogger" 或 .log/.txt 的附件，导致
    GMLog_20261027_152355.7z / pataclogger_2026_10_27_17_15_0.part01.rar /
    784da062_20261027_173855.7z 这类明明带时间的日志包被判成“无参考”。
    """
    times = []
    for att in attachments:
        fname = att.get("filename", "") or ""
        if not fname:
            continue
        fn_lower = fname.lower()
        # 视频/图片不是日志包
        if fn_lower.endswith(_VIDEO_SUFFIXES) or fn_lower.endswith(_IMAGE_SUFFIXES):
            continue
        is_logish = (
            any(h in fn_lower for h in _LOG_NAME_HINTS)
            or fn_lower.endswith(".log") or fn_lower.endswith(".txt")
            or fn_lower.endswith(_LOG_ARCHIVE_SUFFIXES)
        )
        if not is_logish:
            continue
        t = _parse_any_log_filename_time(fname)
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
    _ATTACH_BUDGET.begin_bug(bugid)  # 每个 bug 的附件预算独立计数
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
    import time as _time
    # 按基础名分组收集分卷：支持 .zip.001 后缀式与 .part1.rar 嵌入式命名，后缀数字为分卷号（单卷为0）
    _ATTACH_BUDGET.begin_bug(bugid)  # 每个 bug 的附件预算独立计数
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
    _DL_DEADLINE = 300  # 总下载时间上限 5 分钟，超时则跳过
    _dl_start = _time.time()
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
                    _vol_total = 0
                    for _p, att in parts:
                        dst = os.path.join(rar_dir, att.get("filename", "") or f"part{_p}.rar")
                        remaining = _MAX_RAR_VOLUME_BYTES - _vol_total
                        if remaining <= 0:
                            raise _AttachmentLimitError(
                                f"rar 分卷总量超过 {_MAX_RAR_VOLUME_BYTES // 1024 // 1024 // 1024}GB 上限")
                        _vol_total += _stream_download(
                            att.get("content", ""), headers, dst, timeout=timeout,
                            bugid=bugid, filename=os.path.basename(dst), max_bytes=remaining)
                        if _time.time() - _dl_start > _DL_DEADLINE:
                            raise TimeoutError(f"gmlogger 下载超时({_DL_DEADLINE}s)")
                except TimeoutError as e:
                    logger.warning("gmlogger rar 下载超时: %s", e)
                    return {"status": "failed", "reason": f"gmlogger 下载超时({_DL_DEADLINE}s)",
                            "main_entries": [], "main_times": [], "all_times": []}
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
                _merged_written = 0
                with open(merged, "wb") as out:
                    for _p, att in parts:
                        with _httpx.stream("GET", att.get("content", ""), headers=headers,
                                           timeout=timeout, verify=False, follow_redirects=True) as r:
                            r.raise_for_status()
                            for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                                _merged_written += len(chunk)
                                if _merged_written > _MAX_ATTACHMENT_BYTES:
                                    raise _AttachmentLimitError(
                                        f"gmlogger 压缩包超过 {_MAX_ATTACHMENT_BYTES // 1024 // 1024}MB 上限"
                                        f"（已下载 {_merged_written / 1024 / 1024:.1f}MB），已中止")
                                _ATTACH_BUDGET.charge(len(chunk), bugid)
                                out.write(chunk)
                                if _time.time() - _dl_start > _DL_DEADLINE:
                                    raise TimeoutError(f"gmlogger 下载超时({_DL_DEADLINE}s)")
            except TimeoutError as e:
                logger.warning("gmlogger 分卷下载超时: %s", e)
                return {"status": "failed", "reason": f"gmlogger 下载超时({_DL_DEADLINE}s)",
                        "main_entries": [], "main_times": [], "all_times": []}
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


def _get_rapid_ocr():
    """获取 RapidOCR 引擎实例（懒加载+缓存，线程安全，安装不可用时返回 None）"""
    global _rapid_ocr_engine
    if _rapid_ocr_engine is not None and _rapid_ocr_engine is not _OCR_UNAVAILABLE:
        return _rapid_ocr_engine
    if _rapid_ocr_engine is _OCR_UNAVAILABLE:
        return None
    with _rapid_ocr_lock:
        if _rapid_ocr_engine is not None:
            return None if _rapid_ocr_engine is _OCR_UNAVAILABLE else _rapid_ocr_engine
        try:
            from rapidocr_onnxruntime import RapidOCR
            _rapid_ocr_engine = RapidOCR()
            logger.info("RapidOCR 引擎初始化完成")
        except Exception as e:
            logger.warning("RapidOCR 引擎初始化失败（未安装或依赖缺失）: %s", e)
            _rapid_ocr_engine = _OCR_UNAVAILABLE
            return None
    return _rapid_ocr_engine


def _rapid_ocr_readtext(image, _already_enhanced: bool = False):
    """调用 RapidOCR 识别图像，返回与 EasyOCR 兼容的 [bbox, text, conf] 格式

    图像预处理（从 EasyOCR 迁移）：
    - 放大 1.5x（等效 EasyOCR mag_ratio=1.5），提升小字号/低对比度时钟识别能力
    - 已二值化/锐化的图像不再放大（_already_enhanced=True），避免伪影放大降低识别率
    - 降低 box_thresh 至 0.3（默认 0.5 太高，低质量视频帧检测不到文本）
    - text_score 至 0.15（与应用层过滤阈值对齐，避免引擎内部丢弃可用文本）
    """
    import numpy as np
    import cv2
    engine = _get_rapid_ocr()
    if engine is None:
        return []
    try:
        h, w = image.shape[:2]
        # 仅对小尺寸原始帧放大，已二值化/锐化的图像跳过（ROI 已放大，跳过二次放大）
        if not _already_enhanced and w < 1280:
            mag_ratio = 1.5
            enlarged = cv2.resize(image, (int(w * mag_ratio), int(h * mag_ratio)),
                                  interpolation=cv2.INTER_CUBIC)
        else:
            mag_ratio = 1.0
            enlarged = image
        scale = enlarged.shape[0] / h if enlarged is not image else 1.0
        result, elapse = engine(enlarged, box_thresh=0.3, text_score=0.15, use_cls=False)
        if not result:
            return []
        items = []
        for bbox, text, conf in result:
            # 将 bbox 缩放回原图坐标（如果做过放大）
            if scale != 1.0:
                bbox = [[p[0] / scale, p[1] / scale] for p in bbox]
            # RapidOCR bbox 是 [[x1,y1],[x2,y1],[x2,y2],[x1,y2]] 格式，与 EasyOCR 兼容
            items.append([bbox, text, conf])
        logger.info("RapidOCR 识别完成: %d 条文本 (放大%.1fx), 耗时 det=%.2fs cls=%.2fs rec=%.2fs",
                    len(items), mag_ratio if scale != 1.0 else 1.0,
                    elapse[0] if len(elapse) > 0 else 0,
                    elapse[1] if len(elapse) > 1 else 0,
                    elapse[2] if len(elapse) > 2 else 0)
        return items
    except Exception as e:
        logger.warning("RapidOCR 识别异常: %s", e)
        return []


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
            _easyocr_reader = easyocr.Reader(['en', 'ch_sim'], gpu=True, verbose=False)
            logger.info("easyocr Reader 初始化完成（en + ch_sim）")
        except Exception as e:
            logger.warning("easyocr 初始化失败（模型下载超时或网络不可用），视频 OCR 功能已禁用: %s", e)
            _easyocr_reader = _OCR_UNAVAILABLE
            return None
    return _easyocr_reader


# 视频 OCR 统计（ROI 命中 / 整帧 / 静帧跳过 / 投票命中），用于后续调参
_VIDEO_OCR_STATS = {"videos": 0, "roi_frames": 0, "full_frames": 0, "skipped_frames": 0, "vote_hits": 0}


def _frame_signature(frame):
    """帧缩略签名（32x18 灰度），用于判断相邻帧是否相同"""
    import cv2
    small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (32, 18), interpolation=cv2.INTER_AREA)
    return small.astype("float32")


def _same_frame(a, b, tol: float = 1.5) -> bool:
    try:
        import numpy as np
        return float(np.mean(np.abs(a - b))) <= tol
    except Exception:
        return False


def _vote_from_texts(texts, ref_pool, gm_ref_dt, tol):
    """多帧投票（复用已 OCR 文本）：同一 HH:MM 出现 ≥2 次且通过参考池校验才采用"""
    from collections import Counter
    votes = Counter()
    for _sec, text in texts:
        if not text:
            continue
        fixed = _fix_ocr_char_confusion(_fix_ocr_missing_colon(text))
        m = _OCR_TIME_ONLY_RE.search(fixed)
        if m:
            votes[_normalize_ocr_time(m.group(1))] += 1
    if not votes:
        return "", 0
    hm, n = votes.most_common(1)[0]
    if n < 2:
        return "", 0
    date = ref_pool[0] if ref_pool else gm_ref_dt
    if date is None:
        return "", 0
    cand = f"{date.year:04d}-{date.month:02d}-{date.day:02d} {hm}"
    parsed = _parse_datetime_string(cand)
    if not parsed:
        return "", 0
    if ref_pool and not any(abs((dt - parsed[1]).total_seconds()) <= tol for dt in ref_pool):
        return "", 0
    return cand, n


def _ocr_frame_regions(frame) -> str:
    """对状态栏/任务栏等小区域做高倍 OCR

    录屏时间通常出现在：手机顶部状态栏、Windows 右下角任务栏。
    先裁这两块放大 2.5x 再识别，区域小、速度快、抗内容干扰。
    """
    import cv2
    parts = []
    try:
        h, w = frame.shape[:2]
        regions = [
            (0, 0, w, max(1, int(h * 0.10))),                 # 顶部状态栏
            (int(w * 0.55), int(h * 0.94), w, h),             # 右下任务栏
        ]
        for (x1, y1, x2, y2) in regions:
            if x2 - x1 < 40 or y2 - y1 < 12:
                continue
            crop = frame[y1:y2, x1:x2]
            crop = cv2.resize(crop, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
            res = _ocr_readtext(None, crop, _already_enhanced=True) or []
            txt = " ".join(str(r[1]) for r in res if len(r) > 1)
            if txt.strip():
                parts.append(txt)
    except Exception:
        return ""
    return " ".join(parts)


def _ocr_readtext(reader, image, _already_enhanced: bool = False):
    """统一 OCR 调用，RapidOCR 优先 + EasyOCR 回退。

    实测对比（20条视频帧基准测试）：
    - RapidOCR: 正确疬35%, 平均置信度0.867
    - EasyOCR:  正确疬30%, 平均置信度0.234

    流程：RapidOCR → 失败/不可用时回退 EasyOCR
    返回 readtext 结果列表（每项 [bbox, text, conf]）。

    _already_enhanced=True 时跳过图像放大（用于已放大/增强过的 ROI 图像）。

    过滤规则：
    1. 置信度过低的时间类文本（数字/冒号/斜杠）会被过滤掉
    2. 水印相机区域内的时间类文本会被过滤掉（保留设备屏幕时间）
    """
    # 优先使用 RapidOCR（中文场景识别能力更强，置信度更高）
    results = _rapid_ocr_readtext(image, _already_enhanced=_already_enhanced)
    # 类型安全：确保 conf 为数值型
    for _r in results:
        if len(_r) > 2 and not isinstance(_r[2], (int, float)):
            try:
                _r[2] = float(_r[2])
            except (ValueError, TypeError):
                _r[2] = 0.0
    _avg_conf = sum((r[2] for r in results if len(r) > 2), 0) / max(len(results), 1) if results else 0
    # RapidOCR 失败或质量差时回退 EasyOCR（延迟初始化，避免不必要的模型下载）
    if not results or _avg_conf < 0.3:
        if reader is None:
            reader = _get_ocr_reader()
        if reader is not None:
            logger.info("RapidOCR %s（avg_conf=%.2f），回退 EasyOCR",
                       "未识别到文本" if not results else f"质量偏低", _avg_conf)
            try:
                easy_results = reader.readtext(image, canvas_size=2560, mag_ratio=1.5,
                                              text_threshold=0.25, low_text=0.3)
            except Exception as e:
                logger.warning("EasyOCR 参数化调用失败，回退默认: %s", e)
                easy_results = reader.readtext(image)
            easy_avg = sum((r[2] for r in easy_results if len(r) > 2), 0) / max(len(easy_results), 1) if easy_results else 0
            if easy_avg > _avg_conf:
                logger.info("EasyOCR 回退成功（avg_conf=%.2f → %.2f）", _avg_conf, easy_avg)
                results = easy_results
    import re as _re
    _time_like = _re.compile(r'^[\d:\-/\.\s]+$')
    # 1. 过滤低置信度的时间类文本
    filtered = []
    for item in results:
        text = item[1] if len(item) > 1 else ""
        conf = item[2] if len(item) > 2 else 1.0
        if conf < 0.15 and text and _time_like.match(text.strip()):
            logger.info("OCR 过滤低置信度时间类文本: '%s' (conf=%.2f)", text, conf)
            continue
        filtered.append(item)
    # 2. 过滤水印相机区域内的时间类文本
    _wm_keywords = ("水印", "相机真实")
    _weather_keywords = ("晴", "阴", "雨", "雪", "℃", "星期", "周")
    wm_items = [it for it in filtered if any(kw in (it[1] if len(it) > 1 else "") for kw in _wm_keywords)]
    # 回退检测：底部区域的日期+天气混合文本也视为水印标记
    if not wm_items:
        img_h = max((max(p[1] for p in it[0]) for it in filtered if it and it[0]), default=0)
        if img_h > 0:
            bottom_threshold = img_h * 0.6
            for it in filtered:
                text = it[1] if len(it) > 1 else ""
                bbox = it[0] if it else []
                if not bbox or not text:
                    continue
                cy = sum(p[1] for p in bbox) / len(bbox)
                if cy >= bottom_threshold and any(kw in text for kw in _weather_keywords):
                    wm_items.append(it)
    if wm_items:
        # 计算水印区域包围盒（y 范围）
        wm_y_min = min(p[1] for it in wm_items for p in it[0])
        wm_y_max = max(p[1] for it in wm_items for p in it[0])
        wm_x_min = min(p[0] for it in wm_items for p in it[0])
        # 向上扩展 80% 高度（水印时间通常在水印标记上方或同行）
        wm_h = wm_y_max - wm_y_min or 1
        wm_y_min_ext = wm_y_min - wm_h * 0.8
        wm_y_max_ext = wm_y_max + wm_h * 0.3
        clean = []
        for item in filtered:
            text = item[1] if len(item) > 1 else ""
            bbox = item[0] if item else []
            if text and _time_like.match(text.strip()) and bbox:
                # 检查该文本是否在水印区域内
                cy = sum(p[1] for p in bbox) / len(bbox)
                cx = sum(p[0] for p in bbox) / len(bbox)
                if wm_y_min_ext <= cy <= wm_y_max_ext and cx >= wm_x_min - 300:
                    logger.info("OCR 过滤水印相机时间: '%s' (y=%.0f, 水印区域 y=[%.0f,%.0f])",
                                text, cy, wm_y_min_ext, wm_y_max_ext)
                    continue
            clean.append(item)
        filtered = clean
    return filtered


def _normalize_ocr_time(text: str) -> str:
    """将 OCR 时间中的点号/逗号分隔符替换为冒号（10.26.39 → 10:26:39），并规范化日期时间分隔"""
    # 0a. 两位年份扩展：26-10-20 → 2026-10-20（常见于截图/聊天记录）
    def _expand_2digit_year(m):
        yy = int(m.group(1))
        # 00-99 → 2000-2099
        return f"{2000 + yy}{m.group(2)}"
    text = re.sub(r'(?<!\d)(\d{2})([/-]\d{1,2}[/-]\d{1,2})(?!\d)', _expand_2digit_year, text)
    # 0b. 修正年份 OCR 误识别：首位 3-9 大概率是 2 被误识别（如 6024 → 2024）
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
    # 4. 将时间点号/逗号/分号替换为冒号（EasyOCR 常把 : 误识别为 ;）
    text = re.sub(r'(\d{1,2})[.,;](\d{2})(?:[.,;](\d{2}))?',
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


def _parse_video_filename_datetime(filename: str) -> str:
    """从视频文件名提取完整日期时间（YYYY-MM-DD HH:MM:SS），用于 OCR 仅时间的补充验证。
    支持格式：
    - VID_20261014_113000.mp4 → 2026-10-14 11:30:00
    - 20260928-163807.mp4 → 2026-09-28 16:38:07
    - video_2026-10-14_11-30-00.mp4 → 2026-10-14 11:30:00
    返回空字符串表示无法解析。
    """
    from datetime import datetime as _dt
    name = os.path.basename(filename).rsplit('.', 1)[0] if '.' in filename else filename
    # 跳过 hash 文件名
    if re.match(r'^[0-9a-fA-F]{20,}$', name):
        return ""
    # 1. YYYYMMDD_HHMMSS 或 YYYYMMDD-HHMMSS
    m = re.search(r'(20\d{2})([01]\d)([0-3]\d)[-_]([01]\d|2[0-3])([0-5]\d)([0-5]\d)', name)
    if m:
        try:
            dt = _dt(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                     int(m.group(4)), int(m.group(5)), int(m.group(6)))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    # 2. YYYY-MM-DD_HH-MM-SS 或 YYYY-MM-DD HH_MM_SS
    m = re.search(r'(20\d{2})-([01]\d)-([0-3]\d)[_\s]([01]\d|2[0-3])[-_]([0-5]\d)[-_]([0-5]\d)', name)
    if m:
        try:
            dt = _dt(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                     int(m.group(4)), int(m.group(5)), int(m.group(6)))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    # 3. YYYYMMDD_HHMM（无秒）
    m = re.search(r'(20\d{2})([01]\d)([0-3]\d)[-_]([01]\d|2[0-3])([0-5]\d)(?![0-9])', name)
    if m:
        try:
            dt = _dt(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                     int(m.group(4)), int(m.group(5)), 0)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return ""


def _correct_ocr_by_reference(time_str: str, ref_dt) -> str:
    """参照 gmlogger 时间纠正 OCR 数字混淆（如 07:10 被识别为 19:19）
    在参考时间±5分钟范围内生成候选，选择与 OCR 结果数字差异最少的候选。
    普通场景最多允许1位差异；12h偏移场景（AM/PM混淆）允许3位差异。
    OCR 时间与参考时间差值在 10 分钟内视为正确，不做纠正。
    """
    m = re.match(r'(\d{2}):(\d{2})(?::(\d{2}))?', time_str)
    if not m or ref_dt is None:
        return time_str
    hh_str, mm_str = m.group(1), m.group(2)
    ss = m.group(3) or "00"
    ocr_digits = [int(hh_str[0]), int(hh_str[1]), int(mm_str[0]), int(mm_str[1])]
    ocr_hh = ocr_digits[0] * 10 + ocr_digits[1]
    ref_minutes = ref_dt.hour * 60 + ref_dt.minute
    # OCR 时间与参考时间差值在 10 分钟内视为正确，无需纠正
    ocr_minutes = ocr_digits[0] * 600 + ocr_digits[1] * 60 + ocr_digits[2] * 10 + ocr_digits[3]
    if abs(ocr_minutes - ref_minutes) <= 10:
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


def _issue_created_dt(issue: dict):
    """取 Jira 创建时间（用于多视频时优先选最接近创建时间的那份）"""
    try:
        _c = (issue.get("fields") or {}).get("created")
        if _c:
            return _ts_parse_datetime(str(_c).replace("T", " ")[:19])
    except Exception:
        return None
    return None


def _rank_videos(videos: list, attachments: list, created_dt=None) -> list:
    """按与参考时间的相关性对视频排序，返回排序后的列表（最相关的在前）。

    排序策略（按优先级）：
    0. 有 Jira 创建时间（多次复现）→ 视频文件名时间最接近创建时间的优先
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
        if parsed and created_dt:
            return (0, abs((parsed[1] - created_dt).total_seconds()), "")
        if parsed and gm_ref_dt:
            return (1, abs((parsed[1] - gm_ref_dt).total_seconds()), "")
        v_upload_dt = _ts_parse_datetime(v.get("created", ""))
        if v_upload_dt and gm_upload_dt:
            return (2, abs((v_upload_dt - gm_upload_dt).total_seconds()), v.get("created", ""))
        return (3, 0, v.get("created", ""))
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
        # 统一去除时区信息，避免与 naive datetime 比较异常
        if upload_time and upload_time.tzinfo is not None:
            upload_time = upload_time.replace(tzinfo=None)
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
    if video_upload and video_upload.tzinfo is not None:
        video_upload = video_upload.replace(tzinfo=None)
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


def _image_fallback_time(issue: dict, headers: dict, timeout: int, bugid: str, ref_pool: list) -> str:
    """视频未命中 gmlogger 时的图片兜底：非视频图片 OCR 时钟(如20:01)与参考时间(如20:05)
    按"时分"接近(容差10分钟)则用参考日期+图片时间拼接返回；无参考时直接返回图片时间。
    差距过大则弃用，回退后续逻辑。"""
    img_ts, _img_detail = _diag_extract_time_from_images(issue, headers, timeout, bugid)
    if not img_ts:
        return ""
    img_dt = _ts_parse_datetime(img_ts)
    if not img_dt:
        return ""
    if not ref_pool:
        logger.info("视频兜底提取(%s, 图片兜底-无参考): %s", bugid, img_ts)
        return img_ts

    def _tod(dt):
        return dt.hour * 3600 + dt.minute * 60 + dt.second

    best_diff, best_ref = float("inf"), None
    for dt in ref_pool:
        d = abs(_tod(dt) - _tod(img_dt))
        d = min(d, 86400 - d)
        if d < best_diff:
            best_diff, best_ref = d, dt
    if best_ref is None or best_diff > 600:
        logger.info("视频兜底提取(%s, 图片兜底): 图片时间 %s 与参考差 %.0f 秒过大，弃用",
                    bugid, img_ts, best_diff)
        return ""
    combined = best_ref.replace(hour=img_dt.hour, minute=img_dt.minute, second=img_dt.second)
    logger.info("视频兜底提取(%s, 图片兜底): 图片 %s 与参考 %s 接近(%.0f秒)，拼接为 %s",
                bugid, img_ts, best_ref, best_diff, combined)
    return combined.strftime("%Y-%m-%d %H:%M:%S")


def _fix_video_time_against_created(issue: dict, ts: str) -> str:
    """用 Jira 创建时间/日志包/视频文件名给提取结果纠偏（v3）

    参照优先级：日志包抓包时间（≤创建时间，取最接近创建时间） > 视频文件名完整日期时间 > 视频文件名时分+创建日
    """
    from datetime import timedelta
    created = _issue_created_dt(issue)
    attachments = (issue.get("fields") or {}).get("attachment") or []
    refs_all = [d for _, d in _diag_gmlogger_times(attachments) if d]
    if created:
        refs = sorted([r for r in refs_all if r <= created])
    else:
        refs = sorted(refs_all)
    ref_anchor = min(refs, key=lambda r: abs((r - created).total_seconds())) if (refs and created) else (refs[0] if refs else None)

    video_dts, time_only = [], []
    for a in attachments:
        fn = a.get("filename", "") or ""
        if not fn.lower().endswith((".mp4", ".mov", ".avi", ".mkv")):
            continue
        try:
            e = _diag_parse_entry_time(fn)
            if e:
                video_dts.append(e[1])
                continue
            vt = _parse_video_filename_time(fn)
            if vt:
                import re as _re
                mm = _re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", str(vt).strip())
                if mm:
                    from datetime import datetime as _dtm
                    time_only.append(_dtm(1900, 1, 1, int(mm.group(1)), int(mm.group(2)), int(mm.group(3) or 0)))
        except Exception:
            pass
    if created:
        video_dts = [v for v in video_dts if v <= created + timedelta(minutes=5)]

    if not ts:
        if ref_anchor:
            logger.info("视频时间纠偏(提取为空,用日志包): %s", ref_anchor)
            return ref_anchor.strftime("%Y-%m-%d %H:%M:%S")
        if video_dts:
            vt = min(video_dts, key=lambda v: abs((v - created).total_seconds())) if created else video_dts[0]
            logger.info("视频时间纠偏(提取为空,用视频录制时间): %s", vt)
            return vt.strftime("%Y-%m-%d %H:%M:%S")
        if created and time_only:
            hm = min(time_only, key=lambda t: abs((t.hour * 60 + t.minute) - (created.hour * 60 + created.minute)))
            cand = created.replace(hour=hm.hour, minute=hm.minute, second=0)
            if cand <= created + timedelta(minutes=1):
                logger.info("视频时间纠偏(提取为空,用视频时分+创建日): %s", cand)
                return cand.strftime("%Y-%m-%d %H:%M:%S")
        return ""

    dt = _ts_parse_datetime(ts)
    if not dt or not created:
        return ts

    if dt > created + timedelta(minutes=1):
        if ref_anchor:
            cand = dt.replace(year=ref_anchor.year, month=ref_anchor.month, day=ref_anchor.day)
            if cand <= created + timedelta(minutes=1) and abs((cand - ref_anchor).total_seconds()) <= 7200:
                logger.info("视频时间纠偏(晚于创建,对齐日志包日期): %s -> %s", ts, cand)
                return cand.strftime("%Y-%m-%d %H:%M:%S")
            logger.info("视频时间纠偏(晚于创建,改用日志包时间): %s -> %s", ts, ref_anchor)
            return ref_anchor.strftime("%Y-%m-%d %H:%M:%S")
        if video_dts:
            vt = min(video_dts, key=lambda v: abs((v - created).total_seconds()))
            logger.info("视频时间纠偏(晚于创建,改用视频录制时间): %s -> %s", ts, vt)
            return vt.strftime("%Y-%m-%d %H:%M:%S")
        return ts

    # 与视频录制时间相差 >2 小时：以录制时间为准（OCR 读到的可能是界面里的旧时钟）
    if video_dts:
        vt = min(video_dts, key=lambda v: abs((v - dt).total_seconds()))
        if abs((vt - dt).total_seconds()) > 3600 and vt <= created + timedelta(minutes=1):
            logger.info("视频时间纠偏(与录制时间差>2h): %s -> %s", ts, vt)
            return vt.strftime("%Y-%m-%d %H:%M:%S")

    if (not refs) and (not video_dts) and dt.date() != created.date() and abs(created - dt) <= timedelta(days=3):
        cand = dt.replace(year=created.year, month=created.month, day=created.day)
        if cand <= created + timedelta(minutes=1):
            logger.info("视频时间纠偏(无日期参照,改用创建日): %s -> %s", ts, cand)
            return cand.strftime("%Y-%m-%d %H:%M:%S")
    return ts


def _diag_extract_time_from_video_simple(issue: dict, stop_event=None) -> str:
    """视频提取入口（带创建时间纠偏）"""
    ts = _diag_extract_time_from_video_simple_impl(issue, stop_event=stop_event)
    try:
        return _fix_video_time_against_created(issue, ts)
    except Exception as e:
        logger.warning("视频时间纠偏失败: %s", e)
        return ts


def _diag_extract_time_from_video_simple_impl(issue: dict, stop_event=None) -> str:
    """视频帧 OCR 提取触发时间，多视频按优先级逐个尝试，命中即停。

    支持本地缓存：每个视频提取结果保存到 data/video_time_cache.json，
    避免重复下载和 OCR。缓存命中时直接使用已提取时间进行匹配。

    :param stop_event: 可选的 threading.Event，设置后中断提取
    """
    import tempfile
    import shutil
    import httpx as _httpx
    import time as _time
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
    # 1. 解析 gmlogger 压缩包文件名时间（不解压，外层日期）
    gm_times = _diag_gmlogger_times(attachments)
    # 2. 直接上传的 main.log 文件（已解压，内层日期）
    _inner_times = []
    for att in attachments:
        fname = att.get("filename", "") or ""
        bname = os.path.basename(fname).lower()
        # 跳过 gmlogger 压缩包（已在步骤1处理）和视频/图片
        if "gmlogger" in fname.lower():
            continue
        if not bname.endswith((".log", ".txt")):
            continue
        if "main" not in bname:
            continue
        parsed = _diag_parse_entry_time(fname)
        if parsed:
            _inner_times.append(parsed)
            logger.info("视频兜底提取(%s)：直接上传的 main 文件: %s -> %s", bugid, fname, parsed[0])
    # 3. 非 gmlogger 且非 main 的压缩包：解压探测包内 main 文件（场景三）
    #    如果已有 gmlogger 文件名时间（三个文件日期一致），无需再解压确认
    _skip_archive_probe = bool(gm_times)
    if _skip_archive_probe:
        logger.info("视频兜底提取(%s)：已有 %d 个 gmlogger 文件名时间，跳过压缩包探测", bugid, len(gm_times))
    cfg = load_config().get("jira_api", {})
    _timeout = max(int(cfg.get("timeout", 30)), 120)
    headers = {}
    token = cfg.get("token", "")
    if token:
        auth_type = cfg.get("auth_type", "bearer").lower()
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {token}"
    if not _skip_archive_probe:
        for att in attachments:
            fname = att.get("filename", "") or ""
            fn_lower = fname.lower()
            # 跳过非压缩包
            if not _ARCHIVE_NAME_RE.search(fn_lower):
                continue
            # 跳过分卷
            if _SPLIT_ARCHIVE_RE.search(fn_lower):
                continue
            # 跳过超大包
            if att.get("size", 0) and att["size"] > _ARCHIVE_PROBE_MAX_BYTES:
                continue
            res = _diag_list_archive_entries(att.get("content", ""), headers, _timeout, bugid, filename=att.get("filename", ""))
            if not res.get("ok"):
                continue
            for entry in res.get("entries", []):
                ebname = os.path.basename(entry).lower()
                if "main" not in ebname:
                    continue
                parsed = _diag_parse_entry_time(entry)
                # 兆底：下划线分隔格式 main.log_2026_10_19_6_56_11.gz（小时可为 1-2 位）
                if not parsed:
                    import re as _re
                    _m = _re.search(r"(20\d{2})_(\d{1,2})_(\d{1,2})_(\d{1,2})_(\d{1,2})(?:_(\d{1,2}))?", entry)
                    if _m:
                        from datetime import datetime as _dt_inner
                        try:
                            _y, _mo, _d = int(_m.group(1)), int(_m.group(2)), int(_m.group(3))
                            _h, _mi = int(_m.group(4)), int(_m.group(5))
                            _s = int(_m.group(6)) if _m.group(6) else 0
                            _idt = _dt_inner(_y, _mo, _d, _h, _mi, _s)
                            parsed = (_idt.strftime("%Y-%m-%d %H:%M:%S"), _idt)
                        except (ValueError, IndexError):
                            pass
                if parsed:
                    _inner_times.append(parsed)
                    logger.info("视频兜底提取(%s)：压缩包 %s 内 main 文件: %s -> %s",
                                bugid, fname, entry, parsed[0])
    # 构建 ref_pool
    gm_dates = [(dt.year, dt.month, dt.day) for _, dt in gm_times]
    ref_pool = [dt for _, dt in gm_times]
    _has_inner_dates = False
    if _inner_times:
        _has_inner_dates = True
        for ts, dt in _inner_times:
            d = (dt.year, dt.month, dt.day)
            if d not in gm_dates:
                gm_dates.append(d)
            if dt not in ref_pool:
                ref_pool.append(dt)
        logger.info("视频兜底提取(%s)：内层 main 日期 %d 个", bugid, len(_inner_times))
    _timestudy_update_ctx(bugid, gm_count=len(gm_times) + len(_inner_times),
                          ref_times="|".join(str(dt) for _, dt in (gm_times + _inner_times)[:3]))
    _timestudy_trace(bugid, f"gm:{len(gm_times)}+inner:{len(_inner_times)}")
    # 构建 gmlogger 详细信息（用于智能匹配视频）
    gm_info_list = _build_gmlogger_info(attachments)
    gm_ref_dt = None
    for att in attachments:
        fname = att.get("filename", "") or ""
        if fname and "gmlogger" in fname.lower():
            gm_ref_dt = _ts_parse_datetime(att.get("created", ""))
            break
    # 统一去除时区信息，避免与 naive datetime 比较异常
    if gm_ref_dt and gm_ref_dt.tzinfo is not None:
        gm_ref_dt = gm_ref_dt.replace(tzinfo=None)
    # 注意：gmlogger 上传时间 ≠ 事件时间，禁止写入 ref_pool。
    # 否则“日期取上传日”的候选会被当成验证通过（曾把 10-19 的事件算成 10-27）。
    # 按优先级排序视频
    ranked_videos = _rank_videos(videos, attachments, created_dt=_issue_created_dt(issue))
    single_video = len(ranked_videos) == 1
    # 匹配容差：内层日期（main文件）可用时 5 分钟，仅外层文件名日期时 10 分钟
    if not ref_pool:
        logger.info("视频兜底提取(%s)：gmlogger 和内层均无日期，仍尝试视频OCR（无参考日期校验）", bugid)
    _match_tolerance = 300 if _has_inner_dates else 600
    logger.info("视频兜底提取(%s)：ref_pool %d 个（外层 %d + 内层 %d），匹配容差 %ds",
                bugid, len(ref_pool), len(gm_times), len(_inner_times), _match_tolerance)
    best_partial = ""
    # 12h 制兜底候选（延迟决策）
    best_12h_cand = None  # (time_str, ext_dt)
    best_12h_diff = float("inf")
    for vi, video_att in enumerate(ranked_videos):
        if stop_event and stop_event.is_set():
            logger.info("视频兜底提取(%s)：收到停止信号，中断视频提取", bugid)
            return ""
        video_url = video_att.get("content", "")
        video_name = video_att.get("filename", "")
        if not video_url:
            continue
        _full_start = _VIDEO_OCR_STATS["full_frames"]
        _roi_start = _VIDEO_OCR_STATS["roi_frames"]
        _skip_start = _VIDEO_OCR_STATS["skipped_frames"]
        _vote_start = _VIDEO_OCR_STATS["vote_hits"]
        ts = None  # 初始化：避免 OCR/文件名解析均未命中时 UnboundLocalError
        video_label = f"{bugid} [{vi+1}/{len(ranked_videos)}] {video_name}"
        # 为当前视频找到最接近的 gmlogger（按接近度排序 ref_pool）
        closest_gm = _find_closest_gmlogger(video_att, gm_info_list)
        # 按接近度构建 ref_pool：最近的排前面
        if closest_gm:
            close_refs = []
            for gm in closest_gm:
                if gm["filename_time"]:
                    close_refs.append(gm["filename_time"])
            # 最近的在前 + 其余补充
            video_ref_pool = close_refs + [dt for dt in ref_pool if dt not in close_refs]
            closest_name = closest_gm[0]["filename"]
            logger.info("视频 %s 最近 gmlogger: %s", video_label, closest_name)
        else:
            video_ref_pool = ref_pool
        # 同期性约束：视频文件名带完整日期时间时，只接受与之相差 ≤6h 的日志包参考。
        # 否则说明这个视频是“事后复现”，与日志包不是同一时段，不能拿来当触发时间。
        _vfn_str = _parse_video_filename_datetime(video_name)
        if _vfn_str:
            _vfn_parsed = _parse_datetime_string(_vfn_str)
            if _vfn_parsed:
                _vfn_dt = _vfn_parsed[1]
                _same_period = [dt for dt in video_ref_pool
                                if abs((dt - _vfn_dt).total_seconds()) <= 6 * 3600]
                if _same_period:
                    video_ref_pool = _same_period
                else:
                    logger.info("视频兜底提取(%s)：视频 %s 与日志包参考相差超过 6 小时，跳过该视频",
                                bugid, video_label)
                    _timestudy_trace(bugid, "video:out_of_period")
                    continue
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
                    if any(abs((dt - ext_dt).total_seconds()) <= _match_tolerance for dt in video_ref_pool):
                        logger.info("视频兜底命中(%s, 缓存+重合): %s", video_label, ts)
                        _timestudy_update_ctx(bugid, source="video_ocr")
                        _timestudy_trace(bugid, "cache:hit")
                        return ts
                    # 缓存时间未通过日志包校验：不再当部分结果（旧逻辑会把错误日期带出来）
                continue  # 缓存无时间，也跳过处理
        # 下载视频（流式下载，避免一次性加载到内存）
        video_path = None
        tmp_dir = None
        try:
            logger.info("视频兜底提取：开始下载视频 %s%s", video_label,
                        "（单视频）" if single_video else "")
            tmp_dir = tempfile.mkdtemp()
            video_path = os.path.join(tmp_dir, "video.bin")
            _VFB_DL_DEADLINE = 180  # 单个视频下载上限 3 分钟
            # 统一走附件守卫：字节上限 + 磁盘水位 + 预算记账 + 可取消/超时
            _stream_download(video_url, headers, video_path, timeout=120, bugid=bugid,
                             max_bytes=_MAX_MEDIA_BYTES, filename="video.bin",
                             use_cache=False, stop_event=stop_event,
                             deadline_seconds=_VFB_DL_DEADLINE)
            logger.info("视频兜底提取：下载完成 %s", video_label)
            _timestudy_trace(bugid, "dl:ok")
        except Exception as e:
            logger.warning("视频兜底提取：下载失败 %s: %s", video_label, e)
            _timestudy_update_ctx(bugid, error_type="video_download_failed",
                                  error_detail=f"{video_name}: {e}")
            _timestudy_trace(bugid, "dl:fail")
            continue
        if not video_path or not os.path.exists(video_path):
            logger.warning("视频兜底提取：视频文件不存在 %s", video_label)
            continue
        try:
            # 步骤1：一次性截帧：0~8 秒每秒 1 帧 + 10/15 秒兜底帧
            # 依据 2026-10-27 实测：时钟最晚在第 5 秒出现，且单帧 OCR 不稳定（相邻帧时有时无）
            video_positions = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 15]
            frames = _extract_video_frames_gpu(video_path, positions=video_positions, use_gpu=True) or []
            if not frames:
                logger.warning("视频兜底提取：无法提取视频帧 %s，尝试下一个", video_label)
                _timestudy_trace(bugid, "frame:fail")
                continue
            first_full = ""
            first_partial = ""
            _VIDEO_OCR_STATS["videos"] += 1
            _collected_texts = []  # [(sec, text)] 供循环结束后投票（复用已 OCR 文本）
            for _phase in [0]:
                if True:
                    logger.info("视频兜底提取(%s)：截取 %d 帧（0~8s 每秒 + 10/15s 兜底）",
                                video_label, len(frames))
                
                _prev_sig = None
                for sec, frame in frames:
                    # 静帧跳过：与上一帧几乎相同就不重复 OCR（静态画面常见）
                    _sig = _frame_signature(frame)
                    if _prev_sig is not None and _same_frame(_sig, _prev_sig):
                        _VIDEO_OCR_STATS["skipped_frames"] += 1
                        logger.debug("视频兜底提取(%s)：第%d秒与上一帧相同，跳过 OCR", video_label, sec + 1)
                        continue
                    _prev_sig = _sig
                    # 整帧 OCR 优先；整帧没读到时间时再用状态栏/任务栏 ROI 兜底
                    try:
                        results = _ocr_readtext(None, frame) or []
                    except Exception as e:
                        logger.warning("视频兜底提取(%s)：OCR 第%d秒失败: %s", video_label, sec, e)
                        continue
                    all_text = " ".join(r[1] for r in results)
                    _has_time = bool(all_text) and bool(
                        _OCR_TIME_FULL_RE.search(all_text) or _OCR_TIME_ONLY_RE.search(all_text))
                    _roi_has_time = False
                    if not _has_time:
                        try:
                            _roi_text = _ocr_frame_regions(frame) or ""
                        except Exception:
                            _roi_text = ""
                        if _roi_text:
                            all_text = f"{_roi_text} {all_text}"
                            _roi_has_time = bool(
                                _OCR_TIME_FULL_RE.search(_roi_text) or _OCR_TIME_ONLY_RE.search(_roi_text))
                    _VIDEO_OCR_STATS["roi_frames" if _roi_has_time else "full_frames"] += 1
                    _collected_texts.append((sec, all_text))
                    # 诊断日志：打印 OCR 实际读到的原文
                    logger.info("视频兜底提取(%s)：第%d秒 OCR 原文: %s", video_label, sec + 1, (all_text[:120] or "(空)"))
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
                            if any(abs((dt - ext_dt).total_seconds()) <= _match_tolerance for dt in video_ref_pool):
                                logger.info("视频兜底命中(%s, 时间戳重合): %s (第%d秒)",
                                            video_label, ts, sec + 1)
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
                                    if parsed2 and any(abs((dt - parsed2[1]).total_seconds()) <= _match_tolerance for dt in video_ref_pool):
                                        logger.info("视频兜底命中(%s, 纠正+包内重合): %s -> %s", video_label, ts, ts2)
                                        cache[cache_key] = {"time": ts2, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                        _save_video_time_cache()
                                        return ts2
                                    ts = ts2
                            # 12h 制候选（完整日期+时间）
                            if ext_dt.hour < 12:
                                dt_alt = ext_dt + timedelta(hours=12)
                            else:
                                dt_alt = ext_dt - timedelta(hours=12)
                            ts_alt = dt_alt.strftime("%Y-%m-%d %H:%M:%S")
                            orig_match = any(abs((dt - ext_dt).total_seconds()) <= _match_tolerance for dt in video_ref_pool)
                            alt_match = any(abs((dt - dt_alt).total_seconds()) <= _match_tolerance for dt in video_ref_pool)
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
                    # 仅时间+日期补充：日期只能来自日志包（gmlogger），禁止用视频上传时间
                    m = _OCR_TIME_ONLY_RE.search(all_text)
                    closest_date = None
                    if not closest_date and closest_gm and closest_gm[0]["filename_time"]:
                        closest_date = (closest_gm[0]["filename_time"].year,
                                        closest_gm[0]["filename_time"].month,
                                        closest_gm[0]["filename_time"].day)
                    if not closest_date and gm_dates:
                        closest_date = gm_dates[0]
                    if m:
                        time_str = _normalize_ocr_time(m.group(1))
                        # 多级验证：检查视频自身文件名是否含完整日期时间且时间匹配
                        _vid_fn_dt_str = _parse_video_filename_datetime(video_name)
                        if _vid_fn_dt_str:
                            _vid_fn_parsed = _parse_datetime_string(_vid_fn_dt_str)
                            if _vid_fn_parsed:
                                _vid_fn_ts, _vid_fn_dt = _vid_fn_parsed
                                _ocr_hm = time_str[:5]
                                _fn_hm = _vid_fn_dt.strftime("%H:%M")
                                _fn_verified = (not video_ref_pool) or any(
                                    abs((dt - _vid_fn_dt).total_seconds()) <= _match_tolerance
                                    for dt in video_ref_pool)
                                if (_ocr_hm == _fn_hm or (len(time_str) >= 8 and _vid_fn_dt.strftime("%H:%M:%S") == time_str[:8])) and _fn_verified:
                                    logger.info("视频兜底命中(%s, 视频文件名日期+OCR时间多级确认): %s", video_label, _vid_fn_dt_str)
                                    cache[cache_key] = {"time": _vid_fn_dt_str, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                    _save_video_time_cache()
                                    _timestudy_update_ctx(bugid, source="video_ocr+filename")
                                    _timestudy_trace(bugid, "vid_fn:hit")
                                    return _vid_fn_dt_str
                        _corr_ref = (closest_gm[0]["filename_time"] if closest_gm and closest_gm[0]["filename_time"] else gm_ref_dt)
                        if _corr_ref:
                            time_str = _correct_ocr_by_reference(time_str, _corr_ref)
                        if closest_date:
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
                                orig_match = any(abs((dt - ext_dt).total_seconds()) <= _match_tolerance for dt in video_ref_pool)
                                alt_match = any(abs((dt - dt_alt).total_seconds()) <= _match_tolerance for dt in video_ref_pool)
                                gm_orig = gm_ref_dt and abs((gm_ref_dt - ext_dt).total_seconds()) <= _match_tolerance
                                gm_alt = gm_ref_dt and abs((gm_ref_dt - dt_alt).total_seconds()) <= _match_tolerance
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
                                if not (orig_match or gm_orig) and not (alt_match or gm_alt) and video_ref_pool:
                                    d_orig = min(abs((dt.hour * 3600 + dt.minute * 60 + dt.second) - (ext_dt.hour * 3600 + ext_dt.minute * 60 + ext_dt.second)) for dt in video_ref_pool)
                                    d_alt = min(abs((dt.hour * 3600 + dt.minute * 60 + dt.second) - (dt_alt.hour * 3600 + dt_alt.minute * 60 + dt_alt.second)) for dt in video_ref_pool)
                                    if d_alt < d_orig and d_alt < best_12h_diff:
                                        best_12h_diff = d_alt
                                        best_12h_cand = (ts_alt, dt_alt)
                                    elif d_orig < best_12h_diff:
                                        best_12h_diff = d_orig
                                        best_12h_cand = (ts, ext_dt)
                                if ts and not first_partial:
                                    first_partial = ts
            # 循环结束仍未命中：用已 OCR 文本做多帧投票（同一时间 ≥2 次且通过校验才采用）
            if not first_full and not first_partial and _collected_texts:
                try:
                    _vote_ts, _vote_n = _vote_from_texts(_collected_texts, video_ref_pool, gm_ref_dt, _match_tolerance)
                except Exception:
                    _vote_ts, _vote_n = "", 0
                if _vote_ts:
                    logger.info("视频兜底命中(%s, 多帧投票%d票): %s", video_label, _vote_n, _vote_ts)
                    cache[cache_key] = {"time": _vote_ts, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                    _save_video_time_cache()
                    _timestudy_trace(bugid, "vote:hit")
                    _VIDEO_OCR_STATS["vote_hits"] += 1
                    return _vote_ts

            # OCR 完全失败时，尝试从视频文件名提取时间（回退方案）
            if not first_full and not first_partial:
                _timestudy_trace(bugid, "fn:try")
                fn_time = _parse_video_filename_time(video_name)
                if fn_time:
                    # 日期补充：只能用日志包日期（gmlogger），禁止用视频上传时间
                    closest_date = None
                    if not closest_date and closest_gm and closest_gm[0]["filename_time"]:
                        closest_date = (closest_gm[0]["filename_time"].year,
                                        closest_gm[0]["filename_time"].month,
                                        closest_gm[0]["filename_time"].day)
                    if not closest_date and gm_dates:
                        closest_date = gm_dates[0]
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
                            orig_match = any(abs((dt - ext_dt).total_seconds()) <= _match_tolerance for dt in video_ref_pool)
                            alt_match = any(abs((dt - dt_alt).total_seconds()) <= _match_tolerance for dt in video_ref_pool)
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
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
    # 保存缓存（所有视频处理完后统一保存）
    if cache_updated:
        _save_video_time_cache()
    # 视频未命中 gmlogger → 图片 OCR 兜底
    img_ts = _image_fallback_time(issue, headers, _timeout, bugid, ref_pool)
    if img_ts:
        _timestudy_update_ctx(bugid, source="image_ocr")
        _timestudy_trace(bugid, "image:fallback")
        return img_ts
    # 12h 制兜底
    if best_12h_cand and best_12h_diff <= _match_tolerance:
        cand_time, cand_dt = best_12h_cand
        logger.info("视频兜底提取(%s, 12h兜底): 使用 12h 候选 %s（差值 %.0f 秒）", bugid, cand_time, best_12h_diff)
        _timestudy_update_ctx(bugid, source="video_ocr", h12="yes", match_diff=str(int(best_12h_diff)))
        _timestudy_trace(bugid, "12h:fallback")
        return cand_time
    if best_12h_cand:
        logger.info("视频兜底提取(%s)：12h 候选 %s 差值 %.0f 秒超过容差 %d，丢弃",
                    bugid, best_12h_cand[0], best_12h_diff, _match_tolerance)
    # 未通过日志包校验的候选一律不返回，交由文本提取兜底（避免把错误日期写进触发时间）
    if best_partial:
        logger.info("视频兜底提取(%s)：候选 %s 未通过日志包校验，丢弃", bugid, best_partial)
        _timestudy_update_ctx(bugid, error_type="time_no_match_gmlogger",
                              error_detail=f"未通过日志包校验: {best_partial}")
        _timestudy_trace(bugid, "partial:rejected")
    logger.info("视频兜底提取(%s)：所有视频封面及前6帧均未识别到时间", bugid)
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
    import time as _time
    from datetime import datetime as _dt, timedelta
    fields = issue.get("fields") or {}
    attachments = fields.get("attachment") or []
    videos = [a for a in attachments if (a.get("filename", "") or "").lower().endswith(_VIDEO_SUFFIXES)]
    if not videos:
        return "", ""
    # 确定验证池和容忍度
    if ref_pool:
        # 已解压：使用包内时间戳，±5分钟严格匹配
        # ref_pool 元素为 (str, datetime) 元组，仅取 datetime 参与校验
        validation_pool = [dt for _, dt in ref_pool]
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
    ranked_videos = _rank_videos(videos, attachments, created_dt=_issue_created_dt(issue))
    single_video = len(ranked_videos) == 1
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
    # OCR 统计基线初始化（避免 finally 中引用未定义变量）
    _full_start = _roi_start = _skip_start = _vote_start = 0
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
                    # 缓存时间未通过日志包校验：不再当部分结果
            continue  # 缓存无时间，也跳过处理
        # 下载视频（流式下载，避免一次性加载到内存）
        video_path = None
        tmp_dir = None
        # 记录当前视频开始时的 OCR 统计基线（用于 finally 中计算本视频增量）
        _full_start = _VIDEO_OCR_STATS["full_frames"]
        _roi_start = _VIDEO_OCR_STATS["roi_frames"]
        _skip_start = _VIDEO_OCR_STATS["skipped_frames"]
        _vote_start = _VIDEO_OCR_STATS["vote_hits"]
        try:
            # 下载子块：单独捕获下载异常，失败则跳过当前视频（临时目录由外层 finally 统一清理）
            try:
                logger.info("视频帧提取：开始下载视频 %s%s", video_label,
                            "（单视频）" if single_video else "")
                tmp_dir = tempfile.mkdtemp()
                video_path = os.path.join(tmp_dir, "video.bin")
                _VID_DL_DEADLINE = 180  # 单个视频下载上限 3 分钟
                # 统一走附件守卫：字节上限 + 磁盘水位 + 预算记账 + 超时
                _stream_download(video_url, headers, video_path, timeout=timeout, bugid=bugid,
                                 max_bytes=_MAX_MEDIA_BYTES, filename="video.bin",
                                 use_cache=False, deadline_seconds=_VID_DL_DEADLINE)
                logger.info("视频帧提取：下载完成 %s", video_label)
            except TimeoutError as e:
                logger.warning("视频帧提取：下载超时 %s: %s", video_name, e)
                continue  # 超时跳过，尝试下一个视频
            except Exception as e:
                logger.warning("视频帧提取：下载失败 %s: %s", video_name, e)
                continue  # 下载失败，尝试下一个视频
            if not video_path or not os.path.exists(video_path):
                logger.warning("视频帧提取：视频文件不存在 %s", video_label)
                continue
            # 截帧 + OCR：先封面，再第2~6秒
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
                    other_frames = _extract_video_frames_gpu(video_path, positions=[1, 2, 3, 4, 5], use_gpu=True) or []
                    if not other_frames:
                        break
                    frames = other_frames
                    logger.info("视频帧提取：封面未识别到时间，继续截取前6帧")
                
                for sec, frame in frames:
                    try:
                        results = _ocr_readtext(None, frame)
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
                    # 仅时间（无日期），优先用视频文件名日期补充，再用 gmlogger 文件名日期补充，延迟 12h 决策
                    m = _OCR_TIME_ONLY_RE.search(all_text)
                    if m:
                        time_str = _normalize_ocr_time(m.group(1))
                        # 优先检查视频自身文件名是否含完整日期时间且时间匹配
                        _vid_fn_dt_str = _parse_video_filename_datetime(video_name)
                        if _vid_fn_dt_str:
                            _vid_fn_parsed = _parse_datetime_string(_vid_fn_dt_str)
                            if _vid_fn_parsed:
                                _vid_fn_ts, _vid_fn_dt = _vid_fn_parsed
                                # 视频文件名时间与 OCR 时间一致（容差 1 分钟）
                                _ocr_hm = time_str[:5]  # HH:MM
                                _fn_hm = _vid_fn_dt.strftime("%H:%M")
                                _fn_verified = (not validation_pool) or any(
                                    abs((dt - _vid_fn_dt).total_seconds()) <= strict_tol
                                    for dt in validation_pool)
                                if (_ocr_hm == _fn_hm or (len(time_str) >= 5 and _vid_fn_dt.strftime("%H:%M:%S") == time_str[:8])) and _fn_verified:
                                    detail = f"从视频{video_label}第{sec+1}秒 OCR 识别到 {time_str}，视频文件名含 {_vid_fn_dt_str}，时间完全匹配"
                                    logger.info("视频帧提取命中(视频文件名日期+OCR时间): %s", _vid_fn_dt_str)
                                    cache[cache_key] = {"time": _vid_fn_dt_str, "extracted_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")}
                                    _save_video_time_cache()
                                    return _vid_fn_dt_str, detail
                        # 参照 gmlogger 时间纠正数字混淆
                        if gm_ref_dt:
                            time_str = _correct_ocr_by_reference(time_str, gm_ref_dt)
                        # 用 gmlogger 日期补充，延迟 12h 决策
                        if gmlogger_dates:
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
            # 每视频统计：便于观察 ROI/投票是否真的有价值（连续几天 roi_frames 恒为 0 就可以删 ROI）
            logger.info("视频 OCR 统计(%s): 整帧帧=%d ROI帧=%d 跳过帧=%d 投票命中=%d",
                        video_name,
                        max(0, _VIDEO_OCR_STATS["full_frames"] - _full_start),
                        max(0, _VIDEO_OCR_STATS["roi_frames"] - _roi_start),
                        max(0, _VIDEO_OCR_STATS["skipped_frames"] - _skip_start),
                        max(0, _VIDEO_OCR_STATS["vote_hits"] - _vote_start))
            # 统一清理临时目录：无论成功、失败、命中返回还是 continue，都删除下载的视频文件
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
    if cache_updated:
        _save_video_time_cache()
    # 所有候选（15min~1h fallback / 12h / 完整时间 / 部分时间）都必须通过日志包校验才返回，
    # 否则交给文本提取兜底，避免把错误日期或错误时钟当成触发时间。
    if fallback_candidate:
        logger.info("视频帧提取：候选 %s 未在容差内命中，丢弃（差值 %.0f 秒）", fallback_candidate, fallback_diff)
    if best_12h_cand:
        logger.info("视频帧提取：12h 候选 %s 未在容差内命中，丢弃（差值 %.0f 秒）", best_12h_cand[0], best_12h_diff)
    if best_full:
        logger.info("视频帧提取：完整时间候选 %s 未通过校验，丢弃", best_full)
    if best_partial:
        logger.info("视频帧提取：部分时间候选 %s 未通过校验，丢弃", best_partial)
    return "", ""


def _diag_extract_time_from_images(issue: dict, headers: dict, timeout: int, bugid: str = "", stop_event=None) -> tuple:
    """从图片附件 OCR 提取触发时间，返回 (time_str, detail) 或 ("", "")

    优先级：
    1. 标记检测：某时间戳文字颜色与周围文字显著不同（红/绿色调）或位置独立（大字号/独立区域）
    2. 频率兆底：统计所有图片提取的时间，取出现次数最多的
    图片数量上限 5 张，按创建时间倒序取最新。
    """
    import tempfile
    import httpx as _httpx
    import cv2
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
    # 收集所有提取的时间
    all_times = []       # [(time_str, datetime, is_marked, image_name)]
    marked_time = None   # 标记检测命中的时间
    with tempfile.TemporaryDirectory() as tmp:
        for att in images:
            if stop_event and stop_event.is_set():
                logger.info("%s图片 OCR: 收到停止信号，中断", bugid)
                return "", ""
            fname = att.get("filename", "") or ""
            img_path = os.path.join(tmp, fname)
            logger.info("%s图片 OCR: 处理 %s", f"{bugid} " if bugid else "", fname)
            try:
                # 下载图片（附件守卫：字节上限 + 磁盘水位 + 预算 + 可取消）
                _stream_download(att.get("content", ""), headers, img_path, timeout=timeout,
                                 bugid=bugid, max_bytes=_MAX_MEDIA_BYTES,
                                 filename=fname or "image.bin", use_cache=False,
                                 stop_event=stop_event)
                # OCR 识别（返回 bbox + 文字 + 置信度）
                img = cv2.imread(img_path)
                if img is None:
                    logger.warning("%s图片 OCR: cv2.imread 失败 %s", f"{bugid} " if bugid else "", fname)
                    continue
                results = _ocr_readtext(None, img)
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
                # 提取相对日期 + 时间（昨天/今天/前天 + HH:MM）
                # 参考日期：优先用附件上传时间，其次用 bug 创建时间
                _ref_date = None
                att_created = att.get("created", "") or ""
                if att_created:
                    try:
                        _ref_date = _dt.strptime(att_created[:10], "%Y-%m-%d").date()
                    except Exception:
                        pass
                if not _ref_date:
                    _ref_date = _dt.now().date()
                for m in _OCR_RELATIVE_DATE_TIME_RE.finditer(full_text):
                    rel_word, time_str = m.group(1), m.group(2)
                    time_str = time_str.replace(",", ":").replace(";", ":").replace(".", ":")
                    try:
                        parts = time_str.split(":")
                        hh, mm = int(parts[0]), int(parts[1])
                        ss = int(parts[2]) if len(parts) > 2 else 0
                        offset = {"今天": 0, "昨天": -1, "前天": -2, "大前天": -3}.get(rel_word, 0)
                        from datetime import timedelta as _td
                        target_date = _ref_date + _td(days=offset)
                        parsed_dt = _dt(target_date.year, target_date.month, target_date.day, hh, mm, ss)
                        full_ts = parsed_dt.strftime("%Y-%m-%d %H:%M:%S")
                        times_found.append((full_ts, parsed_dt))
                        logger.info("%s图片 OCR 相对日期解析: %s %s -> %s", f"{bugid} " if bugid else "", rel_word, time_str, full_ts)
                    except Exception:
                        pass
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


def _build_simple_detail(comment_time: str, video_time: str, img_time_str: str, final_result: str) -> str:
    """生成简洁的4行格式诊断详情"""
    lines = []
    if comment_time:
        lines.append(f"评论提取到：{comment_time}")
    if video_time:
        lines.append(f"视频提取到：{video_time}")
    if img_time_str:
        lines.append(f"图片提取到：{img_time_str}")
    lines.append(f"最终结果：{final_result}")
    return "\n".join(lines)


def _diag_verify_suggestion(issue: dict, gm_times: list, archive_results: list, main_times: list = None,
                            all_times: list = None, headers: dict = None, att_timeout: int = 60) -> tuple:
    """触发时间修正链路：先用已有时间提取工具提取新时间（评论区优先），再用 gmlogger 包内时间戳验证，返回 (verify_status, suggested_time, verify_detail, vid_time)

    验证池：包内全部时间戳（main 文件 + 全部条目文件名），任一与提取时间前后5分钟命中即验证通过。
    gmlogger 外侧文件名时间不准，不参与权威判定，仅作备注参考。
    vid_time: 视频 OCR 实际提取到的时间（即使未通过验证也返回，用于诊断详情展示）
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
                    return "success", extracted, f"提取时间 {extracted}（评论区优先）在 gmlogger 包内前后5分钟有对应时间戳({s})，可用该时间作为替换", ""
        # 包内时间戳存在但提取时间未命中：尝试视频帧 OCR 兜底
        if headers:
            gm_dates = [(dt.year, dt.month, dt.day) for _, dt in (gm_times or [])]
            gm_ref_dt = gm_times[0][1] if gm_times else None
            vid_time, vid_detail = _diag_extract_time_from_video(issue, headers, att_timeout, gm_dates, ref_pool, gm_ref_dt, gm_times)
            if vid_time:
                return "success", vid_time, f"视频帧 OCR 兜底: {vid_detail}", vid_time
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
                                      f"视频提取也未命中。包内最近时间戳为 {best_s}，请人工确认是否正确{gm_note}"), ""
        return "manual", "", (f"提取时间 {extracted or '(未提取到)'} 与包内时间戳前后5分钟均未命中，"
                              f"待人工审核正确的时间{gm_note}"), ""
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
                    f"视频提取时间 {vid_time}，{vid_detail}"), vid_time
            # 评论区提取时间与 gmlogger 文件名时间接近 → 可用
            if ext_dt and abs((gm_ref_dt - ext_dt).total_seconds()) <= 900:
                return "success", extracted, (
                    f"gmlogger 包内无法解析，提取时间 {extracted}（来自评论区/标题/描述/字段）"
                    f"与 gmlogger 文件名时间 {gm_times[0][0]} 前后15分钟内命中，可用该时间作为替换"), vid_time or ""
            # 视频时间与提取时间接近 → 互相印证（用视频时间，因为有 12h 转换）
            if vid_dt and ext_dt and abs((vid_dt - ext_dt).total_seconds()) <= 900:
                return "success", vid_time, (
                    f"gmlogger 包内无法解析，视频时间 {vid_time} 与提取时间 {extracted}（来自评论区/标题/描述/字段）接近，交叉印证可用"), vid_time
            # 视频时间存在但与任何源都不接近 → 参考建议
            if vid_time:
                return "manual", vid_time, (
                    f"gmlogger 包内无法解析（文件过大/解压失败），"
                    f"视频提取时间 {vid_time}，gmlogger 文件名时间 {gm_times[0][0]}，"
                    f"提取时间 {extracted or '(无)'}（来自评论区/标题/描述/字段），三者未命中，待人工审核{gm_note}"), vid_time
        # 无视频或视频提取失败：仅用提取时间与 gmlogger 文件名时间对比
        if ext_dt and abs((gm_ref_dt - ext_dt).total_seconds()) <= 3600:
            return "success", extracted, (
                f"gmlogger 包内无法解析，提取时间 {extracted}（来自评论区/标题/描述/字段）"
                f"与 gmlogger 文件名时间 {gm_times[0][0]} 前后60分钟内接近，可用该时间作为替换{gm_note}"), ""
        return "manual", "", (
            f"gmlogger 包内无法解析（文件过大/解压失败），"
            f"提取时间 {extracted or '(未提取到)'}（来自评论区/标题/描述/字段），gmlogger 文件名时间 {gm_times[0][0]}，"
            f"未能交叉印证，待人工审核正确的时间{gm_note}"), ""
    if ext_dt:
        for arc in archive_results:
            for n in arc.get("entries", []):
                if "main.log" not in os.path.basename(n).lower():
                    continue
                if _diag_match_time_window(os.path.basename(n), extracted, 5)[0]:
                    return "success", extracted, f"提取时间 {extracted} 在解压文件[{os.path.basename(n)}]前后5分钟内有对应文件，可用该时间作为替换", ""
        total_main_log = sum(1 for a in archive_results for n in a.get("entries", []) if "main.log" in os.path.basename(n).lower())
        if total_main_log == 0:
            return "success", extracted, f"无可用 main.log 文件时间戳验证，直接采纳评论区/描述提取的时间 {extracted}（建议应用后重新分析验证）{gm_note}", ""
        return "manual", "", f"提取时间 {extracted} 在 main.log 文件中前后5分钟内无对应文件，待人工审核正确的时间{gm_note}", ""
    return "manual", "", f"未能提取到新触发时间（评论区/描述/视频均无时间），待人工审核正确的时间{gm_note}", ""


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


def _diag_time_check(issue: dict, candidate: str, gm_times: list = None,
                     main_times: list = None, all_times: list = None,
                     vid_time: str = "", current_time: str = "") -> dict:
    """问题排查：对“建议时间/当前时间”做方向敏感判定，并给出证据链

    :return: {"status": 正常/待确认/不可用/无参考, "ref_time": str, "delta_sec": int|None,
              "need_fix": bool, "evidence": [{"来源","时间","与抓包差秒"}]}
    """
    from src.clients import jira_client as _jc
    from src.services.trigger_ops import self_check_trigger_time
    refs = [dt for _, dt in (main_times or [])] + [dt for _, dt in (all_times or [])]
    # 优先用日志包文件名时间（真正的抓包时刻）；包内时间戳可能是历史轮转日志，不能直接当抓包时间
    try:
        cap = _jc.get_log_capture_time(issue)
    except Exception:
        cap = None
    if cap is None and gm_times:
        cap = max(dt for _, dt in gm_times)
    if cap is None and refs:
        cap = max(refs)
    ref = cap.strftime("%Y-%m-%d %H:%M:%S") if cap else ""
    chk = self_check_trigger_time(candidate, ref)
    evidence = []
    def _add(src_name, t):
        if not t:
            return
        t_str = str(t)[:19]
        if any(e["来源"] == src_name and e["时间"] == t_str for e in evidence):
            return
        d = None
        if cap and _ts_parse_datetime(t_str):
            d = int((_ts_parse_datetime(t_str) - cap).total_seconds())
        evidence.append({"来源": src_name, "时间": t_str, "与抓包差秒": d})
    _add("建议时间", candidate)
    _add("视频OCR", vid_time if vid_time and len(str(vid_time)) >= 16 else "")
    try:
        _add("附件名", _jc.extract_attachment_time(issue))
    except Exception:
        pass
    if cap:
        _add("包内最晚时间戳", ref)
    # 展示用的差值带方向（正=晚于抓包，负=早于抓包）
    def _signed(t):
        if not t or not cap:
            return None
        _dt = _ts_parse_datetime(str(t))
        return int((_dt - cap).total_seconds()) if _dt else None

    signed_delta = _signed(candidate)
    cur_chk = self_check_trigger_time(current_time, ref) if current_time else {}
    cur_delta = _signed(current_time)
    # 建议时间相对当前时间的变化（正=建议更晚）
    change_sec = None
    if current_time and candidate:
        _c = _ts_parse_datetime(str(current_time))
        _n = _ts_parse_datetime(str(candidate))
        if _c and _n:
            change_sec = int((_n - _c).total_seconds())
    return {"status": chk.get("status", "无参考"), "ref_time": ref,
            "delta_sec": signed_delta,
            "need_fix": chk.get("status") == "不可用", "evidence": evidence,
            "current": {"time": str(current_time or "")[:19],
                        "status": cur_chk.get("status", "无参考"),
                        "delta_sec": cur_delta},
            "change_sec": change_sec}


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
    # —— 无报错信息或"服务有报错"的记录不进行排查，直接跳过 ——
    if not err_msg or err_msg == "服务有报错":
        skip_category = "服务关闭"
        report = _generate_troubleshoot_report(bugid, skip_category, err_msg, "")
        result = {"bugid": bugid, "category": skip_category, "problem_time": problem_time,
                  "archive_files": [], "detail": "多维表格记录无错误信息字段，无排查依据，已跳过",
                  "verify_status": "", "suggested_time": "", "report": report, "done_time": done_time}
        _save_diagnose_cache(bugid, result)
        return _ok(result)
    # —— 预归类：无需附件比对即可判定的场景 ——
    pre = _diag_pre_classify(err_msg)
    if pre:
        conn_tip = "" if pre != "服务关闭" else "（建议：确认 AI 日志分析接口内外网可达性后重试）"
        report = _generate_troubleshoot_report(bugid, pre, err_msg, conn_tip)
        result = {"bugid": bugid, "category": pre, "problem_time": problem_time,
                    "archive_files": [], "detail": f"根据失败原因预归类：{pre}{conn_tip}",
                    "verify_status": "", "suggested_time": "", "report": report, "done_time": done_time}
        _save_diagnose_cache(bugid, result)
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


def _extract_trigger_time_with_confidence(issue: dict, attachments: list,
                                          headers: dict = None, att_timeout: int = 120,
                                          bugid: str = "") -> tuple:
    """多源置信度提取触发时间（可复用，供批量提取和诊断共用）

    全量提取所有来源（文本/视频OCR/图片OCR/文件名），交叉验证补全仅时间候选，
    返回置信度最高的时间。

    :return: (best_time, source_label) — best_time 为 "YYYY-MM-DD HH:MM:SS" 或 ""
    """
    from src.clients import jira_client as _jc
    if not _has_gmlogger_logs(attachments, bugid):
        return "", ""
    gm_times = _diag_gmlogger_times(attachments)
    # —— 源1: 视频 OCR ——
    video_time = ""
    gm_dates_for_video = [(dt.year, dt.month, dt.day) for _, dt in gm_times] if gm_times else []
    gm_ref_dt_for_video = gm_times[0][1] if gm_times else None
    if headers:
        _vid_result, _ = _diag_extract_time_from_video(
            issue, headers, att_timeout, gm_dates_for_video, [], gm_ref_dt_for_video, gm_times)
        if _vid_result:
            video_time = _vid_result
    # —— 源2: 图片 OCR ——
    img_time_str = ""
    if headers:
        img_time_str, _ = _diag_extract_time_from_images(issue, headers, att_timeout, bugid)
    # —— A. 收集“日期提供者”——
    _fields = issue.get("fields") or {}
    _created_date = (_fields.get("created") or "")[:10]
    _date_providers = []  # [(datetime, source_label, display_str)]
    _text_time_only_hm = []  # 仅时间 HH:MM
    for _txt_label, _txt_content in [
        ("描述", _fields.get("description") or ""),
        ("标题", _fields.get("summary") or ""),
    ]:
        if not _txt_content:
            continue
        _full_set = {_t for _t, _ in _jc._extract_times_from_text(_txt_content)}
        _full_hm_set = set()
        for _ft in _full_set:
            if len(_ft) >= 16:
                _full_hm_set.add(_ft[11:16])
        for _t, _dt in _jc._extract_times_from_text(_txt_content, date_str=_created_date):
            if _t in _full_set:
                _date_providers.append((_dt, f"文本:{_txt_label}", _t))
            else:
                _hm = _dt.strftime("%H:%M")
                if _hm not in _full_hm_set:
                    _text_time_only_hm.append((_hm, _txt_label))
    # A2: 视频文件名（仅用于与视频OCR时间组合补全，不作为独立候选）
    _vid_fn_date = None  # (year, month, day)
    _vid_fn_dt_str = ""
    _vid_fn_dt = None
    for _att in attachments:
        _fn = _att.get("filename", "") or ""
        if _fn.lower().endswith(_VIDEO_SUFFIXES):
            _vid_fn_dt_str = _parse_video_filename_datetime(_fn)
            if _vid_fn_dt_str:
                _p = _jc._parse_datetime_string(_vid_fn_dt_str)
                if _p:
                    _vid_fn_dt = _p[1]
                    _vid_fn_date = (_vid_fn_dt.year, _vid_fn_dt.month, _vid_fn_dt.day)
            break
    # A2b: 视频上传日期不再参与日期补全（上传日≠事件日，会算错日期）
    # A3: gmlogger 文件名日期时间仅作为兑底，不直接作为日期提供者（已在步骤E处理）
    # A4: 视频 OCR（完整日期）
    if video_time and len(video_time) >= 16:
        _vid_dt = _jc._parse_datetime_string(video_time)
        if _vid_dt:
            _date_providers.append((_vid_dt[1], "视频OCR", video_time))
    # A5: 图片 OCR（完整日期）
    if img_time_str and len(img_time_str) >= 16:
        _img_dt = _jc._parse_datetime_string(img_time_str)
        if _img_dt:
            _date_providers.append((_img_dt[1], "图片OCR", img_time_str))
    # —— B. 收集仅时间候选 ——
    _time_only_candidates = []
    for _hm, _src in _text_time_only_hm:
        _time_only_candidates.append((_hm, f"文本:{_src}"))
    if video_time and len(video_time) <= 8:
        _time_only_candidates.append((video_time[:5], "视频OCR"))
    if img_time_str and len(img_time_str) <= 8:
        _time_only_candidates.append((img_time_str[:5], "图片OCR"))
    # —— C. 补全匹配 ——
    _completed = {}
    def _ensure_key(key):
        if key not in _completed:
            _completed[key] = {"score": 0.0, "sources": [], "confirmations": 0}
    # C1: 日期提供者自身作为候选（基础分 1.0）
    for _dp_dt, _dp_src, _dp_str in _date_providers:
        _k = _dp_dt.strftime("%Y-%m-%d %H:%M")
        _ensure_key(_k)
        _completed[_k]["score"] += 1.0
        if _dp_src not in _completed[_k]["sources"]:
            _completed[_k]["sources"].append(_dp_src)
        _completed[_k]["confirmations"] += 1
    # C2: 仅时间候选匹配日期提供者来补全（视频OCR+视频文件名自洽额外加分）
    for _hm, _hm_src in _time_only_candidates:
        _best_dp_score = 0.0
        _best_dp_key = ""
        for _dp_dt, _dp_src, _dp_str in _date_providers:
            _dp_hm = _dp_dt.strftime("%H:%M")
            _min_diff = abs(int(_hm[:2]) * 60 + int(_hm[3:5]) - (int(_dp_hm[:2]) * 60 + int(_dp_hm[3:5])))
            _min_diff = min(_min_diff, 1440 - _min_diff)
            if _hm == _dp_hm:
                _match_score = 3.0
            elif _min_diff <= 30:
                _match_score = 1.5
            elif _min_diff <= 60:
                _match_score = 0.5
            else:
                continue
            _completed_key = _dp_dt.strftime("%Y-%m-%d") + " " + _hm
            _ensure_key(_completed_key)
            if _match_score > _best_dp_score:
                _best_dp_score = _match_score
                _best_dp_key = _completed_key
            _completed[_dp_dt.strftime("%Y-%m-%d %H:%M")]["confirmations"] += 1
        if _best_dp_key:
            _completed[_best_dp_key]["score"] += _best_dp_score
            _label = f"{_hm_src}+补全"
            if _label not in _completed[_best_dp_key]["sources"]:
                _completed[_best_dp_key]["sources"].append(_label)
            _completed[_best_dp_key]["confirmations"] += 1
    # C3: 视频OCR仅时间 + 视频文件名/上传日期补全（仅作日期补全，不作为独立候选）
    _vid_date_providers = []  # [(date_tuple, label)]
    if _vid_fn_date:
        _vid_date_providers.append((_vid_fn_date, "视频文件名"))
    if _vid_date_providers and _time_only_candidates:
        for _hm, _hm_src in _time_only_candidates:
            if _hm_src != "视频OCR":
                continue
            for (_vy, _vm, _vd), _vdp_label in _vid_date_providers:
                _ck = f"{_vy:04d}-{_vm:02d}-{_vd:02d} {_hm}"
                _ensure_key(_ck)
                # 基础分 2.0 + 匹配分 3.0 + 自洽奖励 2.0
                _completed[_ck]["score"] += 7.0
                if _vdp_label not in _completed[_ck]["sources"]:
                    _completed[_ck]["sources"].append(_vdp_label)
                _label = f"{_hm_src}+{_vdp_label}补全"
                if _label not in _completed[_ck]["sources"]:
                    _completed[_ck]["sources"].append(_label)
                _completed[_ck]["confirmations"] += 2
    # —— D. 选择最终答案 ——
    _best_time = ""
    _best_score = 0.0
    _best_confirm = 0
    _best_sources = []
    for _k, _v in _completed.items():
        if (_v["confirmations"] > _best_confirm or
            (_v["confirmations"] == _best_confirm and _v["score"] > _best_score)):
            _best_confirm = _v["confirmations"]
            _best_score = _v["score"]
            _best_time = _k + ":00" if len(_k) == 16 else _k
            _best_sources = _v["sources"]
    # —— E. 兑底：gmlogger文件名日期 + 包内main文件名 ——
    if _best_confirm < 2:
        # E1: gmlogger 文件名日期作为兑底日期提供者
        for _gm_s, _gm_dt in gm_times:
            _date_providers.append((_gm_dt, "gmlogger兑底", _gm_s))
        if headers:
            try:
                _probe_atts = [a for a in attachments
                               if "gmlogger" in (a.get("filename", "") or "").lower()
                               or (a.get("filename", "") or "").lower().endswith((".zip", ".rar", ".7z"))]
                if _probe_atts:
                    _gm_probe = _diag_gmlogger_main_times(_probe_atts, headers, att_timeout, bugid)
                    _main_times_probe = _gm_probe.get("main_times", [])
                    _all_times_probe = _gm_probe.get("all_times", [])
                    for _mt_s, _mt_dt in (_main_times_probe + _all_times_probe):
                        _date_providers.append((_mt_dt, "包内main", _mt_s))
            except Exception as e:
                logger.warning("%s: 包内main兑底失败: %s", bugid, e)
        # E2: 用兑底日期提供者重新匹配仅时间候选
        _fallback_srcs = {"gmlogger兑底", "包内main"}
        if _date_providers and _time_only_candidates:
            for _hm, _hm_src in _time_only_candidates:
                _best_dp_score2 = 0.0
                _best_dp_key2 = ""
                for _dp_dt, _dp_src, _dp_str in _date_providers:
                    if _dp_src not in _fallback_srcs:
                        continue
                    _dp_hm = _dp_dt.strftime("%H:%M")
                    _min_diff = abs(int(_hm[:2]) * 60 + int(_hm[3:5]) - (int(_dp_hm[:2]) * 60 + int(_dp_hm[3:5])))
                    _min_diff = min(_min_diff, 1440 - _min_diff)
                    if _hm == _dp_hm:
                        _match_score = 3.0
                    elif _min_diff <= 30:
                        _match_score = 1.5
                    elif _min_diff <= 60:
                        _match_score = 0.5
                    else:
                        continue
                    _ck = _dp_dt.strftime("%Y-%m-%d") + " " + _hm
                    _ensure_key(_ck)
                    if _match_score > _best_dp_score2:
                        _best_dp_score2 = _match_score
                        _best_dp_key2 = _ck
                if _best_dp_key2:
                    _completed[_best_dp_key2]["score"] += _best_dp_score2
                    _label = f"{_hm_src}+兑底补全"
                    if _label not in _completed[_best_dp_key2]["sources"]:
                        _completed[_best_dp_key2]["sources"].append(_label)
                    _completed[_best_dp_key2]["confirmations"] += 1
            for _k, _v in _completed.items():
                if (_v["confirmations"] > _best_confirm or
                    (_v["confirmations"] == _best_confirm and _v["score"] > _best_score)):
                    _best_confirm = _v["confirmations"]
                    _best_score = _v["score"]
                    _best_time = _k + ":00" if len(_k) == 16 else _k
                    _best_sources = _v["sources"]
    source_label = "+".join(_best_sources) if _best_sources else ""
    logger.info("%s: 置信度提取完成 time=%s, confirm=%d, score=%.1f, sources=%s",
                bugid, _best_time or "(空)", _best_confirm, _best_score, _best_sources)
    return _best_time, source_label


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
            detail = _build_simple_detail("", "", "", "问题重复（评论区标记）")
            report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time)
            result = {"bugid": bugid, "category": category, "problem_time": problem_time,
                       "archive_files": [], "detail": detail, "main_entries": [],
                       "verify_status": "", "suggested_time": "", "report": report, "done_time": done_time}
            _save_diagnose_cache(bugid, result)
            return _ok(result, f"{bugid} 诊断完成：{category}")
    # —— 识别 gmlogger 附件（智能检测：文件名含 gmlogger 或压缩包内含 main.log）——
    if not _has_gmlogger_logs(attachments, bugid):
        # 无 gmlogger 日志文件
        category = "无gmlogger文件"
        detail = _build_simple_detail("", "", "", f"无gmlogger文件（共 {len(attachments)} 个附件）")
        verify_status, suggested_time = "", ""
        archive_results = []
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
    # —— 多源独立提取，然后综合置信度判断 ——
    comment_time = ""  # 文本提取时间（仅用于显示，保持原始格式）
    video_time = ""
    img_time_str = ""
    # 源2: 视频 OCR（独立执行，不因评论成功而跳过）
    _check_diag_cancel(bugid)
    logger.info("诊断 %s: 开始视频 OCR 提取", bugid)
    gm_dates_for_video = [(dt.year, dt.month, dt.day) for _, dt in gm_times] if gm_times else []
    gm_ref_dt_for_video = gm_times[0][1] if gm_times else None
    if headers:
        _vid_result, _vid_detail = _diag_extract_time_from_video(
            issue, headers, att_timeout, gm_dates_for_video, [], gm_ref_dt_for_video, gm_times)
        if _vid_result:
            video_time = _vid_result
            logger.info("诊断 %s: 视频 OCR 提取到 %s", bugid, video_time)
        else:
            logger.info("诊断 %s: 视频 OCR 未提取到时间", bugid)
    # 源3: 图片 OCR（独立执行）
    _check_diag_cancel(bugid)
    gm_atts = [a for a in attachments
                if "gmlogger" in (a.get("filename", "") or "").lower()
                or (a.get("filename", "") or "").lower().endswith(".log")
                or (a.get("filename", "") or "").lower().endswith(".txt")]
    gm_groups = _group_gmlogger_attachments(gm_atts)
    if len(gm_groups) > 10:
        img_time_str, _img_detail = _diag_extract_time_from_images(issue, headers, att_timeout, bugid)
        if img_time_str:
            logger.info("诊断 %s: 图片 OCR 提取到 %s", bugid, img_time_str)
    # —— 综合置信度评分：全量收集 → 日期补全 → 命中计数 ——
    logger.info("诊断 %s: 多源提取完成 video=%s, img=%s", bugid,
                video_time or '(空)', img_time_str or '(空)')
    from src.clients import jira_client as _jc
    from datetime import datetime as _score_dt
    _fields = issue.get("fields") or {}
    _created_date = (_fields.get("created") or "")[:10]
    # ── A. 收集“日期提供者”（有完整 YYYY-MM-DD HH:MM:SS 的来源）──
    _date_providers = []  # [(datetime, source_label, display_str)]
    # A1: 文本中的完整日期时间
    _text_time_only_hm = []  # 文本中仅时间的 HH:MM（用于显示）
    for _txt_label, _txt_content in [
        ("描述", _fields.get("description") or ""),
        ("标题", _fields.get("summary") or ""),
    ]:
        if not _txt_content:
            continue
        _full_set = {_t for _t, _ in _jc._extract_times_from_text(_txt_content)}
        # 收集已有完整日期时间中的所有 HH:MM，避免 time-only 重复显示
        _full_hm_set = set()
        for _ft in _full_set:
            if len(_ft) >= 16:
                _full_hm_set.add(_ft[11:16])
        for _t, _dt in _jc._extract_times_from_text(_txt_content, date_str=_created_date):
            if _t in _full_set:
                _date_providers.append((_dt, f"文本:{_txt_label}", _t))
            else:
                _hm = _dt.strftime("%H:%M")
                if _hm not in _full_hm_set:  # 过滤已包含在完整日期时间中的 time-only
                    _text_time_only_hm.append((_hm, _txt_label))
    # A2: 视频文件名（仅用于与视频OCR时间组合补全，不作为独立候选）
    _vid_fn_date = None  # (year, month, day)
    _vid_fn_dt_str = ""
    _vid_fn_dt = None
    for _att in attachments:
        _fn = _att.get("filename", "") or ""
        if _fn.lower().endswith(_VIDEO_SUFFIXES):
            _vid_fn_dt_str = _parse_video_filename_datetime(_fn)
            if _vid_fn_dt_str:
                _p = _jc._parse_datetime_string(_vid_fn_dt_str)
                if _p:
                    _vid_fn_dt = _p[1]
                    _vid_fn_date = (_vid_fn_dt.year, _vid_fn_dt.month, _vid_fn_dt.day)
            break
    # A2b: 视频上传日期不再参与日期补全（上传日≠事件日，会算错日期）
    # A3: gmlogger 文件名日期时间仅作为兑底，不直接作为日期提供者（已在步骤E处理）
    # A4: 视频 OCR 结果（如果有完整日期）
    if video_time and len(video_time) >= 16:
        _vid_dt = _jc._parse_datetime_string(video_time)
        if _vid_dt:
            _date_providers.append((_vid_dt[1], "视频OCR", video_time))
    # A5: 图片 OCR 结果（如果有完整日期）
    if img_time_str and len(img_time_str) >= 16:
        _img_dt = _jc._parse_datetime_string(img_time_str)
        if _img_dt:
            _date_providers.append((_img_dt[1], "图片OCR", img_time_str))
    # ── B. 收集“仅时间候选”（需要补全日期）──
    _time_only_candidates = []  # [(HH:MM, source_label)]
    # B1: 文本中仅时间
    for _hm, _src in _text_time_only_hm:
        _time_only_candidates.append((_hm, f"文本:{_src}"))
    # B2: 视频 OCR（如果结果是仅时间 HH:MM）
    if video_time and len(video_time) <= 8:
        _time_only_candidates.append((video_time[:5], "视频OCR"))
    # B3: 图片 OCR（如果结果是仅时间）
    if img_time_str and len(img_time_str) <= 8:
        _time_only_candidates.append((img_time_str[:5], "图片OCR"))
    # ── C. 补全：为每个仅时间候选找最佳日期提供者来补全 ──
    _completed = {}  # {"YYYY-MM-DD HH:MM": {"score": float, "sources": [], "confirmations": int}}
    def _ensure_key(key):
        if key not in _completed:
            _completed[key] = {"score": 0.0, "sources": [], "confirmations": 0}
    # C1: 日期提供者自身作为候选（基础分 1.0）
    for _dp_dt, _dp_src, _dp_str in _date_providers:
        _k = _dp_dt.strftime("%Y-%m-%d %H:%M")
        _ensure_key(_k)
        _completed[_k]["score"] += 1.0
        if _dp_src not in _completed[_k]["sources"]:
            _completed[_k]["sources"].append(_dp_src)
        _completed[_k]["confirmations"] += 1
    # C2: 仅时间候选匹配日期提供者来补全（视频OCR+视频文件名自洽额外加分）
    for _hm, _hm_src in _time_only_candidates:
        _best_dp_score = 0.0
        _best_dp_key = ""
        for _dp_dt, _dp_src, _dp_str in _date_providers:
            _dp_hm = _dp_dt.strftime("%H:%M")
            _min_diff = abs(int(_hm[:2]) * 60 + int(_hm[3:5]) - (int(_dp_hm[:2]) * 60 + int(_dp_hm[3:5])))
            _min_diff = min(_min_diff, 1440 - _min_diff)  # 环形距离
            if _hm == _dp_hm:
                _match_score = 3.0  # 完全一致：最高分
            elif _min_diff <= 30:
                _match_score = 1.5  # 差距≤30分钟
            elif _min_diff <= 60:
                _match_score = 0.5  # 差距≤1小时
            else:
                continue  # 差距太大，不算匹配
            _completed_key = _dp_dt.strftime("%Y-%m-%d") + " " + _hm
            _ensure_key(_completed_key)
            if _match_score > _best_dp_score:
                _best_dp_score = _match_score
                _best_dp_key = _completed_key
            # 匹配的日期提供者确认+1
            _completed[_dp_dt.strftime("%Y-%m-%d %H:%M")]["confirmations"] += 1
        if _best_dp_key:
            _completed[_best_dp_key]["score"] += _best_dp_score
            _label = f"{_hm_src}+补全"
            if _label not in _completed[_best_dp_key]["sources"]:
                _completed[_best_dp_key]["sources"].append(_label)
            _completed[_best_dp_key]["confirmations"] += 1
    # C3: 视频OCR仅时间 + 视频文件名/上传日期补全（仅作日期补全，不作为独立候选）
    _vid_date_providers = []  # [(date_tuple, label)]
    if _vid_fn_date:
        _vid_date_providers.append((_vid_fn_date, "视频文件名"))
    if _vid_date_providers and _time_only_candidates:
        for _hm, _hm_src in _time_only_candidates:
            if _hm_src != "视频OCR":
                continue
            for (_vy, _vm, _vd), _vdp_label in _vid_date_providers:
                _ck = f"{_vy:04d}-{_vm:02d}-{_vd:02d} {_hm}"
                _ensure_key(_ck)
                # 基础分 2.0 + 匹配分 3.0 + 自洽奖励 2.0
                _completed[_ck]["score"] += 7.0
                if _vdp_label not in _completed[_ck]["sources"]:
                    _completed[_ck]["sources"].append(_vdp_label)
                _label = f"{_hm_src}+{_vdp_label}补全"
                if _label not in _completed[_ck]["sources"]:
                    _completed[_ck]["sources"].append(_label)
                _completed[_ck]["confirmations"] += 2
    # ── D. 选择最终答案：优先看确认次数，其次看得分 ──
    _best_time = ""
    _best_score = 0.0
    _best_confirm = 0
    _best_sources = []
    for _k, _v in _completed.items():
        # 排序优先级：确认次数 > 得分 > 时间字符串（稳定排序）
        if (_v["confirmations"] > _best_confirm or
            (_v["confirmations"] == _best_confirm and _v["score"] > _best_score)):
            _best_confirm = _v["confirmations"]
            _best_score = _v["score"]
            _best_time = _k + ":00" if len(_k) == 16 else _k
            _best_sources = _v["sources"]
    logger.info("诊断 %s: 置信度评分结果 best_time=%s, confirm=%d, score=%.1f, sources=%s, 候选数=%d", bugid,
                _best_time or '(空)', _best_confirm, _best_score, _best_sources, len(_completed))
    # ── E. 兜底：gmlogger文件名日期 + 包内main文件名 ──
    if _best_confirm < 2:
        _check_diag_cancel(bugid)
        logger.info("诊断 %s: 置信度不足，尝试gmlogger文件名+包内main兜底", bugid)
        # E1: gmlogger 文件名日期作为兜底日期提供者
        for _gm_s, _gm_dt in gm_times:
            _date_providers.append((_gm_dt, "gmlogger兜底", _gm_s))
        if headers:
            try:
                _probe_atts = [a for a in attachments
                               if "gmlogger" in (a.get("filename", "") or "").lower()
                               or (a.get("filename", "") or "").lower().endswith((".zip", ".rar", ".7z"))]
                if _probe_atts:
                    _gm_probe = _diag_gmlogger_main_times(_probe_atts, headers, att_timeout, bugid)
                    _main_times_probe = _gm_probe.get("main_times", [])
                    _all_times_probe = _gm_probe.get("all_times", [])
                    for _mt_s, _mt_dt in (_main_times_probe + _all_times_probe):
                        _date_providers.append((_mt_dt, "包内main", _mt_s))
            except Exception as e:
                logger.warning("诊断 %s: 包内main兜底失败: %s", bugid, e)
        # E2: 用兜底日期提供者重新匹配仅时间候选
        _fallback_srcs = {"gmlogger兜底", "包内main"}
        if _date_providers and _time_only_candidates:
            for _hm, _hm_src in _time_only_candidates:
                _best_dp_score2 = 0.0
                _best_dp_key2 = ""
                for _dp_dt, _dp_src, _dp_str in _date_providers:
                    if _dp_src not in _fallback_srcs:
                        continue
                    _dp_hm = _dp_dt.strftime("%H:%M")
                    _min_diff = abs(int(_hm[:2]) * 60 + int(_hm[3:5]) - (int(_dp_hm[:2]) * 60 + int(_dp_hm[3:5])))
                    _min_diff = min(_min_diff, 1440 - _min_diff)
                    if _hm == _dp_hm:
                        _match_score = 3.0
                    elif _min_diff <= 30:
                        _match_score = 1.5
                    elif _min_diff <= 60:
                        _match_score = 0.5
                    else:
                        continue
                    _ck = _dp_dt.strftime("%Y-%m-%d") + " " + _hm
                    _ensure_key(_ck)
                    if _match_score > _best_dp_score2:
                        _best_dp_score2 = _match_score
                        _best_dp_key2 = _ck
                if _best_dp_key2:
                    _completed[_best_dp_key2]["score"] += _best_dp_score2
                    _label = f"{_hm_src}+兜底补全"
                    if _label not in _completed[_best_dp_key2]["sources"]:
                        _completed[_best_dp_key2]["sources"].append(_label)
                    _completed[_best_dp_key2]["confirmations"] += 1
                    logger.info("诊断 %s: 兜底匹配成功 %s -> %s", bugid, _hm, _best_dp_key2)
            # 重新选择最佳候选
            for _k, _v in _completed.items():
                if (_v["confirmations"] > _best_confirm or
                    (_v["confirmations"] == _best_confirm and _v["score"] > _best_score)):
                    _best_confirm = _v["confirmations"]
                    _best_score = _v["score"]
                    _best_time = _k + ":00" if len(_k) == 16 else _k
                    _best_sources = _v["sources"]
            logger.info("诊断 %s: 兜底后 best_time=%s, confirm=%d, score=%.1f", bugid,
                        _best_time or '(空)', _best_confirm, _best_score)
    # comment_time 用于显示：文本中提取到的所有时间（保持原始格式）
    _display_parts = []
    for _hm, _src in _text_time_only_hm:
        _display_parts.append(_hm)
    for _dp_dt, _dp_src, _dp_str in _date_providers:
        if _dp_src.startswith("文本:") and _dp_str not in _display_parts:
            _display_parts.append(_dp_str)
    comment_time = ", ".join(_display_parts[:3]) if _display_parts else ""
    # 用置信度最高的时间作为建议时间
    verify_status = ""
    suggested_time = ""
    vdetail = ""
    if _best_time:
        suggested_time = _best_time
        verify_status = "success" if _best_score >= 2.0 else "manual"
        vdetail = f"多源置信度: {'+'.join(_best_sources)}={_best_score}分"
        # 如果视频提取的是仅时间，且最终结果来自视频源，显示组合后的完整时间
        if video_time and len(video_time) <= 8 and any("视频" in s for s in _best_sources):
            video_time = f"{video_time}（结合视频日期 → {suggested_time}）"
    if verify_status == "success":
        category = "触发时间问题"
        # 根据置信度评分结果生成描述
        verify_desc = vdetail or "验证通过"
        detail = _build_simple_detail(comment_time, video_time, img_time_str, f"触发时间问题（{verify_desc}）")
        report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time, verify_status, suggested_time)
        _tc = _diag_time_check(issue, suggested_time or problem_time, gm_times, None, None,
                               video_time or "", current_time=problem_time)
        if _tc["status"] == "不可用" and verify_status == "success":
            verify_status = "manual"
        result = {"bugid": bugid, "category": category, "problem_time": problem_time,
                   "archive_files": [], "detail": detail, "main_entries": [],
                   "verify_status": verify_status, "suggested_time": suggested_time,
                   "time_check": _tc, "report": report, "done_time": done_time}
        _save_diagnose_cache(bugid, result)
        return _ok(result, f"{bugid} 诊断完成：{category}（{verify_desc}）")
    # 置信度不足（仅单源提取到），进入 gmlogger 压缩包验证流程
    _check_diag_cancel(bugid)
    img_detail = ""
    # 筛选日志附件（gmlogger / .log / .txt）并按分卷分组
    gm_atts = [a for a in attachments
                if "gmlogger" in (a.get("filename", "") or "").lower()
                or (a.get("filename", "") or "").lower().endswith(".log")
                or (a.get("filename", "") or "").lower().endswith(".txt")]
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
        detail = _build_simple_detail(comment_time, video_time, img_time_str, f"解压问题（包内时间戳命中但日志为空）")
        verify_status, suggested_time = "", ""
    else:
        # —— 时间不匹配时先检查评论区是否有“问题重复”，有则直接跳过后续链路 ——
        _comments = jira_client.extract_comments(issue)
        _has_dup = any("问题重复" in str(c) for c in _comments)
        if _has_dup:
            category = "问题重复"
            detail = _build_simple_detail(comment_time, video_time, img_time_str, "问题重复（评论区标记）")
            report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time)
            result = {"bugid": bugid, "category": category, "problem_time": problem_time,
                       "archive_files": [], "detail": detail, "main_entries": [],
                       "verify_status": "", "suggested_time": "", "report": report, "done_time": done_time}
            _save_diagnose_cache(bugid, result)
            return _ok(result, f"{bugid} 诊断完成：{category}")
        category = "触发时间问题"
        if main_times:
            final_msg = f"触发时间问题（包内时间戳与错误时间不匹配）"
        elif all_times:
            final_msg = f"触发时间问题（包内文件时间戳与错误时间不匹配）"
        else:
            final_msg = f"触发时间问题（包内未提取到内容时间戳）"
        if gm_probe.get("status") == "failed":
            final_msg += f"（内包探测失败）"
        elif main_entries:
            final_msg += f"（包内 main 文件：{', '.join(main_entries[:5])}）"
        # —— 包内时间戳也未命中：用包内时间戳重新验证修正建议 ——
        _check_diag_cancel(bugid)
        verify_status, suggested_time, vdetail, _vid_extracted = _diag_verify_suggestion(issue, gm_times, [],
                                                                         main_times=main_times, all_times=all_times,
                                                                         headers=headers, att_timeout=att_timeout)
        # 直接使用函数返回的视频提取时间（即使未通过验证也记录）
        if _vid_extracted:
            video_time = _vid_extracted
        # 方向敏感判定：晚于抓包 >300s 判不可用；早于抓包 <=15min 属正常
        time_check = _diag_time_check(issue, suggested_time or problem_time, gm_times, main_times, all_times,
                                      video_time or "", current_time=problem_time)
        if time_check["status"] == "不可用" and verify_status == "success":
            verify_status = "manual"
            vdetail = f"{vdetail}（时间方向异常，需人工确认）" if vdetail else "时间方向异常，需人工确认"
        elif time_check["status"] == "正常" and verify_status == "manual":
            verify_status = "success"
            vdetail = f"{vdetail}（方向判定正常：与抓包差 {time_check['delta_sec']} 秒）" if vdetail else "方向判定正常"
        detail = _build_simple_detail(comment_time, video_time, img_time_str, final_msg)
    report = _generate_troubleshoot_report(bugid, category, err_msg, detail, problem_time, verify_status, suggested_time, archive_results)
    result = {"bugid": bugid, "category": category, "problem_time": problem_time,
               "archive_files": archive_results, "detail": detail, "main_entries": main_entries,
               "verify_status": verify_status, "suggested_time": suggested_time,
               "time_check": locals().get("time_check"), "report": report, "done_time": done_time}
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
    import json, urllib.request
    url = f"{_AI_LOG_SERVICE_URL}/api/logs?name={name}&start_line=1&limit={min(limit, 5000)}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            # 兼容多种返回格式
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("logs") or data.get("data") or data.get("lines") or []
            return []
    except Exception as e:
        logger.error("读取AI日志失败: %s", e)
        raise

