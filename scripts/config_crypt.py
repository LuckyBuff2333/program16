"""配置加解密工具：把本机 config.yaml 加密成可提交的 config/config.enc。

用法：
  python scripts/config_crypt.py genkey
  python scripts/config_crypt.py encrypt
  python scripts/config_crypt.py decrypt

密钥来源优先级：
  1. 环境变量 D16_CONFIG_KEY（base64 的 32 字节）
  2. config/config.key 文件（base64，一行）
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
PLAIN_PATH = os.path.join(CONFIG_DIR, "config.yaml")
ENC_PATH = os.path.join(CONFIG_DIR, "config.enc")
KEY_PATH = os.path.join(CONFIG_DIR, "config.key")
ENV_KEY = "D16_CONFIG_KEY"


def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.strip())


def load_key() -> bytes:
    env = os.environ.get(ENV_KEY, "").strip()
    if env:
        raw = _b64d(env)
    elif os.path.exists(KEY_PATH):
        with open(KEY_PATH, "r", encoding="utf-8") as f:
            raw = _b64d(f.read())
    else:
        raise SystemExit(f"未找到密钥：请设置 {ENV_KEY} 或先生成 config/config.key")
    if len(raw) != 32:
        raise SystemExit("密钥长度必须是 32 字节（base64 后 44 字符）")
    return raw


def genkey() -> None:
    if os.path.exists(KEY_PATH):
        raise SystemExit(f"密钥已存在：{KEY_PATH}（如要更换请先备份并删除）")
    key = get_random_bytes(32)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(KEY_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(_b64e(key))
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass
    print(f"已生成密钥：{KEY_PATH}")
    print(f"其他机器请把该文件放到同一路径，或设置环境变量 {ENV_KEY}={_b64e(key)}")


def encrypt() -> None:
    if not os.path.exists(PLAIN_PATH):
        raise SystemExit(f"未找到明文配置：{PLAIN_PATH}")
    key = load_key()
    with open(PLAIN_PATH, "rb") as f:
        plain = f.read()
    nonce = get_random_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    data, tag = cipher.encrypt_and_digest(plain)
    payload = {"v": 1, "alg": "AES-256-GCM", "nonce": _b64e(nonce), "tag": _b64e(tag), "data": _b64e(data)}
    with open(ENC_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"已加密：{ENC_PATH}")


def decrypt() -> None:
    if not os.path.exists(ENC_PATH):
        raise SystemExit(f"未找到密文：{ENC_PATH}")
    key = load_key()
    with open(ENC_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    cipher = AES.new(key, AES.MODE_GCM, nonce=_b64d(payload["nonce"]))
    plain = cipher.decrypt_and_verify(_b64d(payload["data"]), _b64d(payload["tag"]))
    with open(PLAIN_PATH, "wb") as f:
        f.write(plain)
    print(f"已解密：{PLAIN_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="config.yaml 加解密")
    parser.add_argument("action", choices=("genkey", "encrypt", "decrypt"))
    args = parser.parse_args()
    {"genkey": genkey, "encrypt": encrypt, "decrypt": decrypt}[args.action]()


if __name__ == "__main__":
    main()
