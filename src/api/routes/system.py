"""系统管理路由：配置读写、服务控制、概览"""
import asyncio
import os
import signal
import subprocess
import sys
import tempfile

import yaml
from fastapi import APIRouter, Request

from src import config as cfg_module
from src.config import get_path, load_config, setup_logger, PROJECT_ROOT
from src.api.routes.shared import ok, fail, read_csv_rows
from src.schemas.common import ApiResponse
from src.schemas.misc import GitPullRequest

logger = setup_logger("web.system")
router = APIRouter()


@router.post("/api/shutdown", response_model=ApiResponse)
async def shutdown_server():
    """优雅关闭服务：发送 Ctrl+C 信号让整个进程组正常退出"""
    logger.info("收到关闭请求，正在优雅退出...")
    _flag = os.path.join(tempfile.gettempdir(), ".web_browser_opened")
    try:
        if os.path.exists(_flag):
            os.remove(_flag)
    except Exception:
        pass

    def _do_shutdown():
        if os.name == "nt":
            os.kill(0, signal.CTRL_C_EVENT)
        else:
            os.kill(os.getpid(), signal.SIGINT)

    loop = asyncio.get_event_loop()
    loop.call_later(0.3, _do_shutdown)
    return ok(message="服务正在关闭...")


@router.post("/api/restart", response_model=ApiResponse)
async def restart_server():
    """重启 worker：只终止当前 worker，reloader 会自动拉起新 worker 加载最新代码"""
    logger.info("收到重启请求，终止 worker 让 reloader 自动重启...")
    loop = asyncio.get_event_loop()
    loop.call_later(0.3, lambda: sys.exit(0))
    return ok(message="worker 正在终止，reloader 将自动重启...")


@router.post("/api/system/git_pull", response_model=ApiResponse)
async def git_pull_and_restart(req: GitPullRequest):
    """远程拉取最新代码并可选重启服务"""
    token = ""
    do_restart = req.restart
    cfg = load_config()
    expected_token = cfg.get("deploy_token", "program16")
    if token != expected_token:
        return fail("安全令牌不匹配")
    logger.info("收到远程更新请求，执行 git pull...")
    try:
        result = subprocess.run(
            ["git", "pull", "origin", "master"],
            capture_output=True, text=True, timeout=60,
            cwd=PROJECT_ROOT
        )
        output = result.stdout.strip()
        err = result.stderr.strip()
        success = result.returncode == 0
        if success:
            already_up = "Already up to date" in output or "already up to date" in output
            msg = "代码已是最新" if already_up else "代码更新成功"
            logger.info("git pull 成功: %s", output[:200])
        else:
            msg = f"git pull 失败: {err[:200]}"
            logger.warning("git pull 失败: %s", err[:200])
        resp_data = {"output": output[:500], "error": err[:500], "success": success}
        if success and do_restart and not already_up:
            resp_data["restarting"] = True
            msg += "\n服务正在重启..."
            loop = asyncio.get_event_loop()
            loop.call_later(1.0, lambda: __import__("sys").exit(0))
        return ok(resp_data, msg)
    except subprocess.TimeoutExpired:
        return fail("git pull 超时（60秒）")
    except Exception as e:
        return fail(f"git pull 异常: {str(e)[:200]}")


@router.get("/api/config", response_model=ApiResponse)
def get_config():
    """读取当前全局配置（过滤敏感字段）"""
    cfg = load_config()
    # 过滤敏感配置段，前端不应看到服务器内部地址
    _SENSITIVE_KEYS = {"app_log_server"}
    safe_cfg = {k: v for k, v in cfg.items() if k not in _SENSITIVE_KEYS}
    return ok(safe_cfg)


