"""报表与数据管理服务：日报/周报/范围报告生成、多维表格写入、文档管理

从 server.py 提取，包含报告生成和数据操作的完整逻辑。
函数通过 server.py 的 _alias 导入保持向后兼容。
"""

import json
import os
import re
import threading
from datetime import datetime

import pandas as pd
import yaml
from fastapi import Request

from src import config as cfg_module
from src import pipeline
from src.clients import ai_log_client, bug_source, jira_client
from src.clients import diana_client as _diana_client
from src.config import get_path, load_config, setup_logger, PROJECT_ROOT
from src.core import doc_generator

# 从共享模块导入公共工具和状态
from src.api.routes.shared import (
    bitable_text as _bitable_text,
    is_bitable_excluded as _is_bitable_excluded,
    flatten_bitable_record as _flatten_bitable_record,
    get_prod_ai_url as _get_prod_ai_url,
    ts_parse_datetime as _ts_parse_datetime,
    read_csv_rows as _read_csv_rows,
    parse_markdown_batch_table as _parse_markdown_batch_table,
    ok as _ok,
    fail as _fail,
)

logger = setup_logger("services.report_ops")

# 从 trigger_ops 共享飞书表格批量缓存
from src.services.trigger_ops import _bitable_bulk_cache, _BITABLE_CACHE_TTL

# 云端批次记录缓存：{日期: {"ts": 缓存时间, "data": {jira号: 执行信息}}}
_cloud_batch_cache = {}
_CLOUD_CACHE_TTL = 300  # 缓存有效期 5 分钟

# 每日播报配置文件路径
_DAILY_BROADCAST_CONFIG_PATH = os.path.join(PROJECT_ROOT, "data", "daily_broadcast_config.json")

# 需要从 server.py 延迟导入的函数（在函数体内 import）
# _bot_daily_broadcast 等 feishu bot 函数留在 server.py


