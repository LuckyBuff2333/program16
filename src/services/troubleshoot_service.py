"""Troubleshoot service layer - 排查诊断业务逻辑

将路由处理函数中的业务逻辑提取到独立服务模块，
路由层只负责 HTTP 解析和响应格式化。
"""
import csv
import os
from datetime import datetime
from typing import Optional

from src.config import load_config, PROJECT_ROOT, setup_logger
from src.clients import feishu_client

logger = setup_logger("service.troubleshoot")


# ── 飞书多维表格通用查询 ──


def _get_bitable_config() -> dict:
    """获取飞书多维表格配置，返回 cfg；缓存与文件不一致时自动从文件重新加载"""
    cfg = load_config().get("feishu_bitable", {})
    # 缓存中缺少关键配置时，强制从文件重新加载
    if not cfg.get("app_token") and not cfg.get("app_id"):
        try:
            import src.config as _cfg_mod
            _cfg_mod._CONFIG = None
            cfg = load_config().get("feishu_bitable", {})
            logger.info("已从配置文件重新加载 feishu_bitable 配置")
        except Exception:
            pass
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    # 支持 wiki_token 自动转换为 app_token
    if not app_token and cfg.get("wiki_token"):
        try:
            if feishu_client._is_cookie_mode():
                app_token = feishu_client.cookie_get_app_token_from_wiki(cfg["wiki_token"])
            else:
                app_token = feishu_client.get_wiki_node_app_token(cfg["wiki_token"])
            cfg = dict(cfg)
            cfg["app_token"] = app_token
            logger.info("通过 wiki_token 获取 app_token: %s", app_token)
        except Exception as e:
            logger.warning("通过 wiki_token 获取 app_token 失败: %s", e)
            return None
    if not app_token or not table_id:
        return None
    return cfg


def _query_bitable_records() -> list:
    """查询飞书多维表格全部记录，失败时抛出异常"""
    cfg = _get_bitable_config()
    if not cfg:
        raise ValueError("多维表格 app_token/table_id 未配置")
    return feishu_client.list_bitable_records(cfg["app_token"], cfg["table_id"])


def _bitable_text(val) -> str:
    """提取飞书多维表格文本字段的纯文本值"""
    if isinstance(val, list):
        return "".join(seg.get("text", "") for seg in val if isinstance(seg, dict))
    if isinstance(val, dict):
        return val.get("text", "")
    return str(val) if val else ""


def _ts_parse_datetime(s: str) -> Optional[datetime]:
    """解析多种日期格式为 datetime 对象"""
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def _pick_error_info(fields: dict) -> str:
    """从多维表格字段中提取错误信息摘要"""
    for key in ("错误信息", "error_info", "报错信息"):
        val = fields.get(key, "")
        text = _bitable_text(val)
        if text:
            return text[:500]
    return ""


def _extract_record_row(fields: dict, cfg: dict) -> dict:
    """从飞书记录字段提取标准化的排查行"""
    done_dt = _ts_parse_datetime(fields.get("分析完成时间", ""))
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")
    report_val = fields.get(report_field, "")
    report_link = ""
    if isinstance(report_val, dict):
        report_link = report_val.get("link", "")
    return {
        "jira号": _bitable_text(fields.get(cfg.get("bugid_field", "jira号"), "")),
        "分析结果": _bitable_text(fields.get("分析结果", "")),
        "触发来源": _bitable_text(fields.get("触发来源", "")),
        "分析完成时间": done_dt.strftime("%Y-%m-%d %H:%M:%S") if done_dt else _bitable_text(fields.get("分析完成时间", "")),
        "分析问题时间": _bitable_text(fields.get("分析问题时间", "")),
        "错误信息": _pick_error_info(fields),
        "人工审核结果": _bitable_text(fields.get("人工审核结果", "")),
        "飞书报告链接": report_link,
    }


# ── 业务方法 ──


