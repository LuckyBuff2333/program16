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
from src.api.routes import observability as observability_router
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
        observability_router,
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

            def _cfg_browser() -> str:
                """config.web.browser：auto(默认)/chrome/edge/firefox/system"""
                try:
                    from src.config import load_config
                    return str((load_config().get("web") or {}).get("browser", "auto")).strip().lower()
                except Exception:
                    return "auto"

            def _user_choice_progid() -> str:
                """读取系统默认浏览器的 ProgId（http 协议）"""
                try:
                    import winreg
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
                    ) as k:
                        return str(winreg.QueryValueEx(k, "ProgId")[0] or "")
                except Exception:
                    return ""

            def _progid_exe(prog_id: str) -> str:
                r"""从 ProgId 的 shell\open\command 解析出浏览器可执行文件路径"""
                try:
                    import winreg
                except Exception:
                    return ""
                for root, sub in (
                    (winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command"),
                    (winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog_id}\shell\open\command"),
                    (winreg.HKEY_LOCAL_MACHINE, rf"Software\Classes\{prog_id}\shell\open\command"),
                ):
                    try:
                        with winreg.OpenKey(root, sub) as k:
                            cmd = str(winreg.QueryValueEx(k, "")[0] or "")
                    except Exception:
                        continue
                    exe = cmd[1:cmd.find('"', 1)] if cmd.startswith('"') else cmd.split(" ")[0]
                    if exe and os.path.isfile(exe):
                        return exe
                return ""

            def _known_exe(name: str) -> str:
                rels = {
                    "chrome": r"Google\Chrome\Application\chrome.exe",
                    "edge": r"Microsoft\Edge\Application\msedge.exe",
                    "msedge": r"Microsoft\Edge\Application\msedge.exe",
                    "firefox": r"Mozilla Firefox\firefox.exe",
                }
                rel = rels.get(name, "")
                if not rel:
                    return ""
                for root in (
                    os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                    os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                    os.environ.get("LOCALAPPDATA", ""),
                ):
                    if root:
                        path = os.path.join(root, rel)
                        if os.path.isfile(path):
                            return path
                return ""

            def _pick_browser():
                """返回 (exe, 说明)；("","") 表示交给系统关联"""
                mode = _cfg_browser()
                if mode == "system":
                    return "", ""
                if mode in ("chrome", "edge", "msedge", "firefox"):
                    exe = _known_exe(mode)
                    return (exe, f"配置={mode}") if exe else ("", "")
                prog_id = _user_choice_progid()
                if prog_id:
                    exe = _progid_exe(prog_id)
                    if exe:
                        return exe, f"系统默认={prog_id}"
                for name in ("chrome", "edge", "firefox"):
                    exe = _known_exe(name)
                    if exe:
                        return exe, f"默认不可用，回退={name}"
                return "", ""

            def _launch_args(exe: str, url: str):
                name = os.path.basename(exe).lower()
                if "firefox" in name:
                    return [exe, "-new-window", url]
                if any(k in name for k in ("chrome", "msedge", "chromium", "brave", "opera")):
                    return [exe, "--new-window", url]
                return [exe, url]

            def _is_elevated() -> bool:
                """当前进程是否以管理员（High 完整性）运行"""
                try:
                    import ctypes
                    return bool(ctypes.windll.shell32.IsUserAnAdmin())
                except Exception:
                    return False

            def _open_browser(url: str):
                """打开浏览器：直接用系统默认浏览器的可执行文件开新窗口，失败逐级回退"""
                if sys.platform != "win32":
                    try:
                        subprocess.Popen(["xdg-open", url],
                                         stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
                        _logger.info("已通过 xdg-open 请求打开页面: %s", url)
                    except Exception as e:
                        _logger.warning("打开浏览器失败: %s，请手动访问 %s", e, url)
                    return
                if _is_elevated():
                    # 管理员进程直接起 chrome/edge 时，会和桌面普通权限的浏览器实例冲突（静默无窗口），
                    # 交给 explorer（桌面 shell，中等权限）打开更可靠
                    try:
                        subprocess.Popen(["explorer.exe", url])
                        _logger.info("当前为管理员权限，已通过桌面 shell 打开默认浏览器: %s", url)
                        return
                    except Exception as e:
                        _logger.warning("explorer 打开失败: %s，尝试直接启动浏览器", e)
                exe, why = _pick_browser()
                if exe:
                    try:
                        subprocess.Popen(_launch_args(exe, url), close_fds=True)
                        _logger.info("已用浏览器打开页面: %s (%s, %s)", url, os.path.basename(exe), why)
                        return
                    except Exception as e:
                        _logger.warning("直接启动浏览器失败(%s)，改用系统关联", e)
                try:
                    os.startfile(url)  # noqa: S606  ShellExecute
                    _logger.info("已通过系统关联打开页面: %s", url)
                    return
                except Exception as e:
                    _logger.warning("系统关联打开失败: %s，尝试 cmd start", e)
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

    # 后台预热看板缓存：冷启动首次计算要 60~90 秒（主表 6000+ 条 + CSV），
    # 提前算好，用户打开「数据看板」时直接命中缓存
    def _warm_dashboard_cache():
        import time as _time
        from datetime import datetime
        _time.sleep(8)
        try:
            from src.api.routes.report import _dashboard_data_sync, _dashboard_dates_sync
            _dashboard_data_sync(datetime.now().strftime("%Y-%m-%d"))
            try:
                _dashboard_dates_sync()
            except Exception as _e2:
                _logger.warning("看板日期列表预热失败: %s", _e2)
            _logger.info("看板缓存预热完成（今天 + 日期列表）")
        except Exception as _e:
            _logger.warning("看板缓存预热失败（不影响主服务）: %s", _e)

    try:
        threading.Thread(target=_warm_dashboard_cache, name="dashboard-warmup", daemon=True).start()
    except Exception as _e:
        _logger.warning("看板预热线程启动失败: %s", _e)

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
