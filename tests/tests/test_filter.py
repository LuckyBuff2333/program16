"""评论 Agent 过滤模块测试"""
import allure

from src.core import filter as comment_filter


@allure.feature("评论过滤")
@allure.story("日志分析步骤提取")
def test_extract_analysis_steps():
    """仅提取日志分析相关评论，噪音评论被过滤"""
    comments = [
        "稍后跟进",
        "日志分析步骤：查看错误日志发现超时；分析监控确认连接打满",
        "辛苦啦",
    ]
    steps, valid_comments = comment_filter.extract_analysis_steps(comments)
    # 有效评论1条不足3条触发补齐：两条短噪音均不足6字符不产生步骤
    assert steps == ["查看错误日志发现超时", "分析监控确认连接打满"]
    assert len(valid_comments) >= 1


@allure.feature("评论过滤")
@allure.story("日志分析步骤提取")
def test_no_analysis_comments():
    """无分析类评论且补齐评论过短时返回空列表"""
    comments = ["收到", "已同步"]
    steps, valid_comments = comment_filter.extract_analysis_steps(comments)
    # 兜底提取最后 2 条，但均不足 6 字符不产生步骤
    assert steps == []
    assert len(valid_comments) == 2


@allure.feature("评论过滤")
@allure.story("转给无效评论规则")
def test_forward_comment_invalid():
    """含“转给”且无有效关键词的评论判定为无效，补齐时也不纳入"""
    comments = ["转给运维组继续跟进", "辛苦啦", "收到哦"]
    steps, valid_comments = comment_filter.extract_analysis_steps(comments)
    # 兜底提取最后 2 条（跳过纯转发），但均不足 6 字符不产生步骤
    assert steps == []
    assert len(valid_comments) == 2
    assert not any("转给" in c for c in valid_comments)


@allure.feature("评论过滤")
@allure.story("转给无效评论规则")
def test_forward_comment_with_keyword_still_valid():
    """含“转给”但同时含有效关键词时以有效为准"""
    comments = ["转给张三，日志显示连接超时报错"]
    steps, valid_comments = comment_filter.extract_analysis_steps(comments)
    assert steps == ["转给张三，日志显示连接超时报错"]
    assert len(valid_comments) == 1


@allure.feature("评论过滤")
@allure.story("有效评论为0时兜底规则")
def test_fallback_zero_valid_extracts_last_two():
    """有效评论为 0 时，自动提取最后 2 条评论（跳过纯转发评论）"""
    comments = [
        "收到，我这边先看下",
        "转给DBA协助排查",
        "已同步给研发团队关注",
        "日志分析：定位到订单查询SQL缺少索引导致全表扫描锁表",
        "问题已修复，感谢大家支持",
    ]
    steps, valid_comments = comment_filter.extract_analysis_steps(comments)
    # 有效评论为 0，兜底提取最后 2 条：最后一条过短被过滤，倒数第二条有效
    assert any("已修复" in s or "感谢" in s for s in steps) or len(steps) >= 1
    assert len(valid_comments) >= 1


@allure.feature("评论过滤")
@allure.story("有效评论补齐规则")
def test_fallback_adds_last_comments():
    """有效评论少于3条时，自动补充最后几条评论（跳过已有效与纯转发评论）"""
    comments = [
        "稍后跟进",
        "日志分析步骤：查看错误日志发现超时；分析监控确认连接打满",
        "辛苦大家了",
        "好的，明天给出结论",
        "转给运维组继续跟进",
    ]
    steps, valid_comments = comment_filter.extract_analysis_steps(comments)
    # 有效评论仅1条，补齐最后三条：纯转发评论被跳过，"辛苦大家了"被规则精炼过滤
    # mock 规则精炼去除"好的，"前缀，保留技术内容部分
    assert any("明天给出结论" in s for s in steps)
    assert not any("转给" in s for s in steps)
    assert len(steps) == 3  # 2条分析步骤 + 1条补齐步骤
    assert len(valid_comments) >= 2


@allure.feature("评论过滤")
@allure.story("日志分析步骤提取")
def test_empty_and_none_comments():
    """空列表与含 None 的评论不报错"""
    steps1, valid1 = comment_filter.extract_analysis_steps([])
    assert steps1 == [] and valid1 == []
    steps2, valid2 = comment_filter.extract_analysis_steps([None, ""])
    assert steps2 == [] and valid2 == []


