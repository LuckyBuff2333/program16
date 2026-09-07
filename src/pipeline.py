"""主流程编排：内容补充模式 —— 对缺失字段执行补充填充

输入表格 6 列：jira号、分析问题时间、AI分析结果(飞书链接)、AI评论总结、rootcause、结果置信度
过滤规则：重复 bugid 且其余 5 字段均有非空值时才跳过，其余走补充流程
"""
import csv
import os
from datetime import datetime

from src import db
from src.clients import ai_log_client, bug_source, diana_client, jira_client, kb_client, feishu_client
from src.config import get_path, load_config, setup_logger
from src.core import doc_generator, filter as comment_filter
from src.core import report as report_module
from src.core import semantic as semantic_module
from src.core import similarity

logger = setup_logger("pipeline")


def _extract_error_detail(e: Exception) -> str:
    """提取更具体的错误信息，包含异常类型、状态码、响应内容"""
    import httpx
    err_type = type(e).__name__
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        url = e.request.url
        if status == 404:
            return f"[{err_type}] HTTP 404: 接口路径不存在，请检查 URL: {url}"
        try:
            body = e.response.json()
            detail = body.get("message") or body.get("error") or str(body)[:200]
        except Exception:
            detail = e.response.text[:300] if e.response.text else "无响应内容"
        return f"[{err_type}] HTTP {status}: {detail}"
    if isinstance(e, httpx.TimeoutException):
        return f"[{err_type}] 请求超时，请检查服务是否正常运行"
    if isinstance(e, httpx.ConnectError):
        return f"[{err_type}] 连接失败，请检查服务地址是否正确"
    if isinstance(e, ValueError):
        return f"[{err_type}] {str(e)}"
    return f"[{err_type}] {str(e)[:500]}"


# 触发时间记录存储目录
_TRIGGER_TIME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "trigger_times")


