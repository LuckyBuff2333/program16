"""测试公共夹具：每个测试使用独立的临时数据库与临时输出目录"""
import pytest

from src import db
from src import config as cfg_module


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """为每个测试初始化全新的临时数据库，避免用例间数据污染"""
    db_url = "sqlite:///" + str(tmp_path / "test.db").replace("\\", "/")
    db.init_db(db_url)
    yield


@pytest.fixture(autouse=True)
def isolated_output(tmp_path, monkeypatch):
    """将文档/报表/日志输出目录重定向到临时路径，避免用例共享真实目录

    报表为磁盘合并模式，若共用真实 reports 目录会把前序用例结果带入，
    故必须隔离输出目录以保证用例独立性。
    """
    out = tmp_path / "output"
    output_cfg = {
        "doc_dir": str(out / "docs"),
        "report_dir": str(out / "reports"),
        "log_dir": str(out / "logs"),
    }
    # get_path 内部用 os.path.join(PROJECT_ROOT, rel)，绝对路径会直接生效
    monkeypatch.setitem(cfg_module.load_config()["output"], "doc_dir", output_cfg["doc_dir"])
    monkeypatch.setitem(cfg_module.load_config()["output"], "report_dir", output_cfg["report_dir"])
    monkeypatch.setitem(cfg_module.load_config()["output"], "log_dir", output_cfg["log_dir"])
    yield


@pytest.fixture(autouse=True)
def llm_filter_mock(monkeypatch):
    """测试环境强制 LLM 过滤为 mock 模式，避免真实 API 调用与网络依赖"""
    llm_cfg = cfg_module.load_config().get("llm_filter")
    if llm_cfg:
        monkeypatch.setitem(llm_cfg, "mock", True)


@pytest.fixture(autouse=True)
def ai_log_api_mock(monkeypatch):
    """测试环境强制 AI 日志分析接口为 mock 模式，避免依赖本地模拟服务"""
    ai_cfg = cfg_module.load_config().get("ai_log_api")
    if ai_cfg:
        monkeypatch.setitem(ai_cfg, "mock", True)
