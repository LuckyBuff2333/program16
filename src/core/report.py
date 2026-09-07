"""每日分析结论 CSV 报表生成模块

工具运行结果只落地为 CSV 结论表格，不写入数据库；
同日多次运行时，新结果按 bugid 覆盖合并到已有报表中。
"""
import os
import shutil
from datetime import datetime

import pandas as pd

from src.config import get_day_dir, get_path, setup_logger

logger = setup_logger("report")

# 报表列定义（ 6 列新格式）
COLUMNS = ["jira号", "分析问题时间", "AI分析结果(飞书链接)", "AI评论总结", "rootcause", "结果置信度"]


def generate_daily_csv(results: list, date_str: str = None) -> str:
    """将分析结果生成/合并当日结论报表：docs/YYYY-MM-DD/YYYY-MM-DD_daily.csv

    与生成的 md 分析文档放在同一目录下；
    同日多次运行时，新结果放在最上面（最新优先），批次间插入空行分隔。

    :param results: 内存中的分析结果字典列表（含 6 列字段）
    :param date_str: 日期字符串，默认当天
    :return: 生成的 CSV 文件绝对路径
    """
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    day_dir = get_day_dir("doc_dir", date_str)
    csv_path = os.path.join(day_dir, f"{date_str}_daily.csv")
    df_new = pd.DataFrame(results, columns=COLUMNS)
    # 已存在当日报表时，新结果前置（最新在上），旧结果追加在下，中间插入空行分隔批次
    if os.path.exists(csv_path):
        df_old = pd.read_csv(csv_path, encoding="utf-8-sig")
        # 按 jira号 去重：同 bugid 的新结果覆盖旧行
        df_old = df_old[~df_old["jira号"].astype(str).isin(df_new["jira号"].astype(str))]
        # 插入空行作为批次分隔标记
        separator = pd.DataFrame([{col: "" for col in COLUMNS}])
        df_new = pd.concat([df_new, separator, df_old], ignore_index=True)
    # utf-8-sig 保证 Excel 打开中文不乱码
    df_new.to_csv(csv_path, index=False, encoding="utf-8-sig")
    logger.info("每日结论报表已生成: %s, 本次写入 %d 条, 合计 %d 条",
                csv_path, len(results), len(df_new))
    return csv_path


def classify_comment_docs(date_str: str = None) -> dict:
    """根据执行记录对当天评论分析文档分类存储到 True/False 子文件夹

    读取当日的 _daily.csv 和 jira_input_compare_log.csv，
    将尚未分类的 {bugid}_comments.md 文件移动到对应子目录。

    :param date_str: 日期字符串，默认当天
    :return: {"moved_true": int, "moved_false": int, "skipped": int}
    """
    from src.config import load_config
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    day_dir = os.path.join(get_path("doc_dir"), date_str)
    if not os.path.isdir(day_dir):
        return {"moved_true": 0, "moved_false": 0, "skipped": 0}

    threshold = float(load_config().get("similarity", {}).get("threshold", 0.7))

    # 从所有 CSV 记录中收集 bugid -> confidence 映射
    bugid_confidence = {}
    for csv_name in os.listdir(day_dir):
        if not csv_name.endswith(".csv"):
            continue
        csv_path = os.path.join(day_dir, csv_name)
        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            df = df.fillna("").astype(str)
            # 支持 jira号 列
            jira_col = "jira号" if "jira号" in df.columns else (df.columns[0] if len(df.columns) else None)
            conf_col = "结果置信度" if "结果置信度" in df.columns else None
            if jira_col and conf_col:
                for _, row in df.iterrows():
                    bugid = row[jira_col].strip()
                    conf_str = row[conf_col].strip()
                    if bugid and conf_str:
                        try:
                            bugid_confidence[bugid] = float(conf_str)
                        except ValueError:
                            pass
        except Exception as e:
            logger.debug("读取分类记录失败: %s, %s", csv_name, e)

    # 扫描日期文件夹下未分类的 _comments.md 文件
    moved_true = 0
    moved_false = 0
    skipped = 0
    for fname in os.listdir(day_dir):
        if not fname.endswith("_comments.md"):
            continue
        src_path = os.path.join(day_dir, fname)
        if not os.path.isfile(src_path):
            continue
        bugid = fname.replace("_comments.md", "")
        conf = bugid_confidence.get(bugid, -1)
        if conf < 0:
            # 无执行记录，跳过
            skipped += 1
            continue
        passed = conf >= threshold
        target_dir = os.path.join(day_dir, "True" if passed else "False")
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, fname)
        try:
            shutil.move(src_path, target_path)
            if passed:
                moved_true += 1
            else:
                moved_false += 1
            logger.info("分类存储: %s -> %s (置信度=%.3f)", fname, "True" if passed else "False", conf)
        except Exception as e:
            logger.warning("分类存储失败: %s, %s", fname, e)
            skipped += 1

    result = {"moved_true": moved_true, "moved_false": moved_false, "skipped": skipped}
    logger.info("当天文档分类完成: %s", result)
    return result