def _save_trigger_time(bugid: str, trigger_time: str):
    """将提取到的触发时间保存到云端 bitable，失败时降级写本地 CSV"""
    try:
        from src.web.server import _save_trigger_time_to_cloud
        _save_trigger_time_to_cloud(bugid, trigger_time)
        logger.info("触发时间已保存到云端: %s → %s", bugid, trigger_time)
        return
    except Exception as e:
        logger.warning("云端触发时间保存失败，降级写本地 CSV: %s", e)
    # 降级：写本地 CSV
    os.makedirs(_TRIGGER_TIME_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    csv_path = os.path.join(_TRIGGER_TIME_DIR, f"trigger_times_{date_str}.csv")
    file_exists = os.path.exists(csv_path)
    try:
        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["jira号", "触发时间", "提取时间"])
            writer.writerow([bugid, trigger_time, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        logger.info("触发时间已保存到本地 CSV: %s → %s (%s)", bugid, trigger_time, csv_path)
    except Exception as e:
        logger.warning("触发时间保存失败: %s", e)


# 表格 6 列名称
TABLE_COLUMNS = ["jira号", "分析问题时间", "AI分析结果(飞书链接)", "AI评论总结", "rootcause", "结果置信度"]
# 除 bugid 外的其余 5 个字段
SUPPLEMENT_FIELDS = TABLE_COLUMNS[1:]


def _is_row_complete(row: dict) -> bool:
    """判断行是否 5 个字段全有非空值"""
    return all((row.get(f) or "").strip() not in ("", "-", "None") for f in SUPPLEMENT_FIELDS)


def _filter_rows(rows: list) -> list:
    """过滤规则：重复 bugid 且 5 字段全有值才跳过，其余走补充流程"""
    seen_complete = set()
    result = []
    for row in rows:
        bugid = (row.get("jira号") or "").strip()
        if not bugid:
            continue
        if _is_row_complete(row):
            if bugid in seen_complete:
                logger.info("bugid=%s 重复且字段完整，跳过", bugid)
                continue
            seen_complete.add(bugid)
            result.append(row)
        else:
            # 字段不完整，走补充流程
            result.append(row)
    return result


def supplement_row(row: dict) -> dict:
    """对单行缺失字段执行补充，按依赖顺序填充：状态检查→AI分析→飞书→rootcause→置信度"""
    bugid = (row.get("jira号") or "").strip()
    trigger_time = (row.get("分析问题时间") or "").strip()
    feishu_link = (row.get("AI分析结果(飞书链接)") or "").strip()
    result = dict(row)

    # 前置检查：仅处理状态为 Closed 的 bug
    issue = jira_client.fetch_issue(bugid)
    status = jira_client.extract_status(issue)
    if status and status.lower() != "closed":
        raise ValueError(f"Jira 状态为 [{status}]，仅 Closed 状态才进入补充流程")

    # 触发时间提取：若无传入则从评论区提取日志时间（提取失败不阻断流程）
    if not trigger_time:
        try:
            extracted_time = jira_client.extract_trigger_time_from_issue(issue)
            if extracted_time:
                trigger_time = extracted_time
                result["分析问题时间"] = trigger_time
                _save_trigger_time(bugid, trigger_time)
                logger.info("bugid=%s 从评论提取触发时间: %s", bugid, trigger_time)
            else:
                logger.info("bugid=%s 评论中未提取到日志时间", bugid)
        except Exception as e:
            logger.warning("bugid=%s 触发时间提取异常（不阻断流程）: %s", bugid, e)

    # 检查本地是否已有分析报告，无本地文档且无飞书链接时调用 AI 日志分析接口生成
    has_local_doc = False
    try:
        doc_generator.find_latest_document(bugid)
        has_local_doc = True
    except FileNotFoundError:
        pass
    if not has_local_doc and not feishu_link:
        try:
            logger.info("bugid=%s 无本地文档且无飞书链接，调用 AI 日志分析接口生成报告", bugid)
            response = ai_log_client.analyze_logs(bugid, trigger_time)
            report_text = ai_log_client.extract_report(response)
            doc_path = doc_generator.save_document(bugid, report_text)
            result["AI分析结果(飞书链接)"] = doc_path
            feishu_link = doc_path
        except Exception as e:
            logger.error("bugid=%s AI 日志分析失败（不阻断后续步骤）: %s", bugid, e)
            result["AI分析结果(飞书链接)"] = f"失败: {_extract_error_detail(e)}"
    elif not has_local_doc and feishu_link and feishu_link.startswith("http"):
        # 有飞书链接但无本地文档：通过飞书 Open API 下载文档并保存为 md
        try:
            doc_id = feishu_client.extract_doc_id_from_url(feishu_link)
            if not doc_id:
                raise ValueError(f"无法从飞书链接提取文档 ID: {feishu_link}")
            feishu_domain = feishu_client.extract_domain_from_url(feishu_link)
            logger.info("bugid=%s 从飞书文档下载分析报告: doc_id=%s, domain=%s", bugid, doc_id, feishu_domain)
            md_content = feishu_client.fetch_docx_as_markdown(doc_id, bugid=bugid, feishu_domain=feishu_domain)
            doc_path = doc_generator.save_document(bugid, md_content)
            logger.info("bugid=%s 飞书文档已下载到本地: %s", bugid, doc_path)
        except Exception as e:
            logger.error("bugid=%s 飞书文档下载失败（不阻断后续步骤）: %s", bugid, e)

    # 填充 rootcause：复用已获取的 issue（优先提取，供后续评论截断使用）
    rootcause = (row.get("rootcause") or "").strip()
    if not rootcause or rootcause in ("-", "None"):
        try:
            rootcause = _fill_rootcause(bugid, issue)
            result["rootcause"] = rootcause
        except Exception as e:
            logger.error("bugid=%s rootcause 填充失败: %s", bugid, e)
            result["rootcause"] = f"失败: {_extract_error_detail(e)}"

    # 填充 AI评论总结：用 rootcause 或 AI 报告结论截断评论 → LLM简化 → 生成 md
    comment_summary_path = (row.get("AI评论总结") or "").strip()
    if not comment_summary_path or comment_summary_path in ("-", "None"):
        try:
            cs_result = _fill_comment_summary(bugid, trigger_time, feishu_link, issue, rootcause)
            conclusion = cs_result["conclusion"]
            doc_path = cs_result["doc_path"]
            doc_url = cs_result.get("doc_url", "")
            link = doc_url or doc_path
            result["AI评论总结"] = f"{conclusion} [详情: {link}]" if conclusion else link
        except Exception as e:
            logger.error("bugid=%s AI评论总结填充失败: %s", bugid, e)
            result["AI评论总结"] = f"失败: {_extract_error_detail(e)}"

    # 填充结果置信度：计算根因对比 + 步骤对比的平均分
    confidence = (row.get("结果置信度") or "").strip()
    if not confidence or confidence in ("-", "None", "0"):
        try:
            confidence = _fill_confidence(bugid, feishu_link, rootcause, issue)
            result["结果置信度"] = confidence
        except Exception as e:
            logger.error("bugid=%s 置信度计算失败: %s", bugid, e)
            result["结果置信度"] = f"失败: {_extract_error_detail(e)}"

    return result


# 符合需求/符合预期类通用根因关键词（语义上无具体根因信息）
_GENERIC_ROOTCAUSE_KEYWORDS = ("符合需求", "符合预期", "需求符合", "预期行为", "设计如此", "非问题")


def _is_generic_rootcause(rootcause: str) -> bool:
    """判断 Jira 根因是否为无具体信息的通用表述（如“符合预期”）"""
    if not rootcause:
        return False
    # 去除括号内容后判断纯根因文本
    base = rootcause.split("（")[0].split("(")[0].strip()
    return any(kw in base for kw in _GENERIC_ROOTCAUSE_KEYWORDS) and len(base) <= 10


# LLM 输出可能带的前缀，需在表格结论中去除
_CONCLUSION_PREFIXES = (
    "核心发现：", "核心发现:", "核心发现 - ",
    "分析结论：", "分析结论:", "排查结论：", "排查结论:",
    "结论：", "结论:", "发现：", "发现:",
    "概括：", "概括:", "总结：", "总结:",
    "核心语义：", "核心语义:",
)


def _strip_conclusion_prefix(text: str) -> str:
    """去除 LLM 输出中常见的前缀标签（如“核心发现：”“结论：”等）"""
    if not text:
        return text
    cleaned = text.strip()
    for prefix in _CONCLUSION_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    return cleaned


def _fill_comment_summary(bugid: str, trigger_time: str, feishu_link: str,
                          issue: dict = None, rootcause: str = "") -> dict:
    """填充 AI评论总结：优先复用本地已有文档，否则 全部评论 → LLM简化 → 合并核心语义 → 生成 md

    :return: {"conclusion": 核心语义结论, "doc_path": md文档路径, "doc_url": 在线文档链接}
    """
    # 优先复用本地已有的评论分析文档（避免重复分析）
    try:
        doc_dir = get_path("doc_dir")
        for day in sorted(os.listdir(doc_dir), reverse=True):
            candidate = os.path.join(doc_dir, day, f"{bugid}_comments.md")
            if os.path.exists(candidate):
                with open(candidate, "r", encoding="utf-8") as f:
                    content = f.read()
                # 从文档中提取结论（兼容新旧格式：优先“排查摘要”→“核心语义摘要”，回退“排查结论”→“核心语义”段落首段）
                conclusion = ""
                for line in content.splitlines():
                    if line.startswith("**排查摘要**") or line.startswith("**核心语义摘要**"):
                        conclusion = line.replace("**排查摘要**", "").replace("**核心语义摘要**", "").strip().lstrip("：:").strip()
                        break
                if not conclusion:
                    in_section = False
                    for line in content.splitlines():
                        if line.startswith("## 排查结论") or line.startswith("## 核心语义"):
                            in_section = True
                            continue
                        if in_section and line.strip() and not line.startswith("#"):
                            # 优先用 Diana 语义简化，回退截断
                            raw_text = line.strip()
                            try:
                                result = diana_client._llm_chat(
                                    f"用一句话（8到20字）概括以下排查结论，偏bug分析方向，必须是完整语义，只输出概括本身：\n{raw_text}\n概括：",
                                    max_tokens=50, timeout=15)
                                if result:
                                    conclusion = _strip_conclusion_prefix(result.strip().rstrip('。.'))
                            except Exception:
                                pass
                            if not conclusion:
                                conclusion = comment_filter._extract_core_summary(raw_text, max_len=20)
                                conclusion = _strip_conclusion_prefix(conclusion)
                            break
                        if in_section and line.startswith("##"):
                            break
                if conclusion:
                    logger.info("bugid=%s 复用本地评论文档: %s, 结论=%s", bugid, candidate, conclusion[:30])
                    return {"conclusion": conclusion, "doc_path": candidate, "doc_url": ""}
    except Exception as e:
        logger.debug("bugid=%s 查找本地评论文档失败: %s", bugid, e)
    # 1. 获取 AI 报告结论
    ai_conclusion = ""
    try:
        ai_content = _get_ai_report_content(bugid, feishu_link)
        ai_conclusion = doc_generator.parse_conclusion(ai_content)
    except (ValueError, FileNotFoundError):
        logger.info("bugid=%s 无 AI 报告", bugid)

    # 2. 获取 Jira 全部评论（不截断）
    if issue is None:
        issue = jira_client.fetch_issue(bugid)
    comments = jira_client.extract_comments(issue)
    logger.info("bugid=%s 共 %d 条评论，全部参与分析", bugid, len(comments))

    # 3. LLM 简化评论（语义优化+证据论证）
    summaries = comment_filter.summarize_comments(comments)

    # 4. AI评论分析：对评论整体分析并与AI日志分析对比
    comment_analysis = comment_filter.generate_comment_analysis(summaries, ai_conclusion)

    # 5. 核心语义 + 表格字段：让 Diana 模型概括AI评论分析
    overall_conclusion = ""
    table_conclusion = ""
    if comment_analysis and diana_client.is_diana_mode() and diana_client.check_connectivity():
        try:
            # 截断到完整句子（避免截断导致LLM看到半截文本胡说）
            def _truncate_to_sentence(text: str, max_len: int = 800) -> str:
                if len(text) <= max_len:
                    return text
                # 在 max_len 之前找最后一个句号
                truncated = text[:max_len]
                last_period = max(truncated.rfind('。'), truncated.rfind('.'), truncated.rfind('\n'))
                if last_period > max_len * 0.5:  # 确保截掉的内容不超过一半
                    return text[:last_period + 1]
                return truncated
            ca_text = _truncate_to_sentence(comment_analysis, 800)
            summary_prompt = (
                f"对以下分析内容用一段话概括：\n"
                f"用1-2句话（30-60字）概括排查结论，"
                f"包含关键发现和当前问题定位状态（已定位/待进一步排查）\n"
                f"要求：只输出概括内容，不要任何前缀、序号或解释。\n\n"
                f"分析内容：\n{ca_text}\n\n概括："
            )
            result = diana_client._llm_chat(summary_prompt, max_tokens=80, timeout=30)
            if result:
                # 过滤掉可能的序号前缀
                cleaned = result.strip()
                for prefix in ['第一行：', '1.', '- ', '• ']:
                    cleaned = cleaned.replace(prefix, '')
                lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
                if lines:
                    overall_conclusion = lines[0].rstrip('。.') + '。'
                logger.info("bugid=%s Diana概括排查结论: %s", bugid, overall_conclusion[:40])
        except Exception as e:
            logger.warning("bugid=%s Diana概括失败，回退规则: %s", bugid, e)
    # 回退：规则提取
    if not overall_conclusion and comment_analysis:
        overall_conclusion = comment_filter._extract_core_summary(comment_analysis, max_len=60)
    if not overall_conclusion:
        overall_conclusion = comment_filter.combine_comment_conclusions(summaries)
    # 表格结论：将排查结论交给 Diana 概括为 8-20 字的核心语义
    if overall_conclusion and not table_conclusion:
        try:
            simplify_prompt = (
                f"用一句话（8到20字）概括以下排查结论，偏bug分析方向，必须是完整语义，只输出概括本身：\n{overall_conclusion}\n概括："
            )
            result = diana_client._llm_chat(simplify_prompt, max_tokens=50, timeout=15)
            if result:
                table_conclusion = _strip_conclusion_prefix(result.strip().rstrip('。.'))
                logger.info("bugid=%s Diana表格结论: %s", bugid, table_conclusion)
        except Exception:
            pass
    if overall_conclusion and not table_conclusion:
        table_conclusion = _strip_conclusion_prefix(
            comment_filter._extract_core_summary(overall_conclusion, max_len=20))

    # 6. 生成 md 文档（排查结论 + 排查过程分析 + 时序排查详情）
    doc_path = comment_filter.generate_comment_summary_doc(
        bugid, summaries, overall_conclusion=overall_conclusion,
        ai_conclusion=ai_conclusion, comment_analysis=comment_analysis)

    # 上传云盘延至用户点击“写入表格”时执行，此处仅生成本地文档
    return {"conclusion": table_conclusion, "doc_path": doc_path, "doc_url": ""}


def _get_ai_report_content(bugid: str, feishu_link: str) -> str:
    """获取 AI 报告内容：优先本地 docs/ 目录，回退飞书 Open API"""
    try:
        doc_path = doc_generator.find_latest_document(bugid)
        return doc_generator.read_document(doc_path)
    except FileNotFoundError:
        pass
    # 回退：通过飞书 Open API 获取文档内容（HTTP GET 无法获取 SPA 渲染内容）
    if feishu_link and feishu_link.startswith("http"):
        doc_id = feishu_client.extract_doc_id_from_url(feishu_link)
        if doc_id:
            feishu_domain = feishu_client.extract_domain_from_url(feishu_link)
            logger.info("bugid=%s 本地无文档，尝试从飞书链接下载: link=%s, doc_id=%s, domain=%s",
                        bugid, feishu_link, doc_id, feishu_domain)
            try:
                return feishu_client.fetch_docx_as_markdown(doc_id, bugid=bugid, feishu_domain=feishu_domain)
            except Exception as e:
                logger.warning("bugid=%s 飞书文档下载失败: %s", bugid, e)
                raise
        else:
            logger.warning("bugid=%s 飞书链接无法提取 doc_id: %s", bugid, feishu_link)
    else:
        logger.info("bugid=%s 无飞书链接（feishu_link=%r），无法下载 AI 报告", bugid, feishu_link)
    raise ValueError(f"bugid={bugid} 无本地文档且无法从飞书链接获取内容")


def _fill_rootcause(bugid: str, issue: dict = None) -> str:
    """从 Jira API 获取 rootcause（复用已获取的 issue）"""
    if issue is None:
        issue = jira_client.fetch_issue(bugid)
    return jira_client.extract_rootcause(issue)


def _fill_confidence(bugid: str, feishu_link: str, rootcause: str, issue: dict = None) -> str:
    """计算结果置信度

    - 正常根因：(根因语义对比分 + 评论vs因果链分) / 2
    - 通用根因（符合预期等）：置信度 = 评论vs因果链语义相似度
    无 AI 报告时返回 0；AI 报告无法提取根因结论或分析步骤时直接判定对比失败
    """
    # 获取 AI 报告内容，无报告时置信度为 0（无法对比）
    try:
        ai_content = _get_ai_report_content(bugid, feishu_link)
    except (ValueError, FileNotFoundError):
        logger.info("bugid=%s 无 AI 报告，置信度为 0", bugid)
        return "0"
    ai_conclusion = doc_generator.parse_conclusion(ai_content)
    ai_steps = doc_generator.parse_doc_steps(ai_content)

    # AI 报告无法提取根因或步骤：直接判定对比失败
    if not ai_conclusion or not ai_steps:
        logger.info("bugid=%s AI报告无法提取根因(%s)或步骤(%d条)，置信度为0",
                    bugid, "有" if ai_conclusion else "无", len(ai_steps))
        return "0"

    is_generic = _is_generic_rootcause(rootcause)

    # 根因对比：Jira rootcause vs AI 根因结论（通用根因跳过）
    root_cause_score = 0.0
    if not is_generic and rootcause and ai_conclusion:
        root_cause_score = semantic_module.semantic_similarity(rootcause, ai_conclusion)

    # 步骤对比：Jira 评论提取步骤 vs AI 分析步骤（复用已获取的 issue）
    if issue is None:
        issue = jira_client.fetch_issue(bugid)
    comments = jira_client.extract_comments(issue)
    comment_steps, valid_comments = comment_filter.extract_analysis_steps(comments)

    step_score = 0.0
    if valid_comments and comment_steps:
        layer1_scores = semantic_module.semantic_best_matches(
            [c for c in valid_comments if c.strip()], comment_steps
        )
        layer1_score = sum(layer1_scores) / len(layer1_scores) if layer1_scores else 0.0
        joined_doc_steps = "，".join(ai_steps) if ai_steps else ""
        error_cause = jira_client.extract_error_cause(issue)
        layer2_score = semantic_module.semantic_similarity(error_cause, joined_doc_steps) if joined_doc_steps else 0.0
        step_score = max(layer1_score, layer2_score)

    # 通用根因时置信度直接等于评论vs因果链分，正常根因取平均
    if is_generic:
        confidence = round(step_score, 3)
        logger.info("bugid=%s 通用根因(%s)，置信度=评论因果链分%.3f", bugid, rootcause, step_score)
    else:
        confidence = round((root_cause_score + step_score) / 2, 3)
    return str(confidence)


def execute_single_flow(bugid: str, trigger_time: str = "", cancel_check=None, step_callback=None) -> dict:
    """单 bugid 流程执行：逐步检查 6 字段并补充缺失，返回每步详细结果

    cancel_check: 可选回调函数，返回 True 表示需要取消，流程会在当前步骤完成后立即停止
    step_callback: 可选回调函数，每步完成后立即调用（传入步骤结果字典），用于实时推送
    """
    import time
    import pandas as pd
    from src.config import get_path

    def _cancelled():
        """检查是否收到取消信号"""
        return cancel_check and cancel_check()

    steps = []
    row = {f: "" for f in SUPPLEMENT_FIELDS}
    row["jira号"] = bugid
    if trigger_time:
        row["分析问题时间"] = trigger_time
    failed = False
    feishu_link = (row.get("AI分析结果(飞书链接)") or "").strip()
    issue = {}

    def _step(num, name, ok, skipped=False, elapsed=0.0, summary="", detail=None, error=None):
        result = {"step": num, "name": name, "ok": ok, "skipped": skipped,
                "elapsed": round(elapsed, 2), "summary": summary,
                "detail": detail, "error": error}
        if step_callback:
            step_callback(result)
        return result

    # Step 1: Jira 状态检查
    t0 = time.time()
    try:
        issue = jira_client.fetch_issue(bugid)
        status = jira_client.extract_status(issue)
        elapsed = time.time() - t0
        issue_key = issue.get("key") or bugid
        issue_summary = (issue.get("fields") or {}).get("summary") or ""
        if status and status.lower() != "closed":
            steps.append(_step(1, "Jira状态检查", False, elapsed=elapsed,
                               summary=f"状态为 [{status}]，仅 Closed 允许",
                               detail={"status": status, "key": issue_key, "summary": issue_summary},
                               error=f"Jira 状态为 [{status}]，仅 Closed 状态才进入补充流程"))
            failed = True
        else:
            steps.append(_step(1, "Jira状态检查", True, elapsed=elapsed,
                               summary=f"状态: {status or 'Closed'}",
                               detail={"status": status, "key": issue_key, "summary": issue_summary}))
    except Exception as e:
        elapsed = time.time() - t0
        steps.append(_step(1, "Jira状态检查", False, elapsed=elapsed,
                           summary="Jira 查询失败", error=_extract_error_detail(e)))
        failed = True

    # 触发时间自动提取：在 AI 分析前从评论/附件提取（提取失败不阻断流程）
    if not failed and not trigger_time:
        try:
            extracted = jira_client.extract_trigger_time_from_issue(issue)
            if extracted:
                trigger_time = extracted
                row["分析问题时间"] = trigger_time
                _save_trigger_time(bugid, trigger_time)
                logger.info("flow: bugid=%s 自动提取触发时间: %s", bugid, trigger_time)
        except Exception as e:
            logger.warning("flow: bugid=%s 触发时间提取异常（不阻断流程）: %s", bugid, e)

    # Step 2: 字段完整性检查
    if not failed and not _cancelled():
        t0 = time.time()
        try:
            date_str = datetime.now().strftime("%Y-%m-%d")
            csv_path = os.path.join(get_path("doc_dir"), date_str, f"{date_str}_daily.csv")
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path, encoding="utf-8-sig")
                first_col = df.columns[0]
                df = df[df[first_col].notna() & (df[first_col].astype(str).str.strip() != "")]
                df = df.fillna("").astype(str)
                match = df[df["jira号"].astype(str) == bugid]
                if not match.empty:
                    for f in SUPPLEMENT_FIELDS:
                        if f in match.columns:
                            row[f] = match.iloc[0].get(f, "")
        except Exception:
            pass
        missing = [f for f in SUPPLEMENT_FIELDS
                   if (row.get(f) or "").strip() in ("", "-", "None")]
        complete = [f for f in SUPPLEMENT_FIELDS if f not in missing]
        elapsed = time.time() - t0
        msg = f"{len(complete)}/5 字段已有值"
        if missing:
            msg += f"，缺失: {', '.join(missing)}"
        field_values = {f: (row.get(f) or "").strip() for f in SUPPLEMENT_FIELDS}
        steps.append(_step(2, "字段检查", True, elapsed=elapsed, summary=msg,
                           detail={"missing": missing, "complete": complete, "field_values": field_values}))
        all_complete = len(missing) == 0

        # Step 3: AI 日志分析
        if not failed and not _cancelled():
            t0 = time.time()
            need_ai = ("分析问题时间" in missing) or ("AI分析结果(飞书链接)" in missing)
            feishu_link = (row.get("AI分析结果(飞书链接)") or "").strip()
            if need_ai:
                # 检测 AI 分析接口连通性（15s 超时，避免 3 次重试 ×30s 连接超时的长等待）
                api_reachable = True
                try:
                    import socket
                    from urllib.parse import urlparse
                    parsed = urlparse(load_config()["ai_log_api"]["url"])
                    sock = socket.create_connection(
                        (parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)),
                        timeout=15)
                    sock.close()
                except Exception:
                    api_reachable = False
                if not api_reachable:
                    elapsed = time.time() - t0
                    steps.append(_step(3, "AI日志分析", False, elapsed=elapsed,
                                       summary="AI分析接口不可达",
                                       error="AI 日志分析接口不可达，请确认是否在内网环境"))
                    failed = True
                else:
                    try:
                        logger.info("flow: bugid=%s 缺少AI分析字段，调用AI日志分析接口", bugid)
                        # 进度回调：异步任务提交成功时推送 50% 进度
                        def _on_async_submitted(msg):
                            if not trigger_time:
                                trigger_time_ref[0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            row["分析问题时间"] = trigger_time_ref[0]
                            elapsed = time.time() - t0
                            step_result = _step(3, "AI日志分析", True, elapsed=elapsed,
                                                summary=f"分析已提交(50%): {msg[:80]}，等待文档生成...",
                                                detail={"trigger_time": trigger_time_ref[0], "msg": msg, "pending": True})
                        trigger_time_ref = [trigger_time]  # 用列表绕过闭包赋值限制
                        response = ai_log_client.analyze_logs(
                            bugid, trigger_time, cancel_check=cancel_check,
                            progress_callback=_on_async_submitted)
                        # 检查响应是否表示失败（如轮询超时）
                        resp_code = response.get("code") if isinstance(response, dict) else None
                        if resp_code is not None and resp_code != 200 and resp_code != 0:
                            elapsed = time.time() - t0
                            err_msg = response.get("msg", "未知错误") if isinstance(response, dict) else str(response)
                            steps.append(_step(3, "AI日志分析", False, elapsed=elapsed,
                                               summary="AI 分析失败",
                                               error=f"{err_msg}"))
                            failed = True
                        else:
                            report_text = ai_log_client.extract_report(response)
                            doc_path = doc_generator.save_document(bugid, report_text)
                            row["AI分析结果(飞书链接)"] = doc_path
                            if not trigger_time:
                                trigger_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            row["分析问题时间"] = trigger_time
                            feishu_link = doc_path
                            elapsed = time.time() - t0
                            conclusion_preview = doc_generator.parse_conclusion(report_text)[:200] if report_text else ""
                            steps.append(_step(3, "AI日志分析", True, elapsed=elapsed,
                                               summary=f"报告已生成: {os.path.basename(doc_path)}",
                                               detail={"doc_path": doc_path, "content_length": len(report_text or ""),
                                                       "conclusion": conclusion_preview, "trigger_time": trigger_time}))
                    except Exception as e:
                        elapsed = time.time() - t0
                        steps.append(_step(3, "AI日志分析", False, elapsed=elapsed,
                                           summary="AI 分析失败", error=_extract_error_detail(e)))
                        failed = True
            elif all_complete:
                steps.append(_step(3, "AI日志分析", True, skipped=True,
                                   summary="所有字段已完整，跳过"))
            else:
                steps.append(_step(3, "AI日志分析", True, skipped=True,
                                   summary="AI分析字段已有值"))

        # Step 4: 飞书文档获取
        if not failed and not _cancelled():
            t0 = time.time()
            has_local_doc = False
            try:
                doc_generator.find_latest_document(bugid)
                has_local_doc = True
            except FileNotFoundError:
                pass
            if not has_local_doc and feishu_link and feishu_link.startswith("http"):
                try:
                    doc_id = feishu_client.extract_doc_id_from_url(feishu_link)
                    feishu_domain = feishu_client.extract_domain_from_url(feishu_link)
                    md_content = feishu_client.fetch_docx_as_markdown(
                        doc_id, bugid=bugid, feishu_domain=feishu_domain)
                    doc_path = doc_generator.save_document(bugid, md_content)
                    elapsed = time.time() - t0
                    steps.append(_step(4, "飞书文档获取", True, elapsed=elapsed,
                                       summary=f"文档已下载: {os.path.basename(doc_path)}",
                                       detail={"doc_path": doc_path, "content_length": len(md_content or ""),
                                               "doc_id": doc_id, "domain": feishu_domain}))
                except Exception as e:
                    elapsed = time.time() - t0
                    steps.append(_step(4, "飞书文档获取", False, elapsed=elapsed,
                                       summary="飞书文档下载失败", error=_extract_error_detail(e)))
                    failed = True
            else:
                reason = "本地文档已存在" if has_local_doc else "无飞书链接"
                steps.append(_step(4, "飞书文档获取", True, skipped=True, summary=reason))

        # Step 5: Rootcause 提取
        if not failed and not _cancelled():
            t0 = time.time()
            rootcause = (row.get("rootcause") or "").strip()
            if not rootcause or rootcause in ("-", "None"):
                try:
                    rootcause = _fill_rootcause(bugid, issue)
                    row["rootcause"] = rootcause
                    elapsed = time.time() - t0
                    # 根因分析内容为空时直接过滤
                    if not rootcause:
                        steps.append(_step(5, "Rootcause提取", False, elapsed=elapsed,
                                           summary="Jira根因分析内容为空，跳过分析",
                                           error="Jira根因分析内容为空，该条数据无需分析"))
                        failed = True
                    else:
                        steps.append(_step(5, "Rootcause提取", True, elapsed=elapsed,
                                           summary=f"{rootcause[:80]}",
                                           detail={"rootcause": rootcause}))
                except Exception as e:
                    elapsed = time.time() - t0
                    steps.append(_step(5, "Rootcause提取", False, elapsed=elapsed,
                                       summary="rootcause 获取失败", error=_extract_error_detail(e)))
                    failed = True
            else:
                steps.append(_step(5, "Rootcause提取", True, skipped=True,
                                   summary=f"已有: {rootcause[:50]}"))

        # Step 6: AI评论总结
        if not failed and not _cancelled():
            t0 = time.time()
            comment_summary = (row.get("AI评论总结") or "").strip()
            if not comment_summary or comment_summary in ("-", "None"):
                try:
                    cs_result = _fill_comment_summary(
                        bugid, trigger_time, feishu_link, issue, row.get("rootcause", ""))
                    conclusion = cs_result["conclusion"]
                    cs_path = cs_result["doc_path"]
                    doc_url = cs_result.get("doc_url", "")
                    link = doc_url or cs_path
                    row["AI评论总结"] = f"{conclusion} [详情: {link}]" if conclusion else link
                    row["doc_url"] = doc_url
                    elapsed = time.time() - t0
                    cs_content = conclusion
                    steps.append(_step(6, "AI评论总结", True, elapsed=elapsed,
                                       summary=f"已生成: {os.path.basename(cs_path)}",
                                       detail={"path": cs_path, "content_preview": cs_content}))
                except Exception as e:
                    elapsed = time.time() - t0
                    steps.append(_step(6, "AI评论总结", False, elapsed=elapsed,
                                       summary="评论总结生成失败", error=_extract_error_detail(e)))
                    failed = True
            else:
                steps.append(_step(6, "AI评论总结", True, skipped=True, summary="已有值"))

        # Step 7: 置信度计算
        if not failed and not _cancelled():
            t0 = time.time()
            confidence = (row.get("结果置信度") or "").strip()
            if not confidence or confidence in ("-", "None", "0"):
                try:
                    conf = _fill_confidence(
                        bugid, feishu_link, row.get("rootcause", ""), issue)
                    row["结果置信度"] = conf
                    elapsed = time.time() - t0
                    steps.append(_step(7, "置信度计算", True, elapsed=elapsed,
                                       summary=f"置信度: {conf}",
                                       detail={"confidence": conf, "threshold": load_config().get("similarity", {}).get("threshold", 0.7)}))
                except Exception as e:
                    elapsed = time.time() - t0
                    steps.append(_step(7, "置信度计算", False, elapsed=elapsed,
                                       summary="置信度计算失败", error=_extract_error_detail(e)))
                    failed = True
            else:
                steps.append(_step(7, "置信度计算", True, skipped=True,
                                   summary=f"已有: {confidence}"))

    cancelled = _cancelled()
    if cancelled and not failed:
        failed = True
    all_ok = not failed and not cancelled and _is_row_complete(row)
    # 将结果写入每日结论报表（合并模式）
    try:
        report_module.generate_daily_csv([row])
    except Exception as e:
        logger.warning("flow: bugid=%s 写入每日报表失败（不影响主流程）: %s", bugid, e)
    return {"bugid": bugid, "steps": steps, "row": row, "all_ok": all_ok,
            "failed": failed, "cancelled": cancelled, "complete": _is_row_complete(row)}


def verify_and_fill_row(bugid: str, row: dict) -> dict:
    """验证并填入三个字段（AI评论总结、rootcause、结果置信度）

    从 docs/ 找已有分析报告 + Jira 接口获取 issue，计算三个字段写回 row。
    :param bugid: Jira bug ID
    :param row: CSV 行字典（会被原地修改）
    :return: {"bugid": str, "success": bool, "error": str}
    """
    from src.clients import jira_client
    feishu_link = row.get("AI分析结果(飞书链接)", "") or ""
    trigger_time = row.get("分析问题时间", "") or ""
    # 获取 Jira issue
    issue = None
    try:
        issue = jira_client.fetch_issue(bugid)
    except Exception as e:
        return {"bugid": bugid, "success": False, "error": f"Jira获取失败: {e}"}
    # 1. rootcause
    try:
        rootcause = _fill_rootcause(bugid, issue)
        # Jira 根因分析内容为空时跳过
        if not rootcause:
            row["rootcause"] = ""
            return {"bugid": bugid, "success": False, "error": "Jira根因分析内容为空"}
        # 符合需求/符合预期类根因 → 追加 AI 精炼结论到括号中（仅影响展示）
        display_rootcause = rootcause
        if _is_generic_rootcause(rootcause):
            try:
                ai_content = _get_ai_report_content(bugid, feishu_link)
                ai_conclusion = doc_generator.parse_conclusion(ai_content)
                # 过滤无意义的 AI 结论（如“根因未明”“无法确定”等笼统表述）
                _VAGUE_KEYWORDS = ("根因未明", "无法确定", "无法定位", "无法判断", "暂无结论", "未明确")
                if ai_conclusion and not any(kw in ai_conclusion for kw in _VAGUE_KEYWORDS):
                    # 取首条分析的精炼主句，避免多行文本进入表格
                    ai_summary = comment_filter._extract_core_summary(ai_conclusion, max_len=60)
                    display_rootcause = f"{rootcause}（{ai_summary}）"
            except (ValueError, FileNotFoundError):
                pass  # 无 AI 报告，保持原 rootcause
        row["rootcause"] = comment_filter._clean_table_text(display_rootcause)
    except Exception as e:
        row["rootcause"] = ""
        return {"bugid": bugid, "success": False, "error": f"rootcause提取失败: {e}"}
    # 2. AI评论总结
    try:
        cs_result = _fill_comment_summary(bugid, trigger_time, feishu_link, issue, rootcause)
        conclusion = comment_filter._clean_table_text(cs_result["conclusion"])
        doc_path = cs_result["doc_path"]
        doc_url = cs_result.get("doc_url", "")
        link = doc_url or doc_path
        row["AI评论总结"] = f"{conclusion} [详情: {link}]" if conclusion else link
        row["doc_url"] = doc_url
        row["doc_path"] = doc_path
    except Exception as e:
        row["AI评论总结"] = ""
        return {"bugid": bugid, "success": False, "error": f"评论总结生成失败: {e}"}
    # 3. 结果置信度
    try:
        confidence = _fill_confidence(bugid, feishu_link, rootcause, issue)
        row["结果置信度"] = confidence
    except Exception as e:
        row["结果置信度"] = "0"
        return {"bugid": bugid, "success": False, "error": f"置信度计算失败: {e}"}

    # 3.1 根据置信度结果将评论文档分类存储到 True/False 子文件夹
    if doc_path and os.path.isfile(doc_path):
        try:
            from src.config import load_config
            threshold = float(load_config().get("similarity", {}).get("threshold", 0.7))
            conf_val = float(confidence or 0)
            passed = conf_val >= threshold
            # 目标目录：日期文件夹/True 或 日期文件夹/False
            date_dir = os.path.dirname(doc_path)
            target_dir = os.path.join(date_dir, "True" if passed else "False")
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, os.path.basename(doc_path))
            import shutil
            shutil.move(doc_path, target_path)
            # 更新 doc_path 为新路径
            doc_path = target_path
            row["doc_path"] = doc_path
            logger.info("bugid=%s 评论文档分类存储: %s", bugid, target_path)
        except Exception as e:
            logger.warning("bugid=%s 评论文档分类存储失败: %s", bugid, e)

    # 4. 备用语义相似度（AI日志分析结论核心语义 vs AI评论排查结论核心语义），用于置信度不达标时兆底判定
    extra_similarity = 0.0
    try:
        # 获取 AI 日志分析完整结论段落
        ai_content = _get_ai_report_content(bugid, feishu_link)
        ai_log_conclusion = doc_generator.parse_conclusion(ai_content)
        # 获取 AI 评论分析文档的排查结论段落
        comment_conclusion = ""
        if doc_path and os.path.isfile(doc_path):
            with open(doc_path, "r", encoding="utf-8") as f:
                in_section = False
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("## 排查结论"):
                        in_section = True
                        continue
                    if in_section and stripped.startswith("##"):
                        break
                    if in_section and stripped:
                        comment_conclusion += stripped + "\n"
                comment_conclusion = comment_conclusion.strip()
        if ai_log_conclusion and comment_conclusion:
            extra_similarity = semantic_module.semantic_similarity(ai_log_conclusion, comment_conclusion)
            extra_similarity = round(extra_similarity, 3)
    except Exception:
        pass

    return {"bugid": bugid, "success": True, "error": "", "extra_similarity": extra_similarity}


