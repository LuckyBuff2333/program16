"""ADP 分析管道：dpportal查附件 → ADP v2 SSE分析 → 提取结果 → 写入飞书多维表格

学习自 program17/adp_analysis_pipeline.py，适配项目风格。
"""
import os
import re
import json
import uuid
import subprocess
import sys
from datetime import datetime

import httpx

from src.config import load_config, get_path, setup_logger

logger = setup_logger("adp_ops")

# SSE 已知事件类型（不触发未知事件日志）
_KNOWN_EVENT_TYPES = {
    "text.delta", "text.replace", "content.added", "response.created",
    "request_ack", "response.completed", "error", "message.done",
    "message.processing", "message.added", "response.processing",
}

# ===== 错误码分级（参考 docs/ADP接口问题判别与处理策略.md）=====

# 致命错误码：配置/账号级问题，发"继续"无效，应立即终止
FATAL_ERROR_CODES = {
    "4505004", "460001", "460004", "460026", "460048",
    "460501", "460502", "460032", "460702",
}

# 并发限流码：原样重发原始请求（会话是空的）
RATE_LIMIT_CODES = {"460011", "460031"}

# TPM 限流码（Token 级限流，退避 60s）
TPM_LIMIT_CODES = {
    "460701",   # 企业级 TPM
    "460711",   # 空间级 TPM
    "460721",   # 应用级 TPM
}

# 容量类限流码（QPM/RPM，分钟级窗口，退避 300s）
CAPACITY_LIMIT_CODES = {
    "460701",                       # 企业级 TPM（实测日志出现过）
    "460711", "460712", "460713",   # 空间级
    "460721", "460722", "460723",   # 应用级
}

# 可重试错误码（模型超时等，发"继续"即可恢复）
RETRYABLE_ERROR_CODES = {"460020", "460030"}

# 需换会话ID重试的错误码（会话级冲突，新ID可解决）
SESSION_CONFLICT_CODES = {"460919"}

# 拒答/澄清 ReplyMethod（response.completed 里的 ExtraInfo.ReplyMethod）
NO_REPORT_REPLY_METHODS = {"3", "15"}  # 3=拒答, 15=澄清确认
CONCURRENT_LIMIT_REPLY = "7"  # ReplyMethod=7 表示并发超限

# 澄清/索取信息话术关键词（仅短篇回复 < 4000 字时生效）
CLARIFY_KEYWORDS = [
    "请提供", "请补充", "请上传", "请确认", "请重新提供",
    "无法下载", "无法获取", "无法访问", "下载失败", "未找到日志",
    "缺少日志", "需要您提供", "需要您确认",
]

# 拒答话术关键词
REFUSAL_KEYWORDS = ["无法分析", "无法处理", "不能分析", "拒绝回答", "不予回答"]

# 回复完整收尾章节标志（出现 2 个以上说明分析主体已完成）
COMPLETE_SECTION_MARKERS = ["归因", "根因", "修复建议", "决策点", "待办与缺口", "结论"]


# ===== 配置读取 =====

def _get_adp_cfg() -> dict:
    """读取 adp 配置段，带默认值"""
    cfg = load_config().get("adp") or {}
    # jira_field 乱码兜底：历史配置被写坏（如 "Jira閾炬帴"）时回退到正确字段名
    _jf = cfg.get("jira_field") or ""
    if _jf and any(ch in _jf for ch in ("閾", "鏈", "锛", "�")):
        logger.warning("adp.jira_field 配置疑似乱码（%s），回退为 Jira链接", _jf)
        cfg = dict(cfg)
        cfg["jira_field"] = "Jira链接"
    return {
        "app_key": cfg.get("app_key", ""),
        "url": cfg.get("url", "https://wss.lke.cloud.tencent.com/adp/v2/chat"),
        "sandbox_base": cfg.get("sandbox_base", "https://sandbox.adp.cloud.tencent.com/files?path="),
        "attach_api": cfg.get("attach_api", "https://dpportal.apps.saic-gm.com/api/logAnalysis/attachments"),
        "attach_api_key": cfg.get("attach_api_key", ""),
        "attach_timeout": int(cfg.get("attach_timeout", 120)),
        "attach_retry_interval": int(cfg.get("attach_retry_interval", 10)),
        "attach_cache_ttl": int(cfg.get("attach_cache_ttl", 300)),
        "timeout": int(cfg.get("timeout", 3600)),
        "bitable_app_token": cfg.get("bitable_app_token", ""),
        "bitable_table_id": cfg.get("bitable_table_id", ""),
        "bitable_table_name": cfg.get("bitable_table_name", ""),
        "bitable_view_id": cfg.get("bitable_view_id", ""),
        "jira_field": cfg.get("jira_field", "Jira链接"),
        "save_dir": cfg.get("save_dir", "docs/adp_results"),
        "app_id": str(cfg.get("app_id", "") or ""),
        "space_id": str(cfg.get("space_id", "") or ""),
        "mcp_api_key": cfg.get("mcp_api_key", "") or "",
        "trace_report_base": cfg.get("trace_report_base", "http://127.0.0.1:8060"),
        "trace_report_folder": cfg.get("trace_report_folder", ""),
        "sse_read_timeout": int(cfg.get("sse_read_timeout", 180)),
        "report_folder": cfg.get("report_folder", ""),
        "batch_report_folder": cfg.get("batch_report_folder", ""),
    }


# ===== 工具函数 =====

def _fix_encoding(text: str) -> str:
    """修复 latin-1 误读的 UTF-8 乱码（ADP SSE 返回已知问题）"""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


# ===== traceid 排查技能（log-review-pan-scan）=====

_TRACE_SKILL_SUBDIR = os.path.join("tools", "skills", "log-review-pan-scan")


def _trace_skill_dir() -> str:
    from src.config import PROJECT_ROOT as _root
    return os.path.join(_root, _TRACE_SKILL_SUBDIR)


def _publish_md_to_feishu(title: str, md_content: str, folder_token: str = "") -> str:
    """把 Markdown 发布成飞书在线文档（可指定文件夹），返回长期链接（失败返回空串）"""
    try:
        from src.clients import feishu_client
        res = feishu_client.create_docx_document(title, md_content, folder_token=folder_token or "")
        url = (res or {}).get("url", "")
        if url:
            logger.info("已发布飞书文档: %s", url)
        return url
    except Exception as e:
        logger.warning("发布飞书文档失败: %s", str(e)[:150])
        return ""


def _run_trace_skill(jira_key: str, trace_id: str):
    """调用 log-review-pan-scan 技能导出 traceid 取证包，汇总为 md 报告。

    返回 (report_path, error)：成功 error 为空；失败 report_path 为空。
    """
    if not trace_id:
        return "", "无 trace_id"
    skill_dir = _trace_skill_dir()
    script = os.path.join(skill_dir, "scripts", "record_lookup.py")
    if not os.path.isfile(script):
        return "", "技能未安装（tools/skills/log-review-pan-scan）"
    cfg = _get_adp_cfg()
    evidence_dir = os.path.join(get_path("doc_dir"), "adp_results", jira_key, f"traceid_{trace_id[:8]}")
    os.makedirs(evidence_dir, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "ADP_API_KEY": str(cfg.get("mcp_api_key") or cfg.get("app_key") or ""),
        "ADP_APP_ID": str(cfg.get("app_id") or ""),
        "ADP_SPACE_ID": str(cfg.get("space_id") or ""),
    })
    last_err = ""
    for days in (3, 1):
        try:
            proc = subprocess.run(
                [sys.executable, script, trace_id, "--days", str(days), "--refresh",
                 "--export", evidence_dir],
                cwd=skill_dir, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="ignore", timeout=240)
        except Exception as e:
            last_err = f"技能执行异常: {str(e)[:120]}"
            continue
        if proc.returncode == 0 and os.path.isfile(os.path.join(evidence_dir, "record.json")):
            break
        last_err = ((proc.stderr or "") + (proc.stdout or "")).strip()[:200] or f"exit={proc.returncode}"
    else:
        return "", last_err or "技能无输出"

    rec_path = os.path.join(evidence_dir, "record.json")
    if not os.path.isfile(rec_path):
        return "", last_err or "未生成 record.json"
    report_path = os.path.join(get_path("doc_dir"), "adp_results", jira_key, f"{jira_key}_traceid_report.md")
    try:
        with open(rec_path, encoding="utf-8") as f:
            rec = json.load(f)
        msg_path = os.path.join(evidence_dir, "session_messages.txt")
        messages = ""
        if os.path.isfile(msg_path):
            with open(msg_path, encoding="utf-8", errors="ignore") as f:
                messages = f.read()
        lines = [
            f"# {jira_key} traceid 排查报告",
            "",
            f"- traceid: `{trace_id}`",
            f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "- 来源: log-review-pan-scan 1.0.0（record_lookup --export）",
            f"- 证据目录: `{evidence_dir}`",
            "",
            "## 智能体结论（answer）",
            "",
            str(rec.get("answer") or "（空）")[:8000],
            "",
            "## 用户问题（question）",
            "",
            str(rec.get("question") or "（空）")[:2000],
            "",
            "## 指标",
            "",
            "```json",
            json.dumps({k: v for k, v in rec.items() if k not in ("answer", "question")},
                       ensure_ascii=False, indent=2)[:2000],
            "```",
            "",
            "## 分析过程消息流（session_messages.txt）",
            "",
            "```text",
            messages[:12000] or "（空）",
            "```",
            "",
        ]
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info("traceid 排查报告已生成: %s", report_path)
        with open(report_path, encoding="utf-8") as f:
            _md = f.read()
        _folder = str(_get_adp_cfg().get("trace_report_folder") or "")
        _doc_url = _publish_md_to_feishu(f"{jira_key} traceid排查报告", _md, folder_token=_folder)
        return report_path, "", _doc_url
    except Exception as e:
        return "", f"报告生成失败: {str(e)[:120]}", ""


# ===== Step 1: dpportal 查询附件 =====

_ATTACH_CACHE = {}
_ATTACH_CACHE_LOCK = __import__("threading").Lock()


