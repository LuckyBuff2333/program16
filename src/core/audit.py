"""随机抽查复核模块：从数据库抽样重新分析，与已入库字段对比供人工审核

规则：
- 每次从已入库表随机抽取指定数量（默认30）的 bugid；
- 已抽查过的 bugid 记录在报表目录的 audited_bugids.csv 中，下次抽样自动排除；
- 按 bugid 与触发时间重新调用 AI 日志分析工具，新结果与库中根因分析/分析流程字段做语义对比（千问 LLM 判定）；
- 达标条件：根因语义相似 且（步骤语义相似 或 综合分析语义相似）；
- 抽查重新分析文档存入 spotcheck/日期/re-bugid.md；
- 全部结果输出审核表格（audit_comparison.csv），不达标项单独输出报表（audit_failed_日期.csv）。
"""
import os
import random
from datetime import datetime

import pandas as pd

from src import db
from src.clients import ai_log_client
from src.config import get_path, load_config, setup_logger
from src.core import doc_generator, similarity

logger = setup_logger("audit")

# 审核表格列定义（中文表头）
AUDIT_COLUMNS = [
    "bugid", "触发时间", "新根因结论", "已入库根因分析", "根因相似度",
    "已入库分析流程", "流程相似度", "判定结果", "文档路径", "抽查时间", "人工审核结论",
]


def _spotcheck_day_dir() -> str:
    """获取当日 spotcheck 目录：spotcheck/日期/"""
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    spotcheck_dir = os.path.join(get_path("report_dir"), "..", "spotcheck", date_str)
    os.makedirs(spotcheck_dir, exist_ok=True)
    return os.path.abspath(spotcheck_dir)


def _audited_csv_path() -> str:
    """已抽查 bugid 记录文件路径"""
    cfg = load_config()["audit"]
    return os.path.join(get_path("report_dir"), cfg["audited_file"])


def load_audited_bugids() -> set:
    """读取历史已抽查的 bugid 集合"""
    path = _audited_csv_path()
    if not os.path.exists(path):
        return set()
    df = pd.read_csv(path, encoding="utf-8-sig")
    return {str(b) for b in df["bugid"].tolist()}


def _append_audited_records(rows: list):
    """将本次抽查的 bugid 追加到记录文件（含抽查时间，供追溯）"""
    df_new = pd.DataFrame(rows)
    path = _audited_csv_path()
    if os.path.exists(path):
        df_old = pd.read_csv(path, encoding="utf-8-sig")
        df_new = pd.concat([df_old, df_new], ignore_index=True)
    df_new.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("已抽查记录已更新: %s, 本次追加 %d 条", path, len(rows))


def _save_spotcheck_doc(bugid: str, report_text: str) -> str:
    """将抽查重新分析的文档存入 spotcheck/日期/re-bugid.md"""
    spotcheck_dir = _spotcheck_day_dir()
    doc_path = os.path.join(spotcheck_dir, f"re-{bugid}.md")
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    logger.info("抽查文档已存入: %s", doc_path)
    return doc_path


def _llm_judge_audit(stored: dict, new_conclusion: str, report_text: str) -> tuple:
    """用千问 LLM 判定抽查结果是否达标

    达标规则：根因语义相似 且（步骤语义相似 或 综合分析语义相似）
    :return: (cause_result, process_result, verdict)
    """
    stored_cause = stored.get("root_cause") or ""
    stored_process = stored.get("analysis_process") or ""
    new_steps_text = "\n".join(doc_generator.parse_doc_steps(report_text))

    # 1. 根因语义相似判定
    cause_judge = similarity.llm_semantic_judge(stored_cause, new_conclusion, "根因分析")

    # 2. 分析步骤语义相似判定
    process_judge = similarity.llm_semantic_judge(stored_process, new_steps_text, "分析步骤")

    # 3. 如果步骤不相似，尝试综合分析对比（已入库根因+步骤 vs 新根因+步骤）
    combined_judge = {"similar": False, "score": 0.0}
    if not process_judge["similar"]:
        stored_combined = f"{stored_cause}\n{stored_process}"
        new_combined = f"{new_conclusion}\n{new_steps_text}"
        combined_judge = similarity.llm_semantic_judge(stored_combined, new_combined, "综合分析")

    # 达标条件：根因相似 且（步骤相似 或 综合分析相似）
    process_similar = process_judge["similar"] or combined_judge["similar"]
    verdict = "达标" if (cause_judge["similar"] and process_similar) else "不达标"

    logger.info("LLM 抽查判定: bugid 根因=%s(%.2f), 步骤=%s(%.2f), 综合=%s(%.2f) → %s",
                cause_judge["similar"], cause_judge["score"],
                process_judge["similar"], process_judge["score"],
                combined_judge["similar"], combined_judge["score"], verdict)
    return cause_judge, process_judge, verdict