def compare_bug_analysis(bugid: str, trigger_time: str = None, uploaded_rows: list = None) -> dict:
    """对单个 bug 执行完整对比：AI 报告 vs bug 单数据（根因 + 步骤）

    统一 pipeline 和 server 的对比逻辑。
    :return: 对比结果字典，含根因/步骤匹配度与结论
    """
    # 1. AI 分析并生成文档
    response = ai_log_client.analyze_logs(bugid, trigger_time)
    report_text = ai_log_client.extract_report(response)
    doc_path = doc_generator.save_document(bugid, report_text)
    doc_steps = doc_generator.parse_doc_steps(report_text)
    conclusion_text = doc_generator.parse_conclusion(report_text)

    # AI 报告无法提取根因或步骤：直接判定对比失败
    if not conclusion_text or not doc_steps:
        logger.info("bugid=%s AI报告无法提取根因(%s)或步骤(%d条)，对比直接失败",
                    bugid, "有" if conclusion_text else "无", len(doc_steps))
        return {
            "bugid": bugid, "doc_path": doc_path, "doc_steps": doc_steps,
            "ai_conclusion": conclusion_text, "bug_root_cause": "",
            "root_cause_score": 0.0, "root_cause_ok": False,
            "layer1_score": 0.0, "layer1_ok": False,
            "layer2_score": 0.0, "layer2_ok": False,
            "comment_compare_ok": False, "all_ok": False,
            "comments": [], "comment_steps": [], "valid_comments": [],
            "threshold": load_config()["similarity"].get("threshold", 0.7),
            "compare_mode": semantic_module.compare_mode(),
        }

    # 2. 获取 bug 单数据（根因 + 评论）
    bug_data = bug_source.load_bug_data(bugid, trigger_time, uploaded_rows)
    bug_root_cause = bug_data["root_cause"]
    comments = bug_data["comments"]
    # Jira 根因分析内容为空时直接过滤
    if not bug_root_cause:
        logger.info("bugid=%s Jira根因分析内容为空，跳过对比", bugid)
        return {
            "bugid": bugid, "doc_path": doc_path, "doc_steps": doc_steps,
            "ai_conclusion": conclusion_text, "bug_root_cause": "",
            "root_cause_score": 0.0, "root_cause_ok": False,
            "layer1_score": 0.0, "layer1_ok": False,
            "layer2_score": 0.0, "layer2_ok": False,
            "comment_compare_ok": False, "all_ok": False,
            "comments": comments, "comment_steps": [], "valid_comments": [],
            "threshold": load_config()["similarity"].get("threshold", 0.7),
            "compare_mode": semantic_module.compare_mode(),
            "skipped": True, "skip_reason": "Jira根因分析内容为空",
        }
    # 3. 步骤提取（不截断，用全部评论）
    comment_steps, valid_comments = comment_filter.extract_analysis_steps(comments)
    # 4. 根因对比：AI 分析结论 vs bug 单根因（通用根因跳过）
    sim_cfg = load_config()["similarity"]
    threshold = sim_cfg.get("threshold", 0.7)
    is_generic = _is_generic_rootcause(bug_root_cause)
    root_cause_score = 0.0
    root_cause_ok = True  # 通用根因默认通过
    if not is_generic and conclusion_text and bug_root_cause:
        root_cause_score = semantic_module.semantic_similarity(conclusion_text, bug_root_cause)
        root_cause_ok = root_cause_score >= threshold
    # 5. 评论对比：两层语义比对
    layer1_score = 0.0
    if valid_comments and comment_steps:
        layer1_scores = semantic_module.semantic_best_matches(
            [c for c in valid_comments if c.strip()], comment_steps
        )
        layer1_score = sum(layer1_scores) / len(layer1_scores) if layer1_scores else 0.0
    layer1_ok = layer1_score >= threshold
    joined_doc_steps = "，".join(doc_steps)
    layer2_score = semantic_module.semantic_similarity(bug_root_cause, joined_doc_steps) if joined_doc_steps else 0.0
    layer2_ok = layer2_score >= threshold
    comment_compare_ok = layer1_ok or layer2_ok
    # 通用根因时 all_ok 仅看评论对比，正常根因需两者都通过
    all_ok = (root_cause_ok and comment_compare_ok) if not is_generic else comment_compare_ok
    # 符合需求/符合预期类根因 → 追加 AI 结论到括号中（仅影响展示）
    display_root_cause = bug_root_cause
    if is_generic and conclusion_text:
        display_root_cause = f"{bug_root_cause}（{conclusion_text}）"
    logger.info("bugid=%s 对比完成: 根因=%.3f(%s), L1=%.3f(%s), L2=%.3f(%s), 通过=%s",
                bugid, root_cause_score, root_cause_ok, layer1_score, layer1_ok,
                layer2_score, layer2_ok, all_ok)
    return {
        "bugid": bugid, "doc_path": doc_path, "doc_steps": doc_steps,
        "ai_conclusion": conclusion_text, "bug_root_cause": display_root_cause,
        "root_cause_score": round(root_cause_score, 3), "root_cause_ok": root_cause_ok,
        "layer1_score": round(layer1_score, 3), "layer1_ok": layer1_ok,
        "layer2_score": round(layer2_score, 3), "layer2_ok": layer2_ok,
        "comment_compare_ok": comment_compare_ok, "all_ok": all_ok,
        "comments": comments, "comment_steps": comment_steps,
        "valid_comments": valid_comments, "threshold": threshold,
        "compare_mode": semantic_module.compare_mode(),
    }