def query_attachments(jira_key: str):
    """查询 JIRA 附件列表（dpportal 接口，带本地短期缓存）。

    返回:
      - list: 正常（可能为空列表，表示确实没有附件）
      - None: 接口异常（非 JSON / 5xx / 重试后仍失败）——与“无附件”区分开，避免误标为无法分析
    """
    adp_cfg = _get_adp_cfg()
    import time as _t

    # 本地缓存：同一 Jira 在 TTL 内复用，避免重复慢查询
    ttl = adp_cfg.get("attach_cache_ttl", 300)
    with _ATTACH_CACHE_LOCK:
        hit = _ATTACH_CACHE.get(jira_key)
        if hit and _t.time() - hit[0] < ttl:
            logger.info("dpportal 附件查询: %s 命中缓存（%d 个附件）", jira_key, len(hit[1]))
            return list(hit[1])

    logger.info("dpportal 查询附件: %s", jira_key)
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        try:
            resp = httpx.post(
                adp_cfg["attach_api"],
                headers={"Content-Type": "application/json", "X-API-Key": adp_cfg["attach_api_key"]},
                json={"jiraKey": jira_key},
                timeout=adp_cfg.get("attach_timeout", 120),
            )
            # 非 200 / 非 JSON：按传输异常处理（网关 502、空响应等）
            body_head = (resp.text or "")[:200].replace("\n", " ")
            if resp.status_code != 200:
                raise httpx.HTTPError(f"HTTP {resp.status_code}: {body_head}")
            try:
                data = resp.json()
            except Exception:
                raise httpx.HTTPError(f"响应非 JSON: {body_head!r}")
            if data.get("code") != 0:
                logger.warning("dpportal 附件查询业务错误: %s -> %s", jira_key, body_head)
                return []
            attachments = data.get("data", {}).get("attachments", [])
            logger.info("dpportal 附件查询: %s 找到 %d 个附件", jira_key, len(attachments))
            with _ATTACH_CACHE_LOCK:
                _ATTACH_CACHE[jira_key] = (_t.time(), list(attachments))
            return attachments
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError, httpx.HTTPError) as e:
            if attempt < max_attempts:
                wait = adp_cfg.get("attach_retry_interval", 10)
                logger.warning("dpportal 附件查询异常（第 %d/%d 次）: %s -> %s，%ds 后重试",
                               attempt, max_attempts, jira_key, str(e)[:120], wait)
                _t.sleep(wait)
                continue
            logger.error("dpportal 附件查询异常（重试耗尽）: %s -> %s", jira_key, str(e)[:150])
            return None
        except Exception as e:
            logger.error("dpportal 附件查询异常（不可重试）: %s -> %s", jira_key, e)
            return None
    return None


# ===== Step 2: 构建消息 + 调用 ADP SSE =====

def _build_signal(error_code: str, error_msg: str, reply_method: str,
                  response_status: str, has_cards: bool, request_ack: bool,
                  stream_exc: str, conversation_id: str = "") -> dict:
    """构造信号信息字典（SSE 流中采集的各类判别信号）"""
    return {
        "error_code": error_code,
        "error_msg": error_msg,
        "reply_method": reply_method,
        "response_status": response_status,
        "has_cards": has_cards,
        "request_ack": request_ack,
        "stream_exc": stream_exc,
        "conversation_id": conversation_id,
    }


# 有效附件后缀（压缩包或 txt/log），用于过滤非日志附件
# 有效附件：压缩包（含任意分卷）/ 日志 / 文本
# 分卷覆盖：.zip.001 / .7z.001 / .001、.z01、.r00、.part01.rar、.tar.gz.001 等
_VALID_ATTACH_RE = re.compile(
    r'(?:\.(?:zipx?|rar|7z|tar|tgz|gz|bz2|xz|zst|lz4|cab|log|txt)'
    r'(?:\.(?:gz|bz2|xz|zst|lz4))?'
    r'(?:\.\d{1,4}|\.z\d{1,3}|\.r\d{2,3}|\.part\d{1,3}\.rar)?'
    r'|\.part\d{1,3}\.rar'
    r'|\.z\d{1,3}'
    r'|\.r\d{2,3}'
    r'|\.\d{3,4})$',
    re.IGNORECASE)


def _is_valid_attachment(att: dict) -> bool:
    """判断附件是否为有效的日志/分析文件（压缩包或 txt）"""
    name = att.get("filename", "")
    url = att.get("downloadUrl", "")
    if not url:
        return False
    return bool(_VALID_ATTACH_RE.search(name))


def build_adp_message(jira_key: str, description: str, trigger_time: str, attachments: list) -> str:
    """拼接 ADP 入参消息，传递所有有效附件链接"""
    msg = f"JIRA号{jira_key}，描述: {description}，触发时间: {trigger_time}\n"
    msg += "日志附件下载链接：\n"
    count = 0
    for att in attachments:
        if not _is_valid_attachment(att):
            continue
        name = att.get("filename", "")
        size_mb = att.get("size", 0) / 1024 / 1024
        url = att.get("downloadUrl", "")
        msg += f"- {name} ({size_mb:.1f}MB): {url}\n"
        count += 1
    logger.info("ADP 消息: %s 附件链接（共 %d 个附件，过滤后 %d 个）", jira_key, len(attachments), count)
    return msg


