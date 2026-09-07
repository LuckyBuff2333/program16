"""相似性比对模块测试：验证高低相似度样本与阈值判定"""
import allure

from src.core import similarity


@allure.feature("相似性比对")
@allure.story("文本余弦相似度")
def test_cosine_identical_texts():
    """完全相同的文本相似度为 1"""
    text = "数据库连接池耗尽导致服务超时"
    assert similarity.cosine_of_texts(text, text) > 0.99


@allure.feature("相似性比对")
@allure.story("文本余弦相似度")
def test_cosine_different_texts():
    """完全不相关的文本相似度较低"""
    score = similarity.cosine_of_texts(
        "数据库连接池耗尽导致服务超时",
        "前端页面按钮样式错位需要调整颜色",
    )
    assert score < 0.3


@allure.feature("相似性比对")
@allure.story("步骤比对")
def test_compare_steps_high_similarity():
    """相同步骤集合的平均相似度高于阈值"""
    steps = ["查看服务错误日志发现连接超时", "分析连接池监控确认连接数打满"]
    score = similarity.compare_steps(steps, list(steps))
    assert score >= 0.7


@allure.feature("相似性比对")
@allure.story("步骤比对")
def test_compare_steps_low_similarity():
    """完全不同的步骤集合相似度低于阈值"""
    doc_steps = ["查看服务错误日志发现连接超时", "分析连接池监控确认连接数打满"]
    comment_steps = ["修改前端按钮颜色", "调整页面布局样式"]
    score = similarity.compare_steps(doc_steps, comment_steps)
    assert score < 0.7


@allure.feature("相似性比对")
@allure.story("步骤比对")
def test_compare_steps_empty_input():
    """空输入返回 0 分不报错"""
    assert similarity.compare_steps([], ["任意步骤"]) == 0.0
    assert similarity.compare_steps(["任意步骤"], []) == 0.0


@allure.feature("相似性比对")
@allure.story("根因关键词提取")
def test_extract_cause_text():
    """从根因结论中只取原因部分，去掉导致之后的现象"""
    assert similarity._extract_cause_text("数据库连接池耗尽导致服务超时") == "数据库连接池耗尽"
    assert similarity._extract_cause_text("Redis集群节点宕机引发缓存雪崩") == "Redis集群节点宕机"
    assert similarity._extract_cause_text("SSL证书过期造成HTTPS握手失败") == "SSL证书过期"
    # 无因果连接词时返回全文
    assert similarity._extract_cause_text("内存溢出") == "内存溢出"


@allure.feature("相似性比对")
@allure.story("根因关键词提取")
def test_extract_cause_keywords():
    """关键词只从原因部分提取，现象部分不参与"""
    kw = similarity.extract_cause_keywords("数据库连接池耗尽导致服务超时")
    assert "数据库" in kw
    assert "连接池" in kw
    assert "耗尽" in kw
    # 现象部分「服务」「超时」不应出现在关键词中
    assert "服务" not in kw
    assert "超时" not in kw


@allure.feature("相似性比对")
@allure.story("根因比对")
def test_compare_root_cause_hit():
    """报错原因关键词全部出现在文档中时命中比例为 1"""
    ratio, hits = similarity.compare_root_cause(
        "连接池耗尽", "分析结论：连接池耗尽导致超时"
    )
    assert ratio == 1.0
    assert len(hits) > 0


@allure.feature("相似性比对")
@allure.story("阈值判定")
def test_judge_result():
    """按配置阈值判定一致/不一致"""
    cause_ok, step_ok = similarity.judge_result(0.9, 0.8)
    assert cause_ok and step_ok
    cause_ok, step_ok = similarity.judge_result(0.1, 0.2)
    assert not cause_ok and not step_ok
