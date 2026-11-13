"""全局配置加载与日志初始化模块"""
import json
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
# 可提交的公共配置（不含密钥），先加载它，再用本地 config.yaml 覆盖
CONFIG_CORE_PATH = os.path.join(PROJECT_ROOT, "config", "core_settings.json")
# 加密配置（仓库里只提交密文）
CONFIG_ENC_PATH = os.path.join(PROJECT_ROOT, "config", "config.enc")
CONFIG_KEY_PATH = os.path.join(PROJECT_ROOT, "config", "config.key")

# 全局配置缓存
_CONFIG = None


def _read_encrypted_yaml() -> dict:
    """用 config.key 或环境变量 D16_CONFIG_KEY 解密 config.enc。"""
    import base64
    from Crypto.Cipher import AES

    key_text = os.environ.get("D16_CONFIG_KEY", "").strip()
    if not key_text and os.path.exists(CONFIG_KEY_PATH):
        with open(CONFIG_KEY_PATH, "r", encoding="utf-8") as f:
            key_text = f.read().strip()
    if not key_text:
        raise RuntimeError("缺少配置密钥：请设置 D16_CONFIG_KEY 或放置 config/config.key")
    key = base64.b64decode(key_text)
    with open(CONFIG_ENC_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    cipher = AES.new(key, AES.MODE_GCM, nonce=base64.b64decode(payload["nonce"]))
    plain = cipher.decrypt_and_verify(
        base64.b64decode(payload["data"]), base64.b64decode(payload["tag"]))
    return yaml.safe_load(plain.decode("utf-8")) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并配置：override 覆盖 base，dict 逐层合并。"""
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val
    return base


def load_config(config_path: str = None) -> dict:
    """加载公共配置 + 本地 YAML，结果缓存供全局复用

    - config/core_settings.json：可提交的公共参数（并发、超时、开关等）；
    - config/config.yaml：本机密钥与本机覆盖，不提交。
    """
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
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            local_cfg = yaml.safe_load(f) or {}
    elif config_path is None and os.path.exists(CONFIG_ENC_PATH):
        local_cfg = _read_encrypted_yaml()
    else:
        raise FileNotFoundError(f"未找到配置文件：{path}")
    merged = {}
    if config_path is None and os.path.exists(CONFIG_CORE_PATH):
        try:
            with open(CONFIG_CORE_PATH, "r", encoding="utf-8") as f:
                merged = json.load(f) or {}
        except Exception:
            merged = {}
    # 加密配置叠加在公共配置之上、本机明文之下；密钥放 config.enc，
    # 本机 config.yaml 仍可覆盖非敏感项（并行数、模型路径等）。
    if config_path is None and os.path.exists(CONFIG_ENC_PATH):
        try:
            enc_cfg = _read_encrypted_yaml()
            merged = _deep_merge(merged, enc_cfg)
        except Exception as e:
            logging.getLogger(__name__).warning("读取加密配置失败，跳过: %s", e)
    _CONFIG = _deep_merge(merged, local_cfg)
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
    # 子 logger（含 "."）不添加自己的 handler，通过传播由父 logger 统一输出，避免日志重复
    if "." in name:
        return logger
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