def call_adp_sse_stream(message: str, keepalive_cb=None, max_retries: int = 3, stop_event=None,
                        conversation_id: str = None) -> tuple:
    """
    调用 ADP v2 SSE 接口（流式读取，支持心跳回调、自动重试和续接）
    :param keepalive_cb: 可选回调 fn(elapsed_sec)，每 30 秒调用一次用于 SSE 心跳
    :param max_retries: 连接失败时最大重试次数（默认 3 次）
    :param stop_event: 可选 threading.Event，设置后尽快中止流式读取
    :param conversation_id: 可选会话 ID（用于续接场景，复用同一会话上下文）
    返回: (full_text, file_urls, closeout_data, start_ts, end_ts, trace_id, signal_info)
           signal_info 包含: error_code, error_msg, reply_method, response_status,
                             has_cards, request_ack, stream_exc
    """
    import time

    def _should_stop():
        return stop_event is not None and stop_event.is_set()

    def _interruptible_sleep(total_sec):
        """可中断的 sleep：每 0.5 秒检查 stop_event"""
        elapsed = 0.0
        while elapsed < total_sec:
            if _should_stop():
                return True
            time.sleep(min(0.5, total_sec - elapsed))
            elapsed += 0.5
        return False
    adp_cfg = _get_adp_cfg()
    # 支持续接场景：复用传入的 conversation_id，否则生成新的
    conv_id = conversation_id or uuid.uuid4().hex[:32]
    payload = {
        "RequestId": uuid.uuid4().hex[:32],
        "ConversationId": conv_id,
        "AppKey": adp_cfg["app_key"],
        "VisitorId": "jira_analysis_user",
        "Contents": [{"Type": "text", "Text": message}],
        "Incremental": True,
        "Stream": "enable",
        "StreamingThrottle": 5,
    }
    logger.info("ADP 调用 SSE 接口（流式，超时 %ds，最多重试 %d 次，conv=%s）...",
                adp_cfg["timeout"], max_retries, conv_id[:12])
    last_err = None
    event_types_seen = set()
    logged_unknown = set()
    trace_id = ""
    conv_seen = ""  # response.created 里的 ConversationId（续接必须复用）
    # 信号采集变量（跨尝试累计，不重置）
    error_code = ""
    error_msg = ""
    reply_method = ""
    response_status = ""
    has_cards = False
    request_ack = False
    stream_exc = ""
    for attempt in range(1, max_retries + 1):
        full_text = ""
        file_urls = []
        closeout_data = None
        start_ts = 0
        end_ts = 0
        t0 = time.time()
        last_keepalive = t0
        # 每次尝试重置流级信号（error_code 等保留最后一次）
        stream_exc = ""
        try:
            with httpx.stream(
                "POST", adp_cfg["url"],
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=httpx.Timeout(adp_cfg["timeout"], connect=30, read=int(adp_cfg.get("sse_read_timeout", 180))),
            ) as resp:
                if resp.status_code != 200:
                    logger.error("ADP SSE HTTP %d", resp.status_code)
                    return "", [], None, 0, 0, trace_id
                if _should_stop():
                    logger.info("ADP SSE 收到停止信号，中止读取")
                    return full_text, file_urls, closeout_data, start_ts, end_ts, trace_id
                for line in resp.iter_lines():
                    if _should_stop():
                        logger.info("ADP SSE 收到停止信号，中止读取")
                        return full_text, file_urls, closeout_data, start_ts, end_ts, trace_id
                    # 心跳回调
                    now = time.time()
                    if keepalive_cb and now - last_keepalive >= 30:
                        keepalive_cb(round(now - t0, 1))
                        last_keepalive = now
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        continue
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    et = data.get("Type", "")
                    ts = int(data.get("Timestamp", 0))
                    event_types_seen.add(et)
                    # 未知事件类型每种只打一次（诊断用，不刷屏）
                    if et and et not in _KNOWN_EVENT_TYPES and et not in logged_unknown:
                        logged_unknown.add(et)
                        logger.info("ADP SSE 未知事件: Type=%s", et)
                    if et == "response.created":
                        if ts > 0:
                            start_ts = ts
                        _resp = data.get("Response") or {}
                        _conv = str(_resp.get("ConversationId") or "")
                        if _conv:
                            conv_seen = _conv
                        _extra = _resp.get("ExtraInfo") or {}
                        _tid = str(_extra.get("TraceId") or "").split(" / ")[0].strip()
                        # 以最后一次 response.created 的 traceid 为准
                        if _tid:
                            trace_id = _tid
                        elif _conv and not trace_id:
                            trace_id = _conv
                        # 兼容旧字段名（顶层）
                        for tid_key in ("TraceId", "trace_id", "TraceID", "ConversationId", "conversation_id"):
                            v = data.get(tid_key, "")
                            if v and not trace_id:
                                trace_id = str(v)
                                break
                        # 记录关键字段（不打印整段 JSON，避免日志被截断误读）
                        logger.info("ADP response.created: conv=%s record=%s trace=%s status=%s",
                                    _conv, _resp.get("RecordId", ""), trace_id,
                                    _resp.get("Status", ""))
                    # ---- 新增：request_ack 事件（请求被受理）----
                    if et == "request_ack":
                        request_ack = True
                        logger.debug("ADP request_ack: 请求已被受理")
                    # ---- 新增：error 事件（平台错误：致命/限流/安全拦截）----
                    if et == "error":
                        err_obj = data.get("Error") or {}
                        error_code = str(err_obj.get("Code") or "")
                        error_msg = str(err_obj.get("Message") or "")[:400]
                        logger.warning("ADP SSE 错误事件: code=%s msg=%s", error_code, error_msg[:120])
                        # 致命错误立即终止，不再消费后续事件
                        if error_code in FATAL_ERROR_CODES:
                            logger.error("ADP 致命错误 %s，立即终止", error_code)
                            break
                        # 限流错误也终止本轮（由上层决策是否重发）
                        if error_code in RATE_LIMIT_CODES or error_code in CAPACITY_LIMIT_CODES:
                            logger.warning("ADP 限流错误 %s，终止本轮", error_code)
                            break
                        # 可重试错误终止本轮（上层发"继续"续接）
                        if error_code in RETRYABLE_ERROR_CODES:
                            logger.warning("ADP 可重试错误 %s（模型超时等），终止本轮", error_code)
                            break
                        # 会话冲突终止本轮（上层换新ID重试）
                        if error_code in SESSION_CONFLICT_CODES:
                            logger.warning("ADP 会话冲突 %s，需换新ID重试", error_code)
                            break
                    # ---- 新增：response.completed 事件（本轮响应完成）----
                    if et == "response.completed":
                        resp_obj = data.get("Response") or {}
                        response_status = str(resp_obj.get("Status") or "")
                        extra_info = resp_obj.get("ExtraInfo") or {}
                        reply_method = str(extra_info.get("ReplyMethod") or "")
                        # 从 response.completed 的 Messages 兜底取完整回复
                        if not full_text:
                            for msg in (resp_obj.get("Messages") or []):
                                for c in (msg.get("Contents") or []):
                                    if c.get("Type") == "text":
                                        full_text += _fix_encoding(c.get("Text") or "")
                        logger.info("ADP response.completed: status=%s reply_method=%s",
                                    response_status, reply_method)
                    if ts > 0:
                        end_ts = ts
                    if et == "text.delta":
                        full_text += _fix_encoding(data.get("Text", ""))
                    elif et == "text.replace":
                        raw = _fix_encoding(data.get("Text", ""))
                        if '"ok"' in raw and '"html"' in raw:
                            try:
                                closeout_data = json.loads(raw)
                                logger.info("ADP closeout_data keys: %s", list(closeout_data.keys()))
                            except json.JSONDecodeError:
                                pass
                    elif et == "content.added":
                        content = data.get("Content", {})
                        ctype = content.get("Type") or ""
                        if ctype == "file":
                            finfo = content.get("File", {})
                            fname = finfo.get("FileName", "")
                            furl = finfo.get("FileUrl", "")
                            file_urls.append({"name": fname, "url": furl})
                            if fname.endswith(".html"):
                                logger.info("ADP SSE 捕获 HTML 文件: %s", fname)
                        # 新增：追问卡片/问卷检测
                        elif ctype in ("option_cards", "questionnaire"):
                            has_cards = True
                            logger.warning("ADP 智能体发出追问信号: type=%s", ctype)
        except httpx.ReadTimeout:
            # 读超时（60s 无新数据）：非连接错误，检查停止信号后返回已收集的数据
            stream_exc = "读超时（60s 无新数据）"
            if _should_stop():
                logger.info("ADP SSE 读超时且收到停止信号，中止")
            else:
                logger.warning("ADP SSE 读超时（60s 无新数据），已收集 %d 字符", len(full_text))
            return full_text, file_urls, closeout_data, start_ts, end_ts, trace_id, _build_signal(
                error_code, error_msg, reply_method, response_status, has_cards, request_ack, stream_exc, conversation_id=conv_seen)
        except Exception as e:
            last_err = e
            stream_exc = "%s: %s" % (type(e).__name__, e)
            # 连接级错误（DNS/超时/断连）可重试，已收到数据则不重试
            is_conn_err = any(kw in str(e).lower() for kw in ["getaddrinfo", "connect", "timed out", "timeout", "connection"])
            if is_conn_err and not full_text and attempt < max_retries:
                wait = 10 * attempt
                logger.warning("ADP SSE 连接失败（第 %d/%d 次）: %s，%ds 后重试...", attempt, max_retries, e, wait)
                if keepalive_cb:
                    keepalive_cb(round(time.time() - t0, 1))
                if _interruptible_sleep(wait):
                    logger.info("ADP SSE 重试等待中被停止")
                    return "", [], None, 0, 0, trace_id, _build_signal(
                        error_code, error_msg, reply_method, response_status, has_cards, request_ack, stream_exc, conversation_id=conv_seen)
                continue
            logger.error("ADP SSE 流式读取异常: %s", e)
            return full_text, file_urls, closeout_data, start_ts, end_ts, trace_id, _build_signal(
                error_code, error_msg, reply_method, response_status, has_cards, request_ack, stream_exc, conversation_id=conv_seen)
        # 成功完成，跳出重试循环
        break
    else:
        # 所有重试均失败
        stream_exc = "连接失败，已重试 %d 次: %s" % (max_retries, last_err)
        logger.error("ADP SSE %s", stream_exc)
        return "", [], None, 0, 0, trace_id, _build_signal(
            error_code, error_msg, reply_method, response_status, has_cards, request_ack, stream_exc, conversation_id=conv_seen)
    # closeout 兜底
    if closeout_data is None:
        for pattern in [r'\{[^{}]*"ok"\s*:\s*true[^{}]*"html"[^{}]*\}', r'\{[^{}]*"case_id"[^{}]*\}']:
            m = re.search(pattern, full_text)
            if m:
                try:
                    closeout_data = json.loads(m.group())
                    break
                except json.JSONDecodeError:
                    pass
    # ---- 迟到报告检测：仅在流耗时 > 5 分钟时触发，短流说明连接异常中断 ----
    def _has_downloadable_report():
        """检查是否有真正可下载的报告链接（agent.adp-cos.com CDN 或 file_urls 中的 HTML）"""
        if re.search(r'agent\.adp-cos\.com', full_text):
            return True
        if any(f.get("name", "").endswith(".html") and "meta" not in f.get("name", "").lower()
               for f in file_urls):
            return True
        return False

    stream_sec = (end_ts - start_ts) / 1000 if start_ts and end_ts else 0
    if full_text and len(full_text) > 500 and not _has_downloadable_report() and error_code not in FATAL_ERROR_CODES:
        if stream_sec <= 300:
            logger.info("ADP 正常收口但无报告（%.0fs < 5分钟），跳过迟到检测", stream_sec)
        else:
            for round_idx in range(2):  # 最多 2 轮，每轮等 5 分钟，总计最多 10 分钟
                wait_sec = 300
                logger.info("ADP 无 HTML 报告信号，%d 秒后尝试第 %d 轮续接...", wait_sec, round_idx + 1)
                if keepalive_cb:
                    keepalive_cb(round(time.time() - t0, 1))
                if _interruptible_sleep(wait_sec):
                    logger.info("ADP 续接等待中被停止")
                    break
                logger.info("续接 ADP 会话（第 %d 轮）...", round_idx + 1)
                prev_text_len = len(full_text)
                prev_file_count = len(file_urls)
                try:
                    payload2 = dict(payload)
                    payload2["RequestId"] = uuid.uuid4().hex[:32]
                    client2 = httpx.Client(timeout=httpx.Timeout(adp_cfg["timeout"], connect=30))
                    try:
                        with client2.stream("POST", adp_cfg["url"], json=payload2,
                                            headers={"Content-Type": "application/json"}) as sse_resp:
                            if sse_resp.status_code == 200:
                                new_text_len = 0
                                for line in sse_resp.iter_lines():
                                    if _should_stop():
                                        logger.info("ADP 续接 SSE 收到停止信号")
                                        break
                                    if not line or not line.startswith("data: "):
                                        continue
                                    data_str = line[6:]
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        data = json.loads(data_str)
                                    except json.JSONDecodeError:
                                        continue
                                    et = data.get("Type", "")
                                    ts = int(data.get("Timestamp", 0))
                                    event_types_seen.add(et)
                                    if et and et not in _KNOWN_EVENT_TYPES and et not in logged_unknown:
                                        logged_unknown.add(et)
                                        logger.info("ADP 续接 SSE 未知事件: Type=%s", et)
                                    if ts > 0:
                                        end_ts = ts
                                    if et == "text.delta":
                                        chunk = _fix_encoding(data.get("Text", ""))
                                        full_text += chunk
                                        new_text_len += len(chunk)
                                    elif et == "text.replace":
                                        raw = _fix_encoding(data.get("Text", ""))
                                        if '"ok"' in raw and '"html"' in raw:
                                            try:
                                                closeout_data = json.loads(raw)
                                            except json.JSONDecodeError:
                                                pass
                                    elif et == "content.added":
                                        content = data.get("Content", {})
                                        if content.get("Type") == "file":
                                            finfo = content.get("File", {})
                                            fname = finfo.get("FileName", "")
                                            furl = finfo.get("FileUrl", "")
                                            file_urls.append({"name": fname, "url": furl})
                                            if fname.endswith(".html"):
                                                logger.info("ADP 续接 SSE 捕获 HTML 文件: %s", fname)
                                logger.info("ADP 续接第 %d 轮完成: 新增 %d 字符, file_urls=%d, closeout=%s",
                                            round_idx + 1, new_text_len, len(file_urls), closeout_data is not None)
                    finally:
                        client2.close()
                except Exception as e:
                    logger.warning("ADP 续接会话第 %d 轮失败: %s", round_idx + 1, e)
                    break
                # 有报告信号了，不再等待
                if _has_downloadable_report():
                    logger.info("ADP 续接第 %d 轮检测到 HTML 报告信号", round_idx + 1)
                    break
                # 无变化，不再等待
                has_change = (len(full_text) > prev_text_len or len(file_urls) > prev_file_count)
                if not has_change:
                    logger.info("ADP 续接第 %d 轮无新内容，停止等待", round_idx + 1)
                    break
    elapsed_sec = (end_ts - start_ts) / 1000 if start_ts and end_ts else 0
    # trace_id 兑底：从 closeout_data 或 payload 中获取
    if not trace_id and closeout_data:
        for tid_key in ("trace_id", "TraceId", "TraceID", "conversation_id", "ConversationId"):
            v = closeout_data.get(tid_key, "")
            if v:
                trace_id = str(v)
                break
    if not trace_id:
        trace_id = payload.get("ConversationId", "")
    logger.info("ADP 分析完成: %d 字符, 耗时 %.0fs, trace_id=%s, SSE 事件类型: %s",
                len(full_text), elapsed_sec, trace_id, sorted(event_types_seen))
    return full_text, file_urls, closeout_data, start_ts, end_ts, trace_id, _build_signal(
        error_code, error_msg, reply_method, response_status, has_cards, request_ack, stream_exc, conversation_id=conv_seen)


def call_adp_sse(message: str) -> tuple:
    """调用 ADP v2 SSE 接口（兼容旧调用）"""
    return call_adp_sse_stream(message)


# ===== Step 3: 提取分析结果 =====

def _extract_problem_module(text: str) -> str:
    """从分析文本中提取问题模块（归位/问题所在域）"""
    # ADP 专有模式：全文搜索取最后匹配（高度特异，不会误匹配中间文本）
    adp_patterns = [
        r"断点模块[：:：]\s*(.+?)(?:（pid|\(pid|\n|$)",       # ADP 标准格式
    ]
    for p in adp_patterns:
        matches = re.findall(p, text, re.IGNORECASE)
        if matches:
            return matches[-1].strip("*").strip()
    # 通用模式：仅搜索末尾 5000 字符（避免误匹配中间分析文本）
    tail = text[-5000:] if len(text) > 5000 else text
    generic_patterns = [
        r"问题在\s*\*?\*?(上游[^\uff0c\u3002\n]+|车端[^\uff0c\u3002\n]+|云端[^\uff0c\u3002\n]+)",
        r"归位[：:]\s*(\S+)",
        r"归位.*?(external|internal|上游|车端|云端)",
        r"问题所在模块[：:：]*\s*[\*]*(.+?)[\*]*(?:\n|$)",
        r"问题(?:归属|所在|模块)[^\n]*[：:：]\s*(.+?)(?:\n|$)",
        r"(?:归因|归属|定位|问题域|责任方)[：:：]\s*(.+?)(?:\n|$)",
        r"(?:属于|定位到|定位在|归因于|归到)\s*(.{4,40}?)(?:[\uff0c\u3002\n。]|$)",
    ]
    for p in generic_patterns:
        m = re.search(p, tail, re.IGNORECASE)
        if m:
            return m.group(1).strip("*").strip()
    return ""