@router.post("/api/config", response_model=ApiResponse)
async def save_config(request: Request):
    """更新配置：按配置段合并前端提交项并写回 config.yaml"""
    try:
        updates = await request.json() or {}
        cfg = load_config()
        for section, values in updates.items():
            if isinstance(values, dict) and isinstance(cfg.get(section), dict):
                cfg[section].update(values)
        with open(cfg_module.CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        load_config(cfg_module.CONFIG_PATH)
        logger.info("配置已由页面更新: %s", list(updates.keys()))
        return ok(message="配置保存成功")
    except Exception as e:
        logger.error("配置保存失败: %s", e)
        return fail(str(e))


@router.get("/api/overview", response_model=ApiResponse)
def overview():
    """首页概览：统计指标与接口模式状态"""
    from datetime import datetime
    cfg = load_config()
    daily = read_csv_rows(
        os.path.join(get_path("doc_dir"),
                     datetime.now().strftime("%Y-%m-%d"),
                     f"{datetime.now().strftime('%Y-%m-%d')}_daily.csv")
    )
    audited = read_csv_rows(os.path.join(get_path("report_dir"), cfg["audit"]["audited_file"]))
    supplement_fields = ["分析问题时间", "AI分析结果(飞书链接)", "AI评论总结", "rootcause", "结果置信度"]
    complete_count = sum(1 for r in daily if all(
        (r.get(f) or "").strip() not in ("", "-", "None") for f in supplement_fields))
    data = {
        "today": datetime.now().strftime("%Y-%m-%d"),
        "mock": {
            "ai_log": bool(cfg["ai_log_api"].get("mock")),
            "jira": bool(cfg["jira_api"].get("mock")),
            "kb": bool(cfg["knowledge_base_api"].get("mock")),
        },
        "daily_total": len(daily),
        "daily_complete": complete_count,
        "daily_incomplete": len(daily) - complete_count,
        "audited_total": len(audited),
    }
    return ok(data)


@router.get("/api/applog/download")
async def download_app_log(source: str = "pc"):
    """代理下载远程服务器 app.log，source=pc|online"""
    import httpx
    cfg_all = load_config().get("app_log_server", {})
    # 兼容旧配置：如果没有 pc/online 分层，直接用默认值
    if source not in cfg_all and "host" in cfg_all:
        cfg = cfg_all
    else:
        cfg = cfg_all.get(source, cfg_all.get("pc", {}))
    host = cfg.get("host", "10.22.126.133")
    port = cfg.get("port", 8001)
    endpoint = cfg.get("endpoint", "/api/logs/download")
    url = f"http://{host}:{port}{endpoint}"
    # 保存路径：项目根目录/logs/app_{source}.log
    logs_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    filename = "app.log" if source == "pc" else f"app_{source}.log"
    save_path = os.path.join(logs_dir, filename)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        # 写入本地文件
        with open(save_path, "wb") as f:
            f.write(resp.content)
        size_mb = len(resp.content) / 1024 / 1024
        label = "PC" if source == "pc" else "线上"
        logger.info("[%s] app.log 已下载到 %s (%.2f MB)", label, save_path, size_mb)
        return ok({"path": save_path, "size_mb": round(size_mb, 2)}, f"{label} 下载成功")
    except httpx.ConnectError:
        return fail(f"无法连接{source}服务器 {host}:{port}，请检查网络或服务器状态")
    except httpx.TimeoutException:
        return fail("下载超时（120秒），文件可能过大或网络不稳定")
    except Exception as e:
        logger.error("app.log 下载失败: %s", e)
        return fail(f"下载失败: {str(e)[:200]}")


@router.post("/api/applog/open_folder")
async def open_app_log_folder():
    """打开 app.log 所在目录"""
    logs_dir = os.path.join(PROJECT_ROOT, "logs")
    if not os.path.isdir(logs_dir):
        return fail("logs 目录不存在")
    try:
        if os.name == "nt":
            os.startfile(logs_dir)
        else:
            subprocess.Popen(["xdg-open", logs_dir])
        return ok(message="已打开目录")
    except Exception as e:
        return fail(f"打开目录失败: {e}")
