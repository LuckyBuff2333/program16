#!/bin/bash
# Bug 文档沉淀工具 - Ubuntu 打包脚本
# 使用方法: chmod +x scripts/build.sh && ./scripts/build.sh

set -e

echo "=========================================="
echo "  Bug 文档沉淀工具 - 智能打包脚本 (Linux)"
echo "=========================================="
echo ""

# 切换到项目根目录
cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

# 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "[FAIL] 未找到 python3，请先安装 Python 3.10+"
    exit 1
fi

# 检查 PyInstaller
if ! command -v pyinstaller &> /dev/null; then
    echo "[INFO] 未找到 pyinstaller，正在安装..."
    pip3 install pyinstaller
fi

# 检查并安装项目依赖
if [ -f "requirements.txt" ]; then
    echo "[INFO] 安装项目依赖..."
    pip3 install -r requirements.txt -q
fi

# 结束可能正在运行的旧进程
if pgrep -f "bug-doc-tool" > /dev/null 2>&1; then
    echo "[INFO] 检测到 bug-doc-tool 正在运行，正在结束进程..."
    pkill -f "bug-doc-tool" 2>/dev/null || true
    sleep 2
fi

# 清理旧的 build 目录
if [ -d "build" ]; then
    echo "[INFO] 清理旧的 build 目录..."
    rm -rf build 2>/dev/null || {
        echo "[WARN] build 目录清理失败，可能有文件被占用"
        echo "[INFO] 使用备用输出目录..."
        EXTRA_ARGS="--distpath dist2"
    }
fi

# 执行打包
echo "[INFO] 开始打包..."
pyinstaller bug-doc-tool.spec --noconfirm ${EXTRA_ARGS:-}

if [ $? -ne 0 ]; then
    echo ""
    echo "[FAIL] 打包失败，请检查错误信息"
    exit 1
fi

# 设置可执行权限
chmod +x dist/bug-doc-tool

echo ""
echo "[DONE] 打包完成！"
echo "[PATH] 输出: ${PROJECT_ROOT}/dist/bug-doc-tool"
echo "[SIZE] $(du -h dist/bug-doc-tool | cut -f1)"
echo ""
echo "运行方式: ./dist/bug-doc-tool"