def _extract_module_from_html(html_path: str) -> str:
    """从 HTML 报告中提取断点模块/现象承载模块值（优先级最高）"""
    if not html_path or not os.path.isfile(html_path):
        return ""
    try:
        with open(html_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        # HTML 结构：<strong>断点模块：</strong>值<br> 或 <strong>现象承载模块：</strong>值<br>
        for kw in ("断点模块", "现象承载模块"):
            m = re.search(
                rf'<strong>\s*{kw}[：:]\s*</strong>\s*(.+?)(?:<br|<strong|</div)',
                content, re.DOTALL)
            if m:
                val = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                if val:
                    return val
        # 降级纯文本匹配
        for kw in ("断点模块", "现象承载模块"):
            m = re.search(rf'{kw}[：:：]\s*(.+?)(?:\n|$)', content)
            if m:
                val = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                if val:
                    return val
    except Exception:
        pass
    return ""


def _extract_root_cause(text: str) -> str:
    """从分析文本中提取 root cause（支持 ADP 根因归属、现象级归因、定位归因等格式）"""
    # ADP 专有模式：全文搜索取最后匹配（高度特异）
    adp_patterns = [
        r"根因归属[：:：]\s*(.+?)(?:\n|$)",                 # ADP 标准格式
        r"现象级归因[：:：]\s*(.+?)(?:\n|$)",                # ADP 现象级归因
        r"##\s*定位归因[^\n]*\n+\*\*结论\*\*[：:：]\s*(.+?)(?:\n|$)",  # 定位归因 + **结论**：
        r"###\s*归因[（(][^\n)]*[）)]\s*\n+(.{10,300}?)(?:\n\n|\n(?=###)|$)",  # ### 归因（为什么断）
    ]
    for p in adp_patterns:
        matches = re.findall(p, text, re.IGNORECASE)
        if matches:
            val = matches[-1].strip()
            # 清除 HTML 标签残留
            val = re.sub(r'<[^>]+>', '', val).strip()
            return val
    # 通用模式：仅搜索末尾 5000 字符
    tail = text[-5000:] if len(text) > 5000 else text
    generic_patterns = [
        r"结论[：:：]\s*(.+?)(?:\n|$)",
        r"\*\*结论\*\*[：:：]\s*(.+?)(?:\n|$)",              # **结论**：加粗格式
        r"根因[：:：]\s*(.+?)(?:\n|$)",
        r"根本原因[：:：]\s*(.+?)(?:\n|$)",
        r"根本原因[是：:：]\s*(.+?)(?:\*\*|\n)",
        r"root\s*cause[：:：]\s*(.+?)(?:\n|$)",
        r"分析结论[^\n]*\n+(.{10,200}?)(?:\n\n|$)",
        r"##\s*结论\s*\n+(.{10,200}?)(?:\n\n|$)",
        r"诊断结论[：:：]*\s*(.+?)(?:\n|$)",
        r"(?:最终|总结|收案)[^\n]*结论[：:：]*\s*(.{10,200}?)(?:\n|$)",
        r"(?:rootcause|根因分析|故障原因|问题原因)[：:：]\s*(.{5,200}?)(?:\n|$)",
        r"判定[：:：]\s*(.{10,200}?)(?:\n|$)",
    ]
    for p in generic_patterns:
        m = re.search(p, tail, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            val = re.sub(r'<[^>]+>', '', val).strip()
            return val
    return ""


def _extract_confidence(text: str) -> str:
    """从分析文本中提取置信度（支持多种格式，返回值范围 0~1 的小数或百分比）

    修复：旧版 ``[0-9]+\\.?[0-9]*`` 在 'confidence 我给 0.7' 等中文间隔场景下
    findall 最后一条可能为空匹配，导致返回空字符串。
    新版策略：只取有效数值匹配，并做 0~1 范围校验。
    """
    # 精确模式（高优先级，有明确分隔符）
    precise_patterns = [
        r"自评置信度\s*([0-9]+\.?[0-9]*)",                # 自评置信度 0.85
        r"置信度\s*[:：：]\s*自评\s*([0-9]+\.?[0-9]*)",     # 置信度：自评 0.85
        r"confidence\s*[=：:]\s*([0-9]+\.?[0-9]*)",       # confidence=0.7 / confidence: 0.7
        r"置信度\s*[:：：]?\s*([0-9]+\.?[0-9]*)",          # 置信度 0.85
        r"置信度\s*[:：：]?\s*([0-9]+%)",                  # 置信度 85%
    ]
    # 宽松模式（ADP 特有格式：中文间隔、上下文提及）
    loose_patterns = [
        r"confidence\s*[给为定填评]\s*([0-9]+\.?[0-9]*)",  # confidence 我给 0.7 / confidence 定为 0.8
        r"confidence\s+(?:should\s+be\s+)?([0-9]\.[0-9]+)",  # confidence 0.7 / confidence should be 0.8
        r"conf(?:idence)?\s*[=：:]\s*([0-9]\.[0-9]+)",     # conf=0.7 / conf: 0.8
        r"置信\s*[:：：]?\s*([0-9]+\.?[0-9]*)",            # 置信 0.85 / 置信：0.85（无"度"字）
    ]
    # 第一步：精确模式全文搜索，取最后匹配
    for p in precise_patterns:
        matches = re.findall(p, text, re.IGNORECASE)
        # 过滤空匹配和无效值
        valid = [m for m in matches if m and m not in ("0", "0.0")]
        if valid:
            return _validate_confidence(valid[-1])
    # 第二步：宽松模式全文搜索，取最后匹配
    for p in loose_patterns:
        matches = re.findall(p, text, re.IGNORECASE)
        valid = [m for m in matches if m]
        if valid:
            return _validate_confidence(valid[-1])
    return ""


def _validate_confidence(raw: str) -> str:
    """校验置信度值有效性，返回规范化字符串或空串"""
    if not raw:
        return ""
    # 百分比格式
    if raw.endswith("%"):
        try:
            v = float(raw[:-1])
            return raw if 0 < v <= 100 else ""
        except ValueError:
            return ""
    # 小数格式
    try:
        v = float(raw)
        if 0 < v <= 1:
            return raw
        if 1 < v <= 100:
            # 可能是百分数漏了%，转换
            return f"{v / 100:.2f}"
        return ""
    except ValueError:
        return ""


def _extract_report_url(text: str, file_urls: list) -> tuple:
    """从文本或 file_urls 中提取报告链接（兼容三种域名 + lke 短链 + 沙箱路径）
    优先级（签名 URL 始终优先于无签名 URL，避免 403 Forbidden）：
      1a) reply 文本中 agent.adp-cos.com 的直签 CDN URL（含 q-signature）
      1b) reply 文本中 agent.adp-cos.com 无签名 URL（降级，可能 403）
      2)  reply 文本中 lke.cloud.tencent.com/s/xxx 分享短链（302 → COS 签名 URL）
      3)  file_urls 中带签名的 .html 文件（content.added 事件）
      3b) file_urls 中无签名的 .html 文件（降级兜底）
      4)  文本中的沙箱报告路径（sandbox.adp，401 不可下载，仅作链接展示）
    返回: (html_filename, direct_url)
    """
    # 1. agent.adp-cos.com CDN URL（区分签名/无签名）
    signed_url, signed_name = "", ""
    unsigned_url, unsigned_name = "", ""
    for m in re.finditer(r'(https?://agent\.adp-cos\.com/[^\s)"\']*(?:report_|out/)[^\s)"\']*\.html[^\s)"\']*)', text):
        url = m.group(1)
        name_m = re.search(r'(report_[^\s)"\'/?]*\.html)', url)
        name = name_m.group(1) if name_m else url.split("/")[-1].split("?")[0]
        if "q-sign" in url and not signed_url:
            signed_url, signed_name = url, name
        elif "q-sign" not in url and not unsigned_url:
            unsigned_url, unsigned_name = url, name
    # 签名 URL 优先（无签名的裸路径会被 COS 拒绝返回 403）
    if signed_url:
        return signed_name, signed_url
    # 2. lke.cloud.tencent.com/s/xxx 分享短链（302 跳转到 COS 签名 URL）
    m = re.search(r'(https?://lke\.cloud\.tencent\.com/s/[A-Za-z0-9]+)', text)
    if m:
        url = m.group(1)
        name = re.search(r'(report_[A-Za-z0-9_\-]+\.html)', text[max(0, m.start() - 500):m.end() + 200])
        return (name.group(1) if name else "adp_report.html"), url
    # 3. file_urls（content.added 事件），同样签名优先
    signed_fu, unsigned_fu = None, None
    for f in (file_urls or []):
        name = f.get("name", "")
        url = f.get("url", "")
        if name.endswith(".html") and "meta" not in name.lower() and url:
            if "q-sign" in url and not signed_fu:
                signed_fu = (name, url)
            elif not unsigned_fu:
                unsigned_fu = (name, url)
    if signed_fu:
        return signed_fu
    if unsigned_fu:
        return unsigned_fu
    # 1b 降级：文本中无签名的 agent.adp-cos.com URL（可能 403）
    if unsigned_url:
        return unsigned_name, unsigned_url
    # 4. 沙箱报告路径（sandbox.adp，401 不可下载，仅作为链接展示）
    # 4a. 已有完整 sandbox URL
    m = re.search(r'(https?://sandbox\.adp\.cloud\.tencent\.com/files\?path=[^\s)"\']*report_[^\s)"\']*\.html)', text)
    if m:
        url = m.group(1)
        name = re.search(r'(report_[^\s)"\'/?]*\.html)', url)
        return (name.group(1) if name else "report.html"), url
    # 4b. 文本中的沙箱报告路径（如 /workdir/case_.../out/report_full_....html）
    m = re.search(r'(/workdir/case_[A-Za-z0-9_\-]+/out/(report_[A-Za-z0-9_\-]+\.html))', text)
    if m:
        path, name = m.group(1), m.group(2)
        return name, f"https://sandbox.adp.cloud.tencent.com/files?path={path}"
    return "", ""


# ===== 回复形态判断辅助函数 =====

def _looks_truncated(reply: str) -> bool:
    """疑似截断：三条件同时成立（长文 + 无收尾章节 + 非终止符结尾）"""
    if len(reply) < 2000:
        return False
    if any(k in reply for k in COMPLETE_SECTION_MARKERS):
        return False
    return reply.rstrip()[-1:] not in "。！？!?…）)】」》\"'"


def _looks_like_clarify_or_refusal(reply: str, reply_method: str) -> tuple:
    """智能体正常收口但在等用户补充/拒答 → 发"继续"无意义。
    返回 (is_clarify_or_refusal, reason)"""
    # 平台结构化信号优先于文本猜测
    if reply_method in NO_REPORT_REPLY_METHODS:
        if reply_method == "3":
            return True, "ReplyMethod=3（智能体拒答）"
        return True, "ReplyMethod=15（澄清确认，智能体在等用户补充信息）"
    # 文本关键词兜底（仅短篇回复 < 4000 字时生效）
    hit_c = [k for k in CLARIFY_KEYWORDS if k in reply]
    if hit_c and len(reply) < 4000:
        return True, "澄清/索取信息话术: %s" % ",".join(hit_c[:3])
    hit_r = [k for k in REFUSAL_KEYWORDS if k in reply]
    if hit_r and len(reply) < 4000:
        return True, "拒答话术: %s" % ",".join(hit_r[:3])
    return False, ""


def _looks_complete_no_report(reply: str) -> bool:
    """分析主体完整但缺报告链接（≥ 800 字且命中 ≥ 2 个收尾章节标志）"""
    if len(reply) < 800:
        return False
    hits = [k for k in COMPLETE_SECTION_MARKERS if k in reply]
    return len(hits) >= 2


# 过程叙述关键词：出现 ≥2 个且无报告时，判为“还在干活”，值得再发一轮“继续”
PROCESS_NARRATION_KEYWORDS = [
    "让我", "我先", "我将", "现在", "接下来", "继续下载", "重新下载", "重试",
    "manifest", "预热", "report_data", "baseline", "verdict", "schema", "再看",
]


def _looks_like_process_narration(reply: str) -> bool:
    """疑似“过程叙述”：文本不长不短、带多个进行时关键词"""
    if not reply or len(reply) < 300:
        return False
    hits = [k for k in PROCESS_NARRATION_KEYWORDS if k in reply]
    return len(hits) >= 2


# 错误分类（对外统一写入的短分类，避免长句影响筛选/统计）
FAILURE_CATEGORIES = ["澄清", "拒答", "分析超时", "分析未完成", "无日志附件",
                      "附件接口异常", "报告未产出", "平台限流", "平台配置错误",
                      "会话冲突", "网络异常", "分析失败"]

_CATEGORY_RULES = [
    (("追问", "澄清"), "澄清"),
    (("拒答",), "拒答"),
    (("模型超时", "分析超时", "超时自动取消"), "分析超时"),
    (("截断", "分析过程未完成", "流异常", "未完成", "收口无报告"), "分析未完成"),
    (("无日志附件",), "无日志附件"),
    (("附件接口异常",), "附件接口异常"),
    (("报告渲染", "未产出HTML", "报告链接", "下载链接失效"), "报告未产出"),
    (("限流", "并发超限", "容量"), "平台限流"),
    (("配置错误", "安全拦截", "余额"), "平台配置错误"),
    (("会话冲突",), "会话冲突"),
    (("连接超时", "网络异常"), "网络异常"),
]


def short_failure_category(detail: str) -> str:
    """把详细归因映射成统一短分类（澄清/拒答/分析超时/...）"""
    text = str(detail or "")
    for keywords, category in _CATEGORY_RULES:
        if any(k in text for k in keywords):
            return category
    return "分析失败"


def classify_adp_failure(error: str = "", full_text: str = "", attachment_count: int = 0,
                         signal_info: dict = None) -> str:
    """根据错误信息、分析返回内容和 SSE 信号，自动归类 ADP 分析失败原因"""
    sig = signal_info or {}
    error_code = sig.get("error_code", "")
    reply_method = sig.get("reply_method", "")
    has_cards = sig.get("has_cards", False)
    stream_exc = sig.get("stream_exc", "")

    # ---- 1. 致命错误码（配置/账号级问题）----
    if error_code in FATAL_ERROR_CODES:
        code_map = {
            "4505004": "AppKey 无效",
            "460001": "Token 校验失败",
            "460004": "应用不存在",
            "460026": "应用停用或欠费",
            "460048": "应用未发布",
            "460501": "输入内容安全拦截",
            "460502": "输出内容安全拦截",
            "460032": "模型余额不足",
            "460702": "专属模型余额不足",
        }
        return "ADP平台配置错误: %s(%s)" % (code_map.get(error_code, "未知"), error_code)

    # ---- 2. 限流错误（并发/容量超限）----
    if error_code in RATE_LIMIT_CODES:
        return "ADP并发限流(%s)" % error_code
    if error_code in CAPACITY_LIMIT_CODES:
        return "ADP容量限流(%s)" % error_code

    # ---- 2b. 可重试错误（模型超时等）----
    if error_code in RETRYABLE_ERROR_CODES:
        return "ADP模型超时(%s)" % error_code

    # ---- 2c. 会话冲突（需换ID重试）----
    if error_code in SESSION_CONFLICT_CODES:
        return "ADP会话冲突(%s)" % error_code

    # ---- 3. 追问卡片（智能体在等用户作答）----
    if has_cards:
        return "ADP智能体追问（需人工作答）"

    # ---- 4. ReplyMethod 判断（拒答/澄清/并发超限）----
    if reply_method == CONCURRENT_LIMIT_REPLY:
        return "ADP并发超限(ReplyMethod=7)"
    if reply_method in NO_REPORT_REPLY_METHODS and full_text:
        is_cr, reason = _looks_like_clarify_or_refusal(full_text, reply_method)
        if is_cr:
            return "ADP智能体收口无报告(%s)" % reason

    # ---- 5. 前置条件不满足 ----
    if error in ("无附件", "无日志附件") or error.startswith("没有日志附件"):
        return "无日志附件"
    if error == "ADP附件接口异常":
        return "ADP附件接口异常"
    if error == "ADP 无返回":
        return "ADP连接超时或网络异常"

    # ---- 6. 分析 ADP 返回的 full_text ----
    if full_text:
        text_short = full_text[:2000]
        text_lower = text_short.lower()
        # 回复形态判断：截断
        if _looks_truncated(full_text):
            return "ADP分析输出被截断(%d字、无收尾章节)" % len(full_text)
        # 回复形态判断：澄清/拒答（文本关键词）
        is_cr, reason = _looks_like_clarify_or_refusal(full_text, reply_method)
        if is_cr:
            return "ADP智能体收口无报告(%s)" % reason
        # 回复形态判断：主体完整但无报告
        if _looks_complete_no_report(full_text):
            return "ADP报告渲染环节异常(分析主体完整但无报告链接)"
        # 输入质量问题（ADP 短文本回复，要求澄清/补充）
        if len(full_text) < 1500:
            if any(kw in text_short for kw in ("日志附件下载链接", "日志包路径", "日志包下载链接")) \
               and any(kw in text_short for kw in ("缺失", "空", "补充", "请提供", "请补充")):
                return "输入质量问题（日志附件链接为空）"
            for kw in ("请先明确", "请先确认", "确认", "无法启动", "矛盾", "不一致", "不明确"):
                if kw in text_short:
                    return "输入质量问题（描述矛盾或信息不足）"
        # 下载链接失效（含 404 / 传输中断 / 体积对账误判）
        if ("404" in text_short and ("下载" in text_short or "链接" in text_short)) or "链接已失效" in text_short:
            return "下载链接失效"
        if ("rc=18" in text_short or "transfer closed" in text_lower or "下载中断" in text_short) \
            and "残件" in text_short:
            return "下载链接失效（传输中断）"
        if "expect=46" in text_short or ("体积对账" in text_short and "误判" in text_short):
            return "下载链接失效（签名URL响应异常）"
        # 分析过程未完成
        if any(kw in text_short for kw in ("下载", "解包", "索引", "fetch_raw", "unpack")) \
           and len(full_text) > 3000:
            return "分析过程未完成"

    # ---- 7. 流异常 / 连接超时 ----
    if stream_exc:
        return "ADP流异常: %s" % stream_exc[:100]
    err_lower = (error or "").lower()
    if "connect" in err_lower or "timed out" in err_lower or "timeout" in err_lower:
        return "ADP连接超时或网络异常"
    return "分析完成但未产出HTML报告"


def extract_adp_results(full_text: str, closeout_data: dict, start_ts: int, end_ts: int, file_urls: list = None) -> dict:
    """从 ADP 返回内容中提取需要写入飞书的 6 个字段"""
    result = {"完成状态": "完成"}
    # 报告链接（多来源提取）
    html_file, report_url = _extract_report_url(full_text, file_urls or [])
    if report_url:
        _has_sig = "q-sign" in report_url
        logger.info("ADP 报告URL提取: %s (签名=%s, 来源=%s)", html_file, _has_sig,
                     "file_urls签名" if _has_sig and "agent-file" in report_url else
                     "reply文本签名" if _has_sig else "无签名降级")
        result["报告链接（分析报告、可观测报告）"] = report_url
    elif html_file:
        result["报告链接（分析报告、可观测报告）"] = html_file
    # 置信度：优先 closeout_data，其次从文本提取，最后校验
    confidence = ""
    if closeout_data:
        raw_conf = closeout_data.get("confidence")
        if raw_conf is not None:
            confidence = _validate_confidence(str(raw_conf))
    if not confidence:
        confidence = _extract_confidence(full_text)
    result["置信度"] = confidence
    # 耗时(分)
    if start_ts and end_ts:
        elapsed_min = round((end_ts - start_ts) / 1000 / 60, 1)
        result["耗时(分)"] = str(elapsed_min)
    # 问题模块 + root cause
    problem_module = _extract_problem_module(full_text)
    result["agent分析的问题模块"] = problem_module
    result["agent分析的root cause"] = _extract_root_cause(full_text)
    # 额外返回报告直链（供前端展示，不写入飞书）
    result["_report_url"] = report_url
    result["_html_file"] = html_file
    return result


# ===== Step 4: 保存本地文件 =====

def save_adp_local(jira_key: str, full_text: str, closeout_data: dict,
                   file_urls: list = None, description: str = "", trigger_time: str = "",
                   attachment_count: int = 0, results: dict = None, elapsed_sec: float = 0,
                   trace_id: str = "") -> str:
    """保存完整分析报告到本地 docs/adp_results/{jira_key}/"""
    adp_cfg = _get_adp_cfg()
    save_dir = get_path("doc_dir") if adp_cfg["save_dir"] == "docs/adp_results" else adp_cfg["save_dir"]
    out_dir = os.path.join(save_dir, "adp_results", jira_key)
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 保存完整分析 MD
    analysis_path = os.path.join(out_dir, f"{jira_key}_full_analysis.md")
    with open(analysis_path, "w", encoding="utf-8-sig") as f:
        f.write(f"# {jira_key} ADP 分析报告\n\n")
        f.write(f"> 生成时间: {ts}\n\n")
        # 入参
        f.write("## 入参\n\n")
        f.write(f"- **Jira号**: {jira_key}\n")
        f.write(f"- **描述**: {description[:300]}{'...' if len(description) > 300 else ''}\n")
        f.write(f"- **触发时间**: {trigger_time}\n")
        f.write(f"- **附件数**: {attachment_count}\n")
        f.write(f"- **耗时**: {elapsed_sec:.1f}s\n")
        if trace_id:
            f.write(f"- **Trace ID**: {trace_id}\n")
        f.write("\n")
        # 提取结果
        if results:
            f.write("## 提取结果\n\n")
            for k, v in results.items():
                if k.startswith("_"):  # 跳过内部字段
                    continue
                f.write(f"- **{k}**: {v}\n")
            report_url = results.get("_report_url", "")
            if report_url:
                f.write(f"\n报告下载: {report_url}\n")
            f.write("\n")
        # closeout_data
        if closeout_data:
            f.write("## Closeout Data\n\n")
            f.write(f"```json\n{json.dumps(closeout_data, ensure_ascii=False, indent=2)}\n```\n\n")
        # file_urls
        if file_urls:
            f.write("## 文件链接\n\n")
            for fu in file_urls:
                name = fu.get("name", "")
                url = fu.get("url", "")
                f.write(f"- [{name}]({url})\n" if url else f"- {name}\n")
            f.write("\n")
        # 完整分析文本
        f.write("---\n\n## 完整分析文本\n\n")
        f.write(full_text)
    # 保存原始结构化数据 JSON
    raw_path = os.path.join(out_dir, f"{jira_key}_raw_data.json")
    raw_data = {
        "jira_key": jira_key,
        "description": description[:500],
        "trigger_time": trigger_time,
        "attachment_count": attachment_count,
        "elapsed_sec": elapsed_sec,
        "trace_id": trace_id,
        "closeout_data": closeout_data,
        "file_urls": file_urls or [],
        "results": {k: v for k, v in (results or {}).items() if not k.startswith("_")},
        "_report_url": (results or {}).get("_report_url", ""),
        "full_text_length": len(full_text),
        "saved_at": ts,
    }
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)
    logger.info("ADP 本地保存: %s (raw: %s)", analysis_path, raw_path)
    return out_dir


# ===== 下载 HTML 报告并上传多维表格附件 =====

def download_adp_report(jira_key: str, report_url: str, html_file: str) -> dict:
    """下载 ADP HTML 报告到本地，再上传为多维表格附件，返回 {file_token, local_path, error_code}"""
    from src.config import PROJECT_ROOT
    from src.clients import feishu_client
    if not report_url:
        return {"file_token": "", "local_path": "", "error_code": ""}
    save_dir = os.path.join(PROJECT_ROOT, "reports", "adp", jira_key)
    os.makedirs(save_dir, exist_ok=True)
    filename = html_file or report_url.split("/")[-1].split("?")[0]
    local_path = os.path.join(save_dir, filename)
    try:
        # Step 1: 下载到本地
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.get(report_url)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(resp.content)
        logger.info("ADP 报告下载成功: %s (%d bytes)", jira_key, len(resp.content))
        # Step 2: 上传为多维表格附件
        adp_cfg = _get_adp_cfg()
        file_token = feishu_client.upload_bitable_attachment(
            adp_cfg["bitable_app_token"], local_path, content_type="text/html")
        if file_token:
            logger.info("ADP 报告附件上传成功: %s -> %s", jira_key, file_token)
        return {"file_token": file_token, "local_path": local_path, "error_code": ""}
    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        logger.error("ADP 报告下载失败: %s -> HTTP %d (%s)", jira_key, status_code, e)
        return {"file_token": "", "local_path": "", "error_code": f"HTTP_{status_code}"}
    except Exception as e:
        logger.error("ADP 报告处理失败: %s -> %s", jira_key, e)
        return {"file_token": "", "local_path": "", "error_code": "OTHER"}


# ===== Step 5: 写入飞书多维表格（独立 ADP 表格）=====

def write_adp_to_feishu(jira_key: str, fields_dict: dict) -> dict:
    """写入 ADP 独立多维表格，返回 {ok, record_id, message}"""
    from src.clients import feishu_client
    adp_cfg = _get_adp_cfg()
    app_token = adp_cfg["bitable_app_token"]
    table_id = adp_cfg["bitable_table_id"]
    jira_field = adp_cfg["jira_field"]
    if not app_token or not table_id:
        return {"ok": False, "record_id": "", "message": "ADP 多维表格未配置"}
    try:
        # 查找已有记录
        records = feishu_client.list_bitable_records(app_token, table_id)
        record_id = None
        for item in records:
            fv = item.get("fields", {}).get(jira_field, "")
            if isinstance(fv, list) and fv:
                fv_text = fv[0].get("text", "") if isinstance(fv[0], dict) else str(fv[0])
            else:
                fv_text = str(fv)
            if jira_key in fv_text:
                record_id = item.get("record_id", "")
                break
        # 不存在则新建
        if not record_id:
            created = feishu_client.batch_create_records(app_token, table_id, [{"fields": {jira_field: jira_key}}])
            recs = ((created or {}).get("data") or {}).get("records") or []
            record_id = recs[0].get("record_id", "") if recs else ""
        if not record_id:
            return {"ok": False, "record_id": "", "message": "无法获取 record_id"}
        # 写入字段白名单
        allowed = ["完成状态", "报告链接（分析报告、可观测报告）", "耗时(分)",
                    "agent分析的问题模块", "agent分析的root cause", "root cause",
                    "置信度", "分析失败归因", "原因", "traceid", "traceid排查"]
        write_fields = {k: v for k, v in fields_dict.items() if k in allowed}
        # 确保 root cause 字段也被填充（与 agent分析的root cause 同步）
        adp_rc = write_fields.get("agent分析的root cause", "")
        if adp_rc:
            write_fields["root cause"] = adp_rc
        # traceid排查 是 URL 类型字段，必须用 {link, text} 格式，空值则移除
        tid_check = write_fields.get("traceid排查", "")
        if tid_check and isinstance(tid_check, str) and tid_check.startswith("http"):
            write_fields["traceid排查"] = {"link": tid_check, "text": tid_check}
        else:
            write_fields.pop("traceid排查", None)
        # 附件字段"报告链接"处理：file_token 为附件格式，沙箱 URL 不写入附件字段（链接已追加到 root cause）
        file_token = fields_dict.get("_report_file_token", "")
        report_url = fields_dict.get("_report_url", "")
        is_sandbox = bool(report_url and "sandbox.adp" in report_url)
        if file_token:
            write_fields["报告链接（分析报告、可观测报告）"] = [{"file_token": file_token}]
        else:
            write_fields.pop("报告链接（分析报告、可观测报告）", None)
            if report_url and not is_sandbox:
                existing = write_fields.get("分析失败归因", "") or ""
                suffix = f"\n报告链接（下载受限）: {report_url}"
                write_fields["分析失败归因"] = (existing + suffix).strip()
        feishu_client.update_bitable_records(app_token, table_id,
                                              [{"record_id": record_id, "fields": write_fields}])
        logger.info("ADP 飞书写入成功: %s -> %s", jira_key, list(write_fields.keys()))
        return {"ok": True, "record_id": record_id, "message": "写入成功", "fields": write_fields}
    except Exception as e:
        logger.error("ADP 飞书写入失败: %s -> %s", jira_key, e)
        return {"ok": False, "record_id": "", "message": str(e)}


# ===== 完整单条执行流程 =====

def _save_adp_fail_snapshot(jira_key: str, full_text: str, description: str = "",
                            trigger_time: str = "", error: str = "", results: dict = None) -> str:
    """失败时保存快照（含完整 ADP 返回内容），返回 md 路径供前端「查看完整报告」

    失败场景下完整文本同样有价值（能看出 ADP 分析到哪一步断的），
    因此这里不做截断，整段写入文件。
    """
    adp_cfg = _get_adp_cfg()
    save_dir = get_path("doc_dir") if adp_cfg["save_dir"] == "docs/adp_results" else adp_cfg["save_dir"]
    out_dir = os.path.join(save_dir, "adp_results", jira_key)
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"{jira_key}_fail_{ts}.md")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(f"# {jira_key} ADP 分析失败\n\n> 时间: {ts}\n\n")
        f.write(f"## 错误信息\n\n{error or '-'}\n\n")
        if description:
            f.write(f"## 问题描述\n\n{description}\n\n")
        if trigger_time:
            f.write(f"## 触发时间\n\n{trigger_time}\n\n")
        if results:
            clean = {k: v for k, v in results.items() if not str(k).startswith("_")}
            f.write("## 已提取字段\n\n```json\n")
            f.write(json.dumps(clean, ensure_ascii=False, indent=2, default=str))
            f.write("\n```\n\n")
        f.write("## ADP 返回内容\n\n")
        f.write(full_text or "（无返回内容）")
    logger.info("ADP 失败快照已保存: %s（%d 字）", path, len(full_text or ""))
    return path


