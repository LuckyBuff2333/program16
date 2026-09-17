# -*- mode: python ; coding: utf-8 -*-
"""
Bug 文档沉淀工具 PyInstaller 打包配置（跨平台：Windows / Ubuntu）
使用方法：pyinstaller bug-doc-tool.spec
"""

import os
import sys
import sysconfig

block_cipher = None
is_windows = sys.platform == 'win32'

# 获取项目根目录（spec 文件所在目录）
project_root = os.path.abspath(SPECPATH)
print(f"项目根目录: {project_root}")
print(f"目标平台: {'Windows' if is_windows else 'Linux'}")

# —— 平台专属二进制文件 ——
platform_binaries = []
if is_windows:
    # Windows: Python 3.13 需要 python3.dll（稳定 ABI）
    dll_path = os.path.join(os.path.dirname(sys.executable), 'python3.dll')
    if os.path.exists(dll_path):
        platform_binaries.append((dll_path, '.'))

a = Analysis(
    [os.path.join(project_root, 'src', 'main.py')],
    pathex=[project_root],
    binaries=platform_binaries,
    datas=[
        # 前端文件
        (os.path.join('src', 'web', 'index.html'), os.path.join('src', 'web')),
        (os.path.join('src', 'web', 'static'), os.path.join('src', 'web', 'static')),
        # 配置文件
        (os.path.join('config', 'config.yaml'), 'config'),
        # 测试数据
        (os.path.join('testdata', 'bug_test_data.csv'), 'testdata'),
        # 模型文件
        (os.path.join('tools', 'models'), os.path.join('tools', 'models')),
    ],
    hiddenimports=[
        'src',
        'src.config',
        'src.db',
        'src.pipeline',
        'src.clients',
        'src.clients.ai_log_client',
        'src.clients.base',
        'src.clients.bug_source',
        'src.clients.diana_client',
        'src.clients.feishu_client',
        'src.clients.jira_client',
        'src.clients.kb_client',
        'src.core',
        'src.core.audit',
        'src.core.doc_generator',
        'src.core.filter',
        'src.core.report',
        'src.core.semantic',
        'src.core.similarity',
        'src.web',
        'src.web.server',
        'fastapi',
        'fastapi.responses',
        'fastapi.staticfiles',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'sqlalchemy',
        'httpx',
        'httpx._transports',
        'httpx._transports.default',
        'urllib3',  # httpx 底层依赖
        'tenacity',
        'pandas',
        'sklearn',
        'jieba',
        'yaml',
        'starlette',
        'starlette.middleware',
        'starlette.responses',
        'starlette.routing',
        'starlette.staticfiles',
        'anyio',
        'anyio._backends',
        'anyio._backends._asyncio',
        'pydantic',
        # 7z/rar 解压
        'py7zr',
        # 图片处理与 OCR
        'cv2',
        'easyocr',
        'numpy',  # easyocr/cv2 依赖
        # 飞书机器人 SDK
        'lark_oapi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'torchvision', 'torchaudio',
        'tensorflow', 'tensorflow_intel', 'keras',
        'transformers', 'tokenizers',
        'onnxruntime',
        'matplotlib', 'plotly',
        'IPython', 'jupyter', 'notebook',
        'pyarrow', 'PIL',
        'pytest', 'allure_pytest',
        # 排除未使用的数据库驱动（项目使用 sqlite3 标准库）
        'pysqlite2', 'MySQLdb', 'psycopg2',
        # 排除已废弃/动态生成的模块（消除打包警告）
        'pycparser.lextab', 'pycparser.yacctab',
        'importlib_resources.trees',
        'scipy.special._cdflib',
        # 注意：不能排除 distutils/setuptools——PyInstaller 内置 hook 需为
        # distutils 建立 setuptools 别名，排除会导致 ValueError 打包崩溃；
        # wheel 与二者强耦合，一并保留避免误伤。
    ],
    # win_* 参数仅 Windows 生效，Linux 下自动忽略
    **({'win_no_prefer_redirects': False, 'win_private_assemblies': False} if is_windows else {}),
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='bug-doc-tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=not is_windows,  # Linux 下 strip 可减小体积
    upx=False,  # 禁用UPX，避免压缩大文件导致zip header损坏闪退
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 控制台应用，显示日志输出
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
