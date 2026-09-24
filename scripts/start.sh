#!/bin/bash
# 启动服务脚本：自动使用虚拟环境的 Python
cd "$(dirname "$0")/.." || exit 1
exec .venv/bin/python -m src.main web --port "${1:-8060}"
