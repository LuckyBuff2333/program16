"""Bug 单数据源测试：验证上传文件解析与 API 回退加载"""
import allure
import pytest

from src.clients import bug_source


@allure.feature("数据源")
@allure.story("文件解析")
def test_parse_csv_content():
    """CSV 文件内容解析为标准字段行列表"""
    content = b"bugid,\xe6\xa0\xb9\xe5\x9b\xa0\xe5\x88\x86\xe6\x9e\x90,\xe8\xaf\x84\xe8\xae\xba,\xe9\x97\xae\xe9\xa2\x98\xe8\xa7\xa6\xe5\x8f\x91\xe6\x97\xb6\xe9\x97\xb4\nBUG-001,\xe6\x95\xb0\xe6\x8d\xae\xe5\xba\x93\xe8\xbf\x9e\xe6\x8e\xa5\xe6\xb1\xa0\xe8\x80\x97\xe5\xb0\xbd,\xe8\xaf\x84\xe8\xae\xba1|\xe8\xaf\x84\xe8\xae\xba2,2026-08-10"
    rows = bug_source.parse_uploaded_file(content, "test.csv")
    assert len(rows) == 1
    assert rows[0]["bugid"] == "BUG-001"
    assert rows[0]["root_cause"] == "数据库连接池耗尽"
    assert rows[0]["comments"] == "评论1|评论2"
    assert rows[0]["trigger_time"] == "2026-08-10"


@allure.feature("数据源")
@allure.story("字段映射")
def test_match_field_aliases():
    """列名别名匹配：支持中英文及常见变体"""
    columns = ["bugid", "根因分析", "评论", "问题触发时间"]
    assert bug_source._match_field(columns, "bugid") == "bugid"
    assert bug_source._match_field(columns, "root_cause") == "根因分析"
    assert bug_source._match_field(columns, "comments") == "评论"
    assert bug_source._match_field(columns, "trigger_time") == "问题触发时间"
    # 不存在的字段返回空字符串
    assert bug_source._match_field(columns, "nonexistent") == ""


@allure.feature("数据源")
@allure.story("数据加载")
def test_load_from_uploaded_rows():
    """优先从上传数据中加载 bug 单信息"""
    uploaded = [
        {"bugid": "BUG-X1", "root_cause": "内存溢出", "comments": "评论A|评论B", "trigger_time": "2026-08-10"},
    ]
    result = bug_source.load_bug_data("BUG-X1", uploaded_rows=uploaded)
    assert result["bugid"] == "BUG-X1"
    assert result["root_cause"] == "内存溢出"
    assert result["comments"] == ["评论A", "评论B"]


@allure.feature("数据源")
@allure.story("根因清洗")
def test_clean_root_cause():
    """清洗 description 前缀提取纯根因"""
    assert bug_source._clean_root_cause("线上服务报错，原因：数据库连接池耗尽") == "数据库连接池耗尽"
    assert bug_source._clean_root_cause("线上服务报错，原因:OOM进程重启") == "OOM进程重启"
    assert bug_source._clean_root_cause("直接根因文本") == "直接根因文本"
    assert bug_source._clean_root_cause("") == ""


@allure.feature("数据源")
@allure.story("文件解析")
def test_parse_csv_missing_bugid_column():
    """CSV 缺少 bugid 列时返回空列表"""
    content = b"name,value\nfoo,bar\n"
    rows = bug_source.parse_uploaded_file(content, "test.csv")
    assert rows == []
