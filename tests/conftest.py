"""测试公共夹具：sys.path 初始化、mock 模式、临时数据库与临时输出目录"""
import os
import sys

# 确保 src 包可被导入（conftest 加载先于 test 文件收集）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src import db
from src import config as cfg_module


# ── 全局 mock：在任何测试模块导入前生效 ──
@pytest.fixture(autouse=True, scope="session")
def _global_mock():
    """测试环境强制 mock 模式，避免真实网络请求（session 级，最先执行）"""
    cfg = cfg_module.load_config()
    cfg.setdefault("jira_api", {})["mock"] = True
    cfg.setdefault("ai_log_api", {})["mock"] = True
    cfg.setdefault("diana", {})["mock"] = True
    llm_cfg = cfg.get("llm_filter")
    if llm_cfg:
        llm_cfg["mock"] = True
    yield


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