def query_records(
    after_time: str = "",
    result_filter: str = "",
    source_filter: str = "",
    dedup: bool = True,
    no_manual_review: bool = False,
) -> dict:
    """按条件查询排查记录

    Returns:
        {"rows": [...], "count": int, "message": str}
    """
    cutoff = _ts_parse_datetime(after_time)
    if not cutoff:
        raise ValueError("请选择有效的排查时间（分析完成时间起点）")

    cfg = _get_bitable_config()
    if not cfg:
        raise ValueError("多维表格 app_token/table_id 未配置")

    records = _query_bitable_records()
    bugid_field = cfg.get("bugid_field", "jira号")
    picked = {}

    for rec in records:
        fields = rec.get("fields", {})
        done_dt = _ts_parse_datetime(fields.get("分析完成时间", ""))
        if not done_dt or done_dt <= cutoff:
            continue
        result_status = _bitable_text(fields.get("分析结果", ""))
        if result_filter and result_status != result_filter:
            continue
        if source_filter:
            trigger_source = _bitable_text(fields.get("触发来源", ""))
            if trigger_source != source_filter:
                continue
        jira_no = _bitable_text(fields.get(bugid_field, ""))
        if not jira_no:
            continue
        row = _extract_record_row(fields, cfg)
        if no_manual_review and row["人工审核结果"]:
            continue
        prev = picked.get(jira_no)
        if not dedup or prev is None or row["分析完成时间"] > prev["分析完成时间"]:
            picked[jira_no] = row

    rows = sorted(picked.values(), key=lambda r: r["分析完成时间"])
    source_label = {"parseFullTicket": "线上", "feishu_bot": "飞书机器人", "jira_analyze": "PC"}.get(source_filter, "全部")
    message = f"{after_time} 之后执行完成 {len(rows)} 条（结果：{result_filter or '全部'}，来源：{source_label}，去重：{'是' if dedup else '否'}）"
    return {"rows": rows, "count": len(rows), "message": message}


def query_by_bugids(bugids: list[str]) -> dict:
    """按 Jira 号列表精确查询

    Returns:
        {"rows": [...], "count": int, "not_found": [...], "message": str}
    """
    cfg = _get_bitable_config()
    if not cfg:
        raise ValueError("多维表格 app_token/table_id 未配置")

    records = _query_bitable_records()
    bugid_field = cfg.get("bugid_field", "jira号")
    target_set = set(b.strip().upper() for b in bugids if b.strip())
    picked = {}

    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(bugid_field, "")).upper()
        if not jira_no or jira_no not in target_set:
            continue
        row = _extract_record_row(fields, cfg)
        prev = picked.get(jira_no)
        if prev is None or row["分析完成时间"] > prev["分析完成时间"]:
            picked[jira_no] = row

    rows = sorted(picked.values(), key=lambda r: r["分析完成时间"])
    not_found = sorted(target_set - set(picked.keys()))
    message = f"查询到 {len(rows)} 条匹配记录"
    if not_found:
        message += f"，未找到: {', '.join(not_found[:5])}{'...' if len(not_found) > 5 else ''}"
    return {"rows": rows, "count": len(rows), "not_found": not_found, "message": message}


def search_by_keyword(keyword: str) -> dict:
    """按关键词模糊搜索 Jira 号

    Returns:
        {"rows": [...], "count": int, "message": str}
    """
    cfg = _get_bitable_config()
    if not cfg:
        raise ValueError("多维表格 app_token/table_id 未配置")

    records = _query_bitable_records()
    bugid_field = cfg.get("bugid_field", "jira号")
    keyword_upper = keyword.strip().upper()
    rows = []

    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(bugid_field, "")).upper()
        if not jira_no or keyword_upper not in jira_no:
            continue
        done_dt = _ts_parse_datetime(fields.get("分析完成时间", ""))
        rows.append({
            "jira号": _bitable_text(fields.get(bugid_field, "")),
            "分析结果": _bitable_text(fields.get("分析结果", "")),
            "分析完成时间": done_dt.strftime("%Y-%m-%d %H:%M:%S") if done_dt else "",
            "分析问题时间": _bitable_text(fields.get("分析问题时间", "")),
            "错误信息": _pick_error_info(fields),
            "人工审核结果": _bitable_text(fields.get("人工审核结果", "")),
        })

    rows.sort(key=lambda r: r["分析完成时间"] or "", reverse=True)
    return {"rows": rows, "count": len(rows), "message": f"找到 {len(rows)} 条匹配记录"}