def _analyze_single(bugid: str, trigger_time: str = None) -> dict:
    """对单个 bugid 执行 AI 分析、生成文档、Jira 比对，返回流水线结果"""
    result = compare_bug_analysis(bugid, trigger_time)
    return {
        "bugid": bugid,
        "trigger_time": trigger_time,
        "exec_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "success",
        "root_cause_ok": result["root_cause_ok"],
        "root_cause_score": result["root_cause_score"],
        "comment_compare_ok": result["comment_compare_ok"],
        "all_ok": result["all_ok"],
        "layer1_score": result["layer1_score"],
        "layer2_score": result["layer2_score"],
        "similarity_score": max(result["root_cause_score"], result["layer1_score"], result["layer2_score"]),
        "doc_path": result["doc_path"],
        "error_msg": None,
        "analysis_time": datetime.now(),
    }


def run_pipeline(rows: list) -> dict:
    """执行内容补充流程：对缺失字段补充，输出完整表格

    :param rows: 输入表格行列表（含 6 列字段）
    :return: {"csv_path": str, "rows": list, "stats": dict}
    """
    # 过滤：重复且完整才跳过
    filtered_rows = _filter_rows(rows)
    logger.info("输入 %d 行，过滤后 %d 行需处理", len(rows), len(filtered_rows))

    supplemented = []
    complete_count = 0
    for row in filtered_rows:
        if _is_row_complete(row):
            row["补充状态"] = "success"
            supplemented.append(row)
            complete_count += 1
        else:
            try:
                result = supplement_row(row)
                result["补充状态"] = "success" if _is_row_complete(result) else "部分补充"
                supplemented.append(result)
                if _is_row_complete(result):
                    complete_count += 1
            except Exception as e:
                logger.error("bugid=%s 补充失败: %s", row.get("jira号"), e)
                row["补充状态"] = f"失败: {_extract_error_detail(e)}"
                supplemented.append(row)

    # 生成报表
    csv_path = report_module.generate_daily_csv(supplemented)
    return {
        "csv_path": csv_path,
        "rows": supplemented,
        "stats": {
            "total": len(supplemented),
            "complete": complete_count,
            "supplemented": len(supplemented) - complete_count,
        },
    }


