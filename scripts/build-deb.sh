#!/bin/bash
# Bug 文档沉淀工具 - .deb 打包构建脚本
# 使用方法: chmod +x scripts/build-deb.sh && ./scripts/build-deb.sh
#
# 前置条件:
#   1. Ubuntu 20.04+ / Debian 11+
#   2. Python 3.12+ 已安装
#   3. dpkg-deb 可用（Debian/Ubuntu 自带）
#   4. 系统依赖: sudo apt install python3-dev libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 p7zip-full

set -e

echo "=========================================="
echo "  Bug 文档沉淀工具 - .deb 打包脚本"
echo "=========================================="
echo ""

# 切换到项目根目录
cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)
VERSION=$(grep '^Version:' debian/DEBIAN/control | awk '{print $2}')
PKG_NAME="bug-doc-tool_${VERSION}_amd64"
STAGING_DIR="${PROJECT_ROOT}/build/deb-staging"

echo "[INFO] 项目根目录: ${PROJECT_ROOT}"
echo "[INFO] 版本号: ${VERSION}"
echo "[INFO] 目标: ${PKG_NAME}.deb"
echo ""

# ---- 检查环境 ----
check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo "[FAIL] 未找到 $1，请先安装: $2"
        exit 1
    fi
}

check_command python3 "sudo apt install python3 python3-dev"
check_command pip3 "sudo apt install python3-pip"
check_command dpkg-deb "dpkg-deb 是 Debian/Ubuntu 系统自带工具"

# 检查 Python 版本
PYTHON_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VER" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VER" | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 12 ]); then
    echo "[FAIL] 需要 Python 3.12+，当前: ${PYTHON_VER}"
    exit 1
fi
echo "[OK] Python ${PYTHON_VER}"

# 检查系统依赖
echo ""
echo "[INFO] 检查系统依赖..."
MISSING_DEPS=""
for pkg in libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 p7zip; do
    if ! dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
        # 尝试替代包名
        ALT_PKG=""
        case "$pkg" in
            libgl1) ALT_PKG="libgl1-mesa-glx" ;;
        esac
        if [ -n "$ALT_PKG" ] && dpkg -l "$ALT_PKG" 2>/dev/null | grep -q "^ii"; then
            echo "  [OK] ${pkg} (${ALT_PKG})"
        else
            MISSING_DEPS="${MISSING_DEPS} ${pkg}"
            echo "  [MISS] ${pkg}"
        fi
    else
        echo "  [OK] ${pkg}"
    fi
done

if [ -n "$MISSING_DEPS" ]; then
    echo ""
    echo "[WARN] 缺少系统依赖，尝试安装..."
    echo "  sudo apt install${MISSING_DEPS}"
    sudo apt install -y ${MISSING_DEPS} 2>/dev/null || {
        echo "[FAIL] 系统依赖安装失败，请手动安装后重试"
        exit 1
    }
fi

# ---- 安装 Python 依赖 ----
echo ""
echo "[INFO] 安装 Python 依赖..."
if ! command -v pyinstaller &> /dev/null; then
    pip3 install pyinstaller -q
fi
pip3 install -r requirements.txt -q

# ---- 停止旧进程 ----
if pgrep -f "bug-doc-tool" > /dev/null 2>&1; then
    echo "[INFO] 检测到 bug-doc-tool 正在运行，正在结束..."
    pkill -f "bug-doc-tool" 2>/dev/null || true
    sleep 2
fi

# ---- PyInstaller 打包 ----
echo ""
echo "[INFO] 开始 PyInstaller 打包..."
rm -rf build/bug-doc-tool 2>/dev/null || true
pyinstaller bug-doc-tool.spec --noconfirm

if [ $? -ne 0 ]; then
    echo "[FAIL] PyInstaller 打包失败"
    exit 1
fi
echo "[OK] PyInstaller 打包完成"

# ---- 组装 deb 目录 ----
echo ""
echo "[INFO] 组装 .deb 包..."
rm -rf "${STAGING_DIR}"
mkdir -p "${STAGING_DIR}"

# 复制 DEBIAN 控制文件
cp -r debian/DEBIAN "${STAGING_DIR}/"
chmod 755 "${STAGING_DIR}/DEBIAN/postinst"
chmod 755 "${STAGING_DIR}/DEBIAN/prerm"

# 复制启动器到 /usr/bin
mkdir -p "${STAGING_DIR}/usr/bin"
cp debian/usr/bin/bug-doc-tool "${STAGING_DIR}/usr/bin/"
chmod 755 "${STAGING_DIR}/usr/bin/bug-doc-tool"

# 复制 PyInstaller 产物到 /usr/lib/bug-doc-tool
LIB_DIR="${STAGING_DIR}/usr/lib/bug-doc-tool"
mkdir -p "${LIB_DIR}"
cp "dist/bug-doc-tool" "${LIB_DIR}/"
chmod 755 "${LIB_DIR}/bug-doc-tool"

# 复制配置和数据目录
if [ -d "config" ]; then
    cp -r config "${LIB_DIR}/"
fi
if [ -d "data" ]; then
    cp -r data "${LIB_DIR}/"
fi
if [ -d "testdata" ]; then
    cp -r testdata "${LIB_DIR}/"
fi
if [ -d "tools/models" ]; then
    mkdir -p "${LIB_DIR}/tools"
    cp -r tools/models "${LIB_DIR}/tools/"
fi
# 复制前端文件
mkdir -p "${LIB_DIR}/src/web"
cp src/web/index.html "${LIB_DIR}/src/web/" 2>/dev/null || true
if [ -d "src/web/static" ]; then
    cp -r src/web/static "${LIB_DIR}/src/web/"
fi

# ---- 构建 deb ----
echo ""
echo "[INFO] 构建 .deb 包..."
OUTPUT_DIR="${PROJECT_ROOT}/dist"
mkdir -p "${OUTPUT_DIR}"
dpkg-deb --build --root-owner-group "${STAGING_DIR}" "${OUTPUT_DIR}/${PKG_NAME}.deb"

# ---- 清理 ----
rm -rf "${STAGING_DIR}"

# ---- 结果 ----
DEB_SIZE=$(du -h "${OUTPUT_DIR}/${PKG_NAME}.deb" | cut -f1)
echo ""
echo "=========================================="
echo "  .deb 打包完成！"
echo "=========================================="
echo ""
echo "[FILE] ${OUTPUT_DIR}/${PKG_NAME}.deb"
echo "[SIZE] ${DEB_SIZE}"
echo ""
echo "安装命令:"
echo "  sudo dpkg -i ${PKG_NAME}.deb"
echo "  sudo apt install -f  # 自动修复依赖"
echo ""
echo "卸载命令:"
echo "  sudo apt remove bug-doc-tool"
echo ""