def batch_write_review(items: list[dict], only_empty_review: bool = False) -> dict:
    """批量写入人工审核结果到多维表格

    Returns:
        {"matched": int, "unmatched": int, "skipped": int, "updated": int, "message": str}
    """
    cfg = _get_bitable_config()
    if not cfg:
        raise ValueError("多维表格 app_token/table_id 未配置")

    app_token = cfg["app_token"]
    table_id = cfg["table_id"]
    bugid_field = cfg.get("bugid_field", "jira号")
    review_field = cfg.get("review_field", "人工审核结果")

    records = feishu_client.list_bitable_records(app_token, table_id)
    index = {}
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get(bugid_field, ""))
        done_time = _bitable_text(fields.get("分析完成时间", ""))
        if jira_no and done_time:
            index[(jira_no, done_time)] = rec["record_id"]

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
        raise ValueError(f"未匹配到任何记录（共 {len(items)} 条待写入，0 条匹配{hint}）")

    for i in range(0, len(updates), 500):
        batch = updates[i:i + 500]
        feishu_client.update_bitable_records(app_token, table_id, batch)

    message = f"批量写入完成: {matched}/{len(items)} 条匹配并写入"
    if unmatched:
        message += f"，{unmatched} 条未匹配"
    if skipped:
        message += f"，{skipped} 条已有审核结果已跳过"
    return {"matched": matched, "unmatched": unmatched, "skipped": skipped, "updated": len(updates), "message": message}


