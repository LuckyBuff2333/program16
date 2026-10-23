"""ADP 分析管道：dpportal查附件 → ADP v2 SSE分析 → 提取结果 → 写入飞书多维表格

学习自 program17/adp_analysis_pipeline.py，适配项目风格。
"""
import os
import re
import json
import uuid
import logging
from datetime import datetime

import httpx

from src.config import load_config, get_path

logger = logging.getLogger(__name__)


# ===== 配置读取 =====

def _get_adp_cfg() -> dict:
    """读取 adp 配置段，带默认值"""
    cfg = load_config().get("adp") or {}
    return {
        "app_key": cfg.get("app_key", ""),
        "url": cfg.get("url", "https://wss.lke.cloud.tencent.com/adp/v2/chat"),
        "sandbox_base": cfg.get("sandbox_base", "https://sandbox.adp.cloud.tencent.com/files?path="),
        "attach_api": cfg.get("attach_api", "https://dpportal.apps.saic-gm.com/api/logAnalysis/attachments"),
        "attach_api_key": cfg.get("attach_api_key", ""),
        "timeout": int(cfg.get("timeout", 3600)),
        "bitable_app_token": cfg.get("bitable_app_token", ""),
        "bitable_table_id": cfg.get("bitable_table_id", ""),
        "jira_field": cfg.get("jira_field", "Jira链接"),
        "save_dir": cfg.get("save_dir", "docs/adp_results"),
    }


# ===== 工具函数 =====

def _fix_encoding(text: str) -> str:
    """修复 latin-1 误读的 UTF-8 乱码（ADP SSE 返回已知问题）"""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


# ===== Step 1: dpportal 查询附件 =====

