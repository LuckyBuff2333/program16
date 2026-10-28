"""测试公共夹具：sys.path 初始化、mock 模式、临时数据库与临时输出目录"""
import os
import sys

# 确保 src 包可被导入（conftest 加载先于 test 文件收集）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import io

from src import config as cfg_module

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config", "config.yaml")
# 模拟 CI：DSH_SIMULATE_NO_CONFIG=1 时按“无 config.yaml”运行，用于本地验证跳过逻辑
_SIMULATE_NO_CONFIG = os.environ.get("DSH_SIMULATE_NO_CONFIG") == "1"
CONFIG_AVAILABLE = os.path.exists(CONFIG_FILE) and not _SIMULATE_NO_CONFIG

# 依赖真实 config.yaml 的用例（CI 里没有该文件）自动跳过
requires_config = pytest.mark.skipif(
    not CONFIG_AVAILABLE,
    reason="缺少 config/config.yaml（CI 环境），跳过依赖真实配置的用例",
)

def _load_example_config():
    """CI/新环境无 config.yaml 时，使用仓库内的脱敏示例配置（避免污染真实配置）"""
    example = os.path.join(PROJECT_ROOT, "config", "config.example.yaml")
    import yaml
    with open(example, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # 兜底：数据库指向进程内临时库，避免 CI 里 sqlite 路径为空
    cfg.setdefault("database", {})["url"] = "sqlite:///:memory:"
    cfg["database"].setdefault("table_name", "ai_analysis")
    if not cfg["database"].get("table_name"):
        cfg["database"]["table_name"] = "ai_analysis"
    # 兜底：kb_analysis 表结构字段（示例配置里这些字段是空字符串，会拼出非法 SQL）
    audit = cfg.setdefault("audit", {})
    audit.update({"kb_table": "kb_analysis", "bugid_column": "bugid",
                  "trigger_time_column": "trigger_time",
                  "root_cause_column": "root_cause", "process_column": "process"})
    # 兜底：确保 mock 开关为真，CI 里不会误发真实请求
    for sec in ("jira_api", "ai_log_api", "diana", "prod_ai", "llm_filter"):
        if isinstance(cfg.get(sec), dict) and "mock" in cfg[sec]:
            cfg[sec]["mock"] = True
    return cfg


if not CONFIG_AVAILABLE:
    # 无配置文件时加载示例配置，保证 conftest 与测试可运行
    cfg_module._CONFIG = _load_example_config()


# db 模块在 import 时会读取配置（表名等），必须在配置就绪后再导入
from src import db


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
