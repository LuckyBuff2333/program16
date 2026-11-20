#!/bin/bash
# 启动服务脚本：自动使用虚拟环境的 Python
cd "$(dirname "$0")/.." || exit 1

# 将 venv 中 nvidia CUDA 12 库目录加入 LD_LIBRARY_PATH，
# 使 ONNX Runtime 能加载 libcublasLt.so.12 / libcudnn.so.9
# 动态链接器不支持中文路径，需用符号链接到纯 ASCII 路径
NVIDIA_DIR="$(pwd)/.venv/lib/python3.10/site-packages/nvidia"
if [ -d "$NVIDIA_DIR" ]; then
    LINK_DIR="/tmp/nvidia_libs_$(echo "$(pwd)" | md5sum | cut -c1-8)"
    ln -snf "$NVIDIA_DIR" "$LINK_DIR" 2>/dev/null
    EXTRA=""
    for d in "$LINK_DIR"/*/lib; do
        [ -d "$d" ] && EXTRA="$EXTRA:$d"
    done
    if [ -n "$EXTRA" ]; then
        export LD_LIBRARY_PATH="${EXTRA#:}:${LD_LIBRARY_PATH}"
    fi
fi

exec .venv/bin/python -m src.main web --port "${1:-8060}"