def _audit_single(bugid: str, trigger_time) -> dict:
    """对单个 bugid 执行重新分析并与库存储字段对比，返回审核表格行"""
    stored = db.fetch_stored_analysis(bugid)
    # 按 bugid 与触发时间重新调用 AI 日志分析工具
    response = ai_log_client.analyze_logs(bugid, str(trigger_time) if trigger_time else None)
    report_text = ai_log_client.extract_report(response)

    # 新结果与库存储字段做 LLM 语义对比
    new_conclusion = doc_generator.parse_conclusion(report_text)
    cause_judge, process_judge, verdict = _llm_judge_audit(stored, new_conclusion, report_text)

    # 将抽查文档存入 spotcheck 目录
    doc_path = _save_spotcheck_doc(bugid, report_text)

    return {
        "bugid": bugid,
        "触发时间": trigger_time or "-",
        "新根因结论": new_conclusion,
        "已入库根因分析": stored.get("root_cause") or "-",
        "根因相似度": cause_judge["score"],
        "已入库分析流程": (stored.get("analysis_process") or "-").replace("\n", " | "),
        "流程相似度": process_judge["score"],
        "判定结果": verdict,
        "文档路径": doc_path,
        "抽查时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "人工审核结论": "",
    }


def sample_and_audit(count: int = None) -> str:
    """随机抽查主流程：抽样 → 重新分析 → 对比 → 生成审核表格

    :param count: 抽样数量，默认取配置 sample_count
    :return: 审核表格 CSV 路径
    """
    cfg = load_config()["audit"]
    count = count or cfg.get("sample_count", 30)

    # 候选池排除历史已抽查的 bugid
    candidates = db.fetch_audit_candidates()
    audited = load_audited_bugids()
    pool = [c for c in candidates if c["bugid"] not in audited]
    logger.info("抽查候选: 库内 %d 个, 已抽查 %d 个, 可用 %d 个",
                len(candidates), len(audited), len(pool))
    if not pool:
        raise ValueError("无可抽查的 bugid（库内已全部抽查过或库为空）")
    if len(pool) < count:
        logger.warning("可用候选不足 %d 个，本次抽查全部 %d 个", count, len(pool))
        count = len(pool)

    sampled = random.sample(pool, count)
    rows = []
    for item in sampled:
        try:
            rows.append(_audit_single(item["bugid"], item["trigger_time"]))
        except Exception as e:
            # 单条失败不中断整批抽查，失败行也进审核表格供人工处理
            logger.error("抽查失败: bugid=%s, 错误: %s", item["bugid"], e)
            rows.append({
                "bugid": item["bugid"], "触发时间": item["trigger_time"] or "-",
                "新根因结论": "-", "已入库根因分析": "-", "根因相似度": "-",
                "已入库分析流程": "-", "流程相似度": "-", "判定结果": "分析失败",
                "文档路径": "-",
                "抽查时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "人工审核结论": f"分析失败: {str(e)[:200]}",
            })

    # 生成人工审核表格并持久化已抽查记录
    df = pd.DataFrame(rows, columns=AUDIT_COLUMNS)
    day_dir = _spotcheck_day_dir()
    report_path = os.path.join(day_dir, cfg["report_file"])
    # 同日多次抽查时，新结果前置（最新在上），旧结果追加在下，中间插入空行分隔
    if os.path.exists(report_path):
        df_old = pd.read_csv(report_path, encoding="utf-8-sig")
        separator = pd.DataFrame([{col: "" for col in AUDIT_COLUMNS}])
        df = pd.concat([df, separator, df_old], ignore_index=True)
    df.to_csv(report_path, index=False, encoding="utf-8-sig")
    logger.info("抽查审核表格已生成: %s, 本次 %d 条, 合计 %d 条", report_path, len(rows), len(df))
    # 不达标项单独输出报表
    failed_rows = [r for r in rows if r.get("判定结果") != "达标"]
    if failed_rows:
        _save_failed_report(failed_rows, day_dir)
    _append_audited_records([
        {"bugid": r["bugid"], "抽查时间": r["抽查时间"], "抽查结果": r.get("判定结果", "-")} for r in rows
    ])
    return report_path


def _save_failed_report(failed_rows: list, day_dir: str = None) -> str:
    """将不达标项单独输出到审计不达标日报表（spotcheck/日期/）"""
    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = day_dir or _spotcheck_day_dir()
    filename = f"audit_failed_{today}.csv"
    path = os.path.join(day_dir, filename)
    df = pd.DataFrame(failed_rows, columns=AUDIT_COLUMNS)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("不达标报表已生成: %s, 共 %d 条", path, len(failed_rows))
    return path