def run_adp_single(jira_key: str, description: str, trigger_time: str, progress_cb=None, keepalive_cb=None, skip_feishu: bool = False, stop_event=None) -> dict:
    """
    完整 ADP 分析流程（单条）
    :param progress_cb: 可选回调 fn(step_name, status, detail) 用于 SSE 推送
    :param keepalive_cb: 可选回调 fn(elapsed_sec)，ADP 分析期间每 30s 触发
    :param stop_event: 可选 threading.Event，设置后尽快中止分析
    :return: {ok, jira_key, description, trigger_time, attachment_count, results, feishu, elapsed_sec, error}
    """
    import time
    t0 = time.time()
    out = {"ok": False, "jira_key": jira_key, "description": description, "trigger_time": trigger_time}
    signal_info = {}  # SSE 判别信号（reply_method / response_status 等），失败时写入 error 便于排查

    def _progress(step, status, detail=""):
        if progress_cb:
            progress_cb(step, status, detail)

    # Step 1: 查附件
    _progress("attachments", "running")
    attachments = query_attachments(jira_key)
    # 接口异常（非 JSON/网关错误）：不是“无附件”，标分析失败，交由人工/下次重跑
    if attachments is None:
        out["error"] = "ADP附件接口异常"
        out["results"] = {"完成状态": "分析失败", "分析失败归因": "ADP附件接口异常"}
        out["fail_type"] = "ADP附件接口异常"
        _progress("attachments", "fail", "附件接口异常")
        return out
    out["attachment_count"] = len(attachments)
    # 确实没有附件：无法分析，不重试，直接下一条
    if not attachments:
        out["error"] = "无日志附件"
        out["results"] = {"完成状态": "无法分析", "分析失败归因": "无日志附件"}
        out["fail_type"] = "无日志附件"
        _progress("attachments", "fail", "无日志附件")
        return out
    # 检查过滤后是否有有效日志附件
    valid_atts = [a for a in attachments if _is_valid_attachment(a)]
    if not valid_atts:
        file_names = [a.get('filename', '?') for a in attachments]
        out["error"] = "无日志附件"
        out["results"] = {"完成状态": "无法分析", "分析失败归因": "无日志附件"}
        out["fail_type"] = "无日志附件"
        _progress("attachments", "fail", f"无日志附件（已有: {', '.join(file_names[:5])}）")
        return out
    _progress("attachments", "done", f"{len(valid_atts)} 个有效附件（共 {len(attachments)} 个）")

    # Step 2: 构建消息 + 调用 ADP
    _progress("adp_analysis", "running")
    message = build_adp_message(jira_key, description, trigger_time, attachments)
    full_text, file_urls, closeout_data, start_ts, end_ts, trace_id, signal_info = call_adp_sse_stream(
        message, keepalive_cb=keepalive_cb, stop_event=stop_event)
    out["trace_id"] = trace_id
    # 致命错误/限流早判：无需进入提取流程
    err_code = signal_info.get("error_code", "")
    if err_code in FATAL_ERROR_CODES:
        fail_reason = classify_adp_failure(error="", full_text="", signal_info=signal_info)
        out["error"] = fail_reason
        out["results"] = {"完成状态": "分析失败", "分析失败归因": fail_reason}
        out["fail_type"] = fail_reason
        _progress("adp_analysis", "fail", fail_reason)
        return out
    if not full_text:
        out["error"] = "ADP 无返回"
        out["results"] = {"完成状态": "分析失败", "分析失败归因": "ADP连接超时或网络异常"}
        out["fail_type"] = "ADP连接超时或网络异常"
        _progress("adp_analysis", "fail", "无返回")
        return out
    elapsed_sec = (end_ts - start_ts) / 1000 if start_ts and end_ts else 0
    out["elapsed_sec"] = round(elapsed_sec, 1)
    # 先记录预览：后续步骤即使失败，前端也能看到 ADP 返回内容
    out["text_len"] = len(full_text)
    out["text_preview"] = full_text[:2000]
    _progress("adp_analysis", "done", f"{len(full_text)} 字符, {elapsed_sec:.0f}s")

    try:
        # Step 3: 提取结果
        _progress("extract", "running")
        results = extract_adp_results(full_text, closeout_data, start_ts, end_ts, file_urls)
        out["results"] = results
        out["full_text"] = full_text  # 返回完整分析文本供前端展示
        out["file_urls"] = file_urls
        _progress("extract", "done", f"完成状态={results.get('完成状态', '')}")
        # 将 trace_id 写入结果（供飞书表格展示）
        if trace_id:
            results["traceid"] = trace_id
        # traceid 排查报告：优先 ADP 报告链接，其次沙箱链接，最后本地报告路径
        _report_url_for_trace = results.get("_report_url", "")
        _sandbox_for_trace = out.get("_sandbox_url", "")
        results["traceid排查"] = _report_url_for_trace or _sandbox_for_trace or ""

        # 前置判断：没有任何报告链接 → 标记“可疑未完成”，供续接与失败归因区分
        if not results.get("_report_url"):
            results["_suspected_unfinished"] = True
            logger.info("ADP 无报告链接，进入可疑未完成分支（%d 字）", len(full_text or ""))

        # Step 3.3: 续接机制（截断/无报告/过程叙述 → 发"继续"；限流/首轮未开工 → 重发原始消息）
        max_continues = 6
        for cont_idx in range(max_continues):
            # 前置判断：没有任何报告链接 → 视为"可疑未完成"，参与续接决策
            _no_report = not results.get("_report_url")
            _has_closing = any(k in full_text for k in COMPLETE_SECTION_MARKERS)
            _clarify, _ = _looks_like_clarify_or_refusal(full_text, signal_info.get("reply_method", ""))
            _short_no_report = (_no_report and not _clarify and not _has_closing)
            need_continue = (
                results.get("完成状态") == "分析失败"
                and results.get("分析失败归因") in (
                    "分析完成但未产出HTML报告", "未完成（疑似流中断）",
                )
                or _looks_truncated(full_text)
                or (not _clarify and _no_report and _looks_like_process_narration(full_text))
                or _short_no_report
                or err_code in RETRYABLE_ERROR_CODES
            )
            need_resend = (
                err_code in RATE_LIMIT_CODES
                or (not full_text and signal_info.get("request_ack")
                    and not signal_info.get("stream_exc"))
            )
            need_new_session = err_code in SESSION_CONFLICT_CODES
            if signal_info.get("has_cards") or signal_info.get("questionnaire"):
                # 智能体在追问用户（questionnaire/cards）：继续发“继续”没有意义
                results["完成状态"] = "分析失败"
                results["分析失败归因"] = "需要澄清（ADP智能体追问，需人工作答）"
                logger.warning("ADP 智能体追问，停止续接并归因需要澄清: %s", jira_key)
                _progress("adp_continue", "fail", "智能体追问，需补充信息")
                break
            if not need_continue and not need_resend and not need_new_session:
                break
            if need_new_session:
                # 会话冲突：换新会话ID重发原始消息
                new_conv_id = uuid.uuid4().hex[:32]
                _progress("adp_continue", "running", f"会话冲突({err_code})，换新ID重试")
                logger.warning("ADP 会话冲突 %s，换新会话ID %s 重试", err_code, new_conv_id[:12])
                cont_text, cont_urls, cont_close, _, _, cont_tid, cont_sig = call_adp_sse_stream(
                    message, keepalive_cb=keepalive_cb, stop_event=stop_event, conversation_id=new_conv_id)
            elif need_continue:
                # 续接必须复用原会话：优先用 response.created 里的 ConversationId
                _conv_use = signal_info.get("conversation_id") or trace_id
                _progress("adp_continue", "running", f"第{cont_idx+1}轮续接（发'继续'）")
                logger.info("ADP 分析疑似截断或完整无报告，第%d次续接（conv=%s）", cont_idx + 1, (_conv_use or "")[:12])
                cont_text, cont_urls, cont_close, _, _, cont_tid, cont_sig = call_adp_sse_stream(
                    "继续", keepalive_cb=keepalive_cb, stop_event=stop_event, conversation_id=_conv_use)
            else:
                if err_code in TPM_LIMIT_CODES:
                    backoff = 60          # TPM 墙：60 秒
                elif err_code in CAPACITY_LIMIT_CODES:
                    backoff = 300         # QPM/RPM：300 秒
                else:
                    backoff = 60          # 并发限流
                _progress("adp_continue", "running", f"限流退避{backoff}s后重发")
                logger.warning("ADP %s（%s），%ds后重发原始消息", err_code, signal_info.get("error_msg", "")[:60], backoff)
                # 可中断退避：每 0.5s 检查 stop_event
                _waited = 0.0
                while _waited < backoff:
                    if stop_event is not None and stop_event.is_set():
                        logger.info("ADP 限流退避等待中被停止")
                        return out
                    time.sleep(min(0.5, backoff - _waited))
                    _waited += 0.5
                _conv_use = signal_info.get("conversation_id") or trace_id
                cont_text, cont_urls, cont_close, _, _, cont_tid, cont_sig = call_adp_sse_stream(
                    message, keepalive_cb=keepalive_cb, stop_event=stop_event, conversation_id=_conv_use)
            # 合并结果
            full_text += ("\n" + cont_text) if cont_text else ""
            file_urls.extend(cont_urls)
            if cont_tid:
                trace_id = cont_tid  # 以最后一次续接的 traceid 为准
            _sig_conv = (cont_sig or {}).get("conversation_id") or ""
            if _sig_conv:
                signal_info["conversation_id"] = _sig_conv
            if cont_close:
                closeout_data = cont_close
            # 重新提取
            results = extract_adp_results(full_text, closeout_data, start_ts, end_ts, file_urls)
            if trace_id:
                results["traceid"] = trace_id
            out["text_len"] = len(full_text)
            out["text_preview"] = full_text[:2000]
            out["trace_id"] = trace_id
            if trace_id:
                results["traceid"] = trace_id
            out["results"] = results
            if results.get("_report_url"):
                logger.info("ADP 续接第%d次成功（%d字）", cont_idx + 1, len(full_text))
                _progress("adp_continue", "done", f"续接成功，{len(full_text)}字")
                break
            logger.warning("ADP 续接第%d次仍未产出报告", cont_idx + 1)
            _progress("adp_continue", "running", f"第{cont_idx+1}次续接仍无报告")
            # 更新 err_code 为本次续接返回的错误码
            err_code = (cont_sig or {}).get("error_code", "")
            # 致命错误（如 460502 内容安全拦截）：续接无意义，立即退出
            if err_code in FATAL_ERROR_CODES:
                logger.error("ADP 续接第%d次返回致命错误 %s，停止续接", cont_idx + 1, err_code)
                _progress("adp_continue", "fail", f"致命错误 {err_code}")
                break
            # 限流退避：避免连续请求再次触发限流
            if err_code in TPM_LIMIT_CODES:
                _backoff = 60
            elif err_code in CAPACITY_LIMIT_CODES or err_code in RATE_LIMIT_CODES:
                _backoff = 120
            else:
                _backoff = 0
            if _backoff > 0:
                logger.warning("ADP 续接触发限流 %s，退避 %ds 后重试", err_code, _backoff)
                _progress("adp_continue", "running", f"限流退避{_backoff}s")
                _waited = 0.0
                while _waited < _backoff:
                    if stop_event is not None and stop_event.is_set():
                        logger.info("ADP 限流退避等待中被停止")
                        return out
                    time.sleep(min(0.5, _backoff - _waited))
                    _waited += 0.5
        # 续接后仍无报告的最终归类
        if results.get("完成状态") == "分析失败" and not results.get("分析失败归因"):
            results["分析失败归因"] = classify_adp_failure(
                error=out.get("error", ""), full_text=full_text,
                attachment_count=len(attachments), signal_info=signal_info)

        # Step 3.5: 下载 HTML 报告到本地，上传为多维表格附件
        report_url = results.get("_report_url", "")
        html_file = results.get("_html_file", "")
        is_sandbox = bool(report_url and "sandbox.adp" in report_url)
        if report_url and not is_sandbox:
            _progress("download_report", "running")
            dl_result = download_adp_report(jira_key, report_url, html_file)
            file_token = dl_result.get("file_token", "")
            local_path = dl_result.get("local_path", "")
            error_code = dl_result.get("error_code", "")
            if file_token:
                results["_report_file_token"] = file_token
                results["报告链接（分析报告、可观测报告）"] = f"附件: {html_file or 'report.html'}"
                out["_report_file_token"] = file_token
            else:
                # 下载失败：根据错误码区分归类
                results["完成状态"] = "分析失败"
                if error_code == "HTTP_403":
                    results["分析失败归因"] = "报告下载被拒绝（403 Forbidden，签名URL可能已过期）"
                elif error_code.startswith("HTTP_4"):
                    results["分析失败归因"] = f"报告下载失败（{error_code}，链接可能已失效）"
                elif error_code.startswith("HTTP_5"):
                    results["分析失败归因"] = f"报告下载服务端错误（{error_code}）"
                else:
                    results["分析失败归因"] = "分析完成但未产出HTML报告"
                results.pop("报告链接（分析报告、可观测报告）", None)
            # HTML 报告中的"断点模块"优先级高于文本提取，覆盖"问题模块"字段
            html_module = _extract_module_from_html(local_path)
            if html_module:
                results["agent分析的问题模块"] = html_module
            _progress("download_report", "done" if file_token else "fail")
        elif is_sandbox:
            # 沙箱 URL 不可下载（401），保持完成状态，链接追加到 root cause 文本末尾
            rc = results.get("agent分析的root cause", "") or ""
            if report_url and report_url not in rc:
                results["agent分析的root cause"] = (rc + f"\n报告链接: {report_url}").strip()
            out["_sandbox_url"] = report_url
            _progress("download_report", "done", "沙箱链接（不可下载）")
        else:
            # 无任何报告链接：区分“未完成（疑似流中断）”与“分析完成但无报告”
            results["完成状态"] = "分析失败"
            _has_closing_text = any(k in full_text for k in COMPLETE_SECTION_MARKERS)
            _unfinished_hint = (
                bool(signal_info.get("stream_exc"))
                or _looks_like_process_narration(full_text)
                or (len(full_text or "") >= 300 and not _has_closing_text)
            )
            results["分析失败归因"] = (
                "未完成（疑似流中断）" if _unfinished_hint else "分析完成但未产出HTML报告"
            )
            results.pop("报告链接（分析报告、可观测报告）", None)

        # traceid 排查：仅成功（已拿到报告附件）时调用技能；失败时留空/用返回内容报告
        _trace_report, _trace_err, _trace_doc = ("", "", "")
        if results.get("_report_file_token"):
            _trace_report, _trace_err, _trace_doc = _run_trace_skill(jira_key, trace_id)
        if _trace_report:
            _base = str((_get_adp_cfg().get("trace_report_base") or "http://127.0.0.1:8060")).rstrip("/")
            results["traceid排查"] = _trace_doc or f"{_base}/api/test/adp_trace_report?jira_key={jira_key}"
            out["traceid_report_path"] = _trace_report
            out["traceid_report_doc_url"] = _trace_doc
        else:
            out["traceid_skill_error"] = _trace_err
            logger.warning("traceid 排查技能失败 %s: %s（回退 ADP 报告链接）", jira_key, _trace_err)
            if not results.get("traceid排查") and out.get("_sandbox_url"):
                results["traceid排查"] = out["_sandbox_url"]

        # 失败归因：分析失败但没有明确原因时，按 ADP 返回内容自动归类（失败类型）
        if results.get("完成状态") == "分析失败" and not results.get("分析失败归因"):
            results["分析失败归因"] = classify_adp_failure(
                error=out.get("error", ""), full_text=full_text,
                attachment_count=len(attachments), signal_info=signal_info)

        # Step 4: 保存本地
        _progress("save_local", "running")
        report_dir = save_adp_local(jira_key, full_text, closeout_data, file_urls,
                                    description=description, trigger_time=trigger_time,
                                    attachment_count=len(attachments), results=results,
                                    elapsed_sec=out.get("elapsed_sec", 0),
                                    trace_id=out.get("trace_id", ""))
        # 完整文本只落盘、不随响应回传：前端只拿预览 + 报告路径（避免几十 MB 的 SSE/JSON 响应）
        out["report_path"] = os.path.join(report_dir, f"{jira_key}_full_analysis.md") if report_dir else ""
        # 发布完整分析为飞书文档：服务关闭后仍可访问
        try:
            if out.get("report_path") and os.path.isfile(out["report_path"]):
                with open(out["report_path"], encoding="utf-8") as f:
                    _full_md = f.read()
                _rfolder = str(_get_adp_cfg().get("report_folder") or "")
                out["report_doc_url"] = _publish_md_to_feishu(f"{jira_key} ADP 分析报告", _full_md, folder_token=_rfolder)
        except Exception as _e:
            logger.warning("发布完整分析报告失败 %s: %s", jira_key, str(_e)[:120])
        _progress("save_local", "done")

        # Step 5: 写入飞书（可跳过，由调用方自行写回）
        if skip_feishu:
            _progress("write_feishu", "done", "跳过（由调用方写回）")
            out["feishu"] = {"ok": True, "record_id": "", "message": "跳过"}
            out["ok"] = bool(out.get("results", {}).get("_report_file_token", ""))
        else:
            _progress("write_feishu", "running")
            fs_result = write_adp_to_feishu(jira_key, results)
            out["feishu"] = fs_result
            _progress("write_feishu", "done" if fs_result["ok"] else "fail", fs_result["message"])
            out["ok"] = fs_result["ok"]
    except Exception as e:
        logger.error("ADP 后续处理失败 %s: %s", jira_key, e, exc_info=True)
        _results = out.get("results") or {}
        _results.setdefault("完成状态", "分析失败")
        _results.setdefault("分析失败归因", f"处理异常: {str(e)[:120]}")
        out["results"] = _results
        out["error"] = out.get("error") or f"处理异常: {str(e)[:200]}"
        out["ok"] = False
        # 失败也把 ADP 返回内容落盘，前端可点「查看完整报告」
        try:
            out["report_path"] = _save_adp_fail_snapshot(
                jira_key, full_text, description=description, trigger_time=trigger_time,
                error=out["error"], results=_results)
            _progress("save_local", "done")
        except Exception as save_err:
            logger.warning("保存 ADP 失败快照失败 %s: %s", jira_key, save_err)

    # 失败快照/异常报告也发布到飞书文件夹，保证「查看完整报告」长期可用
    if out.get("report_path") and not out.get("report_doc_url") and os.path.isfile(out["report_path"]):
        try:
            with open(out["report_path"], encoding="utf-8") as f:
                _fail_md = f.read()
            _rfolder = str(_get_adp_cfg().get("report_folder") or "")
            out["report_doc_url"] = _publish_md_to_feishu(
                f"{jira_key} ADP 分析报告（失败快照）", _fail_md, folder_token=_rfolder)
        except Exception as _e:
            logger.warning("发布失败快照失败 %s: %s", jira_key, str(_e)[:120])

    # 失败时不写 traceid；traceid排查 只放“返回内容”的报告链接
    if not out.get("ok"):
        _res = out.get("results") or {}
        _res.pop("traceid", None)
        _doc = out.get("report_doc_url") or ""
        if _doc:
            _res["traceid排查"] = _doc
        else:
            _res.pop("traceid排查", None)
        out["results"] = _res

    # 失败类型：成功时为空；失败时优先用已有归因，其次自动归类，保证前端总能拿到明确分类
    if out.get("ok"):
        out["fail_type"] = ""
    else:
        _res = out.get("results") or {}
        _ft = _res.get("分析失败归因") or out.get("fail_type") or ""
        if not _ft:
            if _res.get("完成状态") == "完成":
                _ft = "飞书写入失败"   # 分析本身成功，仅写回飞书失败
            else:
                _ft = classify_adp_failure(error=out.get("error", ""), full_text=full_text,
                                           attachment_count=len(attachments), signal_info=signal_info)
        out["fail_type"] = _ft
        if not _res.get("分析失败归因"):
            _res["分析失败归因"] = _ft
        # 表格"原因"列同步短分类（澄清/拒答/截断/分析超时 等）
        if not _res.get("原因"):
            _res["原因"] = short_failure_category(_ft) if _ft else ""
        out["results"] = _res

    # 失败时记录 SSE 判别信号（reply_method / response_status），便于区分正常收口与异常断开
    if not out.get("ok"):
        _sig_dbg = "reply_method=%s; response_status=%s" % (
            signal_info.get("reply_method", ""), signal_info.get("response_status", ""))
        out["signal_debug"] = _sig_dbg
        _prev_err = out.get("error") or ""
        out["error"] = (f"{_prev_err}（{_sig_dbg}）" if _prev_err else _sig_dbg)

    out["total_elapsed"] = round(time.time() - t0, 1)
    return out


