"""Web API 测试：使用 FastAPI TestClient 验证页面、配置读写与流程执行接口"""
import allure
import pytest
import yaml
from fastapi.testclient import TestClient

from src import config as cfg_module
from src.web import server


@pytest.fixture()
def client():
    """FastAPI 测试客户端"""
    return TestClient(server.app)


@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    """将配置文件重定向到临时路径，避免测试写坏真实 config.yaml"""
    path = tmp_path / "config.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg_module.load_config(), f, allow_unicode=True)
    monkeypatch.setattr(cfg_module, "CONFIG_PATH", str(path))
    return path


@allure.feature("Web 接口")
@allure.story("页面与概览")
def test_index_and_overview(client):
    """首页可访问，概览接口返回统计与 mock 状态"""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Bug 文档沉淀工具" in resp.text
    body = client.get("/api/overview").json()
    assert body["ok"] is True
    assert "mock" in body["data"]


@allure.feature("Web 接口")
@allure.story("配置读写")
def test_config_save_and_reload(client, temp_config):
    """保存配置写回文件并立即生效"""
    body = client.post("/api/config", json={"ai_log_api": {"timeout": 99}}).json()
    assert body["ok"] is True
    with open(temp_config, encoding="utf-8") as f:
        saved = yaml.safe_load(f)
    assert saved["ai_log_api"]["timeout"] == 99
    # 配置缓存已重载，GET 返回更新后的值
    got = client.get("/api/config").json()["data"]
    assert got["ai_log_api"]["timeout"] == 99


@allure.feature("Web 接口")
@allure.story("流程执行")
def test_analyze_api(client):
    """analyze 接口执行补充流程并返回当日报表，空输入被拒绝"""
    rows = [
        {"jira号": "WEB-1", "分析问题时间": "2026-08-14 10:00:00",
         "AI分析结果(飞书链接)": "", "AI评论总结": "", "rootcause": "", "结果置信度": ""},
        {"jira号": "WEB-2", "分析问题时间": "",
         "AI分析结果(飞书链接)": "", "AI评论总结": "", "rootcause": "", "结果置信度": ""},
        {"jira号": "WEB-1", "分析问题时间": "2026-08-14 10:00:00",
         "AI分析结果(飞书链接)": "", "AI评论总结": "", "rootcause": "", "结果置信度": ""},
    ]
    body = client.post("/api/analyze", json={"rows": rows}).json()
    assert body["ok"] is True
    # WEB-1 重复且字段不全，仍走补充流程
    jira_ids = [r["jira号"] for r in body["data"]["rows"]]
    assert "WEB-1" in jira_ids
    assert "WEB-2" in jira_ids
    # 空输入被拒绝
    assert client.post("/api/analyze", json={"rows": []}).json()["ok"] is False
    # 兼容旧格式 bugids
    body2 = client.post("/api/analyze", json={"bugids": "WEB-10"}).json()
    assert body2["ok"] is True


@allure.feature("Web 接口")
@allure.story("报表查询")
def test_report_api(client):
    """每日报表与抽查报表查询接口正常"""
    rows = [{"jira号": "WEB-10", "分析问题时间": "", "AI分析结果(飞书链接)": "",
             "AI评论总结": "", "rootcause": "", "结果置信度": ""}]
    client.post("/api/analyze", json={"rows": rows})
    daily = client.get("/api/report/daily").json()
    assert daily["ok"] is True
    assert len(daily["data"]) >= 1
    audit = client.get("/api/report/audit").json()
    audited = client.get("/api/report/audited").json()
    assert audit["ok"] is True
    assert audited["ok"] is True


@allure.feature("Web 接口")
@allure.story("功能测试接口")
def test_ai_analyze_api(client):
    """功能测试1：AI 分析生成文档，返回结论与步骤；空 bugid 被拒绝"""
    body = client.post("/api/test/ai_analyze",
                       json={"bugid": "BUG-5001", "trigger_time": "2026-08-10 09:15:00"}).json()
    assert body["ok"] is True
    assert body["data"]["doc_path"].endswith("BUG-5001.md")
    assert body["data"]["conclusion"]
    assert len(body["data"]["steps"]) == 4
    assert client.post("/api/test/ai_analyze", json={"bugid": ""}).json()["ok"] is False


@allure.feature("Web 接口")
@allure.story("功能测试接口")
def test_comment_compare_api(client):
    """功能测试2：评论提取与双重对比，一致样本判定通过"""
    body = client.post("/api/test/comment_compare", json={"bugid": "BUG-5001"}).json()
    assert body["ok"] is True
    data = body["data"]
    assert len(data["comments"]) == 5
    assert len(data["comment_steps"]) >= 3
    assert data["root_cause_ok"] is True
    assert data["comment_compare_ok"] is True
    assert data["all_ok"] is True


@allure.feature("Web 接口")
@allure.story("批量对比")
def test_batch_compare_api(client):
    """批量对比：分号分隔多个 bugid，返回汇总表格"""
    body = client.post("/api/test/batch_compare",
                       json={"bugids": "BUG-5001;BUG-5002"}).json()
    assert body["ok"] is True
    data = body["data"]
    assert data["total"] == 2
    assert len(data["results"]) == 2
    # 每个结果包含必要字段
    for r in data["results"]:
        assert "bugid" in r
        assert "root_cause_ok" in r
        assert "comment_compare_ok" in r
        assert "all_ok" in r
        assert "conclusion" in r
    # 空输入被拒绝
    assert client.post("/api/test/batch_compare", json={"bugids": ""}).json()["ok"] is False


@allure.feature("Web 接口")
@allure.story("文件上传")
def test_upload_bug_file_api(client, tmp_path):
    """上传 CSV 文件解析后返回 file_id，可用于后续批量对比"""
    import io
    csv_content = "bugid,根因分析,评论,问题触发时间\nBUG-U1,内存溢出,评论1|评论2,2026-08-10\n"
    resp = client.post("/api/test/upload_bug_file",
                       files={"file": ("test_bugs.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")})
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["file_id"]
    assert body["data"]["row_count"] == 1
    # 无文件上传时返回错误
    resp2 = client.post("/api/test/upload_bug_file")
    assert resp2.json()["ok"] is False
