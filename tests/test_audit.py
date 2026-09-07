"""随机抽查复核模块测试：抽样、排除已抽查、对比审核表格生成"""
import os

import allure
import pandas as pd
import pytest
from sqlalchemy import text

from src import db
from src.clients.ai_log_client import _load_testdata_row, MOCK_DOC_STEPS
from src.config import get_path, load_config
from src.core import audit

# 抽查测试用的 bugid 列表，必须在 bug_test_data.csv 中存在
AUDIT_BUGIDS = ["BUG-5001", "BUG-5002", "BUG-5003", "BUG-5004", "BUG-5005"]


def _seed_kb_table(bugids: list):
    """创建 kb_analysis 表并从 bug_test_data.csv 中读取对应数据填充"""
    session = db._get_session()
    session.execute(text(
        "CREATE TABLE IF NOT EXISTS kb_analysis ("
        "bugid TEXT PRIMARY KEY, trigger_time TEXT, root_cause TEXT, analysis_process TEXT)"
    ))
    for bugid in bugids:
        row = _load_testdata_row(bugid)
        assert row is not None, f"{bugid} 在 bug_test_data.csv 中未找到"
        # 分析步骤与 mock 报告中的步骤保持一致，确保抽查对比同源
        detail_steps = MOCK_DOC_STEPS.get(bugid, [
            "按触发时间检索日志，发现告警前兆",
            "定位触发时间点附近的 ERROR 日志",
            f"结合异常堆栈与监控指标，确认根因：{row['根因分析']}",
        ])
        process_text = "\n".join(f"{i}. {s}" for i, s in enumerate(detail_steps, 1))
        session.execute(
            text("INSERT OR REPLACE INTO kb_analysis VALUES (:b, :t, :r, :p)"),
            {"b": bugid, "t": row["问题触发时间"],
             "r": row["根因分析"], "p": process_text},
        )
    session.commit()
    session.close()


def _read_csv(path: str) -> pd.DataFrame:
    """读取 CSV 表格，自动过滤批次分隔空行"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    if "bugid" in df.columns:
        df = df[df["bugid"].notna() & (df["bugid"].astype(str).str.strip() != "")]
    return df


@allure.feature("随机抽查复核")
@allure.story("抽样与审核表格")
def test_audit_generates_report():
    """抽样指定数量重新分析，生成含相似度对比的人工审核表格"""
    _seed_kb_table(AUDIT_BUGIDS)
    report_path = audit.sample_and_audit(count=5)

    assert os.path.exists(report_path)
    df = _read_csv(report_path)
    assert len(df) == 5
    # 新结果与已入库字段一致（mock 数据同源），相似度应接近 1
    assert (df["根因相似度"] >= 0.9).all()
    assert (df["流程相似度"] >= 0.7).all()
    # 人工审核结论列留空待人工填写
    assert df["人工审核结论"].isna().all()

    # 已抽查记录表格同步生成
    audited_path = os.path.join(get_path("report_dir"), load_config()["audit"]["audited_file"])
    assert len(_read_csv(audited_path)) == 5


@allure.feature("随机抽查复核")
@allure.story("排除已抽查")
def test_audit_excludes_audited_bugids():
    """下次抽查不再抽取已抽查过的 bugid，候选耗尽后报错"""
    _seed_kb_table(AUDIT_BUGIDS)
    audit.sample_and_audit(count=3)
    first_batch = audit.load_audited_bugids()
    assert len(first_batch) == 3

    # 第二批与第一批无交集，剩余 2 个全部抽出
    audit.sample_and_audit(count=3)
    all_audited = audit.load_audited_bugids()
    assert len(all_audited) == 5
    assert first_batch.issubset(all_audited)

    # 候选池耗尽，再次抽查报错
    with pytest.raises(ValueError):
        audit.sample_and_audit(count=3)


@allure.feature("随机抽查复核")
@allure.story("候选不足")
def test_audit_pool_smaller_than_count():
    """可用候选不足请求数量时抽查全部可用候选"""
    _seed_kb_table(["BUG-5001", "BUG-5002", "BUG-5003"])
    report_path = audit.sample_and_audit(count=30)
    df = _read_csv(report_path)
    assert len(df) == 3


@allure.feature("随机抽查复核")
@allure.story("空候选池")
def test_audit_empty_pool_raises():
    """库内无记录时抽查直接报错"""
    _seed_kb_table([])
    with pytest.raises(ValueError):
        audit.sample_and_audit(count=5)
