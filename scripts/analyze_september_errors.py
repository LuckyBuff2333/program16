#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
9月批量执行错误分析脚本
从云端(降级本地CSV)读取2026-09批量执行记录，关联数据沉淀多维表格，
区分执行问题/分析问题并做错误类型统计，生成离线自包含HTML报告。
"""
import csv
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import setup_logger, get_path
from src.clients import feishu_client

# 初始化日志
logger = setup_logger("september_error_analysis")

# 配置常量
SEPTEMBER_PREFIX = "2026-09"
BATCH_FOLDER_TOKEN = "RUaqfJVJLlZ3hkdKSEuclX7Ynje"
BITABLE_APP_TOKEN = "HOARbsrB0aSViFs5AjNchSQ0nAf"
BITABLE_TABLE_ID = "tblM5keGYh2y0aSX"
BUGID_FIELD = "jira号"

# 执行问题分类关键词（收窄匹配，避免裸数字误命中）
EXEC_ERROR_KEYWORDS = {
    "HTTP错误": ["Client error", "Server error", "Not Allowed", "Bad Gateway",
                 "Gateway Timeout", "Service Unavailable", "Internal Server Error",
                 "HTTP 4", "HTTP 5", "405 Not Allowed", "403 Forbidden", "404 Not Found"],
    "无触发时间": ["无触发时间"],
    "连接超时/连接失败": ["timeout", "超时", "ConnectError", "all connection attempts failed",
                        "connection refused", "连接失败", "无法连接", "timed out",
                        "WinError 10060", "连接尝试失败", "read operation timed out",
                        "WinError 10061", "积极拒绝"],
    "用户中断": ["任务已被用户取消", "手动中断", "被取消"],
}

# 分析问题分类关键词
ANALYSIS_ERROR_KEYWORDS = {
    "触发时间问题": ["未找到问题时间", "problem_time", "时间添加", "时间异常"],
    "无gmlogger文件": ["没有可下载的日志附件", "无gmlogger", "无日志附件"],
    "日志过滤逻辑": ["时间过滤后日志为空", "日志里无对应", "信息不全", "日志文件已损坏"],
    "模型调用失败": [r"第\d+轮.*调用失败", "LLM 调用失败"],
    "接口拥堵/并发": ["adjudication", "未获取有效响应", "接口拥堵"],
    "接口连接问题": ["server disconnected", "disconnected without sending", "连接失败"],
    "服务运行问题": ["服务有报错", "服务运行"],
    "上游jira卡住问题": ["504 Gateway Timeout", "502 Bad Gateway", "503 Service Unavailable",
                        "500 Internal Server Error", "Gateway Timeout"],
    "磁盘空间不足": ["no space left on device", "Errno 28"],
    "执行超时": ["分析任务执行超时", "分析任务被取消", "执行超时"],
    "解压问题": ["解压"],
    "问题重复": ["问题重复"],
}

# 多维表格「错误分类」字段值 → 预定义类别的映射（字段内容为原始错误描述，需归类）
_BITABLE_CAT_MAP = {
    "时间过滤后日志为空": "日志过滤逻辑",
    "处理后未找到有效的日志文件": "无gmlogger文件",
    "日志过滤逻辑": "日志过滤逻辑",
    "无gmlogger文件": "无gmlogger文件",
    "触发时间问题": "触发时间问题",
    "模型调用失败": "模型调用失败",
    "磁盘空间不足": "磁盘空间不足",
    "执行超时": "执行超时",
    "服务运行问题": "服务运行问题",
    "接口拥堵": "接口拥堵/并发",
    "解压问题": "解压问题",
    "问题重复": "问题重复",
    "上游jira卡住问题": "上游jira卡住问题",
}

# 人工审核结果 → 预定义类别映射（避免截断原文当类别名）
REVIEW_TO_CATEGORY = {
    "模型调用失败": "模型调用失败",
    "时间添加": "触发时间问题",
    "时间异常": "触发时间问题",
    "无gmlogger": "日志过滤逻辑",
    "无日志附件": "日志过滤逻辑",
    "损坏": "日志过滤逻辑",
    "日志里无对应": "日志过滤逻辑",
    "信息不全": "日志过滤逻辑",
    "解压问题": "解压问题",
    "解压": "解压问题",
    "接口无响应": "接口连接问题",
    "接口拥堵": "接口拥堵/并发",
    "手动中断": "接口拥堵/并发",
    "服务有报错": "服务运行问题",
    "执行超时": "执行超时",
    "问题重复": "问题重复",
    "正常处理机制": "正常处理机制",
    "待人工排查": "待人工排查",
    "待开发排查": "待开发排查",
    "分析can信号导致超时": "执行超时",
    "gmlogger文件已上传": "无gmlogger文件",
    "磁盘空间不足": "磁盘空间不足",
    "触发时间问题": "触发时间问题",
}

# 修复建议映射
FIX_SUGGESTIONS = {
    "HTTP错误": "检查接口权限与请求参数，确认服务端状态",
    "无触发时间": "在批量执行前补充触发时间字段，或使用自动提取功能",
    "连接超时/连接失败": "检查网络连接与目标服务可用性，适当增加超时时间",
    "用户中断": "非异常情况，无需处理",
    "触发时间问题": "确认Jira中触发时间字段已正确填写，或启用自动提取",
    "无gmlogger文件": "检查Jira附件中是否有gmlogger日志文件，或确认日志命名规范",
    "日志过滤逻辑": "检查日志文件内容与时间范围，确认过滤逻辑正确性",
    "模型调用失败": "检查模型服务状态与调用参数，适当重试或降级",
    "接口拥堵/并发": "降低并发数或错峰执行，避免接口拥堵",
    "接口连接问题": "检查服务端连接稳定性，考虑增加重试机制",
    "服务运行问题": "联系服务提供方排查服务端异常",
    "上游jira卡住问题": "Jira服务暂时不可用，稍后重试",
    "磁盘空间不足": "清理磁盘空间或扩容存储",
    "执行超时": "优化分析逻辑或增加超时时间",
    "解压问题": "检查压缩包完整性与解压工具兼容性",
    "问题重复": "非异常情况，无需处理",
    "正常处理机制": "非异常情况，无需处理",
    "待人工排查": "需人工排查具体原因",
    "待开发排查": "需开发排查具体原因",
    "其他(人工审核)": "需人工排查具体原因",
    "未归类": "需人工排查具体原因",
}


def _is_september_doc(name: str, folder: str) -> bool:
    """判断文档是否属于2026年9月批次

    优先按文档名中的日期前缀精确匹配(如 '批量执行 2026-09-30_193747')；
    文档名无日期时才退回用 folder 判断。
    """
    # 从文档名提取日期前缀：匹配 2026-09-xx 或 2026-09 xx 格式
    m = re.search(r'(202\d-\d{2})-\d{2}', name)
    if m:
        return m.group(1) == SEPTEMBER_PREFIX
    # 文档名中无明确日期，退回folder判断
    if folder:
        m2 = re.search(r'(202\d-\d{2})', folder)
        if m2:
            return m2.group(1) == SEPTEMBER_PREFIX
    return False


def _is_september_exec_time(exec_time: str) -> bool:
    """判断执行时间是否落在2026-09"""
    return exec_time.startswith(SEPTEMBER_PREFIX) if exec_time else False


def parse_markdown_table(md: str) -> list:
    """解析飞书文档Markdown中的批量执行表格"""
    rows = []
    lines = md.splitlines()
    header_idx = -1
    headers = []

    # 找到表头行（包含jira的行）
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and "jira" in stripped.lower():
            header_idx = i
            headers = [h.strip() for h in stripped.strip("|").split("|")]
            break

    if header_idx < 0:
        return rows

    # 找到分隔行并跳过
    data_start = header_idx + 1
    for i in range(header_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if re.match(r'^\|[-|:\s]+\|$', stripped):
            data_start = i + 1
            break
        data_start = i
        break

    # 解析数据行
    for line in lines[data_start:]:
        line = line.strip()
        if not line or not line.startswith("|"):
            continue
        if re.match(r'^\|[-|:\s]+\|$', line):
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < len(headers):
            cells.extend([""] * (len(headers) - len(cells)))

        row = {}
        for idx, h in enumerate(headers):
            row[h] = cells[idx] if idx < len(cells) else ""

        # 统一jira号字段（兼容大小写）
        jira_val = ""
        for key in ("Jira号", "jira号"):
            if key in row:
                jira_val = row[key].strip()
                break

        if jira_val:
            row["jira号"] = jira_val
            rows.append(row)

    return rows


def bitable_text(val) -> str:
    """多维表格字段值归一化为纯文本（兼容list/dict/标量）"""
    if val is None:
        return ""
    if isinstance(val, list):
        return "".join(bitable_text(item) for item in val)
    if isinstance(val, dict):
        return str(val.get("text", "") or val.get("name", "") or val.get("link", "") or "").strip()
    return str(val).strip()


def load_cloud_batches() -> tuple:
    """从云端加载9月批量执行记录

    Returns:
        (rows, data_source): rows为记录列表，data_source为数据来源标识
    """
    logger.info("开始从云端加载批量执行记录...")
    all_rows = []
    data_source = "云端+本地"

    try:
        # 列出文件夹内容
        files = feishu_client.list_folder_files(BATCH_FOLDER_TOKEN, recursive=True)
        logger.info(f"云端文件夹共找到 {len(files)} 个文件")

        # 精确过滤9月批次文档
        september_docs = []
        for f in files:
            if f.get("type") != "docx":
                continue
            name = f.get("name", "")
            folder = f.get("folder", "")
            if _is_september_doc(name, folder):
                september_docs.append(f)

        logger.info(f"9月批次文档共 {len(september_docs)} 个")

        # 逐个获取文档内容并解析
        for doc in september_docs:
            try:
                doc_token = doc.get("token", "")
                doc_name = doc.get("name", "")
                logger.info(f"正在获取文档: {doc_name}")

                md = feishu_client.fetch_docx_as_markdown(doc_token)
                rows = parse_markdown_table(md)

                # 为每条记录添加来源标记
                for row in rows:
                    row["_source"] = "云端"
                    row["_doc_name"] = doc_name

                all_rows.extend(rows)
                logger.info(f"文档 {doc_name} 解析到 {len(rows)} 条记录")

            except Exception as e:
                logger.error(f"获取文档 {doc.get('name', '')} 失败: {e}")
                continue

        logger.info(f"云端共加载 {len(all_rows)} 条记录")

    except Exception as e:
        logger.error(f"云端数据加载失败，将降级为本地CSV: {e}")
        data_source = "本地CSV(云端不可达)"

    return all_rows, data_source


def load_local_batches() -> list:
    """从本地CSV加载9月批量执行记录（使用utf-8-sig兼容BOM）"""
    logger.info("开始从本地CSV加载批量执行记录...")
    all_rows = []

    # 加载docs/2026-09-*/batch_*.csv
    for csv_file in Path(PROJECT_ROOT / "docs").glob("2026-09-*/batch_*.csv"):
        try:
            with open(csv_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row["_source"] = "本地"
                    row["_file"] = str(csv_file)
                    all_rows.append(row)
            logger.info(f"加载本地文件: {csv_file.name}")
        except Exception as e:
            logger.error(f"加载本地文件 {csv_file} 失败: {e}")

    # 加载data/unanalyzed/prod_batch_2026-09-*.csv
    for csv_file in Path(PROJECT_ROOT / "data" / "unanalyzed").glob("prod_batch_2026-09-*.csv"):
        try:
            with open(csv_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row["_source"] = "本地"
                    row["_file"] = str(csv_file)
                    all_rows.append(row)
            logger.info(f"加载本地文件: {csv_file.name}")
        except Exception as e:
            logger.error(f"加载本地文件 {csv_file} 失败: {e}")

    logger.info(f"本地共加载 {len(all_rows)} 条记录")
    return all_rows


def deduplicate_rows(rows: list) -> list:
    """按jira号去重，优先取执行时间在2026-09的记录，同月内取最晚

    去重时保留触发来源：若胜出记录缺少触发来源而落选记录有，则补充。
    """
    logger.info("开始去重处理...")
    jira_map = {}

    for row in rows:
        jira_no = (row.get("jira号") or row.get("Jira号") or "").strip()
        if not jira_no:
            continue

        exec_time = (row.get("执行时间") or "").strip()
        is_sep = _is_september_exec_time(exec_time)

        if jira_no not in jira_map:
            row["_is_sep"] = is_sep
            jira_map[jira_no] = row
        else:
            existing = jira_map[jira_no]
            existing_is_sep = existing.get("_is_sep", False)
            existing_time = (existing.get("执行时间") or "").strip()

            # 判断是否替换
            should_replace = False
            if is_sep and not existing_is_sep:
                should_replace = True
            elif is_sep == existing_is_sep and exec_time > existing_time:
                should_replace = True

            if should_replace:
                # 补充触发来源：新记录缺少时从旧记录继承
                if not (row.get("触发来源") or "").strip():
                    old_src = (existing.get("触发来源") or "").strip()
                    if old_src:
                        row["触发来源"] = old_src
                row["_is_sep"] = is_sep
                jira_map[jira_no] = row
            else:
                # 不替换，但补充旧记录的触发来源
                if not (existing.get("触发来源") or "").strip():
                    new_src = (row.get("触发来源") or "").strip()
                    if new_src:
                        existing["触发来源"] = new_src

    # 清除临时标记
    deduped = []
    for row in jira_map.values():
        row.pop("_is_sep", None)
        deduped.append(row)

    logger.info(f"去重后共 {len(deduped)} 条记录")
    return deduped


def load_bitable_records() -> dict:
    """加载多维表格记录，建立jira号到记录的映射（不传view_id，与全月统计口径一致）"""
    logger.info("开始加载多维表格记录...")
    jira_map = {}

    try:
        # 不传view_id：项目所有全月/批量统计口径都不带view_id
        records = feishu_client.list_bitable_records(
            BITABLE_APP_TOKEN, BITABLE_TABLE_ID, None, page_size=500
        )
        logger.info(f"多维表格共加载 {len(records)} 条记录")

        for rec in records:
            fields = rec.get("fields", {})
            jira_no = bitable_text(fields.get(BUGID_FIELD, ""))

            if not jira_no:
                continue

            # 提取关键字段（含错误分类/错误类型，优先复用表内已有分类）
            record_data = {
                "分析结果": bitable_text(fields.get("分析结果", "")),
                "错误信息": bitable_text(fields.get("错误信息", "")),
                "人工审核结果": bitable_text(fields.get("人工审核结果", "")),
                "触发来源": bitable_text(fields.get("触发来源", "")),
                "分析完成时间": bitable_text(fields.get("分析完成时间", "")),
                "错误分类": bitable_text(fields.get("错误分类", "")),
                "错误类型": bitable_text(fields.get("错误类型", "")),
            }

            if jira_no not in jira_map:
                jira_map[jira_no] = []
            jira_map[jira_no].append(record_data)

        logger.info(f"多维表格映射建立完成，共 {len(jira_map)} 个jira号")

    except Exception as e:
        logger.error(f"加载多维表格记录失败: {e}")

    return jira_map


def select_best_record(jira_no: str, bt_records: list, exec_time: str) -> dict:
    """为指定jira选择最佳的多维表格记录

    策略A: 候选=分析完成时间非空且>=批次执行时间的记录
    若候选为空则用全部记录兜底；候选按分析完成时间升序排序
    有成功记录取第一条成功，否则取最后一条(最晚失败)
    """
    if not bt_records:
        return {}

    # 筛选候选记录
    candidates = [r for r in bt_records
                  if r.get("分析完成时间", "") and r["分析完成时间"] >= exec_time]

    if not candidates:
        candidates = bt_records

    # 按分析完成时间排序
    candidates.sort(key=lambda x: x.get("分析完成时间", ""))

    # 优先取成功记录
    success_records = [r for r in candidates if r.get("分析结果", "") == "成功"]
    if success_records:
        return success_records[0]

    # 全失败取最后一条
    return candidates[-1]


def classify_exec_error(err_msg: str) -> str:
    """对执行侧错误文本进行分类"""
    if not err_msg:
        return "未归类"

    msg_lower = err_msg.lower()

    # 按优先级匹配关键词
    for category, keywords in EXEC_ERROR_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in msg_lower:
                return category

    return "未归类"


def _map_review_to_category(review: str) -> str:
    """将人工审核结果映射到预定义类别，避免截断原文当类别名"""
    for keyword, category in REVIEW_TO_CATEGORY.items():
        if keyword in review:
            return category
    # 无法映射时统一归入"其他(人工审核)"
    return "其他(人工审核)"


def classify_analysis_error(err_msg: str, human_review: str = "",
                            existing_category: str = "") -> str:
    """对分析侧错误文本进行分类

    优先使用多维表格已有的错误分类字段（映射到预定义类别），
    其次人工审核映射，最后关键词匹配。
    """
    # 优先复用多维表格已有分类字段：精确匹配或关键词归类
    if existing_category:
        # 精确匹配预定义类别
        if existing_category in _BITABLE_CAT_MAP:
            return _BITABLE_CAT_MAP[existing_category]
        # 尝试用关键词匹配将原始描述归类
        mapped = _classify_by_keywords(existing_category)
        if mapped != "未归类":
            return mapped

    if not err_msg and not human_review:
        return "未归类"

    msg = err_msg or ""
    msg_lower = msg.lower()
    review = human_review or ""

    # 人工审核结果映射到预定义类别
    if review:
        mapped = _map_review_to_category(review)
        if mapped != "其他(人工审核)":
            return mapped
        # 人工审核无法精确映射时，继续尝试错误信息关键词匹配

    # 检查错误信息关键词
    result = _classify_by_keywords(msg)
    if result != "未归类":
        return result

    # 人工审核有值但无法映射到预定义类别
    if review:
        return "其他(人工审核)"

    return "未归类"


def _classify_by_keywords(msg: str) -> str:
    """用关键词匹配对错误文本归类（内部复用）"""
    if not msg:
        return "未归类"
    msg_lower = msg.lower()
    for category, keywords in ANALYSIS_ERROR_KEYWORDS.items():
        for kw in keywords:
            if kw.startswith(r"第\d+轮"):
                if re.search(kw, msg):
                    return category
            elif kw.lower() in msg_lower:
                return category
    return "未归类"


def analyze_rows(rows: list, bt_map: dict) -> list:
    """分析每条记录，确定归属与错误类型"""
    logger.info("开始分析记录...")
    results = []

    for row in rows:
        jira_no = (row.get("jira号") or row.get("Jira号") or "").strip()
        if not jira_no:
            continue

        exec_result = (row.get("执行结果") or "").strip()
        exec_time = (row.get("执行时间") or "").strip()
        remark = (row.get("备注") or "").strip()
        trigger_source = (row.get("触发来源") or "").strip()
        source_mark = row.get("_source", "本地")

        result = {
            "jira号": jira_no,
            "执行结果": exec_result,
            "执行时间": exec_time,
            "触发来源": trigger_source,
            "来源标记": source_mark,
        }

        # 判断归属
        if exec_result == "失败":
            # 执行问题
            result["归属"] = "执行问题"
            result["错误类型"] = classify_exec_error(remark)
            result["错误原文"] = remark
            result["修复建议"] = FIX_SUGGESTIONS.get(result["错误类型"], "需人工排查")
        elif exec_result == "成功":
            # 检查多维表格记录
            bt_records = bt_map.get(jira_no, [])
            if bt_records:
                best_rec = select_best_record(jira_no, bt_records, exec_time)
                analysis_result = best_rec.get("分析结果", "")

                if analysis_result == "成功":
                    result["归属"] = "成功"
                    result["错误类型"] = ""
                    result["错误原文"] = ""
                    result["修复建议"] = ""
                elif analysis_result == "失败":
                    # 分析问题：优先使用表内已有分类字段
                    result["归属"] = "分析问题"
                    err_info = best_rec.get("错误信息", "")
                    human_review = best_rec.get("人工审核结果", "")
                    # 优先取多维表格已有的错误分类/错误类型字段
                    existing_cat = (best_rec.get("错误分类", "") or
                                    best_rec.get("错误类型", ""))
                    result["错误类型"] = classify_analysis_error(
                        err_info, human_review, existing_cat)
                    result["错误原文"] = err_info
                    result["修复建议"] = FIX_SUGGESTIONS.get(result["错误类型"], "需人工排查")
                else:
                    result["归属"] = "分析中/无记录"
                    result["错误类型"] = ""
                    result["错误原文"] = ""
                    result["修复建议"] = ""
            else:
                result["归属"] = "分析中/无记录"
                result["错误类型"] = ""
                result["错误原文"] = ""
                result["修复建议"] = ""
        else:
            result["归属"] = "未知"
            result["错误类型"] = ""
            result["错误原文"] = ""
            result["修复建议"] = ""

        results.append(result)

    logger.info(f"分析完成，共 {len(results)} 条结果")
    return results


def compute_statistics(results: list) -> dict:
    """计算统计数据"""
    logger.info("开始计算统计数据...")

    total = len(results)
    success_count = sum(1 for r in results if r["归属"] == "成功")
    exec_error_count = sum(1 for r in results if r["归属"] == "执行问题")
    analysis_error_count = sum(1 for r in results if r["归属"] == "分析问题")
    pending_count = sum(1 for r in results if r["归属"] == "分析中/无记录")

    # 成功率
    denominator = success_count + exec_error_count + analysis_error_count
    success_rate = (success_count / denominator * 100) if denominator > 0 else 0

    # 执行问题子类统计
    exec_subtypes = {}
    for r in results:
        if r["归属"] == "执行问题":
            subtype = r["错误类型"]
            exec_subtypes[subtype] = exec_subtypes.get(subtype, 0) + 1

    # 分析问题子类统计
    analysis_subtypes = {}
    for r in results:
        if r["归属"] == "分析问题":
            subtype = r["错误类型"]
            analysis_subtypes[subtype] = analysis_subtypes.get(subtype, 0) + 1

    # 按触发来源交叉统计
    source_stats = {}
    for r in results:
        source = r["触发来源"] or "未知"
        if source not in source_stats:
            source_stats[source] = {"成功": 0, "执行问题": 0, "分析问题": 0, "分析中/无记录": 0}
        cat = r["归属"]
        if cat in source_stats[source]:
            source_stats[source][cat] += 1

    stats = {
        "总jira数": total,
        "成功数": success_count,
        "执行问题数": exec_error_count,
        "分析问题数": analysis_error_count,
        "分析中数": pending_count,
        "成功率": success_rate,
        "执行问题子类": exec_subtypes,
        "分析问题子类": analysis_subtypes,
        "触发来源统计": source_stats,
    }

    logger.info(f"统计完成: 总数={total}, 成功={success_count}, 执行问题={exec_error_count}, "
                f"分析问题={analysis_error_count}, 分析中={pending_count}, 成功率={success_rate:.1f}%")

    return stats


def generate_donut_svg(stats: dict) -> str:
    """生成环形图SVG"""
    import math

    total = stats["总jira数"]
    if total == 0:
        return "<svg width='300' height='300'></svg>"

    categories = [
        ("成功", stats["成功数"], "#10b981"),
        ("执行问题", stats["执行问题数"], "#f59e0b"),
        ("分析问题", stats["分析问题数"], "#ef4444"),
        ("分析中", stats["分析中数"], "#6b7280"),
    ]

    cx, cy, r_outer, r_inner = 150, 150, 120, 70
    svg_parts = ['<svg width="300" height="300" viewBox="0 0 300 300" xmlns="http://www.w3.org/2000/svg">']

    start_angle = -90
    for name, count, color in categories:
        if count == 0:
            continue
        angle = (count / total) * 360
        end_angle = start_angle + angle
        start_rad = math.radians(start_angle)
        end_rad = math.radians(end_angle)

        x1_o = cx + r_outer * math.cos(start_rad)
        y1_o = cy + r_outer * math.sin(start_rad)
        x2_o = cx + r_outer * math.cos(end_rad)
        y2_o = cy + r_outer * math.sin(end_rad)
        x1_i = cx + r_inner * math.cos(end_rad)
        y1_i = cy + r_inner * math.sin(end_rad)
        x2_i = cx + r_inner * math.cos(start_rad)
        y2_i = cy + r_inner * math.sin(start_rad)

        large_arc = 1 if angle > 180 else 0
        path = (f'M {x1_o:.2f} {y1_o:.2f} '
                f'A {r_outer} {r_outer} 0 {large_arc} 1 {x2_o:.2f} {y2_o:.2f} '
                f'L {x1_i:.2f} {y1_i:.2f} '
                f'A {r_inner} {r_inner} 0 {large_arc} 0 {x2_i:.2f} {y2_i:.2f} Z')
        svg_parts.append(f'<path d="{path}" fill="{color}" opacity="0.9"/>')
        start_angle = end_angle

    svg_parts.append(f'<text x="{cx}" y="{cy-10}" text-anchor="middle" font-size="24" font-weight="bold" fill="#1f2937">{total}</text>')
    svg_parts.append(f'<text x="{cx}" y="{cy+15}" text-anchor="middle" font-size="14" fill="#6b7280">总数</text>')
    svg_parts.append('</svg>')
    return "\n".join(svg_parts)


def generate_bar_svg(subtypes: dict, title: str, color: str) -> str:
    """生成横向条形图SVG"""
    if not subtypes:
        return f"<div class='chart-title'>{title}</div><p>无数据</p>"

    sorted_items = sorted(subtypes.items(), key=lambda x: x[1], reverse=True)
    max_count = max(v for _, v in sorted_items) if sorted_items else 1

    bar_height = 28
    bar_gap = 8
    label_width = 160
    chart_width = 450
    svg_height = len(sorted_items) * (bar_height + bar_gap) + 40

    svg_parts = [f'<svg width="{label_width + chart_width + 60}" height="{svg_height}" xmlns="http://www.w3.org/2000/svg">']
    svg_parts.append(f'<text x="10" y="20" font-size="14" font-weight="bold" fill="#1f2937">{title}</text>')

    y_offset = 40
    for name, count in sorted_items:
        display_name = name if len(name) <= 14 else name[:14] + "…"
        svg_parts.append(f'<text x="10" y="{y_offset + bar_height/2 + 4}" font-size="11" fill="#4b5563">{display_name}</text>')
        bar_width = (count / max_count) * chart_width if max_count > 0 else 0
        svg_parts.append(f'<rect x="{label_width}" y="{y_offset}" width="{bar_width:.1f}" height="{bar_height}" fill="{color}" opacity="0.8" rx="4"/>')
        svg_parts.append(f'<text x="{label_width + bar_width + 8:.1f}" y="{y_offset + bar_height/2 + 4}" font-size="11" fill="#1f2937">{count}</text>')
        y_offset += bar_height + bar_gap

    svg_parts.append('</svg>')
    return "\n".join(svg_parts)


def _render_source_stats_table(source_stats: dict) -> str:
    """渲染触发来源交叉统计表格"""
    if not source_stats:
        return "<p>无触发来源数据</p>"
    rows_html = []
    for source in sorted(source_stats.keys()):
        data = source_stats[source]
        total_s = sum(data.values())
        rows_html.append(
            f"<tr><td>{source}</td><td>{total_s}</td>"
            f"<td>{data.get('成功', 0)}</td>"
            f"<td>{data.get('执行问题', 0)}</td>"
            f"<td>{data.get('分析问题', 0)}</td>"
            f"<td>{data.get('分析中/无记录', 0)}</td></tr>"
        )
    return "\n".join(rows_html)


def generate_html_report(results: list, stats: dict, data_source: str) -> str:
    """生成离线自包含HTML报告"""
    logger.info("开始生成HTML报告...")

    donut_svg = generate_donut_svg(stats)
    exec_bar_svg = generate_bar_svg(stats["执行问题子类"], "执行问题子类分布", "#f59e0b")
    analysis_bar_svg = generate_bar_svg(stats["分析问题子类"], "分析问题子类分布", "#ef4444")
    source_table_rows = _render_source_stats_table(stats["触发来源统计"])

    exec_errors = [r for r in results if r["归属"] == "执行问题"]
    analysis_errors = [r for r in results if r["归属"] == "分析问题"]

    # 归属名称 → CSS class映射（避免中文+斜杠在class名中引发转义问题）
    badge_cls = {"执行问题": "exec", "分析问题": "analysis", "成功": "success",
                 "分析中/无记录": "pending", "未知": "pending"}

    def render_table_rows(items: list) -> str:
        rows_html = []
        for item in items:
            err_text = (item['错误原文'] or '-')[:100]
            cls = badge_cls.get(item['归属'], 'pending')
            rows_html.append(
                f"<tr><td>{item['jira号']}</td>"
                f'<td><span class="badge badge-{cls}">{item["归属"]}</span></td>'
                f"<td>{item['错误类型'] or '-'}</td>"
                f'<td class="error-text">{err_text}</td>'
                f"<td>{item['触发来源'] or '-'}</td>"
                f"<td>{item['修复建议'] or '-'}</td></tr>"
            )
        return "\n".join(rows_html)

    def render_suggestions() -> str:
        suggestions_html = []
        all_subtypes = set(stats["执行问题子类"].keys()) | set(stats["分析问题子类"].keys())
        for subtype in sorted(all_subtypes):
            if not subtype:
                continue
            suggestion = FIX_SUGGESTIONS.get(subtype, "需人工排查")
            count = stats["执行问题子类"].get(subtype, 0) + stats["分析问题子类"].get(subtype, 0)
            suggestions_html.append(
                f'<div class="suggestion-item">'
                f'<div class="suggestion-type">{subtype} ({count}条)</div>'
                f'<div class="suggestion-text">{suggestion}</div></div>'
            )
        return "\n".join(suggestions_html)

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # CSS中避免\/转义：用属性选择器代替含斜杠的class名
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>2026年9月批量执行错误分析报告</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;padding:40px 20px;color:#1f2937}}
.container{{max-width:1400px;margin:0 auto;background:white;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,0.3);overflow:hidden}}
.header{{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;padding:40px;text-align:center}}
.header h1{{font-size:32px;margin-bottom:10px}}
.header .subtitle{{font-size:14px;opacity:0.9}}
.data-source{{background:#f3f4f6;padding:12px 40px;font-size:13px;color:#6b7280;border-bottom:1px solid #e5e7eb}}
.content{{padding:40px}}
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:20px;margin-bottom:40px}}
.stat-card{{background:#f9fafb;border-radius:12px;padding:24px;text-align:center;border:1px solid #e5e7eb;transition:transform 0.2s,box-shadow 0.2s}}
.stat-card:hover{{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,0.1)}}
.stat-value{{font-size:36px;font-weight:bold;margin-bottom:8px}}
.stat-label{{font-size:14px;color:#6b7280}}
.stat-success .stat-value{{color:#10b981}}
.stat-exec .stat-value{{color:#f59e0b}}
.stat-analysis .stat-value{{color:#ef4444}}
.stat-pending .stat-value{{color:#6b7280}}
.charts-section{{margin-bottom:40px}}
.chart-container{{background:#f9fafb;border-radius:12px;padding:24px;margin-bottom:24px;border:1px solid #e5e7eb;overflow-x:auto}}
.chart-title{{font-size:18px;font-weight:bold;margin-bottom:16px;color:#1f2937}}
.charts-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:24px}}
.suggestions-section{{margin-bottom:40px}}
.suggestion-item{{background:#f9fafb;border-radius:8px;padding:16px;margin-bottom:12px;border-left:4px solid #667eea}}
.suggestion-type{{font-weight:bold;margin-bottom:8px;color:#1f2937}}
.suggestion-text{{font-size:14px;color:#6b7280}}
.details-section{{margin-bottom:40px}}
.section-title{{font-size:20px;font-weight:bold;margin-bottom:16px;padding-bottom:8px;border-bottom:2px solid #e5e7eb}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f3f4f6;padding:12px;text-align:left;font-weight:600;border-bottom:2px solid #e5e7eb}}
td{{padding:12px;border-bottom:1px solid #e5e7eb}}
tr:hover{{background:#f9fafb}}
.badge{{display:inline-block;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:500}}
.badge-exec{{background:#fef3c7;color:#92400e}}
.badge-analysis{{background:#fee2e2;color:#991b1b}}
.badge-success{{background:#d1fae5;color:#065f46}}
.badge-pending{{background:#f3f4f6;color:#374151}}
.error-text{{max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.source-table{{margin-bottom:40px}}
.source-table table{{max-width:700px}}
.footer{{text-align:center;padding:20px;color:#6b7280;font-size:12px;border-top:1px solid #e5e7eb}}
</style>
</head>
<body>
<div class="container">
<div class="header">
<h1>2026年9月批量执行错误分析报告</h1>
<div class="subtitle">生成时间: {now_str}</div>
</div>
<div class="data-source">数据来源: {data_source}</div>
<div class="content">

<div class="stats-grid">
<div class="stat-card"><div class="stat-value">{stats['总jira数']}</div><div class="stat-label">总Jira数</div></div>
<div class="stat-card stat-success"><div class="stat-value">{stats['成功数']}</div><div class="stat-label">成功</div></div>
<div class="stat-card stat-exec"><div class="stat-value">{stats['执行问题数']}</div><div class="stat-label">执行问题</div></div>
<div class="stat-card stat-analysis"><div class="stat-value">{stats['分析问题数']}</div><div class="stat-label">分析问题</div></div>
<div class="stat-card stat-pending"><div class="stat-value">{stats['分析中数']}</div><div class="stat-label">分析中/无记录</div></div>
<div class="stat-card"><div class="stat-value">{stats['成功率']:.1f}%</div><div class="stat-label">成功率</div></div>
</div>

<div class="charts-section">
<div class="section-title">数据可视化</div>
<div class="charts-grid">
<div class="chart-container"><div class="chart-title">归属分布</div>{donut_svg}</div>
<div class="chart-container">{exec_bar_svg}</div>
<div class="chart-container">{analysis_bar_svg}</div>
</div>
</div>

<div class="source-table">
<div class="section-title">按触发来源(PC/线上)的错误分布</div>
<table>
<thead><tr><th>触发来源</th><th>合计</th><th>成功</th><th>执行问题</th><th>分析问题</th><th>分析中/无记录</th></tr></thead>
<tbody>{source_table_rows}</tbody>
</table>
</div>

<div class="suggestions-section">
<div class="section-title">修复建议</div>
{render_suggestions()}
</div>

<div class="details-section">
<div class="section-title">执行问题明细 ({len(exec_errors)}条)</div>
<table>
<thead><tr><th>Jira号</th><th>归属</th><th>错误类型</th><th>错误原文摘要</th><th>触发来源</th><th>修复建议</th></tr></thead>
<tbody>{render_table_rows(exec_errors)}</tbody>
</table>
</div>

<div class="details-section">
<div class="section-title">分析问题明细 ({len(analysis_errors)}条)</div>
<table>
<thead><tr><th>Jira号</th><th>归属</th><th>错误类型</th><th>错误原文摘要</th><th>触发来源</th><th>修复建议</th></tr></thead>
<tbody>{render_table_rows(analysis_errors)}</tbody>
</table>
</div>

</div>
<div class="footer">本报告由自动化脚本生成 | 仅供内部参考</div>
</div>
</body>
</html>"""

    return html


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("9月批量执行错误分析脚本启动")
    logger.info("=" * 60)

    try:
        # 1. 加载云端数据（带降级）
        cloud_rows, data_source = load_cloud_batches()

        # 2. 加载本地数据
        local_rows = load_local_batches()

        # 3. 合并数据
        all_rows = cloud_rows + local_rows
        logger.info(f"合并后共 {len(all_rows)} 条记录")

        # 4. 去重
        deduped_rows = deduplicate_rows(all_rows)

        # 5. 加载多维表格记录
        bt_map = load_bitable_records()

        # 6. 分析记录
        results = analyze_rows(deduped_rows, bt_map)

        # 7. 计算统计
        stats = compute_statistics(results)

        # 8. 生成HTML报告
        html_content = generate_html_report(results, stats, data_source)

        # 9. 写入文件
        report_dir = get_path("report_dir")
        report_path = os.path.join(report_dir, "september_error_analysis.html")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info(f"HTML报告已生成: {report_path}")
        logger.info("=" * 60)
        logger.info("分析完成！")
        logger.info(f"总Jira数: {stats['总jira数']}")
        logger.info(f"成功数: {stats['成功数']}")
        logger.info(f"执行问题数: {stats['执行问题数']}")
        logger.info(f"分析问题数: {stats['分析问题数']}")
        logger.info(f"分析中数: {stats['分析中数']}")
        logger.info(f"成功率: {stats['成功率']:.1f}%")
        logger.info(f"数据来源: {data_source}")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"脚本执行失败: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