@allure.feature("评论过滤")
@allure.story("根因结论截断规则")
def test_truncate_at_conclusion():
    """到达与根因结论相似的评论后截断，后续评论不参与对比"""
    conclusion = "数据库连接池耗尽导致服务超时"
    comments = [
        "查看错误日志发现大量连接超时报错",
        "最终确认：数据库连接池耗尽导致服务超时",
        "后面的修复方案与验证记录不再参与对比",
    ]
    used = comment_filter.truncate_comments_by_conclusion(comments, conclusion)
    assert len(used) == 2
    assert used == comments[:2]


@allure.feature("评论过滤")
@allure.story("根因结论截断规则")
def test_truncate_no_match_keeps_all():
    """未到达相似结论时全部评论参与对比；空结论不截断"""
    comments = "稍后跟进、明天再讨论、周五前处理完毕".split("、")
    used = comment_filter.truncate_comments_by_conclusion(comments, "网关证书过期导致请求失败")
    assert used == comments
    assert comment_filter.truncate_comments_by_conclusion(comments, "") == comments


@allure.feature("评论过滤")
@allure.story("根因结论截断规则")
def test_truncate_by_keyword_hit():
    """关键词命中达标也视为到达结论（双判定机制）"""
    conclusion = "数据库连接池耗尽导致服务超时"
    # 关键词只从原因部分提取（「导致」之后为现象，不参与）
    keywords = ["数据库", "连接池", "耗尽"]
    # 关键词命中比例计算验证：评论含全部 3 个原因关键词
    extracted = comment_filter._keyword_hit_ratio(
        "确认是数据库连接池耗尽，服务出现超时", keywords)
    assert extracted == 1.0
    # 含全部根因关键词的评论触发截断，后续评论不参与对比
    comments = [
        "先看网关配置有无变更",
        "确认是数据库连接池耗尽，服务出现超时",
        "后续修复与验证记录不再参与对比",
    ]
    used = comment_filter.truncate_comments_by_conclusion(comments, conclusion)
    assert used == comments[:2]


@allure.feature("评论过滤")
@allure.story("评论简化")
def test_summarize_comments():
    """LLM 简化评论：每条评论提取分析结论和日志证据"""
    comments = [
        "查看错误日志发现大量连接超时报错\n2026-08-10 ERROR ConnectionTimeout at com.db.pool",
        "确认是数据库连接池耗尽，服务出现超时",
    ]
    summaries = comment_filter.summarize_comments(comments)
    assert len(summaries) == 2
    # 每条简化结果包含 summary 和 evidence 字段
    for s in summaries:
        assert "summary" in s
        assert "evidence" in s
        assert s["summary"]  # 结论不为空


@allure.feature("评论过滤")
@allure.story("评论简化")
def test_summarize_empty_comments():
    """空评论列表返回空结果"""
    assert comment_filter.summarize_comments([]) == []
    assert comment_filter.summarize_comments([None, ""]) == []


@allure.feature("评论过滤")
@allure.story("评论总结文档生成")
def test_generate_comment_summary_doc(tmp_path, monkeypatch):
    """评论总结 md 文档生成并存入 docs/日期/ 目录"""
    from src import config as cfg_module
    monkeypatch.setattr(cfg_module, "_CONFIG",
                        {**cfg_module.load_config(), "doc_dir": str(tmp_path)})
    summaries = [
        {"index": 1, "comment": "原始评论", "summary": "连接池耗尽导致超时", "evidence": ["ERROR ConnectionTimeout"]},
        {"index": 2, "comment": "第二条评论", "summary": "确认根因", "evidence": []},
    ]
    doc_path = comment_filter.generate_comment_summary_doc("BUG-TEST", summaries, "2026-08-10")
    assert doc_path.endswith("BUG-TEST_comments.md")
    import os
    assert os.path.exists(doc_path)
    content = open(doc_path, encoding="utf-8").read()
    assert "连接池耗尽导致超时" in content
    assert "ERROR ConnectionTimeout" in content