# ===== ADP 执行批次记录（本地 CSV + 云端已有表格）=====

import threading as _threading

_ADP_BATCH_LOG_LOCK = _threading.Lock()

# 批次计数器本地持久化文件
_ADP_BATCH_LOG_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "adp_batch_log_state.json",
)


def _load_adp_batch_state() -> dict:
    """读取 ADP 批次记录状态（批次计数）"""
    try:
        if os.path.exists(_ADP_BATCH_LOG_STATE_FILE):
            with open(_ADP_BATCH_LOG_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("ADP 批次记录状态读取失败: %s", e)
    return {"batch_count": 0}


def _save_adp_batch_state(state: dict):
    """持久化 ADP 批次记录状态"""
    try:
        os.makedirs(os.path.dirname(_ADP_BATCH_LOG_STATE_FILE), exist_ok=True)
        with open(_ADP_BATCH_LOG_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("ADP 批次记录状态保存失败: %s", e)


def save_adp_batch_log(results: list, total_elapsed: float = 0) -> dict:
    """ADP 每次执行完成后，将批次记录写入本地 CSV

    云端表格（回归测试第一批次）的写入已由 write_adp_to_feishu / _write_back 负责，
    本函数只做本地 CSV 批次留痕（含 traceid、traceid排查）。

    :param results: 执行结果列表，每条包含:
        - jira_key: Jira 号
        - ok: 是否成功
        - error: 错误信息
        - fail_type: 失败类型
        - traceid: trace ID
        - traceid排查: 排查报告链接
    :param total_elapsed: 本批次总执行耗时（秒），0 表示未统计
    :return: {"batch_no": int, "csv_path": str}
    """
    if not results:
        return {}
    with _ADP_BATCH_LOG_LOCK:
        return _save_adp_batch_log_inner(results, total_elapsed)


def _save_adp_batch_log_inner(results: list, total_elapsed: float = 0) -> dict:
    """批次记录写入核心逻辑（已在锁内调用，线程安全）"""
    import csv as _csv

    state = _load_adp_batch_state()
    batch_no = state.get("batch_count", 0) + 1
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 格式化总执行时间
    elapsed_str = ""
    if total_elapsed > 0:
        mins, secs = divmod(int(total_elapsed), 60)
        hours, mins = divmod(mins, 60)
        elapsed_str = f"{hours}时{mins:02d}分{secs:02d}秒" if hours else f"{mins}分{secs:02d}秒"

    # 字段定义
    fieldnames = ["Jira号", "执行结果", "任务开始时间", "执行完成时间", "执行报错",
                  "错误分类", "traceid", "traceid排查", "总执行时间"]

    # 构建行数据
    rows = []
    for r in results:
        rows.append({
            "Jira号": r.get("jira_key", ""),
            "执行结果": "成功" if r.get("ok") else "失败",
            "任务开始时间": r.get("start_time") or "",
            "执行完成时间": r.get("end_time") or now_str,
            "执行报错": (r.get("error") or "")[:500],
            "错误分类": r.get("fail_type") or "",
            "traceid": r.get("traceid") or "",
            "traceid排查": r.get("traceid排查") or "",
            "总执行时间": elapsed_str,
        })

    # ── 本地 CSV ──
    log_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "adp_batch_logs",
    )
    os.makedirs(log_dir, exist_ok=True)
    csv_path = os.path.join(log_dir, f"adp_batch_{batch_no}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = _csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # ── 云端归档：批次 CSV 上传到指定飞书文件夹 ──
    folder_token = str(_get_adp_cfg().get("batch_report_folder") or "")
    if folder_token:
        try:
            from src.clients import feishu_client
            up = feishu_client.upload_file_to_drive(
                csv_path, folder_token=folder_token, content_type="text/csv")
            logger.info("ADP 批次记录已上传云端: %s -> %s",
                        os.path.basename(csv_path), (up or {}).get("url") or (up or {}).get("file_token", ""))
        except Exception as e:
            logger.warning("ADP 批次记录上传云端失败: %s", str(e)[:150])

    # 更新批次计数
    state["batch_count"] = batch_no
    _save_adp_batch_state(state)

    success_count = sum(1 for r in results if r.get("ok"))
    logger.info("ADP 批次记录已保存: 批次%d（成功 %d/%d），本地: %s",
                batch_no, success_count, len(results), csv_path)

    return {"batch_no": batch_no, "csv_path": csv_path}
