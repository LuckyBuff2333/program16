# -*- mode: python ; coding: utf-8 -*-
"""
Bug 文档沉淀工具 PyInstaller 打包配置
使用方法：pyinstaller bug-doc-tool.spec
"""

import os
import sys

block_cipher = None

# 获取项目根目录（spec 文件所在目录）
# 在 PyInstaller 中，SPECPATH 是 spec 文件所在的目录
project_root = os.path.abspath(SPECPATH)
print(f"项目根目录: {project_root}")

a = Analysis(
    [os.path.join(project_root, 'src', 'main.py')],
    pathex=[project_root],
    binaries=[
        # Python 3.13 需要 python3.dll（稳定 ABI）
        (os.path.join(os.path.dirname(sys.executable), 'python3.dll'), '.'),
    ],
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
        # 注意：不能排除 distutils/setuptools——PyInstaller 内置 hook 需为
        # distutils 建立 setuptools 别名，排除会导致 ValueError 打包崩溃；
        # wheel 与二者强耦合，一并保留避免误伤。
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
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
    strip=False,
    upx=True,
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