def _batch_csv_to_markdown(csv_path: str) -> str:
    """将批量执行 CSV 转为 Markdown 格式文档，含统计摘要和完整表格"""
    rows = _read_csv_rows(csv_path)
    if not rows:
        return "# 批量执行记录\n\n无执行记录"
    success = sum(1 for r in rows if r.get("执行结果", "").strip() == "成功")
    fail = len(rows) - success
    times = [r.get("执行时间", "").strip() for r in rows if r.get("执行时间", "").strip()]
    time_range = f"{min(times)} ~ {max(times)}" if len(times) >= 2 else (times[0] if times else "未知")
    # 从第一条记录提取基础配置信息
    first = rows[0]
    concurrency = first.get("分析并发数", "").strip() or "-"
    download_concurrency = first.get("下载并发数", "").strip() or "-"
    model = first.get("模型", "").strip() or "-"
    trigger_source = first.get("触发来源", "").strip() or "-"
    # 构建 Markdown
    lines = [
        f"# 批量执行记录",
        f"",
        f"- 总条数：{len(rows)}",
        f"- 成功：{success}",
        f"- 失败：{fail}",
        f"- 执行时间：{time_range}",
        f"- 分析并发数：{concurrency}",
        f"- 下载并发数：{download_concurrency}",
        f"- 模型：{model}",
        f"- 触发来源：{trigger_source}",
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
    # 磁盘空间不足：No space left on device
    if "no space left on device" in err_info.lower() or "Errno 28" in err_info:
        return "磁盘空间不足"
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
    # 上传：原地覆盖内容，保持链接不变
    try:
        if existing_docs:
            # 用第一个文档原地覆盖内容（全选替换）
            main_token, main_url = existing_docs[0]
            ok = feishu_client.update_docx_content(main_token, md_content)
            if ok:
                logger.info("每日结论文档已原地覆盖: %s", main_url)
                return main_url
            logger.warning("每日结论文档原地覆盖失败")
            return ""
        # 无同名文档：创建新文档
        doc_result = feishu_client.create_docx_document(
            doc_title, md_content, folder_token=_DAILY_BROADCAST_FOLDER)
        url = doc_result.get("url", "")
        if url:
            logger.info("每日结论文档已创建: %s", url)
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
        # 先写入新记录，成功后再删除旧记录（避免写入失败时数据丢失）
        old_ids = [rec.get("record_id") for rec in records if rec.get("record_id")]
        # 按日期降序重新写入
        feishu_client.batch_create_records(app_token, stats_table_id, sorted_records)
        # 写入成功后才删除旧记录
        if old_ids:
            feishu_client.batch_delete_records(app_token, stats_table_id, old_ids)
        logger.info("统计表已同步并排序: %s (total=%d, 共%d条)", date_str, total, len(sorted_records))
    except Exception as e:
        logger.warning("统计表同步失败: %s", e)


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
                return main_url
            logger.warning("每周汇总文档原地覆盖失败")
            return ""
        # 无同名文档：创建新文档
        doc_result = feishu_client.create_docx_document(
            doc_title, md_content, folder_token=_DAILY_BROADCAST_FOLDER)
        url = doc_result.get("url", "")
        if url:
            logger.info("每周汇总文档已创建: %s", url)
        return url
    except Exception as e:
        logger.warning("每周汇总文档上传失败: %s", e)
        return ""


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
                doc_name = doc.get("name", "")
                if not doc_token:
                    continue
                try:
                    md = feishu_client.fetch_docx_as_markdown(doc_token)
                    batch_rows = _parse_markdown_batch_table(md)
                    if batch_rows:
                        # 根据文档名补全触发来源（云端表格可能无该列）
                        inferred_source = "parseFullTicket" if doc_name.startswith("线上批量执行") else "jira_analyze"
                        for r in batch_rows:
                            if not (r.get("触发来源") or "").strip():
                                r["触发来源"] = inferred_source
                        cloud_data.update(_process_batch(batch_rows))
                except Exception as e:
                    logger.warning("云端批次记录读取失败 %s: %s", doc_name, e)
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


def _spotcheck_csv_path(filename: str, date_str: str = None) -> str:
    """抽查报表路径：spotcheck/日期/filename"""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    return os.path.join(get_path("report_dir"), "spotcheck", date_str, filename)


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
    elif category == "模型调用失败" or category == "待后端开发排查":
        ai_reason = msg or "LLM 调用失败"
        human_reason = "模型调用失败"
        retry_result = ""
        final_category = "待后端开发排查"
    elif category == "磁盘空间不足":
        ai_reason = msg or "No space left on device"
        human_reason = "磁盘空间不足"
        retry_result = ""
        final_category = "磁盘空间不足"
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
    elif category == "无gmlogger" or category == "无gmlogger文件":
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


def _troubleshoot_cache_dir() -> str:
    """获取诊断结果本地缓存目录"""
    cache_dir = os.path.join(PROJECT_ROOT, "data", "troubleshoot")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


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


def _delete_default_bitable_table(app_token: str, keep_table_id: str, keep_table_ids: set = None):
    """删除飞书创建 bitable 时自动生成的默认空数据表（保留我们自己创建的表）

    只删除名称匹配默认模式的表（如"数据表"），绝不删除以"触发时间"开头的自定义表。
    keep_table_id 和 keep_table_ids 作为双重保险。

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
            tname = t.get("name", "")
            if not tid or tid in all_keep:
                continue
            # 安全检查：只删除名称匹配默认模式的表，绝不删除自定义表
            if tname.startswith("触发时间"):
                logger.info("跳过自定义触发时间表: %s (%s)", tname, tid)
                continue
            if tname not in _DEFAULT_TABLE_NAMES:
                logger.info("跳过非默认表（可能是用户手动创建）: %s (%s)", tname, tid)
                continue
            del_url = f"{_FEISHU_API}/bitable/v1/apps/{app_token}/tables/{tid}"
            _httpx.delete(del_url, headers=headers, timeout=15, verify=False)
            logger.info("已删除默认数据表: %s (%s)", tname, tid)
    except Exception as e:
        logger.warning("删除默认数据表失败: %s", e)


async def _verify_write_bitable_impl(request: Request):
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


def _scan_all_batch_records(after_date: str = "") -> list:
    """扫描所有批量执行记录（本地 + 云端），返回批次列表

    :param after_date: 日期过滤（YYYY-MM-DD），跳过该日期之前的批次
    :return: [{batch_id, date, name, source, total, success, fail, base_info, jira_list}]
    """
    batches = []
    doc_dir = get_path("doc_dir")
    cutoff_date = after_date[:10] if after_date else ""  # YYYY-MM-DD
    # 从配置读取 Jira 号字段名，兼容旧版 CSV 的 "jira号"/"Jira号" 列名
    _jira_col = load_config().get("feishu_bitable", {}).get("bugid_field", "jira号")

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
            jira_no = (r.get(_jira_col) or r.get("jira号") or r.get("Jira号") or "").strip()
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
            if cutoff_date and date_folder < cutoff_date:
                continue
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

    # 路径2：本地 data/unanalyzed/prod_batch_*.csv 和 regression_*.csv
    unanalyzed_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "unanalyzed")
    if os.path.isdir(unanalyzed_dir):
        for fname in sorted(os.listdir(unanalyzed_dir)):
            if not fname.endswith(".csv"):
                continue
            is_prod = fname.startswith("prod_batch_")
            is_regr = fname.startswith("regression_")
            if not is_prod and not is_regr:
                continue
            parts = fname.replace(".csv", "").split("_")
            date_str = f"{parts[2]}-{parts[3]}-{parts[4]}" if len(parts) >= 5 else ""
            if cutoff_date and date_str and date_str < cutoff_date:
                continue
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
                f_folder = f.get("folder", "")  # 日期子文件夹名，如 2026-10-11
                # 按日期跳过旧文件夹
                if cutoff_date and f_folder and f_folder < cutoff_date:
                    continue
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
                        jira_no = (r.get(_jira_col) or r.get("jira号") or r.get("Jira号") or "").strip()
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