def export_trigger_time_issues(items: list[dict], folder_token: str = "") -> dict:
    """导出触发时间问题到本地 CSV 和飞书多维表格

    Returns:
        {"count": int, "csv_path": str, "cloud_url": str, "message": str}
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M%S")
    local_dir = os.path.join(PROJECT_ROOT, "data", "troubleshoot", "trigger_time_issues")
    os.makedirs(local_dir, exist_ok=True)
    csv_path = os.path.join(local_dir, f"trigger_time_issues_{date_str}_{time_str}.csv")

    fieldnames = ["jira号", "问题归类", "分析完成时间", "错误时间", "诊断详情", "修正建议", "人工审核结果"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for it in items:
            writer.writerow({k: it.get(k, "") for k in fieldnames})

    cloud_url = ""
    try:
        bitable_name = f"触发时间问题_{date_str}_{time_str}"
        result = feishu_client.create_bitable(bitable_name, folder_token)
        app_token = result.get("app_token", "")
        if app_token:
            fields = [{"field_name": fn, "type": 1} for fn in fieldnames]
            table_id = feishu_client.create_bitable_table(app_token, "触发时间问题", fields)
            records = [{"fields": {k: it.get(k, "") for k in fieldnames}} for it in items]
            feishu_client.batch_create_records(app_token, table_id, records)
            cloud_url = result.get("url", "")
    except Exception as e:
        logger.warning("云端上传失败: %s", e)

    message = f"已生成触发时间问题表格: {len(items)} 条"
    if cloud_url:
        message += f"，云端: {cloud_url}"
    else:
        message += "，云端上传失败"
    return {"count": len(items), "csv_path": csv_path, "cloud_url": cloud_url, "message": message}


# ── 预归类与开发者通知 ──

# 无需深入分析的预归类类别（前端优先展示，单独成表）
_SKIP_ANALYSIS_CATEGORIES = {
    "待后端开发排查", "磁盘空间不足", "服务关闭",
    "并发过多", "IT侧服务停止", "接口连接问题", "接口响应问题",
    "分析任务执行超时，跳过排查", "问题重复", "问题未复现",
}


def _diag_pre_classify(err_msg: str) -> str:
    """根据失败原因文本预归类，无法判定时返回空串"""
    import re
    msg = err_msg or ""
    # 无错误信息 → 服务关闭
    if not msg:
        return "服务关闭"
    if "未找到问题时间" in msg:
        return "触发时间问题"
    if "没有可下载的日志附件" in msg:
        return "无gmlogger"
    # JIRA/网关超时 → 分析任务执行超时（区别于并发过多）
    if ("JIRA 分析任务执行超时" in msg or "JIRA 网关分析任务执行超时" in msg):
        return "分析任务执行超时，跳过排查"
    # 普通分析任务超时 → 并发过多
    if "分析任务执行超时" in msg or "分析任务被取消" in msg:
        return "并发过多"
    # reasoning 第N轮 LLM 调用失败 → 并发过多
    if "reasoning 第" in msg and "轮 LLM 调用失败" in msg:
        return "并发过多"
    if "no space left on device" in msg.lower() or "Errno 28" in msg:
        return "磁盘空间不足"
    # 模型调用失败 → 服务停止
    if msg.startswith("模型调用失败"):
        return "IT侧服务停止"
    # adjudication 失败 / 分析报告生成失败 / LLM调用失败 → 并发过多
    if ("adjudication" in msg or "未获取有效响应" in msg or "LLM 调用失败" in msg
            or "分析报告生成失败" in msg):
        return "并发过多"
    # 504/502 网关错误 → 并发过多
    if "504 Gateway Timeout" in msg or "502 Bad Gateway" in msg:
        return "并发过多"
    # server disconnected → 服务关闭
    if "server disconnected" in msg.lower() or "disconnected without sending" in msg.lower():
        return "服务关闭"
    # 服务有报错 → 服务关闭
    if msg == "服务有报错":
        return "服务关闭"
    low = msg.lower()
    if ("all connection attempts failed" in low or "connecterror" in low
            or "连接失败" in msg or "无法连接" in msg or "connection refused" in low):
        return "服务关闭"
    # HTTPStatusError → 待后端开发排查
    if "HTTPStatusError" in msg:
        return "待后端开发排查"
    if "时间过滤后日志为空" in msg or "未找到有效的日志文件" in msg:
        return ""  # 需下载附件比对时间后才能判定
    return "待后端开发排查"


def batch_pre_classify(records: list[dict]) -> dict:
    """批量预归类：根据错误信息和人工审核结果快速分类，跳过无需深度分析的记录"""
    from src.services.report_ops import _generate_troubleshoot_report
    if not records:
        return {"skip": [], "need_analysis": [], "message": "无记录"}
    skip_list, need_list = [], []
    for rec in records:
        bugid = rec.get("bugid", "")
        err_msg = rec.get("err_msg", "") or ""
        human_review = rec.get("human_review", "") or ""
        done_time = rec.get("done_time", "")
        problem_time = rec.get("problem_time", "")
        category = ""
        # 1. 无报错信息或“服务有报错” → 服务关闭
        if not err_msg or err_msg == "服务有报错":
            category = "服务关闭"
        # 2. 人工审核结果倒推（从多维表格读取）
        if not category and human_review and human_review not in ("-", "None"):
            if "并发过多" in human_review or "接口拥堵" in human_review or "手动中断" in human_review:
                category = "并发过多"
            elif "模型调用失败" in human_review or "IT侧服务停止" in human_review or "服务停止" in human_review:
                category = "IT侧服务停止"
            elif "服务关闭" in human_review or "服务有报错" in human_review:
                category = "服务关闭"
            elif "待后端开发排查" in human_review:
                category = "待后端开发排查"
            elif "接口无响应" in human_review or "连接失败" in human_review:
                category = "接口响应问题"
            elif "JIRA Server" in human_review or "过载" in human_review or "网络抖动" in human_review:
                category = "并发过多"
            elif "执行超时" in human_review or "JIRA 分析任务执行超时" in human_review:
                category = "分析任务执行超时，跳过排查"
            elif "问题重复" in human_review:
                category = "问题重复"
            elif "未复现" in human_review or "不复现" in human_review:
                category = "问题未复现"
            elif "无gmlogger" in human_review or "无gmlogger文件" in human_review:
                category = "无gmlogger"
            elif "gmlogger文件已上传" in human_review:
                category = "无gmlogger"
            elif "损坏" in human_review or "日志文件已损坏" in human_review:
                category = "日志过滤逻辑"
            elif "磁盘空间不足" in human_review:
                category = "磁盘空间不足"
            elif "时间添加" in human_review or "时间异常" in human_review:
                category = "触发时间问题"
            elif "解压" in human_review or "unrar" in human_review or "RAR5" in human_review:
                category = "解压问题"
            elif "分析can信号" in human_review:
                category = "分析can信号导致超时"
        # 3. 错误信息预归类
        if not category:
            category = _diag_pre_classify(err_msg)
        entry = {"bugid": bugid, "category": category or "", "done_time": done_time,
                 "problem_time": problem_time, "err_msg": err_msg[:200]}
        if category and category in _SKIP_ANALYSIS_CATEGORIES:
            report = _generate_troubleshoot_report(bugid, category, err_msg, f"预归类：{category}")
            entry["report"] = report
            entry["detail"] = f"根据失败原因/人工审核预归类：{category}"
            entry["needs_analysis"] = False
            skip_list.append(entry)
        else:
            entry["needs_analysis"] = True
            need_list.append(entry)
    logger.info("批量预归类: 共 %d 条 → 跳过 %d 条, 需分析 %d 条", len(records), len(skip_list), len(need_list))
    return {"skip": skip_list, "need_analysis": need_list,
            "message": f"预归类完成: 跳过 {len(skip_list)} 条, 需分析 {len(need_list)} 条"}


def send_to_developer(records: list[dict]) -> dict:
    """将自动归类记录通过飞书机器人发送给后端开发者"""
    if not records:
        raise ValueError("发送列表为空")
    lines = [f"\U0001f514 AI日志分析失败 - 待后端排查记录（{len(records)} 条）",
             "", "| # | Jira号 | 分析完成时间 | 错误信息 |",
             "|---|--------|-------------|----------|"]
    for i, rec in enumerate(records, 1):
        bugid = rec.get("bugid", "")
        done_time = rec.get("done_time", "") or "-"
        err_msg = (rec.get("err_msg", "") or "-")[:80]
        lines.append(f"| {i} | {bugid} | {done_time} | {err_msg} |")
    cat_count: dict[str, int] = {}
    for rec in records:
        cat = rec.get("category", "未知")
        cat_count[cat] = cat_count.get(cat, 0) + 1
    lines.append("")
    lines.append("分类统计: " + ", ".join(f"{k}({v})" for k, v in sorted(cat_count.items(), key=lambda x: -x[1])))
    msg_text = "\n".join(lines)
    notify_chat = load_config().get("feishu_bot", {}).get("notify_chat_id", "")
    if not notify_chat:
        raise ValueError("未配置 feishu_bot.notify_chat_id，无法发送")
    sent = feishu_client.send_bot_message(notify_chat, msg_text)
    if sent:
        logger.info("已发送 %d 条待后端排查记录给开发者", len(records))
        return {"message": f"已成功发送 {len(records)} 条记录给后端开发"}
    raise ValueError("发送失败，请检查飞书机器人配置")
