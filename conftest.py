# 项目根目录 conftest：确保 src 包可被导入，测试环境强制 mock 模式
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 测试环境强制开启 Jira mock 和 AI 日志分析 mock 模式，避免真实网络请求
# 直接修改全局缓存 _CONFIG，所有已 import load_config 的模块均会生效
from src.config import load_config
_cfg = load_config()
_cfg.setdefault("jira_api", {})["mock"] = True
_cfg.setdefault("ai_log_api", {})["mock"] = True
_cfg.setdefault("diana", {})["mock"] = True