def retry_bug(bugid: str) -> dict:
    """失败 bug 重新补充：开发手工触发，重新走补充流程"""
    logger.info("重新补充 bugid=%s", bugid)
    row = {"jira号": bugid, "分析问题时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "AI分析结果(飞书链接)": "", "AI评论总结": "", "rootcause": "", "结果置信度": ""}
    result = supplement_row(row)
    csv_path = report_module.generate_daily_csv([result])
    return {"csv_path": csv_path, "rows": [result]}


def store_bug(bugid: str) -> None:
    """知识库入库：由开发确认分析正确后手工执行，推送文档并写入本地库供抽查"""
    doc_path = doc_generator.find_latest_document(bugid)
    doc_content = doc_generator.read_document(doc_path)
    kb_client.store_to_knowledge_base(bugid, doc_content)
    # 将根因与分析流程写入 kb_analysis 表（抽查候选池）
    conclusion = doc_generator.parse_conclusion(doc_content)
    steps = doc_generator.parse_doc_steps(doc_content)
    trigger_time = _get_trigger_time_from_report(bugid)
    db.save_stored_analysis(bugid, trigger_time, conclusion, "\n".join(steps))
    logger.info("bugid=%s 分析文档已手工推入知识库: %s", bugid, doc_path)


def _get_trigger_time_from_report(bugid: str) -> str:
    """从当日结论报表中读取 bugid 对应的触发时间"""
    import os
    from src.config import get_path
    date_str = datetime.now().strftime("%Y-%m-%d")
    csv_path = os.path.join(get_path("doc_dir"), date_str, f"{date_str}_daily.csv")
    if not os.path.exists(csv_path):
        return ""
    import pandas as pd
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    # 过滤空行
    df = df[df["jira号"].notna() & (df["jira号"].astype(str).str.strip() != "")]
    match = df[df["jira号"].astype(str).str.endswith(bugid)]
    if not match.empty:
        val = match.iloc[0].get("分析问题时间", "")
        return "" if str(val) == "-" else str(val)
    return ""
