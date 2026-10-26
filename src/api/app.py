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
        docs_router, bitable_router, feishu_router,
        troubleshoot_router, misc_router, testing_router,
    ]
    for r in _ROUTERS:
        application.include_router(r.router)
    # 作业注册表（可选模块，缺失时不影响主流程）
    try:
        from src.api.routes import jobs as _jobs_module
        application.include_router(_jobs_module.router)
    except Exception as _e:  # noqa: BLE001
        logger.warning("作业状态路由注册失败: %s", _e)

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
        from src.config import PROJECT_ROOT as _PROJECT_ROOT
        _flag = os.path.join(_PROJECT_ROOT, "data", ".web_browser_opened")
        if not os.path.exists(_flag):
            import subprocess
            import sys

            def _default_browser_hint() -> str:
                """从注册表读取系统默认浏览器（返回 msedge/chrome/firefox 或空串）"""
                try:
                    import winreg
                    key_path = (r"Software\Microsoft\Windows\Shell\Associations"
                                r"\UrlAssociations\http\UserChoice")
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
                        prog_id = str(winreg.QueryValueEx(k, "ProgId")[0] or "").lower()
                    for name in ("edge", "chrome", "firefox"):
                        if name in prog_id:
                            return {"edge": "msedge"}.get(name, name)
                except Exception:
                    pass
                return ""

            def _configured_browser() -> str:
                """读取 config.web.browser（auto/chrome/edge/firefox/system），默认 auto"""
                try:
                    from src.config import load_config
                    mode = str((load_config().get("web") or {}).get("browser", "auto")).strip().lower()
                except Exception:
                    return "auto"
                return {"edge": "msedge", "msedge": "msedge"}.get(mode, mode)

            def _find_browser_exe():
                """查找浏览器可执行文件：优先 config.web.browser，其次系统默认，最后 Chrome/Edge 兜底"""
                roots = [
                    os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                    os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                    os.environ.get("LOCALAPPDATA", ""),
                ]
                rels = {
                    "msedge": r"Microsoft\Edge\Application\msedge.exe",
                    "chrome": r"Google\Chrome\Application\chrome.exe",
                    "firefox": r"Mozilla Firefox\firefox.exe",
                }
                found = {}
                for name, rel in rels.items():
                    for root in roots:
                        if not root:
                            continue
                        path = os.path.join(root, rel)
                        if os.path.isfile(path):
                            found[name] = path
                            break
                if not found:
                    return "", ""
                mode = _configured_browser()
                if mode == "system":          # 显式要求交给系统关联
                    return "", ""
                if mode in found:             # 配置里指定的浏览器
                    return found[mode], mode
                hint = _default_browser_hint()
                if hint in found:             # 系统默认浏览器
                    return found[hint], hint
                for name in ("chrome", "msedge", "firefox"):
                    if name in found:
                        return found[name], name
                return "", ""

            def _open_browser(url: str):
                """打开浏览器：优先直接启动浏览器可执行文件（不依赖注册表关联），再退回系统关联"""
                if sys.platform != "win32":
                    try:
                        subprocess.Popen(["xdg-open", url],
                                         stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
                        _logger.info("已通过 xdg-open 请求打开页面: %s", url)
                    except Exception as e:
                        _logger.warning("打开浏览器失败: %s，请手动访问 %s", e, url)
                    return

                exe, browser = _find_browser_exe()
                if exe:
                    try:
                        # 保证每次都是新窗口，且不依赖注册表关联
                        args = [exe, "-new-window", url] if browser == "firefox" else [exe, "--new-window", url]
                        subprocess.Popen(args, close_fds=True)
                        _logger.info("已用浏览器新窗口打开页面: %s (%s, 配置=%s, 系统默认=%s)",
                                     url, os.path.basename(exe), _configured_browser(),
                                     _default_browser_hint() or "未知")
                        return
                    except Exception as e:
                        _logger.warning("直接启动浏览器失败(%s)，改用系统关联", e)
                try:
                    os.startfile(url)  # noqa: S606  ShellExecute，走默认浏览器
                    _logger.info("已通过默认浏览器打开页面: %s", url)
                    return
                except Exception as e:
                    _logger.warning("默认浏览器打开失败(%s)，尝试 cmd start", e)
                try:
                    subprocess.Popen(["cmd", "/c", "start", "", url])
                    _logger.info("已通过 cmd start 请求打开页面: %s", url)
                except Exception as e2:
                    _logger.warning("打开浏览器失败: %s，请手动访问 %s", e2, url)

            threading.Timer(0.5, lambda: _open_browser(_open_url)).start()
            try:
                with open(_flag, "w") as f:
                    f.write("1")
            except Exception:
                pass

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