def query_attachments(jira_key: str) -> list:
    """查询 JIRA 附件列表，返回附件 dict 列表"""
    adp_cfg = _get_adp_cfg()
    logger.info("ADP 查询附件: %s", jira_key)
    try:
        resp = httpx.post(
            adp_cfg["attach_api"],
            headers={"Content-Type": "application/json", "X-API-Key": adp_cfg["attach_api_key"]},
            json={"jiraKey": jira_key},
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.warning("ADP 附件查询失败: %s -> %s", jira_key, data)
            return []
        attachments = data.get("data", {}).get("attachments", [])
        logger.info("ADP 附件查询: %s 找到 %d 个附件", jira_key, len(attachments))
        return attachments
    except Exception as e:
        logger.error("ADP 附件查询异常: %s -> %s", jira_key, e)
        return []


# ===== Step 2: 构建消息 + 调用 ADP SSE =====

# 有效附件格式正则：压缩包 + txt
_VALID_ATTACH_RE = re.compile(
    r'\.(zip|z\d+|rar|7z|tar|gz|bz2|xz|tgz|txt|log)$', re.IGNORECASE)


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


def call_adp_sse_stream(message: str, keepalive_cb=None) -> tuple:
    """
    调用 ADP v2 SSE 接口（流式读取，支持心跳回调）
    :param keepalive_cb: 可选回调 fn(elapsed_sec)，每 30 秒调用一次用于 SSE 心跳
    返回: (full_text, file_urls, closeout_data, start_ts, end_ts)
    """
    import time
    adp_cfg = _get_adp_cfg()
    payload = {
        "RequestId": uuid.uuid4().hex[:32],
        "ConversationId": uuid.uuid4().hex[:32],
        "AppKey": adp_cfg["app_key"],
        "VisitorId": "jira_analysis_user",
        "Contents": [{"Type": "text", "Text": message}],
        "Incremental": True,
        "Stream": "enable",
        "StreamingThrottle": 5,
    }
    logger.info("ADP 调用 SSE 接口（流式，超时 %ds）...", adp_cfg["timeout"])
    full_text = ""
    file_urls = []
    closeout_data = None
    start_ts = 0
    end_ts = 0
    t0 = time.time()
    last_keepalive = t0
    try:
        with httpx.stream(
            "POST", adp_cfg["url"],
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(adp_cfg["timeout"], connect=15),
        ) as resp:
            if resp.status_code != 200:
                logger.error("ADP SSE HTTP %d", resp.status_code)
                return "", [], None, 0, 0
            for line in resp.iter_lines():
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
                if et == "response.created" and ts > 0:
                    start_ts = ts
                if ts > 0:
                    end_ts = ts
                if et == "text.delta":
                    full_text += _fix_encoding(data.get("Text", ""))
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
                        file_urls.append({"name": finfo.get("FileName", ""), "url": finfo.get("FileUrl", "")})
    except Exception as e:
        logger.error("ADP SSE 流式读取异常: %s", e)
        return full_text, file_urls, closeout_data, start_ts, end_ts
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
    elapsed_sec = (end_ts - start_ts) / 1000 if start_ts and end_ts else 0
    logger.info("ADP 分析完成: %d 字符, 耗时 %.0fs", len(full_text), elapsed_sec)
    return full_text, file_urls, closeout_data, start_ts, end_ts


def call_adp_sse(message: str) -> tuple:
    """调用 ADP v2 SSE 接口（兼容旧调用）"""
    return call_adp_sse_stream(message)


# ===== Step 3: 提取分析结果 =====

def _extract_problem_module(text: str) -> str:
    """从分析文本中提取问题模块（归位/问题所在域）"""
    patterns = [
        r"问题在\s*\*?\*?(上游[^\uff0c\u3002\n]+|车端[^\uff0c\u3002\n]+|云端[^\uff0c\u3002\n]+)",
        r"归位[：:]\s*(\S+)",
        r"归位.*?(external|internal|上游|车端|云端)",
        r"问题所在模块[：:：]*\s*[\*]*(.+?)[\*]*(?:\n|$)",
        r"模块[：:]\s*(.+?)(?:\n|$)",
        r"问题(?:归属|所在|模块)[^\n]*[：:：]\s*(.+?)(?:\n|$)",
        r"(?:归因|归属|定位|问题域|责任方)[：:：]\s*(.+?)(?:\n|$)",
        r"(?:属于|定位到|定位在|归因于|归到)\s*(.{4,40}?)(?:[\uff0c\u3002\n。]|$)",
        r"(上游[^\s\uff0c]{2,20}|车端[^\s\uff0c]{2,20}|云端[^\s\uff0c]{2,20}|HMI[^\s\uff0c]{2,20}|Android[^\s\uff0c]{2,20}|QNX[^\s\uff0c]{2,20})",
    ]
    # 优先从文本末尾 3000 字符提取（收案报告通常在末尾）
    tail = text[-3000:] if len(text) > 3000 else text
    for p in patterns:
        m = re.search(p, tail, re.IGNORECASE)
        if m:
            return m.group(1).strip("*").strip()
    return ""


def _extract_root_cause(text: str) -> str:
    """从分析文本中提取 root cause"""
    patterns = [
        r"结论[：:：]\s*(.+?)(?:\n|$)",
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
    # 优先从文本末尾 3000 字符提取
    tail = text[-3000:] if len(text) > 3000 else text
    for p in patterns:
        m = re.search(p, tail, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _extract_confidence(text: str) -> str:
    """从分析文本中提取置信度"""
    # 优先从末尾 3000 字符提取
    tail = text[-3000:] if len(text) > 3000 else text
    patterns = [
        r"confidence\s*[:：]?\s*([0-9]+\.?[0-9]*)",
        r"置信度\s*[:：：]?\s*([0-9]+\.?[0-9]*)",
        r"置信度\s*[:：：]?\s*([0-9]+%)",
    ]
    for p in patterns:
        m = re.search(p, tail, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def _extract_report_url(text: str, file_urls: list, closeout_data: dict) -> tuple:
    """从多个来源提取报告链接（优先级：文本中 agent.adp-cos.com > file_urls > closeout sandbox > 文件名）
    返回: (html_filename, direct_url)
    """
    # 1. 从最终 reply 文本中提取 agent.adp-cos.com 报告链接（最准确）
    m = re.search(r'(https?://agent\.adp-cos\.com/[^\s)"\']*(?:report_|out/)[^\s)"\']*\.html[^\s)"\']*)', text)
    if m:
        url = m.group(1)
        name = re.search(r'(report_[^\s)"\'/?]*\.html)', url)
        return (name.group(1) if name else url.split("/")[-1].split("?")[0]), url
    # 2. file_urls（content.added 事件中的文件），只匹配 .html 报告文件
    for f in (file_urls or []):
        name = f.get("name", "")
        url = f.get("url", "")
        if name.endswith(".html") and "meta" not in name.lower():
            return name, url
    # 3. closeout_data 拼 sandbox 路径（兜底）
    if closeout_data:
        case_id = closeout_data.get("case_id", "")
        html_file = closeout_data.get("html", "")
        if case_id and html_file:
            adp_cfg = _get_adp_cfg()
            return html_file, f"{adp_cfg['sandbox_base']}/workdir/{case_id}/out/{html_file}"
    # 4. 文本中的其他 URL
    m = re.search(r'(https?://[^\s)"\']*report_[^\s)"\']*\.html[^\s)"\']*)', text)
    if m:
        url = m.group(1)
        name = re.search(r'(report_[^\s)"\'/?]*\.html)', url)
        return (name.group(1) if name else "report.html"), url
    return "", ""


def extract_adp_results(full_text: str, closeout_data: dict, start_ts: int, end_ts: int, file_urls: list = None) -> dict:
    """从 ADP 返回内容中提取需要写入飞书的 6 个字段"""
    result = {"完成状态": "完成"}
    # 报告链接（多来源提取）
    html_file, report_url = _extract_report_url(full_text, file_urls or [], closeout_data)
    if report_url:
        result["报告链接（分析报告、可观测报告）"] = report_url
    elif html_file:
        result["报告链接（分析报告、可观测报告）"] = html_file
    # 置信度：优先 closeout_data，其次从文本提取
    confidence = ""
    if closeout_data:
        confidence = str(closeout_data.get("confidence", ""))
    if not confidence:
        confidence = _extract_confidence(full_text)
    result["置信度"] = confidence
    # 耗时(分)
    if start_ts and end_ts:
        elapsed_min = round((end_ts - start_ts) / 1000 / 60, 1)
        result["耗时(分)"] = str(elapsed_min)
    # 问题模块 + root cause
    result["agent分析的问题模块"] = _extract_problem_module(full_text)
    result["agent分析的root cause"] = _extract_root_cause(full_text)
    # 额外返回报告直链（供前端展示，不写入飞书）
    result["_report_url"] = report_url
    result["_html_file"] = html_file
    return result


# ===== Step 4: 保存本地文件 =====

def save_adp_local(jira_key: str, full_text: str, closeout_data: dict,
                   file_urls: list = None, description: str = "", trigger_time: str = "",
                   attachment_count: int = 0, results: dict = None, elapsed_sec: float = 0) -> str:
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
        f.write(f"- **耗时**: {elapsed_sec:.1f}s\n\n")
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
    """下载 ADP HTML 报告到本地，再上传为多维表格附件，返回 {file_token, local_path}"""
    from src.config import PROJECT_ROOT
    from src.clients import feishu_client
    if not report_url:
        return {"file_token": "", "local_path": ""}
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
        return {"file_token": file_token, "local_path": local_path}
    except Exception as e:
        logger.error("ADP 报告处理失败: %s -> %s", jira_key, e)
        return {"file_token": "", "local_path": ""}


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
        # 写入 6 个字段
        allowed = ["完成状态", "报告链接（分析报告、可观测报告）", "耗时(分)",
                    "agent分析的问题模块", "agent分析的root cause", "置信度"]
        write_fields = {k: v for k, v in fields_dict.items() if k in allowed}
        # 附件字段"报告链接"需要 file_token 格式，无 file_token 则移除该字段（避免 URL 字符串写入附件类型字段）
        file_token = fields_dict.get("_report_file_token", "")
        if file_token:
            write_fields["报告链接（分析报告、可观测报告）"] = [{"file_token": file_token}]
        else:
            write_fields.pop("报告链接（分析报告、可观测报告）", None)
        feishu_client.update_bitable_records(app_token, table_id,
                                              [{"record_id": record_id, "fields": write_fields}])
        logger.info("ADP 飞书写入成功: %s -> %s", jira_key, list(write_fields.keys()))
        return {"ok": True, "record_id": record_id, "message": "写入成功", "fields": write_fields}
    except Exception as e:
        logger.error("ADP 飞书写入失败: %s -> %s", jira_key, e)
        return {"ok": False, "record_id": "", "message": str(e)}


# ===== 完整单条执行流程 =====

def run_adp_single(jira_key: str, description: str, trigger_time: str, progress_cb=None, keepalive_cb=None) -> dict:
    """
    完整 ADP 分析流程（单条）
    :param progress_cb: 可选回调 fn(step_name, status, detail) 用于 SSE 推送
    :param keepalive_cb: 可选回调 fn(elapsed_sec)，ADP 分析期间每 30s 触发
    :return: {ok, jira_key, description, trigger_time, attachment_count, results, feishu, elapsed_sec, error}
    """
    import time
    t0 = time.time()
    out = {"ok": False, "jira_key": jira_key, "description": description, "trigger_time": trigger_time}

    def _progress(step, status, detail=""):
        if progress_cb:
            progress_cb(step, status, detail)

    # Step 1: 查附件
    _progress("attachments", "running")
    attachments = query_attachments(jira_key)
    out["attachment_count"] = len(attachments)
    if not attachments:
        out["error"] = "无附件"
        out["results"] = {"完成状态": "无法分析"}
        _progress("attachments", "fail", "无附件")
        return out
    # 检查过滤后是否有有效日志附件
    valid_atts = [a for a in attachments if _is_valid_attachment(a)]
    if not valid_atts:
        file_names = [a.get('filename', '?') for a in attachments]
        out["error"] = f"没有日志附件（已有: {', '.join(file_names[:5])}）"
        out["results"] = {"完成状态": "无法分析"}
        _progress("attachments", "fail", out["error"])
        return out
    _progress("attachments", "done", f"{len(valid_atts)} 个有效附件（共 {len(attachments)} 个）")

    # Step 2: 构建消息 + 调用 ADP
    _progress("adp_analysis", "running")
    message = build_adp_message(jira_key, description, trigger_time, attachments)
    full_text, file_urls, closeout_data, start_ts, end_ts = call_adp_sse_stream(message, keepalive_cb=keepalive_cb)
    if not full_text:
        out["error"] = "ADP 无返回"
        _progress("adp_analysis", "fail", "无返回")
        return out
    elapsed_sec = (end_ts - start_ts) / 1000 if start_ts and end_ts else 0
    out["elapsed_sec"] = round(elapsed_sec, 1)
    _progress("adp_analysis", "done", f"{len(full_text)} 字符, {elapsed_sec:.0f}s")

    # Step 3: 提取结果
    _progress("extract", "running")
    results = extract_adp_results(full_text, closeout_data, start_ts, end_ts, file_urls)
    out["results"] = results
    out["full_text"] = full_text[:10000]  # 返回前 10000 字符供前端展示
    out["file_urls"] = file_urls
    _progress("extract", "done", f"完成状态={results.get('完成状态', '')}")

    # Step 3.5: 下载 HTML 报告到本地，上传为多维表格附件
    report_url = results.get("_report_url", "")
    html_file = results.get("_html_file", "")
    if report_url:
        _progress("download_report", "running")
        dl_result = download_adp_report(jira_key, report_url, html_file)
        file_token = dl_result.get("file_token", "")
        if file_token:
            results["_report_file_token"] = file_token
            results["报告链接（分析报告、可观测报告）"] = f"附件: {html_file or 'report.html'}"
            out["_report_file_token"] = file_token
        else:
            # 下载失败时移除报告链接字段，避免 URL 字符串写入附件类型字段
            results.pop("报告链接（分析报告、可观测报告）", None)
        _progress("download_report", "done" if file_token else "fail")

    # Step 4: 保存本地
    _progress("save_local", "running")
    save_adp_local(jira_key, full_text, closeout_data, file_urls,
                   description=description, trigger_time=trigger_time,
                   attachment_count=len(attachments), results=results,
                   elapsed_sec=out.get("elapsed_sec", 0))
    _progress("save_local", "done")

    # Step 5: 写入飞书
    _progress("write_feishu", "running")
    fs_result = write_adp_to_feishu(jira_key, results)
    out["feishu"] = fs_result
    _progress("write_feishu", "done" if fs_result["ok"] else "fail", fs_result["message"])

    out["ok"] = fs_result["ok"]
    out["total_elapsed"] = round(time.time() - t0, 1)
    return out
