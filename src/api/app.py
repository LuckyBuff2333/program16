"""FastAPI 应用工厂：唯一的应用装配点

职责：
1. 创建 FastAPI 实例
2. 配置中间件（CORS）
3. 注册所有路由模块
4. 挂载前端构建产物
5. 注册 startup/shutdown 生命周期事件

server.py 只保留业务逻辑函数，不再创建 FastAPI 实例。
新增路由只需在此处 include_router 即可。
"""
import logging
import os
import signal
import tempfile
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import system as system_router
from src.api.routes import flow as flow_router
from src.api.routes import audit as audit_router
from src.api.routes import timestudy as timestudy_router
from src.api.routes import tuning as tuning_router
from src.api.routes import report as report_router
from src.api.routes import data as data_router
from src.api.routes import trigger as trigger_router
from src.api.routes import docs as docs_router
from src.api.routes import bitable as bitable_router
from src.api.routes import feishu as feishu_router
from src.api.routes import verify as verify_router
from src.api.routes import troubleshoot as troubleshoot_router
from src.api.routes import misc as misc_router
from src.api.routes import testing as testing_router
from src.config import setup_logger

_logger = setup_logger("app")


@asynccontextmanager
async def _lifespan(application: FastAPI):
    """应用生命周期管理：startup → yield → shutdown"""
    await _on_startup()
    yield
    await _on_shutdown()


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例（含生命周期事件）"""
    application = FastAPI(
        title="AI应用测评平台",
        docs_url="/api/docs",
        lifespan=_lifespan,
    )

    # ── CORS（开发模式下允许前端 Vite dev server 跨域） ──
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── 注册路由模块 ──
    _ROUTERS = [
        system_router, flow_router, audit_router, timestudy_router,
        tuning_router, report_router, data_router, trigger_router,
        docs_router, bitable_router, feishu_router, verify_router,
        troubleshoot_router, misc_router, testing_router,
    ]
    for r in _ROUTERS:
        application.include_router(r.router)

    # ── 挂载前端构建产物 ──
    misc_router.mount_frontend_assets(application)

    return application


async def _on_startup():
    """服务启动初始化：信号处理 + 飞书长连接 + 每日播报 + 打开浏览器"""
    from src.api.routes import shared as _shared

    # 重置中断标志
    _shared.interrupted = False
    _shared.prev_sigint = None
    try:
        _shared.prev_sigint = signal.signal(signal.SIGINT, _shared.handle_sigint)
    except (ValueError, OSError):
        pass  # 非主线程时忽略

    # 过滤 favicon access log
    class _AccessFilter(logging.Filter):
        def filter(self, record):
            return "favicon.ico" not in record.getMessage()

    logging.getLogger("uvicorn.access").addFilter(_AccessFilter())

    # 启动飞书机器人长连接客户端
    try:
        from src.clients import feishu_client
        from src.services.server_legacy import _feishu_ws_event_handler
        feishu_client.start_feishu_ws_client(_feishu_ws_event_handler)
    except Exception as e:
        _logger.warning("飞书长连接客户端启动失败（不影响主服务）: %s", e)

    # 初始化昨日播报调度器
    try:
        from src.services.server_legacy import _init_daily_scheduler
        _init_daily_scheduler()
    except Exception as e:
        _logger.warning("每日播报调度器初始化失败（不影响主服务）: %s", e)

    # 服务就绪后打开浏览器（仅首次，reload 时不重复打开）
    _open_url = os.environ.pop("_WEB_OPEN_URL", None)
    if _open_url:
        _flag = os.path.join(tempfile.gettempdir(), ".web_browser_opened")
        if not os.path.exists(_flag):
            import subprocess, sys

            def _open_browser(url: str):
                """跨平台打开浏览器，xdg-open 会在已有窗口中新建标签页"""
                if sys.platform == "win32":
                    subprocess.Popen(["cmd", "/c", "start", "", url])
                    return
                # xdg-open 通过桌面协议复用已有浏览器实例开新标签页
                subprocess.Popen(["xdg-open", url],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)

            threading.Timer(0.5, lambda: _open_browser(_open_url)).start()
            try:
                with open(_flag, "w") as f:
                    f.write("1")
            except Exception:
                pass


async def _on_shutdown():
    """服务关闭时：设置所有取消标志，让轮询线程快速退出"""
    from src.api.routes import shared as _shared

    for bugid in list(_shared.flow_cancel):
        _shared.flow_cancel[bugid] = True

    if _shared._DIAG_EXECUTOR is not None:
        _shared._DIAG_EXECUTOR.shutdown(wait=False)
        _shared._DIAG_EXECUTOR = None
        _logger.info("诊断线程池已关闭")

    _logger.info("服务关闭，已设置所有流程取消标志")


# ── uvicorn 入口：src.api.app:app ──
app = create_app()
