"""全局配置加载与日志初始化模块"""
import logging
import os
import sys
from datetime import datetime

import yaml

# 项目根目录（src 的上一级）
if getattr(sys, 'frozen', False):
    # 打包后：exe 所在目录为项目根（配置和输出写入此处）
    PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 默认配置文件路径
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "config.yaml")

# 全局配置缓存
_CONFIG = None


def load_config(config_path: str = None) -> dict:
    """加载 YAML 配置文件，结果缓存供全局复用"""
    global _CONFIG
    if _CONFIG is not None and config_path is None:
        return _CONFIG
    path = config_path or CONFIG_PATH
    # 打包后首次运行：exe 目录下无 config.yaml 时从内置资源复制
    if not os.path.exists(path) and getattr(sys, 'frozen', False):
        bundled = os.path.join(sys._MEIPASS, "config", "config.yaml")
        if os.path.exists(bundled):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            import shutil
            shutil.copy2(bundled, path)
    with open(path, "r", encoding="utf-8") as f:
        _CONFIG = yaml.safe_load(f)
    return _CONFIG


def get_path(key: str) -> str:
    """获取输出目录的绝对路径并确保目录存在"""
    cfg = load_config()
    rel = cfg["output"][key]
    abs_path = os.path.join(PROJECT_ROOT, rel)
    os.makedirs(abs_path, exist_ok=True)
    return abs_path


def get_day_dir(key: str = "doc_dir", date_str: str = None, subdir: str = "") -> str:
    """获取日期子目录路径并确保目录存在

    :param key: 配置中的输出目录键（doc_dir / report_dir）
    :param date_str: 日期字符串，默认当天
    :param subdir: 额外子目录名（如 spotcheck）
    :return: 日期目录绝对路径
    """
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    parts = [get_path(key)]
    if subdir:
        parts.append(subdir)
    parts.append(date_str)
    day_dir = os.path.join(*parts)
    os.makedirs(day_dir, exist_ok=True)
    return day_dir


def setup_logger(name: str = "bug_doc_tool") -> logging.Logger:
    """初始化日志：控制台 + 按日期归档的文件日志"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    )
    # 控制台输出
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    # 文件输出：logs/app_YYYY-MM-DD.log
    log_dir = get_path("log_dir")
    file_handler = logging.FileHandler(
        os.path.join(log_dir, f"app_{datetime.now().strftime('%Y-%m-%d')}.log"),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger
