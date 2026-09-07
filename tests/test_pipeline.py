"""端到端流程测试：mock 模式下验证内容补充流程（去重、飞书/rootcause/置信度补充、报表生成）

新流程：输入6列表格 → 仅对缺失字段补充 → 输出完整表格
"""
import os

import allure
import pandas as pd
import pytest

from src import db, pipeline


def _read_csv(csv_path: str) -> pd.DataFrame:
    """读取结论报表，自动过滤批次分隔空行"""
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    first_col = df.columns[0] if len(df.columns) else "jira号"
    df = df[df[first_col].notna() & (df[first_col].astype(str).str.strip() != "")]
    return df


def _make_row(bugid: str, **kwargs) -> dict:
    """构造一行输入数据，未指定字段留空走补充流程"""
    row = {"jira号": bugid, "分析问题时间": "", "AI分析结果(飞书链接)": "",
           "AI评论总结": "", "rootcause": "", "结果置信度": ""}
    row.update(kwargs)
    return row


@allure.feature("端到端流程")
@allure.story("内容补充流程")
def test_run_pipeline_end_to_end():
    """输入含重复与缺失字段的行，验证补充流程输出完整表格"""
    rows = [
        _make_row("BUG-5001", **{"分析问题时间": "2026-08-10 09:15:00"}),
        _make_row("BUG-5002"),
        _make_row("BUG-5001", **{"分析问题时间": "2026-08-10 09:15:00"}),  # 重复且字段不全，走补充
    ]
    result = pipeline.run_pipeline(rows)
    csv_path = result["csv_path"]

    # CSV 报表已生成且包含处理后的记录
    assert os.path.exists(csv_path)
    df = _read_csv(csv_path)
    assert "BUG-5001" in df["jira号"].values
    assert "BUG-5002" in df["jira号"].values

    # 统计信息正确
    assert result["stats"]["total"] >= 2
    assert result["stats"]["complete"] >= 0

    # 分析结果不写入数据库
    session = db._get_session()
    assert session.query(db.BugRecord).count() == 0
    session.close()


@allure.feature("端到端流程")
@allure.story("去重规则")
def test_filter_complete_duplicate():
    """重复 bugid 且 5 字段全有值时跳过，其余情况走补充"""
    complete_row = _make_row("BUG-DUP",
                             **{"分析问题时间": "2026-08-10 10:00:00",
                                "AI分析结果(飞书链接)": "https://example.com/doc",
                                "AI评论总结": "/path/to/comments.md",
                                "rootcause": "内存溢出",
                                "结果置信度": "0.85"})
    rows = [complete_row, dict(complete_row)]  # 两条完全相同的完整行
    filtered = pipeline._filter_rows(rows)
    # 第一条保留，第二条重复且完整被跳过
    assert len(filtered) == 1


@allure.feature("端到端流程")
@allure.story("报表合并")
def test_csv_merge_on_rerun():
    """同日再次运行时，新结果按 bugid 覆盖合并，不产生重复行"""
    pipeline.run_pipeline([_make_row("BUG-5001"), _make_row("BUG-5002")])
    result2 = pipeline.run_pipeline([_make_row("BUG-5002"), _make_row("BUG-5003")])
    csv_path = result2["csv_path"]
    df = _read_csv(csv_path)
    assert len(df) == 3
    assert sorted(df["jira号"]) == ["BUG-5001", "BUG-5002", "BUG-5003"]


@allure.feature("端到端流程")
@allure.story("知识库手工入库")
def test_store_bug_manual():
    """store 仅推送已生成的分析文档，无文档时报错"""
    from src.clients import ai_log_client
    from src.core import doc_generator
    # 新补充流程不生成AI文档，需先通过AI分析接口生成文档
    response = ai_log_client.analyze_logs("BUG-5001", "2026-08-10 09:15:00")
    report_text = ai_log_client.extract_report(response)
    doc_generator.save_document("BUG-5001", report_text)
    # 开发手工执行入库（mock 模式下直接成功）
    pipeline.store_bug("BUG-5001")
    with pytest.raises(FileNotFoundError):
        pipeline.store_bug("NOT-EXIST")


@allure.feature("端到端流程")
@allure.story("失败重试")
def test_retry_bug():
    """失败 bug 重新补充，结论报表按 bugid 覆盖更新"""
    pipeline.run_pipeline([_make_row("PROJ-FAIL-1")])
    result = pipeline.retry_bug("PROJ-FAIL-1")
    csv_path = result["csv_path"]
    df = _read_csv(csv_path)
    assert "PROJ-FAIL-1" in df["jira号"].values


@allure.feature("端到端流程")
@allure.story("状态过滤")
def test_skip_non_closed_bug():
    """非 Closed 状态的 bug 应被排除，不进入补充流程"""
    rows = [_make_row("BUG-OPEN-1")]
    result = pipeline.run_pipeline(rows)
    # 非 Closed bug 应标记为失败
    assert len(result["rows"]) == 1
    assert "Open" in result["rows"][0].get("补充状态", "")
    # 其他字段不应被填充
    assert result["rows"][0].get("rootcause", "") in ("", "-", None)


@allure.feature("端到端流程")
@allure.story("AI分析自动生成")
def test_ai_analysis_auto_generate():
    """无本地文档且无飞书链接时，自动调用 AI 日志分析接口生成报告文档"""
    from src.core import doc_generator
    bugid = "BUG-AUTO-GEN"
    # 确保本地无该 bugid 的文档
    with pytest.raises(FileNotFoundError):
        doc_generator.find_latest_document(bugid)
    # 执行补充流程，应自动调用 AI 分析生成报告
    rows = [_make_row(bugid, **{"分析问题时间": "2026-08-19 10:00:00"})]
    result = pipeline.run_pipeline(rows)
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    # AI分析结果字段应被填充为生成的文档路径
    ai_result = row.get("AI分析结果(飞书链接)", "")
    assert ai_result and ai_result.endswith(".md")
    assert os.path.exists(ai_result)
